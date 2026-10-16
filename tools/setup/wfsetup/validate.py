"""Source validation: every problem of the clone's sources, at once.

``render`` and ``doctor`` run this before anything else. Nothing is written,
nothing is executed and no validated script is imported: a Python script is
read through its syntax tree, a Node script and every text through patterns.

    check(where)    -> Report     every problem; never raises for a faulty source
    require(where)  -> Report     the same, or a SetupError of one line per problem

A ``Report`` holds the problems in a fixed order, the skills that could be
read (name, providers, invoke-only), the size of each role's full text and,
for each role that can be loaded, the size of the skill each provider is given.
A ``Problem`` has a file (relative to the clone, with forward slashes), a
line or a key where it has one, a rule id and a message. The rule ids are
stable and are listed in ``RULES``.

What is validated: the skills (a directory at the clone's root that holds
``SKILL.md``), ``rules/``, ``roles/``, ``providers/`` and
``tools/setup/defaults.toml``. A skill named in ``OWN_SETUP`` has a setup of
its own and is checked for its frontmatter only.

What ``render`` would refuse of the sources, this reports first: a name
too long for a file's name, a Windows device name, two names that differ
only in letter case, a loaded role named as a skill, a carriage return of
its own or a line that reads as one of setup's markers in a text ``render``
embeds, a control character in a single-line field.

What cannot be checked from the text, and is not claimed:

    - A path a script computes (``Path(__file__).parents[2]``, the user's
      home, an argument) is not followed. Only a literal with ``..`` segments
      that leaves the skill is found, and a literal machine path. So the one
      allowed reach outside a skill, the setup tool beside it, needs no
      exception here: the launchers compute it.
    - An import made by name at run time (``importlib.import_module(name)``,
      ``require(name)``) is not seen. The standard-library list is the one of
      the interpreter that runs the validator.
    - A Node script is read with patterns, not parsed: an ``import`` written
      in a comment or a string counts as one.
"""
from __future__ import annotations

import ast
import dataclasses
import fnmatch
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import definitions, dictionary, entry, paths, roles, schema, tomlio
from .errors import SetupError
from .locations import Locations

# --- The rules ---------------------------------------------------------------

RULES: dict[str, str] = {
    "source-unreadable": "a file or directory of the sources cannot be read, or is not a regular file",
    "file-too-large": "a source file is larger than the validator reads",
    "symlink": "a link inside a skill, a role, a rule or a provider directory; no link is committed",
    "skill-file": "SKILL.md is not a UTF-8 text file",
    "skill-frontmatter": "the frontmatter is not plain `key: value` lines between two --- lines",
    "skill-name": "`name` is missing or is not the directory's name",
    "skill-description": "`description` is missing or empty",
    "skill-compatibility": "the `compatibility` line is missing or does not follow the grammar (R2.3)",
    "skill-invoke-only": "invoke-only is declared for one provider and not the other, or cannot be read",
    "script-syntax": "a Python script of a skill does not parse, so its imports cannot be checked",
    "script-import": "a skill's script imports what is neither standard library nor a file of the skill (R2.5)",
    "script-path": "a skill's script holds a literal path that leaves the skill (R2.5)",
    "machine-path": "an installed text holds an absolute path of one machine (R6.10)",
    "not-text": "a file of an installed unit is not UTF-8 text, and .gitattributes does not declare its type binary",
    "id-characters": "a skill's or a rule's directory name is not lower-case letters, digits and single hyphens",
    "id-length": "a skill, rule, role or definition id is longer than a file name made from it may be",
    "id-device-name": "a skill, rule or role id is a device name of Windows (con, nul, aux, com1, ...)",
    "id-case": "two skills, two rules or two roles differ only in letter case, which Windows cannot hold apart",
    "role-skill-name": "a role that is loaded as a skill has the name of a skill",
    "field-control": "a single-line field holds a control character, a line break or a direction override",
    "field-length": "a single-line field is longer than its limit",
    "text-carriage-return": "a text render embeds holds a carriage return that is not part of a CRLF line end",
    "text-marker": "a text render embeds holds a line that reads as one of setup's block markers",
    "provider-actions-size": "a provider's actions.md is larger than its limit",
    "provider-name": "shared text names a provider's tool or uses a provider's substitution (R2.4)",
    "role-toml": "role.toml: a key, a type or a value is not the format of roles/README.md",
    "role-text": "ROLE.md is missing or is not UTF-8 text",
    "role-include": "an entry of `includes` is not a file in roles/_shared/",
    "role-actions": "an entry of `actions` is not a section of every provider's actions.md",
    "role-size": "ROLE.md with its includes reaches the size limit",
    "loaded-skill-size": "the skill a loaded role is given on a provider is over that provider's token limit",
    "role-dispatch": "an entry of `limits.dispatches` is not a role definition",
    "role-reserved": "a role definition's id is a scalar key of Codex's [agents] table",
    "bindings": "roles/bindings.toml: a key, a name that does not exist, a row given twice, or a skill that is "
                "not installed for a provider the row's role is made for",
    "stage-unbound": "a stage file of a process skill has no row in roles/bindings.toml",
    "provider-actions": "a provider directory has no readable actions.md",
    "dictionary": "a provider's dictionary.toml fails its schema",
    "defaults": "tools/setup/defaults.toml fails the settings schema",
    "launcher-identical": "the scripts/settings.py launchers of the skills differ",
    "launcher-defaults": "a script's built-in defaults differ from tools/setup/defaults.toml",
}

# --- What is read ------------------------------------------------------------

SKILL_FILE = "SKILL.md"
OPENAI_FILE = ("agents", "openai.yaml")
ACTIONS_FILE = "actions.md"
BINDINGS_FILE = "bindings.toml"
BINDINGS_VERSION = 1
NOTE_LIMIT = 200

# An id becomes a file's and a directory's name in every home
# (``<id>-hard.toml``, ``<id>.config.toml``, a temporary name beside it), and
# a provider's own limit on a skill's name is of this order.
ID_LIMIT = 64
# The single-line fields ``render`` writes into a definition's head.
TITLE_LIMIT = 80
DESCRIPTION_LIMIT = 400
FIELD_LIMIT = 200          # any other string of a role, a binding or a dictionary
# A provider's action notes end every definition and every loaded role.
ACTIONS_LIMIT = 12_000
# The skill of a role that can be loaded is limited, as ``entry`` estimates
# its tokens, on a provider whose dictionary says what it keeps of an
# invoked skill after a compaction (``skills.compaction_tokens``; Claude
# Code). A provider whose dictionary does not say has no limit: the size is
# reported (decision of 2026-10-16).
# The home the skills are measured with: a place inside the clone that
# holds no settings file, so the shipped settings alone decide the
# profile, and a source's validity does not depend on the user's.
NO_HOME = ("tools", "setup", ".no-home")

# The names Windows keeps for devices, whatever follows a dot after them.
DEVICE_NAMES = frozenset(
    ("con", "prn", "aux", "nul", *[f"com{digit}" for digit in "123456789"], *[f"lpt{digit}" for digit in "123456789"])
)

# What no single-line field holds: the C0 and C1 controls (tab, CR, LF and
# NEL among them), the line and paragraph separators, the direction marks
# and overrides, and the byte order mark.
_DIRECTION = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff")


def is_control(char: str) -> bool:
    code = ord(char)
    return code < 0x20 or 0x7F <= code <= 0x9F or char in "\u2028\u2029" or char in _DIRECTION


# A line that ``blocks`` would read as a marker, in either comment syntax.
MARKER_LINE = re.compile(
    r"[ \t]*(?:<!--[ \t]*workflow-setup:(?:start|end)(?:[ \t]+\S+?)?[ \t]*-->"
    r"|#[ \t]*workflow-setup:(?:start|end)(?:[ \t]+\S+)?)[ \t]*"
)
GITATTRIBUTES = ".gitattributes"

# A skill with a setup of its own (R1.2): its frontmatter is checked, since
# that decides nothing but where the skill may be installed, and nothing
# else in it is this tool's to judge.
OWN_SETUP = ("multiagent-collab",)

# No source file comes near this. A larger one is reported and not read.
MAX_FILE_BYTES = 2 * 1024 * 1024

# Left out of every walk: the interpreter's own cache, which git ignores and
# which holds the paths of the machine that wrote it.
SKIPPED_DIRECTORIES = ("__pycache__",)

PROVIDERS = ("claude-code", "codex")
COMPATIBILITY_KEY = "compatibility"
DESCRIPTION_KEY = "description"
# The grammar of AGENTS.md, "Skills", matched on the raw line after the key.
COMPATIBILITY = re.compile(r"^(claude-code|codex|claude-code, codex)( \([^()#:]+\))?$")
INVOKE_KEY = "disable-model-invocation"
IMPLICIT_KEY = "allow_implicit_invocation"

# --- R2.4: what shared text does not name ------------------------------------
#
# Built from providers/*/actions.md and the conventions of AGENTS.md, and
# kept here and nowhere else. A tool whose name is an English word (Agent,
# Bash, Edit, Write, Read, Task, Skill) is not listed by name, because prose
# uses the word; it is caught only where the text calls it a tool
# (``_TOOL_PHRASE``). Names that a script could use for a variable of its
# own (task_name, name, prompt, target) are left out as well.
PROVIDER_TERMS: dict[str, tuple[str, ...]] = {
    "claude-code": (
        "AskUserQuestion", "SendMessage", "subagent_type",  # named in actions.md and the conventions
        "NotebookEdit", "TodoWrite", "ExitPlanMode", "EnterPlanMode", "WebFetch", "WebSearch",
    ),
    "codex": (
        "spawn_agent", "wait_agent", "followup_task", "fork_turns", "agent_type",  # named in actions.md
        "close_agent", "resume_agent", "apply_patch", "request_user_input",
    ),
}
_TERM = re.compile(
    r"(?<![A-Za-z0-9_])(?:%s)(?![A-Za-z0-9_])"
    % "|".join(re.escape(term) for terms in PROVIDER_TERMS.values() for term in terms)
)
# ${CLAUDE_SKILL_DIR}, $CLAUDE_PROJECT_DIR, $CODEX_HOME, $ARGUMENTS.
_SUBSTITUTION = re.compile(r"\$\{?(?:(?:CLAUDE|CODEX)_[A-Z0-9_]+|ARGUMENTS(?![A-Za-z0-9_]))\}?")
_TOOL_PHRASE = re.compile(r"(?<![A-Za-z0-9_])`?(?:Agent|Bash|Edit|Write|Read|Glob|Grep|Task|Skill)`? tool\b")
# Under a skill, the files that are one provider's own by the conventions.
PROVIDER_FILES = ("references/claude-code.md", "references/codex.md", "/".join(OPENAI_FILE))

# The stage files, which the binding table gives a role each (``stage_files``).
REFERENCES_DIR = "references"
STAGE_FILE = "stage-*.md"       # one such file makes a skill a process skill
STAGE_SUFFIX = ".md"
# In ``references/`` and no stage: the conventions hold in every stage and
# are read through each stage file, and a provider's file says how an action
# is done there, not who does it.
NOT_A_STAGE = frozenset(
    {"conventions.md"} | {name.split("/", 1)[1] for name in PROVIDER_FILES if name.startswith(REFERENCES_DIR + "/")}
)

# --- R6.10: the path of one machine ------------------------------------------
#
# Each pattern needs a real name where a machine path has one: the first
# character after the root is a letter, a digit or an underscore, of any
# script (a user name need not be ASCII). A placeholder (<user>, $USER,
# {user}, *, \w) therefore does not match, and neither do these patterns'
# own source text nor a path that merely holds such a segment further in
# (docs/home/x, https://host/home/x).
_NAME = r"\w[\w.-]*"
_NAME2 = r"\w[\w.-]+"   # a name of two characters or more
_NOT_INSIDE = r"(?<![\w.~-])"
_WSL_HOST = r"wsl(?:\.localhost|\$)"
MACHINE_PATHS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a home directory", re.compile(_NOT_INSIDE + r"/(?:home|Users)/" + _NAME)),
    # Two names: /root/<one name> is how Codex writes the task path of a
    # dispatched agent (providers/codex/actions.md names one), and a path
    # in the root user's home that is worth a rule has a file below it.
    ("the root user's home directory", re.compile(_NOT_INSIDE + r"/root/" + _NAME + "/" + _NAME)),
    ("a mounted drive", re.compile(_NOT_INSIDE + r"/mnt/[A-Za-z](?![\w.-])")),
    # A Windows drive as Git Bash, MSYS and Cygwin write it: /c/Users/<name>,
    # /cygdrive/c. A lone /c/ is too short to tell from any path.
    ("a drive, in the form of a Unix shell on Windows",
     re.compile(_NOT_INSIDE + r"/(?:[A-Za-z]/(?:Users|home)/" + _NAME + r"|cygdrive/[A-Za-z](?![\w.-]))")),
    # One letter, a colon, then a slash or one or more backslashes (source
    # code doubles them) and a name. A URL scheme has more than one letter,
    # so https:// is not one.
    ("a drive letter", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\+|/)" + _NAME)),
    ("a WSL share", re.compile(r"(?:\\\\+" + _WSL_HOST + r"\\+|(?<![\w:/])//" + _WSL_HOST + "/)" + _NAME)),
    # A share on another machine, as Windows writes it: two backslashes, a
    # host, one backslash, a share; or the same with every backslash doubled,
    # as source code writes it. Exactly that many, and names of two
    # characters or more: an escaped line feed after a backslash in a
    # script is no path.
    ("a network share", re.compile(
        r"(?<![\\\w])(?:\\{2}(?!\\)(?!" + _WSL_HOST + r")" + _NAME2 + r"\\(?!\\)" + _NAME2
        + r"|\\{4}(?!\\)(?!" + _WSL_HOST + r")" + _NAME2 + r"\\{2}(?!\\)" + _NAME2 + ")"
    )),
)

# --- R2.5 --------------------------------------------------------------------

NODE_SUFFIXES = (".mjs", ".js", ".cjs")
NODE_BUILTINS = frozenset((
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants", "crypto",
    "dgram", "diagnostics_channel", "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks", "process", "punycode", "querystring",
    "readline", "repl", "stream", "string_decoder", "sys", "timers", "tls", "trace_events", "tty",
    "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
))
_NODE_IMPORTS = (
    re.compile(r"""(?m)^[ \t]*(?:import|export)\b[^;'"`]*?\bfrom\s*["']([^"'\n]+)["']"""),
    re.compile(r"""(?m)^[ \t]*import\s*["']([^"'\n]+)["']"""),
    re.compile(r"""\b(?:import|require)\s*\(\s*["']([^"'\n]+)["']\s*\)"""),
)
_NODE_RELATIVE = re.compile(r"""(["'`])(\.{1,2}/[^"'`\s]*)\1""")

# --- Codex's reserved names ----------------------------------------------------
#
# "Scalar setting names are reserved and can't be used as custom role names":
# the row `agents` of the Codex config reference,
# https://learn.chatgpt.com/docs/config-file/config-reference, read on
# 2026-10-05. These are the scalar keys it lists under `agents.`.
CODEX_AGENTS_KEYS = (
    "default_subagent_model",
    "default_subagent_reasoning_effort",
    "enabled",
    "interrupt_message",
    "max_concurrent_threads_per_session",
    "max_threads",
)
# Not on that page on that day, so unverified: keys of earlier Codex
# versions. Refusing them costs a role id nobody wants and guards against a
# client that still reads them.
CODEX_AGENTS_KEYS_UNVERIFIED = ("max_depth", "job_max_runtime_seconds")
RESERVED_IDS = frozenset(CODEX_AGENTS_KEYS + CODEX_AGENTS_KEYS_UNVERIFIED)

# --- The launchers -------------------------------------------------------------

BUILT_IN_NAME = "BUILT_IN"
LAUNCHER = "settings.py"
# A script of a skill that carries a copy of shipped defaults, and the
# groups of tools/setup/defaults.toml its copy must equal.
BUILT_IN_GROUPS: dict[str, tuple[str, ...]] = {
    LAUNCHER: ("process", "memory", "roles"),
    "check.py": ("process",),
}

_PART = re.compile(r"[a-z]+(?:-[a-z]+)*")
_KEYED = re.compile(r'((?:[A-Za-z0-9_-]+|"[^"]*")(?:\.(?:[A-Za-z0-9_-]+|"[^"]*"))*(?:\[[0-9]+\])?): (.+)', re.S)
_REPARSE_LINKS = (0xA000000C, 0xA0000003, paths.WSL_LINK_TAG)  # a Windows symlink, a junction, a link made in WSL


# --- The result ----------------------------------------------------------------

@dataclass(frozen=True)
class Problem:
    """One fault. ``file`` is relative to the clone, with forward slashes;
    ``line`` and ``key`` are None where the fault has no such place."""

    file: str
    rule: str
    message: str
    line: int | None = None
    key: str | None = None

    def text(self) -> str:
        place = self.file if self.line is None else f"{self.file}:{self.line}"
        key = "" if self.key is None else f"{self.key}: "
        return f"{place}: [{self.rule}] {key}{self.message}"

    def as_json(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "key": self.key, "rule": self.rule, "message": self.message}

    def _order(self) -> tuple[Any, ...]:
        return (self.file, self.line or 0, self.rule, self.key or "", self.message)


@dataclass(frozen=True)
class Skill:
    """A skill whose frontmatter could be read. ``providers`` is empty when
    its compatibility line is at fault."""

    name: str
    providers: tuple[str, ...]
    invoke_only: bool
    own_setup: bool


# The version of the --json output. 2: "loaded" lost its one "limit_tokens";
# each provider's entry under it gives its own, null where it has none.
JSON_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Report:
    problems: tuple[Problem, ...]
    skills: dict[str, Skill]
    role_sizes: dict[str, int]
    # By role and provider: the bytes and estimated tokens of its loaded skill,
    # and the provider's limit (None where it has none).
    loaded_sizes: dict[str, dict[str, dict[str, int | None]]] = dataclasses.field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems

    def lines(self) -> list[str]:
        return [problem.text() for problem in self.problems]

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": JSON_SCHEMA_VERSION,
            "ok": self.ok,
            "problems": [problem.as_json() for problem in self.problems],
            "skills": {
                name: {"providers": list(skill.providers), "invoke_only": skill.invoke_only, "own_setup": skill.own_setup}
                for name, skill in self.skills.items()
            },
            "roles": {name: {"bytes": size, "limit": roles.TEXT_LIMIT} for name, size in self.role_sizes.items()},
            "loaded": {"roles": self.loaded_sizes},
        }


def check(where: Locations) -> Report:
    """Every problem of the sources of ``where.clone``. A faulty source is a
    problem, never an exception; only a clone that is not there at all is a
    ``SetupError``."""
    if paths.kind(where.clone) != paths.DIRECTORY:
        raise SetupError(f"{where.clone}: not a directory; the clone to validate is not there")
    run = _Run(where)
    for step in (_find_skills, _check_skills, _check_ids, _check_scripts, _check_texts, _check_roles,
                 _check_embedded, _check_bindings, _check_providers, _check_defaults, _check_launchers,
                 _check_not_text, _check_loaded):
        try:
            step(run)
        except SetupError as exc:
            for line in exc.lines:
                run.add(where.clone, "source-unreadable", run.shorten(line))
        except OSError as exc:
            target = where.clone if exc.filename is None else Path(str(exc.filename))
            run.add(target, "source-unreadable", f"cannot be read: {paths.reason(exc)}")
        except RecursionError:
            run.add(where.clone, "source-unreadable", "a source is nested too deeply to read")
    problems = tuple(sorted(run.found, key=Problem._order))
    return Report(problems, dict(sorted(run.report_skills.items())), dict(sorted(run.sizes.items())),
                  dict(sorted(run.loaded.items())))


def require(where: Locations) -> Report:
    """``check``, for a caller that goes on only when the sources are valid:
    any problem is a ``SetupError`` with one line per problem."""
    report = check(where)
    if not report.ok:
        raise SetupError(*report.lines())
    return report


# --- Reading, with every failure a problem -------------------------------------

@dataclass
class _Source:
    """A skill directory as found, before anything in it is trusted."""

    name: str
    directory: Path
    providers: tuple[str, ...] | None = None  # None: the line could not be read


class _Run:
    def __init__(self, where: Locations) -> None:
        self.where = where
        self.clone = where.clone
        self.found: set[Problem] = set()
        self.skills: dict[str, _Source] = {}
        self.report_skills: dict[str, Skill] = {}
        self.sizes: dict[str, int] = {}
        self.loaded: dict[str, dict[str, dict[str, int | None]]] = {}
        self.defaults: dict[str, Any] | None = None
        self.installed: list[Path] = []   # every file of an installed unit
        self._bytes: dict[Path, bytes | None] = {}
        self._walks: dict[Path, list[Path]] = {}

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.clone).as_posix() or "."
        except ValueError:
            return str(path)

    def shorten(self, line: str) -> str:
        """A loader's line with the clone's own path taken out of it."""
        return line.replace(str(self.clone) + os.sep, "").replace(str(self.clone), ".")

    def add(self, path: Path, rule: str, message: str, line: int | None = None, key: str | None = None) -> None:
        # One line a problem, and nothing in it that a terminal would act on.
        self.found.add(Problem(
            printable(self.rel(path)), rule, printable(" ".join(message.split())), line,
            None if key is None else printable(key),
        ))

    def field(self, file: Path, key: str, value: Any, limit: int = FIELD_LIMIT) -> None:
        """A single-line field: no control character, no marker, and no
        longer than ``limit`` characters. Anything but a string is the
        format check's to report."""
        if not isinstance(value, str):
            return
        bad = sorted({ord(char) for char in value if is_control(char)})
        if bad:
            self.add(file, "field-control", "holds " + ", ".join(f"U+{code:04X}" for code in bad[:5])
                     + (" and more" if len(bad) > 5 else "")
                     + ": a control character, a line break or a direction override; a single-line field holds none",
                     key=key)
        if len(value) > limit:
            self.add(file, "field-length", f"{len(value):,} characters; at most {limit}", key=key)
        if MARKER_LINE.fullmatch(value):
            self.add(file, "text-marker", "reads as one of setup's block markers (workflow-setup:start or :end), "
                                          "and would end or open a block where render embeds it", key=key)

    def loader(self, file: Path, rule: str, lines: list[str]) -> None:
        """Problems from the lines a loader gave: ``<file>: <key>: <text>``."""
        prefix = f"{file}: "
        for line in lines:
            rest = line[len(prefix):] if line.startswith(prefix) else self.shorten(line)
            keyed = _KEYED.fullmatch(rest)
            if keyed:
                self.add(file, rule, self.shorten(keyed.group(2)), key=keyed.group(1))
            else:
                self.add(file, rule, self.shorten(rest))

    def read(self, path: Path) -> bytes | None:
        """The bytes of a regular file, or None with a problem recorded once."""
        if path in self._bytes:
            return self._bytes[path]
        data: bytes | None = None
        try:
            found = os.stat(path)
            if not stat.S_ISREG(found.st_mode):
                self.add(path, "source-unreadable", "is not a regular file")
            elif found.st_size > MAX_FILE_BYTES:
                self.add(path, "file-too-large", f"{found.st_size:,} bytes; at most {MAX_FILE_BYTES:,} are read")
            else:
                with open(path, "rb") as handle:
                    data = handle.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    self.add(path, "file-too-large", f"more than {MAX_FILE_BYTES:,} bytes; no more are read")
                    data = None
        except (OSError, ValueError) as exc:
            self.add(path, "source-unreadable", f"cannot be read: {paths.reason(exc)}")
        self._bytes[path] = data
        return data

    def text(self, path: Path) -> str | None:
        """The file as text, or None when it could not be read or is not
        UTF-8 text. Only the first is a problem here: a binary file is not
        text, and the caller that needs text says so (``need``)."""
        data = self.read(path)
        if data is None or b"\0" in data:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def need(self, path: Path, rule: str) -> str | None:
        """``text``, for a file that must be text."""
        text = self.text(path)
        if text is None and self._bytes.get(path) is not None:
            self.add(path, rule, "is not UTF-8 text")
        return text

    def walk(self, top: Path) -> list[Path]:
        """The regular files under ``top``, in a fixed order. A link is a
        problem and is not followed, so a loop of links cannot be entered;
        what is neither a file nor a directory is a problem too."""
        if top in self._walks:
            return self._walks[top]
        files: list[Path] = []
        pending = [top]
        while pending:
            directory = pending.pop()
            try:
                names = sorted(os.listdir(directory))
            except OSError as exc:
                self.add(directory, "source-unreadable", f"cannot be read: {paths.reason(exc)}")
                continue
            below: list[Path] = []
            for name in names:
                path = directory / name
                try:
                    found = os.lstat(path)
                except (OSError, ValueError) as exc:
                    self.add(path, "source-unreadable", f"cannot be read: {paths.reason(exc)}")
                    continue
                if is_link(found):
                    self.add(path, "symlink", "is a link; no link is committed, and Codex skips a linked file "
                                              "inside a skill")
                elif stat.S_ISDIR(found.st_mode):
                    if name not in SKIPPED_DIRECTORIES:
                        below.append(path)
                elif stat.S_ISREG(found.st_mode):
                    files.append(path)
                else:
                    self.add(path, "source-unreadable", "is not a regular file")
            pending.extend(reversed(below))
        files.sort()
        self._walks[top] = files
        return files


def printable(text: str) -> str:
    """``text`` with every character that is not printable written as its
    code point, so that a faulty source cannot move the cursor."""
    if text.isprintable():
        return text
    return "".join(char if char.isprintable() else f"<U+{ord(char):04X}>" for char in text)


def is_link(found: os.stat_result) -> bool:
    """Whether what ``lstat`` found is a symlink or a Windows junction."""
    return stat.S_ISLNK(found.st_mode) or getattr(found, "st_reparse_tag", 0) in _REPARSE_LINKS


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _shown(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


# --- Skills --------------------------------------------------------------------

@dataclass(frozen=True)
class Field:
    """One frontmatter line: its number, the line as written and its value.
    ``faulty`` is set when the value could not be read; it is then empty."""

    line: int
    raw: str
    value: str
    faulty: bool = False


def parse_frontmatter(text: str) -> tuple[dict[str, Field] | None, list[tuple[int, str]]]:
    """The frontmatter of a ``SKILL.md`` and its faults, as (line, text).

    Read strictly, for exactly the shape these files have: a first line
    ``---``, then ``key: value`` lines, one per key, then ``---``. A value is
    a plain scalar or a quoted one on its own line. Anything else is a fault
    and is not guessed at: an indented line (a multi-line value, a nested
    map), a block or flow value, a comment, a key given twice, a plain value
    that YAML would read as something else. The fields are None when the
    frontmatter has no beginning or no end.

    A CRLF line ending is read as LF: a Windows checkout may have one. The
    ``compatibility`` value is kept as written; its own grammar is stricter.
    """
    faults: list[tuple[int, str]] = []
    if text.startswith("\ufeff"):
        faults.append((1, "starts with a byte order mark; a provider looks for --- as the first bytes"))
        text = text[1:]
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    if lines[0] != "---":
        faults.append((1, "does not start with a --- line; a skill has frontmatter"))
        return None, faults
    end = next((index for index in range(1, len(lines)) if lines[index] == "---"), None)
    if end is None:
        faults.append((1, "the frontmatter has no closing --- line"))
        return None, faults
    fields: dict[str, Field] = {}
    for index in range(1, end):
        line, number = lines[index], index + 1
        if not line.strip():
            continue
        if line[0] in " \t":
            faults.append((number, "an indented line; a multi-line value or a nested map is not read"))
            continue
        found = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(?: +(.*))?", line)
        if found is None:
            faults.append((number, "not a `key: value` line"))
            # The key is there, though its value is not read: it is not
            # reported as missing on top of this.
            started = re.match(r"([A-Za-z_][A-Za-z0-9_-]*):", line)
            if started and started.group(1) not in fields and started.group(1) != COMPATIBILITY_KEY:
                fields[started.group(1)] = Field(number, line, "", faulty=True)
            continue
        key, raw = found.group(1), (found.group(2) or "")
        if key in fields:
            faults.append((number, f"the key {key} is given twice (first on line {fields[key].line})"))
            continue
        if key == COMPATIBILITY_KEY:
            fields[key] = Field(number, line, raw)
            continue
        value, fault = _scalar(raw.rstrip())
        # An empty description is the description rule's to report.
        if fault is not None and (raw.strip() or key != DESCRIPTION_KEY):
            faults.append((number, f"{key}: {fault}"))
        fields[key] = Field(number, line, value, faulty=fault is not None)
    return fields, faults


def _scalar(text: str) -> tuple[str, str | None]:
    """The value of one frontmatter line, and why it cannot be read."""
    if not text:
        return "", "has no value on its line; a nested map or a multi-line value is not read"
    first = text[0]
    if first == '"':
        found = re.fullmatch(r'"((?:[^"\\]|\\["\\])*)"', text)
        if found is None:
            return "", 'a double-quoted value must end at its closing quote and hold no escape but \\" and \\\\'
        return re.sub(r'\\(["\\])', r"\1", found.group(1)), None
    if first == "'":
        found = re.fullmatch(r"'((?:[^']|'')*)'", text)
        if found is None:
            return "", "a single-quoted value must end at its closing quote"
        return found.group(1).replace("''", "'"), None
    if first in "|>":
        return "", "a block value (| or >) is not read; write the value on the key's line"
    if first in "[{":
        return "", "a list or a map is not read; write a plain value"
    if first in "&*!%@`#,]}" or text[:2] in ("- ", "? ", ": ") or text in ("-", "?", ":"):
        return "", f"starts with {first}, which YAML reads as syntax; quote the value"
    if " #" in text:
        return "", "holds ' #', which starts a YAML comment; quote the value"
    if ": " in text or text.endswith(":"):
        return "", "holds ': ', which YAML reads as a key; quote the value"
    return text, None


def read_implicit_invocation(text: str) -> tuple[bool | None, list[tuple[int, str]]]:
    """``policy.allow_implicit_invocation`` of an ``agents/openai.yaml``,
    or None when the file does not set it, and the faults as (line, text).

    A line reader for that one key: ``policy:`` alone on an unindented line,
    and the key on a line of the block's first indent, as ``true`` or
    ``false``. Wherever else the key's name appears, the file says something
    this reader cannot be sure of, and that is a fault."""
    faults: list[tuple[int, str]] = []
    value: bool | None = None
    in_policy = seen_policy = False
    block_indent: int | None = None
    lines = text.removeprefix("\ufeff").split("\n")
    for number, line in enumerate(lines, 1):
        line = line.rstrip("\r")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lead = line[: len(line) - len(line.lstrip())]
        if "\t" in lead:
            faults.append((number, "is indented with a tab, so its place in the file cannot be read"))
            continue
        if not lead:
            in_policy = False
            if stripped == "policy:":
                if seen_policy:
                    faults.append((number, "policy is given twice"))
                in_policy, seen_policy, block_indent = True, True, None
            elif re.match(r"""["']?policy["']?\s*:""", stripped):
                faults.append((number, "policy is not written as a block: `policy:` on a line of its own"))
            elif IMPLICIT_KEY in stripped:
                faults.append((number, f"{IMPLICIT_KEY} is outside the policy block and cannot be read safely"))
            continue
        if in_policy and block_indent is None:
            block_indent = len(lead)
        if in_policy and len(lead) == block_indent and re.match(IMPLICIT_KEY + r"\s*:", stripped):
            found = re.fullmatch(IMPLICIT_KEY + r": +(true|false)", stripped)
            if found is None:
                faults.append((number, f"policy.{IMPLICIT_KEY} is not written as `true` or `false`"))
            elif value is not None:
                faults.append((number, f"policy.{IMPLICIT_KEY} is given twice"))
            else:
                value = found.group(1) == "true"
        elif IMPLICIT_KEY in stripped:
            faults.append((number, f"{IMPLICIT_KEY} is not directly under policy and cannot be read safely"))
    return value, faults


def _find_skills(run: _Run) -> None:
    for entry in paths.entries(run.clone):
        if entry.name.startswith("."):
            continue
        try:
            found = os.lstat(entry)
        except (OSError, ValueError) as exc:
            run.add(entry, "source-unreadable", f"cannot be read: {paths.reason(exc)}")
            continue
        if is_link(found):
            if os.path.lexists(entry / SKILL_FILE):
                run.add(entry, "symlink", "the skill directory is a link; no link is committed")
            continue
        if stat.S_ISDIR(found.st_mode) and os.path.lexists(entry / SKILL_FILE):
            run.skills[entry.name] = _Source(entry.name, entry)


def _check_skills(run: _Run) -> None:
    for source in run.skills.values():
        file = source.directory / SKILL_FILE
        own_setup = source.name in OWN_SETUP
        if not own_setup:
            run.walk(source.directory)  # the links in it
        try:
            found = os.lstat(file)
        except (OSError, ValueError) as exc:
            run.add(file, "source-unreadable", f"cannot be read: {paths.reason(exc)}")
            continue
        if stat.S_ISDIR(found.st_mode):
            run.add(file, "skill-file", "is a directory; a skill's SKILL.md is a file")
            continue
        if is_link(found) and own_setup:
            run.add(file, "symlink", "is a link; no link is committed")
        text = run.need(file, "skill-file")
        if text is None:
            continue
        fields, faults = parse_frontmatter(text)
        for line, fault in faults:
            run.add(file, "skill-frontmatter", fault, line=line)
        if fields is None:
            continue

        name = fields.get("name")
        if name is None:
            run.add(file, "skill-name", "the frontmatter has no name")
        elif name.value and name.value != source.name:
            run.add(file, "skill-name", f"{name.value!r} is not the directory's name, {source.name!r}", line=name.line)

        description = fields.get(DESCRIPTION_KEY)
        if description is None:
            run.add(file, "skill-description", "the frontmatter has no description")
        elif not description.value.strip() and (not description.faulty or not description.raw.split(":", 1)[1].strip()):
            run.add(file, "skill-description", "the description is empty", line=description.line)

        compatibility = fields.get(COMPATIBILITY_KEY)
        if compatibility is None:
            run.add(file, "skill-compatibility", "the frontmatter has no compatibility line")
        else:
            start = COMPATIBILITY_KEY + ": "
            matched = COMPATIBILITY.match(compatibility.raw[len(start):]) if compatibility.raw.startswith(start) else None
            if matched is None:
                run.add(
                    file, "skill-compatibility",
                    "the line must be `compatibility: <providers>` or `compatibility: <providers> (<note>)`, "
                    "with <providers> one of claude-code / codex / claude-code, codex, no quotes, no comment, "
                    "nothing after it, and a note without parenthesis, # or :",
                    line=compatibility.line,
                )
            else:
                source.providers = tuple(matched.group(1).split(", "))

        invoke_only = False if own_setup else _check_invoke_only(run, source, file, fields)
        run.report_skills[source.name] = Skill(source.name, source.providers or (), invoke_only, own_setup)


def _check_invoke_only(run: _Run, source: _Source, file: Path, fields: dict[str, Field]) -> bool:
    """Invoke-only is declared once per provider the skill is for, or not at
    all. Returns whether the skill is invoke-only."""
    in_frontmatter = False
    declared = fields.get(INVOKE_KEY)
    if declared is not None:
        if not declared.faulty and declared.value not in ("true", "false"):
            run.add(file, "skill-invoke-only", f"{INVOKE_KEY} is not written as `true` or `false`", line=declared.line)
        in_frontmatter = declared.value == "true"

    in_yaml = False
    yaml = source.directory.joinpath(*OPENAI_FILE)
    yaml_name = "/".join(OPENAI_FILE)
    if os.path.lexists(yaml):
        text = run.need(yaml, "skill-invoke-only")
        if text is not None:
            value, faults = read_implicit_invocation(text)
            for line, fault in faults:
                run.add(yaml, "skill-invoke-only", fault, line=line)
            in_yaml = value is False

    # A skill for one provider needs that provider's declaration only.
    providers = source.providers or PROVIDERS
    if set(providers) >= set(PROVIDERS):
        if in_frontmatter and not in_yaml:
            run.add(
                file, "skill-invoke-only",
                f"{INVOKE_KEY}: true is declared here and policy.{IMPLICIT_KEY}: false is not in {yaml_name}; "
                "invoke-only is declared for both providers or for neither",
                line=declared.line if declared else None,
            )
        elif in_yaml and not in_frontmatter:
            run.add(
                yaml, "skill-invoke-only",
                f"policy.{IMPLICIT_KEY}: false is declared here and {INVOKE_KEY}: true is not in the frontmatter "
                "of SKILL.md; invoke-only is declared for both providers or for neither",
            )
    return in_frontmatter if "claude-code" in providers else in_yaml


def _judged(run: _Run) -> list[_Source]:
    """The skills this tool judges beyond their frontmatter."""
    return [source for source in run.skills.values() if source.name not in OWN_SETUP]


# --- Names: what becomes a file's or a directory's name in a home ----------------

def _directories(run: _Run, top: Path) -> list[Path]:
    """The directories directly in ``top`` whose name starts with neither
    a dot nor an underscore. Nothing is followed."""
    found = []
    if not _is_directory(run, top):
        return found
    for entry in paths.entries(top):
        if entry.name.startswith((".", "_")):
            continue
        try:
            if stat.S_ISDIR(os.lstat(entry).st_mode):
                found.append(entry)
        except (OSError, ValueError):
            continue  # the walk of its own step says so
    return found


def _check_ids(run: _Run) -> None:
    where = run.where
    rules = _directories(run, run.clone / "rules")
    role_directories = _directories(run, where.roles_dir)
    groups = (
        ("skill", [(source.name, source.directory / SKILL_FILE) for source in run.skills.values()]),
        ("rule", [(rule.name, rule) for rule in rules]),
        ("role", [(directory.name, directory / roles.ROLE_FILE) for directory in role_directories]),
    )
    for what, named in groups:
        for name, file in named:
            # A role's characters are the format check's (``role-toml``).
            if what != "role" and not schema.is_id(name):
                run.add(file, "id-characters", f"the {what} directory {name!r} is not lower-case letters, digits "
                                               "and single hyphens; its name becomes a link's name in every home")
            # A role id leaves room for its hard definition, ``<id>-hard``.
            limit = ID_LIMIT - len(roles.HARD_SUFFIX) if what == "role" else ID_LIMIT
            if len(name) > limit:
                run.add(file, "id-length", (
                    f"the {what} id is {len(name)} characters long; at most {limit}"
                    + (f", so that {roles.HARD_SUFFIX} still fits in {ID_LIMIT}" if what == "role" else "")
                    + ": it becomes a file's and a directory's name in every home"
                ))
            if name.lower().split(".")[0] in DEVICE_NAMES:
                run.add(file, "id-device-name", f"the {what} id {name!r} is a device name of Windows, where no "
                                                "file or directory can have it; choose another")
        seen: dict[str, str] = {}
        for name, file in sorted(named):
            first = seen.setdefault(name.lower(), name)
            if first != name:
                run.add(file, "id-case", f"the {what} {name!r} differs from {first!r} only in letter case; "
                                         "Windows cannot hold the two apart, in the clone or in a home")
    # A loaded role is installed as a skill of the role's name.
    for directory in role_directories:
        file = directory / roles.ROLE_FILE
        try:
            data = tomlio.load(file) if paths.kind(file) == paths.FILE else {}
        except SetupError:
            continue  # the format check says so
        if _get(data, "entry", "load") is not True:
            continue
        name = directory.name
        if name in OWN_SETUP:
            run.add(file, "role-skill-name", f"the role {name} is loaded as the skill {name}, and a skill of that "
                                             "name has a setup of its own; rename the role, or set load = false",
                    key="entry.load")
        elif name in run.skills:
            run.add(file, "role-skill-name", f"the role {name} is loaded as the skill {name}, and the clone has a "
                                             f"skill of that name ({name}/{SKILL_FILE}); rename one of the two, or "
                                             "set load = false", key="entry.load")


# --- R2.5: a skill's scripts ---------------------------------------------------

def _check_scripts(run: _Run) -> None:
    for source in _judged(run):
        files = run.walk(source.directory)
        local = {file.stem for file in files if file.suffix == ".py"}
        local |= {part for file in files for part in file.relative_to(source.directory).parts[:-1]}
        for file in files:
            if file.suffix == ".py":
                _check_python(run, source, file, local)
            elif file.suffix in NODE_SUFFIXES:
                _check_node(run, source, file)


def _depth(source: _Source, file: Path) -> int:
    return len(file.relative_to(source.directory).parts) - 1


def _leaves(text: str, depth: int) -> bool:
    """Whether ``text``, read as a path relative to a directory ``depth``
    levels inside a skill, leads out of the skill."""
    if ".." not in text or not text.strip() or any(char.isspace() for char in text):
        return False
    if text[0] in "/\\" or re.match(r"[A-Za-z]:", text):
        return False  # absolute: the machine-path rule's
    level = depth
    for part in re.split(r"[\\/]+", text):
        if part in ("", "."):
            continue
        if part == "..":
            level -= 1
            if level < 0:
                return True
        else:
            level += 1
    return False


def _check_python(run: _Run, source: _Source, file: Path, local: set[str]) -> None:
    text = run.need(file, "script-syntax")
    if text is None:
        return
    try:
        tree = ast.parse(text.removeprefix("\ufeff"))
    except SyntaxError as exc:
        run.add(file, "script-syntax", f"does not parse as Python: {exc.msg}", line=exc.lineno)
        return
    except (ValueError, RecursionError, MemoryError) as exc:
        run.add(file, "script-syntax", f"does not parse as Python: {paths.reason(exc)}")
        return
    depth = _depth(source, file)
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            modules = [node.module]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _leaves(node.value, depth):
            run.add(file, "script-path", f"the path {_shown(node.value)!r} leaves the skill; a skill reaches no "
                                         "path outside its own", line=node.lineno)
        for module in modules:
            top = module.split(".")[0]
            if top not in sys.stdlib_module_names and top not in local:
                run.add(
                    file, "script-import",
                    f"imports {module}, which is neither standard library nor a file of this skill",
                    line=node.lineno,
                )


def _check_node(run: _Run, source: _Source, file: Path) -> None:
    text = run.need(file, "script-syntax")
    if text is None:
        return
    for pattern in _NODE_IMPORTS:
        for found in pattern.finditer(text):
            module = found.group(1)
            if module.startswith(("./", "../", "node:")) or module.split("/")[0] in NODE_BUILTINS:
                continue
            run.add(
                file, "script-import",
                f"imports {_shown(module)}, which is neither a Node built-in module nor a relative file of this skill",
                line=_line(text, found.start(1)),
            )
    depth = _depth(source, file)
    for found in _NODE_RELATIVE.finditer(text):
        if _leaves(found.group(2), depth):
            run.add(file, "script-path", f"the path {_shown(found.group(2))!r} leaves the skill; a skill reaches "
                                         "no path outside its own", line=_line(text, found.start(2)))


# --- R6.10 and R2.4: the texts -------------------------------------------------

def _check_texts(run: _Run) -> None:
    shared: list[Path] = []     # R2.4 applies
    installed: list[Path] = []  # R6.10 applies
    for source in _judged(run):
        files = run.walk(source.directory)
        installed += files
        # R2.4 is about text both providers read. A skill for one provider
        # may name what that provider has; one whose compatibility line
        # could not be read is taken as shared.
        if source.providers is None or len(source.providers) > 1:
            shared += [
                file for file in files
                if file.relative_to(source.directory).as_posix() not in PROVIDER_FILES
            ]
    role_files = run.walk(run.where.roles_dir) if _is_directory(run, run.where.roles_dir) else []
    installed += role_files
    shared += role_files
    for directory in (run.clone / "rules", run.where.providers_dir):
        if _is_directory(run, directory):
            installed += run.walk(directory)
    if paths.kind(run.where.defaults_file) == paths.FILE:
        installed.append(run.where.defaults_file)

    run.installed = list(installed)
    for file in installed:
        text = run.text(file)
        if text is None:
            continue  # ``_check_not_text`` says so, where no rule of the file's own did
        for kind, pattern in MACHINE_PATHS:
            for found in pattern.finditer(text):
                run.add(
                    file, "machine-path",
                    f"holds {kind}, {_shown(found.group())!r}: an absolute path of one machine; write ~, a path "
                    "relative to the unit, or a placeholder such as <user>",
                    line=_line(text, found.start()),
                )
    for file in shared:
        text = run.text(file)
        if text is None:
            continue
        for what, pattern in (("the provider tool or parameter", _TERM), ("the provider substitution", _SUBSTITUTION),
                              ("a provider tool", _TOOL_PHRASE)):
            for found in pattern.finditer(text):
                run.add(
                    file, "provider-name",
                    f"names {what} {found.group()!r}; shared text says what is done, and a provider's own way "
                    "goes in its references file or its actions.md",
                    line=_line(text, found.start()),
                )


def _check_not_text(run: _Run) -> None:
    """A file of an installed unit that was read and is not UTF-8 text: no
    rule here can look into it, and it is installed with its unit all the
    same. Last of the steps: a file that a rule of its own already
    reported as not being text (a ``SKILL.md``, a script, a ``ROLE.md``) is
    not reported twice."""
    binary = _binary_patterns(run)
    said = {problem.file for problem in run.found if "not UTF-8 text" in problem.message}
    for file in run.installed:
        if run._bytes.get(file) is None or run.text(file) is not None:
            continue
        if printable(run.rel(file)) in said or _declared_binary(run, file, binary):
            continue
        run.add(
            file, "not-text",
            "holds a NUL byte, or bytes that are not UTF-8, so no rule can read it, and "
            f"{GITATTRIBUTES} does not declare its type binary; it is installed with its unit",
        )


def _binary_patterns(run: _Run) -> list[str]:
    """The patterns ``.gitattributes`` at the clone's root gives the
    attribute ``binary``."""
    file = run.clone / GITATTRIBUTES
    try:
        if paths.kind(file) != paths.FILE:
            return []
    except SetupError:
        return []
    text = run.text(file) or ""
    found = []
    for line in text.split("\n"):
        words = line.split()
        if len(words) > 1 and not words[0].startswith("#") and "binary" in words[1:]:
            found.append(words[0])
    return found


def _declared_binary(run: _Run, file: Path, patterns: list[str]) -> bool:
    relative = run.rel(file)
    for pattern in patterns:
        if "/" in pattern.strip("/"):
            if fnmatch.fnmatchcase(relative, pattern.lstrip("/")):
                return True
        elif fnmatch.fnmatchcase(file.name, pattern.strip("/")):
            return True
    return False


def _is_directory(run: _Run, path: Path) -> bool:
    try:
        return paths.kind(path) == paths.DIRECTORY
    except SetupError as exc:
        for line in exc.lines:
            run.add(path, "source-unreadable", run.shorten(line))
        return False


# --- Roles ---------------------------------------------------------------------

def _check_roles(run: _Run) -> None:
    where = run.where
    if not _is_directory(run, where.roles_dir):
        return
    files = roles.files(where)
    data: dict[str, dict[str, Any]] = {}
    for name, file in files.items():
        lines: list[str] = []
        loaded = roles.check_file(file, name, lines, strict=True)
        run.loader(file, "role-toml", lines)
        if loaded is not None:
            data[name] = loaded.data
        else:
            try:
                data[name] = tomlio.load(file) if paths.kind(file) == paths.FILE else {}
            except SetupError:
                data[name] = {}

    hard = {name for name, found in data.items() if isinstance(_get(found, "profile", "hard"), dict)}
    definitions = set(files) | {name + roles.HARD_SUFFIX for name in hard}
    shared_dir = where.roles_dir / roles.SHARED_DIR
    for name, file in files.items():
        found = data[name]
        directory = file.parent
        # The name is the directory's, whose length ``id-length`` judges.
        for key, limit in (("name", max(ID_LIMIT, len(name))), ("title", TITLE_LIMIT), ("description", DESCRIPTION_LIMIT)):
            run.field(file, key, found.get(key), limit)
        for definition in [name] + ([name + roles.HARD_SUFFIX] if name in hard else []):
            if definition.replace("-", "_") in RESERVED_IDS:
                run.add(
                    file, "role-reserved",
                    f"the definition id {definition} is the key {definition.replace('-', '_')} of Codex's [agents] "
                    "table, which Codex reserves; choose another role id",
                )
        if name in hard and name + roles.HARD_SUFFIX in files:
            run.add(file, "role-toml", f"yields the definition {name}{roles.HARD_SUFFIX}, which is also the role "
                                       f"directory {name}{roles.HARD_SUFFIX}", key="profile.hard")

        try:
            has_text = paths.kind(directory / roles.TEXT_FILE) == paths.FILE
        except SetupError as exc:
            run.loader(directory / roles.TEXT_FILE, "role-text", exc.lines)
            has_text = False
        else:
            if not has_text:
                run.add(directory / roles.TEXT_FILE, "role-text", "missing or not a file; a role directory must have it")
        parts = [run.need(directory / roles.TEXT_FILE, "role-text")] if has_text else [None]

        includes = found.get("includes")
        for item in includes if isinstance(includes, list) else []:
            if not isinstance(item, str) or not item.strip():
                continue  # the format check said so
            include = shared_dir / item
            plain = item not in (".", "..") and not re.search(r"[\\/]", item)
            try:
                there = plain and paths.kind(include) == paths.FILE
            except SetupError:
                there = False
            if not there:
                run.add(file, "role-include", f"{item!r} is not a file in roles/{roles.SHARED_DIR}/ (a file name, "
                                              "with no directory)", key="includes")
                parts.append(None)
            else:
                parts.append(run.need(include, "role-include"))

        if all(part is not None for part in parts) and isinstance(includes, list):
            size = len(roles.join_text(parts).encode("utf-8"))  # type: ignore[arg-type]
            run.sizes[name] = size
            if size >= roles.TEXT_LIMIT:
                run.add(
                    directory / roles.TEXT_FILE, "role-size",
                    f"with its includes the role's text is {size:,} bytes; it must stay under {roles.TEXT_LIMIT:,}",
                )

        actions = found.get("actions")
        for item in actions if isinstance(actions, list) else []:
            if not isinstance(item, str) or not item.strip():
                continue  # the format check said so
            missing = [provider for provider, names in _action_sections(run).items() if item not in names]
            if missing:
                run.add(
                    file, "role-actions",
                    f"{item!r} is not a section of {', '.join(f'providers/{name}/{ACTIONS_FILE}' for name in missing)}; "
                    "a section is named by its level-three heading, in lower case with hyphens",
                    key="actions",
                )

        dispatches = _get(found, "limits", "dispatches")
        for item in dispatches if isinstance(dispatches, list) else []:
            if isinstance(item, str) and item.strip() and item not in definitions:
                run.add(
                    file, "role-dispatch",
                    f"{item!r} is not a role definition; known: {', '.join(sorted(definitions))}",
                    key="limits.dispatches",
                )


def _action_sections(run: _Run) -> dict[str, set[str]]:
    """The ids of the sections of each provider's action notes that can be
    read. A provider whose notes cannot be read is left out: its own rule
    says so."""
    found: dict[str, set[str]] = {}
    for directory in paths.entries(run.where.providers_dir):
        if directory.name.startswith("."):
            continue
        try:
            there = paths.kind(directory / ACTIONS_FILE) == paths.FILE
        except SetupError:
            there = False
        text = run.text(directory / ACTIONS_FILE) if there else None
        if text is not None:
            found[directory.name] = {name for name, _ in definitions.action_sections(text)[1]}
    return found


def _check_loaded(run: _Run) -> None:
    """The skill of each role that can be loaded, made as ``render`` makes
    it for each provider that has a dictionary, and measured as ``render``
    and ``doctor`` measure it. The profile is the shipped one (``NO_HOME``).
    Sources the skills cannot be made from have a fault another rule
    reports; where none did, the reason is reported here."""
    where = run.where
    if not _is_directory(run, where.roles_dir) or not _is_directory(run, where.providers_dir):
        return
    shipped = Locations(home=where.clone.joinpath(*NO_HOME), clone=where.clone)
    try:
        providers = [name for name in entry.PROVIDERS if name in dictionary.files(where)]
        made = entry.skills(shipped, providers)
    except SetupError as exc:
        if not run.found:
            for line in exc.lines:
                run.add(where.roles_dir, "loaded-skill-size", "a loaded role's skill cannot be made, so its size "
                        f"is not known: {run.shorten(line)}")
        return
    for one in made:
        if not one.name.endswith(entry.SKILL_FILE):
            continue
        run.loaded.setdefault(one.role, {})[one.provider] = {
            "bytes": one.size, "tokens": one.tokens, "limit_tokens": one.limit_tokens,
        }
        if one.over_limit:
            run.add(
                where.roles_dir / one.role / roles.TEXT_FILE, "loaded-skill-size",
                f"loaded as a skill on {one.provider} the role is about {one.tokens:,} tokens ({one.size:,} bytes, at "
                f"{entry.BYTES_PER_TOKEN} bytes a token); at most {one.limit_tokens:,}, which is what "
                f"{one.provider_name} keeps of an invoked skill after a compaction (skills.compaction_tokens in "
                f"providers/{one.provider}/{dictionary.DICTIONARY_FILE}). Cut the role's text, its includes or its "
                "actions",
            )


def _check_embedded(run: _Run) -> None:
    """The texts ``render`` embeds whole: each role's ``ROLE.md``, the
    shared sections and each provider's action notes. ``render`` joins
    them with CRLF read as LF, and refuses a text that then still holds a
    carriage return; a line that reads as one of setup's markers would end
    setup's own block where the text is written into one."""
    where = run.where
    files: list[Path] = []
    for directory in _directories(run, where.roles_dir):
        files.append(directory / roles.TEXT_FILE)
    shared = where.roles_dir / roles.SHARED_DIR
    if _is_directory(run, where.roles_dir) and _is_directory(run, shared):
        files += run.walk(shared)
    for directory in _directories(run, where.providers_dir):
        files.append(directory / ACTIONS_FILE)
    for file in files:
        try:
            if paths.kind(file) != paths.FILE:
                continue  # missing: said by the step that needs it
        except SetupError:
            continue
        text = run.text(file)
        if text is None:
            continue
        for number, line in enumerate(text.split("\n"), 1):
            bare = line[:-1] if line.endswith("\r") else line
            if "\r" in bare:
                run.add(file, "text-carriage-return", "holds a carriage return that is not part of a CRLF line "
                                                      "end; render writes LF and refuses the text", line=number)
            if MARKER_LINE.fullmatch(bare):
                run.add(file, "text-marker", "the line reads as one of setup's block markers "
                                             "(workflow-setup:start or :end), and would end or open a block where "
                                             "render embeds the text; reword it", line=number)


def _strings(value: Any, key: str = "") -> list[tuple[str, str]]:
    """Every string of a parsed TOML value, keys included, with the key it
    is at."""
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        found.append((key, value))
    elif isinstance(value, dict):
        for name, inner in value.items():
            here = f"{key}.{tomlio.format_key(printable(str(name)))}" if key else tomlio.format_key(printable(str(name)))
            if is_control_text(str(name)):
                found.append((here, str(name)))
            found.extend(_strings(inner, here))
    elif isinstance(value, list):
        for number, inner in enumerate(value, 1):
            found.extend(_strings(inner, f"{key}[{number}]"))
    return found


def is_control_text(text: str) -> bool:
    return any(is_control(char) for char in text)


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _check_bindings(run: _Run) -> None:
    where = run.where
    if not _is_directory(run, where.roles_dir):
        return
    file = where.roles_dir / BINDINGS_FILE
    try:
        data = tomlio.load_if_present(file)
    except SetupError as exc:
        run.loader(file, "bindings", exc.lines)
        return
    if data is None:
        run.add(file, "bindings", "missing; roles/ holds the binding table, with no row when no stage is bound")
        return

    def fault(message: str, key: str | None = None) -> None:
        run.add(file, "bindings", message, key=key)

    version = data.get(schema.VERSION_KEY)
    if version is None:
        fault("missing; the file holds schema_version = 1", schema.VERSION_KEY)
    elif tomlio.type_name(version) != "integer":
        fault(f"expected an integer, got {tomlio.article(tomlio.type_name(version))}", schema.VERSION_KEY)
    elif version != BINDINGS_VERSION:
        fault(f"{version} is not the version this tool reads ({BINDINGS_VERSION})", schema.VERSION_KEY)
    for key in data:
        if key not in (schema.VERSION_KEY, "binding"):
            fault(f"unknown key; known here: {schema.VERSION_KEY}, binding", tomlio.format_key(key))
    rows = data.get("binding", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        fault("expected [[binding]] tables, one per row", "binding")
        return

    try:
        role_names = set(roles.files(where))
    except SetupError:
        role_names = set()
    made_for = _made_for(run)
    known = ("role", "skill", "stage", "part", "note")
    seen: dict[tuple[str, str, str], int] = {}
    for number, row in enumerate(rows, 1):
        place = f"binding[{number}]"  # the row's number in the file, from 1
        for key in row:
            if key not in known:
                fault(f"unknown key; known here: {', '.join(known)}", f"{place}.{tomlio.format_key(key)}")
        values: dict[str, str] = {}
        for key in known:
            if key != "note":  # a note has a limit and a check of its own, below
                run.field(file, f"{place}.{key}", row.get(key))
            elif isinstance(row.get(key), str) and (
                    is_control_text(row[key].replace("\n", "")) or MARKER_LINE.fullmatch(row[key])):
                run.field(file, f"{place}.{key}", row[key], limit=max(NOTE_LIMIT, len(row[key])))
            if key not in row:
                if key != "note":
                    fault("missing; a row must have it", f"{place}.{key}")
            elif not isinstance(row[key], str):
                fault(f"expected a string, got {tomlio.article(tomlio.type_name(row[key]))}", f"{place}.{key}")
            elif not row[key].strip():
                fault("must not be empty", f"{place}.{key}")
            else:
                values[key] = row[key]

        role, skill, stage = values.get("role"), values.get("skill"), values.get("stage")
        if role is not None and role not in role_names:
            fault(f"{role!r} is not a role: no such directory under roles/", f"{place}.role")
        skill_there = False
        if skill is not None:
            skill_there = skill in run.skills
            if not skill_there:
                fault(f"{skill!r} is not a skill: a directory at the repository root that holds SKILL.md, "
                      "named and never given as a path", f"{place}.skill")
            # The row reaches the role in every file made for it, under the
            # path of the skill in that provider's skills directory: the
            # skill has to be installed there. A compatibility line that
            # cannot be read is its own rule's to report.
            installed = run.skills[skill].providers if skill_there else None
            for provider in made_for.get(role or "", ()) if installed is not None else ():
                if provider not in installed:
                    fault(
                        f"the role {role} is made for {provider}, where the skill {skill!r} is not installed: its "
                        f"compatibility line names {', '.join(installed) or 'no provider'}. The role would be told "
                        f"to read its stage file in a skills directory that does not hold the skill. Name {provider} "
                        f"in {skill}/{SKILL_FILE}, or bind a role that is not made for {provider}", f"{place}.skill")
        if stage is not None:
            if re.search(r"[\\/]", stage) or stage in (".", ".."):
                fault(f"{stage!r} is not a file name; a stage is named without a directory", f"{place}.stage")
            elif skill_there:
                target = run.clone / skill / "references" / stage  # type: ignore[operator]
                try:
                    there = paths.kind(target) == paths.FILE
                except SetupError:
                    there = False
                if not there:
                    fault(f"no stage file {run.rel(target)}", f"{place}.stage")
        if "part" in values and not _PART.fullmatch(values["part"]):
            fault(f"{values['part']!r} is not `owns` or a part's id in lower-case letters and hyphens", f"{place}.part")
        if "note" in values and (len(values["note"]) > NOTE_LIMIT or "\n" in values["note"]):
            fault(f"a note is one line of at most {NOTE_LIMIT} characters; this one has "
                  f"{len(values['note'])}", f"{place}.note")
        if role is not None and skill is not None and stage is not None:
            first = seen.setdefault((role, skill, stage), number)
            if first != number:
                fault(f"the same role, skill and stage as row {first}; a row is unique by the three", place)

    # Every stage of every process skill has a row. A row counts by its
    # skill and stage alone: a fault in its role is reported above.
    bound = {(row.get("skill"), row.get("stage")) for row in rows
             if isinstance(row.get("skill"), str) and isinstance(row.get("stage"), str)}
    for source in _judged(run):
        for stage in stage_files(run, source.directory):
            if (source.name, stage.name) not in bound:
                run.add(
                    stage, "stage-unbound",
                    f"no row of roles/{BINDINGS_FILE} names this stage file; every stage file of a process skill "
                    "has a row with the role that follows it",
                )


def _made_for(run: _Run) -> dict[str, tuple[str, ...]]:
    """For each role that can be read, the providers ``render`` makes a
    file for it on, of those that have a dictionary: a definition
    (``definitions.providers_of``), the skill of a loaded role, the profile
    of a starting role on Codex. A role whose ``role.toml`` is at fault is
    left out; its own rule says so."""
    where = run.where
    try:
        files = roles.files(where)
        with_dictionary = dictionary.files(where)
    except SetupError:
        return {}
    found: dict[str, tuple[str, ...]] = {}
    for name, file in files.items():
        try:
            role = roles.check_file(file, name, [])
        except (SetupError, OSError):
            role = None
        if role is None:
            continue
        wanted = set(definitions.providers_of(role))
        if entry.loads(role):
            wanted.update(entry.PROVIDERS)
        if entry.starts(role):
            wanted.add(entry.CODEX)
        found[name] = tuple(provider for provider in entry.PROVIDERS if provider in wanted and provider in with_dictionary)
    return found


def stage_files(run: _Run, skill: Path) -> list[Path]:
    """The stage files of the skill in the directory ``skill``, by name; none
    for a skill that is no process skill. A process skill is one that holds
    a file ``references/stage-*.md``. Its stage files are the ``.md`` files
    directly in ``references/``, whatever their names, but for
    ``NOT_A_STAGE``: so a stage file added under any name needs a row. A
    file in a directory below ``references/`` is none, and neither is a file
    of another type. Names are compared without regard to letter case
    (``Stage-1.md``, ``notes.MD``): a file system that folds case opens
    them all the same. A row still names a file exactly as it is written."""
    references = skill / REFERENCES_DIR
    try:
        if paths.kind(references) != paths.DIRECTORY:
            return []
    except SetupError:
        return []  # the walk of the skill's texts reports it
    found = [file for file in run.walk(references)
             if file.parent == references and file.name.lower().endswith(STAGE_SUFFIX)]
    if not any(fnmatch.fnmatchcase(file.name.lower(), STAGE_FILE) for file in found):
        return []
    return [file for file in found if file.name.lower() not in NOT_A_STAGE]


# --- Providers and settings ------------------------------------------------------

def _check_providers(run: _Run) -> None:
    where = run.where
    if not _is_directory(run, where.providers_dir):
        return
    with_dictionary = dictionary.files(where)
    for directory in paths.entries(where.providers_dir):
        if directory.name.startswith("."):
            continue
        try:
            if paths.kind(directory) != paths.DIRECTORY:
                continue
        except SetupError as exc:
            run.loader(directory, "source-unreadable", exc.lines)
            continue
        actions = directory / ACTIONS_FILE
        try:
            there = paths.kind(actions) == paths.FILE
        except SetupError:
            there = False
        if not there:
            run.add(actions, "provider-actions", "missing or not a file; a provider has its action notes")
        else:
            text = run.need(actions, "provider-actions")
            if text is not None and not text.strip():
                run.add(actions, "provider-actions", "is empty")
            size = len(run.read(actions) or b"")
            if size > ACTIONS_LIMIT:
                run.add(actions, "provider-actions-size", f"{size:,} bytes; at most {ACTIONS_LIMIT:,}: the action "
                                                          "notes end every definition and every loaded role")
        if directory.name not in with_dictionary:
            run.add(directory / dictionary.DICTIONARY_FILE, "dictionary", "missing; a provider has its dictionary")
    for provider, file in with_dictionary.items():
        lines: list[str] = []
        dictionary.check_file(file, provider, lines)
        run.loader(file, "dictionary", lines)
        try:
            data = tomlio.load_if_present(file) or {}
        except SetupError:
            continue  # said above
        # A model's name and an effort's value go into every definition.
        for key, value in _strings(data):
            run.field(file, key, value)


def _check_defaults(run: _Run) -> None:
    file = run.where.defaults_file
    try:
        data = tomlio.load_if_present(file)
    except SetupError as exc:
        run.loader(file, "defaults", exc.lines)
        return
    if data is None:
        run.add(file, "defaults", "the shipped defaults are missing; the clone is incomplete")
        return
    lines: list[str] = []
    if schema.check_document(data, file, lines):
        for group in schema.GROUPS:
            if group in data:
                schema.validate(group, data[group], file, lines)
    run.loader(file, "defaults", lines)
    if not lines:
        run.defaults = data


# --- The launchers ---------------------------------------------------------------

def read_built_in(text: str) -> dict[str, Any] | None:
    """The ``BUILT_IN`` literal of a script, read from its syntax tree and
    never by running it; None when the script has no such literal."""
    try:
        tree = ast.parse(text.removeprefix("\ufeff"))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        if any(isinstance(target, ast.Name) and target.id == BUILT_IN_NAME for target in targets):
            try:
                value = ast.literal_eval(node.value)  # type: ignore[arg-type]
            except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
                return None
            if isinstance(value, dict) and all(isinstance(key, str) for key in value):
                return value
            return None
    return None


def _check_launchers(run: _Run) -> None:
    launchers: list[Path] = []
    for source in _judged(run):
        for name, groups in BUILT_IN_GROUPS.items():
            file = source.directory / "scripts" / name
            try:
                if paths.kind(file) != paths.FILE:
                    continue
            except SetupError:
                continue  # the walk said so
            if name == LAUNCHER:
                launchers.append(file)
            _check_built_in(run, file, groups)
    read = [(file, run.read(file)) for file in launchers]
    read = [(file, data) for file, data in read if data is not None]
    for file, data in read[1:]:
        if data != read[0][1]:
            run.add(file, "launcher-identical", f"differs from {run.rel(read[0][0])}; the file is kept "
                                                "byte-identical in every skill that carries it")


def _check_built_in(run: _Run, file: Path, groups: tuple[str, ...]) -> None:
    text = run.need(file, "launcher-defaults")
    if text is None or run.defaults is None:
        return  # no defaults to compare with: that fault is reported as its own
    built_in = read_built_in(text)
    if built_in is None:
        run.add(file, "launcher-defaults", f"has no {BUILT_IN_NAME} dictionary literal that can be read without "
                                           "running the script")
        return
    shipped = dict(
        leaf for group in groups if group in run.defaults for leaf in schema.flatten(run.defaults[group], (group,))
    )
    source = run.rel(run.where.defaults_file)
    differences: list[str] = []
    for key in shipped:
        if key not in built_in:
            differences.append(f"{key} is missing")
        elif type(built_in[key]) is not type(shipped[key]) or built_in[key] != shipped[key]:
            differences.append(f"{key} is {built_in[key]!r} here and {shipped[key]!r} there")
    differences += [f"{key} is not in {'/'.join(groups)} there" for key in built_in if key not in shipped]
    if differences:
        run.add(
            file, "launcher-defaults",
            f"{BUILT_IN_NAME} differs from the {' and '.join(groups)} of {source}: {'; '.join(differences)}",
        )
