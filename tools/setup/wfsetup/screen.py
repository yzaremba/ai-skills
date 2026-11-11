"""The screen of ``setup.py`` on a terminal without ``--yes`` (R2).

One numbered list of every option, each with its value now and the layer and
file it comes from. Enter shows the plan, file by file, and asks "Apply?
[Y/n]"; n ends the run with exit code 1 and writes nothing. Numbers open
those options, then the list is shown again; ``r`` and numbers take those
options out of the file the run writes, so that the layer below gives them
again (R4.4).

The screen writes nothing and plans nothing itself. What it is told is kept
as the options of a run (``--docs-dir``, ``--tier``, ``--reset`` and the
others), and the plan and the apply are the program's own run with those
options: a dry run, then the run with ``--yes``. So a value changed here is
written, a value accepted as shown is not (R4.3), and the file a project is
given is made only when it holds a value (R6.1). An old key (R10.2) is named
with what replaces it; the settings file the run writes is written without it.

The items line opens a checklist (R3.2, R3.4). The Codex item opens as off,
on or on with the profile, then the worktree root (R8.3).

A generated file, key or block the user edited since setup wrote it: the first
plan finds each, the screen asks "replace, after a backup? [y/N]", and the plan
is made again with the answers (R8.4); what is not replaced is kept and
reported, with exit code 3, as in an unattended run.

A settings file written or edited by hand that the plan would rewrite is asked
about with them, once per run: "Rewrite it, after a backup? [y/N]" (R4.3). Yes
gives the run ``rewrite_settings``; no gives it ``keep_by_hand``, an option of
the screen's with no flag: the file is kept, the values not written are named,
the install goes on, and the run ends with exit code 3. Unattended, ``--yes``
alone still stops and names ``--rewrite-settings``.
"""
from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import codexsettings, definitions, dictionary, homes, locations, schema, settings, settingsfile, tomlio
from .errors import SetupError

EXIT_NO = 1
APPLY, NO, BACK = "apply", "no", "back"


def terminal() -> bool:
    """Whether standard input is a terminal: the screen is shown only there."""
    stream = sys.stdin
    try:
        return bool(stream) and stream.isatty()
    except (AttributeError, ValueError):
        return False


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        raise SetupError("standard input ended before the screen was answered; nothing was written") from None


@dataclass
class Row:
    number: int
    label: str
    kind: str                 # where, items, setting, map, codex
    key: str = ""             # a setting's dotted key, or `install`
    attribute: str = ""       # its attribute in the options
    flag: str = ""
    value_kind: str = ""      # a setting's type
    provider: str = ""        # a mapping row
    table: str = ""           # tiers or efforts


class Screen:
    def __init__(
        self, args: argparse.Namespace, where: locations.Locations, found: homes.Homes,
        execute: Callable[..., int], skills: Any = (),
    ) -> None:
        self.state = copy.copy(args)
        self.state.yes = False
        self.state.dry_run = False
        self.state.reset = list(args.reset)
        self.state.tier = list(args.tier)
        self.state.effort = list(args.effort)
        self.where = where
        self.found = found
        self.execute = execute
        self.replace: set[str] = set()     # the edited items the user said to replace
        self.asked: set[str] = set()       # and those already asked about
        self.skills = skills
        self.project = where.project is not None
        self.scope = settingsfile.PROJECT if self.project else settingsfile.USER
        self.target: Path = where.project_file if self.project else where.user_file    # type: ignore[assignment]
        self.below_layers = ("shipped",) if not self.project else ("shipped", settingsfile.USER)
        known = dictionary.load_all(where)
        self.providers = [
            provider.name for provider in found.providers if provider.installed and provider.name in known
        ]
        self.old = settings.old_keys(where)

    # --- The rows -------------------------------------------------------------

    def rows(self) -> list[Row]:
        rows = [Row(1, "where", "where"), Row(2, "items to install", "items", key=schema.INSTALL_KEY)]
        by_key = {key: (flag, attribute, kind) for key, flag, attribute, kind in settingsfile.SINGLE_SETTINGS}
        order = [
            "roles.manager_default", "process.docs_dir", "process.questions", "process.recommend", "memory.dir",
            "roles.high_stakes", "roles.max_parallel_coders",
        ]
        for key in order:
            if key == "roles.manager_default" and not self.project:
                continue
            flag, attribute, kind = by_key[key]
            label = "start as the Manager" if key == "roles.manager_default" else key
            rows.append(Row(len(rows) + 1, label, "setting", key, attribute, flag, kind))
        for name in self.providers:
            for table in settingsfile.MAPPINGS:
                rows.append(Row(len(rows) + 1, f"{name} {table}", "map", provider=name, table=table))
        if not self.project and self._codex_installed():
            rows.append(Row(len(rows) + 1, "Codex config item", "codex"))
        return rows

    def _codex_installed(self) -> bool:
        return any(provider.name == homes.CODEX and provider.installed for provider in self.found.providers)

    # --- Values ---------------------------------------------------------------

    def _origin(self, entry: settings.Entry) -> str:
        file = entry.file
        if entry.layer == "shipped":
            try:
                file = file.relative_to(self.where.clone)
            except ValueError:
                pass
        return f"{entry.layer}: {file}"

    def _mapping_flags(self, table: str) -> dict[tuple[str, str], str]:
        flag = "tier" if table == "tiers" else "effort"
        found: dict[tuple[str, str], str] = {}
        for text in getattr(self.state, flag):
            head, _, value = text.partition("=")
            provider, _, name = head.partition(":")
            found[(provider, name)] = value
        return found

    def describe(self, row: Row, entries: dict[str, settings.Entry], below: dict[str, settings.Entry]) -> str:
        if row.kind == "where":
            if self.project:
                return f"project {self.where.project} (and this machine's homes)"
            return "this machine"
        if row.kind == "items":
            return self._single(row.key, getattr(self.state, "install"), self._install_entry(), self._install_below())
        if row.kind == "setting":
            return self._single(row.key, getattr(self.state, row.attribute), entries.get(row.key), below.get(row.key))
        if row.kind == "codex":
            mode = getattr(self.state, "codex_settings", None)
            root = getattr(self.state, "worktree_root", None)
            if mode is not None:
                return f"{mode}{'' if root is None else f', worktree root {root}'}  (this run: written to the Codex config)"
            if root is not None:
                return f"{self._codex_held(root=False)}, worktree root {root}  (this run: written to the Codex config)"
            return f"{self._codex_held()}  (as the Codex config holds it; not changed by this run)"
        given = self._mapping_flags(row.table)
        names = schema.TIERS if row.table == "tiers" else schema.EFFORTS
        parts, origins = [], []
        for name in names:
            key = f"providers.{row.provider}.{row.table}.{name}"
            if (row.provider, name) in given:
                parts.append(f"{name}={given[(row.provider, name)]}")
                origin = f"this run: written to {self.target}"
            elif key in self.state.reset and key in below:
                parts.append(f"{name}={below[key].value}")
                origin = f"taken out of {self.target}; {self._origin(below[key])}"
            elif key in entries:
                parts.append(f"{name}={entries[key].value}")
                origin = self._origin(entries[key])
            else:
                continue
            if origin not in origins:
                origins.append(origin)
        return "  ".join(parts) + "  (" + "; ".join(origins) + ")"

    def _single(self, key: str, given: Any, entry: settings.Entry | None, below: settings.Entry | None) -> str:
        if given is not None:
            return f"{self._value(given)}  (this run: written to {self.target})"
        if key in self.state.reset:
            if below is None:
                return f"nothing  (taken out of {self.target})"
            return f"{self._value(below.value)}  (taken out of {self.target}; {self._origin(below)})"
        if entry is None:
            return "not set"
        return f"{self._value(entry.value)}  ({self._origin(entry)})"

    @staticmethod
    def _value(value: Any) -> str:
        if isinstance(value, list):
            return " ".join(str(item) for item in value) or "nothing"
        return tomlio.format_value(value)

    def _install_entry(self) -> settings.Entry | None:
        held = settings.install(self.where)
        return held[-1] if held else None

    def _install_below(self) -> settings.Entry | None:
        held = [entry for entry in settings.install(self.where) if entry.layer in self.below_layers]
        return held[-1] if held else None

    # --- The screen -----------------------------------------------------------

    def show(self) -> list[Row]:
        entries = settings.resolve(self.where)
        below = settings.resolve(self.where, layers=self.below_layers)
        rows = self.rows()
        print()
        for file, key, replacement in self.old:
            if file == self.target:
                print(f"old key {key} in {file}: use {replacement}. The file written drops it")
            else:
                print(f"old key {key} in {file}: use {replacement}. This run does not write that file: change it there")
        if self.old:
            print()
        width = max(len(row.label) for row in rows)
        for row in rows:
            print(f"{row.number:>3}  {row.label:<{width}}  {self.describe(row, entries, below)}")
        return rows

    def loop(self) -> int:
        while True:
            rows = self.show()
            print()
            answer = _ask("Enter: the plan.  Numbers: change those options.  r and numbers: reset them. ")
            if answer:
                self.choose(answer, rows)
                continue
            verdict = self.plan()
            if verdict == APPLY:
                return self.apply()
            if verdict == NO:
                return EXIT_NO

    def plan(self) -> str:
        """Show the plan and ask: ``APPLY``, ``NO``, or ``BACK`` when the plan
        was refused and the screen comes again."""
        print()
        while True:
            planned = self._with_answers()
            planned.dry_run = True
            edited: list[tuple[str, str]] = []
            try:
                self.execute(planned, edited)
            except SetupError as exc:
                for line in exc.lines:
                    print(f"error: {line}")
                return BACK
            if not self._ask_edited(edited):
                break
            print()
        while True:
            answer = _ask("Apply? [Y/n] ").lower()
            if answer in ("", "y", "yes"):
                return APPLY
            if answer in ("n", "no"):
                return NO

    def _with_answers(self) -> argparse.Namespace:
        """The options of a run, with the edited items answered yes to (R8.4);
        ``--overwrite-edited`` on the command line stays as it is."""
        given = copy.copy(self.state)
        hand = {ident for ident in self.asked if ident.startswith(settingsfile.HAND_ID)}
        items = {ident for ident in self.replace if ident not in hand}
        if items and not given.overwrite_edited:
            given.overwrite_edited = frozenset(items)
        if hand:
            if hand & self.replace:
                given.rewrite_settings = True
            else:
                given.keep_by_hand = True
        return given

    def _ask_edited(self, edited: list[tuple[str, str]]) -> bool:
        """Ask about each edited item not asked about yet; whether any answer
        was yes, or was about a settings file by hand, so that the plan is to be made again."""
        said = False
        for ident, text in edited:
            if ident in self.asked:
                continue
            self.asked.add(ident)
            if ident.startswith(settingsfile.HAND_ID):
                question = f"{text}: written or edited by hand. Rewrite it, after a backup? [y/N] "
            else:
                question = f"{text}: edited by hand since setup wrote it. Replace, after a backup? [y/N] "
            if _ask(question).lower() in ("y", "yes"):
                self.replace.add(ident)
                said = True
            elif ident.startswith(settingsfile.HAND_ID):
                said = True         # a no to the file by hand changes the plan too: it is kept
        return said

    def apply(self) -> int:
        applied = self._with_answers()
        applied.yes = True
        return self.execute(applied)

    # --- Numbers --------------------------------------------------------------

    def choose(self, answer: str, rows: list[Row]) -> None:
        words = answer.split()
        reset = words[0].lower() == "r"
        if reset:
            words = words[1:]
        numbers: list[Row] = []
        for word in words:
            if not word.isdigit() or not 1 <= int(word) <= len(rows):
                print(f"{word}: not an option; type numbers from 1 to {len(rows)}")
                return
            numbers.append(rows[int(word) - 1])
        if not numbers:
            print("type the numbers of the options" + (" to reset" if reset else ""))
            return
        for row in numbers:
            (self.reset_row if reset else self.open_row)(row)

    def _held(self, key: str) -> bool:
        """Whether the file this run writes holds ``key``."""
        for document in settings.documents(self.where):
            if document.file == self.target:
                return key in settingsfile.flat_keys(document.data)
        return False

    def _take_out(self, key: str, label: str) -> None:
        if key in self.state.reset:
            return
        if self._held(key):
            self.state.reset.append(key)
        else:
            print(f"{label}: {self.target} does not hold it; nothing to take out")

    def reset_row(self, row: Row) -> None:
        if row.kind == "where":
            print("where: given on the command line; nothing to reset")
        elif row.kind == "codex":
            self.state.codex_settings = None
            self.state.worktree_root = None
            print(f"{row.label}: this run no longer changes it")
        elif row.kind == "map":
            if not self.project:
                print(
                    f"{row.label}: the user's file holds the mapping in full, so a key of it is not taken out; "
                    "change one instead"
                )
                return
            names = schema.TIERS if row.table == "tiers" else schema.EFFORTS
            flag = "tier" if row.table == "tiers" else "effort"
            setattr(self.state, flag, [
                text for text in getattr(self.state, flag) if not text.startswith(f"{row.provider}:")
            ])
            held = [f"providers.{row.provider}.{row.table}.{name}" for name in names]
            if not any(self._held(key) for key in held):
                print(f"{row.label}: {self.target} does not hold it; nothing to take out")
            for key in held:
                if self._held(key):
                    self._take_out(key, row.label)
        else:
            if row.kind == "items":
                self.state.install = None
            else:
                setattr(self.state, row.attribute, None)
            self._take_out(row.key, row.label)

    def open_row(self, row: Row) -> None:
        if row.kind == "where":
            print("where: given on the command line (the project's DIR, or none for this machine)")
        elif row.kind == "items":
            self._open_items(row)
        elif row.kind == "setting":
            self._open_setting(row)
        elif row.kind == "codex":
            self._open_codex(row)
        else:
            self._open_map(row)

    def _open_items(self, row: Row) -> None:
        """The checklist of the clone's skills, the rule and ``roles`` (R3.2, R3.4)."""
        every = definitions.units(self.where, self.skills)
        home: set[str] = set()
        roles_bind = True
        if self.project:
            level = definitions.user_level(self.where)
            home = set(definitions.home_selection(level, self.skills).units)
            if definitions.roles_installed(level):
                home.add(schema.ROLES_ITEM)
            roles_bind = schema.ROLES_ITEM not in home    # where the home has roles, they add nothing here
        names = [schema.ROLES_ITEM] + sorted(every)
        chosen = [name for name in self._chosen() if name in every or name == schema.ROLES_ITEM]
        first = list(chosen)
        needs = definitions.dependencies(self.where)
        bound = definitions.bound_skills(self.where) & every
        def view() -> tuple[set[str], dict[str, list[str]]]:
            selection = definitions.select(self.where, chosen, every, roles_bind=roles_bind)
            ticked = set(selection.units) | ({schema.ROLES_ITEM} & set(chosen))
            needers: dict[str, list[str]] = {}
            for unit in sorted(selection.units):
                for need in needs.get(unit, ()):
                    if need in every:
                        needers.setdefault(need, []).append(unit)
            if schema.ROLES_ITEM in chosen and roles_bind:
                for unit in sorted(bound):
                    needers.setdefault(unit, []).append(definitions.ROLES_NEED)
            return ticked, needers

        while True:
            ticked, needers = view()
            width = len(str(len(names)))
            print(f"{row.label}:")
            for number, name in enumerate(names, 1):
                if name in home:
                    mark, note = "x", "  (from this machine)"
                else:
                    mark = "x" if name in ticked else " "
                    note = f"  (needed by {', '.join(needers[name])})" if needers.get(name) and name in ticked else ""
                print(f"  {number:>{width}}  [{mark}] {name}{note}")
            answer = _ask("Numbers to tick or untick, nothing to finish: ")
            if not answer:
                break
            for word in answer.split():
                if not word.isdigit() or not 1 <= int(word) <= len(names):
                    print(f"{word}: not an item; type numbers from 1 to {len(names)}")
                    break
                name = names[int(word) - 1]
                ticked, needers = view()
                if name in home:
                    print(f"{name}: from this machine; it is changed there")
                elif name not in ticked:
                    chosen.append(name)
                elif needers.get(name):
                    print(f"{name}: needed by {', '.join(needers[name])}; untick that first")
                else:
                    chosen.remove(name)
                    if name == schema.ROLES_ITEM:    # the skills it brought stay
                        chosen += [unit for unit in sorted(bound - home) if unit not in chosen]
        if chosen != first:
            self.state.install = chosen
            self._unreset(row.key)

    def _chosen(self) -> list[str]:
        """The names the items line holds now: this run's, else the file's."""
        if self.state.install is not None:
            return list(self.state.install)
        # The file this run writes: a project's own, not the local file's above it.
        held = [entry for entry in settings.install(self.where)
                if entry.file == self.target or (not self.project and entry.layer in self.below_layers)]
        return list(held[-1].value) if held else []

    def _open_setting(self, row: Row) -> None:
        entries = settings.resolve(self.where)
        shown = getattr(self.state, row.attribute)
        if shown is None:
            shown = entries[row.key].value
        hint = f"{row.flag} or --no-{row.flag[2:]}" if row.value_kind == "boolean" else row.flag
        while True:
            answer = _ask(f"{row.key} [{tomlio.format_value(shown)}] ({hint}): ")
            if not answer:
                return
            value = settingsfile.typed_value(row.value_kind, answer)
            try:
                settingsfile.check_value(row.key, value, "answer")
            except SetupError as exc:
                for line in exc.lines:
                    print(f"  {line}")
                continue
            setattr(self.state, row.attribute, value)
            self._unreset(row.key)
            return

    def _open_codex(self, row: Row) -> None:
        shown = getattr(self.state, "codex_settings", None) or "as it stands"
        while True:
            answer = _ask(
                f"{row.label} [{shown}]: off, on, or profile (on with the profile selected), or nothing to leave it "
                f"({codexsettings.CODEX_OPTION}): "
            )
            if not answer:
                break
            if answer in codexsettings.MODES:
                self.state.codex_settings = answer
                break
            print(f"  {answer}: expected {', '.join(codexsettings.MODES)}")
        mode = getattr(self.state, "codex_settings", None)
        if mode == "off":
            self.state.worktree_root = None
            return
        if mode is None and not self._codex_on():
            return
        held = getattr(self.state, "worktree_root", None)
        while True:
            answer = _ask(
                f"worktree root [{held or 'none'}]: the directory your git worktrees are made under, or nothing to "
                f"leave it ({codexsettings.WORKTREE_OPTION}): "
            )
            if not answer:
                return
            try:
                codexsettings.worktree_root(answer)
            except SetupError as exc:
                for line in exc.lines:
                    print(f"  {line}")
                continue
            self.state.worktree_root = answer
            return

    def _codex_held(self, root: bool = True) -> str:
        """The mode (off, on, profile) and the worktree root as the Codex
        config's blocks hold them now."""
        try:
            place = self.found.provider(homes.CODEX).place(homes.CONFIG).path
            held = codexsettings.analyse(place.read_bytes() if place.is_file() else None).held
        except (SetupError, OSError, KeyError, ValueError):
            return "not read"
        if held is None:
            return "off"
        text = "profile" if held.default else "on"
        return f"{text}, worktree root {held.root}" if root and held.root else text

    def _codex_on(self) -> bool:
        """Whether the Codex config holds setup's blocks now."""
        provider = self.found.provider(homes.CODEX)
        try:
            place = provider.place(homes.CONFIG).path
            return place.is_file() and codexsettings.analyse(place.read_bytes()).held is not None
        except (SetupError, OSError, KeyError, ValueError):
            return False

    def _open_map(self, row: Row) -> None:
        word, meta, names, flag = settingsfile.MAPPINGS[row.table]
        entries = settings.resolve(self.where)
        given = self._mapping_flags(row.table)
        shown = "  ".join(
            f"{name}={given.get((row.provider, name), entries[f'providers.{row.provider}.{row.table}.{name}'].value)}"
            for name in names
        )
        print(f"{row.label}: {shown}")
        while True:
            answer = _ask(f"  change, as {word}={meta} ..., or nothing to accept ({flag} {row.provider}:...): ")
            if not answer:
                return
            changed: dict[str, str] = {}
            try:
                for item in answer.split():
                    name, equals, value = item.partition("=")
                    if not equals or not name:
                        raise SetupError(f"{item}: expected {word}={meta}")
                    settingsfile.check_value(f"providers.{row.provider}.{row.table}.{name}", value, "answer")
                    changed[name] = value
            except SetupError as exc:
                for line in exc.lines:
                    print(f"  {line}")
                continue
            kept = [
                text for text in getattr(self.state, flag[2:])
                if text.partition("=")[0].partition(":")[2] not in changed or not text.startswith(f"{row.provider}:")
            ]
            kept += [f"{row.provider}:{name}={value}" for name, value in changed.items()]
            setattr(self.state, flag[2:], kept)
            for name in changed:
                self._unreset(f"providers.{row.provider}.{row.table}.{name}")
            return

    def _unreset(self, key: str) -> None:
        if key in self.state.reset:
            self.state.reset.remove(key)


def run(
    args: argparse.Namespace, where: locations.Locations, found: homes.Homes,
    execute: Callable[..., int], skills: Any = (),
) -> int:
    """Show the screen and carry out what it ends in; the run's exit code.
    ``execute`` is the program's run with the options it is given: a dry run
    for the plan, the run with ``--yes`` for the apply."""
    return Screen(args, where, found, execute, skills).loop()
