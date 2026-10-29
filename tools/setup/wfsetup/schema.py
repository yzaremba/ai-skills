"""What a settings file may hold.

The schema is a tree of ``Table`` and ``Value`` nodes, one subtree per group.
Groups are validated one at a time, so that a reader of one group never
depends on another (see ``settings.resolve``).
"""
from __future__ import annotations

import re
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
#
# ``roles.enabled`` is whether ``render`` generates the roles at all: false
# is the process alone, what ``render --no-roles`` does for one run. No role
# id can be ``enabled``: Codex reserves it (``validate``, role-reserved).
#
# ``[setup]`` is read by the setup tool alone, and from the user's file
# alone (``USER_ONLY``): it holds facts of this machine, not of a project.
# ``setup.allow_unshared_clone`` is what ``--allow-unshared-clone`` says for
# one run, decided once. ``setup.enabled`` and ``setup.disabled`` name the
# skills and rules a home installs and goes without; which names they may
# hold is checked against the clone where they are read
# (``definitions.list_problems``).
SCHEMA: dict[str, Table] = {
    "process": Table({
        "docs_dir": _STRING,
        "questions": Value("string", choices=QUESTIONS),
        "recommend": Value("boolean", choices=RECOMMEND_WORDS),
        "density": Value("string", choices=DENSITIES),
    }),
    "roles": Table(
        {
            "enabled": _BOOLEAN,
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
    "setup": Table({
        "allow_unshared_clone": _BOOLEAN,
        "enabled": Strings(),
        "disabled": Strings(),
    }),
}
GROUPS = tuple(SCHEMA)
# The groups a project's files may not hold: read from the user's file alone.
USER_ONLY = ("setup",)
_ROOT = Table(dict(SCHEMA))


def check_document(data: dict[str, Any], file: Any, problems: list[str]) -> bool:
    """Check what holds for the file as a whole: its version, and the names
    of its top-level keys. No group's content is looked at.

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
        if key != VERSION_KEY and key not in SCHEMA:
            problems.append(
                f"{file}: {tomlio.format_key(key)}: unknown key; known here: {VERSION_KEY}, {', '.join(GROUPS)}"
            )
    return True


def validate(group: str, value: Any, file: Any, problems: list[str]) -> None:
    """Check one group's content, adding a line to ``problems`` per fault."""
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
                shown = tomlio.format_value(value) if actual in ("string", "integer") else tomlio.article(actual)
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


def parse_key(text: str) -> tuple[str, ...]:
    """Split a key given on the command line and check that the schema has
    such a place: a group, a table in it, or one value."""
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
