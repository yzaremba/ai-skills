"""What a generated file holds that is not setup's: whatever Codex or the
user added to the Codex profile after setup's part, carried over each time
setup writes the file.

How it is used

    tail = carried.split(data, carried.own_hash(entry))  # bytes after setup's part, or None
    text = carried.join(generated, carried.tail_text(tail))
    text = carried.join(generated, carried.extracted(data, generated)[0])  # edited, on request
    carried.unchanged(data, entry)                         # setup's part is as setup wrote it
    carried.no_setup_key(data)                             # a file setup's part is not in

Why
    Setup writes the Codex profile ``<role>.config.toml`` whole (``entry``).
    Started with ``codex --profile <role>``, Codex (seen with 0.162.1)
    writes into that file, its active layer, what the user does in it: the
    answer to "trust this project?" as a table
    ``[projects."<absolute path of the project>"]`` with
    ``trust_level = "trusted"``, and by what its program holds, other state
    of its interface (``[notice]`` flags such as
    ``hide_full_access_warning``, ``model_migrations``, ...). It adds them
    after what is there. That is Codex's and the user's, not setup's. Were
    it taken for a hand edit, the profile would stay on old text until
    ``--overwrite-edited``, and Codex would ask its questions again.

Setup's part, and the rest
    Setup owns its own part alone: the text it generated, always the head
    of the file. The record of a profile holds, beside the hash of the
    whole file, the hash of that part (``OWN_KEY``). A file is setup's part
    as setup wrote it, followed by a part setup carries over, when a head
    of it, ending at a line break, has that hash, and what follows it is
    white space or TOML that parses, sets no key of setup's (``SETUP_KEYS``
    and every key setup's part sets), and with setup's part reads as the
    keys of both. Any keys and comments are carried. A change inside
    setup's part (``/model`` rewriting setup's ``model`` line in place, a
    changed byte of its text) is a hand edit as before, and so is a part
    after it that sets one of setup's keys.

    A record written before the hash of setup's part was kept has none.
    Such a profile was written whole by setup, with nothing carried over,
    so the hash of the whole file is that of setup's part (``own_hash``).

Carrying it over
    What follows setup's part is written again after the new text exactly
    as it is (``tail_text``); only its line ends are made LF, because setup
    writes LF, and where that would change what the part reads as, it is
    written anew. A file edited by hand that is replaced on request
    (``--overwrite-edited``) keeps every key of it that is not setup's:
    those are read and written anew (``extracted``), each key and value
    reading back unchanged, a key with quotes, backslashes or a drive
    letter among them; its comments are not kept, and a value of a type
    setup does not write stops that file with an error. ``join`` checks
    that setup's own text ends in a line break (the record's hash of it is
    of exactly those bytes), that the result parses, that the part after it
    sets no key of setup's, and that it reads as the keys of both.

What is said
    Keys Codex writes itself (``CODEX_KEYS``) are carried without a word.
    Any other top-level key after setup's part is carried and named
    (``named``, ``said``): in render's line for the profile, and by doctor
    as information; one of ``RISKS``, which changes what a session started
    with the profile may do, is a warning of doctor's.

    A file at the path that the record does not list and whose keys are
    all Codex's own (``only_codexs``: what ``uninstall`` left of a profile
    Codex wrote into) is taken up by ``render``, with setup's text written
    before it. Any other file there is the user's and a conflict, as
    before. Its line ends become LF, and where it has to be written anew
    its comments go: a file of the user's that went that way and is then
    uninstalled comes back with its keys, and not byte for byte.
"""
from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path
from typing import Any

from . import fsio, tomlio
from .errors import SetupError

# The keys setup writes in a profile (``entry.BLOCK_KEYS``).
SETUP_KEYS = ("model", "model_reasoning_effort", "developer_instructions")

# The top-level keys Codex itself writes into the config layer it was
# started with, read from Codex 0.162.1: the answer to "trust this
# project?" (``projects``) and the flags of its interface (``notice``).
# They are carried without a word. Any other key after setup's part is
# carried too, and named: in render's line for the profile and by doctor.
CODEX_KEYS = ("projects", "notice")

# Keys after setup's part that change what a session started with the
# profile may do, or what it is: carried, and doctor warns of each.
RISKS = {
    "sandbox_mode": "while it is set in any config Codex loads, Codex uses the older sandbox settings for the "
                    "session and ignores the permission profile (default_permissions), setup's among them",
    "approval_policy": "it changes when Codex asks before it runs a command in a session started with the profile",
    "default_permissions": "it selects the permission profile of a session started with the profile, in place of "
                           "the one config.toml selects",
    "permissions": "it defines or changes permission profiles for a session started with the profile",
    "model_provider": "it sends the session's requests to another model provider, so the role's model may not be "
                      "the one setup chose",
    "model_providers": "it defines model providers for a session started with the profile",
    "model_instructions_file": "it replaces the model's base instructions for a session started with the profile",
    "profile": "it names another profile for the session, whose keys then apply as well",
    "profiles": "it defines profiles inside the profile file, which the session may then use",
    "mcp_servers": "it gives a session started with the profile MCP servers, and with them more tools",
}
# The key of a file's entry in the record: the hash of setup's own part.
OWN_KEY = "own_sha256"
# How the inputs digest of a Codex profile begins (``entry.PROFILE_SCHEME``).
PROFILE_INPUTS = "render:codex-profile:"

WHAT = "what Codex or you added after setup's part"


def own_hash(entry: dict[str, Any] | None) -> str | None:
    """The hash of setup's own part of the file of ``entry``, for a Codex
    profile; None for any other file."""
    if not isinstance(entry, dict) or entry.get("kind") != "file":
        return None
    if not str(entry.get("inputs") or "").startswith(PROFILE_INPUTS):
        return None
    own = entry.get(OWN_KEY)
    if isinstance(own, str):
        return own
    sha = entry.get("sha256")
    return sha if isinstance(sha, str) else None


def _parse(data: bytes | str) -> dict[str, Any] | None:
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        return tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, RecursionError, ValueError):
        return None


def _taken(theirs: dict[str, Any], mine: dict[str, Any]) -> list[str]:
    """The keys of ``theirs`` that are setup's."""
    return [key for key in theirs if key in SETUP_KEYS or key in mine]


def split(data: bytes, own: str | None) -> bytes | None:
    """What follows setup's own part in ``data``: the bytes after the head
    whose hash is ``own``, when they are a part setup carries over (see the
    module). ``b""`` when the file is setup's part alone; None when no head
    has that hash, or what follows it is not such a part."""
    if not own:
        return None
    digest = hashlib.sha256()
    end = 0
    for line in data.splitlines(keepends=True):
        digest.update(line)
        end += len(line)
        if digest.hexdigest() == own:
            head, tail = data[:end], data[end:]
            if not tail.strip():
                return tail
            mine, theirs, whole = _parse(head), _parse(tail), _parse(data)
            if mine is None or theirs is None or whole is None or _taken(theirs, mine):
                return None
            return tail if whole == {**mine, **theirs} else None
    return None


def unchanged(data: bytes, entry: dict[str, Any] | None) -> bool:
    """Whether ``data`` holds setup's part as setup wrote it, followed by
    nothing but a part setup carries over. Always False for a file that is
    not a Codex profile: for that one the hash of the whole file decides."""
    return split(data, own_hash(entry)) is not None


def no_setup_key(data: bytes) -> bool:
    """Whether ``data`` is TOML with something in it and no key of setup's:
    a profile setup's part is not in (what ``uninstall`` leaves, or what
    is left once its owner took setup's part out)."""
    if not data.strip():
        return False
    parsed = _parse(data.removeprefix(b"\xef\xbb\xbf"))
    return parsed is not None and not _taken(parsed, {})


def only_codexs(data: bytes) -> bool:
    """Whether ``data`` is TOML with something in it whose keys are all
    ones Codex writes itself (``CODEX_KEYS``): what ``uninstall`` leaves of
    a profile Codex wrote into, which ``render`` takes up again. A file at
    the profile's path with any other key is the user's, and a conflict."""
    if not data.strip():
        return False
    parsed = _parse(data.removeprefix(b"\xef\xbb\xbf"))
    return parsed is not None and all(key in CODEX_KEYS for key in parsed)


def named(keys: Any) -> list[str]:
    """The top-level keys of a carried part that are not Codex's own
    (``CODEX_KEYS``): those are said."""
    return [key for key in keys if key not in CODEX_KEYS]


def tail_keys(tail: bytes | None) -> list[str]:
    """The top-level keys of a carried part, in its order."""
    if not tail or not tail.strip():
        return []
    return list(_parse(tail) or {})


def said(keys: list[str]) -> str:
    """What render says of the keys ``named`` gives: empty when there are
    none."""
    if not keys:
        return ""
    risky = [key for key in keys if key in RISKS]
    text = f"; besides what Codex writes there it holds {', '.join(keys)}"
    if risky:
        text += f" ({', '.join(risky)} change{'s' if len(risky) == 1 else ''} what a session may do; see doctor)"
    return text


def parts(record: Any) -> list[tuple[str, Path, dict[str, Any]]]:
    """Each Codex profile the record lists, by key and path, with the keys
    of what follows setup's part in it (empty where nothing follows, or
    the file is not as setup wrote it). Read only; a file that cannot be
    read is left out."""
    found = []
    for key, entry in sorted(record.entries.items()):
        own = own_hash(entry)
        if not own:
            continue
        try:
            path = record.path(key)
            seen = fsio.look(path)
            if seen.kind == fsio.LINK and os.path.isfile(path):
                data = fsio.read_bytes(Path(os.path.realpath(path)))
            elif seen.kind == fsio.FILE:
                data = fsio.read_bytes(path)
            else:
                continue
        except SetupError:
            continue
        tail = split(data, own)
        found.append((key, path, (_parse(tail) or {}) if tail and tail.strip() else {}))
    return found


def _written(table: dict[str, Any]) -> str:
    """``table`` written anew, after one empty line."""
    text = tomlio.dumps(table)
    if tomllib.loads(text) != table:
        raise SetupError("what is kept does not read back as it was written")
    return "\n" + text


def tail_text(tail: bytes | None) -> str:
    """What follows setup's part, as it is written again after the new
    text: the same text with LF line ends, or nothing when it is white
    space. A part that would read otherwise with LF is written anew, with
    the same keys and values."""
    if not tail or not tail.strip():
        return ""
    text = tail.decode("utf-8")
    if "\r" not in text:
        return text
    lf = text.replace("\r\n", "\n")
    before = tomllib.loads(text)
    if "\r" not in lf and _parse(lf) == before:
        return lf
    return _written(before)


def extracted(data: bytes, own: str) -> tuple[str, str | None]:
    """The keys of a file that is not as setup wrote it which are not
    setup's (nor set by setup's new text ``own``), written anew, and what
    to say of them: ("", None) when there are none, and ("", why) when the
    file cannot be read as TOML, so that nothing of it is carried over (the
    backup of the file holds it). A value that cannot be written again (of
    a type setup does not write) is a ``SetupError``."""
    parsed = _parse(data.removeprefix(b"\xef\xbb\xbf"))
    if parsed is None:
        return "", f"the file is not valid TOML, so nothing of {WHAT} could be kept; its backup holds it"
    mine = _parse(own) or {}
    rest = {key: value for key, value in parsed.items() if key not in SETUP_KEYS and key not in mine}
    if not rest:
        return "", None
    try:
        return _written(rest), None
    except SetupError as exc:
        raise SetupError(f"{WHAT} cannot be kept: {exc.lines[0]}") from None


def left(tail: bytes) -> bytes:
    """What is left of a file once setup's part is taken out: what followed
    it, without the empty lines it began with."""
    return tail.lstrip(b"\r\n")


def join(own: str, tail: str) -> str:
    """Setup's text ``own`` with ``tail`` after it, checked (see the
    module). A ``SetupError`` says what is wrong."""
    if not own.endswith("\n"):
        raise SetupError("setup's own text does not end in a line break, so nothing can be carried after it")
    if not tail.strip():
        return own
    mine, theirs = _parse(own), _parse(tail)
    if mine is None:
        raise SetupError("setup's own text is not valid TOML")
    if theirs is None:
        raise SetupError(f"{WHAT} cannot be kept: it is not valid TOML")
    taken = _taken(theirs, mine)
    if taken:
        raise SetupError(f"{WHAT} cannot be kept: it sets {', '.join(taken)}, which setup sets")
    whole = own + tail
    if _parse(whole) != {**mine, **theirs}:
        raise SetupError(f"{WHAT} cannot be kept: the file would not read as setup's keys and those")
    return whole
