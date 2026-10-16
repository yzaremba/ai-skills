"""The model and effort a role definition runs with on a provider.

Decided in this order, each step replacing what the one before gave:

    1. ``role.toml``: ``[profile]`` ``tier`` and ``effort``; for the hard
       definition, ``[profile.hard]``.
    2. ``high_stakes_tier`` of ``[profile]`` in place of the tier, when the
       setting ``roles.high_stakes`` is true. The hard definition has none
       (see ``roles``).
    3. The settings ``[roles.<id>]``: ``tier`` and ``effort``, each on its
       own. ``<id>`` is the definition's id, so ``[roles.coder]`` leaves
       ``coder-hard`` alone and ``[roles.coder-hard]`` is its own table.
    4. The provider's maps: ``providers.<name>.tiers`` gives the model and
       ``providers.<name>.efforts`` the provider's effort value. An entry
       for the definition's id in ``providers.<name>.role_models`` is the
       model whatever the tier.

Step 3 comes after step 2 whichever layer sets each: an explicit
``[roles.<id>] tier`` beats ``roles.high_stakes``, even when the tier is set
in the user's file and the switch in a project's. An explicit setting for
one role wins over the general switch; the layers only decide between two
settings of the same key.

The effort value is then checked against the provider's dictionary:

    - the model does not accept it: an error;
    - the dictionary lists the model as taking no effort setting: there is
      no effort (``Resolved.effort`` is None), and a note says why;
    - the dictionary does not list the model: the value stands unchecked,
      and a note says so.

The cache is apart from these steps: ``[profile]`` ``cache`` of ``role.toml``
names one, the provider's dictionary maps the name to its own value under
``[cache]``, and no setting changes either. A provider whose dictionary has
no such entry has no such setting: the key is accepted and nothing is
written for it there, without a note.

Each value keeps where it came from (``Source``). A value read from
``role.toml`` has the layer ``role``; the others have a settings layer.
When the high-stakes tier is the tier in effect, the setting that switched
it on (``Resolved.high_stakes``) is part of what decided the model, and its
layer counts in ``Resolved.model_layer``.

A provider is one that has a dictionary; a ``[providers.<name>]`` section
for any other name is not resolved against. Such a section, and an override
for a role id that no definition has, change nothing. They are not errors,
because a project may define its own specialist later, but they are said:
``resolution`` returns them as notes (``unmatched``) beside the profiles.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import dictionary, roles, settings, tomlio
from .dictionary import Dictionary
from .errors import SetupError
from .locations import Locations
from .roles import Definition

ROLE_LAYER = "role"
GROUPS = ("roles", "providers")
HIGH_STAKES_KEY = "roles.high_stakes"

# Which of two layers had the later say. The dictionary's mapping is the
# ground every profile stands on, so ``role`` counts as later than it.
_SAY = ("shipped", ROLE_LAYER, "user", "project", "local")


@dataclass(frozen=True)
class Source:
    """A value, the layer and file it came from, and its key in that file."""

    value: Any
    layer: str
    file: Path
    key: str


@dataclass(frozen=True)
class Resolved:
    """What one definition runs with on one provider.

    ``tier`` and ``effort_name`` are the framework's names, after steps 1 to
    3. ``high_stakes`` is the setting ``roles.high_stakes`` when it is why
    ``tier`` is the role's high-stakes tier, and None otherwise (the switch
    is off, the role has no such tier, or an explicit tier override took its
    place). ``model_from`` is the entry that named the model: a key of
    ``tiers``, or of ``role_models``. ``effort_from`` is the entry of
    ``efforts`` that mapped the effort name. ``effort`` is None for a model
    that takes no effort setting; a definition is then written without one.
    ``cache`` is the provider's value for the cache the role names, and
    None for a role that names none or a provider that has no such setting.
    """

    definition: str
    role: str
    provider: str
    tier: Source
    effort_name: Source
    model: str
    model_from: Source
    effort: str | None
    effort_from: Source
    notes: tuple[str, ...] = ()
    high_stakes: Source | None = None
    cache: str | None = None

    @property
    def explicit_model(self) -> bool:
        """True when ``role_models`` named the model, and the tier did not."""
        return ".role_models." in self.model_from.key

    @property
    def model_layer(self) -> str:
        """The layer that decided the model: that of the ``role_models``
        entry, or the latest of the tier's layer, the tier map's, and, when
        the tier is the high-stakes one, that of ``roles.high_stakes``."""
        if self.explicit_model:
            return self.model_from.layer
        layers = [self.tier.layer, self.model_from.layer]
        if self.high_stakes is not None:
            layers.append(self.high_stakes.layer)
        return _latest(layers)

    @property
    def effort_layer(self) -> str | None:
        """The layer that decided the effort: the later of the effort
        name's layer and the effort map's. None when there is no effort:
        no layer decided a value that is not there."""
        if self.effort is None:
            return None
        return _latest([self.effort_name.layer, self.effort_from.layer])


@dataclass(frozen=True)
class Resolution:
    """Every profile, and what the settings say that matched nothing."""

    profiles: tuple[Resolved, ...]
    notes: tuple[str, ...] = ()


def _latest(layers: Iterable[str]) -> str:
    return max(layers, key=_SAY.index)


def resolution(where: Locations) -> Resolution:
    """Every definition on every provider that has a dictionary: by
    definition (``roles.definitions``), then by provider name; and the
    notes of ``unmatched``. The faults of the role files, the settings and
    the dictionaries, and every effort a model does not accept, are
    reported together."""
    problems: list[str] = []
    loaded: list[Any] = []
    for read in (
        lambda: roles.definitions(where),
        # One group at a time: a dictionary that cannot be read stops the
        # providers group before its settings are looked at, and must not
        # hide a fault of the roles group.
        *(lambda group=group: settings.resolve(where, (group,)) for group in GROUPS),
        lambda: dictionary.load_all(where),
    ):
        try:
            loaded.append(read())
        except SetupError as exc:
            problems.extend(line for line in exc.lines if line not in problems)
    if problems:
        raise SetupError(*problems)
    found, *groups, dictionaries = loaded
    entries = {key: entry for group in groups for key, entry in group.items()}

    resolved: list[Resolved] = []
    for definition in found:
        for provider in sorted(dictionaries):
            try:
                resolved.append(resolve_definition(definition, dictionaries[provider], entries))
            except SetupError as exc:
                problems.extend(exc.lines)
    if problems:
        raise SetupError(*problems)
    notes = unmatched([definition.id for definition in found], sorted(dictionaries), entries)
    return Resolution(tuple(resolved), tuple(notes))


def resolve_all(where: Locations) -> list[Resolved]:
    """The profiles of ``resolution``, without its notes."""
    return list(resolution(where).profiles)


def unmatched(definitions: list[str], providers: list[str], entries: dict[str, settings.Entry]) -> list[str]:
    """What the effective settings ``entries`` (the groups ``GROUPS``) set
    for something that is not there, one line each, naming the file:

        - a ``[roles.<id>]`` table whose id no definition has;
        - a ``[providers.<name>]`` section of a provider with no dictionary;
        - a ``role_models`` key, under a provider that has one, whose id no
          definition has.

    ``definitions`` are the definition ids and ``providers`` the names of
    the providers with a dictionary. A line is a note and not a fault: the
    settings are valid, and a role of that id may be defined later. Only
    keys that hold a value are seen; an empty table sets nothing.
    """
    known = ", ".join(definitions) or "none"
    notes: list[str] = []

    def note(line: str) -> None:
        if line not in notes:
            notes.append(line)

    for key, entry in entries.items():
        parts = key.split(".")
        if parts[0] == "roles" and len(parts) == 3 and parts[1] not in definitions:
            note(
                f"{entry.file}: roles.{parts[1]}: no role definition has the id {parts[1]}, "
                f"so this override changes nothing; definitions: {known}"
            )
        elif parts[0] == "providers" and len(parts) > 2 and parts[1] not in providers:
            note(
                f"{entry.file}: providers.{parts[1]}: no provider of this name has a dictionary, "
                f"so this section is not used; providers: {', '.join(providers) or 'none'}"
            )
        elif parts[0] == "providers" and len(parts) == 4 and parts[2] == "role_models" and parts[3] not in definitions:
            note(
                f"{entry.file}: {key}: no role definition has the id {parts[3]}, "
                f"so this model is given to nothing; definitions: {known}"
            )
    return notes


def resolve(where: Locations, definition: str, provider: str) -> Resolved:
    """One definition, by id, on one provider."""
    for found in resolve_all(where):
        if (found.definition, found.provider) == (definition, provider):
            return found
    known = roles.definitions(where)
    if definition not in [item.id for item in known]:
        raise SetupError(
            f"{definition}: no such role definition; known: {', '.join(item.id for item in known) or 'none'}"
        )
    raise SetupError(
        f"{provider}: no such provider; those with a dictionary: {', '.join(dictionary.files(where)) or 'none'}"
    )


def resolve_definition(definition: Definition, known: Dictionary, entries: dict[str, settings.Entry]) -> Resolved:
    """``definition`` on the provider of the dictionary ``known``, with the
    effective settings ``entries`` (the groups ``GROUPS``)."""
    provider = known.provider
    tier = Source(definition.tier, ROLE_LAYER, definition.file, f"{definition.key}.tier")
    effort_name = Source(definition.effort, ROLE_LAYER, definition.file, f"{definition.key}.effort")
    high_stakes = _setting(entries, HIGH_STAKES_KEY)
    if definition.high_stakes_tier is not None and high_stakes is not None and high_stakes.value is True:
        tier = Source(
            definition.high_stakes_tier, ROLE_LAYER, definition.file, f"{definition.key}.high_stakes_tier"
        )
    else:
        high_stakes = None
    # An explicit tier for this definition wins over the general switch,
    # whichever layer set each; the switch then decided nothing.
    tier_override = _setting(entries, f"roles.{definition.id}.tier")
    if tier_override is not None:
        tier, high_stakes = tier_override, None
    effort_name = _setting(entries, f"roles.{definition.id}.effort") or effort_name

    model_from = _setting(entries, f"providers.{provider}.role_models.{definition.id}")
    if model_from is None:
        model_from = _mapped(entries, f"providers.{provider}.tiers.{tier.value}", definition, provider)
    effort_from = _mapped(entries, f"providers.{provider}.efforts.{effort_name.value}", definition, provider)
    model: str = model_from.value
    effort: str | None = effort_from.value

    notes: list[str] = []
    entry = known.model(model)
    if entry is None:
        notes.append(
            f"the {provider} dictionary does not list the model {tomlio.format_value(model)}, "
            f"so the effort {tomlio.format_value(effort)} is not checked"
        )
    elif not entry.takes_effort:
        notes.append(
            f"the {provider} dictionary lists the model {tomlio.format_value(model)} as taking "
            "no effort setting, so none is written"
        )
        effort = None
    elif not known.accepts(model, effort):
        raise SetupError(
            f"role {definition.id}, provider {provider}: the model {tomlio.format_value(model)} does not "
            f"accept the effort {tomlio.format_value(effort)}; it accepts: {', '.join(entry.efforts)}. "
            f"The model is from {model_from.key} ({model_from.file}); the effort is "
            f"{effort_name.key} = {tomlio.format_value(effort_name.value)} ({effort_name.file}), "
            f"mapped by {effort_from.key} ({effort_from.file})"
        )
    return Resolved(
        definition=definition.id,
        role=definition.role,
        provider=provider,
        tier=tier,
        effort_name=effort_name,
        model=model,
        model_from=model_from,
        effort=effort,
        effort_from=effort_from,
        notes=tuple(notes),
        high_stakes=high_stakes,
        cache=None if definition.cache is None else known.cache.get(definition.cache),
    )


def _setting(entries: dict[str, settings.Entry], key: str) -> Source | None:
    entry = entries.get(key)
    return None if entry is None else Source(entry.value, entry.layer, entry.file, key)


def _mapped(entries: dict[str, settings.Entry], key: str, definition: Definition, provider: str) -> Source:
    found = _setting(entries, key)
    if found is None:
        # A dictionary maps every tier and effort name, so this is a clone
        # whose dictionary and settings were not read together.
        raise SetupError(f"role {definition.id}, provider {provider}: {key} is set in no layer")
    return found
