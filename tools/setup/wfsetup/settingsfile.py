"""The settings file a run of ``setup.py`` writes: the values given by flag.

The file is ~/.agents/workflow.toml, or with DIR DIR/.agents/workflow.toml.
``prepare`` works out what the file should hold, from the file as it is and
the flags of the run, and plans the write; ``Prepared.apply`` makes it. The
options are in ``add_arguments``; ``program`` prints them in its help.

What a run writes
    A user file holds the tier and effort mapping of each installed
    provider in full, as it was confirmed: a later version of the dictionaries
    does not change it, since a model changes cost and behaviour. Every other
    value is written where a flag stated it, and otherwise only where it
    differs from the layers below. A value given by flag is stated: it is
    written even when it equals what the layers below give. A value accepted
    as shown is not: when it equals what the layers below give, the key stays
    out and follows them. This holds for a project's file as for the user's,
    the provider mappings included.

    A value already in the file stays as it is unless a flag changes it.
    `--reset KEY` takes KEY out of the file, so that it follows the layer
    below again. The file written holds no old key.

A file that setup did not write in its present form (one written by hand, or
edited since: its content is not the one the install record holds) is not
rewritten by --yes alone, because --yes cannot have meant its comments and
layout: --rewrite-settings as well. The file is rewritten from its values;
the file as it was is copied to the backup directory first.

The model list
    A provider's mapping is checked against the provider's own list where one
    can be read (``modellist``). A mapped model the list does not hold is an
    error, unless --allow-unlisted keeps it; an effort value the model of a
    role does not accept is an error.
"""
from __future__ import annotations

import argparse
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import dictionary, fileops, fsio, homes, locations, modellist, profiles, roles, schema, settings
from . import tomlio
from .dictionary import Dictionary
from .errors import SetupError
from .modellist import Comparison, Reading

PROG = "setup.py"

USER = "user"
PROJECT = "project"
REWRITE_OPTION = "--rewrite-settings"

# The single-valued settings: key, flag, the name argparse gives it, type.
_SETTINGS = (
    ("process.docs_dir", "--docs-dir", "docs_dir", "string"),
    ("process.questions", "--questions", "questions", "string"),
    ("process.recommend", "--recommend", "recommend", "boolean"),
    ("roles.manager_default", "--manager-default", "manager_default", "boolean"),
    ("roles.high_stakes", "--high-stakes", "high_stakes", "boolean"),
    ("roles.max_parallel_coders", "--max-parallel-coders", "max_parallel_coders", "integer"),
    ("memory.dir", "--memory-dir", "memory_dir", "string"),
)
_TRUE = ("y", "yes", "true")
_FALSE = ("n", "no", "false")
_INTEGER = re.compile(r"[+-]?[0-9]{1,18}")

# The two mappings of a provider: the table's name, what a key is, what a
# value is, the keys, and the flag.
_MAPS = {
    "tiers": ("tier", "MODEL", schema.TIERS, "--tier"),
    "efforts": ("effort", "VALUE", schema.EFFORTS, "--effort"),
}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The options that give a value (R1.3), and ``--install``, ``--reset``
    and ``--rewrite-settings``. ``--allow-unlisted`` is the program's."""
    parser.add_argument(
        REWRITE_OPTION, action="store_true",
        help="with --yes: also rewrite a settings file that was written or edited by hand. The file is rewritten "
        "from its values: every key is kept, its comments and layout are not. The file as it was is copied to "
        "the backup directory first",
    )
    parser.add_argument(
        "--install", nargs="+", metavar="NAME",
        help="what is installed: the whole list, replacing the file's own (skills and rules of the clone by name, "
        f"and `{schema.ROLES_ITEM}`)",
    )
    parser.add_argument(
        "--reset", action="append", default=[], metavar="KEY",
        help="take KEY out of the file, so that it follows the layer below again; a setting, `install`, or a "
        "provider's tier, effort or role model (a tier or an effort is refused when writing the user's file). "
        "May be given several times",
    )
    parser.add_argument(
        "--tier", action="append", default=[], metavar="PROVIDER:TIER=MODEL",
        help=f"the model of a tier ({', '.join(schema.TIERS)}) on a provider; may be given several times",
    )
    parser.add_argument(
        "--effort", action="append", default=[], metavar="PROVIDER:NAME=VALUE",
        help=f"the provider's value for an effort name ({', '.join(schema.EFFORTS)}); may be given several times",
    )
    parser.add_argument(
        "--role-model", action="append", default=[], metavar="PROVIDER:ROLE=MODEL",
        help="a model for one role definition, whatever its tier; an empty MODEL takes the entry out; "
        "may be given several times",
    )
    parser.add_argument("--docs-dir", metavar="DIR", help="process.docs_dir: where the sprint docs live")
    parser.add_argument(
        "--questions", metavar="HOW", help=f"process.questions: {' or '.join(schema.QUESTIONS)}",
    )
    switch = argparse.BooleanOptionalAction
    parser.add_argument("--recommend", action=switch, help="process.recommend: a recommendation with each question")
    parser.add_argument(
        "--manager-default", action=switch,
        help="roles.manager_default: a session in the project starts as the Manager (with DIR only)",
    )
    parser.add_argument("--high-stakes", action=switch, help="roles.high_stakes: roles use their high-stakes tier")
    parser.add_argument(
        "--max-parallel-coders", metavar="N", help="roles.max_parallel_coders: how many Coders work at the same time",
    )
    parser.add_argument("--memory-dir", metavar="DIR", help="memory.dir: where the project memory lives")


# --- Asking -------------------------------------------------------------------

class _Dialogue:
    def __init__(self, yes: bool, interactive: bool) -> None:
        self.yes = yes
        self.interactive = interactive and not yes

    def ask(self, prompt: str) -> str:
        try:
            return input(prompt).strip()
        except EOFError:
            raise SetupError("standard input ended before every question was answered") from None

    def unanswered(self, what: str, flags: str) -> SetupError:
        return SetupError(
            f"{what}: not answered. Standard input is not a terminal, so nothing is asked, and --yes "
            f"was not given. Give {flags}, or --yes to accept what is proposed"
        )


def _check(key: str, value: Any, source: str) -> None:
    """Check one value through the settings schema; ``source`` is named
    where a settings file would be."""
    group, *rest = key.split(".")
    content = value
    for part in reversed(rest):
        content = {part: content}
    problems: list[str] = []
    schema.validate(group, content, source, problems)
    if problems:
        raise SetupError(*problems)


def _typed(kind: str, text: str) -> Any:
    """An answer typed as text, as the value it says. What is not one is
    left as text, for the schema to refuse in its own words."""
    if kind == "boolean":
        if text.lower() in _TRUE:
            return True
        if text.lower() in _FALSE:
            return False
    if kind == "integer" and _INTEGER.fullmatch(text.strip()):
        return int(text.strip())
    return text


def _mapping_flags(values: list[str], flag: str, shape: str) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for text in values:
        head, equals, value = text.partition("=")
        provider, colon, name = head.partition(":")
        if not (equals and colon and provider and name):
            raise SetupError(f"{flag} {text}: expected {shape}")
        if found.setdefault((provider, name), value) != value:
            raise SetupError(f"{flag}: {provider}:{name} is given twice, with different values")
    return found


# --- One provider -------------------------------------------------------------

@dataclass
class _Provider:
    name: str
    known: Dictionary
    reading: Reading
    comparison: Comparison | None
    checked: Dictionary                       # the dictionary as the list corrects it
    maps: dict[str, dict[str, str]]           # "tiers" and "efforts", as they will be
    given: dict[str, set[str]]                # the keys of each that a flag answered
    stated: dict[str, set[str]]               # the keys of each that a flag or the prompt answered
    notes: dict[str, str] = field(default_factory=dict)
    unset: dict[str, set[str]] = field(default_factory=lambda: {table: set() for table in _MAPS})   # taken out

    def choices(self) -> list[str]:
        """The models offered: the list's where there is one, else the
        dictionary's, hidden entries left out."""
        if self.reading.has_list:
            return [
                name + ("" if name in self.known.models else " (new: not in the dictionary)")
                for name in self.reading.offered()
            ]
        return [name for name, model in self.known.models.items() if model.visibility in (None, modellist.LISTED)]

    def model_fault(self, key: str, model: str, flag: str, allow_unlisted: bool) -> str | None:
        """Why ``model`` cannot stay at ``key``, or None. What is worth
        saying about a model that stays goes to ``notes``."""
        shown = tomlio.format_value(model)
        self.notes.pop(key, None)
        if not self.reading.has_list:
            if self.known.model(model) is None:
                self.notes[key] = (
                    f"{key}: {shown} is not in the {self.name} dictionary, and no list was read; "
                    "nothing is known about the efforts it accepts"
                )
            return None
        entry = self.reading.model(model)
        if entry is None:
            if allow_unlisted:
                self.notes[key] = f"{key}: {shown} is not in {self.name}'s own list; kept, as --allow-unlisted says"
                return None
            return (
                f"{key}: the model {shown} is not in {self.name}'s own list and must be replaced: give "
                f"{flag} (listed: {', '.join(self.reading.offered()) or 'none'}), or --allow-unlisted to keep it"
            )
        if not entry.offered:
            self.notes[key] = (
                f"{key}: {shown} is a hidden entry of {self.name}'s list (visibility "
                f"{tomlio.format_value(entry.visibility)}); it is not offered, and stays because it is named"
            )
        return None

    def faults(self, table: str, allow_unlisted: bool) -> list[str]:
        problems: list[str] = []
        if table == "tiers":
            for tier, model in self.maps["tiers"].items():
                fault = self.model_fault(
                    f"providers.{self.name}.tiers.{tier}", model, f"--tier {self.name}:{tier}=MODEL", allow_unlisted
                )
                if fault is not None:
                    problems.append(fault)
            return problems
        accepted = list(dict.fromkeys(value for model in self.checked.models.values() for value in model.efforts))
        for name, value in self.maps["efforts"].items():
            if value not in accepted:
                problems.append(
                    f"providers.{self.name}.efforts.{name}: no model of {self.name} accepts "
                    f"{tomlio.format_value(value)}; accepted values: {', '.join(accepted) or 'none'}"
                )
        return problems

    def table(self, role_models: dict[str, str]) -> list[str]:
        rows = [("tier", "model", "efforts the model accepts")]
        for tier, model in self.maps["tiers"].items():
            rows.append((tier, model, self._efforts(model)))
        for role, model in role_models.items():
            rows.append((f"role {role}", model, self._efforts(model)))
        widths = [max(len(row[column]) for row in rows) for column in (0, 1)]
        lines = [f"  {row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]}" for row in rows]
        mapped = ", ".join(f"{name} = {value}" for name, value in self.maps["efforts"].items())
        lines.append(f"  effort names: {mapped}")
        return lines

    def _efforts(self, model: str) -> str:
        entry = self.checked.model(model)
        if entry is None:
            return "unknown: the model is not listed"
        return ", ".join(entry.efforts) if entry.takes_effort else "none: the model takes no effort setting"


def _settle_map(dialogue: _Dialogue, state: _Provider, table: str, allow_unlisted: bool) -> None:
    """Bring one mapping of a provider to its final values, or raise."""
    word, meta, names, flag = _MAPS[table]
    values, given = state.maps[table], state.given[table]
    while True:
        problems = state.faults(table, allow_unlisted)
        if dialogue.yes or all(name in given for name in names):
            if problems:
                raise SetupError(*problems)
            return
        if not dialogue.interactive:
            flags = ", ".join(f"{flag} {state.name}:{name}={meta}" for name in names if name not in given)
            raise dialogue.unanswered(f"{state.name}: the {word} mapping", flags)
        print(f"{state.name} {table}: " + "  ".join(f"{name}={values[name]}" for name in names))
        if table == "tiers":
            print(f"  models: {', '.join(state.choices()) or 'none listed'}")
        for line in problems:
            print(f"  {line}")
        answer = dialogue.ask(f"  change, as {word}={meta} ..., or nothing to accept ({flag} {state.name}:...): ")
        if not answer:
            if not problems:
                return
            continue
        try:
            changed: dict[str, str] = {}
            for item in answer.split():
                name, equals, value = item.partition("=")
                if not equals or not name:
                    raise SetupError(f"{item}: expected {word}={meta}")
                _check(f"providers.{state.name}.{table}.{name}", value, "answer")
                changed[name] = value
        except SetupError as exc:
            for line in exc.lines:
                print(f"  {line}")
            continue
        values.update(changed)
        state.stated[table].update(changed)
        state.unset[table].difference_update(changed)
        if not state.faults(table, allow_unlisted):
            return


def _settle_setting(dialogue: _Dialogue, key: str, flag: str, kind: str, proposed: Any) -> tuple[Any, bool]:
    """The value, and whether it was typed: Enter and --yes accept a proposal, which is not an answer."""
    if dialogue.yes:
        return proposed, False
    hint = f"{flag} or --no-{flag[2:]}" if kind == "boolean" else flag
    if not dialogue.interactive:
        raise dialogue.unanswered(key, hint)
    while True:
        answer = dialogue.ask(f"{key} [{tomlio.format_value(proposed)}] ({hint}): ")
        if not answer:
            return proposed, False
        value = _typed(kind, answer)
        try:
            _check(key, value, "answer")
        except SetupError as exc:
            for line in exc.lines:
                print(f"  {line}")
            continue
        return value, True



# --- The file -----------------------------------------------------------------

def _header(scope: str) -> list[str]:
    if scope == USER:
        what = "the user layer (~/.agents/workflow.toml)"
        written = [
            "The tiers and efforts of each installed provider are written in full: they",
            "are the mapping confirmed by a run of setup, and an update of the clone does",
            "not change them. Every other key is here where a flag stated it or it differs",
            "from the layers below; a key that is not here has the value of the layer below.",
        ]
    else:
        what = "the project layer (.agents/workflow.toml in the project)"
        written = [
            "A key is here where a flag stated it or it differs from the layers below;",
            "a key that is not here has the value of the layer below, which for the",
            "provider mappings is each user's own file.",
        ]
    return [
        f"Workflow settings: {what}.",
        f"Written by `{PROG}`. `install` lists what is installed, by name.",
        "",
        "Layers, later wins: the shipped defaults (tools/setup/defaults.toml and",
        "providers/<name>/dictionary.toml in the clone), ~/.agents/workflow.toml,",
        "<project>/.agents/workflow.toml, <project>/.agents/workflow.local.toml.",
        *written,
        "",
        f"To change a value, run `{PROG}` again with a flag (`{PROG} --help` lists",
        "them), or edit this file. Setup rewrites the file from its values: every key",
        "is kept, comments and layout are not.",
    ]


def _flat(data: dict[str, Any]) -> dict[str, Any]:
    flat = {
        key: value
        for group in schema.GROUPS if group in data
        for key, value in schema.flatten(schema.strip_old_keys(group, data[group]), (group,))
    }
    if schema.INSTALL_KEY in data:     # a key of the file itself, above every table: kept as it is
        flat[schema.INSTALL_KEY] = data[schema.INSTALL_KEY]
    return flat


def _nest(flat: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {schema.VERSION_KEY: schema.SCHEMA_VERSION}
    for key in sorted(flat, key=schema.order):
        *tables, last = key.split(".")
        table = data
        for part in tables:
            table = table.setdefault(part, {})
        table[last] = flat[key]
    return data


def _document(flat: dict[str, Any], scope: str) -> str:
    return tomlio.dumps(_nest(flat), header=_header(scope))


def _changes(old: dict[str, Any], new: dict[str, Any], below: dict[str, settings.Entry]) -> list[str]:
    show = tomlio.format_value
    lines: list[str] = []
    for key in sorted(set(old) | set(new), key=schema.order):
        if key in old and key in new:
            if old[key] != new[key] or type(old[key]) is not type(new[key]):
                lines.append(f"  {key}: {show(old[key])} -> {show(new[key])}")
        elif key in new:
            was = f"not set; {show(below[key].value)} from the {below[key].layer} layer" if key in below else "not set"
            lines.append(f"  {key}: ({was}) -> {show(new[key])}")
        else:
            now = f"{show(below[key].value)} from the {below[key].layer} layer" if key in below else "nothing"
            lines.append(f"  {key}: {show(old[key])} -> (taken out; the value is then {now})")
    return lines


# --- The run ------------------------------------------------------------------

@dataclass
class Prepared:
    """What the run does about the settings file: ``lines`` tell it. Nothing
    is written until ``apply``."""

    target: Path
    lines: list[str]
    changed: bool                    # the file is written
    data: dict[str, Any] | None      # what the file would hold, as it is read (None: it is not written)
    _plan: fileops.Plan | None = None
    _roots: Any = None
    _replaces: bool = False
    _project: bool = False

    def apply(self) -> list[str]:
        """Write the file; the lines to tell."""
        if not self.changed or self._plan is None:
            return []
        self._plan.apply()
        lines = [f"written: {self.target}"]
        if self._replaces:
            lines.append(f"the file as it was is in {self._roots.backups_dir_of(self._project) / self._plan.stamp}")
        return lines


def prepare(where: locations.Locations, found: homes.Homes, args: argparse.Namespace, *, dry_run: bool) -> Prepared:
    """Work out the settings file of this run, from the file as it is and the
    flags, and plan its write. Nothing is asked: a value no flag states is
    accepted as shown. The providers are those of ``found`` that are installed
    and have a dictionary. A fault in a flag, or in the model list, is a
    ``SetupError`` and nothing is written."""
    scope = PROJECT if where.project is not None else USER
    target: Path = where.project_file if scope == PROJECT else where.user_file  # type: ignore[assignment]
    below_layers = ("shipped",) if scope == USER else ("shipped", USER)
    dictionaries = dictionary.load_all(where)
    lines: list[str] = []
    say = lines.append

    if args.manager_default is not None and scope == USER:
        raise SetupError("--manager-default is about a project's sessions: give it with DIR")

    # The file as it is must be one this tool reads: it is the base of
    # what is written.
    try:
        settings.resolve(where, layers=(*below_layers, scope))
    except SetupError as exc:
        raise SetupError(*exc.lines, "setup changes nothing while a settings file has a fault; correct the file first") from None
    below = settings.resolve(where, layers=below_layers)
    current = [document for document in settings.documents(where) if document.layer == scope]
    existing = _flat(current[0].data) if current else None
    flat: dict[str, Any] = dict(existing or {})

    def proposed(key: str) -> Any:
        return flat[key] if key in flat else below[key].value

    def place(key: str, value: Any, pin: bool = False, stated: bool = False) -> None:
        """Set, keep or take out one key; see "What a run writes". A stated
        value (a flag) is written whatever the layers below give."""
        if pin or stated or (key in flat and _same(flat[key], value)):
            flat[key] = value
        elif key in below and _same(below[key].value, value):
            flat.pop(key, None)
        else:
            flat[key] = value

    dialogue = _Dialogue(True, False)
    layer = "the user layer" if scope == USER else "the project layer"
    say(f"settings file: {target} ({layer}; {'it exists' if existing is not None else 'not there yet'})")

    # --- Which providers ------------------------------------------------------
    configured = []
    for provider in found.providers:
        if not provider.installed:
            continue
        if provider.name not in dictionaries:
            say(f"{provider.name}: installed, but this clone has no dictionary for it; left out")
        else:
            configured.append(provider)
    names = [provider.name for provider in configured]

    # --- The flags ------------------------------------------------------------
    flags = {
        "tiers": _mapping_flags(args.tier, "--tier", "PROVIDER:TIER=MODEL, such as codex:deep=gpt-6-astra"),
        "efforts": _mapping_flags(args.effort, "--effort", "PROVIDER:NAME=VALUE, such as codex:max=ultra"),
        "role_models": _mapping_flags(
            args.role_model, "--role-model", "PROVIDER:ROLE=MODEL, such as codex:coder-hard=gpt-6-astra"
        ),
    }
    for table, flag in (("tiers", "--tier"), ("efforts", "--effort"), ("role_models", "--role-model")):
        for (provider_name, name), value in flags[table].items():
            source = f"{flag} {provider_name}:{name}={value}"
            if provider_name not in names:
                raise SetupError(
                    f"{source}: {provider_name} is not a provider this run sets up; installed here, "
                    f"with a dictionary: {', '.join(names) or 'none'}"
                )
            if table != "role_models" or value:
                _check(f"providers.{provider_name}.{table}.{name}", value, source)
    answers: dict[str, Any] = {}
    for key, flag, attribute, kind in _SETTINGS:
        value = getattr(args, attribute)
        if value is not None:
            if isinstance(value, str) and kind == "string" and locations.control_character(value):
                raise SetupError(f"{flag}: the value holds a control character or a line break")
            answers[key] = _typed(kind, value) if isinstance(value, str) else value
            _check(key, answers[key], flag)
    if args.install is not None:
        problems: list[str] = []
        schema.check_install({schema.INSTALL_KEY: list(args.install)}, "--install", problems)
        if problems:
            raise SetupError(*problems)
        answers[schema.INSTALL_KEY] = list(args.install)

    # --- What is taken out ----------------------------------------------------
    unset: set[str] = set()
    settings_keys = {key for key, _, _, _ in _SETTINGS} | {schema.INSTALL_KEY}
    for text in args.reset:
        key = text if text == schema.INSTALL_KEY else ".".join(schema.parse_key(text))
        parts = key.split(".")
        mapped = len(parts) == 4 and parts[0] == "providers" and parts[2] in (*_MAPS, "role_models")
        if mapped and parts[2] in _MAPS and parts[3] not in _MAPS[parts[2]][2]:
            mapped = False
        # A key setup writes, or any other key of the file itself (process.density, a role's override).
        if not (key in settings_keys or mapped or key in flat):
            raise SetupError(
                f"--reset {text}: not a key setup writes or the file holds; those setup writes are "
                f"{', '.join(sorted(settings_keys))}, and providers.<provider>.tiers.<tier>, "
                ".efforts.<effort> and .role_models.<role>"
            )
        if mapped and parts[1] not in names:
            raise SetupError(
                f"--reset {text}: {parts[1]} is not a provider this run sets up; installed here, "
                f"with a dictionary: {', '.join(names) or 'none'}"
            )
        if mapped and parts[2] == "role_models" and key not in flat:
            ids = [definition.id for definition in roles.definitions(where)]
            if parts[3] not in ids:
                raise SetupError(
                    f"--reset {text}: no role definition has the id {parts[3]}; definitions: {', '.join(ids) or 'none'}"
                )
        if mapped and scope == USER and parts[2] in _MAPS:
            raise SetupError(
                f"--reset {text}: the user's file holds the {parts[2]} mapping in full, so a key of it is not taken "
                "out; give --tier or --effort to change one"
            )
        if key in answers or (mapped and (parts[1], parts[3]) in flags[parts[2]]):
            raise SetupError(f"--reset {text}: a flag answers the same key; give one of them")
        if key in unset:
            continue
        unset.add(key)
        if key not in flat:
            say(f"--reset {text}: {target} does not hold it; nothing to take out")

    # --- The mappings ---------------------------------------------------------
    states: list[_Provider] = []
    for provider in configured:
        known = dictionaries[provider.name]
        reading = modellist.read(known, homes.child_environment(found), program_file=provider.program_file)
        state = _Provider(
            name=provider.name, known=known, reading=reading,
            comparison=modellist.compare(known, reading, {}),
            checked=modellist.effective(known, reading),
            maps={
                table: {name: proposed(f"providers.{provider.name}.{table}.{name}") for name in _MAPS[table][2]}
                for table in _MAPS
            },
            given={table: set() for table in _MAPS},
            stated={table: set() for table in _MAPS},
        )
        for table in _MAPS:
            for (provider_name, name), value in flags[table].items():
                if provider_name == provider.name:
                    state.maps[table][name] = value
                    state.given[table].add(name)
                    state.stated[table].add(name)
        for table in _MAPS:
            for name in _MAPS[table][2]:
                key = f"providers.{state.name}.{table}.{name}"
                if key in unset:
                    state.maps[table][name] = below[key].value
                    state.given[table].add(name)
                    state.unset[table].add(name)
        say(f"{state.name}: {reading.describe()}")
        if state.comparison is not None:
            for line in state.comparison.lines():
                say(f"  {line}")
        for table in _MAPS:
            _settle_map(dialogue, state, table, args.allow_unlisted)
        states.append(state)

    for state in states:
        for table in _MAPS:
            for name, value in state.maps[table].items():
                if name in state.unset[table]:
                    flat.pop(f"providers.{state.name}.{table}.{name}", None)
                    continue
                place(
                    f"providers.{state.name}.{table}.{name}", value,
                    pin=scope == USER, stated=name in state.stated[table],
                )
        for (provider_name, role), model in flags["role_models"].items():
            if provider_name != state.name:
                continue
            key = f"providers.{state.name}.role_models.{role}"
            if not model:
                flat.pop(key, None)
                continue
            fault = state.model_fault(key, model, f"--role-model {state.name}:{role}=MODEL", args.allow_unlisted)
            if fault is not None:
                raise SetupError(fault)
            place(key, model, stated=True)

    # --- The other settings ---------------------------------------------------
    for key in unset:
        if not key.startswith("providers.") or key.split(".")[2:3] == ["role_models"]:
            flat.pop(key, None)
    if schema.INSTALL_KEY in answers:
        flat[schema.INSTALL_KEY] = answers[schema.INSTALL_KEY]
    elif schema.INSTALL_KEY in unset:
        flat.pop(schema.INSTALL_KEY, None)
    for key, flag, _, kind in _SETTINGS:
        if key in answers:
            place(key, answers[key], stated=True)
            continue
        if key in unset:
            flat.pop(key, None)
            continue
        value, typed = _settle_setting(dialogue, key, flag, kind, proposed(key))
        place(key, value, stated=typed)

    # --- What the roles would run with ----------------------------------------
    entries = {key: entry for key, entry in below.items() if key.split(".")[0] in profiles.GROUPS}
    entries.update({
        key: settings.Entry(value, scope, target)
        for key, value in flat.items() if key.split(".")[0] in profiles.GROUPS
    })
    definitions = roles.definitions(where)
    problems = []
    for definition in definitions:
        for state in states:
            try:
                profiles.resolve_definition(definition, state.checked, entries)
            except SetupError as exc:
                problems.extend(line for line in exc.lines if line not in problems)
    if problems:
        raise SetupError(*problems)

    # --- Show -----------------------------------------------------------------
    for state in states:
        role_models = {
            key.rsplit(".", 1)[1]: entry.value
            for key, entry in entries.items() if key.startswith(f"providers.{state.name}.role_models.")
        }
        say("")
        say(f"{state.name}: the mapping")
        for line in state.table(role_models):
            say(line)
        for note in state.notes.values():
            say(f"  note: {note}")
    for note in profiles.unmatched([definition.id for definition in definitions], sorted(dictionaries), entries):
        say(f"note: {note}")
    say("")
    say("settings:")
    for key, _, _, _ in _SETTINGS:
        if key in flat:
            say(f"  {key} = {tomlio.format_value(flat[key])}  (in this file)")
        else:
            say(f"  {key} = {tomlio.format_value(below[key].value)}  ({below[key].layer}; not written)")
    if schema.INSTALL_KEY in flat:
        say(f"  {schema.INSTALL_KEY} = {tomlio.format_value(flat[schema.INSTALL_KEY])}  (in this file)")
    say("")

    # --- Plan -----------------------------------------------------------------
    write = existing is None or not _same_values(flat, existing)
    roots = found.roots()
    plan = fileops.Plan(roots, follow_config_symlinks=args.follow_config_symlinks)
    text = _document(flat, scope)
    if write:
        plan.write_file(target, text, replace=fileops.ANY)
    described = plan.describe()
    if not described.changed:
        say(f"nothing to write: {target} already holds these settings")
        return Prepared(target, lines, False, None)

    replaces = write and existing is not None
    if replaces:
        say(f"changes to {target}:")
        for line in _changes(existing or {}, flat, below):
            say(line)
        was = _read_text(target)
        if was is not None and was != _document(existing or {}, scope):
            say("  the file was edited outside setup: its keys are kept, its comments and layout are not")
    elif write:
        say(f"{target}, as it {'would be' if dry_run else 'will be'} written:")
        for line in text.splitlines():
            say(f"    {line}".rstrip())
    for line in described.lines:
        say(line)
    for note in described.notes:
        say(f"note: {note}")
    # A file setup did not write in its present form: ``--yes`` alone does
    # not confirm that its comments and layout go.
    by_hand = replaces and not _written_by_setup(roots, target)
    if dry_run:
        if by_hand:
            say(f"note: {target} was written or edited by hand; a run that writes it needs --yes {REWRITE_OPTION}")
    elif by_hand and not args.rewrite_settings:
        raise SetupError(
            f"{target}: was written or edited by hand (its content is not what setup wrote), and these flags "
            "change it. Setup rewrites the file from its values: every key is kept, its comments and layout are "
            f"not, and --yes alone does not confirm that. Give {REWRITE_OPTION} with --yes to rewrite it; the file "
            f"as it is now is then copied to {roots.backups_dir_of(scope == PROJECT)} first, under the time of the "
            "run. `uninstall` puts back a file that was there before the first run, and leaves in place, as "
            "yours, one that setup rewrote after you edited it. Nothing was written"
        )
    return Prepared(
        target, lines, True, tomllib.loads(text), plan, roots, replaces, scope == PROJECT,
    )


def _same(one: Any, other: Any) -> bool:
    """Equal as TOML values: ``True`` is not ``1``."""
    return type(one) is type(other) and one == other


def _same_values(one: dict[str, Any], other: dict[str, Any]) -> bool:
    return one.keys() == other.keys() and all(_same(one[key], other[key]) for key in one)


def _written_by_setup(roots: Any, target: Path) -> bool:
    """Whether the file at ``target`` holds exactly what setup wrote there
    last: the install record lists it as a file of setup's, with the hash
    of its present content."""
    try:
        key = roots.key(target)
        entry = fileops.read_record(roots).get(key) if key is not None else None
        if entry is None or entry.get("kind") != "file" or fsio.look(target).kind != fsio.FILE:
            return False
        return entry.get("sha256") == fsio.sha256(fsio.read_bytes(target))
    except SetupError:
        return False


def _read_text(file: Path) -> str | None:
    try:
        return file.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
