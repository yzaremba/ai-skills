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

    DEFERRED.md and BACKLOG.md in the sprint docs directory, and the names
    of the BACKLOG-B<n>-<slug>.md files beside them (the names only)
    SPRINTNN-PLAN-*.md and SPRINTNN-TASKS-*.md there; never DONE/
    AGENTS.md in the project root, for the lesson index: the block between
    the lines <!-- project-memory:index:start --> and
    <!-- project-memory:index:end -->

The forms it checks are defined in this skill's references: deferred.md,
stage-0-backlog.md, and "Format limits" in conventions.md. Length is the
number of characters (code points) of a line without its newline and
without one carriage return before it; every limit is inclusive. A file in
which a carriage return stands anywhere but directly before a newline is
reported (line-endings) and not checked further.

A file is read only if, with every link in its path followed, it is still
inside the directory it was looked for in: the sprint docs directory, or
the project root for AGENTS.md. A link that leads outside is reported and
not read. The docs directory itself is taken as named, link or not.

The report has three parts. The deferred items: every item that is open,
and every item whose state cannot be told (its "Status:" is missing or
malformed), which is marked so. The violations. And the notes: facts that
need no action, such as a BACKLOG.md still in the old form. A note is not
a violation and has no effect on the exit code.

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
SETTINGS_GROUPS = ("process", "roles", "memory", "providers")
GROUP = "process"
# Each key of the group: its type, and the values allowed when not every one is.
PROCESS_KEYS = {
    "docs_dir": ("string", ()),
    "questions": ("string", ("one-at-a-time", "all-together")),
    "recommend": ("boolean", ()),
}
DOCS_DIR = "process.docs_dir"

# The process group of scripts/settings.py and of tools/setup/defaults.toml.
BUILT_IN = {
    "process.docs_dir": "docs",
    "process.questions": "one-at-a-time",
    "process.recommend": True,
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
BACKLOG_LIMIT = 300
DEFERRED_LIMIT = 300
INDEX_LINES = 50
INDEX_LINE_LIMIT = 150

DEFERRED_FILE = "DEFERRED.md"
BACKLOG_FILE = "BACKLOG.md"
AGENTS_FILE = "AGENTS.md"
INDEX_START = "<!-- project-memory:index:start -->"
INDEX_END = "<!-- project-memory:index:end -->"

PLAN_NAME = re.compile(r"^SPRINT[0-9]{2,}-PLAN-.+\.md$")
TASKS_NAME = re.compile(r"^SPRINT[0-9]{2,}-TASKS-.+\.md$")
DOCUMENT_NAME = re.compile(r"^BACKLOG-B([0-9]+)-.*\.md$")

DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
DATE_ONLY = re.compile(rf"^{DATE}$")

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*))?$")
STEP_ID = re.compile(r"^P[0-9]+\.[0-9]+(?![0-9A-Za-z])")
ANNOTATIONS = (("> Landed ", "Landed"), ("> Bug fix ", "Bug fix"), ("> Audit ", "Audit"))
MARKS = ("> Depends on:", "> Parallel:", "> Tag:")
TASKS_STARTS = ("- [ ]", "- [~]", "- [x]")

B_POINTER = re.compile(r"^Latest assigned: B([1-9][0-9]*)$")
B_ITEM = re.compile(r"^- \*\*B([1-9][0-9]*)\*\* (?:\*\*\[(?:HIGH|MED|LOW)\]\*\* )?(\S.*)$")
B_NUMBERED = re.compile(r"^- \*\*B[0-9]+\*\*")
B_TAG = re.compile(r"\*\*\[[^\]]*\]\*\*")
B_LINK = re.compile(r"\]\(([^)]*)\)")
B_DOCUMENT = re.compile(r"^BACKLOG-B([1-9][0-9]*)-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")

D_TITLE = "# Deferred items"
D_POINTER = re.compile(r"^Latest assigned: D([1-9][0-9]*)$")
D_HEAD = re.compile(r"^### D([1-9][0-9]*) — (\S.*)$")
D_FIELDS = ("Sprint", "Trigger", "Review by", "Check", "Status")
D_REQUIRED = ("Sprint", "Trigger", "Review by", "Status")
D_SPRINT = re.compile(r"^([0-9]{2,}) (P[0-9]+\.[0-9]+)$")
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
        if actual != wanted:
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


def check_tasks(lines: list[str], add) -> None:
    for number, line in _outside_fences(lines):
        if line is not None and line.startswith(TASKS_STARTS) and len(line) > TASKS_LIMIT:
            add(number, "tasks-line-too-long", f"{len(line)} characters; the limit is {TASKS_LIMIT}")


# --- BACKLOG.md ---------------------------------------------------------------

def check_backlog(lines: list[str], names: set[str], add, note) -> set[str]:
    """Check ``BACKLOG.md``. Returns the item documents its items point to.

    A file with no pointer line and no item line is clean when it holds
    nothing but blank lines and headings; otherwise it has not been
    converted, which is a note and not a violation.
    """
    pointed: set[str] = set()
    if not any(B_POINTER.match(line) or B_NUMBERED.match(line) for line in lines):
        if any(line.strip() and not line.startswith("#") for line in lines):
            note(
                None,
                "backlog-not-converted",
                "no pointer line and no numbered item: the file is in the old form; its lines were not checked",
            )
        return pointed
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
            _check_document_link(line, item, number, names, pointed, add)
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
    return pointed


def _check_document_link(line: str, item: int, number: int, names: set[str], pointed: set[str], add) -> None:
    links = [match for match in B_LINK.finditer(line) if "BACKLOG-B" in match.group(1)]
    if not links:
        return
    if len(links) > 1:
        add(number, "backlog-document-link", "an item has at most one document")
        return
    link = links[0]
    target = link.group(1)
    named = B_DOCUMENT.match(target)
    if not named:
        add(number, "backlog-document-link", "the link's target is the file name `BACKLOG-B<n>-<slug>.md`")
        return
    pointed.add(target)
    if int(named.group(1)) != item:
        add(number, "backlog-document-link", f"B{item} points to the document of B{named.group(1)}")
    if link.end() != len(line):
        add(number, "backlog-document-link", "the link to the document is at the end of the line")
    if target not in names:
        add(number, "backlog-document-missing", f"{target} is not in the sprint docs directory")


# --- DEFERRED.md --------------------------------------------------------------

def check_deferred(lines: list[str], today: datetime.date, add) -> list[dict]:
    """Check ``DEFERRED.md``. Returns, in the file's order, its open items
    and the items whose state cannot be told."""
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
        if "Sprint" in fields:
            value, at = fields["Sprint"]
            sprint = D_SPRINT.match(value)
            if not sprint:
                add(at, "deferred-sprint-form", "not a sprint number and a step ID, as in `07 P3.4`")
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
            deferred = check_deferred(lines, today, adder(DEFERRED_FILE))
    pointed: set[str] = set()
    if BACKLOG_FILE in names:
        lines = lines_of(BACKLOG_FILE, docs)
        if lines is not None:
            pointed = check_backlog(lines, set(names), adder(BACKLOG_FILE), adder(BACKLOG_FILE, notes))
        else:
            pointed = {name for name in names if DOCUMENT_NAME.match(name)}  # unknown: report no orphan
    for name in names:
        if DOCUMENT_NAME.match(name) and name not in pointed:
            adder(name)(None, "backlog-document-orphan", "no item of BACKLOG.md points to this document")
    for name in names:
        if PLAN_NAME.match(name) or TASKS_NAME.match(name):
            lines = lines_of(name, docs)
            if lines is not None:
                (check_plan if PLAN_NAME.match(name) else check_tasks)(lines, adder(name))
    if _present(project / AGENTS_FILE):
        lines = lines_of(AGENTS_FILE, project)
        if lines is not None:
            check_index(lines, adder(AGENTS_FILE))

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
        out.append("  no check named" if item["check"] is None else f"  check: {shown(item['check'])}")
        out.append(f"  at: {shown(item['file'])}:{item['line']}")
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
        description="List the open deferred items and report format violations. It executes nothing.",
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
