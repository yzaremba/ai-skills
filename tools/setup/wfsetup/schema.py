"""What a settings file may hold.

The schema is a tree of ``Table`` and ``Value`` nodes, one subtree per group.
Groups are validated one at a time, so that a reader of one group never
depends on another (see ``settings.resolve``).
"""
from __future__ import annotations

import re
import tomllib
from typing import Any

from . import tomlio
from .errors import SetupError

# The version this tool writes and the newest it reads.
SCHEMA_VERSION = 1
VERSION_KEY = "schema_version"

TIERS = ("fast", "standard", "deep", "frontier")
EFFORTS = ("low", "medium", "high", "max")
# How long a role's context stays cached between its turns, where a provider
# lets a definition say: ``long`` for a role that waits on the user or on
# other agents. A role without the key takes the provider's own lifetime.
CACHES = ("long",)
QUESTIONS = ("one-at-a-time", "all-together")
DENSITIES = ("brief", "full")
# The one string ``process.recommend`` takes besides true and false.
RECOMMEND_WORDS = ("accept",)

# A role id, as in roles/README.md, and a provider name: kebab-case.
_KEBAB = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")


def is_id(text: str) -> bool:
    """Whether ``text`` can be a role id or a provider name."""
    return bool(_KEBAB.fullmatch(text))


class Value:
    """A string, integer or boolean. A string is never empty, nor only
    white space. For a boolean, ``choices`` are the strings it takes besides
    true and false."""

    def __init__(self, type: str, choices: tuple[str, ...] = (), minimum: int | None = None) -> None:
        self.type = type
        self.choices = choices
        self.minimum = minimum


class Table:
    """A table with fixed keys, and optionally any number of named entries.

    ``each`` is the node of an entry whose key is not one of ``keys``, such
    as a role id under ``[roles]``; ``each_name`` says what such a key is.
    """

    def __init__(self, keys: dict[str, "Node"] | None = None, each: "Node | None" = None,
                 each_name: str = "") -> None:
        self.keys = keys or {}
        self.each = each
        self.each_name = each_name

    def child(self, key: str) -> "Node | None":
        if key in self.keys:
            return self.keys[key]
        if self.each is not None and _KEBAB.fullmatch(key):
            return self.each
        return None

    def known(self) -> str:
        names = list(self.keys)
        if self.each is not None:
            names.append(f"<{self.each_name}>")
        return ", ".join(names)


class Strings:
    """An array of strings, none of them empty and none given twice."""


Node = Value | Table | Strings

_STRING = Value("string")
_BOOLEAN = Value("boolean")

# A provider's section. One ships per provider in
# providers/<name>/dictionary.toml, which holds these keys among its own
# (see ``dictionary``).
PROVIDER = Table({
    "tiers": Table({tier: _STRING for tier in TIERS}),
    "efforts": Table({effort: _STRING for effort in EFFORTS}),
    "role_models": Table(each=_STRING, each_name="role id"),
})

# ``process.docs_dir`` and ``memory.dir`` are directories, taken as given:
# relative to the project unless absolute. ``process.docs_dir`` is free to
# point outside the project, because sprint docs can live in a separate
# repository; the memory skill stops on a ``memory.dir`` that does. The only
# check here is that the value is not blank. Nothing here looks at the path, and
# whoever reads the setting resolves it against the project.
#
# ``roles.high_stakes`` is the general switch and ``[roles.<id>]`` the
# explicit setting for one role definition: an explicit ``tier`` wins over
# the switch, whichever layer sets each (see ``profiles``).
SCHEMA: dict[str, Table] = {
    "process": Table({
        "docs_dir": _STRING,
        "questions": Value("string", choices=QUESTIONS),
        "recommend": Value("boolean", choices=RECOMMEND_WORDS),
        "density": Value("string", choices=DENSITIES),
    }),
    "roles": Table(
        {
            "manager_default": _BOOLEAN,
            "high_stakes": _BOOLEAN,
            "max_parallel_coders": Value("integer", minimum=1),
        },
        each=Table({
            "tier": Value("string", choices=TIERS),
            "effort": Value("string", choices=EFFORTS),
        }),
        each_name="role id",
    ),
    "memory": Table({
        "dir": _STRING,
    }),
    "providers": Table(each=PROVIDER, each_name="provider name"),
}
GROUPS = tuple(SCHEMA)

# ``install``: what a place installs, by name: the skills of the clone, the
# rule and ``roles`` (the role definitions and a session's entry points). It
# is a key of the file itself, above every table, and no group: a reader of
# a group never meets a fault in it (``check_install``, ``settings.install``).
# Each layer's list replaces the one below it whole.
INSTALL_KEY = "install"
INSTALL = Strings()
ROLES_ITEM = "roles"
# The keys ``install`` replaces, each with what replaces it. They are no part
# of the schema: a file that holds one is not faulted for it and the key is
# not read (``settings.resolve`` skips it), and ``settings.old_keys`` names
# each one a file holds.
OLD_KEYS: dict[str, str] = {
    "setup.enabled": "install in ~/.agents/workflow.toml",
    "setup.disabled": "install in ~/.agents/workflow.toml",
    "project.enabled": "install in the project's .agents/workflow.toml",
    "project.disabled": "install in the project's .agents/workflow.local.toml",
    "roles.enabled": "roles in install",
    "setup.allow_unshared_clone": "none: setup warns on such a clone",
}
# The tables an old key lived in that the schema no longer has: a file that
# holds one with old keys alone is not faulted for it.
OLD_TABLES = tuple(sorted({key.split(".")[0] for key in OLD_KEYS} - set(SCHEMA)))
_ROOT = Table(dict(SCHEMA))


def check_document(data: dict[str, Any], file: Any, problems: list[str]) -> bool:
    """Check what holds for the file as a whole: its version, and the names
    of its top-level keys. No group's content is looked at, nor
    ``install``'s: ``check_install`` checks that.

    Returns False when the file is from a newer schema; nothing else in it
    is then worth checking.
    """
    version = data.get(VERSION_KEY, SCHEMA_VERSION)
    if tomlio.type_name(version) != "integer":
        problems.append(f"{file}: {VERSION_KEY}: expected an integer, got {tomlio.article(tomlio.type_name(version))}")
    elif version > SCHEMA_VERSION:
        problems.append(
            f"{file}: {VERSION_KEY}: {version} is newer than this tool reads ({SCHEMA_VERSION}); "
            "update the clone the tool runs from, or bring the file back to the older schema"
        )
        return False
    elif version < 1:
        problems.append(f"{file}: {VERSION_KEY}: {version} is not a schema version; the first is 1")
    for key in data:
        if key not in (VERSION_KEY, INSTALL_KEY) and key not in SCHEMA and not _old_table(key, data[key]):
            problems.append(
                f"{file}: {tomlio.format_key(key)}: unknown key; known here: "
                f"{VERSION_KEY}, {INSTALL_KEY}, {', '.join(GROUPS)}"
            )
    return True


def _old_table(key: str, value: Any) -> bool:
    """A table of the old keys that the schema no longer has, holding old keys alone."""
    return key in OLD_TABLES and isinstance(value, dict) and all(f"{key}.{name}" in OLD_KEYS for name in value)


def strip_old_keys(group: str, content: Any) -> Any:
    """``content`` of ``group`` without the keys of ``OLD_KEYS``."""
    if not isinstance(content, dict):
        return content
    return {name: item for name, item in content.items() if f"{group}.{name}" not in OLD_KEYS}


def check_install(data: dict[str, Any], file: Any, problems: list[str]) -> None:
    """Check the file's ``install``: an array of names, none blank and none
    given twice, and no ``install`` inside a table, where a line added below
    ``[memory]`` is read as ``memory.install``. Of the groups nothing else is
    looked at."""
    if INSTALL_KEY in data:
        _validate(INSTALL, data[INSTALL_KEY], (INSTALL_KEY,), file, problems)
    tables = [((key,), value) for key, value in data.items() if isinstance(value, dict)]
    for path, table in tables:   # a loop, not recursion: tables may nest deeper than Python recurses
        for key, value in table.items():
            if isinstance(value, dict):
                tables.append((path + (key,), value))
            elif key == INSTALL_KEY and isinstance(value, list):
                problems.append(_misplaced(path, file))


def _misplaced(table: tuple[str, ...], file: Any) -> str:
    """An ``install`` list read as a key of ``table``."""
    key = tomlio.dotted(table + (INSTALL_KEY,))
    return (
        f"{file}: {key}: {INSTALL_KEY} belongs at the top of the file, above every table; "
        f"here, below [{tomlio.dotted(table)}], it is read as {key}"
    )


def validate(group: str, value: Any, file: Any, problems: list[str]) -> None:
    """Check one group's content, adding a line to ``problems`` per fault.
    The keys of ``OLD_KEYS`` are not looked at."""
    value = strip_old_keys(group, value)
    _validate(SCHEMA[group], value, (group,), file, problems)


def check(node: Node, value: Any, path: tuple[str, ...], file: Any, problems: list[str]) -> None:
    """Check ``value``, found at ``path`` of ``file``, against any node. For
    files that are not settings files, such as a provider dictionary."""
    _validate(node, value, path, file, problems)


def _validate(node: Node, value: Any, path: tuple[str, ...], file: Any, problems: list[str]) -> None:
    where = f"{file}: {tomlio.dotted(path)}"
    actual = tomlio.type_name(value)
    if isinstance(node, Strings):
        if actual != "array":
            problems.append(f"{where}: expected an array of strings, got {tomlio.article(actual)}")
            return
        for index, item in enumerate(value):
            if not isinstance(item, str):
                problems.append(
                    f"{where}: expected an array of strings, but item {index + 1} is "
                    f"{tomlio.article(tomlio.type_name(item))}"
                )
            elif not item.strip():
                problems.append(f"{where}: item {index + 1} must not be {'blank' if item else 'empty'}")
            elif item in value[:index]:
                problems.append(f"{where}: {tomlio.format_value(item)} is given twice")
        return
    if isinstance(node, Value):
        if node.type == "boolean" and node.choices:
            if actual != "boolean" and value not in node.choices:
                shown = (str(value) if actual == "integer" else tomlio.format_value(value)) if actual in ("string", "integer") else tomlio.article(actual)
                problems.append(
                    f"{where}: {shown} is not allowed; allowed values: true, false, {', '.join(node.choices)}"
                )
            return
        if actual != node.type:
            problems.append(f"{where}: expected {tomlio.article(node.type)}, got {tomlio.article(actual)}")
        elif node.choices and value not in node.choices:
            problems.append(
                f"{where}: {tomlio.format_value(value)} is not allowed; "
                f"allowed values: {', '.join(node.choices)}"
            )
        elif node.minimum is not None and value < node.minimum:
            problems.append(f"{where}: {value} is too small; the least allowed is {node.minimum}")
        elif node.type == "string" and not value:
            problems.append(f"{where}: must not be empty")
        elif node.type == "string" and not value.strip():
            problems.append(f"{where}: must not be blank; it holds only white space")
        return
    if actual != "table":
        problems.append(f"{where}: expected a table, got {tomlio.article(actual)}")
        return
    for key, item in value.items():
        if key == INSTALL_KEY and key not in node.keys and isinstance(item, list):
            problems.append(_misplaced(path, file))
            continue
        child = node.child(key)
        if child is not None:
            _validate(child, item, path + (key,), file, problems)
        elif node.each is not None and isinstance(item, dict):
            problems.append(
                f"{file}: {tomlio.dotted(path + (key,))}: not a {node.each_name} "
                "(lower-case letters, digits and single hyphens)"
            )
        else:
            problems.append(f"{file}: {tomlio.dotted(path + (key,))}: unknown key; known here: {node.known()}")


def flatten(value: Any, path: tuple[str, ...]) -> list[tuple[str, Any]]:
    """The leaves of a validated group as (dotted key, value) pairs."""
    if not isinstance(value, dict):
        return [(".".join(path), value)]
    leaves: list[tuple[str, Any]] = []
    for key, item in value.items():
        leaves.extend(flatten(item, path + (key,)))
    return leaves


def order(key: str) -> list[tuple[int, Any]]:
    """A sort key for a dotted key: fixed keys in the schema's order, then
    named entries (role ids, provider names) alphabetically."""
    node: Node | None = _ROOT
    rank: list[tuple[int, Any]] = []
    for part in key.split("."):
        fixed = list(node.keys) if isinstance(node, Table) else []
        if part in fixed:
            rank.append((0, fixed.index(part)))
        else:
            rank.append((1, part))
        node = node.child(part) if isinstance(node, Table) else None
    return rank


_DOTTED_KEY = re.compile(r"""\s*(?:[A-Za-z0-9_-]+|"[^"\n]*"|'[^'\n]*')(?:\s*\.\s*(?:[A-Za-z0-9_-]+|"[^"\n]*"|'[^'\n]*'))*\s*""")


def parse_key(text: str) -> tuple[str, ...]:
    """Split a key given on the command line and check that the schema has
    such a place: a group, a table in it, or one value."""
    try:   # a TOML key, so a part may be quoted: providers."claude-code".role_models.coder
        if not _DOTTED_KEY.fullmatch(text):
            raise ValueError(text)   # more than one key: "a = 1 #", "[a]\nb"
        parsed: Any = tomllib.loads(f"{text} = 0")
        parts = []
        while isinstance(parsed, dict):
            (name, parsed), = parsed.items()
            parts.append(name)
        parts = tuple(parts)
    except (tomllib.TOMLDecodeError, ValueError):
        parts = tuple(text.split("."))
    node: Node = _ROOT
    for index, part in enumerate(parts):
        child = node.child(part) if isinstance(node, Table) else None
        if child is None:
            above = ".".join(parts[:index])
            if isinstance(node, Table):
                hint = f"known {'under ' + above if above else 'groups'}: {node.known()}"
            else:
                hint = f"{above} is a single value"
            raise SetupError(f"{text}: no such setting; {hint}")
        node = child
    return parts
