"""A provider's dictionary: ``providers/<name>/dictionary.toml``.

A dictionary records what was checked about one provider on one day:

    schema_version            1; absent means 1
    checked_on_version        the provider version the entries were checked on
    checked_on_date           that day, as YYYY-MM-DD
    oldest_supported_version  optional: the oldest provider version supported
    [model_list]              how the provider's own model list is read
        command               optional: the command, as an argument list; when
                              absent, no command lists models without a session
        offline_command       optional: the same list read without the network
        experimental          optional: the provider may change the command
                              without notice
        note                  optional: a sentence for the user
    [tiers]                   tier -> model; all four tiers
    [efforts]                 effort name -> the provider's value; all four
    [role_models]             optional: role id -> model
    [models.<name>]           one table per known model
        efforts               the effort values the model accepts; empty for a
                              model that takes no effort setting
        visibility            optional: as the provider lists it
        default_effort        optional: the model's own default

``tiers``, ``efforts`` and ``role_models`` are the shipped layer of the
settings section ``[providers.<name>]`` (``Dictionary.settings``); the rest
is not a setting and no settings file can override it.

Beyond keys and types a dictionary must agree with itself: a tier maps to a
model the file lists, an effort name maps to a value at least one listed
model accepts, a default effort is one the model accepts, and the oldest
supported version is not newer than the checked one. Every fault names the
file and the key, and all of a file's faults are reported at once.

Only a reader of the providers group opens these files (see
``settings.resolve``).
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths, schema, tomlio
from .errors import SetupError
from .locations import Locations
from .schema import Strings, Table, Value

DICTIONARY_FILE = "dictionary.toml"

# The version this tool reads; a dictionary has its own, apart from the
# settings files'.
SCHEMA_VERSION = 1

_STRING = Value("string")

# A version is numbers separated by dots. A part has a bounded number of
# digits: no provider's version needs more, and Python refuses to convert a
# number of thousands of digits.
MAX_VERSION_PART_DIGITS = 9
_VERSION = re.compile(r"[0-9]{1,%d}(?:\.[0-9]{1,%d})*" % (MAX_VERSION_PART_DIGITS, MAX_VERSION_PART_DIGITS))
_UNBOUNDED_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*")
_VERSION_IN_TEXT = re.compile(r"(?<![0-9.])[0-9]+(?:\.[0-9]+)+")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

_MODEL = Table({
    "efforts": Strings(),
    "visibility": _STRING,
    "default_effort": _STRING,
})
_MODEL_REQUIRED = ("efforts",)

# The top-level keys, in the order a dictionary is written. ``models`` is
# checked apart: a model name may hold a dot, which no settings key does.
_KEYS: dict[str, schema.Node | None] = {
    schema.VERSION_KEY: None,
    "checked_on_version": _STRING,
    "checked_on_date": _STRING,
    "oldest_supported_version": _STRING,
    "model_list": Table({
        "command": Strings(),
        "offline_command": Strings(),
        "experimental": Value("boolean"),
        "note": _STRING,
    }),
    **schema.PROVIDER.keys,
    "models": None,
}
_REQUIRED = ("checked_on_version", "checked_on_date", "model_list", "tiers", "efforts", "models")
_SETTINGS_KEYS = tuple(schema.PROVIDER.keys)


@dataclass(frozen=True)
class Model:
    """One known model and the effort values it accepts."""

    name: str
    efforts: tuple[str, ...]
    visibility: str | None = None
    default_effort: str | None = None

    @property
    def takes_effort(self) -> bool:
        """False for a model that has no effort setting at all."""
        return bool(self.efforts)

    def accepts(self, value: str) -> bool:
        return value in self.efforts


@dataclass(frozen=True)
class ModelList:
    """How the provider's own model list is read. ``command`` is None where
    no command lists models without starting a session."""

    command: tuple[str, ...] | None = None
    offline_command: tuple[str, ...] | None = None
    experimental: bool = False
    note: str = ""


@dataclass(frozen=True)
class Dictionary:
    provider: str
    file: Path
    checked_on_version: str
    checked_on_date: datetime.date
    oldest_supported_version: str | None
    model_list: ModelList
    tiers: dict[str, str]
    efforts: dict[str, str]
    role_models: dict[str, str]
    models: dict[str, Model]

    def model(self, name: str) -> Model | None:
        """The entry of a model, or None for a model the file does not list
        (a full model id a user named, or a model newer than the file)."""
        return self.models.get(name)

    def accepts(self, model: str, value: str) -> bool | None:
        """Whether ``model`` accepts the provider effort value ``value``.
        None when the file does not list the model, so nothing is known."""
        entry = self.models.get(model)
        return None if entry is None else entry.accepts(value)

    @property
    def settings(self) -> dict[str, dict[str, str]]:
        """The part that is the shipped layer of ``[providers.<name>]``."""
        section = {"tiers": dict(self.tiers), "efforts": dict(self.efforts)}
        if self.role_models:
            section["role_models"] = dict(self.role_models)
        return section


def version_fault(text: str) -> str | None:
    """Why ``text`` is not a version this tool reads, or None when it is one."""
    if _VERSION.fullmatch(text):
        return None
    if _UNBOUNDED_VERSION.fullmatch(text):
        return f"a part has more than {MAX_VERSION_PART_DIGITS} digits"
    return "digits separated by dots"


def parse_version(text: str) -> tuple[int, ...]:
    """A dotted version as numbers, so that two versions compare. Strict:
    the whole of ``text`` is the version. A provider's own output is read
    with ``find_version`` first."""
    fault = version_fault(text)
    if fault is not None:
        raise SetupError(f"{_shown(text)}: not a version ({fault})")
    return tuple(int(part) for part in text.split("."))


def find_version(text: str) -> str | None:
    """The first dotted version in a line a provider prints about itself,
    such as ``2.1.289 (Claude Code)`` or ``codex-cli 0.160.0``, in the form
    ``parse_version`` takes; None when the line holds none.

    Lenient where ``parse_version`` is strict: text around the version is
    skipped, and a pre-release or build suffix (``0.161.0-alpha.2``,
    ``1.2.3+build5``, ``1.2.3rc1``) is ignored, so such a client compares as
    the release it leads to. A lone number is not taken for a version: at
    least one dot is needed.
    """
    found = _VERSION_IN_TEXT.search(text)
    if found is None or version_fault(found.group()) is not None:
        return None
    return found.group()


def _shown(text: str) -> str:
    """``text``, cut short when it is too long to be worth a line."""
    return text if len(text) <= 40 else text[:40] + "..."


def files(where: Locations) -> dict[str, Path]:
    """The dictionary file of each provider that has one, by provider name.

    A provider directory with nothing at the file's place has no dictionary.
    One with a link there whose target is missing, or one that cannot be
    looked into, is listed: ``check_file`` then says what is wrong, where
    silence would drop the provider.
    """
    found: dict[str, Path] = {}
    for directory in paths.entries(where.providers_dir):
        try:
            if paths.kind(directory) != paths.DIRECTORY:
                continue
            file = directory / DICTIONARY_FILE
            if paths.kind(file) == paths.ABSENT:
                continue
        except SetupError:
            file = directory / DICTIONARY_FILE
        found[directory.name] = file
    return found


def load_all(where: Locations) -> dict[str, Dictionary]:
    """Every provider's dictionary, by provider name. The faults of all of
    them are reported together."""
    problems: list[str] = []
    found: dict[str, Dictionary] = {}
    for provider, file in files(where).items():
        loaded = check_file(file, provider, problems)
        if loaded is not None:
            found[provider] = loaded
    if problems:
        raise SetupError(*problems)
    return found


def load(where: Locations, provider: str) -> Dictionary | None:
    """One provider's dictionary, or None when the provider has none."""
    file = files(where).get(provider)
    return None if file is None else load_file(file, provider)


def load_file(file: Path, provider: str | None = None) -> Dictionary:
    """The dictionary at ``file``. ``provider`` defaults to the name of the
    directory the file is in."""
    problems: list[str] = []
    loaded = check_file(file, provider or file.parent.name, problems)
    if loaded is None:
        raise SetupError(*problems)
    return loaded


def check_file(file: Path, provider: str, problems: list[str]) -> Dictionary | None:
    """Read and validate ``file``, adding a line to ``problems`` per fault.
    Returns None when there was any."""
    try:
        # The directory first, so that a link leading nowhere is named.
        paths.kind(file.parent)
        if paths.kind(file) != paths.FILE:
            problems.append(f"{file}: is not a file")
            return None
        data = tomlio.load(file)
    except SetupError as exc:
        problems.extend(exc.lines)
        return None
    before = len(problems)
    if _check_shape(data, file, problems) and len(problems) == before:
        _check_agreement(data, file, problems)
    if len(problems) > before:
        return None
    listing = data["model_list"]
    return Dictionary(
        provider=provider,
        file=file,
        checked_on_version=data["checked_on_version"],
        checked_on_date=datetime.date.fromisoformat(data["checked_on_date"]),
        oldest_supported_version=data.get("oldest_supported_version"),
        model_list=ModelList(
            command=tuple(listing["command"]) if "command" in listing else None,
            offline_command=tuple(listing["offline_command"]) if "offline_command" in listing else None,
            experimental=listing.get("experimental", False),
            note=listing.get("note", ""),
        ),
        tiers=dict(data["tiers"]),
        efforts=dict(data["efforts"]),
        role_models=dict(data.get("role_models", {})),
        models={
            name: Model(name, tuple(entry["efforts"]), entry.get("visibility"), entry.get("default_effort"))
            for name, entry in data["models"].items()
        },
    )


def _check_shape(data: dict[str, Any], file: Path, problems: list[str]) -> bool:
    """Keys and types. Returns False for a file of a newer schema, in which
    nothing else is worth checking."""
    version = data.get(schema.VERSION_KEY, SCHEMA_VERSION)
    if tomlio.type_name(version) != "integer":
        problems.append(
            f"{file}: {schema.VERSION_KEY}: expected an integer, got {tomlio.article(tomlio.type_name(version))}"
        )
    elif version > SCHEMA_VERSION:
        problems.append(
            f"{file}: {schema.VERSION_KEY}: {version} is newer than this tool reads ({SCHEMA_VERSION}); "
            "update the clone the tool runs from"
        )
        return False
    elif version < 1:
        problems.append(f"{file}: {schema.VERSION_KEY}: {version} is not a schema version; the first is 1")

    for key, value in data.items():
        if key not in _KEYS:
            problems.append(f"{file}: {tomlio.format_key(key)}: unknown key; known here: {', '.join(_KEYS)}")
        elif _KEYS[key] is not None:
            schema.check(_KEYS[key], value, (key,), file, problems)
    for key in _REQUIRED:
        if key not in data:
            problems.append(f"{file}: {key}: missing; a dictionary must have it")

    for key in ("checked_on_version", "oldest_supported_version"):
        value = data.get(key)
        if isinstance(value, str) and value.strip() and version_fault(value) is not None:
            problems.append(
                f"{file}: {key}: {tomlio.format_value(_shown(value))} is not a version ({version_fault(value)})"
            )
    date = data.get("checked_on_date")
    if isinstance(date, str) and date and not _is_date(date):
        problems.append(f"{file}: checked_on_date: {tomlio.format_value(date)} is not a date (YYYY-MM-DD)")

    for key, names in (("tiers", schema.TIERS), ("efforts", schema.EFFORTS)):
        if isinstance(data.get(key), dict):
            for name in names:
                if name not in data[key]:
                    problems.append(f"{file}: {key}.{name}: missing; a dictionary maps every one of {', '.join(names)}")

    listing = data.get("model_list")
    if isinstance(listing, dict):
        for key in ("command", "offline_command"):
            if listing.get(key) == []:
                problems.append(f"{file}: model_list.{key}: must not be empty; leave the key out where there is no command")
        if "offline_command" in listing and "command" not in listing:
            problems.append(f"{file}: model_list.offline_command: is given without model_list.command")

    models = data.get("models")
    if "models" in data and not isinstance(models, dict):
        problems.append(f"{file}: models: expected a table, got {tomlio.article(tomlio.type_name(models))}")
    elif isinstance(models, dict):
        if not models:
            problems.append(f"{file}: models: must list at least one model")
        for name, entry in models.items():
            path = ("models", name)
            if not name.strip():
                problems.append(f"{file}: {tomlio.dotted(path)}: a model name must not be empty")
            schema.check(_MODEL, entry, path, file, problems)
            if isinstance(entry, dict):
                for key in _MODEL_REQUIRED:
                    if key not in entry:
                        problems.append(
                            f"{file}: {tomlio.dotted(path + (key,))}: missing; write an empty array "
                            "for a model that takes no effort setting"
                        )
    return True


def _is_date(text: str) -> bool:
    if not _DATE.fullmatch(text):
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _check_agreement(data: dict[str, Any], file: Path, problems: list[str]) -> None:
    """What must hold between the keys of a file whose shape is right."""
    models: dict[str, Any] = data["models"]
    listed = ", ".join(models)
    for tier, model in data["tiers"].items():
        if model not in models:
            problems.append(
                f"{file}: tiers.{tier}: {tomlio.format_value(model)} is not a model this file lists "
                f"under models; listed: {listed}"
            )
    accepted = [value for entry in models.values() for value in entry["efforts"]]
    for effort, value in data["efforts"].items():
        if value not in accepted:
            problems.append(
                f"{file}: efforts.{effort}: no model this file lists accepts {tomlio.format_value(value)}; "
                f"accepted values: {', '.join(dict.fromkeys(accepted)) or 'none'}"
            )
    for name, entry in models.items():
        default = entry.get("default_effort")
        if default is not None and default not in entry["efforts"]:
            problems.append(
                f"{file}: {tomlio.dotted(('models', name, 'default_effort'))}: {tomlio.format_value(default)} "
                f"is not among the model's efforts: {', '.join(entry['efforts']) or 'none'}"
            )
    oldest = data.get("oldest_supported_version")
    if oldest is not None and parse_version(oldest) > parse_version(data["checked_on_version"]):
        problems.append(
            f"{file}: oldest_supported_version: {oldest} is newer than checked_on_version "
            f"({data['checked_on_version']})"
        )
