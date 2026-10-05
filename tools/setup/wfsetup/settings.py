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

``resolve`` is asked for groups and touches nothing else: of each file it
checks the version and the top-level key names, then validates and merges
only the groups asked for. A fault inside ``[providers.x]`` therefore cannot
break a reader of ``[process]``. What no reader can be shielded from is a
file that does not parse at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import dictionary, paths, schema, tomlio
from .errors import SetupError
from .locations import Locations

LAYERS = ("shipped", "user", "project", "local")


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


def resolve(where: Locations, groups: Iterable[str] = schema.GROUPS) -> dict[str, Entry]:
    """The effective value of every key of ``groups``, by dotted key, in the
    schema's order. Every fault found in those groups is reported at once."""
    groups = tuple(groups)
    problems: list[str] = []
    merged: dict[str, Entry] = {}
    for document in documents(where, groups):
        if not schema.check_document(document.data, document.file, problems):
            continue
        for group in groups:
            if group not in document.data:
                continue
            content = document.data[group]
            before = len(problems)
            schema.validate(group, content, document.file, problems)
            if len(problems) > before:
                continue
            for key, value in schema.flatten(content, (group,)):
                merged[key] = Entry(value, document.layer, document.file)
    if problems:
        raise SetupError(*problems)
    return {key: merged[key] for key in sorted(merged, key=schema.order)}
