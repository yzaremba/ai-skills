#!/usr/bin/env python3
"""Check the deferred items and the format limits of a project's sprint docs.

Usage:
    python scripts/check.py [--project DIR] [--docs DIR] [--today DATE]
                            [--home DIR] [--json]

--project DIR  the project root; without it, the working directory
--docs DIR     the sprint docs directory, in place of the setting
               process.docs_dir (a relative DIR is taken from the working
               directory, as any path on a command line is)
--today DATE   the date to compare "Review by:" with, YYYY-MM-DD, in place
               of today's
--home DIR     use DIR in place of the user's home directory
--json         the same report as JSON

A "~" at the start of --project or --home is expanded, as the setup tool
expands it. An empty DIR is refused.

It executes nothing and changes nothing: it reads files and prints. A
"Check:" line of DEFERRED.md is text to it, printed word for word and never
run in any form. This module imports nothing that can start a process or
load code, and its tests assert that from its syntax tree.

What it reads, all as UTF-8:

    DEFERRED.md, DEFERRED-context.md and BACKLOG.md in the sprint docs
    directory, and the item documents (*.md) in the folder BACKLOG/ beside
    them; a BACKLOG-B<n>-<slug>.md beside them is a document at its
    earlier place, reported in one note, to be moved into the folder
    SPRINTNN-THOUGHTS-*.md, SPRINTNN-PRD-*.md, SPRINTNN-PLAN-*.md,
    SPRINTNN-TASKS-*.md and SPRINTNN-STATE-*.md there; never DONE/
    AGENTS.md in the project root, for the lesson index: the block between
    the lines <!-- project-memory:index:start --> and
    <!-- project-memory:index:end -->
    git's own files under the project root's .git, never git itself: the
    .git file and commondir, the HEAD files, rebase-merge/head-name,
    rebase-apply/head-name and BISECT_START beside a detached HEAD,
    worktrees/<name>/gitdir and locked, the names under refs/heads/sprint/
    and packed-refs; and, in each worktree on a sprint branch, the names in
    its sprint docs directory and that sprint's own docs

Sprint workspaces. Each branch sprint/NN-slug is reported with where it is
checked out: in place (in the project root); in a worktree; in a worktree
that is gone, which git calls prunable, or locked; in a worktree whose path
git wrote on the other system, shown as written and not looked at; or
nowhere. A detached HEAD in a rebase or a bisect of the branch still has it,
as git counts it, and is marked so. With it go which of the sprint's own
SPRINTNN-<KIND>-slug.md (THOUGHTS, PRD, PLAN, TASKS, STATE) are in the
sprint docs directory there: the docs directory's path inside the working
tree it is in, the deepest, mapped into the other one. A docs directory
outside every working tree, or in a repository of its own inside one, is
one for all of them, and nothing is mapped. A worktree's docs of that
sprint are checked as those of the docs directory are, and a violation
there names the file by its full path; the docs directory's copy of a doc
checked there, the start commit's, is not reported as well. Its shared
files are stale copies and are never read. In place, a note says the
shared files were read from the sprint branch's copies. Nothing of git's index or objects is read, so
nothing is said of what is committed. A project root with no .git has no
sprint section; a git file that cannot be used is a note. Of git's files
only a regular file of a bounded size is read: never a device or a pipe.
Refs in the reftable format are not read: a note, and no count of sprints.

The forms it checks are defined in this skill's references: deferred.md,
stage-0-backlog.md, and "Format limits" in conventions.md. Length is the
number of characters (code points) of a line without its newline and
without one carriage return before it; every limit is inclusive. A file in
which a carriage return stands anywhere but directly before a newline is
reported (line-endings) and not checked further.

A TASKS line shows one mark of its PLAN step: **[hard]**, directly after
the step ID, when the step carries `> Tag: hard`. Any other bold bracketed
tag on a TASKS line is reported (tasks-tag-form). Where the PLAN of the same
sprint number and slug is beside the TASKS file, a line that disagrees with
its step is reported (tasks-tag-mismatch); a line whose step ID the PLAN
does not hold is not compared.

A sprint doc links only within its own set: the THOUGHTS, PRD, PLAN, TASKS
and STATE of the same sprint number, by bare file name. In each of them,
outside fenced code blocks and code spans, the target of an inline link or
of a link reference definition is read, percent escapes decoded, and
reported when it is outside the set: a doc of another sprint,
SPRINT<NN>-*.md with another NN in any folder, DONE/ included
(link-other-sprint); an epic doc, EPIC<NN>-*.md (link-epic-doc); or any
other relative or absolute target: a doc of the same sprint through a
folder, a backlog item document, a shared file, a project doc, a path into
the code, an image, a path on a Windows drive (link-outside-set). Not
reported: a URL and an anchor in the same file. A footnote ([^1]: ...) is
no definition, and neither is a label followed by words or by a target
that is a bare word ([P1.2]: done). The fix is to name a doc (a .md file)
by its file name in backticks; a README.md or index.md by its path from
the project root; and any other path in backticks from the project root (a
worktree's own root for its docs), given when the docs directory is below
it and the target does not leave it. A file that is never archived with a
sprint, BACKLOG.md, an item document and DEFERRED-context.md, is checked
for links to sprint and epic docs only, the first two rules: the links of
BACKLOG.md to its item documents stay. The archive, DONE/, is not checked.
Known limits: an HTML anchor (<a href>), a fence inside a nested list item
and text such as arr[i](x) are read as markdown is read at the first
column, so the first two are missed and the last may be taken for a link.

A file is read only if, with every link in its path followed, it is still
inside the directory it was looked for in: the sprint docs directory, a
worktree's for its sprint docs, or the project root for AGENTS.md. A
git file is read where it is. A link that leads outside is reported and
not read. The folder BACKLOG/ is listed under the same rule. The docs
directory itself is taken as named, link or not.

The report has four parts. The deferred items: every item that is open,
and every item whose state cannot be told (its "Status:" is missing or
malformed), which is marked so; an item of "Sprint: none" is outside a
sprint, the checks tied to a sprint skip it, and closed it is reported,
since it leaves the file when it is closed. The sprint workspaces,
when the project root holds a .git. The violations. And the notes: facts
that need no action, such as a BACKLOG.md or a DEFERRED.md still in the
old form, or item documents at their earlier place. A note is not a
violation and has no effect on the exit code.

Settings. The process group is read here, and no other group: from the
same files, in the same order and under the same rules as the setup tool's
"show process", but without starting the tool: tools/setup/defaults.toml
of the clone this skill belongs to, ~/.agents/workflow.toml, and the
project's .agents/workflow.toml and .agents/workflow.local.toml; later
files win. Of each file the version and the top-level key names are
checked, then the whole [process] table: an unknown key, a value of the
wrong type, a value that is not one of those allowed, and an empty or
blank string are errors. What another group holds is not looked at. A
skill copied on its own has no setup tool beside it: the built-in defaults
are used and no settings file is read, as settings.py does.

Exit code: 0 when nothing needs action; 1 when an item is past its date,
an item's state cannot be told, or a violation is found; 2 on an error of
the command's own (bad arguments, a directory that is not there or cannot
be read, a settings file that cannot be used), which is one line on stderr.

Standard library only; the same code on Linux and Windows. Output is UTF-8
with LF line endings whatever the console is. Control and format characters
(escape sequences, direction overrides, zero-width characters) are written
as escapes in the text report, in the JSON report and in an error.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import stat
import sys
import tomllib
import unicodedata
from pathlib import Path

SCHEMA_VERSION = 1

EXIT_OK = 0
EXIT_ACTION = 1
EXIT_ERROR = 2

# What the setup tool's schema says of a settings file, as far as this
# command reads one: the top-level keys, and the whole process group. The
# two must stay equal; tools/setup/tests holds a test that they agree.
SETTINGS_SCHEMA_VERSION = 1
VERSION_KEY = "schema_version"
SETTINGS_GROUPS = ("process", "roles", "memory", "providers", "setup")
GROUP = "process"
# Each key of the group: its type, and the values allowed when not every one is.
PROCESS_KEYS = {
    "docs_dir": ("string", ()),
    "questions": ("string", ("one-at-a-time", "all-together")),
    "recommend": ("boolean", ("accept",)),
    "density": ("string", ("brief", "full")),
}
DOCS_DIR = "process.docs_dir"

# The process group of scripts/settings.py and of tools/setup/defaults.toml.
BUILT_IN = {
    "process.docs_dir": "docs",
    "process.questions": "all-together",
    "process.recommend": True,
    "process.density": "brief",
}
BUILT_IN_LAYER = "built-in"

ABSENT = "absent"
FILE = "file"
DIRECTORY = "directory"
OTHER = "other"  # a FIFO, a socket, a device

# This file is <clone>/<skill>/scripts/check.py; the path is made real first,
# as in settings.py, so a link to the skill does not change where the clone is.
_HERE = Path(__file__).resolve()
SETUP_DIR = _HERE.parents[2] / "tools" / "setup"

ANNOTATION_LIMIT = 300
TASKS_LIMIT = 150
STATE_LINES = 70
STATE_CHARACTERS = 8000
BACKLOG_LIMIT = 300
DEFERRED_LIMIT = 300
INDEX_LINES = 50
INDEX_LINE_LIMIT = 150

DEFERRED_FILE = "DEFERRED.md"
BACKLOG_FILE = "BACKLOG.md"
BACKLOG_DIR = "BACKLOG"
CONTEXT_FILE = "DEFERRED-context.md"
AGENTS_FILE = "AGENTS.md"
INDEX_START = "<!-- project-memory:index:start -->"
INDEX_END = "<!-- project-memory:index:end -->"

PLAN_NAME = re.compile(r"^SPRINT[0-9]{2,}-PLAN-.+\.md$")
TASKS_NAME = re.compile(r"^SPRINT[0-9]{2,}-TASKS-.+\.md$")
STATE_NAME = re.compile(r"^SPRINT[0-9]{2,}-STATE-.+\.md$")
# A sprint's own doc in the sprint docs directory: its number and its kind.
SPRINT_DOC_NAME = re.compile(r"^SPRINT([0-9]{2,})-(THOUGHTS|PRD|PLAN|TASKS|STATE)-.+\.md$")
# The last part of a link's target: a doc of a sprint, or of an epic.
LINKED_SPRINT_DOC = re.compile(r"^SPRINT([0-9]{2,})-.+\.md$", re.IGNORECASE)
LINKED_EPIC_DOC = re.compile(r"^EPIC([0-9]{2,})-.+\.md$", re.IGNORECASE)
# A link's target: after `](` of an inline link, or in a link reference definition.
INLINE_LINK = re.compile(r"\]\([ \t]*(<[^>]*>|[^\s)]+)")
# A definition: a label that is no footnote (`[^1]:`), the target, and at
# most a quoted or parenthesised title after it.
REFERENCE_DEFINITION = re.compile(
    r"""^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*(<[^>]*>|\S+)(?:[ \t]+(?:"[^"]*"|'[^']*'|\([^)]*\)))?[ \t]*$""")
# What makes a definition's bare target a path and not a word (`[P1.2]: done`).
PATH_LIKE = re.compile(r"[./\\#]")
PERCENT_ESCAPES = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
# A Windows drive at the start of a target: an absolute path, not a URL's scheme.
WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
# File names that say nothing on their own: such a doc is named by its path.
AMBIGUOUS_NAMES = ("readme.md", "index.md")
BACKTICKS = re.compile(r"`+")
# An item document at its earlier place, beside BACKLOG.md: BACKLOG-B<n>-<slug>.md, in any case.
OLD_DOCUMENT_NAME = re.compile(r"^BACKLOG-B[0-9]+-.*\.md$", re.IGNORECASE)

DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
DATE_ONLY = re.compile(rf"^{DATE}$")

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*))?$")
STEP_ID = re.compile(r"^P[0-9]+\.[0-9]+(?![0-9A-Za-z])")
ANNOTATIONS = (("> Landed ", "Landed"), ("> Bug fix ", "Bug fix"), ("> Audit ", "Audit"))
MARKS = ("> Depends on:", "> Parallel:", "> Tag:")
TASKS_STARTS = ("- [ ]", "- [~]", "- [x]")
HARD_MARK = "> Tag: hard"
# A TASKS line up to the end of its bold step ID; a skipped line has `~~` first.
TASKS_ID = re.compile(r"^- \[[ ~x]\] (?:~~)?\*\*(P[0-9]+\.[0-9]+)\*\*")
TASKS_HARD = re.compile(r" \*\*\[hard\]\*\*(?= |$)")
TASKS_PAIR = re.compile(r"^(SPRINT[0-9]{2,})-TASKS-(.+\.md)$")

B_POINTER = re.compile(r"^Latest assigned: B([1-9][0-9]*)$")
B_ITEM = re.compile(r"^- \*\*B([1-9][0-9]*)\*\* (?:\*\*\[(?:HIGH|MED|LOW)\]\*\* )?(\S.*)$")
B_NUMBERED = re.compile(r"^- \*\*B[0-9]+\*\*")
B_TAG = re.compile(r"\*\*\[[^\]]*\]\*\*")
B_LINK = re.compile(r"\]\(([^)]*)\)")
B_DOCUMENT = re.compile(r"^BACKLOG/(?P<name>B(?P<n>[1-9][0-9]*)-[a-z0-9]+(?:-[a-z0-9]+)*\.md)$")
B_OLD_DOCUMENT = re.compile(r"^BACKLOG-(?P<name>B(?P<n>[1-9][0-9]*)-[a-z0-9]+(?:-[a-z0-9]+)*\.md)$")
# A link is taken for a link to an item document when its target is a path,
# not a URL, with a folder named BACKLOG in any case, or a last part that
# starts like a document at its earlier place.
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
PATH_PARTS = re.compile(r"[/\\]")
OLD_DOCUMENT_START = re.compile(r"^BACKLOG-B[0-9]", re.IGNORECASE)

SPRINT_BRANCH = re.compile(r"^sprint/([0-9]{2,})-([^/]+)$")
SPRINT_KINDS = ("THOUGHTS", "PRD", "PLAN", "TASKS", "STATE")
HEAD_REF = re.compile(r"^ref: *(refs/\S+)$")
HEAD_HASH = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
PACKED_REF = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})? (refs/\S+)$")
BRANCH_REF = "refs/heads/"
# A path git wrote on Windows, as it is read on another system: a drive, or a share.
WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
# What reftable leaves in a HEAD file, for an older git to stop at.
REFTABLE_HEAD = "ref: refs/heads/.invalid"
# Only a regular file is read of git's, and no more than this: a one-line
# file (HEAD, gitdir, commondir, a .git file) and packed-refs.
LINE_FILE_LIMIT = 64 * 1024
PACKED_REFS_LIMIT = 32 * 1024 * 1024
# What keeps a detached HEAD on its branch, as git counts it: a rebase or a bisect.
BUSY_FILES = ((("rebase-merge", "head-name"), "rebase"), (("rebase-apply", "head-name"), "rebase"),
              (("BISECT_START",), "bisect"))
IN_PLACE = "in-place"
WORKTREE = "worktree"
PRUNABLE = "prunable"
LOCKED = "locked"
FOREIGN = "foreign"
NOWHERE = "nowhere"

D_TITLE = "# Deferred items"
D_POINTER = re.compile(r"^Latest assigned: D([1-9][0-9]*)$")
D_HEAD = re.compile(r"^### D([1-9][0-9]*) — (\S.*)$")
# An item heading, well formed or not: what makes a file one of the new form.
D_NUMBERED = re.compile(r"^### D[0-9]+(?![0-9A-Za-z])")
D_FIELDS = ("Sprint", "Trigger", "Review by", "Check", "Status")
D_REQUIRED = ("Sprint", "Trigger", "Review by", "Status")
D_SPRINT = re.compile(r"^([0-9]{2,}) (P[0-9]+\.[0-9]+)$")
D_NO_SPRINT = "none"  # the whole value of `Sprint:` for an item outside a sprint
D_REVIEW = re.compile(rf"^({DATE})(?: \(re-dated ({DATE}): \S.*\))?$")
D_STATUS = re.compile(rf"^(?:open|(?:resolved|dropped) ({DATE}): \S.*)$")

# A carriage return that is not directly before a newline.
LONE_CR = re.compile(r"\r(?!\n)")
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")

# The categories of the characters that would let text from a file change
# how a report looks on a terminal, or hide in it: controls (escape
# sequences, the C1 controls, DEL), format characters (direction marks and
# overrides, U+061C among them, and the zero-width characters), the line and
# paragraph separators, and half a surrogate pair. They are written as
# escapes everywhere this command prints.
_ESCAPED = frozenset(("Cc", "Cf", "Cs", "Zl", "Zp"))


class CheckError(Exception):
    """An error of the command's own: exit code 2."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse would print and exit
        raise CheckError(message)


# --- Reading ------------------------------------------------------------------

def _is_date(text: str) -> bool:
    """Whether ``text``, already of the form YYYY-MM-DD, is a calendar date."""
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def split_lines(text: str) -> list[str]:
    """The lines of a file as they are counted: split at the newline only,
    without it, and without one carriage return before it."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _present(path: Path) -> bool:
    """Whether anything is at ``path``, a link with no target included."""
    try:
        return path.is_symlink() or path.exists()
    except (OSError, ValueError):
        return True


def _kind(path: Path) -> str:
    """``ABSENT``, ``FILE``, ``DIRECTORY`` or ``OTHER``; a link counts as what
    it leads to. What cannot be looked at, and a link that leads nowhere,
    are errors that name the path: the answers of the setup tool."""
    try:
        found = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return ABSENT
    except (OSError, ValueError) as exc:
        raise CheckError(f"{path}: cannot be read: {_reason(exc)}") from None
    if stat.S_ISLNK(found.st_mode):
        try:
            found = path.stat()
        except PermissionError as exc:
            raise CheckError(f"{path}: cannot be read: {_reason(exc)}") from None
        except (OSError, ValueError):
            raise CheckError(f"link target missing: {path}") from None
    if stat.S_ISREG(found.st_mode):
        return FILE
    if stat.S_ISDIR(found.st_mode):
        return DIRECTORY
    return OTHER


def read_lines(path: Path, inside: Path) -> tuple[list[str] | None, tuple[str, str] | None]:
    """The lines of the file at ``path``, or the rule and message of why it
    was not read. ``inside`` is the directory the file must really be in."""
    try:
        real = path.resolve(strict=True)
        base = inside.resolve(strict=True)
        if not real.is_relative_to(base):
            return None, ("link-outside", "a link that leads out of its directory; it was not read")
        if not real.is_file():
            return None, ("not-a-file", "is not a file")
        raw = real.read_bytes()
    except (OSError, RuntimeError, ValueError) as exc:
        return None, ("unreadable", f"cannot be read: {_reason(exc)}")
    try:
        # A byte order mark is what some Windows editors put first.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, ("not-utf8", f"is not UTF-8 text (byte {exc.start}); it was not checked")
    lone = len(LONE_CR.findall(text))
    if lone:
        return None, (
            "line-endings",
            f"{lone} carriage return{'s' if lone > 1 else ''} not directly before a newline: "
            "a line ends with a newline, or a carriage return and a newline; it was not checked",
        )
    return split_lines(text), None


def backlog_documents(docs: Path, names: list[str]) -> tuple[set[str] | None, tuple[str, str] | None]:
    """The names in the folder ``BACKLOG/`` of the sprint docs directory, each
    as ``BACKLOG/<name>``, or None and the rule and message of why the folder
    was not listed. ``names`` are the names in the docs directory: the folder
    is there when one of them is exactly ``BACKLOG``, on every system. No
    folder is an empty set. Only names are read."""
    if BACKLOG_DIR not in names:
        return set(), None
    folder = docs / BACKLOG_DIR
    try:
        real = folder.resolve(strict=True)
        if not real.is_relative_to(docs.resolve(strict=True)):
            return None, ("link-outside", "a link that leads out of its directory; it was not read")
        if not real.is_dir():
            return None, ("not-a-directory", "is not a directory: the item documents are in a folder of this name")
        return {f"{BACKLOG_DIR}/{entry.name}" for entry in real.iterdir()}, None
    except (OSError, RuntimeError, ValueError) as exc:
        return None, ("unreadable", f"cannot be read: {_reason(exc)}")


def _reason(exc: BaseException) -> str:
    """Why the system refused, in its own words and on one line."""
    text = str(exc.strerror) if isinstance(exc, OSError) and exc.strerror else str(exc) or repr(exc)
    return " ".join(text.split())


# --- Settings -----------------------------------------------------------------

def _type_name(value: object) -> str:
    """The TOML name of a parsed value's type."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "table"
    # The other three things TOML can hold; a date-time is also a date.
    if isinstance(value, datetime.datetime):
        return "datetime"
    if isinstance(value, datetime.date):
        return "date"
    return "time"


def _article(noun: str) -> str:
    return f"an {noun}" if noun[:1] in "aeiou" else f"a {noun}"


def _key(key: str) -> str:
    """A key as TOML writes it: bare where it can be, quoted otherwise."""
    return key if BARE_KEY.fullmatch(key) else json.dumps(key, ensure_ascii=False)


def _load_if_present(file: Path) -> dict | None:
    """A settings file parsed, or None when nothing is at its place."""
    found = _kind(file)
    if found == ABSENT:
        return None
    if found != FILE:
        raise CheckError(f"{file}: is not a file")
    try:
        text = file.read_bytes().decode("utf-8-sig")
    except OSError as exc:
        raise CheckError(f"{file}: cannot be read: {_reason(exc)}") from None
    except UnicodeDecodeError as exc:
        raise CheckError(f"{file}: is not UTF-8 text (byte {exc.start})") from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CheckError(f"{file}: is not valid TOML: {exc}") from None
    except RecursionError:
        raise CheckError(f"{file}: is not valid TOML: arrays or inline tables are nested too deeply") from None
    except ValueError:
        raise CheckError(f"{file}: is not valid TOML: it holds an integer with too many digits") from None


def _load_layer(file: Path) -> dict | None:
    """A user, project or local file, or None when it is not there. A
    settings directory that is not a directory is a mistake to report."""
    directory = file.parent
    found = _kind(directory)
    if found == ABSENT:
        return None
    if found != DIRECTORY:
        raise CheckError(f"{directory}: is not a directory; {file.name} is looked for in it")
    return _load_if_present(file)


def _check_document(data: dict, file: Path, problems: list[str]) -> bool:
    """What holds for a settings file as a whole: its version, and the names
    of its top-level keys. Returns False for a file of a newer schema, in
    which nothing else is worth checking."""
    version = data.get(VERSION_KEY, SETTINGS_SCHEMA_VERSION)
    if _type_name(version) != "integer":
        problems.append(f"{file}: {VERSION_KEY}: expected an integer, got {_article(_type_name(version))}")
    elif version > SETTINGS_SCHEMA_VERSION:
        problems.append(
            f"{file}: {VERSION_KEY}: {version} is newer than this command reads ({SETTINGS_SCHEMA_VERSION}); "
            "update the clone the skill runs from, or bring the file back to the older schema"
        )
        return False
    elif version < 1:
        problems.append(f"{file}: {VERSION_KEY}: {version} is not a schema version; the first is 1")
    for key in data:
        if key != VERSION_KEY and key not in SETTINGS_GROUPS:
            problems.append(
                f"{file}: {_key(key)}: unknown key; known here: {VERSION_KEY}, {', '.join(SETTINGS_GROUPS)}"
            )
    return True


def _check_process(table: object, file: Path, problems: list[str]) -> None:
    """Check the whole process group of one file."""
    if not isinstance(table, dict):
        problems.append(f"{file}: {GROUP}: expected a table, got {_article(_type_name(table))}")
        return
    for key, value in table.items():
        where = f"{file}: {GROUP}.{_key(key)}"
        if key not in PROCESS_KEYS:
            problems.append(f"{where}: unknown key; known here: {', '.join(PROCESS_KEYS)}")
            continue
        wanted, choices = PROCESS_KEYS[key]
        actual = _type_name(value)
        if wanted == "boolean" and choices:
            # A boolean that also takes the named strings.
            if actual != "boolean" and value not in choices:
                shown = json.dumps(value, ensure_ascii=False) if actual in ("string", "integer") else _article(actual)
                problems.append(f"{where}: {shown} is not allowed; allowed values: true, false, {', '.join(choices)}")
        elif actual != wanted:
            problems.append(f"{where}: expected {_article(wanted)}, got {_article(actual)}")
        elif choices and value not in choices:
            problems.append(
                f"{where}: {json.dumps(value, ensure_ascii=False)} is not allowed; allowed values: {', '.join(choices)}"
            )
        elif wanted == "string" and not value:
            problems.append(f"{where}: must not be empty")
        elif wanted == "string" and not value.strip():
            problems.append(f"{where}: must not be blank; it holds only white space")


def setup_tool_is_beside() -> bool:
    """Whether this skill is in a clone, with the setup tool beside it."""
    try:
        return (SETUP_DIR / "workflow_setup.py").is_file()
    except (OSError, ValueError):
        return False


def read_settings(project: Path, home: Path | None) -> dict[str, dict]:
    """The process group: the value, layer and file of each key, in the
    schema's order. ``home`` is None when no ``--home`` was given."""
    if not setup_tool_is_beside():
        # A skill copied on its own: no settings file is read.
        return {key: {"value": value, "layer": BUILT_IN_LAYER, "file": None} for key, value in BUILT_IN.items()}
    if home is None:
        try:
            home = Path.home()
        except (RuntimeError, KeyError, OSError):
            raise CheckError("the user's home directory cannot be found; name one with --home DIR") from None
    shipped = SETUP_DIR / "defaults.toml"
    data = _load_if_present(shipped)
    if data is None:
        raise CheckError(f"{shipped}: the shipped defaults are missing; the clone is incomplete")
    documents: list[tuple[str, Path, dict]] = [("shipped", shipped, data)]
    for layer, file in (
        ("user", home / ".agents" / "workflow.toml"),
        ("project", project / ".agents" / "workflow.toml"),
        ("local", project / ".agents" / "workflow.local.toml"),
    ):
        data = _load_layer(file)
        if data is not None:
            documents.append((layer, file, data))
    problems: list[str] = []
    merged: dict[str, dict] = {}
    for layer, file, data in documents:
        if not _check_document(data, file, problems) or GROUP not in data:
            continue
        before = len(problems)
        _check_process(data[GROUP], file, problems)
        if len(problems) > before:
            continue
        for key, value in data[GROUP].items():
            merged[f"{GROUP}.{key}"] = {"value": value, "layer": layer, "file": str(file)}
    if problems:
        more = len(problems) - 1
        raise CheckError(problems[0] + (f" (and {more} more in the settings files)" if more else ""))
    return {f"{GROUP}.{key}": merged[f"{GROUP}.{key}"] for key in PROCESS_KEYS if f"{GROUP}.{key}" in merged}


# --- PLAN and TASKS -----------------------------------------------------------

def _outside_fences(lines: list[str]):
    """Each line that is not in a fenced code block and is not a fence line,
    with its number. A line that ends a run of such lines is given as None
    first, so that a caller's line-to-line state does not cross a block.

    A block closes only at a line of the opener's character, at least as
    many of them as the opener has, with nothing after them but white space.
    """
    fence = None  # the opener's run of backticks or tildes
    for number, line in enumerate(lines, 1):
        match = FENCE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                yield number, None
            else:
                yield number, line
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) \
                and not match.group(2).strip():
            fence = None


def _annotation_kind(line: str) -> str | None:
    for start, kind in ANNOTATIONS:
        if line.startswith(start):
            return kind
    return None


def check_plan(lines: list[str], add) -> None:
    in_step = False
    kinds: dict[str, int] = {}
    # "annotation": the line before was one; "continued": it was a second
    # line of one, already reported.
    before = None
    for number, line in _outside_fences(lines):
        if line is None:
            before = None
            continue
        heading = HEADING.match(line)
        if heading:
            in_step = bool(STEP_ID.match((heading.group(1) or "").strip()))
            kinds = {}
            before = None
            continue
        kind = _annotation_kind(line)
        if kind is not None:
            if len(line) > ANNOTATION_LIMIT:
                add(number, "annotation-too-long", f"{len(line)} characters; the limit is {ANNOTATION_LIMIT}")
            if in_step:
                if kind in kinds:
                    add(
                        number,
                        "annotation-duplicate",
                        f"a second `> {kind}` on this step; the first is on line {kinds[kind]}",
                    )
                else:
                    kinds[kind] = number
            before = "annotation"
        elif line.startswith(">") and not line.startswith(MARKS) and before is not None:
            if before == "annotation":
                add(number, "annotation-continued", "an annotation is one line; this line continues the one above")
            before = "continued"
        else:
            before = None


def plan_steps(lines: list[str]) -> dict[str, tuple[int, int | None]]:
    """Each step of a PLAN by its ID: the line of its heading, and the line
    of its `> Tag: hard`, or None when it carries none. A step runs from its
    heading to the next heading; of two steps with one ID the first counts."""
    steps: dict[str, tuple[int, int | None]] = {}
    current = None
    for number, line in _outside_fences(lines):
        if line is None:
            continue
        heading = HEADING.match(line)
        if heading:
            step = STEP_ID.match((heading.group(1) or "").strip())
            current = step.group(0) if step and step.group(0) not in steps else None
            if current is not None:
                steps[current] = (number, None)
        elif current is not None and line.rstrip() == HARD_MARK and steps[current][1] is None:
            steps[current] = (steps[current][0], number)
    return steps


def check_tasks(lines: list[str], add, plan: dict[str, tuple[int, int | None]] | None = None) -> None:
    """Check a TASKS file. ``plan`` is what ``plan_steps`` gave for the PLAN
    of the same sprint, or None when that PLAN is absent or was not read: a
    line's tag is then checked for its form only. A line whose ID the PLAN
    lacks is not compared either."""
    for number, line in _outside_fences(lines):
        if line is None or not line.startswith(TASKS_STARTS):
            continue
        if len(line) > TASKS_LIMIT:
            add(number, "tasks-line-too-long", f"{len(line)} characters; the limit is {TASKS_LIMIT}")
        head = TASKS_ID.match(line)
        tag = TASKS_HARD.match(line, head.end()) if head else None
        if B_TAG.search(line, tag.end() if tag else 0):
            add(number, "tasks-tag-form", "the only tag of a TASKS line is **[hard]**, once, directly after the step ID")
            continue
        if head is None or plan is None or head.group(1) not in plan:
            continue
        step = head.group(1)
        hard = plan[step][1]
        if hard is not None and tag is None:
            add(number, "tasks-tag-mismatch",
                f"{step} carries `> Tag: hard` in the PLAN (line {hard}); this line has no **[hard]**")
        elif hard is None and tag is not None:
            add(number, "tasks-tag-mismatch",
                f"this line has **[hard]**; {step} carries no `> Tag: hard` in the PLAN (line {plan[step][0]})")


# --- Links in a sprint's docs -------------------------------------------------

def check_state(lines: list[str], add) -> None:
    """Check a STATE file: at most STATE_LINES lines and STATE_CHARACTERS
    characters (code points of the file, each line break counted as one,
    a carriage return not counted). Fenced lines count."""
    if len(lines) > STATE_LINES:
        add(STATE_LINES + 1, "state-too-many-lines",
            f"{len(lines)} lines; the limit is {STATE_LINES}; cut it to the present: what happened is in git log")
    size = sum(len(line) + 1 for line in lines)
    if size > STATE_CHARACTERS:
        add(None, "state-too-long",
            f"{size} characters; the limit is {STATE_CHARACTERS}; cut it to the present: what happened is in git log")


def _without_code_spans(line: str) -> str:
    """``line`` with each code span put out of the way: a run of backticks
    opens one, and the next run of as many closes it. A run with no such
    closer is text."""
    runs = list(BACKTICKS.finditer(line))
    kept: list[str] = []
    position = 0
    index = 0
    while index < len(runs):
        opener = runs[index]
        closer = next((later for later in range(index + 1, len(runs))
                       if len(runs[later].group()) == len(opener.group())), None)
        if closer is None:
            index += 1
            continue
        kept.append(line[position:opener.start()])
        kept.append(" ")
        position = runs[closer].end()
        index = closer + 1
    kept.append(line[position:])
    return "".join(kept)


def _percent_decoded(text: str) -> str:
    """``text`` with each run of percent escapes decoded as UTF-8, as a
    browser reads a link's target (`SPRINT83%20x.md`)."""
    return PERCENT_ESCAPES.sub(
        lambda run: bytes.fromhex("".join(run.group().split("%"))).decode("utf-8", "replace"), text)


def _from_root(base: tuple[str, ...] | None, path: str) -> str | None:
    """``path``, a link's target without its anchor, as a path from the
    project root (a worktree's own root for a worktree's docs), worked out
    from the parts of the linking file's folder below that root, ``base``,
    without looking at the disk. None when ``base`` is not known, or the
    path is absolute, a drive's included, or leads above the root."""
    if base is None or path.startswith(("/", "\\")) or WINDOWS_DRIVE.match(path):
        return None
    parts = list(base)
    for part in PATH_PARTS.split(path):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or "."


def _link_fault(target: str, sprint: int | None, base: tuple[str, ...] | None = None) -> tuple[str, str] | None:
    """The rule and message for a link to ``target``, or None when the link
    may stay. ``sprint`` is the number of the sprint whose doc holds the
    link, or None for a shared file, which is checked for links to sprint
    and epic docs only. ``base`` is the linking file's folder below the
    project root, as parts, or None when it is not known."""
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith("#"):
        return None
    if URL_SCHEME.match(target) and not WINDOWS_DRIVE.match(target):
        return None
    path = _percent_decoded(re.split(r"[#?]", target, maxsplit=1)[0])
    parts = [part for part in PATH_PARTS.split(path) if part not in ("", ".")]
    name = PATH_PARTS.split(path)[-1]
    fix = f"name it instead: `{name}`"
    other = LINKED_SPRINT_DOC.match(name)
    if other and sprint is None:
        return ("link-other-sprint",
                f"a link to {target}, a doc of sprint {other.group(1)}: a file that is not archived with that sprint "
                f"names its docs and never links them, as the link breaks when the sprint is archived; {fix}")
    if LINKED_EPIC_DOC.match(name) and sprint is None:
        return ("link-epic-doc",
                f"a link to {target}, an epic doc: a file that is not archived with the epic names its docs and "
                f"never links them, as the link breaks when the epic is archived; {fix}")
    if sprint is None:
        return None  # a shared file's other links, its item links among them
    own = SPRINT_DOC_NAME.match(name)
    if own and int(own.group(1)) == sprint and len(parts) == 1:
        return None  # the sprint's own set, which sits in one folder and moves as one
    why = (f"a link to {target}, outside the sprint's set: a sprint doc links only within its own set, and this "
           "link breaks when the sprint is archived; ")
    if own and int(own.group(1)) == sprint:
        return "link-outside-set", why + f"link it by its bare file name, as the set sits in one folder: `{name}`"
    if other and int(other.group(1)) != sprint:
        return ("link-other-sprint",
                f"a link to {target}, a doc of sprint {other.group(1)}: a sprint doc links only within its own set, "
                f"and this link breaks when either sprint is archived; {fix}")
    if LINKED_EPIC_DOC.match(name):
        return ("link-epic-doc",
                f"a link to {target}, an epic doc: a sprint doc links only within its own set, and this link breaks "
                f"when the sprint or the epic is archived; {fix}")
    rooted = _from_root(base, path)
    if name.casefold() in AMBIGUOUS_NAMES:
        return "link-outside-set", why + "name it by its path from the project root" + (
            f": `{rooted}`" if rooted is not None else "")
    if name.casefold().endswith(".md"):
        return "link-outside-set", why + fix
    return "link-outside-set", why + "write the path in backticks instead, from the project root" + (
        f": `{rooted}`" if rooted is not None else "")


def check_links(lines: list[str], sprint: int | None, add, base: tuple[str, ...] | None = None) -> None:
    """Report each link that leads out of the set of a doc of sprint
    ``sprint``, or, for a shared file (``sprint`` None), each link to a
    sprint or epic doc. A fenced code block and a code span hold no link; a
    target is reported once on its line."""
    for number, line in _outside_fences(lines):
        if line is None:
            continue
        text = _without_code_spans(line)
        targets = [match.group(1) for match in INLINE_LINK.finditer(text)]
        definition = REFERENCE_DEFINITION.match(text)
        if definition and (definition.group(1).startswith("<") or PATH_LIKE.search(definition.group(1))):
            targets.append(definition.group(1))
        for target in dict.fromkeys(targets):
            fault = _link_fault(target, sprint, base)
            if fault is not None:
                add(number, *fault)


def _below(directory: Path, root: Path) -> tuple[str, ...] | None:
    """The parts of ``directory`` below ``root``, or None when it is not
    below it."""
    try:
        return directory.resolve().relative_to(root.resolve()).parts
    except (OSError, RuntimeError, ValueError):
        return None


# --- BACKLOG.md ---------------------------------------------------------------

class Backlog:
    """What the backlog check knows of the item documents, and what it found.

    ``documents`` holds the files of the folder ``BACKLOG/``, each as
    ``BACKLOG/<name>``, or is None when the folder could not be listed: then
    no document is reported missing. ``earlier`` holds the names of the
    documents at their earlier place, beside BACKLOG.md. The check adds to
    ``pointed`` the folder's documents an item points to, and to
    ``old_links`` the line of each item whose link names the earlier place.
    """

    def __init__(self, documents: set[str] | None, earlier: set[str]):
        self.documents = documents
        self.earlier = earlier
        self.pointed: set[str] = set()
        self.old_links: list[int] = []


def check_backlog(lines: list[str], backlog: Backlog, add, note) -> None:
    """Check ``BACKLOG.md``, noting in ``backlog`` the documents its items
    point to.

    A file with no pointer line and no item line is clean when it holds
    nothing but blank lines and headings; otherwise it has not been
    converted, which is a note and not a violation.
    """
    if not any(B_POINTER.match(line) or B_NUMBERED.match(line) for line in lines):
        if any(line.strip() and not line.startswith("#") for line in lines):
            note(
                None,
                "backlog-not-converted",
                "no pointer line and no numbered item: the file is in the old form; its lines were not checked",
            )
        return
    pointer = None
    items: dict[int, int] = {}
    order: list[tuple[int, int]] = []
    before = None  # "item" or "more": what the line directly above was
    for number, line in enumerate(lines, 1):
        if not line.strip():
            before = None
            continue
        if line.startswith("#"):
            before = None
            continue
        match = B_POINTER.match(line)
        if match:
            before = None
            if pointer is not None:
                add(number, "backlog-pointer-duplicate", "a second pointer line; there is exactly one")
                continue
            pointer = int(match.group(1))
            if order:
                add(number, "backlog-pointer-below-item", "the pointer line belongs above the first item")
            continue
        if line.startswith("- ") and len(line) > BACKLOG_LIMIT:
            add(number, "backlog-item-too-long", f"{len(line)} characters; the limit is {BACKLOG_LIMIT}")
        match = B_ITEM.match(line)
        if match:
            before = "item"
            item = int(match.group(1))
            if item in items:
                add(number, "backlog-number-duplicate", f"B{item} is also on line {items[item]}")
            else:
                items[item] = number
            order.append((item, number))
            if B_TAG.search(match.group(2)):
                add(
                    number,
                    "backlog-item-form",
                    "a priority tag is **[HIGH]**, **[MED]** or **[LOW]**, once, directly after the number",
                )
            _check_document_link(line, item, number, backlog, add)
        elif line.startswith("- "):
            before = "item"
            add(number, "backlog-item-form", "not of the form `- **B<n>** <text>`")
        elif line[0] in " \t" or before is not None:
            before = "more"
            add(number, "backlog-item-not-one-line", "an item is one line; this line continues or hangs under one")
        else:
            before = None
            add(number, "backlog-unknown-line", "not a heading, the pointer line or an item")
    if pointer is None:
        add(None, "backlog-pointer-missing", "the file has numbered items and no line `Latest assigned: B<n>`")
    else:
        for item, number in order:
            if item > pointer:
                add(number, "backlog-number-above-pointer", f"B{item} is above the pointer line's B{pointer}")


def _is_document_target(target: str) -> bool:
    if URL_SCHEME.match(target):
        return False
    parts = PATH_PARTS.split(target)
    return any(part.casefold() == BACKLOG_DIR.casefold() for part in parts[:-1]) or bool(
        OLD_DOCUMENT_START.match(parts[-1]))


def _check_document_link(line: str, item: int, number: int, backlog: Backlog, add) -> None:
    links = [match for match in B_LINK.finditer(line) if _is_document_target(match.group(1))]
    if not links:
        return
    if len(links) > 1:
        add(number, "backlog-document-link", "an item has at most one document")
        return
    link = links[0]
    target = link.group(1)
    old = B_OLD_DOCUMENT.match(target)
    named = old or B_DOCUMENT.match(target)
    if not named:
        add(number, "backlog-document-link", f"the link's target is `{BACKLOG_DIR}/B<n>-<slug>.md`")
        return
    if int(named.group("n")) != item:
        add(number, "backlog-document-link", f"B{item} points to the document of B{named.group('n')}")
    if link.end() != len(line):
        add(number, "backlog-document-link", "the link to the document is at the end of the line")
    documents = backlog.documents
    moved = f"{BACKLOG_DIR}/{named.group('name')}"
    if old:
        # The earlier place: one note for the backlog, not a violation for each item.
        backlog.old_links.append(number)
        if documents is not None and moved in documents:
            backlog.pointed.add(moved)  # moved already, and the link not yet changed
        elif documents is not None and target not in backlog.earlier:
            add(number, "backlog-document-missing",
                f"{target} is not beside BACKLOG.md, and the folder {BACKLOG_DIR}/ has no {named.group('name')}")
        return
    backlog.pointed.add(target)
    if documents is not None and target not in documents:
        add(number, "backlog-document-missing", f"the folder {BACKLOG_DIR}/ has no {named.group('name')}")


def _moved_name(name: str) -> str:
    """The name in the folder of a document at its earlier place:
    ``BACKLOG-B9-slug.md`` is ``B9-slug.md``, whatever the case of its start."""
    return "B" + name[len("BACKLOG-B"):]


def _earlier_place(backlog: Backlog) -> str | None:
    """The one note for item documents at their earlier place, or None."""
    earlier = sorted(backlog.earlier)
    links = backlog.old_links
    if not earlier and not links:
        return None
    parts = []
    if earlier:
        many = len(earlier) > 1
        parts.append(f"{len(earlier)} item document{'s are' if many else ' is'} at the earlier place beside "
                     f"BACKLOG.md (first: {earlier[0]})")
    if links:
        many = len(links) > 1
        parts.append(f"{len(links)} item{'s' if many else ''} link{'' if many else 's'} to that place "
                     f"(first: line {links[0]})")
    message = (" and ".join(parts) + f": move the documents into the folder {BACKLOG_DIR}/ and point the links "
               "there, as backlog-conversion.md says")
    both = [name for name in earlier if f"{BACKLOG_DIR}/{_moved_name(name)}" in (backlog.documents or ())]
    if both:
        message += (f"; {len(both)} {'are' if len(both) > 1 else 'is'} also in {BACKLOG_DIR}/ (first: {both[0]}): "
                    "compare the two copies, then delete the one beside BACKLOG.md instead of moving it")
    return message


# --- DEFERRED.md --------------------------------------------------------------

def check_deferred(lines: list[str], today: datetime.date, add, note) -> list[dict]:
    """Check ``DEFERRED.md``. Returns, in the file's order, its open items
    and the items whose state cannot be told.

    A file with no line that starts `Latest assigned:`, no title `# Deferred
    items` and no item heading, well formed or not, is clean when it holds
    nothing but blank lines and headings; otherwise it has not been
    converted, which is a note and not a violation, as for the backlog.
    Any one of the three makes it a file of the new form, so that a broken
    pointer line or a lost one is reported and not taken for the old form.
    """
    if not any(line.startswith("Latest assigned:") or line == D_TITLE or D_NUMBERED.match(line) for line in lines):
        if any(line.strip() and not line.startswith("#") for line in lines):
            note(
                None,
                "deferred-not-converted",
                "no pointer line, no title `# Deferred items` and no item heading: the file is in the old form; "
                "its lines were not checked",
            )
        return []
    pointer = None
    title_seen = False
    items: list[dict] = []
    current = None
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if line.startswith("#"):
            match = D_HEAD.match(line)
            if match or (line.startswith("###") and not line.startswith("####")):
                current = {"number": None, "title": line[3:].strip(), "line": number, "fields": {}}
                if match:
                    current["number"] = int(match.group(1))
                    current["title"] = match.group(2)
                else:
                    add(number, "deferred-heading-form", "not of the form `### D<n> — <title>`")
                items.append(current)
                if len(line) > DEFERRED_LIMIT:
                    add(number, "deferred-line-too-long", f"{len(line)} characters; the limit is {DEFERRED_LIMIT}")
            elif line == D_TITLE and not title_seen and pointer is None and not items:
                title_seen = True
            elif line == D_TITLE:
                add(number, "deferred-unknown-line", "the title is given once, above the pointer line")
            else:
                add(number, "deferred-unknown-line", "a heading that is neither the title nor an item's")
            continue
        if line.startswith("Latest assigned:"):
            match = D_POINTER.match(line)
            if not match:
                add(number, "deferred-unknown-line", "not of the form `Latest assigned: D<n>`")
            elif pointer is not None:
                add(number, "deferred-pointer-duplicate", "a second pointer line; there is exactly one")
            else:
                pointer = int(match.group(1))
                if items:
                    add(number, "deferred-pointer-below-item", "the pointer line belongs above the first item")
            continue
        name = next((field for field in D_FIELDS if line.startswith(field + ":")), None)
        if name is None or current is None:
            if current is None:
                add(number, "deferred-unknown-line", "not the title, the pointer line or a line of an item")
            else:
                add(
                    number,
                    "deferred-unknown-line",
                    "not a field: an item has no body, and a field's value is never continued",
                )
            continue
        if len(line) > DEFERRED_LIMIT:
            add(number, "deferred-line-too-long", f"{len(line)} characters; the limit is {DEFERRED_LIMIT}")
        rest = line[len(name) + 1:]
        value = rest[1:] if rest.startswith(" ") else rest
        fields = current["fields"]
        if name in fields:
            add(number, "deferred-field-duplicate", f"`{name}:` is also on line {fields[name][1]}")
            continue
        if any(D_FIELDS.index(name) < D_FIELDS.index(other) for other in fields):
            add(number, "deferred-field-order", f"`{name}:` comes after a field it belongs above")
        if not rest.startswith(" ") or not value.strip():
            add(number, "deferred-field-form", f"`{name}:` is followed by one space and a value that is not empty")
        fields[name] = (value, number)

    if pointer is None:
        add(None, "deferred-pointer-missing", "the file has no line `Latest assigned: D<n>`")
    seen: dict[int, int] = {}
    sprints: dict[str, list[dict]] = {}
    listed: list[dict] = []
    for item in items:
        fields = item["fields"]
        for name in D_REQUIRED:
            if name not in fields:
                add(item["line"], "deferred-field-missing", f"the item has no `{name}:`")
        if item["number"] is not None:
            if item["number"] in seen:
                add(item["line"], "deferred-number-duplicate", f"D{item['number']} is also on line {seen[item['number']]}")
            else:
                seen[item["number"]] = item["line"]
            if pointer is not None and item["number"] > pointer:
                add(
                    item["line"],
                    "deferred-number-above-pointer",
                    f"D{item['number']} is above the pointer line's D{pointer}",
                )
        sprint = None
        outside = False
        if "Sprint" in fields:
            value, at = fields["Sprint"]
            sprint = D_SPRINT.match(value)
            outside = value == D_NO_SPRINT
            if not sprint and not outside:
                add(at, "deferred-sprint-form", "not a sprint number and a step ID, as in `07 P3.4`, or `none`")
        review = None
        if "Review by" in fields:
            value, at = fields["Review by"]
            match = D_REVIEW.match(value)
            if not match:
                add(at, "deferred-date", "not `YYYY-MM-DD`, or `YYYY-MM-DD (re-dated YYYY-MM-DD: <reason>)`")
            elif not _is_date(match.group(1)) or (match.group(2) and not _is_date(match.group(2))):
                add(at, "deferred-date", "not a calendar date")
            else:
                review = datetime.date.fromisoformat(match.group(1))
                if match.group(2):
                    redated = datetime.date.fromisoformat(match.group(2))
                    if redated > today:
                        add(at, "deferred-date", f"the day it was re-dated, {redated}, is after today, {today}")
                    if review <= redated:
                        add(
                            at,
                            "deferred-date",
                            f"the new review date, {review}, is not later than the day it was re-dated, {redated}",
                        )
        state = None  # "open", "closed", or None when it cannot be told
        if "Status" in fields:
            value, at = fields["Status"]
            match = D_STATUS.match(value)
            if not match:
                add(at, "deferred-status-form", "not `open`, `resolved YYYY-MM-DD: <how>` or `dropped YYYY-MM-DD: <why>`")
            elif match.group(1) and not _is_date(match.group(1)):
                add(at, "deferred-date", "not a calendar date")
            else:
                state = "open" if value == "open" else "closed"
        item["state"] = state
        if outside and state == "closed":
            add(item["line"], "deferred-closed-item",
                "a closed item outside a sprint leaves the file in the change that closes it")
        if sprint:
            sprints.setdefault(sprint.group(1), []).append(item)
        if state != "closed":
            # An item whose state cannot be told is listed too: left out, an
            # open item with a mistyped status would vanish from the list.
            listed.append({
                "number": item["number"],
                "title": item["title"],
                "state": "open" if state == "open" else "unknown",
                "sprint": fields["Sprint"][0] if "Sprint" in fields else None,
                "outside_sprint": outside,
                "trigger": fields["Trigger"][0] if "Trigger" in fields else None,
                "review_by": fields["Review by"][0] if "Review by" in fields else None,
                "check": fields["Check"][0] if "Check" in fields else None,
                "past_date": review is not None and today > review,
                "line": item["line"],
            })
    for sprint_number, members in sprints.items():
        if all(member["state"] == "closed" for member in members):
            add(
                members[0]["line"],
                "deferred-closed-sprint",
                f"sprint {sprint_number} has no open item left; its closed items leave the file",
            )
    return listed


# --- The lesson index ---------------------------------------------------------

def check_index(lines: list[str], add) -> None:
    starts: list[int] = []
    ends: list[int] = []
    for number, line in _outside_fences(lines):
        if line is None:
            continue
        if line.strip() == INDEX_START:
            starts.append(number)
        elif line.strip() == INDEX_END:
            ends.append(number)
    if not starts and not ends:
        return
    for extra in starts[1:]:
        add(extra, "index-marker-duplicate", "a second start marker of the lesson index")
    for extra in ends[1:]:
        add(extra, "index-marker-duplicate", "a second end marker of the lesson index")
    if not starts:
        add(ends[0], "index-marker-unpaired", "the end marker of the lesson index has no start marker")
        return
    if not ends:
        add(starts[0], "index-marker-unpaired", "the start marker of the lesson index has no end marker")
        return
    start, end = starts[0], ends[0]
    if end < start:
        add(end, "index-marker-unpaired", "the end marker of the lesson index is above its start marker")
        return
    block = lines[start:end - 1]
    if len(block) > INDEX_LINES:
        add(start, "index-too-many-lines", f"{len(block)} lines between the markers; the limit is {INDEX_LINES}")
    for offset, line in enumerate(block):
        if len(line) > INDEX_LINE_LIMIT:
            add(start + 1 + offset, "index-line-too-long", f"{len(line)} characters; the limit is {INDEX_LINE_LIMIT}")


# --- Sprint workspaces --------------------------------------------------------
#
# Read from git's own files, never by running git: what this needs is the
# list of worktrees with the branch each has checked out, and the names of
# the branches. Nothing of the index or of the objects is read, so nothing
# is known of what is committed.

def _read_small(path: Path, limit: int) -> tuple[bytes | None, str | None]:
    """The bytes of a file of git's, or why they were not read; (None, None)
    when nothing is at ``path``. Only a regular file of at most ``limit``
    bytes is read: never a device or a pipe, which can be endless or block."""
    try:
        found = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None, ("is a link that leads nowhere" if _is_link(path) else None)
    except (OSError, ValueError) as exc:
        return None, f"cannot be read: {_reason(exc)}"
    if not stat.S_ISREG(found.st_mode):
        return None, "is not a regular file"
    if found.st_size > limit:
        return None, f"is larger than {limit} bytes; it was not read"
    try:
        return path.read_bytes(), None
    except (FileNotFoundError, NotADirectoryError):
        return None, None
    except (OSError, ValueError) as exc:
        return None, f"cannot be read: {_reason(exc)}"


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink()
    except (OSError, ValueError):
        return False


def _git_line(path: Path) -> tuple[str | None, str | None]:
    """The first line of a one-line file of git's, stripped, or why it was
    not read; (None, None) when nothing is at ``path``."""
    raw, fault = _read_small(path, LINE_FILE_LIMIT)
    if raw is None:
        return None, fault
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, f"is not UTF-8 text (byte {exc.start})"
    lines = split_lines(text)
    first = lines[0].strip() if lines else ""
    if not first:
        return None, "is empty"
    return first, None


def _foreign(value: str) -> bool:
    """Whether ``value`` is an absolute path of the other system: one git
    wrote on Windows read here, or one it wrote elsewhere read on Windows."""
    if sys.platform == "win32":
        return value.startswith("/") and not value.startswith("//")
    return bool(WINDOWS_ABSOLUTE.match(value))


def _git_path(value: str, base: Path) -> Path | None:
    """A path a file of git's holds: a relative one is taken from ``base``.
    None for a path of the other system, which cannot be looked at here."""
    if _foreign(value):
        return None
    try:
        path = Path(value)
        return path if path.is_absolute() else (base / path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _is_dir(path: Path | None) -> bool:
    try:
        return path is not None and path.is_dir()
    except (OSError, ValueError):
        return False


def _same(one: Path, other: Path) -> bool:
    try:
        return one.resolve() == other.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _without_dotgit(value: str) -> str:
    """A worktree's path from the path of its .git, as git wrote it."""
    for end in ("/.git", "\\.git"):
        if value.endswith(end):
            return value[:-len(end)]
    return value


def find_git(project: Path, note) -> tuple[Path, Path] | None:
    """The project root's git directory and the common directory, where the
    worktrees and the branches are. None when the project root holds no
    ``.git``, or what it holds cannot be followed (a note says why)."""
    dotgit = project / ".git"
    skipped = "; sprint workspaces were not looked for"
    try:
        found = dotgit.stat()
    except (FileNotFoundError, NotADirectoryError):
        if _is_link(dotgit):
            note(str(dotgit), "git-unreadable", "a link that leads nowhere" + skipped)
        return None
    except (OSError, ValueError) as exc:
        note(str(dotgit), "git-unreadable", f"cannot be read: {_reason(exc)}{skipped}")
        return None
    if stat.S_ISDIR(found.st_mode):
        gitdir, named = dotgit, str(dotgit)
    else:
        text, fault = _git_line(dotgit)
        if text is None or not text.startswith("gitdir:"):
            note(str(dotgit), "git-file-malformed", (fault or "not of the form `gitdir: <path>`") + skipped)
            return None
        named = text[len("gitdir:"):].strip()
        gitdir = _git_path(named, project)
        if not _is_dir(gitdir):
            note(str(dotgit), "git-dir-missing", f"it points to {named}, which is not a directory here{skipped}")
            return None
    if not _present(gitdir / "HEAD"):
        note(str(dotgit), "git-dir-missing", f"{named} is not a git directory: it holds no HEAD{skipped}")
        return None
    common = gitdir
    text, fault = _git_line(gitdir / "commondir")
    if fault is not None:
        note(str(gitdir / "commondir"), "git-file-malformed", fault + skipped)
        return None
    if text is not None:
        common = _git_path(text, gitdir)
        if not _is_dir(common):
            note(str(gitdir / "commondir"), "git-dir-missing",
                 f"it points to {text}, which is not a directory here{skipped}")
            return None
    return gitdir, common


def _branches(common: Path, note) -> set[str]:
    """The sprint branches: the loose refs under refs/heads/sprint/, and the
    lines of packed-refs."""
    found: set[str] = set()
    loose = common / "refs" / "heads" / "sprint"
    try:
        entries = sorted(loose.iterdir()) if loose.is_dir() else []
    except (OSError, ValueError) as exc:
        note(str(loose), "git-unreadable", f"cannot be read: {_reason(exc)}")
        entries = []
    for entry in entries:
        name = f"sprint/{entry.name}"
        try:
            if entry.is_file() and not entry.name.endswith(".lock") and SPRINT_BRANCH.match(name):
                found.add(name)
        except (OSError, ValueError):
            continue
    packed = common / "packed-refs"
    raw, fault = _read_small(packed, PACKED_REFS_LIMIT)
    if raw is None:
        if fault is not None:
            note(str(packed), "git-unreadable", f"{fault}; the branches only it names are left out")
        return found
    try:
        lines = split_lines(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        note(str(packed), "git-unreadable", f"is not UTF-8 text (byte {exc.start}); the branches only it names "
             "are left out")
        return found
    for line in lines:
        match = PACKED_REF.match(line.strip())
        if match and match.group(1).startswith(BRANCH_REF):
            name = match.group(1)[len(BRANCH_REF):]
            if SPRINT_BRANCH.match(name):
                found.add(name)
    return found


def _branch_of(directory: Path, note, what: str) -> tuple[str | None, str | None] | None:
    """The branch a working tree has checked out, read from its git
    directory, and what holds it there when its HEAD is detached: "rebase"
    or "bisect", as git counts a branch in either as checked out. None when
    the HEAD file cannot be used, which a note says."""
    file = directory / "HEAD"
    text, fault = _git_line(file)
    if text is None:
        note(str(file), "git-file-malformed", f"{fault or 'is missing'}; {what} was left out")
        return None
    match = HEAD_REF.match(text)
    if match:
        ref = match.group(1)
        return (ref[len(BRANCH_REF):] if ref.startswith(BRANCH_REF) else None), None
    if not HEAD_HASH.match(text):
        note(str(file), "git-file-malformed", f"neither `ref: <ref>` nor a commit; {what} was left out")
        return None
    for parts, busy in BUSY_FILES:
        held, _ = _git_line(directory.joinpath(*parts))
        if held is None:
            continue
        if held.startswith(BRANCH_REF):
            return held[len(BRANCH_REF):], busy
        if busy == "bisect" and not HEAD_HASH.match(held):
            return held, busy  # BISECT_START holds a branch by its short name
    return None, None


def _places(project: Path, gitdir: Path, common: Path, note) -> list[dict]:
    """Every working tree of the repository: its branch (None when it has
    none checked out), what holds a detached HEAD on it, its kind (in place,
    a worktree, one that is gone, locked or written on the other system),
    the path as shown, and the path to look in, None when there is none."""
    places: list[dict] = []

    def add(got, where: str, path: str, tree: Path | None, locked: str | None = None) -> None:
        places.append({"branch": got[0], "busy": got[1], "where": where, "path": path, "tree": tree,
                       "locked": locked})

    got = _branch_of(gitdir, note, "the project root")
    if got is not None:
        add(got, IN_PLACE, str(project), project)
    linked = not _same(gitdir, common)
    if linked and common.name == ".git":
        # The project root is itself a linked worktree; the main one is common's parent.
        got = _branch_of(common, note, "the main working tree")
        if got is not None:
            add(got, WORKTREE, str(common.parent), common.parent)
    admin_root = common / "worktrees"
    try:
        admins = sorted(admin_root.iterdir()) if admin_root.is_dir() else []
    except (OSError, ValueError) as exc:
        note(str(admin_root), "git-unreadable", f"cannot be read: {_reason(exc)}")
        admins = []
    for admin in admins:
        if not _is_dir(admin) or (linked and _same(admin, gitdir)):
            continue
        value, fault = _git_line(admin / "gitdir")
        if value is None:
            note(str(admin / "gitdir"), "git-file-malformed", f"{fault or 'is missing'}; this worktree was left out")
            continue
        got = _branch_of(admin, note, "this worktree")
        if got is None:
            continue
        locked = (_git_line(admin / "locked")[0] or "") if _present(admin / "locked") else None
        if _foreign(value):
            # Written by git on the other system: shown as written, never looked at.
            add(got, FOREIGN, _without_dotgit(value), None, locked)
            continue
        dotgit = _git_path(value, admin)
        if dotgit is None:
            add(got, LOCKED if locked is not None else PRUNABLE, _without_dotgit(value), None, locked)
        elif _same(dotgit.parent, project):
            add(got, IN_PLACE, str(project), project, locked)
        elif _present(dotgit) and _is_dir(dotgit.parent):
            add(got, WORKTREE, str(dotgit.parent), dotgit.parent, locked)
        else:
            # Git prunes a worktree whose .git is gone, unless it is locked.
            add(got, LOCKED if locked is not None else PRUNABLE, str(dotgit.parent), None, locked)
    return places


def _map_docs(docs: Path, trees: list[Path]) -> Path | None:
    """The docs directory's path inside the working tree it is in, the
    deepest one (a worktree may sit inside the project root). None when it
    is in none, or in a repository of its own inside one: then it is one
    directory for every worktree, mapped into none."""
    best = None
    try:
        docs_real = docs.resolve()
        for tree in trees:
            tree_real = tree.resolve()
            if docs_real.is_relative_to(tree_real):
                relative = docs_real.relative_to(tree_real)
                if best is None or len(relative.parts) < len(best[1].parts):
                    best = (tree_real, relative)
    except (OSError, RuntimeError, ValueError):
        return None
    if best is None:
        return None
    tree_real, relative = best
    for depth in range(len(relative.parts), 0, -1):
        if _present(tree_real.joinpath(*relative.parts[:depth]) / ".git"):
            return None
    return relative


def _branch_order(branch: str) -> tuple[int, str]:
    number, slug = SPRINT_BRANCH.match(branch).groups()
    return int(number), slug


def sprint_workspaces(project: Path, docs: Path, adder, note) -> tuple[str | None, list[dict] | None]:
    """The common git directory, or None when there is none to read, and an
    entry for each sprint branch: where it is checked out, which of the
    sprint's own docs are there, and, for a worktree, the check of those
    docs. The shared files of a worktree are stale copies: never read.
    The entries are None when the refs are in a form this does not read."""
    found = find_git(project, note)
    if found is None:
        return None, []
    gitdir, common = found
    if _is_dir(common / "reftable") or _git_line(gitdir / "HEAD")[0] == REFTABLE_HEAD:
        note(str(common), "git-reftable", "the refs are in the reftable format, which this command does not read; "
             "sprint workspaces were not looked for")
        return str(common), None
    places = _places(project, gitdir, common, note)
    mapped = _map_docs(docs, [project] + [place["tree"] for place in places if place["tree"] is not None])
    ours = [place for place in places if place["branch"] is not None and SPRINT_BRANCH.match(place["branch"])]
    branches = _branches(common, note) | {place["branch"] for place in ours}
    entries: list[dict] = []
    for branch in sorted(branches, key=_branch_order):
        number, slug = SPRINT_BRANCH.match(branch).groups()
        own = {f"SPRINT{number}-{kind}-{slug}.md": kind for kind in SPRINT_KINDS}
        for place in [place for place in ours if place["branch"] == branch] or [None]:
            entry = {"branch": branch, "where": NOWHERE, "path": None, "busy": None, "locked": None, "docs": None,
                     "docs_state": "not-read", "found": []}
            entries.append(entry)
            if place is None:
                continue
            entry.update(where=place["where"], path=place["path"], busy=place["busy"], locked=place["locked"])
            tree = place["tree"]
            if tree is None:
                continue
            if mapped is None:
                entry["docs_state"] = "outside"
                continue
            there = tree / mapped
            entry["docs"] = str(there)
            if not _is_dir(there):
                entry["docs_state"] = "no-directory"
                continue
            try:
                listed = {item.name for item in there.iterdir()}
            except (OSError, ValueError) as exc:
                note(str(there), "git-unreadable", f"cannot be read: {_reason(exc)}")
                entry["docs_state"] = "unreadable"
                continue
            entry["docs_state"] = "read"
            entry["found"] = [kind for name, kind in own.items() if name in listed]
            if _same(there, docs):
                # The docs directory itself, checked above: in place, or named with --docs.
                if place["where"] == IN_PLACE:
                    note(str(docs), "shared-files-on-sprint-branch",
                         f"the project root has {branch} checked out: the backlog, the deferred items and the "
                         "index were read from that branch's copies, which may be stale; they are current on the "
                         "default branch")
                continue
            plan = None
            for name, kind in own.items():
                if name not in listed:
                    continue
                file = str(there / name)
                lines, fault = read_lines(there / name, there)
                if fault is not None:
                    adder(file)(None, *fault)
                    continue
                if kind == "PLAN":
                    check_plan(lines, adder(file))
                    plan = plan_steps(lines)
                elif kind == "TASKS":
                    check_tasks(lines, adder(file), plan)
                elif kind == "STATE":
                    check_state(lines, adder(file))
                check_links(lines, int(number), adder(file), mapped.parts)
    return str(common), entries


# --- The report ---------------------------------------------------------------

def build_report(project: Path, docs: Path, docs_from: str, settings: dict, today: datetime.date) -> dict:
    try:
        names = sorted(entry.name for entry in docs.iterdir())
    except OSError as exc:
        raise CheckError(f"{docs}: the sprint docs directory cannot be read: {_reason(exc)}") from None
    violations: list[dict] = []
    notes: list[dict] = []

    def adder(file: str, to: list[dict] | None = None):
        found = violations if to is None else to

        def add(line: int | None, rule: str, message: str) -> None:
            found.append({"file": file, "line": line, "rule": rule, "message": message})
        return add

    def lines_of(name: str, directory: Path) -> list[str] | None:
        lines, fault = read_lines(directory / name, directory)
        if fault is not None:
            adder(name)(None, *fault)
        return lines

    deferred: list[dict] = []
    if DEFERRED_FILE in names:
        lines = lines_of(DEFERRED_FILE, docs)
        if lines is not None:
            deferred = check_deferred(lines, today, adder(DEFERRED_FILE), adder(DEFERRED_FILE, notes))
    for name in names:
        if name != BACKLOG_DIR and name.casefold() == BACKLOG_DIR.casefold():
            adder(name)(None, "backlog-folder-case",
                        f"differs from {BACKLOG_DIR} only in case: the item documents are in the folder "
                        f"{BACKLOG_DIR}, in capitals; rename this one, or move what it holds into {BACKLOG_DIR}")
    documents, fault = backlog_documents(docs, names)
    if fault is not None:
        adder(BACKLOG_DIR)(None, *fault)
    backlog = Backlog(documents, {name for name in names if OLD_DOCUMENT_NAME.match(name)})
    if BACKLOG_FILE in names:
        lines = lines_of(BACKLOG_FILE, docs)
        if lines is not None:
            check_backlog(lines, backlog, adder(BACKLOG_FILE), adder(BACKLOG_FILE, notes))
            check_links(lines, None, adder(BACKLOG_FILE))
        else:
            backlog.pointed = set(documents or ())  # unknown: report no orphan
    for name in sorted(documents or ()):
        if name.endswith(".md") and name not in backlog.pointed:
            adder(name)(None, "backlog-document-orphan", "no item of BACKLOG.md points to this document")
    message = _earlier_place(backlog)
    if message:
        adder(BACKLOG_FILE, notes)(None, "backlog-documents-earlier-place", message)
    # The other files that are never archived with a sprint: they name its docs.
    for name in sorted(name for name in documents or () if name.endswith(".md")) + sorted(backlog.earlier) + (
            [CONTEXT_FILE] if CONTEXT_FILE in names else []):
        lines = lines_of(name, docs)
        if lines is not None:
            check_links(lines, None, adder(name))
    # A PLAN's name sorts before the name of the TASKS of the same sprint.
    plans: dict[str, dict] = {}
    base = _below(docs, project)
    for name in names:
        own = SPRINT_DOC_NAME.match(name)
        if own is None:
            continue
        lines = lines_of(name, docs)
        if lines is None:
            continue
        if PLAN_NAME.match(name):
            check_plan(lines, adder(name))
            plans[name] = plan_steps(lines)
        elif TASKS_NAME.match(name):
            check_tasks(lines, adder(name), plans.get(TASKS_PAIR.sub(r"\1-PLAN-\2", name)))
        elif STATE_NAME.match(name):
            check_state(lines, adder(name))
        check_links(lines, int(own.group(1)), adder(name), base)
    if _present(project / AGENTS_FILE):
        lines = lines_of(AGENTS_FILE, project)
        if lines is not None:
            check_index(lines, adder(AGENTS_FILE))

    def note(file: str, rule: str, message: str) -> None:
        notes.append({"file": file, "line": None, "rule": rule, "message": message})
    git, workspaces = sprint_workspaces(project, docs, adder, note)
    # A sprint doc that was checked in the sprint's worktree is not reported
    # again from the docs directory: the copy there is the start commit's.
    checked = set()
    for entry in workspaces or ():
        if entry["docs_state"] == "read" and not _same(Path(entry["docs"]), docs):
            number, slug = SPRINT_BRANCH.match(entry["branch"]).groups()
            checked.update(f"SPRINT{number}-{kind}-{slug}.md" for kind in entry["found"])
    violations[:] = [violation for violation in violations if violation["file"] not in checked]

    # In the order the files were checked, and by line within a file.
    files = list(dict.fromkeys(violation["file"] for violation in violations))
    violations.sort(key=lambda violation: (files.index(violation["file"]), violation["line"] or 0))
    for item in deferred:
        item["file"] = DEFERRED_FILE
    past = sum(1 for item in deferred if item["past_date"])
    unknown = sum(1 for item in deferred if item["state"] == "unknown")
    return {
        "schema_version": SCHEMA_VERSION,
        "today": today.isoformat(),
        "project": str(project),
        "docs": str(docs),
        "docs_from": docs_from,
        "settings": settings,
        "deferred": deferred,
        "git": git,
        "sprint_workspaces": workspaces,
        "violations": violations,
        "notes": notes,
        "summary": {
            "open": len(deferred) - unknown,
            "state_unknown": unknown,
            "past_date": past,
            "violations": len(violations),
            "notes": len(notes),
        },
        "exit_code": EXIT_ACTION if past or unknown or violations else EXIT_OK,
    }


def _unsafe(char: str) -> bool:
    return unicodedata.category(char) in _ESCAPED


def shown(text: str) -> str:
    """``text`` for the text report and for an error: one line whatever it
    holds, with every control and format character as an escape."""
    return "".join(
        (f"\\u{ord(char):04x}" if ord(char) <= 0xFFFF else f"\\U{ord(char):08x}") if _unsafe(char) else char
        for char in text
    )


def _json_escape(char: str) -> str:
    code = ord(char)
    if code <= 0xFFFF:
        return f"\\u{code:04x}"
    code -= 0x10000
    return f"\\u{0xD800 + (code >> 10):04x}\\u{0xDC00 + (code & 0x3FF):04x}"


def _workspace_line(entry: dict) -> str:
    """One sprint branch, on one line: where it is, and its docs there."""
    branch = shown(entry["branch"])
    if entry["where"] == NOWHERE:
        return f"{branch}: checked out nowhere, a branch only; its docs were not read"
    path = shown(entry["path"])
    if entry["where"] == PRUNABLE:
        return f"{branch}: worktree {path} is missing (git calls it prunable); its docs were not read"
    if entry["where"] == LOCKED:
        why = f"locked: {shown(entry['locked'])}" if entry["locked"] else "locked"
        return f"{branch}: worktree {path} is missing ({why}); its docs were not read"
    if entry["where"] == FOREIGN:
        return f"{branch}: worktree {path} was written by git on another system; not looked at"
    place = "in place" if entry["where"] == IN_PLACE else f"worktree {path}"
    if entry["busy"] is not None:
        place += f" (mid-{entry['busy']})"
    state = entry["docs_state"]
    if state == "outside":
        return f"{branch}: {place}; the docs directory is outside the repository, one for every worktree"
    if state == "no-directory":
        return f"{branch}: {place}; no docs directory there"
    if state == "unreadable":
        return f"{branch}: {place}; its docs directory cannot be read"
    return f"{branch}: {place}; docs there: {', '.join(entry['found']) or 'none'}"


def render_text(report: dict) -> str:
    """The text report. It is made from the JSON report's content alone."""
    settings = report["settings"]
    summary = report["summary"]
    out = [
        f"today: {report['today']}",
        f"project: {shown(report['project'])}",
        f"docs: {shown(report['docs'])}  ({report['docs_from']})",
    ]
    for key in sorted(settings):
        out.append(f"{key} = {shown(json.dumps(settings[key]['value'], ensure_ascii=False))}  ({settings[key]['layer']})")
    out.append("")
    out.append(
        f"Deferred items: {summary['open']} open, {summary['state_unknown']} state unknown, "
        f"{summary['past_date']} past its date"
    )
    for item in report["deferred"]:
        number = "D?" if item["number"] is None else f"D{item['number']}"
        flags = ("  [STATE UNKNOWN]" if item["state"] == "unknown" else "") + (
            "  [PAST ITS DATE]" if item["past_date"] else "")
        out.append("")
        out.append(f"{number} — {shown(item['title'])}{flags}")
        for label, key in (("sprint", "sprint"), ("trigger", "trigger"), ("review by", "review_by")):
            out.append(f"  {label}: " + ("(missing)" if item[key] is None else shown(item[key])))
            if key == "sprint" and item["outside_sprint"]:
                out[-1] += " (outside a sprint)"
        out.append("  no check named" if item["check"] is None else f"  check: {shown(item['check'])}")
        out.append(f"  at: {shown(item['file'])}:{item['line']}")
    if report["git"] is not None and report["sprint_workspaces"] is None:
        out.append("")
        out.append("Sprint workspaces: not looked for (see Notes)")
    elif report["git"] is not None:
        out.append("")
        out.append(f"Sprint workspaces: {len(report['sprint_workspaces'])}")
        out.extend(_workspace_line(entry) for entry in report["sprint_workspaces"])
    for title, key in (("Violations", "violations"), ("Notes", "notes")):
        out.append("")
        out.append(f"{title}: {summary[key]}")
        for entry in report[key]:
            place = entry["file"] if entry["line"] is None else f"{entry['file']}:{entry['line']}"
            out.append(f"{shown(place)}: {entry['rule']}: {shown(entry['message'])}")
    out.append("")
    out.append("Result: " + ("action needed" if report["exit_code"] else "nothing needs action"))
    return "\n".join(out) + "\n"


def render_json(report: dict) -> str:
    """The JSON report. A character the text report shows as an escape is a
    ``\\u`` escape here too; it can only stand inside a string, and the
    newlines between the lines of the document are left as they are."""
    text = json.dumps(report, indent=2, ensure_ascii=False)
    return "".join(_json_escape(char) if char != "\n" and _unsafe(char) else char for char in text) + "\n"


# --- The command --------------------------------------------------------------

def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(
        prog="check.py",
        allow_abbrev=False,
        description="List the open deferred items and the sprint workspaces, and report format violations. "
                    "It executes nothing.",
    )
    parser.add_argument("--project", metavar="DIR", help="the project root; without it, the working directory")
    parser.add_argument(
        "--docs", metavar="DIR", help="the sprint docs directory, in place of the setting process.docs_dir"
    )
    parser.add_argument(
        "--today", metavar="DATE", help="the date to compare `Review by:` with, YYYY-MM-DD, in place of today's"
    )
    parser.add_argument("--json", action="store_true", help="the same report as JSON")
    parser.add_argument(
        "--home", metavar="DIR", help="use DIR in place of the user's home directory (for tests and trial runs)"
    )
    return parser.parse_args(argv)


def _directory(text: str, option: str) -> Path:
    """The directory an option names, as the setup tool takes one: an empty
    value is refused, and a ``~`` at its start is expanded."""
    if not text.strip():
        raise CheckError(f"{option}: an empty value is not a directory; name one, or leave the option out")
    try:
        path = Path(text).expanduser()
    except (RuntimeError, KeyError):
        raise CheckError(f"{option}: {text}: the home directory of that user cannot be found") from None
    if _kind(path) != DIRECTORY:
        raise CheckError(f"{option}: {text}: not a directory")
    return path


def run(argv: list[str] | None = None) -> tuple[int, str]:
    """Run the command. Returns its exit code and what it prints to stdout."""
    args = _parse(argv)
    if args.today is None:
        today = datetime.date.today()
    elif DATE_ONLY.match(args.today) and _is_date(args.today):
        today = datetime.date.fromisoformat(args.today)
    else:
        raise CheckError(f"--today: {args.today}: not a date of the form YYYY-MM-DD")
    if args.project is not None:
        project = _directory(args.project, "--project")
    else:
        try:
            project = Path.cwd()
        except OSError as exc:
            raise CheckError(
                f"the working directory cannot be read: {_reason(exc)}; name the project with --project DIR"
            ) from None
    home = None if args.home is None else _directory(args.home, "--home")
    settings = read_settings(project, home)
    if args.docs is not None:
        if not args.docs.strip():
            raise CheckError("--docs: an empty value is not a directory")
        docs, docs_from = Path(args.docs), "--docs"
    elif DOCS_DIR not in settings:
        raise CheckError(f"{DOCS_DIR}: set in no settings file; name the sprint docs directory with --docs DIR")
    else:
        docs, docs_from = project / settings[DOCS_DIR]["value"], DOCS_DIR
    try:
        found = docs.is_dir()
    except (OSError, ValueError):
        found = False
    if not found:
        raise CheckError(f"{docs}: the sprint docs directory ({docs_from}) is not a directory")
    report = build_report(project, docs, docs_from, settings, today)
    return report["exit_code"], render_json(report) if args.json else render_text(report)


def _print(stream, text: str) -> None:
    """Write ``text`` as UTF-8 with LF, whatever the stream's own encoding."""
    data = text.encode("utf-8", errors="backslashreplace")
    try:
        binary = stream.buffer
    except AttributeError:
        stream.write(data.decode("utf-8"))
        return
    stream.flush()
    binary.write(data)
    binary.flush()


def main(argv: list[str] | None = None) -> int:
    try:
        code, text = run(argv)
    except CheckError as exc:
        _print(sys.stderr, f"error: {shown(str(exc))}\n")
        return EXIT_ERROR
    except RecursionError:
        _print(sys.stderr, "error: the input is nested too deeply to read\n")
        return EXIT_ERROR
    except OSError as exc:
        # What no part of the command handled: still one line, never a traceback.
        why = _reason(exc)
        _print(sys.stderr, "error: " + shown(why if exc.filename is None else f"{exc.filename}: {why}") + "\n")
        return EXIT_ERROR
    _print(sys.stdout, text)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
