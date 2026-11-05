"""The settings layers, and the effective value of each key.

Layers, later wins, key by key:

    shipped   tools/setup/defaults.toml, and for the providers group the
              provider dictionaries (see ``_dictionary_documents``)
    user      ~/.agents/workflow.toml
    project   <project>/.agents/workflow.toml
    local     <project>/.agents/workflow.local.toml

A layer whose file does not exist is simply absent. A file that is there
and cannot be read is an error, and so is a link in its place whose target
is missing, and a ``.agents`` that is not a directory.

A key of ``schema.OLD_KEYS`` is no part
of the schema: ``resolve`` skips it, and ``old_keys`` names it.

``resolve`` is asked for groups and touches nothing else: of each file it
checks the version and the top-level key names, then validates and merges
only the groups asked for. A fault inside ``[providers.x]`` therefore cannot
break a reader of ``[process]``. What no reader can be shielded from is a
file that does not parse at all.

``install``, the top-level list of what a place installs, is no group:
``install`` reads it, each layer's value apart, and a fault in it breaks no
reader of a group. ``old_keys`` names each key it replaces that a user's or
a project's file holds.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import dictionary, paths, schema, tomlio
from .errors import SetupError
from .locations import Locations

LAYERS = ("shipped", "user", "project", "local")
# The layers of a project's files.
PROJECT_LAYERS = ("project", "local")


@dataclass(frozen=True)
class Document:
    """One parsed file of a layer."""

    layer: str
    file: Path
    data: dict[str, Any]


@dataclass(frozen=True)
class Entry:
    """An effective value, the layer that decided it and that layer's file."""

    value: Any
    layer: str
    file: Path


def documents(where: Locations, groups: Iterable[str] = schema.GROUPS) -> list[Document]:
    """The files that exist, in the order they are applied."""
    found: list[Document] = []
    shipped = tomlio.load_if_present(where.defaults_file)
    if shipped is None:
        raise SetupError(f"{where.defaults_file}: the shipped defaults are missing; the clone is incomplete")
    found.append(Document("shipped", where.defaults_file, shipped))
    if "providers" in groups:
        found.extend(_dictionary_documents(where))
    for layer, file in (("user", where.user_file), ("project", where.project_file), ("local", where.local_file)):
        if file is None:
            continue
        data = _load_layer(file)
        if data is not None:
            found.append(Document(layer, file, data))
    return found


def _load_layer(file: Path) -> dict[str, Any] | None:
    """A user, project or local file, or None when it is not there.

    Not there means nothing at all at its place. A settings directory that
    is a file, or a file that is a link with no target, is a mistake to
    report: read as absent, it would silently give the shipped values.
    """
    directory = file.parent
    found = paths.kind(directory)
    if found == paths.ABSENT:
        return None
    if found != paths.DIRECTORY:
        raise SetupError(f"{directory}: is not a directory; {file.name} is looked for in it")
    return tomlio.load_if_present(file)


def _dictionary_documents(where: Locations) -> list[Document]:
    """The shipped layer of each ``[providers.<name>]`` section.

    ``providers/<name>/dictionary.toml`` holds, at its top level, the keys of
    a provider section (``schema.PROVIDER``: ``tiers``, ``efforts``,
    ``role_models``) beside what else the dictionary records. Each dictionary
    is validated whole (``dictionary.load_all``), with its faults named by
    its own keys, and those three keys are lifted into ``providers.<name>``.
    The other keys are not settings; ``dictionary`` is where they are read.
    """
    return [
        Document("shipped", loaded.file, {"providers": {provider: loaded.settings}})
        for provider, loaded in dictionary.load_all(where).items()
    ]


def resolve(
    where: Locations, groups: Iterable[str] = schema.GROUPS, layers: Iterable[str] = LAYERS
) -> dict[str, Entry]:
    """The effective value of every key of ``groups``, by dotted key, in the
    schema's order. Every fault found in those groups is reported at once.

    With ``layers``, only those layers count: what the values would be
    without the others, which is what ``init`` compares a file with. A
    layer left out is not checked either; its file must still parse.
    """
    groups = tuple(groups)
    layers = tuple(layers)
    problems: list[str] = []
    merged: dict[str, Entry] = {}
    for document in documents(where, groups):
        if document.layer not in layers:
            continue
        if not schema.check_document(document.data, document.file, problems):
            continue
        for group in groups:
            if group not in document.data:
                continue
            content = document.data[group]
            before = len(problems)
            content = schema.strip_old_keys(group, content)
            schema.validate(group, content, document.file, problems)
            if len(problems) > before:
                continue
            for key, value in schema.flatten(content, (group,)):
                merged[key] = Entry(value, document.layer, document.file)
    if problems:
        raise SetupError(*problems)
    return {key: merged[key] for key in sorted(merged, key=schema.order)}


def install(where: Locations) -> list[Entry]:
    """``install`` of each layer that gives it, in the order the layers
    apply, so a reader takes the user's over the shipped one and the local
    over the project's (each replaces the one below it whole). A home's
    ``where`` has no project, so its layers are shipped and user. Every
    fault of ``install`` is reported at once, and one inside a table among
    them; nothing else of a group is looked at."""
    problems: list[str] = []
    found: list[Entry] = []
    for document in documents(where, ()):
        if not schema.check_document(document.data, document.file, problems):
            continue
        before = len(problems)
        schema.check_install(document.data, document.file, problems)
        if len(problems) == before and schema.INSTALL_KEY in document.data:
            found.append(Entry(document.data[schema.INSTALL_KEY], document.layer, document.file))
    if problems:
        raise SetupError(*problems)
    return found


def old_keys(where: Locations) -> list[tuple[Path, str, str]]:
    """Each key of ``schema.OLD_KEYS`` that a user's or a project's file
    holds, as (file, dotted key, what replaces it), in the order the layers
    apply. The shipped defaults are not the user's to change and are not
    named."""
    found: list[tuple[Path, str, str]] = []
    for document in documents(where, ()):
        if document.layer == "shipped":
            continue
        for key, replacement in schema.OLD_KEYS.items():
            group, name = key.split(".")
            table = document.data.get(group)
            if isinstance(table, dict) and name in table:
                found.append((document.file, key, replacement))
    return found
