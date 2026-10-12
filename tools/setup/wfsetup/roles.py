"""A role's source: ``roles/<role>/role.toml``.

The format is stated in ``roles/README.md``. This module reads what names a
role and what profiles it: ``name``, ``title``, ``description`` and the
``[profile]`` table. The other keys (``includes``, ``actions``, ``[limits]``,
``[entry]``) are left as they are in ``Role.data``. A reader of profiles
does not need them, so ``check_file`` looks at them only when asked to be
``strict``, which is how source validation (``validate``) asks: then every
key of the format must be there, with its type, and no other.

``join_text`` is how a role's full text is put together from ``ROLE.md``
and its includes, and ``TEXT_LIMIT`` the size it must stay under.

A role gives one definition, or two when it has ``[profile.hard]``: the
second is named ``<name>-hard`` and has a tier and an effort of its own.
``high_stakes_tier`` belongs to ``[profile]`` only. ``roles/README.md`` gives
``[profile.hard]`` a tier and an effort and nothing else, and the framework
document raises only the Product Manager and the Architect for high-stakes
work, so the hard definition has no high-stakes tier and does not take the
one of ``[profile]``.

Every fault names the file and the key, and all of a file's faults are
reported at once.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import paths, schema, tomlio
from .errors import SetupError
from .locations import Locations
from .schema import Strings, Table, Value

ROLE_FILE = "role.toml"
TEXT_FILE = "ROLE.md"
SHARED_DIR = "_shared"
HARD_SUFFIX = "-hard"

# ``ROLE.md`` with its includes stays under this many bytes: a dispatched
# role shares its budget with the project's instruction files
# (roles/README.md, "Size"). A role that can be loaded has a limit of its
# own, on the whole skill it is given: ``validate.LOADED_SKILL_TOKENS``.
TEXT_LIMIT = 12_000

_STRING = Value("string")
_BOOLEAN = Value("boolean")
_TIER = Value("string", choices=schema.TIERS)
_EFFORT = Value("string", choices=schema.EFFORTS)

_IDENTITY: dict[str, schema.Node] = {"name": _STRING, "title": _STRING, "description": _STRING}
_HARD = Table({"tier": _TIER, "effort": _EFFORT})
_PROFILE = Table({"tier": _TIER, "effort": _EFFORT, "high_stakes_tier": _TIER, "hard": _HARD})
_PROFILE_REQUIRED = ("tier", "effort")

# What ``strict`` adds: the rest of the format, every key of it required.
_REST: dict[str, schema.Node] = {
    "includes": Strings(),
    "limits": Table({"edits": _BOOLEAN, "commands": _BOOLEAN, "dispatches": Strings()}),
    "entry": Table({"dispatch": _BOOLEAN, "load": _BOOLEAN, "start": _BOOLEAN}),
}
# Optional, and checked with ``strict`` when it is there: the sections of a
# provider's action notes the role is given (``definitions.select_actions``).
_OPTIONAL: dict[str, schema.Node] = {"actions": Strings()}
_KNOWN = (*_IDENTITY, "includes", "actions", "profile", "limits", "entry")


def join_text(parts: Iterable[str]) -> str:
    """A role's full text: ``ROLE.md`` and then its includes, in order.

    Each part loses a byte order mark and its trailing white space, a CRLF
    becomes LF, and the parts are joined by one empty line, so the same
    sources give the same bytes on Linux and in a Windows checkout.
    """
    cleaned = [part.removeprefix("﻿").replace("\r\n", "\n").rstrip() for part in parts]
    return "\n\n".join(cleaned) + "\n"


@dataclass(frozen=True)
class Definition:
    """One definition a role yields, and the profile it starts from.

    ``key`` is the table of ``file`` the profile was read from: ``profile``,
    or ``profile.hard`` for the hard definition.
    """

    id: str
    role: str
    file: Path
    key: str
    tier: str
    effort: str
    high_stakes_tier: str | None = None


@dataclass(frozen=True)
class Role:
    name: str
    title: str
    description: str
    file: Path
    definitions: tuple[Definition, ...]
    data: dict[str, Any]


def files(where: Locations) -> dict[str, Path]:
    """The ``role.toml`` of each role directory, by directory name. A
    directory whose name starts with ``_`` or ``.`` is not a role."""
    found: dict[str, Path] = {}
    for directory in paths.entries(where.roles_dir):
        if directory.name.startswith(("_", ".")):
            continue
        try:
            if paths.kind(directory) != paths.DIRECTORY:
                continue
        except SetupError:
            # A link that leads nowhere: ``check_file`` says so.
            pass
        found[directory.name] = directory / ROLE_FILE
    return found


def load_all(where: Locations) -> dict[str, Role]:
    """Every role, by id, in the order of the ids. The faults of all of
    them are reported together."""
    problems: list[str] = []
    found: dict[str, Role] = {}
    for name, file in files(where).items():
        loaded = check_file(file, name, problems)
        if loaded is not None:
            found[name] = loaded
    for role in found.values():
        for definition in role.definitions:
            if definition.id != role.name and definition.id in found:
                problems.append(
                    f"{role.file}: profile.hard: yields the definition {definition.id}, "
                    f"which is also the role {found[definition.id].file}"
                )
    if problems:
        raise SetupError(*problems)
    return found


def definitions(where: Locations) -> list[Definition]:
    """Every definition, in a fixed order: by role id, and a role's hard
    definition straight after its normal one."""
    return [definition for role in load_all(where).values() for definition in role.definitions]


def load_file(file: Path, name: str | None = None) -> Role:
    """The role at ``file``. ``name`` defaults to the directory's name."""
    problems: list[str] = []
    loaded = check_file(file, name or file.parent.name, problems)
    if loaded is None:
        raise SetupError(*problems)
    return loaded


def check_file(file: Path, name: str, problems: list[str], strict: bool = False) -> Role | None:
    """Read and check ``file``, the ``role.toml`` of the directory ``name``,
    adding a line to ``problems`` per fault. Returns None when there was any.

    With ``strict`` the whole format of ``roles/README.md`` is checked:
    ``includes``, ``[limits]`` and ``[entry]`` must be there with every key
    and the right types, ``actions`` has its type where it is given, and a
    key the format does not have is a fault."""
    try:
        # The directory first: under a link that leads nowhere, or under a
        # directory that cannot be looked into, the file would only seem
        # to be missing.
        paths.kind(file.parent)
        found = paths.kind(file)
        if found == paths.ABSENT:
            problems.append(f"{file}: missing; a role directory must have it")
            return None
        if found != paths.FILE:
            problems.append(f"{file}: is not a file")
            return None
        data = tomlio.load(file)
    except SetupError as exc:
        problems.extend(exc.lines)
        return None
    before = len(problems)
    if not schema.is_id(name):
        problems.append(
            f"{file}: the directory name {tomlio.format_value(name)} is not a role id "
            "(lower-case letters, digits and single hyphens)"
        )
    for key, node in _IDENTITY.items():
        if key not in data:
            problems.append(f"{file}: {key}: missing; a role must have it")
        else:
            schema.check(node, data[key], (key,), file, problems)
    if isinstance(data.get("name"), str) and data["name"] and data["name"] != name:
        problems.append(
            f"{file}: name: {tomlio.format_value(data['name'])} is not the directory's name, "
            f"{tomlio.format_value(name)}"
        )
    _check_profile(data, file, problems)
    if strict:
        _check_rest(data, file, problems)
    if len(problems) > before:
        return None

    profile = data["profile"]
    found = [Definition(name, name, file, "profile", profile["tier"], profile["effort"], profile.get("high_stakes_tier"))]
    if "hard" in profile:
        hard = profile["hard"]
        found.append(Definition(name + HARD_SUFFIX, name, file, "profile.hard", hard["tier"], hard["effort"]))
    return Role(name, data["title"], data["description"], file, tuple(found), data)


def _check_rest(data: dict[str, Any], file: Path, problems: list[str]) -> None:
    for key in data:
        if key not in _KNOWN:
            problems.append(f"{file}: {tomlio.format_key(key)}: unknown key; known here: {', '.join(_KNOWN)}")
    for key, node in _OPTIONAL.items():
        if key in data:
            schema.check(node, data[key], (key,), file, problems)
    for key, node in _REST.items():
        if key not in data:
            problems.append(f"{file}: {key}: missing; a role must have it")
            continue
        schema.check(node, data[key], (key,), file, problems)
        if isinstance(node, Table) and isinstance(data[key], dict):
            for inner in node.keys:
                if inner not in data[key]:
                    problems.append(f"{file}: {key}.{inner}: missing; a role must have it")


def _check_profile(data: dict[str, Any], file: Path, problems: list[str]) -> None:
    if "profile" not in data:
        problems.append(f"{file}: profile: missing; a role must have it")
        return
    profile = data["profile"]
    schema.check(_PROFILE, profile, ("profile",), file, problems)
    if not isinstance(profile, dict):
        return
    tables = [("profile", profile)]
    if isinstance(profile.get("hard"), dict):
        tables.append(("profile.hard", profile["hard"]))
    for path, table in tables:
        for key in _PROFILE_REQUIRED:
            if key not in table:
                problems.append(f"{file}: {path}.{key}: missing; a profile names a tier and an effort")
