"""Setup's part of a text file the user owns: marked blocks, and exact lines.

Everything here works on bytes and touches nothing on disk.

A block is the lines from a start marker to its end marker, both included:

    <!-- workflow-setup:start -->          Markdown (``CLAUDE.md``, ``AGENTS.md``)
    ...
    <!-- workflow-setup:end -->

    # workflow-setup:start codex-settings  ``.gitignore`` and TOML
    ...
    # workflow-setup:end codex-settings

A block may have a name (lower-case letters, digits and ``-``), written
after ``start`` and after ``end``, so one file can hold several. The block
without a name is its own block. A marker is a whole line; spaces around it
are allowed, and a sentence that merely mentions the words is not a marker.

What is refused, with the line number, before anything is changed: a start
without its end, an end without its start, an end whose name is not the
open block's, a start inside an open block (nesting), a second block of the
same name, and a marker with a name that is not one.

What is kept: every byte outside the block. The block takes the file's own
line ending (CRLF where the file has more CRLF than LF line ends, LF
otherwise and in a new file). A byte order mark stays first. A file that
does not end in a line ending still does not once the block is taken out.

Where a new block goes:

    END   after everything: one line ending, then the block. A file whose
          last line had no ending so gets the block on the next line, and
          every other file a blank line before it.
    HEAD  before everything (after a byte order mark): the block, one line
          ending, then the file. Needed where the block must come before
          the first table of a TOML file.

An empty file gets the block alone. Taking a block out removes its lines and
the one line ending that was put there with it, so add-then-remove gives
back the bytes it started from:

    nothing after the block   the line ending before it goes (END)
    nothing before it         the line ending after it goes (HEAD)

That is right for a file nobody changed in between. For one that may have
been changed, ``joint`` says, when a block is added, which line ending was
put there with it, and ``drop`` given that takes out exactly that line
ending and only while it is still there:

    a blank line before the block   goes if a blank line is still there
    the ending of a last line that  goes if that same line is still the
    had none                        one before the block, and nothing
                                    follows the block
    a blank line after the block    goes if a blank line is still there
    nothing (the file was created   nothing goes but the block
    with the block alone)

So a line of the user's never loses its own line ending, and no two lines
of the user's are ever joined. Without a ``joint`` and with text on both
sides, a blank line next to the block goes, the one after it first; where
there is none, nothing but the block goes.

In a TOML file a marker is looked for only outside multi-line strings: a
line of such a string that reads like a marker is the string's text.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

END = "end"
HEAD = "head"

MARKDOWN = "markdown"
GITIGNORE = "gitignore"
TOML = "toml"
SYNTAXES = (MARKDOWN, GITIGNORE, TOML)

WORD = "workflow-setup"
BOM = b"\xef\xbb\xbf"

_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_MARKERS = {
    MARKDOWN: re.compile(rb"^[ \t]*<!--[ \t]*workflow-setup:(start|end)(?:[ \t]+(\S+?))?[ \t]*-->[ \t]*$"),
    GITIGNORE: re.compile(rb"^[ \t]*#[ \t]*workflow-setup:(start|end)(?:[ \t]+(\S+))?[ \t]*$"),
}
_MARKERS[TOML] = _MARKERS[GITIGNORE]


MARKERS = "markers"
NOT_TEXT = "not-text"
BAD_BLOCK = "bad-action"


class Refusal(Exception):
    """Why a text file cannot be edited, in one line without the file name.
    code tells the three reasons apart: the file's markers, the file's
    bytes, or the block that was asked for."""

    def __init__(self, reason: str, code: str = MARKERS) -> None:
        super().__init__(reason)
        self.code = code


def syntax_for(name: str) -> str | None:
    """The comment syntax of a file called ``name``, where the name tells."""
    lowered = name.lower()
    if lowered.endswith(".md"):
        return MARKDOWN
    if lowered == ".gitignore":
        return GITIGNORE
    if lowered.endswith(".toml"):
        return TOML
    return None


def valid_name(name: str) -> bool:
    return name == "" or _NAME.fullmatch(name) is not None


def marker(syntax: str, which: str, name: str = "") -> str:
    words = f"{WORD}:{which}" + (f" {name}" if name else "")
    return f"<!-- {words} -->" if syntax == MARKDOWN else f"# {words}"


def split_bom(data: bytes) -> tuple[bytes, bytes]:
    return (BOM, data[len(BOM):]) if data.startswith(BOM) else (b"", data)


def check_text(data: bytes) -> None:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal(f"is not UTF-8 text (byte {exc.start})", NOT_TEXT) from None


def eol_of(body: bytes) -> bytes:
    """The file's line ending: CRLF where it has the majority."""
    crlf = body.count(b"\r\n")
    return b"\r\n" if crlf > body.count(b"\n") - crlf else b"\n"


def _lines(body: bytes) -> list[bytes]:
    """The lines, each with its ending. Only LF and CRLF end a line: a
    lone CR stays inside its line, where ``splitlines`` would cut."""
    return re.findall(rb"[^\n]*\n|[^\n]+", body)


def _bare(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    return line[:-1] if line.endswith(b"\n") else line


def _ending(line: bytes) -> bytes:
    return line[len(_bare(line)):]


def scan(body: bytes, syntax: str) -> dict[str, tuple[int, int]]:
    """Every block in ``body``: name to the indexes of its first line and of
    the line after its last. Any fault in the markers is a ``Refusal``."""
    pattern = _MARKERS[syntax]
    found: dict[str, tuple[int, int]] = {}
    opened: tuple[str, int] | None = None
    lines = _lines(body)
    inside = _toml_string_lines(lines) if syntax == TOML else frozenset()
    for index, line in enumerate(lines):
        if index in inside:
            continue  # text of a multi-line string, whatever it looks like
        match = pattern.match(_bare(line))
        if match is None:
            continue
        which = match.group(1).decode("ascii")
        name = (match.group(2) or b"").decode("utf-8", "replace")
        where = f"line {index + 1}"
        label = f"{WORD}:{which}" + (f" {name}" if name else "")
        if not valid_name(name):
            raise Refusal(f"{where}: {label}: not a block name setup writes")
        if which == "start":
            if opened is not None:
                raise Refusal(
                    f"{where}: {label} inside the block opened on line {opened[1] + 1}: "
                    f"a {WORD}:end is missing, or blocks are nested"
                )
            if name in found:
                raise Refusal(f"{where}: {label}: a second block of that name")
            opened = (name, index)
        else:
            if opened is None:
                raise Refusal(f"{where}: {label} without a {WORD}:start before it")
            if opened[0] != name:
                raise Refusal(f"{where}: {label} does not close the block opened on line {opened[1] + 1}")
            found[name] = (opened[1], index + 1)
            opened = None
    if opened is not None:
        label = f"{WORD}:start" + (f" {opened[0]}" if opened[0] else "")
        raise Refusal(f"line {opened[1] + 1}: {label} without a {WORD}:end")
    return found


def _toml_string_lines(lines: list[bytes]) -> frozenset[int]:
    """The indexes of the lines of a TOML file that begin inside a
    multi-line string (three double or three single quotes). Such a line
    is the string's text: a ``#`` there starts no comment, so it is no
    marker either.

    A small scanner, not a parser: it knows comments, the two one-line
    strings (which end with their line at the latest) and the two
    multi-line ones, with the backslash of the double-quoted kinds. A file
    that is not TOML gets some answer; ``fileops`` parses the file for real
    before and after any change.
    """
    inside: set[int] = set()
    open_with: bytes | None = None  # the three quotes of the open multi-line string
    for index, line in enumerate(lines):
        if open_with is not None:
            inside.add(index)
        at, end = 0, len(line)
        while at < end:
            if open_with is not None:
                if open_with == b'"""' and line[at:at + 1] == b"\\":
                    at += 2
                    continue
                if line[at:at + 3] == open_with:
                    # Up to two more quotes may belong to the text; the
                    # string ends with the last three of the run.
                    while line[at + 3:at + 4] == open_with[:1]:
                        at += 1
                    at += 3
                    open_with = None
                    continue
                at += 1
                continue
            char = line[at:at + 1]
            if char == b"#":
                break  # a comment, to the end of the line
            if line[at:at + 3] in (b'"""', b"'''"):
                open_with = line[at:at + 3]
                at += 3
                continue
            if char in (b'"', b"'"):
                at += 1
                while at < end and line[at:at + 1] != char:
                    at += 2 if char == b'"' and line[at:at + 1] == b"\\" else 1
                at += 1
                continue
            at += 1
    return frozenset(inside)


def _content_lines(content: str) -> list[str]:
    if "\r" in content:
        raise Refusal(
            "the block's text holds a carriage return; setup writes LF and converts where the file needs it",
            BAD_BLOCK,
        )
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def render(syntax: str, name: str, content: str, eol: bytes = b"\n") -> bytes:
    """The block as bytes: the markers and ``content`` between them."""
    if not valid_name(name):
        raise Refusal(f"{name!r} is not a block name: lower-case letters, digits and '-'", BAD_BLOCK)
    lines = _content_lines(content)
    for line in lines:
        for pattern in set(_MARKERS.values()):
            if pattern.match(line.encode("utf-8")):
                raise Refusal("the block's text holds a marker line", BAD_BLOCK)
    whole = [marker(syntax, "start", name), *lines, marker(syntax, "end", name)]
    return b"".join(line.encode("utf-8") + eol for line in whole)


def get(data: bytes, syntax: str, name: str = "") -> bytes | None:
    """The bytes of the block ``name``, markers included, or None."""
    check_text(data)
    _, body = split_bom(data)
    span = scan(body, syntax).get(name)
    if span is None:
        return None
    return b"".join(_lines(body)[span[0]:span[1]])


def as_written(data: bytes, there: bytes | None, recorded: Any) -> bool:
    """Whether the block ``there``, found in the file ``data``, is the
    block setup wrote, whose hash is ``recorded``: the same bytes, or the
    same lines with the other line ending in a file whose line endings
    were changed as a whole (an editor or git converted it between LF and
    CRLF). Every line of the block then ends as the file's lines do. A
    block with mixed endings, or with any other difference, was edited."""
    if there is None or not isinstance(recorded, str):
        return False
    if hashlib.sha256(there).hexdigest() == recorded:
        return True
    eol = eol_of(split_bom(data)[1])
    lines = _lines(there)
    if any(_ending(line) != eol for line in lines):
        return False
    other = b"\n" if eol == b"\r\n" else b"\r\n"
    return hashlib.sha256(b"".join(_bare(line) + other for line in lines)).hexdigest() == recorded


def content_of(data: bytes, syntax: str, name: str = "") -> list[str] | None:
    """The lines between the markers of the block ``name``, or None."""
    check_text(data)
    _, body = split_bom(data)
    span = scan(body, syntax).get(name)
    if span is None:
        return None
    return [_bare(line).decode("utf-8") for line in _lines(body)[span[0] + 1:span[1] - 1]]


def outside(data: bytes, syntax: str) -> list[str]:
    """The lines that are in no block."""
    check_text(data)
    _, body = split_bom(data)
    spans = scan(body, syntax).values()
    return [
        _bare(line).decode("utf-8")
        for index, line in enumerate(_lines(body))
        if not any(first <= index < after for first, after in spans)
    ]


def put(data: bytes | None, syntax: str, name: str, content: str, place: str = END) -> bytes:
    """``data`` with the block ``name`` holding ``content``. An existing
    block is replaced where it is; a new one goes to ``place``. ``data`` is
    None for a file that does not exist."""
    if data is None:
        return render(syntax, name, content)
    check_text(data)
    bom, body = split_bom(data)
    eol = eol_of(body)
    block = render(syntax, name, content, eol)
    span = scan(body, syntax).get(name)
    if span is not None:
        lines = _lines(body)
        return bom + b"".join(lines[:span[0]]) + block + b"".join(lines[span[1]:])
    if not body:
        return bom + block
    if place == HEAD:
        return bom + block + eol + body
    # A last line that ends in a lone CR keeps it: with a bare LF after it
    # the two would read as one CRLF, and taking the block out would take
    # the CR along.
    return bom + body + (b"\r\n" if body.endswith(b"\r") else eol) + block


def _line_hash(line: bytes) -> str:
    return hashlib.sha256(_bare(line)).hexdigest()


def joint(data: bytes | None, syntax: str, name: str, place: str = END) -> dict[str, Any]:
    """Which line ending ``put`` puts into ``data`` with a new block
    ``name``, for ``drop`` to take out again; see the module. ``data`` is
    the file before the block is added (None for no file)."""
    if data is None:
        return {"where": None}
    check_text(data)
    _, body = split_bom(data)
    if not body or scan(body, syntax).get(name) is not None:
        return {"where": None}
    if place == HEAD:
        return {"where": "after"}
    lines = _lines(body)
    if _ending(lines[-1]) and not body.endswith(b"\r"):
        return {"where": "before", "blank": True}
    return {"where": "before", "blank": False, "line": _line_hash(lines[-1])}


def _drop_joint(before: bytes, after: bytes, how: dict[str, Any]) -> tuple[bytes, bytes]:
    where = how.get("where")
    shorter = before[:len(before) - len(_ending(before))]
    if where == "before" and _ending(before):
        if how.get("blank"):
            if not shorter or _ending(shorter):
                before = shorter  # the blank line setup put there, still there
        elif not after:
            last = _lines(before)[-1]
            if how.get("line") == _line_hash(last):
                before = shorter  # the user's last line, as it was: without an ending
    elif where == "after":
        after = _strip_one_ending(after)
    return before, after


def drop(data: bytes, syntax: str, name: str = "", joint: dict[str, Any] | None = None) -> bytes | None:
    """``data`` without the block ``name`` and without the one line ending
    that set it apart; None when there is no such block. See the module
    for which line ending that is. ``joint`` is what ``joint`` said when
    the block was added; without it the file is taken as unchanged since."""
    check_text(data)
    bom, body = split_bom(data)
    span = scan(body, syntax).get(name)
    if span is None:
        return None
    lines = _lines(body)
    before, after = b"".join(lines[:span[0]]), b"".join(lines[span[1]:])
    if joint is not None:
        before, after = _drop_joint(before, after, joint)
        return bom + before + after
    if not after:
        # Last in the file: the ending before it was put there with it.
        before = before[:len(before) - len(_ending(before))]
    elif not before or after.startswith((b"\n", b"\r\n")):
        # First in the file, or a blank line follows: that one goes.
        after = _strip_one_ending(after)
    else:
        # Text on both sides. The ending before the block goes only if a
        # blank line is what it ends: taking it from a line of text would
        # join that line to the one after the block.
        shorter = before[:len(before) - len(_ending(before))]
        if not shorter or _ending(shorter):
            before = shorter
    return bom + before + after


def swap(data: bytes, syntax: str, name: str, block: bytes) -> bytes | None:
    """``data`` with the lines of the block ``name`` replaced by the bytes
    ``block``, which were there before setup wrote its own (a block of the
    user's between setup's markers); None when there is no such block."""
    check_text(data)
    check_text(block)
    bom, body = split_bom(data)
    span = scan(body, syntax).get(name)
    if span is None:
        return None
    lines = _lines(body)
    return bom + b"".join(lines[:span[0]]) + block + b"".join(lines[span[1]:])


def _strip_one_ending(text: bytes) -> bytes:
    if text.startswith(b"\r\n"):
        return text[2:]
    return text[1:] if text.startswith(b"\n") else text


# --- Exact lines ---------------------------------------------------------------

def remove_lines(data: bytes, wanted: list[str]) -> tuple[bytes, list[dict], list[str]]:
    """``data`` without every line that equals one of ``wanted`` exactly,
    the line ending aside. Returns the new bytes, a record of each removed
    line (its index among the lines before the removal, its text and its
    ending) and the wanted lines that were not found."""
    check_text(data)
    bom, body = split_bom(data)
    targets = {line.encode("utf-8"): line for line in wanted}
    kept: list[bytes] = []
    removed: list[dict] = []
    seen: set[str] = set()
    for index, line in enumerate(_lines(body)):
        text = targets.get(_bare(line))
        if text is None:
            kept.append(line)
            continue
        seen.add(text)
        removed.append({"index": index, "text": text, "eol": _ending(line).decode("ascii")})
    missing = [line for line in wanted if line not in seen]
    return bom + b"".join(kept), removed, missing


def restore_lines(data: bytes, removed: list[dict]) -> bytes:
    """Put back what ``remove_lines`` recorded, each line at its index. In
    a file not changed since, the result is the bytes before the removal.
    A line that is in the file again (the user put it back) is not put
    back a second time."""
    check_text(data)
    bom, body = split_bom(data)
    eol = eol_of(body)
    lines = _lines(body)
    # A line the user put back since is not put back a second time.
    there = [_bare(line) for line in lines]
    for item in sorted(removed, key=lambda item: item["index"]):
        wanted = str(item["text"]).encode("utf-8")
        if wanted in there:
            there.remove(wanted)
            continue
        index = min(max(int(item["index"]), 0), len(lines))
        ending = str(item.get("eol", "")).encode("ascii")
        if index < len(lines) and not ending:
            ending = eol  # it was the last line then, and is not now
        if index == len(lines) and lines and not _ending(lines[-1]):
            # After a lone CR a bare LF would read as one CRLF with it.
            lines[-1] += b"\r\n" if lines[-1].endswith(b"\r") else eol
        lines.insert(index, wanted + ending)
    return bom + b"".join(lines)
