"""Read and write TOML.

Reading uses ``tomllib``. Writing uses the small emitter below, which covers
what setup writes: strings, integers, booleans, arrays of strings, and
tables, with nested tables as ``[a.b]`` headers, and comment lines at the
head of the document. Anything else is refused.

The emitter's output is UTF-8 with LF line endings on every platform, and
any string it accepts reads back unchanged through ``tomllib``.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Iterable

from . import paths
from .errors import SetupError

# What TOML calls an integer: 64 bits, signed. ``tomllib`` reads larger
# ones; other parsers refuse them, so the emitter writes none.
_INTEGER_MIN = -(2 ** 63)
_INTEGER_MAX = 2 ** 63 - 1

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_SHORT_ESCAPES = {
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
    '"': '\\"',
    "\\": "\\\\",
}


# --- Reading ----------------------------------------------------------------

def load(path: Path) -> dict[str, Any]:
    """Parse the TOML file at ``path``. Every failure names the file."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SetupError(f"{path}: cannot be read: {paths.reason(exc)}") from None
    try:
        # A byte order mark is what some Windows editors put first.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SetupError(f"{path}: is not UTF-8 text (byte {exc.start})") from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SetupError(f"{path}: is not valid TOML: {exc}") from None
    except RecursionError:
        # ``tomllib`` reads arrays and inline tables by recursion.
        raise SetupError(f"{path}: is not valid TOML: arrays or inline tables are nested too deeply") from None
    except ValueError:
        # Not a ``TOMLDecodeError``: an integer of more digits than Python
        # converts. The message would repeat the digit limit, not the cause.
        raise SetupError(f"{path}: is not valid TOML: it holds an integer with too many digits") from None


def load_if_present(path: Path) -> dict[str, Any] | None:
    """Parse the file at ``path``, or return None when nothing is there.

    A link whose target is missing is an error, not an absent file, and so
    is anything that is not a regular file (see ``paths.kind``).
    """
    found = paths.kind(path)
    if found == paths.ABSENT:
        return None
    if found != paths.FILE:
        raise SetupError(f"{path}: is not a file")
    return load(path)


# --- Writing ----------------------------------------------------------------

def type_name(value: Any) -> str:
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
    return type(value).__name__.lower()


def article(noun: str) -> str:
    """``noun`` with its article: "an integer", "a string"."""
    return f"an {noun}" if noun[:1] in "aeiou" else f"a {noun}"


def format_key(key: str, where: str = "key") -> str:
    """One key, bare where TOML allows it and quoted otherwise. ``where``
    names the key in an error."""
    if _BARE_KEY.fullmatch(key):
        return key
    _check_encodable(key, where)
    return _basic_string(key)


def dotted(parts: tuple[str, ...] | list[str]) -> str:
    """A key path as TOML writes it: ``a.b."odd key"``."""
    return ".".join(format_key(part) for part in parts)


def format_value(value: Any, multiline: bool = False, where: str = "value") -> str:
    """One value as TOML text.

    With ``multiline``, a string that holds a line feed is written as a
    multi-line string, so long text stays readable. Without it the result
    is always one line. ``where`` names the value in an error.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if not _INTEGER_MIN <= value <= _INTEGER_MAX:
            # The number is not shown: Python refuses to print a very long one.
            raise SetupError(f"{where}: cannot write an integer outside the signed 64-bit range")
        return str(value)
    if isinstance(value, str):
        _check_encodable(value, where)
        if multiline and "\n" in value:
            return _multiline_string(value)
        return _basic_string(value)
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                raise SetupError(f"{where}: cannot write an array that holds {article(type_name(item))}")
            _check_encodable(item, where)
        return "[" + ", ".join(_basic_string(item) for item in value) + "]"
    raise SetupError(f"{where}: cannot write {article(type_name(value))} value")


def dumps(data: dict[str, Any], header: Iterable[str] = ()) -> str:
    """A table as a TOML document. Keys keep their order; in each table the
    plain values come first and the sub-tables after them.

    ``header`` is written first, each item as one comment line (an empty
    item as a bare ``#``), with an empty line between it and the data. A
    comment changes nothing a parser reads, so the document reads back as
    ``data`` with any header; a line TOML does not allow in a comment is
    refused (see ``comment``).
    """
    lines: list[str] = [comment(line) for line in header]
    body: list[str] = []
    _emit_table(data, (), body)
    if lines and body:
        lines.append("")
    lines.extend(body)
    return "\n".join(lines) + "\n" if lines else ""


def comment(text: str) -> str:
    """``text`` as one comment line. TOML allows no control character in a
    comment but the tab, so a line break cannot end the comment early and
    turn the rest of the text into data."""
    if not isinstance(text, str):
        raise SetupError(f"a comment line: cannot write {article(type_name(text))} as a comment")
    _check_encodable(text, "a comment line")
    for char in text:
        code = ord(char)
        if (code < 0x20 and char != "\t") or code == 0x7F:
            raise SetupError(f"a comment line: holds the control character U+{code:04X}, which TOML does not allow")
    return f"# {text}".rstrip(" ") if text.strip(" ") else "#"


def _emit_table(table: dict[str, Any], path: tuple[str, ...], lines: list[str]) -> None:
    for key in table:
        if not isinstance(key, str):
            raise SetupError(f"{dotted(path) or 'document'}: cannot write a key that is not a string")
        # Before any key is written: ``dotted`` below would otherwise meet
        # the fault with no place to name.
        _check_encodable(key, f"{dotted(path) or 'document'}: a key")
    values = [(key, value) for key, value in table.items() if not isinstance(value, dict)]
    tables = [(key, value) for key, value in table.items() if isinstance(value, dict)]
    # A header is needed for a table's own values, and for an empty table,
    # which would otherwise vanish.
    if path and (values or not tables):
        if lines:
            lines.append("")
        lines.append(f"[{dotted(path)}]")
    for key, value in values:
        text = format_value(value, multiline=True, where=dotted(path + (key,)))
        lines.append(f"{format_key(key)} = {text}")
    for key, value in tables:
        _emit_table(value, path + (key,), lines)


def _check_encodable(text: str, where: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise SetupError(f"{where}: holds a character that UTF-8 cannot encode") from None


def _escape(char: str) -> str:
    short = _SHORT_ESCAPES.get(char)
    if short is not None:
        return short
    code = ord(char)
    if code < 0x20 or code == 0x7F:
        return f"\\u{code:04X}"
    return char


def _basic_string(text: str) -> str:
    return '"' + "".join(_escape(char) for char in text) + '"'


def _multiline_string(text: str) -> str:
    """``text`` between triple quotes, its line feeds written as line breaks.

    Everything else is escaped as in a one-line string, except that a quote
    stays as it is where it cannot be taken for part of the closing quotes:
    never two in a row, and never as the last character.
    """
    out: list[str] = []
    after_quote = False
    last = len(text) - 1
    for index, char in enumerate(text):
        if char == "\n":
            out.append("\n")
            after_quote = False
        elif char == '"' and not after_quote and index != last:
            out.append('"')
            after_quote = True
        else:
            out.append(_escape(char))
            after_quote = False
    # The line break after the opening quotes is not part of the string.
    return '"""\n' + "".join(out) + '"""'
