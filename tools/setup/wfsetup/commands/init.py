"""Write a settings file for the providers installed here.

    init [--user | --project DIR] [--home DIR] [--yes [--rewrite-settings]]
         [--dry-run] [--follow-config-symlinks] [answers]

Which file
    --user (the default when neither is given) writes ~/.agents/workflow.toml,
    the user layer. --project DIR writes DIR/.agents/workflow.toml, the
    project layer, and puts .agents/workflow.local.toml into the project's
    ignore block. Giving both is an error.

What is asked
    For each installed provider (its program is on PATH, or its home
    exists) that has a dictionary: which model each tier means, and which
    of the provider's values each effort name means. Then the process,
    roles and memory settings. Every question has a flag, and a flag's
    answer is not asked again:

        --tier PROVIDER:TIER=MODEL        --tier codex:deep=gpt-6-astra
        --effort PROVIDER:NAME=VALUE      --effort codex:max=ultra
        --role-model PROVIDER:ROLE=MODEL  --role-model codex:coder-hard=gpt-6-astra
                                          (an empty MODEL takes the entry out;
                                          never asked, only set by this flag)
        --docs-dir DIR                    process.docs_dir
        --questions HOW                   process.questions
        --recommend / --no-recommend      process.recommend
        --roles / --no-roles              roles.enabled
        --manager-default / --no-...      roles.manager_default
        --high-stakes / --no-...          roles.high_stakes
        --max-parallel-coders N           roles.max_parallel_coders
        --memory-dir DIR                  memory.dir
        --allow-unshared-clone / --no-... setup.allow_unshared_clone
                                          (the user's file only)

    The first three may be given several times. Each answer is checked by
    the settings schema, with the schema's own message.

    roles.enabled = false is the process alone on every `render`, which
    `render --no-roles` is for one run; a project's file may set it for that
    project. setup.allow_unshared_clone = true lets `render` and `doctor`
    accept, on every run, a clone that only this side of the machine can
    read, which `--allow-unshared-clone` does for one run: only where the
    other side does not install from this clone (one side used alone, or a
    clone for each side). It is read from the user's file alone, so it is
    never asked, and its flag is refused, with --project. Its question is
    asked only where it applies: the machine has a Windows side and a WSL
    side and this side's clone is one the other cannot read. Its proposal is
    then the value in effect, false (a shared clone required) unless the
    file already says otherwise. Elsewhere it is not asked, a value the file
    holds stays, and the flag still sets it.

    A script that answers every question by flag, without --yes, now gives
    --roles or --no-roles too, and, on a clone the other side cannot read,
    --allow-unshared-clone or --no-allow-unshared-clone.

    What is proposed for a question is the value in effect now: the one in
    the file being written if it has one, else the one the layers below
    give (the shipped defaults and the provider dictionaries; for a project
    file, the user's file too). --yes accepts every proposal no flag
    answers, and confirms the write. Questions are asked on a terminal
    only: when standard input is not one and --yes is not given, a question
    without a flag is an error that names the flag. Nothing waits for input
    that cannot come.

The model list
    A provider's mapping is checked against the provider's own list where
    one can be read without starting a session. For Codex that is
    `codex debug models`, and `codex debug models --bundled` when the first
    fails; the command sends no model request. Claude Code has no such
    command, so its dictionary alone is used, and the output says so; the
    same holds when a list cannot be read. What an account can actually use
    may differ from both. The command is started with --dry-run as well. It
    is a program of the provider's, and may write state of its own into the
    provider's home; with --home DIR that home is DIR/.codex, never the real
    one.

      - A mapped model that the list does not hold must be replaced: with a
        --tier flag, or at the prompt. --yes alone is then an error, not a
        silent choice. --allow-unlisted keeps such a model, by name.
      - A model the list offers and the dictionary does not know is named,
        and can be chosen.
      - A hidden entry of the list is not offered.
      - An effort value that the model of a role does not accept is an
        error. What a model accepts is read from the list where there is
        one, else from the dictionary.

    The final mapping is shown as a table (tier, model, the efforts the
    model accepts) before anything is written.

What is written
    A user file holds the tier and effort mapping of each installed
    provider in full. They are what was confirmed, and they stay that even
    when a later version of the dictionaries proposes other models: a
    model changes cost and behaviour, so it changes when `init` is run
    again and not with an update of the clone. Every other value is
    written only where it differs from the layers below; a setting left at
    its shipped default keeps following the shipped default. A project file
    holds differences only, the mappings included: it is shared, and what
    it does not set is each user's own.

    A value already in the file stays as it is unless an answer changes
    it. An answer equal to what the layers below give takes the key out.

Running it again
    The same answers write nothing, and the output says so. Other answers
    show each changed key with its old and new value and, once confirmed,
    replace the file; the file as it was is copied to the backup directory
    first (~/.agents/workflow-setup/backups/<time of the run>/, or for a
    project's file DIR/.agents/workflow-setup/backups/<time of the run>/; a
    full copy, readable by you alone). The file is rewritten from its
    values: every key it holds is kept, also those `init` asks nothing
    about ([roles.<id>] overrides, the section of a provider that is not
    installed), but its comments and layout are not. A file whose values do
    not change is not touched, so comments in it stay.

    A file that `init` did not write in its present form (one written by
    hand, or edited since `init` wrote it: its content is not the one the
    install record holds) is not rewritten on --yes alone, because --yes
    cannot have meant its comments and layout. Such a rewrite needs
    --rewrite-settings as well; without it the run stops before anything is
    written and says so. At a terminal the confirmation asks instead.

What `uninstall` does with the file
    No value you set is removed. `uninstall` removes the file only when
    `init` created it and it holds exactly what `init` wrote from its own
    answers; it puts back, byte for byte, a file that was there before the
    first `init`, when nothing but `init` has written the file since. Once
    you edit the file, or `init` rewrites a version you had edited (the
    rewrite above), it holds values you set: `uninstall` then leaves it as
    it is, and it is yours. The backup copies go with the install record
    when `uninstall` finishes.

--dry-run prints what would be written and writes nothing of setup's; it
asks the same questions and leaves out the confirmation. Everything goes
through setup's file operations, so `uninstall` can take it back: the whole
plan is checked before the first write, and a plan that is refused writes
nothing. One run writes to a home at a time, and one to a project: a second
one ends at once with exit code 2 and names the run that holds the lock.

Exit code 0 when the file was written, was already as asked, or on a dry
run; 1 when the write was declined at the prompt; 2 on an error, which is
printed to stderr; 130 when interrupted with Ctrl-C, and 128 plus the
signal's number when told to end by a signal; 141 when the reader of the
output went away.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import commands, dictionary, fileops, fsio, homes, locations, modellist, profiles, roles, schema, settings
from .. import tomlio
from ..dictionary import Dictionary
from ..errors import SetupError
from ..modellist import Comparison, Reading

SUMMARY = "write a settings file for the installed providers (asks, or takes flags)"
PROG = "workflow_setup.py"
EXIT_DECLINED = 1

USER = "user"
PROJECT = "project"
REWRITE_OPTION = "--rewrite-settings"

# The single-valued settings: key, flag, the name argparse gives it, type.
_SETTINGS = (
    ("process.docs_dir", "--docs-dir", "docs_dir", "string"),
    ("process.questions", "--questions", "questions", "string"),
    ("process.recommend", "--recommend", "recommend", "boolean"),
    ("roles.enabled", "--roles", "roles", "boolean"),
    ("roles.manager_default", "--manager-default", "manager_default", "boolean"),
    ("roles.high_stakes", "--high-stakes", "high_stakes", "boolean"),
    ("roles.max_parallel_coders", "--max-parallel-coders", "max_parallel_coders", "integer"),
    ("memory.dir", "--memory-dir", "memory_dir", "string"),
    (homes.UNSHARED_KEY, homes.UNSHARED_OPTION, "allow_unshared_clone", "boolean"),
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


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--user", action="store_true",
        help="write the user's file, ~/.agents/workflow.toml. The default; not to be given with --project",
    )
    locations.add_arguments(parser)
    parser.add_argument(
        "--yes", action="store_true",
        help="accept every proposal that no flag answers, and confirm the write, without asking. It does not "
        f"confirm the rewrite of a settings file that `init` did not write: that takes {REWRITE_OPTION} as well",
    )
    parser.add_argument(
        REWRITE_OPTION, action="store_true",
        help="with --yes: also rewrite a settings file that was written or edited by hand. The file is rewritten "
        "from its values: every key is kept, its comments and layout are not. The file as it was is copied to "
        "the backup directory first",
    )
    fileops.add_arguments(parser)
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
    parser.add_argument(
        "--allow-unlisted", action="store_true",
        help="keep a mapped model that the provider's own list does not hold, instead of refusing it",
    )
    parser.add_argument("--docs-dir", metavar="DIR", help="process.docs_dir: where the sprint docs live")
    parser.add_argument(
        "--questions", metavar="HOW", help=f"process.questions: {' or '.join(schema.QUESTIONS)}",
    )
    switch = argparse.BooleanOptionalAction
    parser.add_argument("--recommend", action=switch, help="process.recommend: a recommendation with each question")
    parser.add_argument(
        "--roles", action=switch,
        help="roles.enabled: render generates the role definitions and the entry points; --no-roles installs "
        "the process alone on every render, as `render --no-roles` does for one run",
    )
    parser.add_argument(
        "--manager-default", action=switch, help="roles.manager_default: a session in the project starts as the Manager",
    )
    parser.add_argument("--high-stakes", action=switch, help="roles.high_stakes: roles use their high-stakes tier")
    parser.add_argument(
        "--max-parallel-coders", metavar="N", help="roles.max_parallel_coders: how many Coders work at the same time",
    )
    parser.add_argument("--memory-dir", metavar="DIR", help="memory.dir: where the project memory lives")
    parser.add_argument(
        homes.UNSHARED_OPTION, action=switch,
        help=f"{homes.UNSHARED_KEY}: render and doctor accept, on every run, a clone that only this side of the "
        "machine can read; only where the other side does not install from this clone (one side used alone, or a "
        "clone for each side). The user's file only; asked only where the clone is such a clone",
    )


# --- Asking -------------------------------------------------------------------

def _terminal() -> bool:
    """Whether a question can be asked: standard input is a terminal.

    On Windows ``isatty`` is true of every character device, the null
    device included, so the console is asked whether the handle is its own.
    """
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
        if os.name != "nt":
            return True
        import ctypes
        import msvcrt

        mode = ctypes.c_uint32()
        handle = ctypes.c_void_p(msvcrt.get_osfhandle(sys.stdin.fileno()))
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except (OSError, ValueError, AttributeError):
        return False


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
    notes: dict[str, str] = field(default_factory=dict)

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
        if not state.faults(table, allow_unlisted):
            return


def _settle_setting(dialogue: _Dialogue, key: str, flag: str, kind: str, proposed: Any) -> Any:
    if dialogue.yes:
        return proposed
    hint = f"{flag} or --no-{flag[2:]}" if kind == "boolean" else flag
    if not dialogue.interactive:
        raise dialogue.unanswered(key, hint)
    while True:
        answer = dialogue.ask(f"{key} [{tomlio.format_value(proposed)}] ({hint}): ")
        if not answer:
            return proposed
        value = _typed(kind, answer)
        try:
            _check(key, value, "answer")
        except SetupError as exc:
            for line in exc.lines:
                print(f"  {line}")
            continue
        return value


# --- The file -----------------------------------------------------------------

def _header(scope: str) -> list[str]:
    if scope == USER:
        what = "the user layer (~/.agents/workflow.toml)"
        written = [
            "The tiers and efforts of each installed provider are written in full: they",
            "are the mapping confirmed at `init`, and an update of the clone does not",
            "change them. Every other key is here only where it differs from the layers",
            "below; a key that is not here has the value of the layer below.",
        ]
    else:
        what = "the project layer (.agents/workflow.toml in the project)"
        written = [
            "Only what this project sets differently is here; a key that is not here",
            "has the value of the layer below, which for the provider mappings is each",
            "user's own file.",
        ]
    return [
        f"Workflow settings: {what}.",
        f"Written by `{PROG} init`.",
        "",
        "Layers, later wins: the shipped defaults (tools/setup/defaults.toml and",
        "providers/<name>/dictionary.toml in the clone), ~/.agents/workflow.toml,",
        "<project>/.agents/workflow.toml, <project>/.agents/workflow.local.toml.",
        *written,
        "",
        "To change a value, run `init` again with a flag (`init --help` lists them),",
        "or edit this file. `init` rewrites the file from its values: every key is",
        "kept, comments and layout are not. `show` prints each effective value and",
        "the layer it came from.",
    ]


def _flat(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for group in schema.GROUPS if group in data
        for key, value in schema.flatten(data[group], (group,))
    }


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


def _next_steps() -> str:
    known = commands.names()

    def named(name: str) -> str:
        return f"`{PROG} {name}`" + ("" if name in known else " (not in this clone yet)")

    return (
        f"next: {named('render')} installs the skills and the role definitions with these settings, "
        f"then {named('doctor')} checks the result"
    )


# --- The command --------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    if args.user and args.project is not None:
        raise SetupError("--user and --project: give one; they name two different files")
    where = locations.from_args(args)
    scope = PROJECT if where.project is not None else USER
    target: Path = where.project_file if scope == PROJECT else where.user_file  # type: ignore[assignment]
    below_layers = ("shipped",) if scope == USER else ("shipped", USER)
    found = homes.resolve(where)
    dictionaries = dictionary.load_all(where)

    # The file as it is must be one this tool reads: it is the base of
    # what is written.
    try:
        settings.resolve(where, layers=(*below_layers, scope))
    except SetupError as exc:
        raise SetupError(*exc.lines, "init changes nothing while a settings file has a fault; correct the file first") from None
    below = settings.resolve(where, layers=below_layers)
    current = [document for document in settings.documents(where) if document.layer == scope]
    existing = _flat(current[0].data) if current else None
    flat: dict[str, Any] = dict(existing or {})

    def proposed(key: str) -> Any:
        return flat[key] if key in flat else below[key].value

    def place(key: str, value: Any, pin: bool = False) -> None:
        """Set, keep or take out one key; see "What is written"."""
        if pin or (key in flat and _same(flat[key], value)):
            flat[key] = value
        elif key in below and _same(below[key].value, value):
            flat.pop(key, None)
        else:
            flat[key] = value

    dialogue = _Dialogue(args.yes, _terminal())
    layer = "the user layer" if scope == USER else "the project layer"
    print(f"settings file: {target} ({layer}; {'it exists' if existing is not None else 'not there yet'})")

    # --- Which providers ------------------------------------------------------
    configured = []
    for provider in found.providers:
        if not provider.installed:
            print(
                f"{provider.name}: not installed (the program `{provider.program}` is not on PATH and "
                f"{provider.home} does not exist); left out"
            )
        elif provider.name not in dictionaries:
            print(f"{provider.name}: installed, but this clone has no dictionary for it; left out")
        else:
            configured.append(provider)
    names = [provider.name for provider in configured]
    if not names:
        print("no provider is installed here: no provider section is written")

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
        if value is not None and scope == PROJECT and key.split(".")[0] in schema.USER_ONLY:
            typed = flag if value is True else f"--no-{flag[2:]}"
            raise SetupError(
                f"{typed}: {key} is read from the user's file alone (~/.agents/workflow.toml): it is a fact of this "
                "machine, not of a project. Give it to `init` without --project"
            )
        if value is not None:
            if isinstance(value, str) and kind == "string" and locations.control_character(value):
                raise SetupError(f"{flag}: the value holds a control character or a line break")
            answers[key] = _typed(kind, value) if isinstance(value, str) else value
            _check(key, answers[key], flag)

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
        )
        for table in _MAPS:
            for (provider_name, name), value in flags[table].items():
                if provider_name == provider.name:
                    state.maps[table][name] = value
                    state.given[table].add(name)
        print(f"{state.name}: {reading.describe()}")
        if state.comparison is not None:
            for line in state.comparison.lines():
                print(f"  {line}")
        for table in _MAPS:
            _settle_map(dialogue, state, table, args.allow_unlisted)
        states.append(state)

    for state in states:
        for table in _MAPS:
            for name, value in state.maps[table].items():
                place(f"providers.{state.name}.{table}.{name}", value, pin=scope == USER)
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
            place(key, model)

    # --- The other settings ---------------------------------------------------
    # The clone's question is asked where it applies: the user's file, on a
    # machine whose other side cannot read this clone. Elsewhere a value the
    # file holds stays as it is, and a flag still sets it.
    clone = homes.clone_standing(found)
    unasked: dict[str, str] = {}
    if scope == PROJECT:
        unasked[homes.UNSHARED_KEY] = "the user's file alone holds it"
    elif clone.shared is not False:
        why = clone.why.removeprefix("not asked: ")
        unasked[homes.UNSHARED_KEY] = f"the clone needs no such permission here ({why})"
    for key, flag, _, kind in _SETTINGS:
        if key in answers:
            place(key, answers[key])
            continue
        if key in unasked:
            continue
        if key == homes.UNSHARED_KEY and dialogue.interactive:
            print(
                f"the clone {clone.real} is {clone.why}: render and doctor refuse it unless {homes.UNSHARED_OPTION} "
                f"is given on each run, or {key} is true. Say true only where the {homes.other_side(found)} "
                f"does not install from this clone ({homes.unshared_cases(found)})"
            )
        place(key, _settle_setting(dialogue, key, flag, kind, proposed(key)))

    # --- What the roles would run with ----------------------------------------
    entries = {key: entry for key, entry in below.items() if key.split(".")[0] in profiles.GROUPS}
    entries.update({
        key: settings.Entry(value, scope, target)
        for key, value in flat.items() if key.split(".")[0] in profiles.GROUPS
    })
    definitions = roles.definitions(where)
    problems: list[str] = []
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
        print()
        print(f"{state.name}: the mapping")
        for line in state.table(role_models):
            print(line)
        for note in state.notes.values():
            print(f"  note: {note}")
    for note in profiles.unmatched([definition.id for definition in definitions], sorted(dictionaries), entries):
        print(f"note: {note}")
    print()
    print("settings:")
    for key, _, _, _ in _SETTINGS:
        if scope == PROJECT and key.split(".")[0] in schema.USER_ONLY:
            continue
        why = f"; not asked: {unasked[key]}" if key in unasked and key not in answers else ""
        if key in flat:
            print(f"  {key} = {tomlio.format_value(flat[key])}  (in this file{why})")
        else:
            print(f"  {key} = {tomlio.format_value(below[key].value)}  ({below[key].layer}; not written{why})")
    print()

    # --- Plan -----------------------------------------------------------------
    write = existing is None or not _same_values(flat, existing)
    roots = found.roots()
    plan = fileops.Plan(roots, follow_config_symlinks=args.follow_config_symlinks)
    text = _document(flat, scope)
    if write:
        plan.write_file(target, text, replace=fileops.ANY)
    if scope == PROJECT:
        plan.ignore()
    described = plan.describe()
    if not described.changed:
        print(f"nothing to write: {target} already holds these settings")
        print(_next_steps())
        return 0

    replaces = write and existing is not None
    if replaces:
        print(f"changes to {target}:")
        for line in _changes(existing or {}, flat, below):
            print(line)
        was = _read_text(target)
        if was is not None and was != _document(existing or {}, scope):
            print("  the file was edited outside `init`: its keys are kept, its comments and layout are not")
    elif write:
        print(f"{target}, as it {'would be' if args.dry_run else 'will be'} written:")
        for line in text.splitlines():
            print(f"    {line}".rstrip())
    for line in described.lines:
        print(line)
    for note in described.notes:
        print(f"note: {note}")
    # A file `init` did not write in its present form: ``--yes`` alone does
    # not confirm that its comments and layout go.
    by_hand = replaces and not _written_by_init(roots, target)
    needed = f"--yes {REWRITE_OPTION}" if by_hand else "--yes"
    if args.dry_run:
        if by_hand:
            print(f"note: {target} was written or edited by hand; without a terminal the run itself needs {needed}")
        print("dry run: nothing was written")
        print(_next_steps())
        return 0

    if dialogue.yes and by_hand and not args.rewrite_settings:
        raise SetupError(
            f"{target}: was written or edited by hand (its content is not what `init` wrote), and these answers "
            "change it. `init` rewrites the file from its values: every key is kept, its comments and layout are "
            f"not, and --yes alone does not confirm that. Give {REWRITE_OPTION} with --yes to rewrite it; the file "
            f"as it is now is then copied to {roots.backups_dir_of(scope == PROJECT)} first, under the time of the "
            "run. `uninstall` puts back a file that was there before the first `init`, and leaves in place, as "
            "yours, one that `init` rewrote after you edited it. Nothing was written"
        )
    if not dialogue.yes:
        if not dialogue.interactive:
            raise dialogue.unanswered("the confirmation to write", needed)
        question = "Write these settings? [y/N] (--yes): "
        if replaces:
            question = (
                f"{target} is rewritten from the values above: every key is kept, comments and layout "
                "are not. The file as it is now is copied to the backup directory first.\n"
                "Replace it? [y/N] (--yes): "
            )
        if dialogue.ask(question).lower() not in _TRUE:
            print("nothing was written")
            return EXIT_DECLINED
    plan.apply()
    if write:
        print(f"written: {target}")
    if replaces:
        print(f"the file as it was is in {roots.backups_dir_of(scope == PROJECT) / plan.stamp}")
    print(_next_steps())
    return 0


def _same(one: Any, other: Any) -> bool:
    """Equal as TOML values: ``True`` is not ``1``."""
    return type(one) is type(other) and one == other


def _same_values(one: dict[str, Any], other: dict[str, Any]) -> bool:
    return one.keys() == other.keys() and all(_same(one[key], other[key]) for key in one)


def _written_by_init(roots: Any, target: Path) -> bool:
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
