"""What the install writes, as parts that fill one plan.

How the program uses it

    for part in render.PARTS: part.add_arguments(parser)   # a part's own options
    outcome = render.execute(homes, sources, args)          # plan, show, apply
    render.report_lines(outcome.report)                     # or the report as JSON
    outcome.errors, outcome.code

A part
    ``Part(name, fill, configure)``. ``fill(run)`` asks for what the part
    installs and writes nothing: ``run.link(provider, place, name, target)``
    for a link into a place of a home, or an action added to ``run.plan``
    directly, with ``run.want(path)`` for each path the action makes.
    ``configure(parser)`` adds the options only that part reads; it reads
    them from ``run.options``. The parts run in the order of ``PARTS`` and
    fill the same ``fileops.Plan``, so the whole run is validated and shown
    together, and a plan that is refused writes nothing. Applying is not
    atomic: a change that fails part way leaves the changes before it made
    and recorded (``fileops``), and the next run goes on from there. A
    later step adds a part to ``PARTS`` and does not change the others.

    The parts now: ``skills`` (R6.2), ``rules`` (R2.2), ``roles`` (R6.2:
    each provider's role definitions, built by ``definitions``) and
    ``entry`` (R4.4, R4.5: how a session becomes a role, built by ``entry``,
    and what a project gets).

The project (``DIR``)
    A run without a project writes nothing in any project. With one, the
    home is refreshed as always, from the user-level settings, and the
    ``entry`` part adds, in the project: the definitions its settings
    change (``Run.file`` into ``.claude/agents`` and ``.codex/agents``), and
    with ``roles.manager_default`` the starting role as the project's
    default (``Run.json_key``: ``agent`` in ``.claude/settings.json``, and
    ``effortLevel`` beside it, the role's effort, which a Claude Code
    session, as documented, does not take from the role's definition (see
    ``entry``: not yet shown by a session); ``Run.block``: a
    marked block at the head of ``.codex/config.toml``). ``effortLevel`` is
    a key like ``agent`` and goes by every rule below. It is not set where
    it cannot hold the role's effort (``max``, or a model that takes
    none): a note says which, and what setup set earlier is taken out.
    While the ``agent`` key has a value that is not setup's and is kept
    (the user's own, or setup's changed by hand), the project's sessions do
    not start as the role and its effort is not theirs to run at: the
    effort is then not set for the first time, and one setup set earlier is
    left as it is, neither changed nor taken out, until the ``agent`` key
    is setup's again or is no longer wanted.
    Both keys are set, changed and taken out only by a run that changed the
    project's choices (``execute``'s ``project_changed``: ``setup.py DIR``
    wrote the project's ``.agents/workflow.toml`` or was given
    ``--manager-default`` or ``--no-manager-default``). Any other run leaves them as they are, set or not,
    and what the record holds of them, even where the home's mapping now
    gives the role another effort (R6.1): the file is tracked, and one
    user's mapping is not the project's. A note says so.
    A rule of the project's list is copied into ``.claude/rules/<name>/``
    for Claude Code (``fill_project_rules``), a generated file like the
    definitions; the sweep (``Run.other_sides``) keeps a copy whose rule is
    still listed while Claude Code is not here or the machine has another
    side, which may have made it. A project's link, whoever made it, is
    setup's by where it leads, not by its text, and the sweep removes it so.
    They are recorded in the project's record, swept from it like a home's
    files, and the generated files are listed in setup's block of the
    repository's exclude file, ``info/exclude`` in its common git directory
    (R6.3, ``gitrepo``); a project with no git directory this side can read
    gets no list, and a note. The key and the block are not listed: they
    are setup's part of a file the project owns and may commit, and an
    entry would hide the whole file. A ``.codex/config.toml`` that setup
    created for its block is listed; one that was there before never is. A project's path is the project's whichever side of the
    machine it is on: only a link in the way is asked about.

    A key or a block that was changed by hand since setup wrote it is
    ``edited`` like a file: kept, reported, exit code 3, and set again with
    ``--overwrite-edited``. One that is no longer wanted is taken out when
    it is as setup left it (the key gets its earlier value back), and kept
    when it was changed.

    What setup did not write is treated the same way. A key that has
    another value and is not in the record (a project's own ``agent``) is
    kept and reported, and replaced only with ``--overwrite-edited``; the
    value it had comes back when setup takes its key out. A marker pair
    that is in a file and not in the record is adopted, as a change of the
    record alone, when the block between the markers is exactly what setup
    would write; with anything else between them it is the user's text:
    kept, reported, and replaced only with ``--overwrite-edited``, after a
    backup of the file.

    A loaded role is a user-level skill, and a provider's personal skill
    wins over a project's skill of the same name, so a project's settings
    cannot reach it and nothing is generated for it in a project. Where
    they give a loaded role another profile the report says so, with both
    profiles (``project.loaded_roles``).

Directories
    A directory setup created is removed again when a removal of this run
    leaves it empty: a loaded role's skill directory, a project's
    ``.codex``; and so is one the record lists below a place this run
    writes, once nothing is in it (a stopped run may have emptied it).
    One that holds anything else stays, and so does a place of a home
    (its skills, agents and rules directories), empty or not, and one
    below a directory of setup's that is a link now. These removals are
    a clean-up: one the system refuses because the directory is no
    longer empty or is in use is skipped with a note, and the run goes on.

    A part that cannot make what it installs says so with ``run.fail``; the
    run then stops before anything is written, like a conflict.

What ``Run.file`` decides for one generated file, in this order
    skipped, needs-flag   as for a link, by the place
    conflict     something is at the path that the record does not show as a
                 file setup wrote: a user's file, a directory, a link
    create       nothing is there
    up-to-date   the file holds the text wanted
    update       setup's file, as setup left it, and the text wanted differs
    edited       setup's file, edited by hand since. It is kept and reported,
                 with what to do; with ``--overwrite-edited`` it is backed up
                 and replaced (``replace``)
    The Codex profile is asked for with ``carry``: Codex writes into it
    (its trust answers, flags of its interface), and what follows setup's
    part is not setup's (``carried``). While setup's own part is as setup
    wrote it and nothing after it sets one of setup's keys, the file is
    not edited, whatever follows; it is written again with that after
    the new text. Replaced on request, an edited profile keeps every key
    of it that is not setup's. A file there that setup did not write and
    whose keys are all ones Codex writes itself (what ``--uninstall``
    leaves) is written over, with setup's text before what it holds, and
    not a conflict; any other file there is. A key after setup's part
    that Codex does not write itself is named in the profile's line.
    The record keeps the hash of setup's own part beside the hash of the
    whole file. A stale profile with something after setup's part is
    ``release``: setup's part is taken out and the rest left, as yours.
    ``inputs`` goes into the record with the file's hash. It starts with
    ``GENERATED_PREFIX``, which is how the stale sweep knows a file is one
    the install generates and not, say, a settings file ``settingsfile`` wrote.

Stale files
    A generated file in the record that no part asked for is removed when it
    still holds what setup wrote, forgotten when it is gone, and kept and
    reported when it was edited. A home whose ``install`` lacks ``roles``
    asks for no role definition, so the definitions of an earlier run are
    stale and go the same way: the homes then hold the process alone.

Whether the roles are generated (``roles_on``)
    The home's roles are on when its effective ``install`` (the user's over
    the shipped one) holds ``roles``. A project gets roles only where the
    home has them: its definitions replace some of the home's, and its
    starting role is a definition of the home's, so it follows the home.

What ``Run.link`` decides for one link, in this order
    skipped      the name is a skill with a setup of its own (R1.2), whatever
                 is at the path;
                 or the place is the other side's, or a second name for a
                 place already handled (``homes.Standing``);
                 or the place is, or leads into, a clone of this repository
                 (``Run.in_clone``): nothing is written into one, with any
                 option
    needs-flag   the place is, or lies under, a link to elsewhere on this
                 side, and ``--follow-config-symlinks`` was not given
    conflict     something is at the path that the record does not show as
                 setup's own link: a file or directory, a link setup did not
                 make, setup's link pointed elsewhere since
    up-to-date   setup's link, as wanted
    create       nothing is there
    The place decides whose the path is, not what an existing entry leads
    to: a link in this side's directory is this side's entry, also when it
    leads to the other side's home. That one is a conflict, not a skip.
    In a project a link is told by where it leads (R3.4): one the record
    holds as setup's that leads, by its real path, to the unit is up to
    date whatever its text or form (the other side's), and is not asked of
    the plan; one the record does not hold that leads there was made by
    hand and is taken over (``fileops.Plan.adopt_link``); anything else is
    a conflict.

Stale links
    After the parts, every link the user-level record holds that no part
    asked for is one the install would no longer make: its skill left the
    clone, or its compatibility line no longer names that provider, or the
    provider is gone. It is removed when it still points where setup pointed
    it, forgotten when it is no longer there, and kept and reported when the
    user changed it. A link in a place this run does not write is left to
    the run that does.
    A project's link that no part asked for is left alone, and not
    reported, while its unit is in the project's list and its
    ``compatibility`` names the provider whose place it is in, where that
    provider is not installed on this side or the machine has another side,
    which may have made it (R3.2, ``Run.other_sides``). A project's link
    is compared with its recorded target from the directory it is in, and
    one taken over by where it leads.

Nothing is written when there is a conflict or an error in the plan: the
report is made, ``Outcome.errors`` holds one line per conflict, and the plan
is not run. A failure while the plan is applied is another matter: it leaves
``execute`` as the ``SetupError`` of ``fileops``, which says how many changes
were made; they are recorded, the next run goes on, and ``--uninstall`` undoes
them.

Exit codes
    0                 done, or nothing to do
    2                 an error, or a conflict (``errors.EXIT_ERROR``)
    EXIT_NEEDS_FLAG   everything else was done (or would be, in a dry run),
                      and at least one path was left that an option would
                      write: a path ``--follow-config-symlinks`` would
                      write, or a generated file, a key or a block that
                      was edited by hand or is not setup's, which
                      ``--overwrite-edited`` would replace
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import blocks, carried, definitions, dictionary, entry, fileops, fsio, gitrepo, homes, jsonkeys, modellist, paths, schema, settings
from . import codexsettings
from .errors import EXIT_ERROR, SetupError
from .locations import Locations
from .validate import Report as Sources

REPORT_SCHEMA_VERSION = 1
EXIT_NEEDS_FLAG = 3

# What became of one link or file.
UP_TO_DATE = "up-to-date"
CREATE = "create"
UPDATE = "update"          # a generated file whose text changed
REPLACE = "replace"        # a generated file edited by hand, replaced on request
EDITED = "edited"          # a generated file edited by hand, kept
REMOVE = "remove"          # stale, still as setup made it
FORGET = "forget"          # stale and gone: only the record changes
RELEASE = "release"        # stale; setup's part taken out, the rest left as the user's
KEPT = "kept"              # stale, and changed by the user
SKIPPED = "skipped"
NEEDS_FLAG = "needs-flag"
CONFLICT = "conflict"
ERROR = "error"

_BLOCKING = (CONFLICT, ERROR)
_WRITES = (CREATE, UPDATE, REPLACE)

# What an item is.
LINK = "link"
FILE = "file"
KEY = "key"                # one key of a JSON file the project owns
BLOCK = "block"            # setup's marked block in a text file the project owns
NEW_FILE = "write, in a new file"   # what a block's item says where setup creates its file

# Where a project's items are, in an item's ``place``.
PROJECT = "project"

# How the ``inputs`` of every file the install generates starts.
GENERATED_PREFIX = "render:"

FOLLOW_OPTION = "--follow-config-symlinks"
OVERWRITE_OPTION = "--overwrite-edited"


def _repository_around(path: Path, clone: Path) -> Path | None:
    """The clone of this repository that the real path of ``path`` is, or
    lies inside: the clone setup runs from, or a directory that holds what
    a clone holds (``doctor.looks_like_clone``), at the path or above it.
    None where there is none. The rule under which the install writes
    nothing in a place, so a ``.git`` entry alone does not count: a user
    may keep a home's own directory under git."""
    from . import doctor
    try:
        real = Path(os.path.realpath(path))
        own = Path(os.path.realpath(clone))
    except (OSError, ValueError):
        return None
    return own if paths.inside(real, own) else doctor.clone_above(real)


@dataclass
class Item:
    """One link or generated file the install looked at."""

    name: str
    path: Path
    status: str
    says: str
    key: str | None = None        # the path as the record writes it
    target: str | None = None     # a link's target as the record writes it
    provider: str | None = None   # None for a stale entry
    place: str | None = None
    whole_place: bool = False     # the reason is the place's, not this entry's
    kind: str = LINK
    size: int | None = None       # a generated file: the bytes of its text
    detail: dict[str, Any] = field(default_factory=dict)  # what the part says of it
    project: bool = False         # in the project, not in a home

    def as_json(self) -> dict[str, Any]:
        found = {
            "name": self.name, "path": str(self.path), "key": self.key, "target": self.target,
            "status": self.status, "says": self.says, "kind": self.kind,
        }
        if self.kind != LINK:
            if self.kind == FILE:
                found["bytes"] = self.size
            found.update(self.detail)
        return found


@dataclass(frozen=True)
class Part:
    """One thing the install writes; see the module."""

    name: str
    fill: Callable[["Run"], None]
    configure: Callable[[Any], None] | None = None

    def add_arguments(self, parser: Any) -> None:
        if self.configure is not None:
            self.configure(parser)


@dataclass
class Outcome:
    report: dict[str, Any]
    code: int
    errors: list[str] = field(default_factory=list)
    # The project's ``.claude/settings.json`` when this run wrote it (R6.2).
    written: tuple[Path, ...] = ()
    # The items kept because the user edited them, each as ``(edited_id, text)``:
    # what the screen asks about (R8.4).
    edited: tuple[tuple[str, str], ...] = ()


def edited_id(path: Path, name: str | None = None) -> str:
    """How an edited item is named to ``Run``'s ``overwrite``: its path, and
    for a key or a block the name in it."""
    return str(path) if name is None else f"{path}#{name}"


_fold = paths.fold_key


class Run:
    """One run of the install: the homes, the sources, the record as it is,
    and the plan the parts fill."""

    def __init__(self, found: homes.Homes, sources: Sources, options: Any = None, *, follow: bool = False,
                 overwrite: bool | frozenset[str] | set[str] = False, stamp: str | None = None,
                 project_changed: bool = True) -> None:
        self.homes = found
        self.sources = sources
        self.options = options
        self.follow = follow
        # True: every edited item may be replaced (``--overwrite-edited``); a
        # set: the items whose ``edited_id`` it holds (the screen's answers).
        self._overwrite = overwrite
        # Whether the project's choices changed in this run; while they did
        # not, the two keys of ``.claude/settings.json`` are left (R6.1).
        self.project_changed = project_changed
        self._codex_tracked: dict[Path, bool | None] = {}
        self.errors: list[str] = []
        self.roots = found.roots()
        self.sorter = homes.Classifier(found)
        self.record = fileops.read_record(self.roots)
        self.plan = fileops.Plan(self.roots, follow_config_symlinks=follow, stamp=stamp)
        self.items: list[Item] = []
        self.stale: list[Item] = []
        self.points: list[dict[str, Any]] = []     # the entry points, for the report
        self.project_facts: dict[str, Any] = {}    # what the entry part found of the project
        self._wanted: set[str] = set()
        self._standings: dict[str, homes.Standing] = {}
        self._clones: dict[str, str | None] = {}
        self._emptied: list[Path] = []
        self._ignore_always = False
        self._roles: tuple[bool, Path | None] | None = None   # whether the roles are generated, and the file of the home's install; see ``roles_on``
        self._dirs: dict[str, dict[str, str]] | None = None   # the binding rows' directories of a project's own roles; see ``project_dirs``
        self._dirs_read = False
        self._selection: definitions.Selection | None = None   # the home's units; see ``home_selection``
        self._selection_read = False
        self._project_selection: definitions.Selection | None = None   # the project's units; see ``project_selection``
        self._project_selection_read = False
        self.notes: list[str] = []                 # what a part says beside its items; printed as notes
        self.notices: list[str] = []               # the notes `--check` reports as warnings (R6.4, R10.3)
        self.model_notes: list[str] = []           # the model-list note (R3.2): printed after every other note
        # Called once the plan has run, been shown or been refused: a part's
        # note that reads the disk as the run left it.
        self.settled: list[Callable[[], None]] = []

    # --- For the parts ---------------------------------------------------------

    def option(self, name: str, default: Any = None) -> Any:
        return getattr(self.options, name, default)

    def want(self, path: Path) -> str | None:
        """Say that this run answers for ``path``: it is not stale."""
        key = self.roots.key(path)
        if key is not None:
            self._wanted.add(_fold(key))
        return key

    def in_project(self, path: Path) -> bool:
        key = self.roots.key(path)
        return key is not None and key.partition(":")[0] == fileops.PROJECT

    def standing(self, directory: Path) -> homes.Standing:
        """Whose a directory is. Asked once: the classifier takes a second
        question for the same place as a second name for it. A directory of
        the project is the project's on either side of the machine: only a
        link in the way is asked about."""
        ident = paths.fold(paths.absolute(directory))
        if ident not in self._standings:
            if self.in_project(directory):
                directory = Path(os.path.abspath(directory))
                try:
                    problem = fileops.symlink_in_the_way(self.roots, directory)
                except SetupError as exc:
                    found = homes.Standing(homes.UNKNOWN, directory, reason=exc.lines[0])
                else:
                    found = homes.Standing(homes.THIS_SIDE, directory) if problem is None else homes.Standing(
                        homes.SHARED, directory, link=problem.link, target=problem.resolves_to
                    )
                self._standings[ident] = found
            else:
                self._standings[ident] = self.sorter.standing(directory)
            found = self._standings[ident]
            if found.through_link:
                # Where the link leads is written only if it is inside the
                # roots of this run and outside every clone: ``fsio``
                # refuses anything else under any option, so the place is
                # skipped here and the rest of the run goes on.
                why = fileops.refusal(self.roots, Path(os.path.abspath(directory)) / "x")
                if why is not None:
                    reason = (
                        "it leads into a clone, which setup never writes to" if "never writes to" in why
                        else "it leads out of the home and the project of this run"
                    )
                    self._standings[ident] = homes.Standing(
                        homes.OUTSIDE, found.path, real=found.real, link=found.link, target=found.target,
                        reason=reason,
                    )
        return self._standings[ident]

    def in_clone(self, directory: Path) -> str | None:
        """Why nothing is written in ``directory``, where its real path is,
        or lies inside, a clone of this repository (the one setup runs
        from, or any other, told by what it holds): a place of a home that
        is a link into a clone holds the clone's own files, and a link or a
        file made there would be made in the clone. None for any other
        directory; a directory of a home that the user keeps under git is
        not a clone of this repository. Asked whatever the options are: no
        option makes setup write into a clone."""
        ident = paths.fold(paths.absolute(directory))
        if ident not in self._clones:
            around = None if self.in_project(directory) else _repository_around(directory, self.homes.clone)
            self._clones[ident] = None if around is None else (
                f"{directory} is, or leads into, a clone of this repository ({around}); setup writes nothing into "
                "a clone. Point it at a directory of its own, or remove the link"
            )
        return self._clones[ident]

    def emptied(self, path: Path) -> None:
        """Say that this run removes ``path``, or setup's part of it: the
        directories setup created above it go too, where nothing is left
        in them."""
        self._emptied.append(Path(os.path.abspath(path)))

    def ignore_always(self) -> None:
        """Say that the project holds something of setup's, so its ignore
        block is kept even when no generated file is listed in it."""
        self._ignore_always = True

    def overwrite(self, path: Path, name: str | None = None) -> bool:
        """Whether the edited item at ``path`` (a key or a block: ``name`` in
        it) may be backed up and replaced."""
        if isinstance(self._overwrite, bool):
            return self._overwrite
        return edited_id(path, name) in self._overwrite

    def link(self, provider: homes.Provider, place: homes.Place, name: str, target: Path,
             own_setup: bool = False, relative: bool = False) -> Item:
        """Ask for the link ``place/name`` to ``target``; see the module.
        ``relative``: the link's text is relative (a project's link, from
        WSL, to a clone on the same Windows drive)."""
        path = place.path / name
        project = self.in_project(path)
        item = Item(name, path, CREATE, "", provider=provider.name, place=place.name,
                    target=self.roots.target_key(str(target), fileops.PROJECT if project else None), project=project)
        self.items.append(item)

        def settle(status: str, says: str, whole_place: bool = False) -> Item:
            item.status, item.says, item.whole_place = status, says, whole_place
            return item

        entry = self.sorter.entry(path)
        if own_setup or entry.kind == homes.OWN_SETUP:
            says = entry.describe() if entry.kind == homes.OWN_SETUP else "managed by its own setup; left alone"
            return settle(SKIPPED, says)
        item.key = self.want(path)
        if item.key is None:
            return settle(ERROR, f"{path}: outside the homes of this run")
        standing = self.standing(place.path)
        if standing.kind == homes.UNKNOWN:
            return settle(ERROR, f"{place.path}: {standing.describe()}", True)
        if not standing.writes:
            return settle(SKIPPED, standing.describe(), True)
        clone = self.in_clone(place.path)
        if clone is not None:
            return settle(SKIPPED, clone, True)
        if standing.through_link and not self.follow:
            return settle(NEEDS_FLAG, f"{standing.describe()}; give {FOLLOW_OPTION} to write there", True)

        base = self.record.get(item.key)
        if base is not None and base.get("kind") not in ("link", *fileops.REPLACEABLE):
            return settle(CONFLICT, f"{path}: the record holds it as {base.get('kind')}, not as a link setup made")
        held = base
        if base is not None and base.get("kind") != "link":
            base = None  # a link or a directory of the user's that setup removed: not a link setup made
        if entry.kind == homes.UNKNOWN:
            return settle(ERROR, f"{path}: {entry.describe()}")
        # A project's link is told by where it leads (R3.4): the other
        # side's link has its own text and form, and is asked of no plan,
        # whose fold would make another text a new link.
        if project and entry.kind == homes.LINK_TO_CLONE and _leads_to(entry.real, target):
            if base is not None and _fold(str(base.get("target"))) == _fold(item.target or ""):
                return settle(UP_TO_DATE, f"linked to {item.target}" + (
                    "; made by hand and taken over" if base.get("adopted") else ""))
            if held is None:
                self.plan.adopt_link(path, target)
                return settle(UP_TO_DATE, (
                    f"linked to {item.target} by a link made by hand, which setup takes over: "
                    "`setup.py --uninstall DIR` leaves it, and taking the skill off the project's `install` list removes it"
                ))
        if entry.kind == homes.PLAIN:
            return settle(CONFLICT, f"{path}: {entry.describe()}, and setup did not make it")
        elif entry.kind != homes.ABSENT:
            if base is None:
                return settle(CONFLICT, f"{path}: {entry.describe()}, and setup did not make it")
            try:
                recorded = self.roots.target_text(base["target"])
            except (SetupError, KeyError, TypeError):
                return settle(CONFLICT, f"{path}: {entry.describe()}; the record's entry for it cannot be read")
            if not fsio.same_target(entry.target or "", recorded, path.parent):
                return settle(
                    CONFLICT,
                    f"{path}: {entry.describe()}; setup made it a link to {recorded}, and it was changed since",
                )
            if fsio.same_target(recorded, str(target), path.parent):
                settle(UP_TO_DATE, f"linked to {item.target}")
        if item.status == CREATE and not item.says:
            item.says = f"link to {item.target}"
        # An up-to-date link is asked for as well: the plan then checks it
        # against the disk once more, and changes nothing.
        self.plan.create_link(path, target, relative=relative)
        return item

    def left_out(self, provider: homes.Provider, place: homes.Place, name: str, says: str) -> Item:
        """A link that is not asked for: an item ``skipped`` with ``says``.
        A link there is the sweep's to judge (``Run.other_sides``)."""
        path = place.path / name
        item = Item(name, path, SKIPPED, says, provider=provider.name, place=place.name,
                    project=self.in_project(path))
        self.items.append(item)
        return item

    def other_sides(self, path: Path) -> bool:
        """Whether the sweep leaves the project's link ``path`` alone, not
        asked for by this run: its unit is still in the project's list, the
        unit's ``compatibility`` names the provider whose place it is in,
        and either that provider is not installed on this side or the
        machine has another side, which may have made it (R3.2)."""
        project = self.homes.project
        if project is None or not self.in_project(path):
            return False
        chosen = project_selection(self)
        if chosen is None:
            return False
        copy = self._rule_copy(path)
        if copy is not None:
            # A rule copy (R4.1) is Claude Code's: kept while its rule is in
            # the list, still holds that file, and Claude Code is not here
            # or the machine has another side.
            installed = {found.name for found in self.homes.installed()}
            return (copy.name in chosen.units and (copy / path.name).is_file()
                    and (homes.CLAUDE_CODE not in installed or self.homes.host.other is not None))
        skill = self.sources.skills.get(path.name)
        if skill is None or path.name not in chosen.units:
            return False
        where = paths.fold(paths.absolute(path.parent))
        provider = next((
            name for name, parts in homes.PROJECT_SKILLS.items()
            if paths.fold(paths.absolute(project.joinpath(*parts))) == where
        ), None)
        if provider is None or provider not in skill.providers:
            return False
        installed = {found.name for found in self.homes.installed()}
        return provider not in installed or self.homes.host.other is not None

    def _rule_copy(self, path: Path) -> Path | None:
        """The clone's rule directory when ``path`` is a file of a rule's copy
        in the project (``.claude/rules/<name>/<file>``), else None."""
        project = self.homes.project
        if project is None:
            return None
        where = paths.fold(paths.absolute(path.parent.parent))
        if where != paths.fold(paths.absolute(project / ".claude" / "rules")):
            return None
        return self.homes.clone / homes.RULES / path.parent.name

    def fail(self, *lines: str) -> None:
        """Say that a part cannot make what it installs. The run stops
        before anything is written, and each line is printed."""
        self.errors.extend(line for line in lines if line not in self.errors)

    def file(self, provider: homes.Provider, place: homes.Place, name: str, text: str, inputs: str,
             detail: dict[str, Any] | None = None, carry: bool = False) -> Item:
        """Ask for the generated file ``place/name`` to hold ``text``; see
        the module. ``inputs`` is the digest of what the text was made from.
        With ``carry`` the file keeps what Codex or the user added after
        setup's part (the Codex profile, see ``carried``)."""
        if not inputs.startswith(GENERATED_PREFIX):
            raise ValueError(f"{name}: the inputs digest of a generated file starts with {GENERATED_PREFIX}")
        path = place.path / name
        data = text.encode("utf-8")
        item = Item(name, path, CREATE, "", provider=provider.name, place=place.name, kind=FILE, size=len(data),
                    detail=dict(detail or {}), project=self.in_project(path))
        self.items.append(item)

        def settle(status: str, says: str, whole_place: bool = False) -> Item:
            item.status, item.says, item.whole_place = status, says, whole_place
            return item

        item.key = self.want(path)
        if item.key is None:
            return settle(ERROR, f"{path}: outside the homes of this run")
        standing = self.standing(place.path)
        if standing.kind == homes.UNKNOWN:
            return settle(ERROR, f"{place.path}: {standing.describe()}", True)
        if not standing.writes:
            return settle(SKIPPED, standing.describe(), True)
        clone = self.in_clone(place.path)
        if clone is not None:
            return settle(SKIPPED, clone, True)
        if standing.through_link and not self.follow:
            return settle(NEEDS_FLAG, f"{standing.describe()}; give {FOLLOW_OPTION} to write there", True)

        base = self.record.get(item.key)
        known = None if base is None else base.get("kind")
        try:
            seen = fsio.look(path)
            there = fsio.read_bytes(path) if seen.kind == fsio.FILE else None
        except SetupError as exc:
            return settle(ERROR, exc.lines[0])
        policy = fileops.OWN
        carrying: dict[str, Any] = {}
        if carry:
            # Setup's own part is ``text``; what the file there carries
            # that is not setup's follows it (``carried``).
            carrying["own_sha256"] = fsio.sha256(data)
        if seen.kind == fsio.ABSENT:
            if known not in (None, "file", "removed-file"):
                return settle(CONFLICT, f"{path}: the record holds it as {known}, not as a file setup generates")
            settle(CREATE, "write")
        elif seen.kind == fsio.LINK:
            if not self.follow:
                return settle(NEEDS_FLAG, f"{path}: a link to {seen.target}; give {FOLLOW_OPTION} to write where it leads")
            settle(UPDATE, "write where the link leads")
            if carry:
                # Where the link leads is setup's file: the same rules as
                # for a file at the path.
                try:
                    real = Path(os.path.realpath(path))
                    held = fsio.read_bytes(real) if os.path.isfile(real) else None
                except SetupError as exc:
                    return settle(ERROR, exc.lines[0])
                if held is not None and known == "file":
                    done = self._carry(item, path, text, held, base or {})
                    if done is None:
                        return item
                    text, policy = done
                    item.says += " (where the link leads)"
                    carrying["made_from"] = fsio.sha256(held)
        elif seen.kind != fsio.FILE:
            return settle(CONFLICT, f"{path}: a {seen.kind} is there, where setup would write a file")
        elif carry and known is None and carried.only_codexs(there or b""):
            # What ``--uninstall`` (or a sweep) left of setup's file: the part
            # that was not setup's, alone. Setup's text goes before it again.
            try:
                keep = carried.tail_text(b"\n" + carried.left((there or b"").removeprefix(b"\xef\xbb\xbf")))
                text = carried.join(text, keep)
            except SetupError as exc:
                return settle(ERROR, f"{path}: {exc.lines[0]}")
            settle(CREATE, f"write before what the file there holds, which is kept ({carried.WHAT})")
            policy = fileops.ANY
            carrying["made_from"] = fsio.sha256(there or b"")
        elif known != "file":
            what = "setup did not write it" if known is None else f"the record holds it as {known}"
            return settle(CONFLICT, f"{path}: a file is there, and {what}")
        elif carry:
            done = self._carry(item, path, text, there or b"", base or {})
            if done is None:
                return item
            text, policy = done
            carrying["made_from"] = fsio.sha256(there or b"")
        elif there == data:
            settle(UP_TO_DATE, "as generated")
        elif fsio.sha256(there or b"") != (base or {}).get("sha256"):
            if not self.overwrite(path):
                return settle(
                    EDITED,
                    f"edited by hand since setup wrote it, and kept; {OVERWRITE_OPTION} backs it up and replaces "
                    "it, or remove the file and run setup.py again",
                )
            policy = fileops.EDITED
            settle(REPLACE, "edited by hand since setup wrote it; backed up and replaced")
        else:
            settle(UPDATE, "write again: its sources or settings changed")
        # An up-to-date file is asked for as well: the plan checks it against
        # the disk once more, and brings the record's digest up to date.
        item.size = len(text.encode("utf-8"))
        self.plan.write_file(path, text, inputs=inputs, replace=policy, **carrying)
        return item

    def _carry(self, item: Item, path: Path, text: str, there: bytes,
               base: dict[str, Any]) -> tuple[str, str] | None:
        """For ``file``: setup's file that carries a part that is not
        setup's. Returns the text to write, setup's ``text`` with that part
        after it, and the plan's policy; None when the item is settled
        without a write (kept, or an error)."""
        tail = carried.split(there, carried.own_hash(base))
        try:
            if tail is not None:
                # Setup's part is as setup wrote it: whatever follows it is
                # Codex's or the user's, and no edit of setup's file.
                keep = carried.tail_text(tail)
                whole = carried.join(text, keep)
                kept = f"; {carried.WHAT} kept" if keep else ""
                kept += carried.said(carried.named(carried.tail_keys(tail)))
                if there == whole.encode("utf-8"):
                    item.status, item.says = UP_TO_DATE, f"as generated{kept}"
                else:
                    item.status, item.says = UPDATE, f"write again: its sources or settings changed{kept}"
                return whole, fileops.OWN
            if not self.overwrite(item.path):
                item.status, item.says = EDITED, (
                    f"edited by hand since setup wrote it, and kept; {OVERWRITE_OPTION} backs it up and replaces "
                    "it, keeping every key of it that is not setup's, or remove the file and run setup.py again"
                )
                return None
            keep, why = carried.extracted(there, text)
            whole = carried.join(text, keep)
        except SetupError as exc:
            item.status, item.says = ERROR, f"{path}: {exc.lines[0]}"
            return None
        says = "edited by hand since setup wrote it; backed up and replaced"
        if keep:
            says += ", and its keys that are not setup's kept"
        if why:
            says += f"; {why}"
        item.status, item.says = REPLACE, says
        return whole, fileops.EDITED

    # --- Setup's part of a file the project owns ------------------------------

    def _owned(self, item: Item, removing: bool = False) -> tuple[bool, bytes | None]:
        """Look at a user-owned file for ``item``: whether the run may go
        on with it, and its bytes (None where no file is)."""
        path = item.path
        item.key = self.roots.key(path)
        if item.key is None:
            item.status, item.says = ERROR, f"{path}: outside the homes and the project of this run"
            return False, None
        standing = self.standing(path.parent)
        verb = "remove it" if removing else "write"
        if standing.kind == homes.UNKNOWN:
            item.status, item.says = ERROR, f"{path.parent}: {standing.describe()}"
            return False, None
        if standing.through_link and not self.follow:
            item.status, item.says = NEEDS_FLAG, f"{standing.describe()}; give {FOLLOW_OPTION} to {verb} there"
            return False, None
        try:
            seen = fsio.look(path)
            if seen.kind == fsio.LINK:
                if not self.follow:
                    item.status = NEEDS_FLAG
                    item.says = f"{path}: a link to {seen.target}; give {FOLLOW_OPTION} to {verb} where it leads"
                    return False, None
                real = Path(os.path.realpath(path))
                # Looked at before it is opened: a FIFO there would block the read.
                if os.path.lexists(real) and not os.path.isfile(real):
                    item.status, item.says = CONFLICT, f"{path}: the link does not lead to a file"
                    return False, None
                return True, fsio.read_bytes(real)
            if seen.kind == fsio.ABSENT:
                return True, None
            if seen.kind != fsio.FILE:
                item.status, item.says = CONFLICT, f"{path}: a {seen.kind} is there, where a settings file would be"
                return False, None
            return True, fsio.read_bytes(path)
        except SetupError as exc:
            item.status, item.says = ERROR, exc.lines[0]
            return False, None

    def _recorded(self, key: str | None, kind: str, table: str, name: str) -> dict[str, Any] | None:
        base = self.record.get(key) if key is not None else None
        if base is None or base.get("kind") != kind:
            return None
        found = (base.get(table) or {}).get(name)
        return found if isinstance(found, dict) else None

    def json_key(self, provider: homes.Provider, path: Path, name: str, value: Any) -> Item:
        """Ask for the top-level key ``name`` of the JSON file ``path`` to
        be ``value``; see the module."""
        item = Item(name, path, CREATE, "", provider=provider.name, place=PROJECT, kind=KEY,
                    detail={"value": value}, project=self.in_project(path))
        self.items.append(item)
        fine, data = self._owned(item)
        if not fine:
            return item
        shown = json.dumps(value, ensure_ascii=False)
        known = self._recorded(item.key, "json", "keys", name)
        if data is None:
            item.says = f"set to {shown}, in a new file"
        else:
            try:
                _, current = jsonkeys.parse(data)
            except jsonkeys.Refusal as exc:
                item.status, item.says = ERROR, f"{path}: {exc}"
                return item
            if name in current and jsonkeys.same(current[name], value):
                item.status = UP_TO_DATE
                item.says = f"is {shown}" + ("" if known is not None else ", set by you; it stays yours")
            elif name in current and known is not None and not jsonkeys.same(current[name], known.get("value")):
                was = json.dumps(current[name], ensure_ascii=False)
                if not self.overwrite(path, name):
                    item.status = EDITED
                    item.says = (
                        f"changed by hand since setup set it (it is {was}, setup set {shown}), and kept; "
                        f"{OVERWRITE_OPTION} sets it again, or remove the key and run setup.py again"
                    )
                    return item
                item.status, item.says = REPLACE, f"changed by hand since setup set it (it was {was}); set to {shown} again"
            elif name in current and known is None:
                # A value setup did not write: the user's, until they say otherwise.
                was = json.dumps(current[name], ensure_ascii=False)
                if not self.overwrite(path, name):
                    item.status = EDITED
                    item.says = (
                        f"is {was}, which setup did not set, and kept: setup does not replace a value of yours, so "
                        f"it is not set to {shown}. {OVERWRITE_OPTION} sets it, and {was} is put back when setup "
                        "takes its key out; or remove the key and run setup.py again"
                    )
                    return item
                item.status = REPLACE
                item.says = (
                    f"was {was}, which setup did not set; set to {shown}, as {OVERWRITE_OPTION} asks. {was} is put "
                    "back when setup takes its key out"
                )
            elif name in current:
                item.status, item.says = UPDATE, f"set to {shown}"
            else:
                item.says = f"set to {shown}"
        self.plan.edit_json(path, set={name: value})
        return item

    def drop_json_key(self, path: Path, name: str) -> Item | None:
        """Take out a key setup set and no part asks for any more. Nothing
        is done where the record does not hold the key."""
        key = self.roots.key(path)
        known = self._recorded(key, "json", "keys", name)
        if known is None:
            return None
        item = Item(name, path, REMOVE, "", key=key, place=PROJECT, kind=KEY, project=self.in_project(path))
        self.stale.append(item)
        fine, data = self._owned(item, removing=True)
        if not fine:
            return item
        try:
            current = {} if data is None else jsonkeys.parse(data)[1]
        except jsonkeys.Refusal as exc:
            item.status, item.says = ERROR, f"{path}: {exc}"
            return item
        if name not in current:
            item.status, item.says = FORGET, "no longer set by setup and no longer there; taken out of the record"
        elif not jsonkeys.same(current[name], known.get("value")):
            item.status, item.says = KEPT, "no longer set by setup, and changed since setup set it; kept, it is yours"
        elif known.get("had"):
            was = json.dumps(known.get("previous"), ensure_ascii=False)
            item.says = f"no longer set by setup; the value it had before, {was}, is put back"
        else:
            item.says = "no longer set by setup; it still has setup's value, so it is removed"
        # The plan gives up the key in each case: one that was changed is
        # left as it is and is the user's from now on.
        self.plan.edit_json(path, remove=[name])
        self.emptied(path)
        return item

    def block(self, provider: homes.Provider, path: Path, name: str, content: str, place: str = fileops.END) -> Item:
        """Ask for setup's block ``name`` in the text file ``path`` to hold
        ``content``; see the module."""
        item = Item(name, path, CREATE, "", provider=provider.name, place=PROJECT, kind=BLOCK,
                    size=len(content.encode("utf-8")), project=self.in_project(path))
        self.items.append(item)
        fine, data = self._owned(item)
        if not fine:
            return item
        syntax = blocks.syntax_for(path.name) or blocks.TOML
        known = self._recorded(item.key, "text", "blocks", name)
        policy: dict[str, str] = {}
        try:
            there = None if data is None else blocks.get(data, syntax, name)
            wanted = blocks.put(data, syntax, name, content, place)
        except blocks.Refusal as exc:
            item.status, item.says = ERROR, f"{path}: {exc}"
            return item
        if data is None:
            item.says = NEW_FILE
        elif wanted == data:
            item.status, item.says = UP_TO_DATE, "as generated" + (
                "" if known is not None else "; the record did not hold the block, and takes it up"
            )
        elif there is None:
            item.says = f"write, at the {'head' if place == fileops.HEAD else 'end'} of the file"
        elif known is not None and not blocks.as_written(data, there, known.get("sha256")):
            if not self.overwrite(path, name):
                item.status = EDITED
                item.says = (
                    f"edited by hand since setup wrote it, and kept; {OVERWRITE_OPTION} backs the file up and "
                    "writes the block again, or remove the block with its markers and run setup.py again"
                )
                return item
            item.status, item.says = REPLACE, "edited by hand since setup wrote it; the file is backed up and the block written again"
            policy = {"replace": fileops.EDITED}   # the plan refuses an edited block unless told
        elif known is None:
            # Setup's markers with other text between them than setup would
            # write, and no record of the block: the user's text.
            if not self.overwrite(path, name):
                item.status = EDITED
                item.says = (
                    "setup's markers are in the file with other text between them than setup writes, and the "
                    f"install record does not hold the block: kept as it is. {OVERWRITE_OPTION} backs the file up "
                    "and writes the block in its place, or take the markers out and run setup.py again"
                )
                return item
            item.status = REPLACE
            item.says = (
                "setup's markers were in the file with other text between them, and the record did not hold the "
                "block; the file is backed up and the block written"
            )
            policy = {"replace": fileops.ANY}   # the plan refuses such a block unless told
        else:
            item.status, item.says = UPDATE, "write again: its sources or settings changed"
        self.plan.edit_block(path, content, name=name, place=place, **policy)
        return item

    def drop_block(self, path: Path, name: str) -> Item | None:
        """Take out a block setup wrote and no part asks for any more.
        Nothing is done where the record does not hold the block."""
        key = self.roots.key(path)
        known = self._recorded(key, "text", "blocks", name)
        if known is None:
            return None
        item = Item(name, path, REMOVE, "", key=key, place=PROJECT, kind=BLOCK, project=self.in_project(path))
        self.stale.append(item)
        fine, data = self._owned(item, removing=True)
        if not fine:
            return item
        syntax = blocks.syntax_for(path.name) or blocks.TOML
        try:
            there = None if data is None else blocks.get(data, syntax, name)
        except blocks.Refusal as exc:
            item.status, item.says = ERROR, f"{path}: {exc}"
            return item
        if there is None:
            item.status, item.says = FORGET, "no longer generated and no longer there; taken out of the record"
        elif not blocks.as_written(data or b"", there, known.get("sha256")):
            item.status = KEPT
            item.says = "no longer generated, and edited since setup wrote it; kept, it is yours to remove"
            return item
        else:
            item.says = "no longer generated; it still holds what setup wrote, so it is removed"
        self.plan.remove_block(path, name=name)
        self.emptied(path)
        return item

    # --- After the parts -------------------------------------------------------

    def sweep(self) -> None:
        """Plan the removal of the links and generated files no part asked
        for; see the module. Not after a part failed: what that part would
        have asked for is then not known, and nothing is written anyway."""
        if self.errors:
            return
        # Both records: a project's files are swept by the same rule as a
        # home's. A run without a project has no project record.
        for key, entry in list(self.record.entries.items()):
            if _fold(key) in self._wanted:
                continue
            if entry.get("kind") == "file":
                if str(entry.get("inputs") or "").startswith(GENERATED_PREFIX):
                    self._sweep_file(key, entry)
                continue
            if entry.get("kind") != "link":
                continue
            try:
                path = self.roots.path(key)
                recorded = self.roots.target_text(entry["target"])
            except (SetupError, KeyError, TypeError) as exc:
                why = exc.lines[0] if isinstance(exc, SetupError) else "the record's entry cannot be read"
                self.stale.append(Item(key, Path(key), KEPT, why, key=key))
                continue
            if self.other_sides(path):
                continue
            item = Item(path.name, path, REMOVE, "", key=key, target=entry.get("target"), project=self.in_project(path))
            self.stale.append(item)
            standing = self.standing(path.parent)
            if standing.kind == homes.UNKNOWN:
                item.status, item.says = ERROR, f"{path.parent}: {standing.describe()}"
                continue
            if not standing.writes:
                item.status, item.says = SKIPPED, standing.describe()
                continue
            if standing.through_link and not self.follow:
                item.status, item.says = NEEDS_FLAG, f"{standing.describe()}; give {FOLLOW_OPTION} to remove it there"
                continue
            try:
                seen = fsio.look(path)
            except SetupError as exc:
                item.status, item.says = ERROR, exc.lines[0]
                continue
            if seen.kind == fsio.ABSENT:
                item.status, item.says = FORGET, "no longer installed and no longer there; taken out of the record"
                self.plan.remove_link(path)
                self.emptied(path)
            elif seen.kind == fsio.LINK and (
                fsio.same_target(seen.target or "", recorded, path.parent)
                or (self.in_project(path) and _leads_to(path, recorded))   # a project's link, by where it leads
            ):
                item.says = "no longer installed; it still points where setup pointed it, so it is removed"
                self.plan.remove_link(path, expect_target=recorded)
                self.emptied(path)
            else:
                what = f"a link to {seen.target}" if seen.kind == fsio.LINK else f"a {seen.kind}"
                item.status = KEPT
                item.says = f"no longer installed, and no longer the link setup made ({what} is there); kept, it is yours"

    def _sweep_file(self, key: str, entry: dict[str, Any]) -> None:
        try:
            path = self.roots.path(key)
        except SetupError as exc:
            self.stale.append(Item(key, Path(key), KEPT, exc.lines[0], key=key, kind=FILE))
            return
        if self.other_sides(path):
            return
        item = Item(path.name, path, REMOVE, "", key=key, kind=FILE, project=self.in_project(path))
        self.stale.append(item)
        standing = self.standing(path.parent)
        if standing.kind == homes.UNKNOWN:
            item.status, item.says = ERROR, f"{path.parent}: {standing.describe()}"
            return
        if not standing.writes:
            item.status, item.says = SKIPPED, standing.describe()
            return
        if standing.through_link and not self.follow:
            item.status, item.says = NEEDS_FLAG, f"{standing.describe()}; give {FOLLOW_OPTION} to remove it there"
            return
        try:
            seen = fsio.look(path)
            there = fsio.read_bytes(path) if seen.kind == fsio.FILE else None
        except SetupError as exc:
            item.status, item.says = ERROR, exc.lines[0]
            return
        recorded = entry.get("sha256")
        # A file that carries a part that is not setup's (``carried``):
        # what follows setup's own part, while that part is as setup wrote it.
        tail = None if there is None else carried.split(there, carried.own_hash(entry))
        if seen.kind == fsio.ABSENT:
            item.status, item.says = FORGET, "no longer generated and no longer there; taken out of the record"
            self.plan.remove_file(path)
            self.emptied(path)
        elif there is not None and tail and carried.left(tail).strip():
            item.status = RELEASE
            item.says = (
                f"no longer generated; setup's part is taken out, and the file is left holding {carried.WHAT}, "
                "as yours"
            )
            self.plan.release_file(path, carried.left(tail), expect_sha256=fsio.sha256(there))
        elif there is not None and tail is None and carried.own_hash(entry) and carried.no_setup_key(there):
            # Its owner took setup's part out: what is left is theirs.
            item.status = RELEASE
            item.says = "no longer generated, and setup's part is no longer in it; left as it is, as yours"
            self.plan.release_file(path, there, expect_sha256=fsio.sha256(there))
        elif there is not None and tail is not None:
            item.says = "no longer generated; it still holds what setup wrote, so it is removed"
            self.plan.remove_file(path, expect_sha256=fsio.sha256(there))
            self.emptied(path)
        elif there is not None and isinstance(recorded, str) and fsio.sha256(there) == recorded:
            item.says = "no longer generated; it still holds what setup wrote, so it is removed"
            self.plan.remove_file(path, expect_sha256=recorded)
            self.emptied(path)
        else:
            what = "it was edited since setup wrote it" if seen.kind == fsio.FILE else f"a {seen.kind} is there"
            item.status, item.says = KEPT, f"no longer generated, and {what}; kept, it is yours"

    def _ignore(self, project: Path) -> None:
        """Setup's block in the project's exclude file: the generated files
        and the links of the project, and a ``.codex/config.toml`` that
        setup created; never a file setup writes into and did not create.
        A project with no git directory this side can read gets no list,
        and a note says why; a block an earlier run listed in the record
        is then left as it is."""
        def entry_of(item: Item) -> str:
            return item.path.relative_to(project).as_posix()

        def created(item: Item) -> bool:
            # A file setup holds a block in, and that setup created: one
            # this run creates, or one the record says setup created.
            if item.status in (ERROR, EDITED, KEPT):
                return False
            if item.says == NEW_FILE:
                return True
            known = self.record.get(item.key) if item.key else None
            return known is not None and known.get("kind") == "text" and bool(known.get("created"))

        add = sorted({
            entry_of(item) for item in self.items
            if item.project and (item.kind == FILE or (item.kind == LINK and item.status != SKIPPED))
        } | {
            entry_of(item) for item in self.items
            if item.project and item.kind == BLOCK and entry_of(item) in fileops.IGNORE_CREATED and created(item)
        })
        remove = sorted({
            entry_of(item) for item in self.stale
            if item.project and item.status in (REMOVE, FORGET) and (
                item.kind in (FILE, LINK) or (item.kind == BLOCK and entry_of(item) in fileops.IGNORE_CREATED)
            )
        } - set(add))
        held = self.record.project is not None and self.record.project.on_disk
        if not (add or remove or held or self._ignore_always):
            return
        found = self.homes.repository
        exclude = None if found is None else found.exclude
        why = None if exclude is None else fileops.refusal(self.roots, exclude)
        if exclude is None or why is not None:
            note = found.note if exclude is None and found is not None and found.note else f"{project}: {why}"
            if self.record.get(fileops.GIT_INFO_EXCLUDE) is not None:
                note += f"; the block the record lists in {fileops.GIT_INFO_EXCLUDE} is left as it is"
            self.notes.append(f"project: {note}")
            return
        self.plan.ignore(exclude, add=add, remove=remove, replace=fileops.ANY if self.overwrite(exclude) else fileops.OWN)

    def notice(self, text: str) -> None:
        """A note that `--check` also reports, as a warning."""
        self.notes.append(text)
        self.notices.append(text)

    def codex_tracked(self, path: Path) -> bool | None:
        """Whether git tracks the project's ``.codex/config.toml`` (R6.4):
        asked once per run; None where ``git`` could not be asked."""
        if path not in self._codex_tracked:
            project = self.homes.project
            assert project is not None
            self._codex_tracked[path] = gitrepo.tracked(project, path.relative_to(project).as_posix())
        return self._codex_tracked[path]

    def _old_ignore(self, project: Path) -> None:
        """Setup's old block in the project's ``.gitignore`` (R10.3): named
        for the user to remove, with its file and lines, and its record
        entry, if there is one, forgotten. The file is never edited: setup
        lists in the repository's exclude file now. A block whose markers
        are setup's counts with or without a record (a fresh checkout has
        none)."""
        path = project / ".gitignore"
        key = self.roots.key(path)
        try:
            data = fsio.read_bytes(path) if fsio.look(path).kind == fsio.FILE else None
            if data is not None:
                blocks.check_text(data)
            span = None if data is None else blocks.scan(blocks.split_bom(data)[1], blocks.GITIGNORE).get("")
        except (SetupError, blocks.Refusal):
            return
        if key is not None and self._recorded(key, "text", "blocks", "") is not None:
            self.plan.forget_block(path, name="")
        if span is not None:
            self.notice(
                f"project: {path}: lines {span[0] + 1}-{span[1]} are setup's old ignore block; setup lists in "
                f"{fileops.GIT_INFO_EXCLUDE} now and never edits it again: remove those lines"
            )

    def _writes_into(self, directory: Path) -> bool:
        """Whether this run writes into the place ``directory`` as it is."""
        if not _is_directory(directory):
            return False
        standing = self.standing(directory)
        if standing.kind == homes.UNKNOWN or not standing.writes or (standing.through_link and not self.follow):
            return False
        return self.in_clone(directory) is None

    def finish(self) -> None:
        """After the sweep: the project's ignore block in the repository's
        exclude file (R6.3), and the directories of setup's that this run
        leaves empty."""
        if self.errors:
            return
        project = self.homes.project
        if project is not None:
            self._ignore(project)
            self._old_ignore(project)
        asked: dict[str, Path] = {}
        places = {
            paths.fold(paths.absolute(place.path))
            for provider in self.homes.providers for place in provider.places
        }
        for path in self._emptied:
            key = self.roots.key(path)
            if key is None:
                continue
            root = self.roots.root(key.partition(":")[0])
            for parent in path.parents:
                if parent == root or self.roots.key(parent) is None or len(parent.parts) <= len(root.parts):
                    break
                ident = paths.fold(parent)
                if ident in places:
                    break
                asked.setdefault(ident, parent)
        # A directory setup created below a place this run writes, which the
        # record still lists: a run stopped after it emptied the directory
        # and recorded that has left no stale entry that leads here. The
        # plan removes it only when nothing is left in it.
        writable = [
            paths.fold(paths.absolute(place.path)) for provider in self.homes.providers for place in provider.places
            if self._writes_into(place.path)
        ]
        for key, entry in self.record.entries.items():
            if entry.get("kind") != "directory" or key.partition(":")[0] == fileops.PROJECT:
                continue
            try:
                path = Path(os.path.abspath(self.roots.path(key)))
            except SetupError:
                continue
            ident = paths.fold(path)
            if ident in places or not _is_directory(path):
                continue
            if any(ident.startswith(place + os.sep) for place in writable):
                asked.setdefault(ident, path)
        # A directory before its parent: the plan empties them in this order.
        for parent in sorted(asked.values(), key=lambda path: -len(path.parts)):
            # A clean-up: refused as not empty or in use, it is skipped.
            self.plan.remove_directory(parent, optional=True)


# --- The parts ----------------------------------------------------------------

def _is_directory(path: Path) -> bool:
    """A directory, and no link to one; False where it cannot be looked at."""
    try:
        return fsio.look(path).kind == fsio.DIRECTORY
    except SetupError:
        return False


def _has_place(provider: homes.Provider, name: str) -> bool:
    return any(place.name == name for place in provider.places)


def _leads_to(path: Path | str | None, place: Path | str) -> bool:
    """Whether ``path`` leads, by its real path, to ``place``, by its own."""
    if path is None:
        return False
    try:
        return paths.fold(os.path.realpath(path)) == paths.fold(os.path.realpath(place))
    except (OSError, ValueError):
        return False


def home_selection(run: Run) -> definitions.Selection | None:
    """The skills and rules the home installs, read once, from its
    ``install``. Each unit added as a dependency is named in a note. None
    where the ``install`` is at fault: the first part to ask reports it,
    and the run then writes nothing."""
    if not run._selection_read:
        run._selection_read = True
        try:
            run._selection = definitions.home_selection(_locations(run, None), run.sources.skills)
            run.notes.extend(run._selection.notes())
        except SetupError as exc:
            run.fail(*exc.lines)
    return run._selection


def project_selection(run: Run) -> definitions.Selection | None:
    """The skills and rules the project lists, read once; see
    ``definitions.project_selection``. None where the run has no project or
    its files hold no ``install``. Its fault is the run's: it then writes nothing."""
    if not run._project_selection_read:
        run._project_selection_read = True
        project = run.homes.project
        if project is not None:
            try:
                found = definitions.project_selection(_locations(run, project), run.sources.skills)
            except SetupError as exc:
                run.fail(*exc.lines)
            else:
                run._project_selection = found
                if found is not None:
                    held = home_selection(run)
                    at_home = held.units if held is not None else frozenset()
                    for name in sorted(found.needed):
                        if name in at_home:   # the run skips it; no install to claim
                            run.notes.append(f"project: {name}: needed by {', '.join(found.needed[name])}; the home has it")
                        else:
                            run.notes.append(f"project: {name}: installed as a dependency of {', '.join(found.needed[name])}")
    return run._project_selection


def fill_skills(run: Run) -> None:
    """Every skill into the skills place of each installed provider its
    ``compatibility`` line names (R6.2), but those the home's selection
    leaves out. A skill with a setup of its own is skipped, whatever is at its path
    (R1.2)."""
    selection = home_selection(run)
    if selection is None:
        return
    for provider in run.homes.installed():
        if not _has_place(provider, homes.SKILLS):
            continue
        place = provider.place(homes.SKILLS)
        for name, skill in run.sources.skills.items():
            if provider.name in skill.providers and (name in selection.units or skill.own_setup):
                run.link(provider, place, name, run.homes.clone / name, own_setup=skill.own_setup)
    fill_project_skills(run, selection)


def fill_project_skills(run: Run, selection: definitions.Selection) -> None:
    """Every skill of the project's selection into the project's skills
    directory of each installed provider its ``compatibility`` line names
    (R3.1), in the form ``homes.project_link`` says. One the home installs
    for that provider is skipped: the home has it (R3.2)."""
    chosen = project_selection(run)
    project = run.homes.project
    if chosen is None or project is None or run.errors:
        return
    form = homes.project_link(run.homes.host, project, run.homes.clone)
    cut: list[str] = []
    made = False
    for provider in run.homes.installed():
        if provider.name not in homes.PROJECT_SKILLS:
            continue
        place = homes.Place(PROJECT, project.joinpath(*homes.PROJECT_SKILLS[provider.name]), True)
        for name, skill in run.sources.skills.items():
            if provider.name not in skill.providers or name not in chosen.units:
                continue
            if name in selection.units and _has_place(provider, homes.SKILLS):
                run.left_out(provider, place, name, "the home has it")
            elif form.form == homes.FORM_NONE:
                run.left_out(provider, place, name, f"not linked from this side: {form.why}")
                if name not in cut:
                    cut.append(name)
            else:
                run.link(provider, place, name, run.homes.clone / name, relative=form.form == homes.FORM_RELATIVE)
                made = True
    if cut:
        run.notes.append(
            f"project: {', '.join(sorted(cut))} not linked into {project} ({form.why}); run "
            f"`setup.py {_windows_path(str(project))}` from Windows, whose junctions this side then keeps"
        )
    if made and form.form == homes.FORM_ABSOLUTE and form.why:
        run.notes.append(f"project: {form.why}")


def _windows_path(text: str) -> str:
    """``/mnt/d/proj`` as Windows names it, ``D:\\proj``; any other path as it is."""
    match = re.fullmatch(r"/mnt/([A-Za-z])(/.*)?", text)
    if match is None:
        return text
    return f"{match.group(1).upper()}:" + (match.group(2) or "\\").replace("/", "\\")


def _wsl_path(text: str) -> str:
    """``D:\\proj`` as WSL names it, ``/mnt/d/proj``; ``\\\\wsl.localhost\\Distro\\home\\me``
    as ``/home/me``; any other path as it is."""
    share = re.fullmatch(r"\\\\(?:wsl\.localhost|wsl\$)\\[^\\]+(\\.*)?", text, re.IGNORECASE)
    if share is not None:
        return (share.group(1) or "\\").replace("\\", "/")
    match = re.fullmatch(r"([A-Za-z]):(\\.*)?", text)
    if match is None:
        return text
    return f"/mnt/{match.group(1).lower()}" + (match.group(2) or "").replace("\\", "/").rstrip("/")


def fill_rules(run: Run) -> None:
    """Every rule directory into the rules place of each installed provider
    that has one: Claude Code (R2.2), those of the home's selection."""
    selection = home_selection(run)
    if selection is None:
        return
    rules = homes.rule_directories(run.homes.clone)
    for provider in run.homes.installed():
        if _has_place(provider, homes.RULES):
            place = provider.place(homes.RULES)
            for rule in rules:
                if rule.name in selection.units:
                    run.link(provider, place, rule.name, rule)
    fill_project_rules(run, selection, rules)


def fill_project_rules(run: Run, selection: definitions.Selection, rules: list[Path]) -> None:
    """Every rule of the project's selection copied into the project's
    ``.claude/rules/<name>/``, for Claude Code only (R4.1): a copy, not a
    link, so the project holds the rule's text. One the home installs is
    skipped (R4.2). ``Run.file`` does the rest."""
    chosen = project_selection(run)
    project = run.homes.project
    if chosen is None or project is None or run.errors:
        return
    for provider in run.homes.installed():
        if provider.name != homes.CLAUDE_CODE:
            continue
        for rule in rules:
            if rule.name not in chosen.units:
                continue
            place = homes.Place(PROJECT, project / ".claude" / "rules" / rule.name, True)
            if rule.name in selection.units and _has_place(provider, homes.RULES):
                run.left_out(provider, homes.Place(PROJECT, place.path.parent, True), rule.name, "the home has it")
                continue
            for name, text in rule_files(run, rule):
                digest = fsio.sha256(text.encode("utf-8"))
                run.file(provider, place, name, text, f"{GENERATED_PREFIX}rule-copy:{digest}")


def rule_files(run: Run, rule: Path) -> list[tuple[str, str]]:
    """The files of the clone's rule directory as (name, text): UTF-8 with a
    byte order mark taken off and CRLF made LF, as ``roles.join_text`` does."""
    found: list[tuple[str, str]] = []
    for path in paths.entries(rule):
        if path.name.startswith(".") or fsio.look(path).kind != fsio.FILE:
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            run.fail(f"{path}: cannot be copied into a project: {exc}")
            continue
        found.append((path.name, text.removeprefix("\ufeff").replace("\r\n", "\n")))
    return found


def roles_on(run: Run) -> bool:
    """Whether the roles are generated in this run: the home's effective
    ``install`` holds ``roles`` (see the module). Read once. A project's
    own roles (``definitions.project_roles``) are no part of this answer.
    A ``SetupError`` where an ``install`` is at fault."""
    if run._roles is None:
        home = definitions.home_install(_locations(run, None))
        on = home is not None and schema.ROLES_ITEM in home.value
        run._roles = (on, None if home is None else home.file)
    return run._roles[0]


def roles_report(run: Run) -> dict[str, Any] | None:
    """The report's ``roles``: whether they are on, and where the home's
    ``install`` is that says so; None where the run did not ask. Where the
    home's roles are off and the project has roles of its own, ``project``
    is the file of the project whose ``install`` lists them."""
    if run._roles is None:
        return None
    found: dict[str, Any] = {"on": run._roles[0], "file": None if run._roles[1] is None else str(run._roles[1])}
    if not run._roles[0] and run.homes.project is not None:
        try:
            held = project_roles_file(run)
        except SetupError:
            held = None
        if held is not None:
            found["project"] = str(held)
    return found


def process_alone_line(found: dict[str, Any] | None) -> str | None:
    """The line that says the home's roles are off, and why; None where
    they are on. Where the project has roles of its own it says so, with
    the file that lists them."""
    if found is None or found["on"]:
        return None
    where = found.get("file") or "any settings file"
    line = f"roles: not in `install` in {where}: the process alone"
    if found.get("project"):
        line += f"; the project has roles of its own, listed in `install` in {found['project']}"
    return line


def _locations(run: Run, project: Path | None) -> Locations:
    """The locations of the run, with or without its project. ``real_home``
    is the run's, so that whatever resolves the homes from them again reads
    the providers' variables exactly where the run did. What a generated
    text says of a home is taken from ``run.homes`` itself."""
    return Locations(home=run.homes.home, project=project, clone=run.homes.clone, real_home=not run.homes.scratch)


def fill_roles(run: Run) -> None:
    """The role definitions of each installed provider, into its agents
    place (R6.2). They are made from the user-level settings: a project's
    settings never reach a home's files. A home whose ``install`` lacks
    ``roles`` asks for none, and the stale sweep then removes those of an
    earlier run; a project with its own roles gets them through
    ``_fill_project_roles``."""
    try:
        if not roles_on(run):
            _fill_project_roles(run)
            return
    except SetupError as exc:
        run.fail(*exc.lines)
        return
    providers = [
        provider for provider in run.homes.installed()
        if provider.name in definitions.PROVIDERS and _has_place(provider, homes.AGENTS)
    ]
    where = _locations(run, None)
    try:
        built = definitions.build(where, [provider.name for provider in providers], run.homes)
    except SetupError as exc:
        run.fail(*exc.lines)
        return
    for provider in providers:
        place = provider.place(homes.AGENTS)
        for found in built:
            if found.provider == provider.name:
                run.file(provider, place, found.name, found.text, found.inputs, detail={
                    "definition": found.definition, "role": found.role, "model": found.model, "effort": found.effort,
                    **_cache(found),
                })


def project_roles_file(run: Run) -> Path | None:
    """The file whose ``install`` gives the project its own roles
    (``definitions.project_roles``); None where it has none. A ``SetupError``
    where an ``install`` is at fault."""
    where = _locations(run, run.homes.project)
    if not definitions.project_roles(where):
        return None
    held = [one for one in settings.install(where) if one.layer in settings.PROJECT_LAYERS]
    return held[-1].file


def project_dirs(run: Run) -> dict[str, dict[str, str]] | None:
    """The directory each skill's binding rows name, by provider
    (``definitions.skill_dirs``), for a project with roles of its own; None
    for any other run, whose rows name the home's. Read once."""
    if not run._dirs_read:
        where = _locations(run, run.homes.project)
        run._dirs = None
        if definitions.project_roles(where):
            run._dirs = {
                provider.name: definitions.skill_dirs(where, provider.name, run.sources.skills, run.homes)
                for provider in _entry_providers(run)
            }
        run._dirs_read = True
    return run._dirs


def _fill_project_roles(run: Run) -> None:
    """The definitions of a project with roles of its own (R5.2): every one
    of each installed provider, made from the shipped definitions and every
    settings layer, into the project's agents directory. A ``SetupError``
    where they cannot be made."""
    project = run.homes.project
    where = _locations(run, project)
    if project is None or not definitions.project_roles(where):
        return
    providers = _entry_providers(run)
    built = definitions.build(where, [provider.name for provider in providers], run.homes, project_dirs(run))
    for provider in providers:
        place = homes.Place(PROJECT, project / entry.PROJECT_AGENTS[provider.name], True)
        for found in built:
            if found.provider == provider.name:
                run.file(provider, place, found.name, found.text, found.inputs, detail={
                    "definition": found.definition, "role": found.role, "model": found.model,
                    "effort": found.effort, "level": PROJECT, **_cache(found),
                })


def _cache(found: definitions.Generated) -> dict[str, Any]:
    """The cache value of a definition that holds one, for its item; nothing
    for any other, so that their items and lines are what they were."""
    return {} if found.cache is None else {"cache": found.cache}


def _entry_providers(run: Run) -> list[homes.Provider]:
    return [provider for provider in run.homes.installed() if provider.name in definitions.PROVIDERS]


def _point(run: Run, provider: str, kind: str, role: str, how: str, item: Item | None = None, **more: Any) -> None:
    found: dict[str, Any] = {"provider": provider, "kind": kind, "role": role, "how": how}
    if item is not None:
        found.update({"file": item.name, "path": str(item.path), "bytes": item.size, "status": item.status})
    found.update(more)
    run.points.append(found)


def fill_entry(run: Run) -> None:
    """How a session becomes a role (R4.4, R4.5), for each installed
    provider, and what the project gets; see ``entry`` and the module.
    A home whose ``install`` lacks ``roles`` asks for none of it, and what an
    earlier run made is then stale: the files go with the sweep, the key and
    the block here; a project with its own roles runs the project path
    instead."""
    project = run.homes.project
    home = _locations(run, None)
    where = _locations(run, project)
    providers = _entry_providers(run)
    names = [provider.name for provider in providers]
    wanted_key = wanted_effort = wanted_block = False
    if run.errors:
        return  # the roles part said why; the same sources would say it here again
    try:
        on = roles_on(run)
    except SetupError as exc:
        run.fail(*exc.lines)
        return
    try:
        if on:
            wanted_key, wanted_effort, wanted_block = _fill_entry(
                run, home, where, providers, names,
            )
        elif definitions.project_roles(where):
            _fill_project_loaded(run, where, providers, names)
            default = entry.manager_default(where)
            run.project_facts.update({"manager_default": default, "starting_role": None})
            if default:
                run.project_facts["starting_role"] = entry.starting_role(where)
            wanted_key, wanted_effort, wanted_block = _project_default(run, where, providers, default)
    except SetupError as exc:
        run.fail(*exc.lines)
        return
    if project is not None and not run.errors:
        if not run.project_changed:
            _keys_left(run, project)
        # The effort first: it was set after the role, and the last member
        # taken out first gives back the bytes that were there.
        if not wanted_effort and run.project_changed:
            run.drop_json_key(project / entry.CLAUDE_SETTINGS, entry.EFFORT_KEY)
        if not wanted_key and run.project_changed:
            run.drop_json_key(project / entry.CLAUDE_SETTINGS, entry.AGENT_KEY)
        if not wanted_block:
            _old_codex_block(run, project / entry.CODEX_CONFIG)
        _trust_note(run, project)


def _trust_note(run: Run, project: Path) -> None:
    """R5.5: where Codex is among the providers and the run asks for a file
    of Codex's in the project (a definition in ``.codex/agents``, by either
    path, or the block), one line says Codex reads them only in a trusted
    project. Whether the project is trusted is not asked."""
    root = project / ".codex"
    if any(one.provider == definitions.CODEX and one.status != REMOVE and one.path.is_relative_to(root)
           for one in run.items):
        run.notes.append(TRUST_NOTE)


TRUST_NOTE = "Codex reads the role definitions and the Manager start only in a project you trust."


def _old_codex_block(run: Run, path: Path) -> None:
    """A block setup no longer asks for in the project's ``.codex/config.toml``.
    Where git tracks the file (R10.3) the block is the user's to remove: it is
    named with its lines, its record entry is forgotten, and the file is never
    edited. Where git does not, setup takes the block out as before. Where git
    could not be asked, the block and the record stay as they are."""
    key = run.roots.key(path)
    recorded = key is not None and run._recorded(key, "text", "blocks", entry.BLOCK_NAME) is not None
    span = None
    try:
        data = fsio.read_bytes(path) if fsio.look(path).kind == fsio.FILE else None
        if data is not None:
            blocks.check_text(data)
            span = blocks.scan(blocks.split_bom(data)[1], blocks.TOML).get(entry.BLOCK_NAME)
    except (SetupError, blocks.Refusal):
        pass
    if not (recorded or span is not None):
        return
    tracked = run.codex_tracked(path)
    if tracked is False:
        run.drop_block(path, entry.BLOCK_NAME)
        return
    if tracked is None:
        if run.project_facts.get("manager_default"):
            return   # the line of ``_fill_entry`` says it
        run.notes.append(
            f"project: {path}: git could not be asked whether it tracks the file, so setup's block there "
            "is left as it is"
        )
        return
    if recorded:
        run.plan.forget_block(path, name=entry.BLOCK_NAME)
    if span is not None:
        run.notice(
            f"project: {path}: lines {span[0] + 1}-{span[1]} are setup's old Codex block (git tracks the file, "
            "so setup never edits it): remove those lines"
        )


def _check_clashes(run: Run, made: list[entry.Made]) -> None:
    """A loaded role is a skill of the role's name: it may not be a skill
    the clone already has, nor one with a setup of its own."""
    loaded = sorted({one.role for one in made if one.kind == entry.LOADED})
    taken = set(run.sources.skills) | set(homes.OWN_SETUP_SKILLS)
    clashes = [role for role in loaded if role in taken]
    if clashes:
        raise SetupError(*[
            f"roles/{role}/role.toml: entry.load: the role would be installed as the skill {role}, and "
            + ("a skill of that name has a setup of its own" if role in homes.OWN_SETUP_SKILLS
               else f"the clone has a skill of that name ({role}/SKILL.md)")
            + "; rename one of the two, or set load = false"
            for role in clashes
        ])


def _fill_project_loaded(run: Run, where: Locations, providers: list[homes.Provider], names: list[str]) -> None:
    """The loaded-role skills of a project with roles of its own (R5.2),
    into each provider's project skills directory. No profile is made and
    nothing of the roles goes into a home."""
    project = run.homes.project
    made = entry.skills(where, names, run.homes, project_dirs(run), project=True)
    _check_clashes(run, made)
    for provider in providers:
        place = homes.Place(PROJECT, project / Path(*homes.PROJECT_SKILLS[provider.name]), True)  # type: ignore[operator]
        for one in made:
            if one.provider == provider.name and one.kind == entry.LOADED:
                _loaded_file(run, provider, place, one)


def _loaded_file(run: Run, provider: homes.Provider, place: homes.Place, one: entry.Made) -> None:
    """One file of a loaded role's skill, and its ``load`` point."""
    detail = {"entry": one.kind, "role": one.role}
    if one.name.endswith(entry.SKILL_FILE):
        detail.update({"model": one.model, "effort": one.effort, "tokens": one.tokens,
                       "limit_tokens": one.limit_tokens, "over_limit": one.over_limit})
    item = run.file(provider, place, one.name, one.text, one.inputs, detail=detail)
    if one.name.endswith(entry.SKILL_FILE):
        _point(run, provider.name, "load", one.role, entry.INVOKE[provider.name].format(role=one.role), item,
               model=one.model, effort=one.effort, tokens=one.tokens,
               limit_tokens=one.limit_tokens, over_limit=one.over_limit,
               provider_name=one.provider_name)


def _fill_entry(run: Run, home: Locations, where: Locations, providers: list[homes.Provider],
                names: list[str]) -> tuple[bool, bool, bool]:
    """Returns whether the project's ``agent`` key, its ``effortLevel`` key
    and its Codex block are wanted; the project follows the home."""
    project = run.homes.project
    made = [*entry.skills(home, names, run.homes), *entry.profiles(home, names, run.homes)]
    _check_clashes(run, made)

    starting = entry.start_roles(home)
    default = False
    if project is not None:
        default = entry.manager_default(where)
        run.project_facts.update({"manager_default": default, "starting_role": None})
        if default:
            run.project_facts["starting_role"] = entry.starting_role(where)
        # Only said, never generated: a fault here must not stop a run that
        # generates nothing from it.
        try:
            run.project_facts["loaded_roles"] = _loaded_differences(made, entry.skills(where, names, run.homes))
        except SetupError as exc:
            run.project_facts["loaded_roles"] = []
            run.notes.append(
                "loaded roles: what the project's settings make of their profiles cannot be worked out "
                f"({exc.lines[0]}); the loaded skills keep the user-level profiles in any case"
            )

    for provider in providers:
        name = provider.name
        if _has_place(provider, homes.SKILLS):
            place = provider.place(homes.SKILLS)
            for one in made:
                if one.provider == name and one.kind == entry.LOADED:
                    _loaded_file(run, provider, place, one)
        if name == definitions.CLAUDE_CODE and _has_place(provider, homes.AGENTS):
            # As documented, a session does not take the effort of the
            # definition it starts as, so the command names it (see ``entry``).
            efforts = entry.session_efforts(home, run.homes) if starting else {}
            for role in starting:
                session = efforts[role]
                _point(run, name, "start", role, entry.start_command(name, role, session.effort),
                       file=definitions.file_name(name, role), model=session.model, effort=session.effort,
                       no_effort=None if session.effort is not None else session.why)
        if name == definitions.CODEX and _has_place(provider, homes.PROFILES):
            place = provider.place(homes.PROFILES)
            for one in made:
                if one.kind == entry.PROFILE:
                    # What Codex writes into the profile after setup's part: carried over.
                    item = run.file(provider, place, one.name, one.text, one.inputs, detail={
                        "entry": one.kind, "role": one.role, "model": one.model, "effort": one.effort,
                    }, carry=True)
                    _point(run, name, "start", one.role, entry.start_command(name, one.role), item,
                           model=one.model, effort=one.effort)

    wanted_key = wanted_effort = wanted_block = False
    if project is None:
        return wanted_key, wanted_effort, wanted_block

    # The definitions the project's settings change, into the project.
    changed = entry.project_definitions(where, names, run.homes)
    for provider in providers:
        place = homes.Place(PROJECT, project / entry.PROJECT_AGENTS[provider.name], True)
        for found in changed:
            if found.provider == provider.name:
                run.file(provider, place, found.name, found.text, found.inputs, detail={
                    "definition": found.definition, "role": found.role, "model": found.model,
                    "effort": found.effort, "level": PROJECT, **_cache(found),
                })

    return _project_default(run, where, providers, default)


def _project_default(run: Run, where: Locations, providers: list[homes.Provider],
                     default: bool) -> tuple[bool, bool, bool]:
    """The starting role as the project's default (R5.4), where the settings
    ask for it: on Claude Code the keys ``agent`` and ``effortLevel``, on
    Codex the block at the head of the project's ``.codex/config.toml``. For
    a project with roles of its own the role's definition is the project's,
    and the way in is named: ``claude --agent`` in the project, a plain
    ``codex`` with the block. Returns whether the key, the effort and the
    block are wanted."""
    project = run.homes.project
    assert project is not None
    wanted_key = wanted_effort = wanted_block = False
    own = definitions.project_roles(where)
    if default:
        role = run.project_facts["starting_role"]
        left = False
        for provider in providers:
            if own and provider.name == definitions.CLAUDE_CODE:
                # As documented, a session does not take the effort of the
                # definition it starts as, so the command names it.
                session = entry.session_efforts(where, run.homes, project_dirs(run))[role]
                _point(run, provider.name, "start", role,
                       entry.start_command(provider.name, role, session.effort) + " in the project",
                       file=definitions.file_name(provider.name, role), model=session.model,
                       effort=session.effort, no_effort=None if session.effort is not None else session.why)
            if provider.name == definitions.CLAUDE_CODE and not run.project_changed:
                left = True   # the keys stay as they are (R6.1); ``fill_entry`` says so
            elif provider.name == definitions.CLAUDE_CODE:
                wanted_key = True
                item = run.json_key(provider, project / entry.CLAUDE_SETTINGS, entry.AGENT_KEY, role)
                _point(run, provider.name, "project-default", role,
                       f'"{entry.AGENT_KEY}": "{role}" in {entry.CLAUDE_SETTINGS}', status=item.status)
                wanted_effort = _project_effort(run, provider, where, role, item)
            elif provider.name == definitions.CODEX:
                path = project / entry.CODEX_CONFIG
                tracked = run.codex_tracked(path)
                if tracked is not False:
                    # R6.4: nothing is written into a file git tracks, or may track.
                    run.notice(
                        f"project: {path} " + (
                            "is tracked by git" if tracked else "was not checked: git could not be started, did not answer or failed"
                        ) + f", so setup writes nothing there: Codex sessions in the project will not start as {role}"
                    )
                    run.project_facts["codex_default"] = "tracked" if tracked else "unknown"
                    continue
                wanted_block = True
                _, content = entry.project_block(where, run.homes, project_dirs(run))
                taken_keys = _keys_outside(path, content)
                if taken_keys:
                    raise SetupError(*[
                        f"{path}: {key} is already set outside setup's block. {entry.MANAGER_DEFAULT_KEY} asks "
                        f"setup to set {key} for the starting role {role}, and a key cannot be set twice in "
                        "one TOML file, so setup writes nothing: your value stays in effect, and a Codex "
                        f"session in this project does not start as {role}. Remove the key from the file, or "
                        f"set {entry.MANAGER_DEFAULT_KEY} = false for this project, and run setup.py again"
                        for key in taken_keys
                    ])
                item = run.block(provider, path, entry.BLOCK_NAME, content, fileops.HEAD)
                item.detail.update({"role": role})
                if own:
                    _point(run, provider.name, "start", role, "a plain `codex` in the project", item)
                _point(run, provider.name, "project-default", role,
                       f"the block {entry.BLOCK_NAME} at the head of {entry.CODEX_CONFIG}, read in a trusted "
                       "project only; it wins over a profile", status=item.status)
        if wanted_key or left or wanted_block:
            run.ignore_always()
    return wanted_key, wanted_effort, wanted_block


def _keys_left(run: Run, project: Path) -> None:
    """A run that did not change the project's choices leaves the keys
    ``agent`` and ``effortLevel`` of ``.claude/settings.json`` as they are,
    set or not, with their record entries (R6.1): the file is tracked, and
    the home's mapping of one user is not the project's. One note, where the
    project's default would set them or the record holds one."""
    if not any(provider.name == definitions.CLAUDE_CODE for provider in _entry_providers(run)):
        return
    key = run.roots.key(project / entry.CLAUDE_SETTINGS)
    held = [name for name in (entry.AGENT_KEY, entry.EFFORT_KEY) if run._recorded(key, "json", "keys", name)]
    if not (held or run.project_facts.get("manager_default")):
        return
    run.notes.append(
        f"{entry.CLAUDE_SETTINGS}: {entry.AGENT_KEY} and {entry.EFFORT_KEY} are left as they are, and so is what "
        f"the record holds of them: this run did not write {_locations(run, project).project_file}, and only a run that "
        f"writes it, or one given --manager-default or --no-manager-default, sets, changes or removes them"
    )


def _project_effort(run: Run, provider: homes.Provider, where: Locations, role: str, agent: Item) -> bool:
    """The effort of a Claude Code session in the project, beside the key
    that makes it start as ``role``: ``effortLevel``, by the rules of that
    key. Whether the key is wanted; where it is not, a note says why, and
    what setup set earlier is taken out by the caller."""
    session = entry.session_efforts(where, run.homes)[role]
    facts = {"role": role, "model": session.model, "effort": session.effort, "setting": None, "why": None}
    run.project_facts["session_effort"] = facts
    start = f"`{entry.start_command(provider.name, role, session.effort)}`"
    path = where.project / entry.CLAUDE_SETTINGS  # type: ignore[operator]
    recorded = run._recorded(run.roots.key(path), "json", "keys", entry.EFFORT_KEY)
    if agent.status in _BLOCKING:
        # The file cannot be written (it is not JSON, say): the key that
        # names the role says so, once. Nothing is written in this run, and
        # what the record holds of the effort stays.
        facts["why"] = f"the key {entry.AGENT_KEY} cannot be set"
        return recorded is not None
    if agent.status == EDITED:
        # The key that names the role has a value that is not setup's
        # (the user's own, or setup's changed by hand) and is kept, so the
        # project's sessions do not start as the role, and its effort is
        # not theirs to run at. None is set for the first time, and one
        # setup set earlier is left exactly as it is: neither set to the
        # role's effort of today nor taken out.
        facts["why"] = (
            f"the key {entry.AGENT_KEY} has a value that is not setup's and is kept, so the project's sessions "
            f"do not start as {role}"
        )
        if recorded is None:
            run.notes.append(
                f"{entry.CLAUDE_SETTINGS}: {entry.EFFORT_KEY} is not set: {facts['why']}. It is set with the key "
                f"{entry.AGENT_KEY}"
            )
            return False
        run.notes.append(
            f"{entry.CLAUDE_SETTINGS}: {entry.EFFORT_KEY} is left as it is: {facts['why']}. Setup set it earlier, "
            f"and sets or removes it again with the key {entry.AGENT_KEY}"
        )
        return True
    if session.setting is None:
        facts["why"] = session.why
        left = (
            "a session in the project runs at the effort of the model's default or of your own settings"
            if session.effort is None else
            f"a session in the project starts as {role} at another effort than the role's unless it is started "
            f"with {start}, or `/effort {session.effort}` is given in it"
        )
        run.notes.append(f"{entry.CLAUDE_SETTINGS}: {entry.EFFORT_KEY} is not set for {role}: {session.why}. So {left}")
        return False
    facts["setting"] = session.setting
    item = run.json_key(provider, path, entry.EFFORT_KEY, session.setting)
    _point(run, provider.name, "project-effort", role,
           f'"{entry.EFFORT_KEY}": "{session.setting}" in {entry.CLAUDE_SETTINGS}', status=item.status)
    return True


def _loaded_differences(user: list[entry.Made], theirs: list[entry.Made]) -> list[dict[str, Any]]:
    """Each loaded role whose profile the project's settings change: the
    loaded skill is user-level and keeps the user-level one, and nothing
    is generated for it in the project; see the module."""
    mine = {(one.provider, one.role): one for one in user
            if one.kind == entry.LOADED and one.name.endswith(entry.SKILL_FILE)}
    found = []
    for one in theirs:
        held = mine.get((one.provider, one.role))
        if held is None or one.kind != entry.LOADED or not one.name.endswith(entry.SKILL_FILE):
            continue
        if (one.model, one.effort) != (held.model, held.effort):
            found.append({
                "provider": one.provider, "role": one.role,
                "model": one.model, "effort": one.effort,
                "loaded_model": held.model, "loaded_effort": held.effort,
            })
    return found


def _keys_outside(path: Path, content: str) -> list[str]:
    """The keys of setup's block that the TOML file at ``path`` already
    sets at its top level outside setup's blocks. A file that cannot be
    read as TOML is left to the plan, which refuses it by its own rule."""
    try:
        if fsio.look(path).kind != fsio.FILE:
            return []
        data = fsio.read_bytes(path)
        outside = "\n".join(blocks.outside(data, blocks.TOML))
        there = tomllib.loads(outside)
        mine = tomllib.loads(content)
    except (SetupError, blocks.Refusal, UnicodeDecodeError, ValueError, RecursionError):
        return []
    return [key for key in mine if key in there]


MODEL_LIST_PART = "model-list"


def fill_model_list(run: Run) -> None:
    """Where this run renders the Codex home, a note on the models Codex's own
    list offers and the dictionary lacks (R3.2), as ``--check`` warns of them
    (R3.1). It writes nothing and never changes the exit code: a list that
    cannot be read is one line, also where the program is not on PATH.
    Nothing is started where Codex is not installed (no home, no program) or
    the dictionary names no list command. The note goes last of all notes."""
    if run.errors:
        return
    provider = run.homes.provider(homes.CODEX)
    if not provider.installed:
        return
    try:
        known = dictionary.load_all(_locations(run, None)).get(provider.name)
    except SetupError:
        return
    if known is None or known.model_list.command is None:
        return
    reading, found = modellist.check(known, homes.child_environment(run.homes), program_file=provider.program_file)
    if found is None:
        run.model_notes.append(f"{provider.name}: {reading.describe()}")
        return
    line = found.new_models_line()
    if line is not None:
        run.model_notes.append(f"{provider.name}: {line} (the dictionary may be stale)")


PARTS: tuple[Part, ...] = (
    Part("skills", fill_skills),
    Part("rules", fill_rules),
    Part("roles", fill_roles),
    Part("entry", fill_entry),
    Part("codex-settings", codexsettings.fill),   # its options: setup.py
    Part(MODEL_LIST_PART, fill_model_list),
)


# --- The run --------------------------------------------------------------------

def execute(found: homes.Homes, sources: Sources, options: Any = None, *, dry_run: bool = False,
            follow: bool = False, overwrite_edited: bool | frozenset[str] | set[str] = False, parts: tuple[Part, ...] | None = None,
            stamp: str | None = None, clone_warning: str | None = None, project_changed: bool = True) -> Outcome:
    """Fill one plan from the parts, then show it (``dry_run``) or apply it.
    The sources are valid and the clone was checked before this is called;
    ``clone_warning`` is the line that check gave, or None (``homes.clone_warning``).
    ``project_changed`` says whether this run changed the project's choices
    (wrote its ``.agents/workflow.toml``); while it is false the project's
    ``agent`` and ``effortLevel`` keys are left as they are (R6.1)."""
    recovered: fileops.Result | None = None
    before = _bytes_of(found.project / entry.CLAUDE_SETTINGS) if found.project is not None else None
    if not dry_run:
        # What an interrupted run left is settled before anything looks at
        # the disk to decide what to do: a file it left under a temporary
        # name is no file of the user's.
        recovered = fileops.recover(found.roots(), follow_config_symlinks=follow)
    run = Run(found, sources, options, follow=follow, overwrite=overwrite_edited, stamp=stamp,
              project_changed=project_changed)
    if recovered is not None and recovered.changed:
        run.notes.extend([*recovered.lines, *recovered.notes])
    for part in PARTS if parts is None else parts:
        part.fill(run)
    run.sweep()
    run.finish()

    everything = [*run.items, *run.stale]
    errors = [*run.errors, *[item.says for item in everything if item.status in _BLOCKING]]
    result: fileops.Result | None = None
    if not errors:
        try:
            result = run.plan.run(dry_run)
        except fileops.PlanError as exc:
            errors = list(exc.lines)
    for call in run.settled:
        call()
    needs_flag = sum(1 for item in everything if item.status in (NEEDS_FLAG, EDITED))
    needs_flag += len(result.edited) if result is not None else 0
    code = EXIT_ERROR if errors else EXIT_NEEDS_FLAG if needs_flag else 0
    report = _report(run, result, errors, dry_run, code)
    report["clone_warning"] = clone_warning
    written: list[Path] = []
    if found.project is not None and not dry_run and not errors:
        path = found.project / entry.CLAUDE_SETTINGS
        if _bytes_of(path) != before:
            written.append(path)
    named = (KEY, BLOCK, codexsettings.KIND)    # the kinds named inside a file
    edited = tuple(
        (edited_id(item.path, item.name if item.kind in named else None),
         str(item.path) if item.kind not in named else f"{item.name} in {item.path}")
        for item in run.items if item.status == EDITED
    )
    return Outcome(report, code, errors, tuple(written), edited)


def _bytes_of(path: Path) -> bytes | None:
    """The bytes of a file, or None where there is none or it cannot be read."""
    try:
        return fsio.read_bytes(path) if fsio.look(path).kind == fsio.FILE else None
    except (SetupError, OSError):
        return None


def _count(items: list[Item], *statuses: str, kind: str | None = None) -> int:
    return sum(1 for item in items if item.status in statuses and kind in (None, item.kind))


def _report(run: Run, result: fileops.Result | None, errors: list[str], dry_run: bool, code: int) -> dict[str, Any]:
    found = run.homes
    providers = []
    for provider in found.providers:
        places = []
        for place in provider.places:
            items = [item for item in run.items if item.provider == provider.name and item.place == place.name]
            if not items:
                continue
            standing = run.standing(place.path) if any(item.key is not None for item in items) else None
            whole = [item for item in items if item.whole_place]
            places.append({
                "name": place.name,
                "path": str(place.path),
                "standing": None if standing is None else standing.kind,
                "skipped": whole[0].says if whole else None,
                "items": [item.as_json() for item in items],
            })
        providers.append({
            "name": provider.name, "installed": provider.installed, "home": str(provider.home),
            "program": provider.program, "places": places,
        })
    everything = [*run.items, *run.stale]
    changed = bool(result and result.changed)
    counts = {
        # Links.
        "create": _count(run.items, CREATE, kind=LINK),
        "up_to_date": _count(run.items, UP_TO_DATE, kind=LINK),
        "remove": _count(run.stale, REMOVE, kind=LINK),
        "forget": _count(run.stale, FORGET),
        "kept": _count(run.stale, KEPT),
        # Generated files.
        "file_write": _count(run.items, *_WRITES, kind=FILE),
        "file_up_to_date": _count(run.items, UP_TO_DATE, kind=FILE),
        "file_remove": _count(run.stale, REMOVE, kind=FILE),
        "file_release": _count(run.stale, RELEASE, kind=FILE),
        "edited": _count(run.items, EDITED),
        # A project's default: the key and the block.
        "default_write": _count(run.items, *_WRITES, kind=KEY) + _count(run.items, *_WRITES, kind=BLOCK),
        "default_remove": _count(run.stale, REMOVE, kind=KEY) + _count(run.stale, REMOVE, kind=BLOCK),
        # The user's Codex config: the blocks of ``codexsettings``.
        "codex_settings_write": _count(run.items, *_WRITES, kind=codexsettings.KIND),
        "codex_settings_remove": _count(run.stale, REMOVE, kind=codexsettings.KIND),
        # Both.
        "skipped": _count(everything, SKIPPED),
        "needs_flag": _count(everything, NEEDS_FLAG),
        "conflict": _count(everything, CONFLICT),
        "error": _count(everything, ERROR) + len(run.errors),
    }
    generated = [
        {
            "provider": item.provider, "definition": item.detail.get("definition"), "role": item.detail.get("role"),
            "file": item.name, "bytes": item.size, "model": item.detail.get("model"),
            "effort": item.detail.get("effort"), "status": item.status,
            "level": PROJECT if item.project else "home",
            **({"cache": item.detail["cache"]} if "cache" in item.detail else {}),
        }
        for item in run.items if item.kind == FILE and "definition" in item.detail
    ]
    home_roles = roles_report(run)
    project = None
    if found.project is not None:
        project = {
            "path": str(found.project),
            "roles": home_roles,
            "manager_default": run.project_facts.get("manager_default"),
            "starting_role": run.project_facts.get("starting_role"),
            "session_effort": run.project_facts.get("session_effort"),
            "loaded_roles": list(run.project_facts.get("loaded_roles") or []),
            "items": [
                {**item.as_json(), "provider": item.provider, "name": _project_name(found.project, item)}
                for item in run.items if item.project
            ],
        }
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "dry_run": dry_run,
        "applied": bool(result and result.applied),
        "changed": changed,
        "exit_code": code,
        "side": found.host.side,
        "home": str(found.home),
        "clone": str(found.clone),
        "clone_warning": None,
        "roles": home_roles,
        "providers": providers,
        "definitions": generated,
        "entry_points": list(run.points),
        "project": project,
        "stale": [item.as_json() for item in run.stale],
        "plan": list(result.lines) if changed else [],
        "notes": [*run.notes, *(result.notes if result else []), *run.model_notes],
        "errors": list(errors),
        "counts": counts,
    }
    report["summary"] = _summary(report)
    return report


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _summary(report: dict[str, Any]) -> str:
    counts = report["counts"]
    left = []
    if counts["skipped"]:
        left.append(f"{counts['skipped']} skipped (each is listed as skipped, with the reason)")
    if counts["kept"]:
        left.append(f"{counts['kept']} kept")
    if counts["needs_flag"]:
        left.append(f"{counts['needs_flag']} skipped that {FOLLOW_OPTION} would write")
    if counts["edited"]:
        left.append(f"{counts['edited']} edited by hand and kept, which {OVERWRITE_OPTION} would replace")
    tail = "".join(f"; {text}" for text in left)
    files = counts["file_write"] or counts["file_remove"] or counts.get("file_release")
    released = counts.get("file_release") or 0
    defaults = counts.get("default_write") or counts.get("default_remove")
    if report["errors"]:
        stopped = []
        if counts["conflict"]:
            stopped.append(_plural(counts["conflict"], "conflict"))
        if counts["error"] or not stopped:
            stopped.append(_plural(counts["error"] or len(report["errors"]), "error"))
        return f"stopped: {', '.join(stopped)}; nothing was written"
    if not report["changed"]:
        return f"{fileops.UP_TO_DATE}; nothing was written{tail}"
    # A link made where a link of the user's was (the plan's "replace link"
    # lines) is one of the links created: said, so that the two numbers are
    # not read as "nothing was taken away".
    swapped = sum(1 for line in report.get("plan") or [] if line.startswith("replace link "))
    dry = bool(report["dry_run"])
    instead = f" ({swapped} of them in place of a link that {'is' if dry else 'was'} there)" if swapped else ""
    made = f"{_plural(counts['create'], 'link')} created{instead}, {counts['remove']} removed"
    if files:
        made += f"; {_plural(counts['file_write'], 'file')} written, {counts['file_remove']} removed"
        if released:
            made += f", {released} left as yours with setup's part taken out"
    if defaults:
        made += f"; {_plural(counts['default_write'], 'project default')} set, {counts['default_remove']} removed"
    codex = counts.get("codex_settings_write") or counts.get("codex_settings_remove")
    if codex:
        made += (f"; {_plural(counts['codex_settings_write'], 'block')} of Codex settings written, "
                 f"{counts['codex_settings_remove']} removed")
    if report["dry_run"]:
        made = f"would create {_plural(counts['create'], 'link')}{instead} and remove {counts['remove']}"
        if files:
            made += f", write {_plural(counts['file_write'], 'file')} and remove {counts['file_remove']}"
            if released:
                made += f", and take setup's part out of {released}, left as yours"
        if defaults:
            made += f", set {_plural(counts['default_write'], 'project default')} and remove {counts['default_remove']}"
        if codex:
            made += (f", write {_plural(counts['codex_settings_write'], 'block')} of Codex settings and remove "
                     f"{counts['codex_settings_remove']}")
        return f"dry run: {made}; nothing was written{tail}"
    return f"done: {made}{tail}"


_WORDS = {
    UP_TO_DATE: "up to date", CREATE: "create", UPDATE: "update", REPLACE: "replace", EDITED: "kept",
    REMOVE: "remove", FORGET: "forget", KEPT: "kept", RELEASE: "left as yours",
    SKIPPED: "skipped", NEEDS_FLAG: f"skipped, needs {FOLLOW_OPTION}", CONFLICT: "conflict", ERROR: "error",
}


def report_lines(report: dict[str, Any]) -> list[str]:
    """The report as text: each provider and place, the stale links, the
    plan, and one line that sums it up."""
    lines = []
    if report["dry_run"]:
        lines.append("dry run: nothing is changed")
    lines.append(f"clone: {report['clone']}")
    if report.get("clone_warning"):
        lines.append(f"  warning: {report['clone_warning']}")
    off = process_alone_line(report.get("roles"))
    if off is not None:
        lines.append(off)
    for provider in report["providers"]:
        if not provider["installed"]:
            lines.append(
                f"{provider['name']}: not installed (no {provider['program']} on PATH and no home at "
                f"{provider['home']}); nothing is installed for it"
            )
            continue
        lines.append(f"{provider['name']}: {provider['home']}")
        for place in provider["places"]:
            lines.append(f"  {place['name']}: {place['path']}")
            rest = []
            for item in place["items"]:
                if place["skipped"] is not None and item["says"] == place["skipped"]:
                    rest.append(item)
                else:
                    lines.append(f"    {item['name']}: {_shown(item)}")
            if rest:
                done = "written" if rest[0].get("kind") == FILE else "linked"
                lines.append(f"    {_WORDS[rest[0]['status']]}: {place['skipped']}")
                lines.append(f"    not {done} here: {', '.join(item['name'] for item in rest)}")
    if report.get("entry_points"):
        lines.append("entry points:")
        for point in report["entry_points"]:
            lines.append(f"  {_point_line(point)}")
    project = report.get("project")
    if project is not None:
        lines.append(f"project: {project['path']}")
        if project["manager_default"] is not None:
            role = project["starting_role"]
            lines.append(
                f"  {entry.MANAGER_DEFAULT_KEY}: "
                + (f"true; a session in the project starts as {role}" if project["manager_default"] else
                   "false; no starting role is set for the project")
            )
        if not project["items"] and off is None:
            lines.append("  nothing is generated for it: its settings change no role definition")
        for item in project["items"]:
            lines.append(f"  {item['name']}: {_shown(item)}")
        for one in project.get("loaded_roles") or []:
            lines.append(
                f"  loaded role {one['role']} on {one['provider']}: the project's settings give it "
                f"{_profile(one)}, and the loaded skill keeps "
                f"{_profile({'model': one['loaded_model'], 'effort': one['loaded_effort']})}: it is installed at the "
                "user level, where a provider's own skill wins over a project's of the same name, so nothing is "
                "generated for it here"
            )
    if report["stale"]:
        lines.append("no longer installed:")
        for item in report["stale"]:
            # A settings file may hold two keys of setup's: said which.
            part = f": key {item['name']}" if item.get("kind") == KEY else ""
            lines.append(f"  {item['key']}{part}: {_shown(item)}")
    lines.append("plan:")
    if report["errors"]:
        lines.append("  none: the run stopped before the plan")
    else:
        lines.extend(f"  {line}" for line in (report["plan"] or [report.get("plan_empty", fileops.UP_TO_DATE)]))
    lines.extend(f"note: {note}" for note in report["notes"])
    lines.append(report["summary"])
    return lines


def _project_name(project: Path, item: Item) -> str:
    """A project's item as the report names it: the file, by its path in
    the project, and for a key or a block which one."""
    try:
        name = item.path.relative_to(project).as_posix()
    except ValueError:
        name = str(item.path)
    if item.kind == KEY:
        return f"{name}: key {item.name}"
    if item.kind == BLOCK:
        return f"{name}: block {item.name}"
    return name


def _profile(found: dict[str, Any]) -> str:
    effort = f", effort {found['effort']}" if found.get("effort") is not None else ", no effort setting"
    # Only a definition that holds a cache value has the key.
    cache = f", cache {found['cache']}" if found.get("cache") is not None else ""
    return f"model {found['model']}{effort}{cache}"


def _point_line(point: dict[str, Any]) -> str:
    what = {
        "load": "load {role} into a session: {how}",
        "start": "start a session as {role}: {how}",
        "project-default": "a session in the project starts as {role}: {how}",
        "project-effort": "a session in the project runs at the effort of {role}: {how}",
    }[point["kind"]].format(**point)
    more = []
    if point.get("file"):
        more.append(point["file"])
    if point.get("bytes") is not None:
        more.append(f"{point['bytes']:,} bytes")
    if point.get("tokens") is not None:
        more.append(f"about {point['tokens']:,} tokens")
    if point.get("model"):
        more.append(_profile(point))
    line = f"{point['provider']}: {what}" + (f" ({'; '.join(more)})" if more else "")
    if point.get("no_effort"):
        line += f"; no --effort: {point['no_effort']}"
    if point.get("over_limit"):
        line += (
            f"; LONG: after a compaction {point['provider_name']} keeps the first {point['limit_tokens']:,} tokens of "
            "an invoked skill, so the end of this one is likely to be cut"
        )
    return line


def _shown(item: dict[str, Any]) -> str:
    says = item["says"]
    path = item["path"]
    if says.startswith(f"{path}: "):
        says = says[len(path) + 2:]  # the line already names the path
    if item.get("kind") == FILE and item.get("bytes") is not None and item.get("model"):
        says = f"{says} ({item['bytes']:,} bytes; {_profile(item)})"
    elif item.get("kind") == FILE and item.get("bytes") is not None and "entry" in item:
        says = f"{says} ({item['bytes']:,} bytes)"
    return f"{_WORDS[item['status']]}: {says}"
