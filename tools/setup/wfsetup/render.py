"""What ``render`` installs, as parts that fill one plan.

How the command uses it

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

    The parts now: ``migrate`` (R6.11: what a v1 install left, removed with
    ``--migrate-v1``; it plans before the first link, see ``migrate``),
    ``skills`` (R6.2), ``rules`` (R2.2), ``roles`` (R6.2:
    each provider's role definitions, built by ``definitions``) and
    ``entry`` (R4.4, R4.5: how a session becomes a role, built by ``entry``,
    and what a project gets).

The project (``--project``)
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
    They are recorded in the project's record, swept from it like a home's
    files, and the generated files are listed in the project's ignore
    block. The key and the block are not: they are setup's part of a file
    the project owns and may commit, and an ignore entry would hide the
    whole file. A project's path is the project's whichever side of the
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
    whose keys are all ones Codex writes itself (what ``uninstall``
    leaves) is written over, with setup's text before what it holds, and
    not a conflict; any other file there is. A key after setup's part
    that Codex does not write itself is named in the profile's line.
    The record keeps the hash of setup's own part beside the hash of the
    whole file. A stale profile with something after setup's part is
    ``release``: setup's part is taken out and the rest left, as yours.
    ``inputs`` goes into the record with the file's hash. It starts with
    ``GENERATED_PREFIX``, which is how the stale sweep knows a file is one
    ``render`` generates and not, say, a settings file ``init`` wrote.

Stale files
    A generated file in the record that no part asked for is removed when it
    still holds what setup wrote, forgotten when it is gone, and kept and
    reported when it was edited. ``--no-roles`` asks for no role definition,
    so the definitions of an earlier run are stale under it and go the same
    way: the homes then hold the process alone.

Whether the roles are generated (``roles``)
    ``--no-roles`` turns them off for the run, in the home and the project.
    Without it the setting ``roles.enabled`` decides: for the home from the
    user-level settings, for the project from the project's (its files over
    the user's). A project gets roles only where the home has them: its
    definitions replace some of the home's, and its starting role is a
    definition of the home's. Off by the setting is exactly off by the
    option, and the report says which it was.

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

Stale links
    After the parts, every link the user-level record holds that no part
    asked for is one ``render`` would no longer make: its skill left the
    clone, or its compatibility line no longer names that provider, or the
    provider is gone. It is removed when it still points where setup pointed
    it, forgotten when it is no longer there, and kept and reported when the
    user changed it. A link in a place this run does not write is left to
    the run that does.

Nothing is written when there is a conflict or an error in the plan: the
report is made, ``Outcome.errors`` holds one line per conflict, and the plan
is not run. A failure while the plan is applied is another matter: it leaves
``execute`` as the ``SetupError`` of ``fileops``, which says how many changes
were made; they are recorded, the next run goes on, and ``uninstall`` undoes
them.

Exit codes
    0                 done, or nothing to do
    2                 an error, or a conflict (``errors.EXIT_ERROR``)
    EXIT_NEEDS_FLAG   everything else was done (or would be, in a dry run),
                      and at least one path was left that an option would
                      write: a path ``--follow-config-symlinks`` would
                      write, or a generated file, a key or a block that
                      was edited by hand or is not setup's, which
                      ``--overwrite-edited`` would replace, or a v1 copy or
                      link the migration kept, which ``--remove-stale``
                      would remove (``migrate.left``)
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import blocks, carried, definitions, dictionary, entry, fileops, fsio, homes, jsonkeys, modellist, paths, settings
from . import codexsettings
from . import migrate
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

# Where a project's items are, in an item's ``place``.
PROJECT = "project"

# How the ``inputs`` of every file ``render`` generates starts.
GENERATED_PREFIX = "render:"

FOLLOW_OPTION = "--follow-config-symlinks"
OVERWRITE_OPTION = "--overwrite-edited"
NO_ROLES_OPTION = "--no-roles"
ROLES_KEY = "roles.enabled"
MIGRATE_OPTION = "--migrate-v1"
# Why the roles are off, in ``Roles``: the option of this run, the setting,
# or (for a project) the home's roles being off.
OFF_BY_OPTION = "option"
OFF_BY_SETTING = "setting"
OFF_BY_HOME = "home"
# The migration part is ``migrate``, in ``PARTS``. False only in a setup
# without it: the hint below then says that the option is not there.
MIGRATION_AVAILABLE = True


def migration_hint() -> str:
    """The line that follows the conflicts: what removes a v1 install."""
    if MIGRATION_AVAILABLE:
        return (
            f"where a conflict is what an earlier (v1) install left, a copy or a link to one, "
            f"`render {MIGRATE_OPTION} --dry-run` shows what migration would remove; anything else is "
            "yours to move away before render links there"
        )
    return (
        f"where a conflict is what an earlier (v1) install left, a copy or a link to one, removing it is "
        f"the work of `render {MIGRATE_OPTION}`, which this version of setup does not have yet; until "
        "then move it away yourself, and render links there on the next run"
    )


@dataclass
class Item:
    """One link or generated file ``render`` looked at."""

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
    """One thing ``render`` installs; see the module."""

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


_fold = paths.fold_key


class Run:
    """One run of ``render``: the homes, the sources, the record as it is,
    and the plan the parts fill."""

    def __init__(self, found: homes.Homes, sources: Sources, options: Any = None, *, follow: bool = False,
                 overwrite: bool = False, stamp: str | None = None) -> None:
        self.homes = found
        self.sources = sources
        self.options = options
        self.follow = follow
        self.overwrite = overwrite
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
        self._roles: Roles | None = None           # whether the roles are generated; see ``roles``
        self._disabled: frozenset[str] | None = None   # what setup.disabled keeps out; see ``disabled``
        self._disabled_read = False
        self.notes: list[str] = []                 # what a part says beside its items; printed as notes
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
            around = None if self.in_project(directory) else migrate.repository_around(directory, self.homes.clone)
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

    def link(self, provider: homes.Provider, place: homes.Place, name: str, target: Path,
             own_setup: bool = False) -> Item:
        """Ask for the link ``place/name`` to ``target``; see the module."""
        path = place.path / name
        item = Item(name, path, CREATE, "", provider=provider.name, place=place.name,
                    target=self.roots.target_key(str(target)))
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
        if base is not None and base.get("kind") != "link":
            base = None  # a link or a directory of the user's that setup removed: not a link setup made
        if entry.kind == homes.UNKNOWN:
            return settle(ERROR, f"{path}: {entry.describe()}")
        # What the migration part removes there in this same plan (a v1
        # link or copy) is not in the way; what it keeps is, and is named.
        cleared = migrate.cleared(self, path)
        if cleared is not None:
            item.says = f"link to {item.target}, in place of what migration removes there ({cleared})"
        elif entry.kind == homes.PLAIN:
            return settle(CONFLICT, migrate.conflict(self, path) or f"{path}: {entry.describe()}, and setup did not make it")
        elif entry.kind != homes.ABSENT:
            if base is None:
                return settle(
                    CONFLICT, migrate.conflict(self, path) or f"{path}: {entry.describe()}, and setup did not make it"
                )
            try:
                recorded = self.roots.target_text(base["target"])
            except (SetupError, KeyError, TypeError):
                return settle(CONFLICT, f"{path}: {entry.describe()}; the record's entry for it cannot be read")
            if not fsio.same_target(entry.target or "", recorded):
                return settle(
                    CONFLICT,
                    f"{path}: {entry.describe()}; setup made it a link to {recorded}, and it was changed since",
                )
            if fsio.same_target(recorded, str(target)):
                settle(UP_TO_DATE, f"linked to {item.target}")
        if item.status == CREATE and not item.says:
            item.says = f"link to {item.target}"
        # An up-to-date link is asked for as well: the plan then checks it
        # against the disk once more, and changes nothing.
        self.plan.create_link(path, target)
        return item

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
            # What ``uninstall`` (or a sweep) left of setup's file: the part
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
            if not self.overwrite:
                return settle(
                    EDITED,
                    f"edited by hand since setup wrote it, and kept; {OVERWRITE_OPTION} backs it up and replaces "
                    "it, or remove the file and run render again",
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
            if not self.overwrite:
                item.status, item.says = EDITED, (
                    f"edited by hand since setup wrote it, and kept; {OVERWRITE_OPTION} backs it up and replaces "
                    "it, keeping every key of it that is not setup's, or remove the file and run render again"
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
                if not self.overwrite:
                    item.status = EDITED
                    item.says = (
                        f"changed by hand since setup set it (it is {was}, setup set {shown}), and kept; "
                        f"{OVERWRITE_OPTION} sets it again, or remove the key and run render again"
                    )
                    return item
                item.status, item.says = REPLACE, f"changed by hand since setup set it (it was {was}); set to {shown} again"
            elif name in current and known is None:
                # A value setup did not write: the user's, until they say otherwise.
                was = json.dumps(current[name], ensure_ascii=False)
                if not self.overwrite:
                    item.status = EDITED
                    item.says = (
                        f"is {was}, which setup did not set, and kept: setup does not replace a value of yours, so "
                        f"it is not set to {shown}. {OVERWRITE_OPTION} sets it, and {was} is put back when setup "
                        "takes its key out; or remove the key and run render again"
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
            item.says = "write, in a new file"
        elif wanted == data:
            item.status, item.says = UP_TO_DATE, "as generated" + (
                "" if known is not None else "; the record did not hold the block, and takes it up"
            )
        elif there is None:
            item.says = f"write, at the {'head' if place == fileops.HEAD else 'end'} of the file"
        elif known is not None and not blocks.as_written(data, there, known.get("sha256")):
            if not self.overwrite:
                item.status = EDITED
                item.says = (
                    f"edited by hand since setup wrote it, and kept; {OVERWRITE_OPTION} backs the file up and "
                    "writes the block again, or remove the block with its markers and run render again"
                )
                return item
            item.status, item.says = REPLACE, "edited by hand since setup wrote it; the file is backed up and the block written again"
            policy = {"replace": fileops.EDITED}   # the plan refuses an edited block unless told
        elif known is None:
            # Setup's markers with other text between them than setup would
            # write, and no record of the block: the user's text.
            if not self.overwrite:
                item.status = EDITED
                item.says = (
                    "setup's markers are in the file with other text between them than setup writes, and the "
                    f"install record does not hold the block: kept as it is. {OVERWRITE_OPTION} backs the file up "
                    "and writes the block in its place, or take the markers out and run render again"
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
            item = Item(path.name, path, REMOVE, "", key=key, target=entry.get("target"))
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
            elif seen.kind == fsio.LINK and fsio.same_target(seen.target or "", recorded):
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

    def _writes_into(self, directory: Path) -> bool:
        """Whether this run writes into the place ``directory`` as it is."""
        if not _is_directory(directory):
            return False
        standing = self.standing(directory)
        if standing.kind == homes.UNKNOWN or not standing.writes or (standing.through_link and not self.follow):
            return False
        return self.in_clone(directory) is None

    def finish(self) -> None:
        """After the sweep: the project's ignore block (R6.6), and the
        directories of setup's that this run leaves empty."""
        if self.errors:
            return
        project = self.homes.project
        if project is not None:
            def entry_of(item: Item) -> str:
                return item.path.relative_to(project).as_posix()

            add = sorted({entry_of(item) for item in self.items if item.project and item.kind == FILE})
            remove = sorted({
                entry_of(item) for item in self.stale
                if item.project and item.kind == FILE and item.status in (REMOVE, FORGET)
            } - set(add))
            held = self.record.project is not None and self.record.project.on_disk
            if add or remove or held or self._ignore_always:
                self.plan.ignore(add=add, remove=remove, replace=fileops.ANY if self.overwrite else fileops.OWN)
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


def disabled(run: Run) -> frozenset[str] | None:
    """The skills and rules ``setup.disabled`` keeps out of the home, read
    once. None where the two lists are at fault: the first part to ask
    reports it, and the run then writes nothing."""
    if not run._disabled_read:
        run._disabled_read = True
        try:
            run._disabled = definitions.disabled(_locations(run, None), run.sources.skills)
        except SetupError as exc:
            run.fail(*exc.lines)
    return run._disabled


def fill_skills(run: Run) -> None:
    """Every skill into the skills place of each installed provider its
    ``compatibility`` line names (R6.2), but those ``setup.disabled`` names.
    A skill with a setup of its own is skipped, whatever is at its path
    (R1.2)."""
    off = disabled(run)
    if off is None:
        return
    for provider in run.homes.installed():
        if not _has_place(provider, homes.SKILLS):
            continue
        place = provider.place(homes.SKILLS)
        for name, skill in run.sources.skills.items():
            if provider.name in skill.providers and name not in off:
                run.link(provider, place, name, run.homes.clone / name, own_setup=skill.own_setup)


def fill_rules(run: Run) -> None:
    """Every rule directory into the rules place of each installed provider
    that has one: Claude Code (R2.2), but those ``setup.disabled`` names."""
    off = disabled(run)
    if off is None:
        return
    rules = homes.rule_directories(run.homes.clone)
    for provider in run.homes.installed():
        if _has_place(provider, homes.RULES):
            place = provider.place(homes.RULES)
            for rule in rules:
                if rule.name not in off:
                    run.link(provider, place, rule.name, rule)


def configure_roles(parser: Any) -> None:
    parser.add_argument(
        NO_ROLES_OPTION,
        action="store_true",
        help="install the process alone for this run: generate no role definition and no entry point. A "
        "definition an earlier run generated is then removed, unless it was edited by hand since. The setting "
        f"{ROLES_KEY} = false (`init {NO_ROLES_OPTION}`, or the settings file) does the same on every run",
    )


@dataclass(frozen=True)
class Roles:
    """Whether the roles are generated for the home and for the project
    (None without one), and why not: ``OFF_BY_OPTION``, ``OFF_BY_SETTING``,
    ``OFF_BY_HOME`` (a project only), or None where they are. ``home_setting``
    and ``project_setting`` are the effective ``roles.enabled`` of each,
    where a layer gives it."""

    home: bool
    home_off_by: str | None
    home_setting: settings.Entry | None
    project: bool | None = None
    project_off_by: str | None = None
    project_setting: settings.Entry | None = None


def roles(run: Run) -> Roles:
    """Whether the roles are generated in this run; see the module. Read
    once, and a ``SetupError`` where the roles group of a settings file has
    a fault."""
    if run._roles is None:
        run._roles = _roles(run)
    return run._roles


def _enabled(entry: settings.Entry | None) -> bool:
    return entry is None or entry.value is not False


def _roles(run: Run) -> Roles:
    project = run.homes.project
    if run.option("no_roles", False):
        # The option wins, and no settings file is read for it: a run with
        # it reads the roles group no more than it did before the setting.
        if project is None:
            return Roles(False, OFF_BY_OPTION, None)
        return Roles(False, OFF_BY_OPTION, None, False, OFF_BY_OPTION, None)
    home_setting = settings.resolve(_locations(run, None), ("roles",)).get(ROLES_KEY)
    project_setting = None
    if project is not None:
        project_setting = settings.resolve(_locations(run, project), ("roles",)).get(ROLES_KEY)
    home = _enabled(home_setting)
    home_off_by = None if home else OFF_BY_SETTING
    if project is None:
        return Roles(home, home_off_by, home_setting)
    if not home:
        # The project's own setting may say true: it gets nothing all the
        # same, since what it gets is built on the home's definitions.
        return Roles(home, home_off_by, home_setting, False, OFF_BY_HOME, project_setting)
    if not _enabled(project_setting):
        return Roles(home, home_off_by, home_setting, False, OFF_BY_SETTING, project_setting)
    return Roles(home, home_off_by, home_setting, True, None, project_setting)


def _setting_json(entry: settings.Entry | None) -> dict[str, Any] | None:
    return None if entry is None else {"value": entry.value, "layer": entry.layer, "file": str(entry.file)}


def roles_report(choice: Roles | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The home's and the project's part of the report."""
    if choice is None:
        return None, None
    home = {"enabled": choice.home, "off_by": choice.home_off_by, "setting": _setting_json(choice.home_setting)}
    if choice.project is None:
        return home, None
    return home, {
        "enabled": choice.project, "off_by": choice.project_off_by, "setting": _setting_json(choice.project_setting),
    }


# Said wherever the home's roles are off: a project is written only by a run
# that names it, and the home's record lists no project (``manifest``).
PROJECTS_LEFT = (
    "a project rendered with roles keeps what render wrote there: the starting role that "
    f"{entry.MANAGER_DEFAULT_KEY} set (\"{entry.AGENT_KEY}\" in {entry.CLAUDE_SETTINGS} and setup's block in "
    f"{entry.CODEX_CONFIG}), which names a definition this home no longer has, and its own definitions. Run "
    "`render --project DIR` for each such project to take them out; setup keeps no list of the projects it "
    "rendered, since each project's record is in the project"
)


def home_roles_setting(where: Locations) -> settings.Entry | None:
    """The effective ``roles.enabled`` of a home: the user-level settings
    alone. None where no layer gives it (on)."""
    return settings.resolve(definitions.user_level(where), ("roles",)).get(ROLES_KEY)


def roles_line(found: dict[str, Any] | None) -> str | None:
    """The line that says the home's roles are off, and why; None where
    they are on."""
    if found is None or found["enabled"]:
        return None
    alone = "the process alone; no role definition or entry point is generated"
    if found["off_by"] == OFF_BY_OPTION:
        return f"roles: off for this run ({NO_ROLES_OPTION}): {alone}"
    setting = found.get("setting") or {}
    return (
        f"roles: off by the setting {ROLES_KEY} = false in {setting.get('file')} ({setting.get('layer')} layer): "
        f"{alone}. Set it to true (`init --roles`) to generate them"
    )


def project_roles_line(found: dict[str, Any] | None) -> str | None:
    """The line that says a project's roles are off, and why; None where
    they are on, or off by the option (the home's line says so)."""
    if found is None or found["enabled"] or found["off_by"] == OFF_BY_OPTION:
        return None
    setting = found.get("setting") or {}
    if found["off_by"] == OFF_BY_HOME:
        line = "roles: off for the home, so nothing of the roles is generated for the project either"
        if setting.get("value") is True and setting.get("layer") in settings.PROJECT_LAYERS:
            line += (
                f" ({ROLES_KEY} = true in {setting.get('file')} asks for them, and what a project gets is built on "
                "the home's role definitions)"
            )
        return line
    return (
        f"roles: off for the project by the setting {ROLES_KEY} = false in {setting.get('file')} "
        f"({setting.get('layer')} layer): nothing of the roles is generated for it"
    )


def _locations(run: Run, project: Path | None) -> Locations:
    """The locations of the run, with or without its project. ``real_home``
    is the run's, so that whatever resolves the homes from them again reads
    the providers' variables exactly where the run did. What a generated
    text says of a home is taken from ``run.homes`` itself."""
    return Locations(home=run.homes.home, project=project, clone=run.homes.clone, real_home=not run.homes.scratch)


def fill_roles(run: Run) -> None:
    """The role definitions of each installed provider, into its agents
    place (R6.2). They are made from the user-level settings: a project's
    settings never reach a home's files. ``--no-roles``, or ``roles.enabled``
    false, asks for none, and the stale sweep then removes those of an
    earlier run."""
    try:
        if not roles(run).home:
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
    ``--no-roles`` asks for none of it, and what an earlier run made is then
    stale: the files go with the sweep, the key and the block here. So does
    ``roles.enabled`` false, for the home or for the project alone."""
    project = run.homes.project
    home = _locations(run, None)
    where = _locations(run, project)
    providers = _entry_providers(run)
    names = [provider.name for provider in providers]
    wanted_key = wanted_effort = wanted_block = False
    if run.errors:
        return  # the roles part said why; the same sources would say it here again
    try:
        choice = roles(run)
    except SetupError as exc:
        run.fail(*exc.lines)
        return
    if choice.home:
        try:
            wanted_key, wanted_effort, wanted_block = _fill_entry(
                run, home, where, providers, names, project_roles=bool(choice.project),
            )
        except SetupError as exc:
            run.fail(*exc.lines)
            return
    if project is not None and not run.errors:
        # The effort first: it was set after the role, and the last member
        # taken out first gives back the bytes that were there.
        if not wanted_effort:
            run.drop_json_key(project / entry.CLAUDE_SETTINGS, entry.EFFORT_KEY)
        if not wanted_key:
            run.drop_json_key(project / entry.CLAUDE_SETTINGS, entry.AGENT_KEY)
        if not wanted_block:
            run.drop_block(project / entry.CODEX_CONFIG, entry.BLOCK_NAME)


def _fill_entry(run: Run, home: Locations, where: Locations, providers: list[homes.Provider],
                names: list[str], project_roles: bool = True) -> tuple[bool, bool, bool]:
    """Returns whether the project's ``agent`` key, its ``effortLevel`` key
    and its Codex block are wanted. With ``project_roles`` false the home's
    entry points are made and nothing of the project."""
    project = run.homes.project if project_roles else None
    made = [*entry.skills(home, names, run.homes), *entry.profiles(home, names, run.homes)]
    loaded = sorted({one.role for one in made if one.kind == entry.LOADED})

    # A loaded role is a skill of the role's name: it may not be a skill
    # the clone already has, nor one with a setup of its own.
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
                    detail = {"entry": one.kind, "role": one.role}
                    if one.name.endswith(entry.SKILL_FILE):
                        detail.update({"model": one.model, "effort": one.effort, "tokens": one.tokens,
                                       "limit_tokens": one.limit_tokens, "over_limit": one.over_limit})
                    item = run.file(provider, place, one.name, one.text, one.inputs, detail=detail)
                    if one.name.endswith(entry.SKILL_FILE):
                        _point(run, name, "load", one.role, entry.INVOKE[name].format(role=one.role), item,
                               model=one.model, effort=one.effort, tokens=one.tokens,
                               limit_tokens=one.limit_tokens, over_limit=one.over_limit,
                               provider_name=one.provider_name)
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

    # The starting role as the project's default.
    if default:
        role = run.project_facts["starting_role"]
        for provider in providers:
            if provider.name == definitions.CLAUDE_CODE:
                wanted_key = True
                item = run.json_key(provider, project / entry.CLAUDE_SETTINGS, entry.AGENT_KEY, role)
                _point(run, provider.name, "project-default", role,
                       f'"{entry.AGENT_KEY}": "{role}" in {entry.CLAUDE_SETTINGS}', status=item.status)
                wanted_effort = _project_effort(run, provider, where, role, item)
            elif provider.name == definitions.CODEX:
                wanted_block = True
                path = project / entry.CODEX_CONFIG
                _, content = entry.project_block(where, run.homes)
                taken_keys = _keys_outside(path, content)
                if taken_keys:
                    raise SetupError(*[
                        f"{path}: {key} is already set outside setup's block. {entry.MANAGER_DEFAULT_KEY} asks "
                        f"setup to set {key} for the starting role {role}, and a key cannot be set twice in "
                        "one TOML file, so setup writes nothing: your value stays in effect, and a Codex "
                        f"session in this project does not start as {role}. Remove the key from the file, or "
                        f"set {entry.MANAGER_DEFAULT_KEY} = false for this project, and run render again"
                        for key in taken_keys
                    ])
                item = run.block(provider, path, entry.BLOCK_NAME, content, fileops.HEAD)
                item.detail.update({"role": role})
                _point(run, provider.name, "project-default", role,
                       f"the block {entry.BLOCK_NAME} at the head of {entry.CODEX_CONFIG}, read in a trusted "
                       "project only; it wins over a profile", status=item.status)
        if wanted_key or wanted_block:
            run.ignore_always()
    return wanted_key, wanted_effort, wanted_block


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


NO_MODEL_LIST_OPTION = "--no-model-list"
MODEL_LIST_PART = "model-list"


def configure_model_list(parser: Any) -> None:
    parser.add_argument(
        NO_MODEL_LIST_OPTION,
        action="store_true",
        help="do not start Codex's list command (`codex debug models`); the note on a model that Codex lists and the "
        "dictionary lacks is left out",
    )


def fill_model_list(run: Run) -> None:
    """Where this run renders the Codex home, a note on the models Codex's own
    list offers and the dictionary lacks (R3.2), as ``doctor`` warns of them
    (R3.1). It writes nothing and never changes the exit code: a list that
    cannot be read is one line, also where the program is not on PATH.
    Nothing is started where Codex is not installed (no home, no program) or
    the dictionary names no list command. The note goes last of all notes."""
    if run.option("no_model_list", False) or run.errors:
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
    Part("roles", fill_roles, configure_roles),
    Part("entry", fill_entry),
    Part("codex-settings", codexsettings.fill, codexsettings.configure),
    # Its removals are planned when the first link asks (``migrate.cleared``),
    # so they come before the links whatever this part's place is.
    Part("migrate", migrate.fill, migrate.configure),
    Part(MODEL_LIST_PART, fill_model_list, configure_model_list),
)


# --- The run --------------------------------------------------------------------

def unshared_clone(standing: homes.CloneStanding, allowance: homes.CloneAllowance) -> dict[str, Any] | None:
    """What the report says of a clone only this side reads that was
    allowed (``homes.clone_allowance``); None for any other clone."""
    if standing.shared is not False or not allowance.allowed:
        return None
    return {
        "why": standing.why, "allowed_by": allowance.by, "said": allowance.describe(),
        "setting": _setting_json(allowance.setting),
    }


def execute(found: homes.Homes, sources: Sources, options: Any = None, *, dry_run: bool = False,
            follow: bool = False, overwrite_edited: bool = False, parts: tuple[Part, ...] | None = None,
            stamp: str | None = None, unshared_clone: dict[str, Any] | None = None) -> Outcome:
    """Fill one plan from the parts, then show it (``dry_run``) or apply it.
    The sources are valid and the clone was checked before this is called;
    ``unshared_clone`` is what that check allowed (see ``unshared_clone``)."""
    recovered: fileops.Result | None = None
    if not dry_run:
        # What an interrupted run left is settled before anything looks at
        # the disk to decide what to do: a file it left under a temporary
        # name is no file of the user's.
        recovered = fileops.recover(found.roots(), follow_config_symlinks=follow)
    run = Run(found, sources, options, follow=follow, overwrite=overwrite_edited, stamp=stamp)
    if recovered is not None and recovered.changed:
        run.notes.extend([*recovered.lines, *recovered.notes])
    for part in PARTS if parts is None else parts:
        part.fill(run)
    run.sweep()
    run.finish()

    everything = [*run.items, *run.stale]
    errors = [*run.errors, *[item.says for item in everything if item.status in _BLOCKING]]
    result: fileops.Result | None = None
    if errors:
        if any(item.status == CONFLICT for item in everything):
            errors.append(migration_hint())
    else:
        try:
            result = run.plan.run(dry_run)
        except fileops.PlanError as exc:
            errors = list(exc.lines)
    for call in run.settled:
        call()
    needs_flag = sum(1 for item in everything if item.status in (NEEDS_FLAG, EDITED)) + migrate.left(run)
    needs_flag += len(result.edited) if result is not None else 0
    code = EXIT_ERROR if errors else EXIT_NEEDS_FLAG if needs_flag else 0
    report = _report(run, result, errors, dry_run, code)
    report["unshared_clone"] = unshared_clone
    return Outcome(report, code, errors)


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
    home_roles, project_roles = roles_report(run._roles)
    project = None
    if found.project is not None:
        project = {
            "path": str(found.project),
            "roles": project_roles,
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
        "unshared_clone": None,
        "roles": home_roles,
        "providers": providers,
        "definitions": generated,
        "entry_points": list(run.points),
        "project": project,
        "migration": migrate.report(run),
        "stale": [item.as_json() for item in run.stale],
        "plan": list(result.lines) if changed else [],
        "notes": [*run.notes, *(result.notes if result else []), *run.model_notes],
        "errors": list(errors),
        "counts": counts,
    }
    report["summary"] = _summary(report) + ("" if errors else migrate.summary(report["migration"]))
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
    # lines) is one of the links created, and its removal is counted with
    # the migration, not here: said, so that the two numbers are not read
    # as "nothing was taken away".
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
    unshared = report.get("unshared_clone")
    if unshared:
        lines.append(f"  only this side reads it ({unshared['why']}); {unshared['said']}")
    off = roles_line(report.get("roles"))
    if off is not None:
        lines.append(off)
        lines.append(f"  {PROJECTS_LEFT}")
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
        off = project_roles_line(project.get("roles"))
        if off is not None:
            lines.append(f"  {off}")
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
                f"generated for it here. `show roles --project {project['path']}` prints the project's profile"
            )
    if report["stale"]:
        lines.append("no longer installed:")
        for item in report["stale"]:
            # A settings file may hold two keys of setup's: said which.
            part = f": key {item['name']}" if item.get("kind") == KEY else ""
            lines.append(f"  {item['key']}{part}: {_shown(item)}")
    lines.extend(migrate.lines(report.get("migration")))
    lines.append("plan:")
    if report["errors"]:
        lines.append("  none: the run stopped before the plan")
    else:
        lines.extend(f"  {line}" for line in (report["plan"] or [fileops.UP_TO_DATE]))
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
