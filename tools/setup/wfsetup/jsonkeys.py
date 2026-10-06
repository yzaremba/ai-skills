"""Setup's keys in a JSON settings file the user owns.

Which keys: ``tools/setup/manifest-keys.json`` lists them, per kind of file:

    {"schema_version": 1,
     "files": {"<kind>": {"path": "<anchor>:<relative path>", "keys": ["<key>", ...]}}}

``path`` is written as the install record writes a path (see ``manifest``),
and ``keys`` are keys of the file's top-level object. A file that is not
listed, and a key that is not listed for its file, cannot be changed. A
later step adds a key to a kind, or a kind, in that file and nowhere else.

What is guaranteed, and tested:

    - The file is never written again from parsed data. Only the bytes of
      the one member change (its value, or the member and its comma);
      every other byte stays: other keys, their order, spacing, line
      endings, a byte order mark, a missing final newline.
    - The text is parsed before, and the result is parsed again and must
      equal the old data with exactly the asked change, or the edit is
      refused.
    - A key that is added is appended as the last member, laid out like the
      members already there. Removing the last member restores the bytes
      before it was appended.
    - An object with no member keeps what is between its braces. ``{}``
      gets its member on a line of its own. One that holds white space
      (``{`` and ``}`` on two lines, say) keeps that white space before
      the member, and the closing brace follows the member directly: that
      is how the removal knows the two apart and gives back either one,
      byte for byte.
    - Refused, and never overwritten: text that is not UTF-8 or not JSON,
      a top level that is not an object, and a top-level key written twice.

A new file is ``{``, the members indented by two spaces, ``}`` and a final
LF.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from . import paths
from .errors import SetupError

KEY_LIST = Path(__file__).resolve().parents[1] / "manifest-keys.json"
KEY_LIST_SCHEMA = 1

_BOM = "﻿"
_SPACE = " \t\r\n"
# How far a member is indented that is put, on a line of its own, into an
# object that held only white space.
_EMPTY_INDENT = "  "


class Refusal(Exception):
    """Why a JSON file cannot be edited, in one line without the file name."""


def load_key_list(file: Path | None = None) -> dict[str, tuple[str, ...]]:
    """The listed keys: a file's path as the record writes it, to its keys."""
    file = KEY_LIST if file is None else file
    try:
        # Looked at before it is opened: a FIFO there would be waited on.
        if not stat.S_ISREG(os.stat(file).st_mode):
            raise SetupError(f"{file}: cannot be read: it is not a file")
        data = json.loads(file.read_bytes().decode("utf-8"))
    except OSError as exc:
        raise SetupError(f"{file}: cannot be read: {paths.reason(exc)}") from None
    except RecursionError:
        raise SetupError(f"{file}: is not valid JSON: nested too deeply") from None
    except ValueError as exc:
        raise SetupError(f"{file}: is not valid JSON: {' '.join(str(exc).split())}") from None
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict) or data.get("schema_version") != KEY_LIST_SCHEMA:
        raise SetupError(f"{file}: is not a key list this setup reads (schema_version {KEY_LIST_SCHEMA})")
    listed: dict[str, tuple[str, ...]] = {}
    for kind, item in files.items():
        path = item.get("path") if isinstance(item, dict) else None
        keys = item.get("keys") if isinstance(item, dict) else None
        if not isinstance(path, str) or not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise SetupError(f"{file}: files.{kind}: needs a path and a list of keys")
        if path in listed:
            raise SetupError(f"{file}: files.{kind}: {path} is listed twice")
        listed[path] = tuple(keys)
    return listed


def same(one: Any, other: Any) -> bool:
    """Whether two JSON values are equal; ``true`` is not ``1``."""
    return json.dumps(one, sort_keys=True) == json.dumps(other, sort_keys=True)


# --- Reading -------------------------------------------------------------------

def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a value JSON has")


def parse(data: bytes) -> tuple[str, dict[str, Any]]:
    """The file's text and its top-level object."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal(f"is not UTF-8 text (byte {exc.start})") from None
    try:
        value = json.loads(text[len(_BOM):] if text.startswith(_BOM) else text, parse_constant=_no_constant)
    except RecursionError:
        raise Refusal("is not valid JSON: nested too deeply") from None
    except ValueError as exc:
        raise Refusal(f"is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise Refusal("is not a JSON object at the top level")
    try:
        # A string with half of a surrogate pair is no text: it could
        # not be written back.
        json.dumps(value, ensure_ascii=False).encode("utf-8")
    except (UnicodeEncodeError, RecursionError, ValueError):
        raise Refusal("holds a string that is not valid Unicode (half of a surrogate pair)") from None
    keys = [key for key, *_ in _members(text)[2]]
    for key in keys:
        if keys.count(key) > 1:
            raise Refusal(f"holds the key {json.dumps(key)} twice")
    return text, value


def _skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index] in _SPACE:
        index += 1
    return index


def _skip_string(text: str, index: int) -> int:
    index += 1
    while text[index] != '"':
        index += 2 if text[index] == "\\" else 1
    return index + 1


def _skip_value(text: str, index: int) -> int:
    if text[index] == '"':
        return _skip_string(text, index)
    if text[index] in "{[":
        depth = 0
        while True:
            char = text[index]
            if char == '"':
                index = _skip_string(text, index)
                continue
            if char in "{[":
                depth += 1
            elif char in "}]":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
    while index < len(text) and text[index] not in ",}]" + _SPACE:
        index += 1
    return index


def _members(text: str) -> tuple[int, int, list[tuple[str, int, int, int]]]:
    """Where the top-level object opens and closes, and for each member its
    key and where its key starts, its value starts and its value ends. The
    text has been parsed already, so it is walked without checking it."""
    opened = _skip_space(text, len(_BOM) if text.startswith(_BOM) else 0)
    members: list[tuple[str, int, int, int]] = []
    index = _skip_space(text, opened + 1)
    while text[index] != "}":
        key_start = index
        key_end = _skip_string(text, index)
        colon = _skip_space(text, key_end)
        value_start = _skip_space(text, colon + 1)
        value_end = _skip_value(text, value_start)
        members.append((json.loads(text[key_start:key_end]), key_start, value_start, value_end))
        index = _skip_space(text, value_end)
        if text[index] == ",":
            index = _skip_space(text, index + 1)
    return opened, index, members


# --- Changing ------------------------------------------------------------------

def _eol(text: str) -> str:
    crlf = text.count("\r\n")
    return "\r\n" if crlf > text.count("\n") - crlf else "\n"


def _value_text(value: Any, indent: str, eol: str) -> str:
    try:
        if isinstance(value, (dict, list)) and value:
            lines = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).split("\n")
            return (eol + indent).join(lines)
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise Refusal(f"a value that JSON cannot hold: {exc}") from None


def new_file(values: dict[str, Any]) -> bytes:
    """A settings file that holds ``values`` and nothing else."""
    members = [
        f'  {json.dumps(key, ensure_ascii=False)}: {_value_text(value, "  ", chr(10))}'
        for key, value in values.items()
    ]
    return ("{\n" + ",\n".join(members) + "\n}\n").encode("utf-8")


def set_key(text: str, key: str, value: Any) -> str:
    """``text`` with ``key`` set to ``value``: in place when the key is
    there, else as a new last member."""
    opened, closed, members = _members(text)
    eol = _eol(text)
    for name, _, value_start, value_end in members:
        if name == key:
            line = text[text.rfind("\n", 0, value_start) + 1:value_start]
            indent = line[:len(line) - len(line.lstrip(" \t"))]
            return text[:value_start] + _value_text(value, indent, eol) + text[value_end:]
    name_text = json.dumps(key, ensure_ascii=False)
    if not members:
        inner = text[opened + 1:closed]
        if not inner:
            member = f"{name_text}: {_value_text(value, '  ', eol)}"
            return text[:opened + 1] + eol + "  " + member + eol + text[closed:]
        # White space between the braces stays, before the member; see the
        # module. On a line of its own the member is indented.
        indent = _EMPTY_INDENT if "\n" in inner else ""
        last = inner[inner.rfind("\n") + 1:] + indent
        member = f"{name_text}: {_value_text(value, last if chr(10) in inner else '', eol)}"
        return text[:opened + 1] + inner + indent + member + text[closed:]
    gap = text[opened + 1:members[0][1]]
    if "\n" not in gap:
        gap = " "
    indent = gap[gap.rfind("\n") + 1:] if "\n" in gap else ""
    last_end = members[-1][3]
    return text[:last_end] + "," + gap + f"{name_text}: {_value_text(value, indent, eol)}" + text[last_end:]


def remove_key(text: str, key: str) -> str:
    """``text`` without the member ``key``."""
    opened, closed, members = _members(text)
    for index, (name, key_start, _, value_end) in enumerate(members):
        if name != key:
            continue
        if len(members) == 1:
            lead, tail = text[opened + 1:key_start], text[value_end:closed]
            if not tail and lead:
                # The layout ``set_key`` gives an object that held only
                # white space: that white space is what was there.
                if "\n" in lead and lead.endswith(_EMPTY_INDENT):
                    lead = lead[:len(lead) - len(_EMPTY_INDENT)]
                return text[:opened + 1] + lead + text[closed:]
            return text[:opened + 1] + text[closed:]
        if index == len(members) - 1:
            return text[:members[index - 1][3]] + text[value_end:]
        return text[:key_start] + text[members[index + 1][1]:]
    return text


def checked(text: str, expected: dict[str, Any]) -> bytes:
    """``text`` as bytes, once it parses to exactly ``expected``, the order
    of the top-level keys included."""
    try:
        _, value = parse(text.encode("utf-8"))
    except Refusal as exc:
        raise Refusal(f"the edit would leave a file that {exc}") from None
    if list(value) != list(expected) or not same(value, expected):
        raise Refusal("the edit would change more than the keys asked for")
    return text.encode("utf-8")
