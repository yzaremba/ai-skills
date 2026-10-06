"""Every change setup makes to a home or a project: planned, then applied.

How a command uses it

    roots = Roots.of(locations)                    # home, project, clone
    fileops.add_arguments(parser)                  # in the command's configure()
    plan = Plan(roots, follow_config_symlinks=args.follow_config_symlinks)
    plan.write_file(home / ".claude/agents/coder.md", text, inputs=digest)
    plan.create_link(home / ".claude/skills/json-tools", clone / "json-tools")
    plan.edit_block(home / ".codex/AGENTS.md", "Sprint work follows ...\\n")
    plan.edit_json(project / ".claude/settings.json", set={"agent": "manager"})
    plan.ignore(add=[".claude/agents/coder.md"])   # the project's .gitignore
    plan.remove_directory(home / ".claude/skills/manager")   # setup's own, once empty
    result = plan.run(dry_run=args.dry_run)        # or describe() / apply()
    for line in result.lines: print(line)

    record = read_record(roots)                    # what doctor reads
    for key, entry in record: record.path(key), entry["kind"], entry.get("sha256")

    recover(roots)                                 # first, in a command that surveys the disk
    plan_reversal(roots).run(dry_run=False)        # what uninstall is made of
    remove_state(roots)                            # once nothing is left
    leftovers(roots)                               # what a killed run left; doctor reads it
    unlisted_backups(roots), discard_backups(roots)   # backups no record lists; only on request

Two records, two states
    What a run does in the home is listed in the user-level record, and
    what it does in a project in the project's; each record has its state
    directory in the place it is the record of (``manifest``), with the
    backups of that place's files and its lock. A plan may change both;
    each change goes with its own record, backup directory and lock.

A run that writes takes the lock of each state it writes to by itself
(``apply``, ``remove_state``): the home's, the project's, or both. Another
run that holds one makes this one end with ``LockHeld``, a ``SetupError`` of
one line, before anything is changed. A command that makes several plans
can hold the locks around all of them with ``with locked(roots):``.

Nothing is done when an action is added. ``describe`` (the dry run) and
``apply`` first fold every action over the state of the disk, in memory.
Two actions on one file make one write. If any action cannot be carried out
the whole plan is refused with a ``PlanError`` that lists every problem, and
nothing is written: not a file, not a backup, not the record. ``check``
returns the same problems without raising.

What is found before the first write: a path outside the roots or inside
the clone; setup's own state; a credentials file; a path that is, or lies
under, a link; a parent that is a file; a directory where a file is wanted
and the reverse; a file, link or key that is there and that setup did not
make (a conflict); a block between setup's markers that setup did not
write; markers that are unpaired, nested or doubled; a file that is not
UTF-8; TOML or JSON that does not parse now, or would not parse with the
change; a key that ``manifest-keys.json`` does not list; a file or
directory the system reports unwritable; a user's file that has a second
name (a hard link), which setup would have to copy.

Where a change may be made
    Enforced in one place, ``fsio.admit``, which every change to the disk
    passes: never inside the clone the tool runs from (or the one of the
    roots), never at a credentials name, and only where the real place of
    the entry is inside the roots of the record that lists it. A change of
    the home is made below the home or a provider's home that the run was
    given as a root, and in no project; a change of a project is made
    inside the project, and never in the home's state. Links are followed
    to decide this, so a directory that is a link to elsewhere cannot have
    anything written, removed or linked through it to a place outside,
    with ``follow_config_symlinks`` or without: the option lets a run
    write through a link, and only to a place that is itself inside the
    roots. The checks here (when the plan is validated, and again before
    each change) ask the same question early, to refuse a plan whole and
    in plain words; ``fsio`` is what guarantees it.

Each ``Problem`` has a ``code``. A link in the way is ``SYMLINK`` and
carries the ``link`` found and what it ``resolves_to``; a plan refused for
that reason alone raises ``SymlinkedConfigPath``, a ``PlanError``, and
``symlink_in_the_way(roots, path)`` asks the question for one path without
a plan, so a command can leave such a path to its owner.

Config paths and links
    Every path a plan changes is a config path: the user-owned files and
    everything setup generates. It is refused when it is a link, or when
    any directory from its root down to it is one, the root (the home, the
    project) included. Directories above the root are not looked at. A link
    that the plan itself creates or removes is not followed and is not a
    link "in the way"; its parents are checked like any other. With
    ``follow_config_symlinks`` the check is off: a linked file is written
    where the link leads, and the link stays a link.

Idempotence (R6.5)
    An action whose target already is as wanted is not a change. A plan
    with no change prints ``UP_TO_DATE``, and applying it writes nothing at
    all, state directory included. This holds for a plan that does not
    undo itself: one that takes a block out and puts the same block in
    moves the block each time it runs. A ``Plan`` is built for one run and
    applied once; the next run builds its own.

Backups
    One directory per run, ``backups/<stamp>/<anchor>/<relative path>``
    under the state directory of the record that lists the path, the stamp
    being the UTC time of the plan to the microsecond. A file a write
    replaces or removes is copied there first and listed in the record,
    with its permission bits, which the way back gives the file again. A
    backup is a full copy of a user's file, a settings file with every key
    among them: where the system has permission bits the copy is readable
    by its owner alone (0600), and so are the directories that hold
    backups (0700). A link is listed with its target and nothing is
    copied. A user's file with more than one hard link is not copied at
    all, and so not changed: under a second name it may be a file setup
    must not read.

    Setup removes a backup in one case only: ``remove_state`` removes the
    backups a record lists, together with that record, once every entry
    of it was restored or removed. No run removes any other file under a
    backups directory. A backup that was written for a change that was
    then not made stays, and stays listed. A file there that no record
    lists (the record was removed by hand) is left where it is, named in
    one line by the next run that writes and by ``doctor``, and removed
    only by ``discard_backups``, which a command calls when the user asks
    for exactly that.

    One kind of backup leaves the record before the record goes. Where
    setup replaced text of the user's on request (see "User-owned files")
    and that text can not be put back where it was, the backup that holds
    it is taken off the record's list by the very change that gives the
    block or the key up (``Result.unlisted``; the pending change says so,
    so a run that is killed in the middle settles it the same way). From
    then on it is a backup no record lists: named, never removed by a run,
    removed by ``discard_backups`` when the user asks.

    The backups directory is setup's own, and so is everything in it:
    nothing is written, read or removed there through a link, with
    ``follow_config_symlinks`` or without. A backups directory that is a
    link refuses the plan before anything is changed.

Atomic writes
    See ``fsio.atomic_write``: a temporary file beside the target, synced,
    renamed over it. An existing file keeps its permission bits.

The order of a run, and what a crash leaves
    1. Validate, without a lock. A fault: nothing happened. A plan with
       no change ends here and has written nothing.
    2. Take the lock of each state the run writes to (``lock``): one run
       writes at a time, and a second one ends with one line and exit code
       2. A state directory that is missing is made on the way; ``lock``
       says how, and how a kill in the middle of that is told. Then
       validate again, now that nothing can change the records under this
       run.
    3. Remove what an interrupted run left under the temporary names its
       record lists: see below.
    4. Save each record with every change of the run listed as ``pending``
       and with the token of this run's temporary names. A crash before
       any change: the next run finds none of them made and drops the list.
    5. Write the backups. A crash leaves backups that the pending changes
       name; the next run drops those changes and keeps the backups listed.
    6. Make the changes, in order. A crash in the middle: the next run
       settles each pending change from the disk (``manifest``), takes
       those that were made into the record and drops the rest, so nothing
       setup wrote is unrecorded and nothing setup removed is forgotten. A
       failure that is not a crash (a write refused) does the same at
       once: the record is saved with exactly the changes made, and the
       error says how many. An interrupt (Ctrl-C) is left as a crash is:
       the pending list stays on disk as it was saved, the step that was
       under way included, and the next run settles it. Nothing is derived
       from what this process believed at that moment.
    7. Save the record without ``pending``. A crash before it is case 6. A
       save that fails is reported; the pending list is still on disk.
    8. Give the locks back.
    A failure in 4 or 5 that is not a crash closes the records at once
    with none of the changes made: the entries are as they were, and a
    backup that was already written stays listed.
    Before each change the path is looked at again; if it is no longer as
    validation saw it, if a directory above it has become a link, or if
    its real place is no longer one ``fsio`` admits, the run stops there,
    as in 6.

What an interrupted run leaves, and who removes it
    A killed process can leave: its lock; a file or an empty directory
    under the temporary name of its run beside a path it was changing, in
    the state directory or among the backups; the marker beside
    ``.agents`` (``lock``); and backups of changes it did not get to. The
    next run that writes clears the lock if that process is provably gone,
    settles the pending changes, and removes the temporaries that the
    record lists: exactly the names the interrupted run's token gives
    (``fsio.temporary_names``), in exactly the directories of the paths
    its pending list names, its state directory and its backups. It says
    so in one line. A command that looks at the disk to decide what to do
    (``render``, ``uninstall``) does this first (``recover``), so that a
    leftover is never taken for a file of the user's; a plan counts a
    recorded temporary as absent when it asks whether a directory is
    empty. Nothing else is removed: no backup, and no file or directory
    that merely has a name like ``.wfsetup-<hex>.tmp``. Those are the
    user's as far as setup can tell; ``leftovers`` lists them for
    ``doctor``. A dry run names the same and removes nothing. One place is
    setup's own by its name, the state directory: a file directly in it
    under a temporary name, or a claim on a lock, is a piece of a lock or
    of a record that a killed run left, and the run that takes the lock
    removes it (``lock``). That reaches no backup and nothing outside.

User-owned files
    Text (``edit_block``, ``remove_block``, ``remove_lines``): see
    ``blocks``. JSON (``edit_json``): see ``jsonkeys``. The record keeps,
    for each block, how it was joined to the file (so that taking it out
    takes out the line ending that came with it and never one of the
    user's) and, where setup's block replaced text of the user's between
    setup's markers on request, that text, which is put back when the
    block goes. That is so for markers the record did not hold (text
    setup never wrote) and for a block of setup's that its owner edited
    and then had written again (``replace=EDITED``): what was between the
    markers, markers included, takes the place of setup's block, and the
    file stays. A key of a JSON file is the same: a value that was there
    and that setup replaced, set by the user before setup ever set the
    key or since, is ``previous``, and goes back when the key is given
    up. Each such record names the backup of the file as it was
    (``replaced.backup``). One place holds one text: where text of the
    user's is replaced a second time at the same block or key, or where
    the block or the key is gone or was changed again when setup's part
    goes, the text that cannot be put back stays in its backup, and that
    backup leaves the record so that nothing removes it (see "Backups").
    A block whose lines are what setup wrote, with the other line ending,
    in a file whose line endings were changed as a whole, is setup's
    block and not an edited one (``blocks.as_written``). A file that
    setup created is removed again only when
    nothing but white space is left in it once setup's part is taken out;
    a file the user owned is left with the bytes it would have without
    setup.

Undoing (R8.1)
    ``plan_reversal`` plans the way back from the record: links that still
    point where setup pointed them and files whose hash is unchanged are
    removed, or replaced by the backup of what was there before; removed
    files and links are put back; created directories that are empty are
    removed. A created directory that holds only things of the user's is
    reported and no longer setup's; one that holds a kept entry stays in
    the record with it. A user-owned file that existed before setup and is
    unchanged since setup's last write gets its original bytes and mode
    back from the backup, exactly. Every other user-owned file (one that
    was changed since, and one that setup created, whatever its hash) has
    setup's blocks and keys taken out and the removed lines put back, and
    keeps the rest: a file setup created is never removed whole on the
    strength of a hash, because that hash is of the whole file at setup's
    last write, with whatever others had written into it by then. Two
    exceptions. A block whose text between the markers was edited is the
    user's text now: the file is kept as it is, and so is its entry, until
    the block is put back as setup wrote it or removed with its markers. A
    key whose value was changed is the user's: it is left, and is no
    longer in the record (``Result.left``). A file setup wrote whole and
    the user edited is kept, and so is its entry; ``Result.kept`` lists
    what was kept and why. A file that holds again exactly what the backup
    of the original holds needs no undoing, and its entry goes. A link of
    the user's that led to a credentials file is not put back: setup makes
    no such link, and the entry is kept. ``remove_state`` then removes the
    record, the backups it lists and the directories that held them, if
    no entry is left.

Setup's link where something of the user's was (the v1 migration)
    One plan may remove a link or a directory of the user's and then create
    setup's link at the same path: ``remove_link`` (or the files, then
    ``remove_directory(path, users=True)``), then ``create_link``. A path
    has one entry in the record, so the link's entry carries what it took
    the place of, as ``replaced``: the ``removed-link`` or
    ``removed-directory`` entry the removal alone would have left. Nothing
    of it is lost on any way out. Removing setup's link later (a skill that
    left the clone) leaves the ``replaced`` entry as the path's entry
    again. The way back removes setup's link and puts back what was there:
    the user's link with its own text and form, or the directory, into
    which the removed files are then restored from their backups. The way
    back undoes what setup made before it puts back what setup removed, so
    a file is never restored below a path that is still setup's link.
    ``create_link`` still refuses a path where something is that this plan
    did not remove. While a plan takes a link away, a path below it is
    read as absent: what the disk shows there is what the link leads to,
    and nothing is written or compared through it. If setup's link was
    changed since, it is kept, and so is every entry of what was removed
    below it: nothing is put back through a link the user made.

What setup writes is UTF-8 with LF, except inside a user-owned file, whose
own line ending is kept.
"""
from __future__ import annotations

import contextlib
import copy
import datetime
import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import blocks, fsio, jsonkeys, lock, manifest as records, paths
from .errors import SetupError
from .fsio import ABSENT, DIRECTORY, FILE, LINK, OTHER
from .lock import LockHeld
from .manifest import CLONE, HOME, PROJECT, RAW, Manifest, Record, Roots

__all__ = [
    "Leftovers", "LockHeld", "Plan", "PlanError", "Problem", "Result", "Roots", "SymlinkedConfigPath",
    "add_arguments", "discard_backups", "leftovers", "locked", "own_ignore_entry", "plan_reversal", "read_record",
    "recover", "refusal", "remove_state", "symlink_in_the_way", "unlisted_backups",
]


@contextlib.contextmanager
def locked(roots: Roots, *, home: bool = True, project: bool = False, follow: bool = False) -> Iterator[None]:
    """Hold the lock of the home, of the project, or both, around several
    plans; inside, each plan uses the same locks."""
    with contextlib.ExitStack() as stack:
        if home:
            stack.enter_context(lock.held(roots, follow=follow))
        if project:
            stack.enter_context(lock.held(roots, project=True, follow=follow))
        yield

UP_TO_DATE = "nothing to do: everything is up to date"

# Where a new block goes.
END = blocks.END
HEAD = blocks.HEAD

# What ``write_file`` may replace.
OWN = "own"        # nothing, or the file setup wrote, unchanged
EDITED = "edited"  # also the file setup wrote, edited by hand since
ANY = "any"        # also a file setup did not write (a settings file)

# Problem codes.
SYMLINK = "symlinked-config-path"
CONFLICT = "conflict"
OUTSIDE = "outside-roots"
STATE = "setup-state"
CREDENTIALS = "credentials"
PARENT = "parent-not-a-directory"
MARKERS = blocks.MARKERS
NOT_TEXT = blocks.NOT_TEXT
BAD_ACTION = blocks.BAD_BLOCK
PARSE = "not-parseable"
KEY = "key-not-listed"
UNREADABLE = "unreadable"
NOT_WRITABLE = "not-writable"
HARD_LINK = "hard-linked"

# The entries the project's ignore block always holds (R5.1): the local
# settings, the project's state directory (its record, its backups, its
# lock), and anything a killed run left under a temporary name.
IGNORE_ALWAYS = (".agents/workflow.local.toml", records.STATE_RELATIVE + "/", fsio.TEMP_PATTERN)

_CONTENT = ("file", "text", "json")
_PENDING = "?"  # an ``original`` that is settled when the steps are built

_MKDIR, _RMDIR, _WRITE, _REMOVE = "mkdir", "rmdir", "write", "remove"
_LINK, _UNLINK, _RELINK, _RECORD = "link", "unlink", "relink", "record"
# One path that holds a thing of one kind before and of another after: a
# directory of the user's and then setup's link, and the reverse on the way
# back. What is there is taken away, then the other is made.
_SWAP = "swap"

# The entries of something of the user's that setup removed. A link setup
# then makes at the path carries one as ``replaced``; see the module.
REMOVED_LINK = "removed-link"
REMOVED_DIRECTORY = "removed-directory"
REPLACEABLE = (REMOVED_LINK, REMOVED_DIRECTORY)

# The mark on the entry of a file that ``write_file(replace=ANY)`` wrote over
# a version its owner had edited since setup's last write (the settings file
# ``init`` rewrites on request). Such a file is made from what its owner put
# there, so its hash says "as setup left it" of content that is not setup's
# alone. A caller that undoes the record (``uninstall``) does not remove it
# on the strength of that hash.
REWRITTEN = "rewritten"


@dataclass(frozen=True)
class Problem:
    """One reason a plan cannot be applied."""

    code: str
    path: Path | None
    message: str
    link: Path | None = None        # SYMLINK: the link that is in the way
    resolves_to: str | None = None  # SYMLINK: that link's own text

    def __str__(self) -> str:
        return self.message


class PlanError(SetupError):
    """A plan that was refused whole. ``problems`` holds every reason."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(*[problem.message for problem in problems])
        self.problems = list(problems)

    def codes(self) -> set[str]:
        return {problem.code for problem in self.problems}


class SymlinkedConfigPath(PlanError):
    """A plan refused only because config paths are, or lie under, links."""


@dataclass
class Result:
    """What a run did, or would do.

    ``lines`` is the text of the dry run, the same for a real run.
    ``notes`` say what was looked for and not found, or left alone.
    ``kept`` lists, for a reversal, each entry that was not undone.
    ``left`` lists, for a reversal, what is the user's from now on and no
    longer in the record: a directory setup created that holds something
    of the user's, a key the user changed, a path the caller released. A
    path in ``kept`` and not in ``left`` is still in the record.
    ``edited`` lists what a plan left as it is because the user edited it:
    a block between setup's markers that no longer holds what setup wrote.
    ``unlisted`` lists the backups that the run takes out of the record and
    leaves on disk: each holds text of the user's that setup replaced on
    request and that could not be put back where it was. No run removes
    one from then on; ``discard_backups`` does, when the user asks.
    """

    changed: bool
    lines: list[str]
    notes: list[str] = field(default_factory=list)
    kept: list[tuple[str, str]] = field(default_factory=list)
    applied: bool = False
    left: list[tuple[str, str]] = field(default_factory=list)
    edited: list[tuple[str, str]] = field(default_factory=list)
    unlisted: list[Path] = field(default_factory=list)


@dataclass
class _State:
    kind: str
    data: bytes | None = None
    mode: int | None = None
    target: str | None = None
    directory: bool = False
    real: Path | None = None  # the file a followed link leads to
    links: int = 1            # a file's hard links: its names, this one included
    # A link's form: True a Windows junction, False a symlink, None the
    # form this system gives a link setup makes (``fsio.make_link``).
    junction: bool | None = None


@dataclass
class _Step:
    op: str
    path: Path
    key: str
    before: _State
    after: _State
    entry: dict[str, Any] | None
    entry_changed: bool
    backup: dict[str, Any] | None
    lines: list[str]
    state: bool = False
    # A state directory that the lock made before the plan was folded: the
    # step only records it.
    premade: bool = False
    # A swap: the entry the path has once what was there is taken away and
    # before the other is made (a one-item list, so that None is an entry).
    between: list[dict[str, Any] | None] | None = None
    # The file is the user's: not one setup wrote whole and finds unchanged.
    users: bool = False
    # Backups, by key, that the record lists no more once this change is
    # made, and that stay on disk: each holds text of the user's that setup
    # replaced on request and could not put back (``Result.unlisted``).
    unlist: list[str] = field(default_factory=list)

    def item(self, roots: Roots) -> dict[str, Any]:
        """The step as the record lists it while it is pending."""
        after: dict[str, Any] | None = {"kind": self.after.kind}
        if self.op == _RECORD or (self.op == _MKDIR and self.premade):
            after = None
        elif self.after.kind == FILE:
            after["sha256"] = fsio.sha256(self.after.data or b"")
        elif self.after.kind == LINK:
            after["target"] = roots.target_key(self.after.target or "", records.scope_of(self.key))
        item = {
            "path": self.key,
            "after": after,
            "set": self.entry_changed,
            "entry": self.entry,
            "backup": self.backup,
        }
        if self.between is not None:
            item["between"] = {"entry": self.between[0]}
        if self.unlist:
            item["unlist"] = list(self.unlist)
        return item


@dataclass
class _Prepared:
    record: Record
    steps: list[_Step]
    notes: list[str]
    kept: list[tuple[str, str]]
    left: list[tuple[str, str]] = field(default_factory=list)
    # What an interrupted run left under the temporary names its record lists.
    temporaries: list[Path] = field(default_factory=list)
    # The locks whose process never gave them back and is provably gone:
    # False for the home's, True for the project's.
    locks: list[bool] = field(default_factory=list)
    # Whose state this run writes: False the home's, True the project's.
    scopes: list[bool] = field(default_factory=list)
    edited: list[tuple[str, str]] = field(default_factory=list)

    def lines(self) -> list[str]:
        lines = [line for step in self.steps for line in step.lines]
        head: list[str] = []
        if self.record.recovered or self.record.dropped:
            head.append(
                f"complete the record of an interrupted run: {self.record.recovered} changes were made, "
                f"{self.record.dropped} were not"
            )
        left = [
            *([f"{len(self.temporaries)} temporary files it recorded"] if self.temporaries else []),
            *(["its lock"] if self.locks else []),
        ]
        if left:
            head.append(f"complete the cleanup of an interrupted run: remove {' and '.join(left)}")
        return [*head, *lines] or [UP_TO_DATE]

    @property
    def changed(self) -> bool:
        return bool(self.steps) or self.record.dirty or bool(self.temporaries or self.locks)

    def unlisted(self) -> list[Path]:
        """The backups the steps take out of the record and leave on disk."""
        found: list[Path] = []
        for step in self.steps:
            for key in step.unlist:
                try:
                    found.append(self.record.roots.path(key))
                except SetupError:
                    pass
        return found


def new_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def add_arguments(parser: Any) -> None:
    """Add ``--dry-run`` and ``--follow-config-symlinks``, which mean the
    same in every command that writes: ``Plan(roots,
    follow_config_symlinks=args.follow_config_symlinks).run(args.dry_run)``."""
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be changed, and change nothing",
    )
    parser.add_argument(
        "--follow-config-symlinks",
        action="store_true",
        help="write through a config path that is a link, or lies under one, where the link leads to a place "
        "inside the home (for a project's path: inside the project). Without it such a path is refused: what "
        "a link leads to may belong to another home. A link that leads out of the home or the project, or "
        "into a clone, is never written through, with or without this option",
    )


def read_record(roots: Roots) -> Record:
    """The install record of ``roots``, read and never written."""
    return Record(roots)


def symlink_in_the_way(roots: Roots, path: Path) -> Problem | None:
    """The first link among ``path`` and the directories from its root
    down to it, as a ``SYMLINK`` problem, or None."""
    path = Path(os.path.abspath(path))
    key = roots.key(path)
    if key is None:
        return None
    for part in _chain_of(roots, key):
        seen = fsio.look(part)
        if seen.kind == LINK:
            return _symlink_problem(path, part, seen.target)
        if seen.kind == ABSENT:
            return None
    return None


def _chain_of(roots: Roots, key: str) -> list[Path]:
    """The root of ``key``, each directory below it, and the path itself."""
    anchor, _, relative = key.partition(":")
    chain = [roots.root(anchor)]
    for part in ([] if relative == "." else relative.split("/")):
        chain.append(chain[-1] / part)
    return chain


def _symlink_problem(path: Path, link: Path, target: str | None) -> Problem:
    what = "is a link" if link == path else f"lies under the link {link}"
    return Problem(
        SYMLINK, path,
        f"{path}: {what} (to {target}); setup does not write through a link unless "
        "--follow-config-symlinks is given",
        link=link, resolves_to=target,
    )


class Plan:
    """A list of changes, applied together or not at all. See the module."""

    def __init__(
        self,
        roots: Roots,
        *,
        follow_config_symlinks: bool = False,
        stamp: str | None = None,
        key_list: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.roots = roots
        self.follow = follow_config_symlinks
        self.stamp = stamp or new_stamp()
        if not records._STAMP.fullmatch(self.stamp):
            raise SetupError(f"{self.stamp}: not a stamp for a run's backups: letters, digits, '.', '_' and '-'")
        self.key_list = key_list
        self.backup_all = True
        # The state directories the lock made for this run, by their folded
        # paths: on disk already, and the plan's to record.
        self.premade: set[str] = set()
        self._locked = False            # this run holds its locks
        self._cleared: set[bool] = set()  # and cleared a stale one to take it: the home's (False), the project's
        # The token of this run's temporary names; see ``fsio``.
        self.token = fsio.new_token()
        self._actions: list[tuple[str, dict[str, Any]]] = []

    # --- The actions ----------------------------------------------------------

    def create_directory(self, path: Path) -> None:
        """A directory, and its parents. One that is there is left alone
        and stays the user's."""
        self._actions.append(("create_directory", {"path": Path(path)}))

    def remove_directory(self, path: Path, *, users: bool = False) -> None:
        """Remove a directory that the record shows setup created, when
        the plan leaves nothing in it. Any other directory is left as it
        is, without a word: one setup did not create is the user's, and one
        that still holds something is still in use. Ask after the actions
        that empty it, and for a directory before its parent.

        With ``users`` the directory is one of the user's that this plan
        empties (the v1 migration): it is removed and recorded as
        ``removed-directory``, so a reversal makes it again. One that still
        holds anything the plan does not remove is a conflict, and nothing
        is removed."""
        self._actions.append(("remove_directory", {"path": Path(path), "users": users}))

    def write_file(
        self,
        path: Path,
        text: str,
        *,
        inputs: str | None = None,
        mode: int | None = None,
        replace: str = OWN,
    ) -> None:
        """A file setup writes whole: UTF-8, LF. ``inputs`` is the caller's
        digest of what the file was generated from, kept in the record for
        ``doctor``. ``replace`` says what may be overwritten (``OWN``,
        ``EDITED``, ``ANY``); anything else there is a conflict. With
        ``ANY``, a user's file that already holds ``text`` is left the
        user's."""
        self._actions.append(("write_file", {
            "path": Path(path), "text": text, "inputs": inputs, "mode": mode, "policy": replace,
        }))

    def remove_file(self, path: Path, *, expect_sha256: str | None = None) -> None:
        """Remove a file, after a backup. With ``expect_sha256`` a file of
        any other content is a conflict. A user's file is recorded, so a
        reversal puts it back."""
        self._actions.append(("remove_file", {"path": Path(path), "expect": expect_sha256}))

    def create_link(self, path: Path, target: Path, *, directory: bool = True) -> None:
        """A link at ``path`` to ``target``, which must exist below a root
        (the clone, as a rule). Only where nothing is, or where the record
        shows setup's own link; anything else is a conflict. Where this
        plan, or an earlier one, removed a link or a directory of the
        user's at the path, the link's entry keeps that as ``replaced``
        (see the module)."""
        self._actions.append(("create_link", {"path": Path(path), "target": Path(target), "directory": directory}))

    def remove_link(self, path: Path, *, expect_target: Path | str | None = None) -> None:
        """Remove a link, never what it leads to. With ``expect_target`` a
        link to anywhere else is a conflict. A user's link is recorded with
        its target, so a reversal puts it back."""
        self._actions.append(("remove_link", {"path": Path(path), "expect": expect_target}))

    def edit_block(
        self,
        path: Path,
        content: str,
        *,
        name: str = "",
        syntax: str | None = None,
        place: str = END,
        replace: str = OWN,
    ) -> None:
        """Setup's block ``name`` in a user-owned text file, holding
        ``content`` (LF). ``syntax`` is told by the file's name
        (``*.md``, ``.gitignore``, ``*.toml``) where it is not given. A new
        block goes to ``place``: ``END`` or ``HEAD``. A TOML file must parse
        before, and with the block.

        A block that is there and that the record does not hold (the
        record was lost, or the user wrote the markers) is setup's only if
        it holds, byte for byte, what would be written: it is then taken
        into the record and nothing is written. With anything else between
        the markers it is the user's text and a conflict, unless
        ``replace`` is ``ANY``: then the file is backed up and the block
        written."""
        self._actions.append(("edit_block", {
            "path": Path(path), "content": content, "name": name, "syntax": syntax, "place": place,
            "policy": replace,
        }))

    def remove_block(self, path: Path, *, name: str = "", syntax: str | None = None, replace: str = OWN) -> None:
        """Take setup's block ``name`` out of a text file. A block that the
        record does not hold is left where it is, with a note: setup cannot
        tell that it wrote it. ``replace=ANY`` removes that one too. A
        block the record holds and the user edited since is left as well,
        and listed in ``Result.edited``; ``replace=EDITED`` or ``ANY``
        removes it, after a backup of the file."""
        self._actions.append(("remove_block", {"path": Path(path), "name": name, "syntax": syntax, "policy": replace}))

    def remove_lines(self, path: Path, lines: Iterable[str]) -> None:
        """Remove every line of a text file that equals one of ``lines``
        exactly, the line ending aside. What was not found is a note. The
        removed lines and their positions go into the record."""
        self._actions.append(("remove_lines", {"path": Path(path), "lines": list(lines)}))

    def edit_json(self, path: Path, *, set: dict[str, Any] | None = None, remove: Iterable[str] = ()) -> None:
        """Set and remove top-level keys of a JSON settings file. Only keys
        that ``manifest-keys.json`` lists for that file. ``remove`` takes
        out a key that setup set and that still has setup's value, and puts
        back the value that was there before; a key that is the user's is
        left, with a note."""
        self._actions.append(("edit_json", {"path": Path(path), "values": dict(set or {}), "remove": list(remove)}))

    def ignore(self, add: Iterable[str] = (), remove: Iterable[str] = (), *, replace: str = OWN) -> None:
        """Keep setup's one block in the project's ``.gitignore``.

        The block holds ``IGNORE_ALWAYS``, what it held before, and ``add``,
        less ``remove``; sorted, each entry once, and without any line the
        user already has outside the block. A caller names only what it
        adds or no longer generates; what another command added stays.

        A block that is there is setup's to keep only while every line of
        it is an entry setup writes (``own_ignore_entry``): a checkout has
        the block in the committed file while its record, which is
        ignored, is not there, and such a block is taken over. A block
        that holds any other line holds the user's text: it is left as it
        is and listed in ``Result.edited`` (a block the record holds, and
        that is still as setup wrote it, is setup's whatever it lists), unless
        ``replace`` is ``ANY``;
        then it is written, and what it held is kept in the record and put
        back when setup's block goes."""
        self._actions.append(("ignore", {"add": list(add), "remove": list(remove), "policy": replace}))

    def _reverse(self, project: bool, keep: dict[Path, str] | None = None,
                 release: dict[Path, str] | None = None) -> None:
        self._actions.append(("reverse", {"project": project, "keep": dict(keep or {}), "release": dict(release or {})}))

    # --- Running --------------------------------------------------------------

    def _prepare(self) -> tuple[_Prepared, list[Problem]]:
        record = Record(self.roots)
        fold = _Fold(self, record)
        fold.check_roots()
        if not fold.problems:
            for name, arguments in self._actions:
                getattr(fold, "do_" + name)(**arguments)
        steps: list[_Step] = []
        temporaries = [] if fold.problems else recorded_temporaries(self.roots, record)
        # A lock whose process is provably gone; under this run's own lock,
        # the one this run cleared when it took it.
        stale: list[bool] = []
        scopes: list[bool] = []
        if not fold.problems:
            steps = fold.steps()
            scopes = fold.scopes(steps, temporaries)
            if steps or record.dirty:
                fold.claim_state(scopes)
                steps = [] if fold.problems else fold.steps()
                fold.check_writable(steps)
            if not fold.problems:
                fold.check_state(scopes)
        for project in self.roots.scopes():
            if self._locked:
                if project in self._cleared:
                    stale.append(project)
                continue
            found = _holder(self.roots, project)
            if found is not None and found[1] == lock.GONE:
                stale.append(project)
        scopes = sorted(set(scopes) | set(stale))
        prepared = _Prepared(record, steps, fold.notes, fold.kept, fold.left, temporaries, stale, scopes, fold.edited)
        for line in fold.unlisted_notes(scopes):
            if line not in prepared.notes:
                prepared.notes.append(line)
        return prepared, fold.problems

    def check(self) -> list[Problem]:
        """Every reason the plan cannot be applied; empty when it can."""
        return self._prepare()[1]

    def prepare(self) -> _Prepared:
        prepared, problems = self._prepare()
        if problems:
            if all(problem.code == SYMLINK for problem in problems):
                raise SymlinkedConfigPath(problems)
            raise PlanError(problems)
        return prepared

    def describe(self) -> Result:
        """The dry run: what applying would do. Nothing is changed."""
        prepared = self.prepare()
        return Result(
            prepared.changed, prepared.lines(), prepared.notes, prepared.kept, left=prepared.left,
            edited=prepared.edited, unlisted=prepared.unlisted(),
        )

    def run(self, dry_run: bool) -> Result:
        return self.describe() if dry_run else self.apply()

    def apply(self) -> Result:
        """Validate, then make every change. See the module for the order."""
        prepared = self.prepare()
        if not prepared.changed:
            return Result(
                False, prepared.lines(), prepared.notes, prepared.kept, applied=True, left=prepared.left,
                edited=prepared.edited,
            )
        with contextlib.ExitStack() as stack:
            # The home's lock first, then the project's: each in the state
            # directory it guards, and only where this run writes.
            mine = {
                project: stack.enter_context(lock.held(self.roots, project=project, follow=self.follow))
                for project in prepared.scopes
            }
            # Nothing else writes now: what the plan does is decided on what
            # is there under the lock, not on what was there before it.
            self.premade = {_Fold._ident(path) for held in mine.values() for path in held.created_paths()}
            self._locked, self._cleared = True, {project for project, held in mine.items() if held.notes}
            notes = [note for held in mine.values() for note in held.notes]
            prepared = self.prepare()
            if any(project not in mine for project in prepared.scopes):
                raise SetupError(
                    "the home or the project changed while setup was starting; nothing was changed. Run again"
                )
            result = Result(
                prepared.changed, prepared.lines(), [*notes, *prepared.notes], prepared.kept, applied=True,
                left=prepared.left, edited=prepared.edited, unlisted=prepared.unlisted(),
            )
            if prepared.changed:
                with fsio.named_temporaries(self.token):
                    self._apply(prepared, mine)
            return result

    def _confined(self, key: str) -> Any:
        """The bounds of a change at the path ``key``; see ``fsio``."""
        return fsio.confined(*self.roots.confinement(records.scope_of(key) == PROJECT))

    def _apply(self, prepared: _Prepared, locks: dict[bool, Any]) -> None:
        record, steps = prepared.record, prepared.steps
        first = [step for step in steps if step.state]
        rest = [step for step in steps if not step.state]
        involved = [
            manifest for manifest in record.manifests()
            if manifest.dirty or any(record.manifest_for(step.key) is manifest for step in steps)
        ]
        waiting = {id(manifest): list(manifest.pending) for manifest in involved}
        for project in sorted({records.scope_of(step.key) == PROJECT for step in rest if _copied(step)}):
            backup_root = self.roots.backups_dir_of(project) / self.stamp
            if os.path.lexists(backup_root):
                raise SetupError(f"{backup_root}: backups of this run's stamp are already there; run again")
        # What an interrupted run left under the names its record lists
        # goes first: the record still lists them until the next save.
        _remove_temporaries(self.roots, prepared.temporaries)
        try:
            for manifest in involved:
                mine = [step for step in first if record.manifest_for(step.key) is manifest]
                self._save_first(manifest, mine, [
                    *waiting[id(manifest)],
                    *[step.item(self.roots) for step in rest if record.manifest_for(step.key) is manifest],
                ])
                held = locks.get(manifest.scope == PROJECT)
                if held is not None:
                    held.recorded()
            self._write_backups(rest)
        except SetupError:
            # Nothing of the user's has changed yet. The records are closed
            # with none of the changes made; a backup that was written stays
            # where it is and stays listed. Where even that is cut short (a
            # kill, an interrupt), the records list every change as pending
            # and the next run settles them.
            self._close(record, [manifest for manifest in involved if manifest.on_disk], waiting, [], rest, None)
            raise
        done: list[_Step] = []
        current: _Step | None = None
        try:
            for step in rest:
                current = step
                self._perform(step)
                done.append(step)
        except SetupError as exc:
            closed = self._close(record, involved, waiting, done, rest, current)
            tail = "and are recorded" if closed else "and the next run completes the record"
            raise SetupError(
                f"{exc.lines[0]}; {len(done)} of {len(rest)} changes were made {tail}; setup stopped there"
            ) from None
        # Anything else (an interrupt, a kill) leaves the records as they
        # are on disk: every change pending, to be settled from the disk.
        if not self._close(record, involved, waiting, rest, rest, None):
            raise SetupError(
                f"{involved[0].file if involved else self.roots.manifest_file}: the record could not be saved; "
                "every change was made, and the next run completes the record"
            )

    def _save_first(self, manifest: Manifest, mine: list[_Step], pending: list[dict[str, Any]]) -> None:
        """Save one record with the changes of the run pending, and the
        token of the run's temporary names. The directories that hold it
        were made by the lock; the record lists them from here on."""
        for step in mine:
            if not step.premade:
                raise SetupError(f"{step.path}: changed while setup was running; it was left as it is")
            self._verify_place(step)
            if fsio.look(step.path).kind != DIRECTORY:
                raise SetupError(f"{step.path}: changed while setup was running; it was left as it is")
            manifest.commit(step.item(self.roots))
        manifest.pending = pending
        manifest.run = self.token if pending else None
        with fsio.confined(*self.roots.confinement(manifest.scope == PROJECT)):
            _admit_now(manifest.file, "record")
            manifest.save()

    def _close(self, record: Record, involved: list[Manifest], waiting: dict[int, list[dict[str, Any]]],
               done: list[_Step], rest: list[_Step], failed: _Step | None) -> bool:
        """Save the records with what was done and nothing pending. A step
        that failed is settled from the disk, as a crashed one would be: it
        may have been made half. A backup that was written for a change
        that was not made stays, and stays listed: no backup is removed
        but with the record that lists it."""
        made = {id(step) for step in done}
        try:
            for manifest in involved:
                for step in rest:
                    if record.manifest_for(step.key) is not manifest:
                        continue
                    item = step.item(self.roots)
                    outcome = records.MADE if id(step) in made else records.NOT_MADE
                    if step is failed:
                        outcome = record.settle(item)
                    if outcome == records.MADE:
                        manifest.commit(item)
                    elif outcome == records.HALF:
                        manifest.commit({
                            "path": item["path"], "set": True, "entry": item["between"]["entry"],
                            "backup": item.get("backup"),
                        })
                    elif _copied(step) and fsio.is_file(self.roots.path(step.backup["backup"])):
                        manifest.keep_backup(step.backup)
                manifest.pending = list(waiting[id(manifest)])
                manifest.run = self.token if manifest.pending else None
            for manifest in involved:
                with fsio.confined(*self.roots.confinement(manifest.scope == PROJECT)):
                    manifest.save()
        except SetupError:
            return False
        return True

    def _write_backups(self, steps: list[_Step]) -> None:
        wanted = [step for step in steps if _copied(step)]
        for project in sorted({records.scope_of(step.key) == PROJECT for step in wanted}):
            base = self.roots.backups_dir_of(project)
            backup_root = base / self.stamp
            with fsio.confined(*self.roots.confinement(project)):
                link = _backup_link(self.roots, project)
                if link is not None:
                    raise _backup_refusal(link)
                _admit_now(backup_root, "backups")
                fsio.make_directories(base, fsio.PRIVATE_DIRECTORY)
                fsio.make_private(base)
                try:
                    fsio.make_directory(backup_root, fsio.PRIVATE_DIRECTORY)
                except SetupError:
                    if os.path.lexists(backup_root):
                        raise SetupError(
                            f"{backup_root}: backups of this run's stamp are already there; run again"
                        ) from None
                    raise
                for step in wanted:
                    if (records.scope_of(step.key) == PROJECT) != project:
                        continue
                    target = self.roots.path(step.backup["backup"])
                    fsio.make_directories(target.parent, fsio.PRIVATE_DIRECTORY)
                    link = _backup_link(self.roots, project, target)
                    if link is not None:
                        raise _backup_refusal(link)
                    # The copy is its owner's alone; the record keeps the file's own bits.
                    fsio.atomic_write(target, step.before.data or b"", fsio.PRIVATE_FILE)

    def _perform(self, step: _Step) -> None:
        if step.op == _RECORD:
            return
        with self._confined(step.key):
            self._perform_confined(step)

    def _perform_confined(self, step: _Step) -> None:
        self._verify(step)
        before, after, path = step.before, step.after, step.path
        if step.op == _MKDIR:
            if not step.premade:
                fsio.make_directory(path, after.mode)
        elif step.op == _RMDIR:
            fsio.remove_directory(path)
        elif step.op == _WRITE:
            fsio.atomic_write(before.real or path, after.data or b"", after.mode)
        elif step.op == _REMOVE:
            fsio.remove_file(path)
        elif step.op == _LINK:
            fsio.make_link(after.target or "", path, after.directory, after.junction)
        elif step.op == _UNLINK:
            fsio.remove_link(path)
        elif step.op == _RELINK:
            fsio.remove_link(path)
            try:
                fsio.make_link(after.target or "", path, after.directory, after.junction)
            except SetupError:
                fsio.make_link(before.target or "", path, before.directory, before.junction)
                raise
        elif step.op == _SWAP:
            self._take_away(path, before)
            try:
                self._put_there(path, after)
            except SetupError:
                # A file's bytes are in this run's backup; a link and an
                # empty directory are made again as they were. If that
                # fails too, the record gets the path as taken away.
                try:
                    self._put_there(path, before)
                except SetupError:
                    pass
                raise

    @staticmethod
    def _take_away(path: Path, state: _State) -> None:
        if state.kind == FILE:
            fsio.remove_file(path)
        elif state.kind == DIRECTORY:
            fsio.remove_directory(path)  # refused by the system unless empty
        else:
            fsio.remove_link(path)

    @staticmethod
    def _put_there(path: Path, state: _State) -> None:
        if state.kind == FILE:
            fsio.atomic_write(path, state.data or b"", state.mode)
        elif state.kind == DIRECTORY:
            fsio.make_directory(path, state.mode)
        else:
            fsio.make_link(state.target or "", path, state.directory, state.junction)

    def _verify_place(self, step: _Step) -> None:
        """Where the change is made is still where validation saw it: no
        directory above the path has become a link, and its real place is
        not inside the clone."""
        path = step.path
        if not self.follow:
            link = _link_above(self.roots, path)
            if link is not None:
                raise SetupError(
                    f"{path}: {link} became a link while setup was running; nothing is written through it, and "
                    "the path was left as it is"
                )
        with self._confined(step.key):
            _admit_now(path, "path")
            if step.before.real is not None:
                _admit_now(step.before.real, "path")

    def _verify(self, step: _Step) -> None:
        """The path is still as validation saw it."""
        self._verify_place(step)
        before, path = step.before, step.path
        seen = fsio.look(path)
        if step.op == _MKDIR and step.premade:
            same = seen.kind == DIRECTORY
        elif before.real is not None:
            same = seen.kind == LINK and os.path.isfile(path) and fsio.read_bytes(before.real) == before.data
        elif before.kind == FILE:
            same = seen.kind == FILE and fsio.read_bytes(path) == before.data
        elif before.kind == LINK:
            same = seen.kind == LINK and fsio.same_target(seen.target or "", before.target or "")
        else:
            same = seen.kind == before.kind
        if not same:
            raise SetupError(f"{path}: changed while setup was running; it was left as it is")


def _link_above(roots: Roots, path: Path) -> Path | None:
    """The first link among the root of ``path`` and the directories from
    there down to its parent; the path itself is not looked at."""
    key = roots.key(path)
    if key is None:
        return None
    for part in _chain_of(roots, key)[:-1]:
        seen = fsio.look(part)
        if seen.kind == LINK:
            return part
        if seen.kind == ABSENT:
            return None
    return None


def _copied(step: _Step) -> bool:
    """Whether the step has a backup that is a copy of a file."""
    return step.backup is not None and step.backup["kind"] == "file"


def _holder(roots: Roots, project: bool) -> tuple[dict[str, Any] | None, str, str] | None:
    try:
        return lock.holder(roots, project)
    except SetupError:
        return None


def _backup_link(roots: Roots, project: bool, path: Path | None = None) -> Path | None:
    """The first link among the backups directory of the home, or of the
    project, and the directories from there down to the one the backup
    ``path`` is in; None where there is none. Setup's backups are in a
    directory of setup's own: nothing is written, read or removed there
    through a link, with ``--follow-config-symlinks`` or without (that
    option is for the config paths of a home, not for setup's state)."""
    base = roots.backups_dir_of(project)
    chain = [base]
    if path is not None:
        try:
            parts = Path(path).relative_to(base).parts[:-1]
        except ValueError:
            return base  # not below the backups directory at all: no backup of this record
        for part in parts:
            chain.append(chain[-1] / part)
    for directory in chain:
        try:
            seen = fsio.look(directory)
        except SetupError:
            return directory
        if seen.kind == LINK:
            return directory
        if seen.kind == ABSENT:
            return None
    return None


def _backup_refusal(link: Path) -> SetupError:
    return SetupError(
        f"{link}: is a link; setup keeps its backups in a directory of its own and writes, reads and removes "
        "none through a link. Nothing was changed. Take the link away and run again"
    )


def _admit_now(path: Path, what: str) -> None:
    """The early, friendly form of what ``fsio`` enforces at each change:
    refuse a place that is not inside the bounds now in force."""
    refused = fsio.admits(path)
    if refused is not None:
        raise SetupError(f"{refused}; the {what} was left as it is")


def real_place(path: Path) -> str:
    """Where a change at ``path`` is made: the real path of its directory,
    and its own name. A link at ``path`` itself is not followed: making or
    removing a link changes the directory it is in."""
    path = Path(path)
    parent = fsio.clean_target(os.path.realpath(path.parent))
    return paths.long_form(os.path.join(parent, path.name))


def inside_clone(roots: Roots, path: Path, real: Path | None = None, place: Path | None = None) -> str | None:
    """The real place of a change at ``path``, or the file ``real`` that a
    followed link there leads to, if ``fsio`` would refuse it as inside the
    clone (the one the tool runs from, or the one of ``roots``); else
    None. ``place`` is the real place where the caller has worked it out."""
    with fsio.confined([os.path.abspath(os.sep)], [] if roots.clone is None else [roots.clone]):
        for one in [path if place is None else place, *([] if real is None else [real])]:
            if fsio.admits(one) is not None:
                return real_place(Path(one))
    return None


def plan_reversal(
    roots: Roots, *, project: bool = False, follow_config_symlinks: bool = False, stamp: str | None = None,
    keep: dict[Path, str] | None = None, release: dict[Path, str] | None = None,
) -> Plan:
    """The plan that undoes what one record lists: the user-level record,
    or with ``project`` the project's. Run it like any plan. Setup's own
    unchanged output is not backed up again on the way out.

    ``keep`` and ``release`` name paths of the record that the caller takes
    out of the way back, each with the reason to report. A path in ``keep``
    is not looked at, and its entry stays (``Result.kept``). A path in
    ``release`` is left as it is and its entry goes: it is the user's from
    now on (``Result.left``)."""
    plan = Plan(roots, follow_config_symlinks=follow_config_symlinks, stamp=stamp)
    plan.backup_all = False
    plan._reverse(project, keep, release)
    return plan


def refusal(roots: Roots, path: Path) -> str | None:
    """Why no change is ever made at ``path``, whatever the options: its
    real place is in the clone, or outside the directories its record may
    change (``fsio.admit``). None where a change may be made. For a
    command that would rather skip such a place than have its plan
    refused."""
    key = roots.key(path)
    if key is None:
        return f"{path}: outside the home and the project; setup writes nowhere else"
    try:
        with fsio.confined(*roots.confinement(records.scope_of(key) == PROJECT)):
            return fsio.admits(path)
    except SetupError as exc:
        return exc.lines[0]


def recover(roots: Roots, *, follow_config_symlinks: bool = False) -> Result:
    """Finish what an interrupted run left, before a command looks at the
    disk to decide what to do: settle its pending changes in the record,
    remove the temporary files its record lists, clear its lock where its
    process is provably gone. Nothing else is changed, and nothing at all
    where no run was interrupted."""
    return Plan(roots, follow_config_symlinks=follow_config_symlinks).apply()


# --- What an interrupted run left ----------------------------------------------

def _backup_files(roots: Roots, project: bool) -> list[tuple[Path, str]]:
    """Every file under a backup directory, with its key. A link is never
    followed, and never listed."""
    found: list[tuple[Path, str]] = []
    base = roots.backups_dir_of(project)
    if fsio.look(base).kind != DIRECTORY:
        return found
    head = records.backups_key(PROJECT if project else HOME)
    for directory, names, files in os.walk(base):
        names[:] = sorted(name for name in names if fsio.look(Path(directory) / name).kind == DIRECTORY)
        for name in sorted(files):
            path = Path(directory) / name
            if fsio.look(path).kind != FILE:
                continue
            relative = path.relative_to(base).parts
            found.append((path, head + "/" + "/".join(relative)))
    return found


def unlisted_backups(roots: Roots, project: bool = False, record: Record | None = None) -> list[Path]:
    """The files under the backup directory of the home, or of the
    project, that its record does not list: nothing of setup's answers for
    them. No run removes one; ``discard_backups`` does, when it is asked.
    Nothing is changed here."""
    try:
        record = Record(roots) if record is None else record
        manifest = record.project if project else record.home
        if manifest is None:
            return []
        needed = {paths.fold_key(key) for key in manifest.needed_backups()}
        # What an interrupted run left under its recorded temporary name is
        # no backup: the next run removes it.
        temporary = {paths.fold(path) for path in recorded_temporaries(roots, record)}
        return [
            path for path, key in _backup_files(roots, project)
            if paths.fold_key(key) not in needed and not fsio.is_credentials(path)
            and paths.fold(path) not in temporary
        ]
    except (SetupError, OSError):
        return []


def discard_backups(roots: Roots, *, project: bool = False, follow_config_symlinks: bool = False) -> list[Path]:
    """Remove the backups that the record of the home, or of the project,
    does not list, because the user asked for exactly that
    (``uninstall --discard-backups``). Returns what was removed. A backup
    a record lists is never removed here."""
    removed: list[Path] = []
    with lock.held(roots, project=project, create=False, follow=follow_config_symlinks) as mine:
        if mine is None:
            return removed
        with fsio.confined(*roots.confinement(project)):
            for path in unlisted_backups(roots, project):
                _admit_now(path, "backup")
                fsio.remove_file(path)
                removed.append(path)
            _prune(roots, project)
            fsio.remove_if_empty(roots.backups_dir_of(project))
    return removed


def _temporary_places(roots: Roots, key: str) -> list[Path]:
    """The directories a run may have left a temporary in while changing
    the path ``key``: the one the path is in, and the one a file is in
    that a link there leads to."""
    found: list[Path] = []
    try:
        path = roots.path(key)
    except SetupError:
        return found
    found.append(path.parent)
    try:
        if fsio.look(path).kind == LINK and os.path.isfile(path):
            found.append(Path(os.path.realpath(path)).parent)
    except (SetupError, OSError):
        pass
    return found


def recorded_temporaries(roots: Roots, record: Record) -> list[Path]:
    """What interrupted runs left under the temporary names their records
    list (``Manifest.run``): beside the paths their pending changes named
    and among the backups. Only an entry with
    exactly such a name, there, is found; a file that merely looks like a
    temporary of setup's is not."""
    found: dict[str, Path] = {}
    try:
        for manifest, token, keys in record.interrupted:
            file_name, directory_name = fsio.temporary_names(token)
            project = manifest.scope == PROJECT
            # Not the state directory itself: what is left there is removed
            # by the run that takes the lock (``lock``).
            places: list[Path] = []
            for key in keys:
                places.extend(_temporary_places(roots, key))
            base = roots.backups_dir_of(project)
            if fsio.look(base).kind == DIRECTORY:
                for directory, names, _ in os.walk(base):
                    names[:] = [name for name in names if fsio.look(Path(directory) / name).kind == DIRECTORY]
                    places.append(Path(directory))
            for place in places:
                if fsio.look(place).kind not in (DIRECTORY, LINK):
                    continue
                one, other = place / file_name, place / directory_name
                if fsio.look(one).kind == FILE:
                    found.setdefault(paths.fold(one), one)
                if fsio.look(other).kind == DIRECTORY and not os.listdir(other):
                    found.setdefault(paths.fold(other), other)
    except (SetupError, OSError):
        return []
    return sorted(found.values())


def _remove_temporaries(roots: Roots, temporaries: list[Path]) -> None:
    """Remove the recorded temporaries of an interrupted run. What cannot
    be removed stays, and the next run tries again. Only under the lock."""
    for path in temporaries:
        key = roots.key(path)
        project = key is not None and records.scope_of(key) == PROJECT
        try:
            with fsio.confined(*roots.confinement(project)):
                fsio.discard_temporary(path)
        except SetupError:
            pass


@dataclass
class Leftovers:
    """What is in a home or a project beside what the records answer for;
    see ``leftovers``."""

    temporaries: list[Path] = field(default_factory=list)   # recorded by an interrupted run; the next run removes them
    unlisted: list[Path] = field(default_factory=list)      # backups no record lists; only the user removes them
    lookalikes: list[Path] = field(default_factory=list)    # named like a temporary, and not recorded; never touched
    lock: list[Path] = field(default_factory=list)          # the marker, pieces of a lock, claims on one

    def __iter__(self) -> Iterator[Path]:
        return iter([*self.temporaries, *self.unlisted, *self.lookalikes, *self.lock])

    def __bool__(self) -> bool:
        return bool(self.temporaries or self.unlisted or self.lookalikes or self.lock)


def leftovers(roots: Roots) -> Leftovers:
    """For a command that only reads (``doctor``): what an interrupted run
    left and the next run that writes removes (``temporaries``, ``lock``),
    the backups no record lists (``unlisted``), and what is merely named
    like a temporary of setup's beside a recorded path (``lookalikes``).
    Nothing is changed."""
    found = Leftovers()
    try:
        record = Record(roots)
    except SetupError:
        return found
    found.temporaries = recorded_temporaries(roots, record)
    known = {paths.fold(path) for path in found.temporaries}
    places: dict[str, Path] = {}
    for project in roots.scopes():
        found.unlisted.extend(unlisted_backups(roots, project, record))
        found.lock.extend(lock.leftovers(roots, project))
        root = roots.project if project else roots.home
        if root is not None:
            places.setdefault(paths.fold(root), root)
            places.setdefault(paths.fold(root / records.STATE_PARTS[0]), root / records.STATE_PARTS[0])
    for key in [*record.entries, *record.pending_paths]:
        for place in _temporary_places(roots, key):
            places.setdefault(paths.fold(place), place)
    taken = known | {paths.fold(path) for path in found.lock}
    for place in places.values():
        try:
            if fsio.look(place).kind != DIRECTORY or roots.is_state(place):
                continue
        except SetupError:
            continue
        for path in fsio.temporaries(place):
            if paths.fold(path) not in taken:
                found.lookalikes.append(path)
    return found


def _prune(roots: Roots, project: bool, start: Path | None = None) -> None:
    """Remove the directories under a backup directory that hold nothing:
    from ``start`` upwards, or all of them. A directory is no backup."""
    base = roots.backups_dir_of(project)
    if start is not None:
        for parent in [start, *start.parents]:
            if paths.same(parent, base) or not paths.inside(parent, base) or not fsio.remove_if_empty(parent):
                return
        return
    if fsio.look(base).kind != DIRECTORY:
        return
    for directory, names, _ in os.walk(base, topdown=False):
        if not paths.same(directory, base) and fsio.look(Path(directory)).kind == DIRECTORY:
            fsio.remove_if_empty(Path(directory))


def _remove_backups_of(roots: Roots, manifest: Manifest) -> None:
    """Remove the backup files one record lists, and the directories under
    its backup directory that this leaves empty. Nothing else there."""
    project = manifest.scope == PROJECT
    prefix = f"{records.backups_key(manifest.scope)}/"
    for item in manifest.backups:
        key = str(item.get("backup"))
        # Only what lies below this record's own backup directory: a record is data.
        if not paths.fold_key(key).startswith(paths.fold_key(prefix)):
            continue
        try:
            path = roots.path(key)
        except SetupError:
            continue
        if fsio.is_credentials(path) or _backup_link(roots, project, path) is not None:
            continue  # nothing is removed through a link: what is there is not setup's backup
        if fsio.look(path).kind == FILE:
            fsio.remove_file(path)
        _prune(roots, project, path.parent)


def remove_state(roots: Roots, *, project: bool = False, follow_config_symlinks: bool = False) -> bool:
    """Remove a record once it lists nothing but the directories that hold
    it: the backups it lists, the record file, and those directories where
    setup created them and they are empty. Returns False, and removes
    nothing, while anything else is listed.

    Only the backups the record lists are removed. A file under the backup
    directory that the record does not list is not setup's to remove: it
    stays, and the state directory with it (``unlisted_backups`` names
    them, ``discard_backups`` removes them when the user asks).

    Where there is no record but something a killed run left (its lock, an
    empty state directory, the marker beside ``.agents``), that goes:
    taking the lock and giving it back removes an empty state directory
    that holds no record.
    """
    if project and roots.project is None:
        raise SetupError("no project was named, so there is no project state to remove")
    with lock.held(roots, project=project, create=False, follow=follow_config_symlinks) as mine:
        if mine is None:
            lock.Lock(roots, project, follow_config_symlinks).settle_marker()
            return True
        with fsio.confined(*roots.confinement(project)):
            record = Record(roots)
            manifest = record.project if project else record.home
            assert manifest is not None
            if not manifest.on_disk:
                return True  # the lock, given back, takes the empty directories away
            ancestors = roots.state_ancestors(project)
            keys = {roots.key(path) for path in ancestors}
            only_holders = all(
                key in keys and entry["kind"] == "directory" for key, entry in manifest.entries.items()
            )
            if manifest.dirty or manifest.pending or not only_holders:
                return False
            found = symlink_in_the_way(roots, manifest.file)
            if found is not None and not follow_config_symlinks:
                raise SymlinkedConfigPath([found])
            _admit_now(manifest.file, "record")
            if manifest.find(roots.key(ancestors[0]) or "") is not None:
                # ``.agents`` goes with the state directory when the lock in
                # it is given back, if nothing of the user's is in it. That
                # setup made it is said beside it before the record that
                # said so is removed.
                mine.mark_agents()
            _remove_backups_of(roots, manifest)
            _prune(roots, project)
            fsio.remove_if_empty(roots.backups_dir_of(project))
            fsio.remove_file(manifest.file)
    return True


class _Fold:
    """The actions of a plan folded over the disk, in memory."""

    def __init__(self, plan: Plan, record: Record) -> None:
        self.plan = plan
        self.roots = plan.roots
        self.record = record
        self.problems: list[Problem] = []
        self.notes: list[str] = []
        self.kept: list[tuple[str, str]] = []
        self.left: list[tuple[str, str]] = []
        self.edited: list[tuple[str, str]] = []
        # What an interrupted run left under its recorded temporary names:
        # absent, to a plan, as it is gone before the first change.
        self.temporary: set[str] = {self._ident(path) for path in recorded_temporaries(plan.roots, record)}
        self.paths: dict[str, Path] = {}
        self.keys: dict[str, str | None] = {}
        self.seen: dict[str, fsio.Seen] = {}
        self.disk: dict[str, _State] = {}
        self.now: dict[str, _State] = {}
        self.order: list[str] = []
        self.entries: dict[str, dict[str, Any] | None] = {}
        self.details: dict[str, list[str]] = {}
        self.reals: dict[str, str] = {}
        self.written: dict[str, bytes] = {}
        self.behind: set[str] = set()  # paths below a link that the plan takes away
        self.ahead: set[str] = set()   # state directories the lock made for this run
        # The blocks and keys, as (path, "blocks" or "keys", name), whose
        # text of the user's this plan puts back where setup had replaced
        # it: the file holds it again.
        self.returned: set[tuple[str, str, str]] = set()
        # What a path's entry is while the plan has it absent, for a path
        # that is there on disk and holds something else afterwards.
        self.between: dict[str, dict[str, Any] | None] = {}
        self._key_list = plan.key_list

    # --- Problems, notes ------------------------------------------------------

    def _add(self, problem: Problem) -> None:
        if problem not in self.problems:
            self.problems.append(problem)

    def _problem(self, code: str, path: Path | None, message: str, **more: Any) -> None:
        self._add(Problem(code, path, message, **more))

    def _note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def _keep(self, key: str, why: str) -> None:
        self.kept.append((key, why))
        self._note(f"kept {key}: {why}")

    def _leave(self, key: str, why: str) -> None:
        """A path of the record that is the user's from now on."""
        if (key, why) not in self.left:
            self.left.append((key, why))

    def _detail(self, ident: str, text: str) -> None:
        self.details.setdefault(ident, []).append(text)

    # --- Looking --------------------------------------------------------------

    @staticmethod
    def _ident(path: Path) -> str:
        return paths.fold(path)

    def _locate(self, path: Path, internal: bool = False) -> tuple[str, str] | None:
        path = Path(os.path.abspath(path))
        ident = self._ident(path)
        if ident not in self.keys:
            self.paths[ident] = path
            self.keys[ident] = self._key(path)
        key = self.keys[ident]
        if key is None:
            return None
        if not internal and self.roots.is_state(path):
            self._problem(STATE, path, f"{path}: setup's own state; no command edits it")
            return None
        return ident, key

    def _key(self, path: Path) -> str | None:
        if fsio.is_credentials(path):
            self._problem(CREDENTIALS, path, f"{path}: a credentials file; setup never opens, copies or writes one")
            return None
        key = self.roots.key(path)
        if key is None:
            self._problem(OUTSIDE, path, f"{path}: outside the home and the project; setup writes nowhere else")
            return None
        anchor, _, relative = key.partition(":")
        if anchor == CLONE:
            self._problem(OUTSIDE, path, f"{path}: inside the clone, which setup never writes to")
            return None
        if relative == ".":
            self._problem(OUTSIDE, path, f"{path}: a root itself; setup changes only what is below one")
            return None
        if records.split_key(key) is None:
            self._problem(
                OUTSIDE, path, f"{path}: a name the record cannot hold (a ':' or a '\\' in it); setup changes no such path"
            )
            return None
        if any(paths.fold_key(part) == ".git" for part in relative.split("/")):
            self._problem(OUTSIDE, path, f"{path}: inside a .git directory, which setup never changes")
            return None
        return key

    def check_roots(self) -> None:
        """What no run is given: a project that holds the home, the clone
        or the home's state. A project's record changes the project and
        nothing else, and it could not if the home lay inside it."""
        roots = self.roots
        project = roots.project
        if project is None:
            return
        for what, other in (("the home", roots.home), ("the clone", roots.clone), ("setup's state", roots.state_dir)):
            if other is None:
                continue
            try:
                real, base = os.path.realpath(other), os.path.realpath(project)
            except (OSError, ValueError):
                continue
            if paths.inside(other, project) or paths.inside(real, base):
                self._problem(
                    OUTSIDE, project,
                    f"{project}: holds {what} ({other}); a project is a directory of its own, and setup changes "
                    "nothing of a home through a project",
                )
                return

    def _look(self, ident: str, path: Path) -> fsio.Seen:
        if ident not in self.seen:
            self.seen[ident] = fsio.look(path)
        return self.seen[ident]

    def _chain(self, ident: str, key: str) -> bool:
        """Every directory from the root down to the path's parent is a
        directory, or will be, and none is a link in the way."""
        path = self.paths[ident]
        chain = _chain_of(self.roots, key)[:-1]
        root = chain[0]
        for part in chain:
            part_ident = self._ident(part)
            planned = self.now.get(part_ident)
            if planned is not None and planned.kind in (DIRECTORY, ABSENT):
                if self.disk[part_ident].kind == LINK:
                    # The plan takes this link away. What the disk shows
                    # below it is what the link leads to, and is not what
                    # will be at the path: nothing will, until the plan
                    # puts it there.
                    self.behind.add(ident)
                if planned.kind == ABSENT:
                    return True
                continue
            try:
                seen = self._look(part_ident, part)
            except SetupError as exc:
                self._problem(UNREADABLE, path, exc.lines[0])
                return False
            if seen.kind == LINK:
                if not self.plan.follow:
                    self._add(_symlink_problem(path, part, seen.target))
                    return False
                if not os.path.isdir(part):
                    self._problem(PARENT, path, f"{path}: {part} is a link that leads to no directory")
                    return False
            elif seen.kind == ABSENT:
                if part == root:
                    self._problem(PARENT, path, f"{path}: {root} does not exist")
                    return False
                return True
            elif seen.kind != DIRECTORY:
                self._problem(PARENT, path, f"{path}: {part} is not a directory")
                return False
        return True

    def _state(self, path: Path, *, content: bool = False, internal: bool = False) -> tuple[str, str, _State] | None:
        """The planned state of ``path``, read from the disk at the first
        look. With ``content`` a link is followed to its file, if that is
        allowed. None when a problem was noted."""
        located = self._locate(path, internal)
        if located is None:
            return None
        ident, key = located
        path = self.paths[ident]
        if ident not in self.now:
            if not self._chain(ident, key):
                return None
            try:
                seen = fsio.Seen(ABSENT) if ident in self.behind else self._look(ident, path)
                if ident in self.plan.premade and seen.kind == DIRECTORY and self.record.get(key) is None:
                    # Made by the lock a moment ago, for this run: to the
                    # plan it is a directory still to create, and to record.
                    seen = fsio.Seen(ABSENT)
                    self.ahead.add(ident)
                state = _State(seen.kind, mode=seen.mode, target=seen.target, directory=seen.directory, links=seen.links)
                if seen.kind == LINK:
                    state.junction = seen.junction
                if seen.kind == FILE:
                    state.data = fsio.read_bytes(path)
            except SetupError as exc:
                self._problem(UNREADABLE, path, exc.lines[0])
                return None
            if seen.kind == OTHER:
                self._problem(CONFLICT, path, f"{path}: neither a file, a directory nor a link")
                return None
            self.disk[ident] = state
            self.now[ident] = replace(state)
            self.order.append(ident)
        state = self.now[ident]
        if content and state.kind == LINK:
            return self._follow(ident, key)
        return ident, key, state

    def _follow(self, ident: str, key: str) -> tuple[str, str, _State] | None:
        path = self.paths[ident]
        link = self.now[ident]
        if not self.plan.follow:
            self._add(_symlink_problem(path, path, link.target))
            return None
        real = Path(os.path.realpath(path))
        if fsio.is_credentials(real):
            self._problem(CREDENTIALS, path, f"{path}: leads to a credentials file; setup never opens one")
            return None
        if self.reals.setdefault(self._ident(real), ident) != ident:
            self._problem(CONFLICT, path, f"{path}: leads to a file another planned path leads to as well")
            return None
        try:
            seen = fsio.look(real)
            if seen.kind != FILE:
                self._problem(CONFLICT, path, f"{path}: a link that leads to no file")
                return None
            state = _State(FILE, data=fsio.read_bytes(real), mode=seen.mode, real=real, links=seen.links)
        except SetupError as exc:
            self._problem(UNREADABLE, path, exc.lines[0])
            return None
        self.disk[ident] = state
        self.now[ident] = replace(state)
        return ident, key, self.now[ident]

    # --- Changing the planned state -------------------------------------------

    def _entry(self, key: str) -> dict[str, Any] | None:
        entry = self.entries[key] if key in self.entries else self.record.get(key)
        return copy.deepcopy(entry)

    def _directory(self, path: Path, internal: bool = False) -> bool:
        """``path`` is a directory, or will be one that setup created."""
        found = self._state(path, internal=internal)
        if found is None:
            return False
        ident, key, state = found
        if state.kind == DIRECTORY:
            return True
        if state.kind == LINK:
            if self.plan.follow and os.path.isdir(path):
                return True
            if not self.plan.follow:
                self._add(_symlink_problem(self.paths[ident], self.paths[ident], state.target))
                return False
        if state.kind != ABSENT:
            self._problem(CONFLICT, path, f"{path}: is there and is not a directory")
            return False
        if not self._parents(ident, key):
            return False
        self._half_way(ident, key)
        self.now[ident] = _State(DIRECTORY)
        self.entries[key] = {"kind": "directory"}
        return True

    def _half_way(self, ident: str, key: str) -> None:
        """Called before the plan puts something at a path it had absent.
        Where the disk holds something there, the path is absent for a
        moment of the run, between two changes; its entry as it stands now
        is what the record holds if the run ends in that moment."""
        if self.disk[ident].kind != ABSENT and self.now[ident].kind == ABSENT:
            self.between[key] = self._entry(key)

    def _parents(self, ident: str, key: str) -> bool:
        chain = _chain_of(self.roots, key)
        return len(chain) <= 2 or self._directory(chain[-2], internal=True)

    def _put(self, ident: str, key: str, state: _State) -> bool:
        if not self._parents(ident, key):
            return False
        self._half_way(ident, key)
        self.now[ident] = state
        return True

    def _absent(self, ident: str) -> bool:
        if self.now[ident].real is not None:
            path = self.paths[ident]
            self._problem(CONFLICT, path, f"{path}: reached through a link; setup removes nothing through a link")
            return False
        self.now[ident] = _State(ABSENT)
        return True

    # --- Whole files, directories, links --------------------------------------

    def do_create_directory(self, path: Path) -> None:
        self._directory(path)

    def _remove_users_directory(self, path: Path) -> None:
        found = self._state(path)
        if found is None:
            return
        ident, key, state = found
        entry = self._entry(key)
        kind = None if entry is None else entry["kind"]
        if state.kind == ABSENT:
            return
        if state.kind != DIRECTORY:
            self._problem(CONFLICT, path, f"{path}: is a {state.kind}, not a directory to remove")
            return
        if kind not in (None, "directory", REMOVED_DIRECTORY):
            self._problem(CONFLICT, path, f"{path}: the record holds it as {kind}, not as a directory")
            return
        if not self._planned_empty(path):
            self._problem(
                CONFLICT, path, f"{path}: still holds something the plan does not remove; it was left as it is"
            )
            return
        base = self.record.get(key) or {}
        if self.disk[ident].kind != DIRECTORY:
            # The directory exists only in this plan: nothing of the user's goes.
            gone = base if base.get("kind") == REMOVED_DIRECTORY else None
        elif base.get("kind") == "directory":
            gone = None  # setup created it
        else:
            gone = {"kind": REMOVED_DIRECTORY}
            mode = fsio.own_directory_mode(path)
            if mode is not None:
                gone["mode"] = mode  # put back with the directory
        self.now[ident] = _State(ABSENT)
        self.entries[key] = gone

    def do_remove_directory(self, path: Path, users: bool = False) -> None:
        if users:
            self._remove_users_directory(path)
            return
        located = self._locate(path, internal=True)
        if located is None:
            return
        entry = self._entry(located[1])
        if entry is None or entry.get("kind") != "directory":
            return  # not one setup created
        if any(self._ident(held) == located[0] for project in (False, True)
               for held in self.roots.state_ancestors(project)):
            return  # it holds a record; ``remove_state`` takes it
        found = self._state(path, internal=True)
        if found is None:
            return
        ident, key, state = found
        if state.kind == ABSENT:
            self.entries[key] = None
        elif state.kind == DIRECTORY and self._planned_empty(path):
            self.now[ident] = _State(ABSENT)
            self.entries[key] = None

    def do_write_file(self, path: Path, text: str, inputs: str | None, mode: int | None, policy: str) -> None:
        found = self._state(path, content=True)
        if found is None:
            return
        ident, key, state = found
        if "\r" in text:
            self._problem(BAD_ACTION, path, f"{path}: the text to write holds a carriage return; setup writes LF")
            return
        try:
            data = text.encode("utf-8")
        except UnicodeEncodeError:
            self._problem(BAD_ACTION, path, f"{path}: the text to write holds a character UTF-8 cannot encode")
            return
        entry = self._entry(key)
        kind = None if entry is None else entry["kind"]
        fresh = {"kind": "file", "sha256": None, "inputs": inputs, "original": None}
        if state.kind == ABSENT:
            if kind in ("file", "removed-file"):
                # Setup's file that went missing, or a user's file that setup
                # removed: what was there before setup is still the original.
                fresh["original"] = entry.get("original")
            elif kind is not None:
                self._problem(CONFLICT, path, f"{path}: the record holds it as {kind}, not as a file setup writes")
                return
        elif state.kind == FILE:
            if kind is None:
                if policy != ANY:
                    self._problem(CONFLICT, path, f"{path}: is there and setup did not write it")
                    return
                if state.data == data:
                    return  # the user's file already says it; it stays the user's
                fresh["original"] = _PENDING
            elif kind == "file":
                fresh["original"] = entry.get("original")
                disk, base = self.disk[ident], self.record.get(key) or {}
                edited = disk.kind == FILE and fsio.sha256(disk.data or b"") != base.get("sha256")
                if edited and policy == OWN and disk.data != data:
                    self._problem(CONFLICT, path, f"{path}: was edited since setup wrote it")
                    return
                if entry.get(REWRITTEN) or (edited and policy == ANY):
                    # A file that is its owner's as much as setup's (a
                    # settings file), written again over what its owner had
                    # put into it since: what setup writes now is made from
                    # that, and holds it. The mark stays for as long as the
                    # entry does; see ``REWRITTEN``.
                    fresh[REWRITTEN] = True
            else:
                self._problem(CONFLICT, path, f"{path}: the record holds it as {kind}, not as a file setup writes")
                return
        else:
            self._problem(CONFLICT, path, f"{path}: is a {state.kind}, where setup would write a file")
            return
        if self.written.setdefault(ident, data) != data:
            self._problem(CONFLICT, path, f"{path}: the plan writes it twice, with different text")
            return
        new = _State(FILE, data=data, mode=state.mode if mode is None else mode, real=state.real)
        if self._put(ident, key, new):
            self.entries[key] = fresh

    def do_remove_file(self, path: Path, expect: str | None) -> None:
        found = self._state(path)
        if found is None:
            return
        ident, key, state = found
        entry = self._entry(key)
        kind = None if entry is None else entry["kind"]
        if state.kind == ABSENT:
            if kind in _CONTENT and not entry.get("original"):
                self.entries[key] = None
            return
        if state.kind != FILE:
            self._problem(CONFLICT, path, f"{path}: is a {state.kind}, not a file to remove")
            return
        disk = self.disk[ident]
        digest = fsio.sha256(state.data or b"")
        if expect is not None and digest != expect:
            self._problem(CONFLICT, path, f"{path}: does not hold what was to be removed; it was left as it is")
            return
        if kind not in (None, "removed-file", *_CONTENT):
            self._problem(CONFLICT, path, f"{path}: the record holds it as {kind}, not as a file")
            return
        # What a way back must restore is the file before setup first
        # touched it. That is told by the record as it was when this run
        # began, whatever the plan did to the file before this action.
        base = self.record.get(key) or {}
        known = base.get("kind")
        gone: dict[str, Any] | None = {"kind": "removed-file", "original": _PENDING}
        held = base.get("original") if known == "removed-file" else None
        if disk.kind == FILE and isinstance(held, dict):
            # Setup removed a file of the user's here, and a file is there
            # again. A path has one backup to go back to: the first one is
            # the user's own, so it is not given up for the new file.
            if fsio.sha256(disk.data or b"") != held.get("sha256"):
                self._problem(
                    CONFLICT, path,
                    f"{path}: a file is there again where setup removed one of yours, whose backup "
                    f"({held.get('backup')}) is kept; setup did not make the new one and does not remove it. Move "
                    "it away, or make it the same as the backup",
                )
                return
            gone = base  # the same bytes again: the backup that is held stays the one to go back to
        elif disk.kind != FILE:
            # The file exists only in this plan: nothing of the user's goes.
            gone = base if known == "removed-file" else None
        elif known == "file":
            gone = {"kind": "removed-file", "original": base["original"]} if base.get("original") else None
        elif known in ("text", "json") and base.get("sha256") == fsio.sha256(disk.data or b""):
            if base.get("original"):
                gone = {"kind": "removed-file", "original": base["original"]}
            elif base.get("created") and self._only_setups(disk.data or b"", base):
                # Setup created it and nothing but setup's own part is in
                # it. A file that holds anything else is backed up and put
                # back like a file of the user's.
                gone = None
        if self._absent(ident):
            self.entries[key] = gone

    def _only_setups(self, data: bytes, entry: dict[str, Any]) -> bool:
        """Whether a user-owned file holds nothing but what setup wrote
        into it: with setup's blocks and keys taken out, only white space
        is left."""
        try:
            if entry.get("kind") == "json":
                _, current = jsonkeys.parse(data)
                return all(name in entry.get("keys", {}) for name in current)
            syntax = entry.get("syntax")
            if entry.get("blocks") and syntax not in blocks.SYNTAXES:
                return False
            for name, known in entry.get("blocks", {}).items():
                there = blocks.get(data, syntax, name)
                if there is not None and not blocks.as_written(data, there, (known or {}).get("sha256")):
                    return False
                dropped = blocks.drop(data, syntax, name, _joint_of(known))
                data = data if dropped is None else dropped
            return not blocks.split_bom(data)[1].strip()
        except (blocks.Refusal, jsonkeys.Refusal, ValueError, TypeError):
            return False

    def do_create_link(self, path: Path, target: Path, directory: bool) -> None:
        target = Path(os.path.abspath(target))
        if fsio.is_credentials(target):
            self._problem(CREDENTIALS, target, f"{target}: a credentials file; setup never links to one")
            return
        if self.roots.key(target, target=True) is None:
            self._problem(OUTSIDE, target, f"{target}: a link target outside the clone, the home and the project")
            return
        if not (os.path.isdir(target) if directory else os.path.isfile(target)):
            wanted = "a directory" if directory else "a file"
            self._problem(CONFLICT, path, f"{path}: the link target {target} is not {wanted}")
            return
        found = self._state(path)
        if found is None:
            return
        ident, key, state = found
        entry = self._entry(key)
        kind = None if entry is None else entry["kind"]
        if kind not in (None, "link", *REPLACEABLE):
            self._problem(CONFLICT, path, f"{path}: the record holds it as {kind}, not as a link")
            return
        # What of the user's the link takes the place of; see the module.
        replaced = entry if kind in REPLACEABLE else (entry or {}).get("replaced")
        if kind in REPLACEABLE and state.kind != ABSENT:
            self._problem(
                CONFLICT, path,
                f"{path}: a {state.kind} is there again, where setup removed one of the user's; setup did not make it",
            )
            return
        if state.kind == LINK:
            if kind is None:
                self._problem(
                    CONFLICT, path, f"{path}: a link to {state.target} is there and setup did not make it"
                )
                return
            base = self.record.get(key)
            disk = self.disk[ident]
            recorded = None if base is None or base["kind"] != "link" else self.roots.target_text(base["target"])
            if disk.kind == LINK and (recorded is None or not fsio.same_target(disk.target or "", recorded)):
                self._problem(CONFLICT, path, f"{path}: no longer points where setup pointed it")
                return
        elif state.kind != ABSENT:
            self._problem(CONFLICT, path, f"{path}: a {state.kind} is there and setup did not make it")
            return
        if self._put(ident, key, _State(LINK, target=str(target), directory=directory)):
            made: dict[str, Any] = {"kind": "link", "target": self.roots.target_key(str(target), records.scope_of(key))}
            if replaced is not None:
                made["replaced"] = replaced
            self.entries[key] = made

    def _exact_target_key(self, text: str, scope: str | None = None) -> str:
        """The text of a link of the user's as the record writes it, so
        that the way back makes the link with exactly this text. A text
        that an anchor would not give back letter for letter (a trailing
        separator, a ``..``, another letter case) is stored raw."""
        key = self.roots.target_key(text, scope)
        try:
            exact = self.roots.target_text(key) == text
        except SetupError:
            exact = False
        return key if exact else f"{RAW}:{text}"

    def do_remove_link(self, path: Path, expect: Path | str | None) -> None:
        found = self._state(path)
        if found is None:
            return
        ident, key, state = found
        entry = self._entry(key)
        kind = None if entry is None else entry["kind"]
        if state.kind == ABSENT:
            if kind == "link":
                # Gone already; what it took the place of is still to put back.
                self.entries[key] = entry.get("replaced")
            return
        if state.kind != LINK:
            self._problem(CONFLICT, path, f"{path}: is a {state.kind}, not a link to remove")
            return
        if expect is not None and not fsio.same_target(state.target or "", str(expect)):
            self._problem(CONFLICT, path, f"{path}: points to {state.target}, not where the link to remove pointed")
            return
        mine = kind == "link" and fsio.same_target(state.target or "", self.roots.target_text(entry["target"]))
        if kind not in (None, "link", "removed-link"):
            self._problem(CONFLICT, path, f"{path}: the record holds it as {kind}, not as a link")
            return
        # Setup's own link leaves what it took the place of, if anything.
        gone = (entry or {}).get("replaced") if mine else {
            "kind": "removed-link",
            "target": self._exact_target_key(state.target or "", records.scope_of(key)),
            "directory": state.directory,
        }
        if not mine and state.junction:
            # Put back as what it was: a junction, not a symlink.
            gone["junction"] = True
        if self._absent(ident):
            self.entries[key] = gone

    # --- User-owned files -----------------------------------------------------

    def _content_entry(self, ident: str, key: str, kind: str) -> dict[str, Any] | None:
        """The record entry of a user-owned file, as it stands in this plan,
        or a new one. None, with a problem noted, where the record holds
        the path as something else."""
        path = self.paths[ident]
        disk = self.disk[ident]
        entry = self._entry(key)
        blank = {"text": {"syntax": None, "blocks": {}, "removed_lines": []}, "json": {"keys": {}}}[kind]
        revived = False
        if entry is None and key in self.entries:
            # Given up earlier in this plan and taken up again: what the
            # record knows of the file before setup still holds.
            base = self.record.get(key)
            if base is not None and base["kind"] == kind:
                entry, revived = {**copy.deepcopy(base), **copy.deepcopy(blank)}, True
        if entry is None:
            return {
                "kind": kind,
                "sha256": None,
                "created": disk.kind == ABSENT,
                "original": _PENDING if disk.kind == FILE else None,
                **blank,
            }
        if entry["kind"] != kind:
            self._problem(CONFLICT, path, f"{path}: the record holds it as {entry['kind']}, not as a {kind} file")
            return None
        if key not in self.entries or revived:
            if disk.kind == ABSENT:
                # The user removed the file; nothing of setup's is left in it.
                entry.update({"created": True, "original": None, **copy.deepcopy(blank)})
            elif entry.get("sha256") != fsio.sha256(disk.data or b""):
                # Changed by someone else: the backup is no longer the file
                # without setup.
                entry["original"] = None
        for name, value in blank.items():
            entry.setdefault(name, copy.deepcopy(value))
        return entry

    def _store(
        self, ident: str, key: str, state: _State, entry: dict[str, Any], new: bytes | None, empty: bool
    ) -> None:
        """The outcome of an edit of a user-owned file: its bytes (None for
        no file) and its entry."""
        answerable = bool(entry.get("blocks") or entry.get("removed_lines") or entry.get("keys"))
        old = state.data if state.kind == FILE else None
        if new is not None and empty and entry.get("created") and not answerable:
            new = None  # setup created it, and nothing but white space would be left in it
        if new is None:
            if old is not None and not self._absent(ident):
                return
        elif new != old:
            if not self._put(ident, key, _State(FILE, data=new, mode=state.mode, real=state.real)):
                return
        self.entries[key] = entry if answerable and new is not None else None

    def _text(self, path: Path, syntax: str | None, needs_syntax: bool = True):
        found = self._state(path, content=True)
        if found is None:
            return None
        ident, key, state = found
        if state.kind not in (ABSENT, FILE):
            self._problem(CONFLICT, path, f"{path}: is a {state.kind}, not a text file")
            return None
        entry = self._content_entry(ident, key, "text")
        if entry is None:
            return None
        syntax = syntax or entry.get("syntax") or blocks.syntax_for(path.name)
        if syntax not in blocks.SYNTAXES and (needs_syntax or syntax is not None):
            known = ", ".join(blocks.SYNTAXES)
            self._problem(BAD_ACTION, path, f"{path}: the name does not tell the comment syntax; name one of {known}")
            return None
        entry["syntax"] = syntax
        return ident, key, state, entry, syntax

    def _refused(self, path: Path, exc: blocks.Refusal) -> None:
        self._problem(exc.code, path, f"{path}: {exc}")

    def _replaced(self, ident: str, key: str, what: dict[str, Any]) -> dict[str, Any]:
        """What a block's or a key's record says of the text of the user's
        that this run replaces there: ``what``, and the backup that holds
        that text. Which backup that is, is settled when the steps are
        built (``_settle_replaced``): the copy this run makes of the file
        before it changes it, or the one the record already names for the
        same text."""
        what["backup"] = _PENDING
        return what

    @staticmethod
    def _settle_replaced(entry: dict[str, Any] | None, base: dict[str, Any] | None, fresh: str | None) -> None:
        """Name, in ``entry``, the backup of each text of the user's that
        the plan replaced: the one ``base`` (the record as the run found
        it) names where it holds the same text for the same block or key,
        so that a run that changes nothing changes no record; else
        ``fresh``, the backup this run writes of the file; and where there
        is neither, none is named."""
        if not isinstance(entry, dict):
            return
        for table, same in (("blocks", "text"), ("keys", "previous")):
            items = entry.get(table)
            for name, known in (items.items() if isinstance(items, dict) else ()):
                replaced = known.get("replaced") if isinstance(known, dict) else None
                if not isinstance(replaced, dict) or replaced.get("backup") != _PENDING:
                    continue
                old = ((base or {}).get(table) or {}).get(name) if isinstance((base or {}).get(table), dict) else None
                was = old.get("replaced") if isinstance(old, dict) else None
                holder, older = (replaced, was) if table == "blocks" else (known, old)
                if (
                    isinstance(was, dict) and isinstance(was.get("backup"), str) and isinstance(older, dict)
                    and same in holder and same in older and jsonkeys.same(holder[same], older[same])
                ):
                    replaced["backup"] = was["backup"]
                elif fresh is not None:
                    replaced["backup"] = fresh
                else:
                    del replaced["backup"]

    def _put_back(self, key: str, table: str, name: str) -> None:
        """The text of the user's that the record of the block or the key
        ``name`` of the file ``key`` holds is put back by this plan: the
        file holds it again."""
        self.returned.add((key, table, name))

    def _put_back_all(self, key: str, entry: dict[str, Any]) -> None:
        """The file ``key`` gets back the bytes it had before setup, with
        everything that setup replaced in them."""
        for table, name in _held(entry):
            self._put_back(key, table, name)

    def _take_out(self, key: str, data: bytes, syntax: str, name: str, known: Any) -> bytes | None:
        """``_without_block``, and the note that what the block had
        replaced is in the file again."""
        new = _without_block(data, syntax, name, known)
        if new is not None:
            self._put_back(key, "blocks", name)
        return new

    def _toml(self, path: Path, data: bytes, when: str) -> bool:
        try:
            tomllib.loads(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            self._problem(NOT_TEXT, path, f"{path}: is not UTF-8 text")
            return False
        except (tomllib.TOMLDecodeError, ValueError, RecursionError) as exc:
            self._problem(PARSE, path, f"{path}: {when}: {' '.join(str(exc).split())}")
            return False
        return True

    def do_edit_block(self, path: Path, content: str, name: str, syntax: str | None, place: str,
                      policy: str = OWN) -> None:
        found = self._text(path, syntax)
        if found is None:
            return
        ident, key, state, entry, syntax = found
        old = state.data if state.kind == FILE else None
        if place not in (END, HEAD):
            self._problem(BAD_ACTION, path, f"{path}: a block goes to the end or to the head of a file")
            return
        try:
            there = None if old is None else blocks.get(old, syntax, name)
            new = blocks.put(old, syntax, name, content, place)
            block = blocks.get(new, syntax, name)
            how = blocks.joint(old, syntax, name, place) if there is None else None
        except blocks.Refusal as exc:
            self._refused(path, exc)
            return
        known = entry["blocks"].get(name)
        foreign = there is not None and known is None and there != block
        edited = (
            there is not None and isinstance(known, dict) and old is not None
            and not blocks.as_written(old, there, known.get("sha256")) and there != block
        )
        if foreign and policy != ANY:
            # Markers of setup's with other text between them, and no
            # record of it: the user's text, as far as setup can tell.
            self._problem(
                CONFLICT, path,
                f"{path}: holds a block between setup's markers ({blocks.marker(syntax, 'start', name)}) that "
                "setup did not write, with other text in it; it was left as it is",
            )
            return
        if edited and policy not in (ANY, EDITED):
            self._problem(
                CONFLICT, path,
                f"{path}: setup's block ({blocks.marker(syntax, 'start', name)}) was edited since setup wrote it; "
                "it was left as it is",
            )
            return
        if syntax == blocks.TOML:
            if old is not None and not self._toml(path, old, "is not valid TOML"):
                return
            if not self._toml(path, new, "would not be valid TOML with setup's block"):
                return
        if new != old:
            self._detail(ident, f"block {name or '(unnamed)'}: {'update' if there is not None else 'add'}")
        fresh: dict[str, Any] = {"sha256": fsio.sha256(block or b"")}
        if isinstance(known, dict):
            for carried in ("joint", "replaced"):
                if carried in known:
                    fresh[carried] = known[carried]
        elif how is not None:
            fresh["joint"] = how
        else:
            fresh["joint"] = {"where": None}  # found there: no line ending came with it
        if foreign or edited:
            # The user's text between the markers, which this run replaces
            # because it was asked to: text setup never wrote (``foreign``),
            # or setup's block as its owner changed it since (``edited``).
            # Kept, and put back in place of setup's block when that goes.
            # Where the block held such text before (it was replaced once
            # already), the earlier text has no place to go back to: its
            # backup leaves the record and stays on disk (``steps``).
            fresh["replaced"] = self._replaced(ident, key, {"text": (there or b"").decode("utf-8")})
        entry["blocks"][name] = fresh
        self._store(ident, key, state, entry, new, empty=False)

    def do_remove_block(self, path: Path, name: str, syntax: str | None, policy: str = OWN) -> None:
        found = self._text(path, syntax)
        if found is None:
            return
        ident, key, state, entry, syntax = found
        new = old = state.data if state.kind == FILE else None
        known = entry["blocks"].get(name)
        if old is not None:
            try:
                dropped = self._take_out(key, old, syntax, name, known)
            except blocks.Refusal as exc:
                self._refused(path, exc)
                return
            if dropped is not None and known is None and policy != ANY:
                self._note(
                    f"{key}: a block between setup's markers ({blocks.marker(syntax, 'start', name)}) is there "
                    "that the record does not hold; left as it is"
                )
                return
            edited = False
            if dropped is not None and isinstance(known, dict):
                there = blocks.get(old, syntax, name)
                edited = there is not None and not blocks.as_written(old, there, known.get("sha256"))
            if edited and policy not in (ANY, EDITED):
                # The user's text between setup's markers: left, with its entry.
                why = (
                    f"setup's block ({blocks.marker(syntax, 'start', name)}) was edited since setup wrote it; "
                    "it was left as it is"
                )
                self.edited.append((key, why))
                self._note(f"{key}: {why}")
                return
            if dropped is not None:
                new = dropped
                if syntax == blocks.TOML and not self._toml(path, new, "would not be valid TOML without setup's block"):
                    return
                back = isinstance(known, dict) and "replaced" in known
                self._detail(ident, f"block {name or '(unnamed)'}: {'put back what it replaced' if back else 'remove'}")
        entry["blocks"].pop(name, None)
        self._store(ident, key, state, entry, new, empty=new is not None and not blocks.split_bom(new)[1].strip())

    def do_remove_lines(self, path: Path, lines: list[str]) -> None:
        if any(not isinstance(line, str) or not line or "\n" in line or "\r" in line for line in lines):
            self._problem(BAD_ACTION, path, f"{path}: a line to remove is one whole line, and not an empty one")
            return
        found = self._text(path, None, needs_syntax=False)
        if found is None:
            return
        ident, key, state, entry, _ = found
        if state.kind != FILE:
            for line in lines:
                self._note(f"{key}: line not found: {line}")
            return
        try:
            new, removed, missing = blocks.remove_lines(state.data or b"", lines)
        except blocks.Refusal as exc:
            self._refused(path, exc)
            return
        for line in missing:
            self._note(f"{key}: line not found: {line}")
        for item in removed:
            self._detail(ident, f"line {item['index'] + 1}: remove: {item['text']}")
        if removed:
            entry["removed_lines"].append(removed)
        self._store(ident, key, state, entry, new, empty=False)

    def do_ignore(self, add: list[str], remove: list[str], policy: str = OWN) -> None:
        if self.roots.project is None:
            self._problem(BAD_ACTION, None, "the ignore block is a project's; no project was named")
            return
        path = self.roots.project / ".gitignore"
        for line in [*add, *remove]:
            if not isinstance(line, str) or not line or line != line.strip() or "\n" in line or line[0] in "#!":
                self._problem(BAD_ACTION, path, f"{path}: {line!r} is not an entry setup puts into an ignore block")
                return
        found = self._text(path, blocks.GITIGNORE)
        if found is None:
            return
        _, key, state, entry, _ = found
        held: list[str] | None = None
        others: set[str] = set()
        there: bytes | None = None
        if state.kind == FILE:
            try:
                held = blocks.content_of(state.data or b"", blocks.GITIGNORE)
                others = {line.strip() for line in blocks.outside(state.data or b"", blocks.GITIGNORE)}
                there = blocks.get(state.data or b"", blocks.GITIGNORE, "")
            except blocks.Refusal as exc:
                self._refused(path, exc)
                return
        known = entry["blocks"].get("")
        as_written = (
            there is not None and isinstance(known, dict)
            and blocks.as_written(state.data or b"", there, known.get("sha256"))
        )
        # A block is setup's to keep only while every line of it is an
        # entry setup writes: a checkout has it in the committed file while
        # its record, which is ignored, is not there. Any other line in it
        # is the user's text, and the block is left as it is.
        own = set(add) | set(remove) | set(IGNORE_ALWAYS)
        users = [] if as_written else [line for line in held or [] if line not in own and not own_ignore_entry(line)]
        if users and policy != ANY:
            why = (
                "holds lines between setup's markers that setup does not write "
                f"({', '.join(repr(line) for line in users[:3])}{', ...' if len(users) > 3 else ''}); it was left "
                "as it is"
            )
            self.edited.append((key, why))
            self._note(f"{key}: {why}")
            return
        kept = [] if users else (held or [])
        wanted = (set(kept) | set(add) | set(IGNORE_ALWAYS)) - (set(remove) - set(IGNORE_ALWAYS)) - others - {""}
        if wanted:
            self.do_edit_block(path, "".join(f"{line}\n" for line in sorted(wanted)), "", blocks.GITIGNORE, END, ANY)
        else:
            self.do_remove_block(path, "", blocks.GITIGNORE, ANY)

    def _listed(self, key: str) -> tuple[str, ...] | None:
        if self._key_list is None:
            self._key_list = jsonkeys.load_key_list()
        for path, keys in self._key_list.items():
            if paths.fold_key(path) == paths.fold_key(key):
                return keys
        return None

    def do_edit_json(self, path: Path, values: dict[str, Any], remove: list[str]) -> None:
        located = self._locate(path)
        if located is None:
            return
        listed = self._listed(located[1])
        if listed is None:
            self._problem(KEY, path, f"{path}: not a JSON file in which setup may change a key (manifest-keys.json)")
            return
        unlisted = [name for name in [*values, *remove] if name not in listed]
        if unlisted:
            self._problem(KEY, path, f"{path}: setup may not change the key {', '.join(unlisted)} (manifest-keys.json)")
            return
        found = self._state(path, content=True)
        if found is None:
            return
        ident, key, state = found
        if state.kind not in (ABSENT, FILE):
            self._problem(CONFLICT, path, f"{path}: is a {state.kind}, not a settings file")
            return
        entry = self._content_entry(ident, key, "json")
        if entry is None:
            return
        try:
            text, current = (None, {}) if state.kind == ABSENT else jsonkeys.parse(state.data or b"")
            expected = dict(current)
            records = entry["keys"]
            for name, value in values.items():
                if name in expected and jsonkeys.same(expected[name], value):
                    if name in records:
                        records[name]["value"] = value
                    continue
                known = records.get(name)
                record: dict[str, Any] = {"value": value, "had": name in expected}
                if known is not None and name in expected and not jsonkeys.same(expected[name], known.get("value")):
                    # Changed by hand since setup set it, and set again
                    # because this run was asked to: the value there is
                    # the user's, and is what goes back when setup's key
                    # goes. A value this key's record held before has no
                    # place to go back to: its backup leaves the record
                    # and stays on disk (``steps``).
                    record["previous"] = expected[name]
                    record["replaced"] = self._replaced(ident, key, {})
                elif known is not None:
                    record["had"] = known.get("had", False)
                    for carried in ("previous", "replaced"):
                        if carried in known:
                            record[carried] = known[carried]
                elif name in expected:
                    # A value setup did not set: the user's, replaced on request.
                    record["previous"] = expected[name]
                    record["replaced"] = self._replaced(ident, key, {})
                records[name] = record
                expected[name] = value
                text = None if text is None else jsonkeys.set_key(text, name, value)
                self._detail(ident, f"key {name}: set")
            for name in remove:
                text = self._release(ident, key, name, records, expected, text)
            if text is None:
                new = jsonkeys.new_file(expected) if expected else None
            else:
                new = jsonkeys.checked(text, expected)
        except jsonkeys.Refusal as exc:
            self._problem(PARSE, path, f"{path}: {exc}")
            return
        self._store(ident, key, state, entry, new, empty=not expected)

    def _release(
        self, ident: str, key: str, name: str, records: dict[str, Any], expected: dict[str, Any], text: str | None
    ) -> str | None:
        """Give up one key of a JSON file: put back what was there before
        setup set it. A key that no longer has setup's value is the user's."""
        record = records.pop(name, None)
        if record is None:
            if name in expected:
                self._note(f"{key}: key {name} was not set by setup; left as it is")
            return text
        if name not in expected:
            return text
        if not jsonkeys.same(expected[name], record.get("value")):
            self._note(f"{key}: key {name} was changed since setup set it; left as it is")
            return text
        if record.get("had"):
            expected[name] = record.get("previous")
            self._put_back(key, "keys", name)
            self._detail(ident, f"key {name}: restore")
            return None if text is None else jsonkeys.set_key(text, name, record.get("previous"))
        del expected[name]
        self._detail(ident, f"key {name}: remove")
        return None if text is None else jsonkeys.remove_key(text, name)

    # --- The way back ---------------------------------------------------------

    def do_reverse(self, project: bool, keep: dict[Path, str] | None = None,
                   release: dict[Path, str] | None = None) -> None:
        manifest = self.record.project if project else self.record.home
        if manifest is None:
            self._problem(BAD_ACTION, None, "no project was named, so there is no project record to undo")
            return
        held = {self._ident(path) for path in self.roots.state_ancestors(project)}
        keep = {self._ident(Path(os.path.abspath(path))): why for path, why in (keep or {}).items()}
        release = {self._ident(Path(os.path.abspath(path))): why for path, why in (release or {}).items()}
        directories: list[tuple[str, Path]] = []
        # What setup made is undone before what setup removed is put back: a
        # removed file may belong below a path that is setup's link now.
        listed = sorted(manifest.entries.items(), key=lambda item: str(item[1]["kind"]).startswith("removed-"))
        for key, entry in listed:
            try:
                path = self.roots.path(key)
            except SetupError as exc:
                self._keep(key, exc.lines[0])
                continue
            ident = self._ident(path)
            if ident in keep and ident not in held:
                self._keep(key, keep[ident])
                continue
            if ident in release and ident not in held:
                # Left as it is, whatever it is now, and no longer setup's.
                if self._state(path) is not None:
                    self.entries[key] = None
                    self._leave(key, release[ident])
                continue
            if entry["kind"] == "directory":
                directories.append((key, path))
                continue
            handler = getattr(self, "_reverse_" + entry["kind"].replace("-", "_"), None)
            if handler is None:
                self._keep(key, f"an entry of a kind this setup does not know: {entry['kind']}")
                continue
            if entry["kind"].startswith("removed-") and self._below_kept_link(path):
                self._keep(key, "the directory it was in is a link now, which was kept; what setup removed there "
                                "was not put back")
                continue
            handler(path, entry)
        for key, path in sorted(directories, key=lambda item: -len(item[1].parts)):
            if self._ident(path) in held:
                continue  # it holds the record; ``remove_state`` takes it
            found = self._state(path, internal=True)
            if found is None:
                continue
            ident, _, state = found
            if state.kind == DIRECTORY and not self._planned_empty(path):
                if any(other.startswith(key + "/") and self._entry(other) is not None for other in manifest.entries):
                    continue  # it holds an entry that was kept; it goes when that one does
                self._keep(key, "the directory is not empty; it is the user's now")
                self._leave(key, "the directory is not empty; it is the user's now")
            elif state.kind == DIRECTORY:
                self.now[ident] = _State(ABSENT)
            self.entries[key] = None

    def _below_kept_link(self, path: Path) -> bool:
        """Whether a directory above ``path`` is a link the record lists
        and this plan leaves a link: setup's link where the user's
        directory was, changed since and so kept. Nothing is put back
        through it."""
        key = self.roots.key(path)
        if key is None:
            return False
        for part in _chain_of(self.roots, key)[1:-1]:
            known = self.record.get(self.roots.key(part) or "")
            if known is None or known.get("kind") != "link":
                continue
            planned = self.now.get(self._ident(part))
            try:
                kind = planned.kind if planned is not None else fsio.look(part).kind
            except SetupError:
                return False
            if kind == LINK:
                return True
        return False

    def _planned_empty(self, directory: Path) -> bool:
        try:
            names = os.listdir(directory)
        except OSError:
            return False
        for name in names:
            ident = self._ident(directory / name)
            if ident in self.temporary:
                continue  # an interrupted run's recorded temporary: gone before the first change
            planned = self.now.get(ident)
            if planned is None or planned.kind != ABSENT:
                return False
        prefix = self._ident(directory) + os.sep
        return not any(
            state.kind != ABSENT and ident.startswith(prefix) and os.sep not in ident[len(prefix):]
            for ident, state in self.now.items()
        )

    def _backup_bytes(self, reference: Any) -> bytes | None:
        try:
            path = self.roots.path(reference["backup"])
            project = records.scope_of(str(reference["backup"])) == PROJECT
            if _backup_link(self.roots, project, path) is not None:
                return None  # no backup is read through a link
            data = fsio.read_bytes(path)
        except (SetupError, KeyError, TypeError):
            return None
        return data if fsio.sha256(data) == reference.get("sha256") else None

    def _restore(self, ident: str, key: str, state: _State, reference: Any) -> bool:
        data = self._backup_bytes(reference)
        if data is None:
            return False
        mode = reference.get("mode") if isinstance(reference.get("mode"), int) else None
        return self._put(ident, key, _State(FILE, data=data, mode=mode, real=state.real))

    def _reverse_link(self, path: Path, entry: dict[str, Any]) -> None:
        found = self._state(path)
        if found is None:
            return
        ident, key, state = found
        replaced = entry.get("replaced")
        if state.kind == LINK and any(
            fsio.same_target(state.target or "", text) for text in self.roots.target_texts(entry["target"])
        ):
            self.now[ident] = _State(ABSENT)
        elif state.kind != ABSENT:
            self._keep(key, "no longer the link setup made" + (
                "; what it took the place of was not put back" if replaced else ""
            ))
            return
        # Setup's link is gone; what it took the place of is the path's
        # entry until it is put back.
        self.entries[key] = replaced if isinstance(replaced, dict) else None
        if isinstance(replaced, dict):
            handler = getattr(self, "_reverse_" + str(replaced.get("kind")).replace("-", "_"), None)
            if replaced.get("kind") not in REPLACEABLE or handler is None:
                self._keep(key, f"took the place of an entry of a kind this setup does not know: {replaced.get('kind')}")
                return
            handler(path, replaced)

    def _reverse_file(self, path: Path, entry: dict[str, Any]) -> None:
        found = self._state(path, content=True)
        if found is None:
            return
        ident, key, state = found
        original = entry.get("original")
        if state.kind == ABSENT:
            if original:
                self._keep(key, "removed since setup wrote it; the backup of what was there before is kept")
                return
        elif state.kind == FILE and original and fsio.sha256(state.data or b"") == original.get("sha256"):
            pass  # what was there before setup is there again: nothing is left to undo
        elif state.kind != FILE or fsio.sha256(state.data or b"") != entry.get("sha256"):
            self._keep(key, "changed since setup wrote it")
            return
        elif original:
            if not self._restore(ident, key, state, original):
                self._keep(key, "the backup of what was there before is missing or damaged")
                return
        elif not self._absent(ident):
            return
        self.entries[key] = None

    def _reverse_owned(self, path: Path, entry: dict[str, Any]):
        """The steps a text and a JSON file share: gone, or unchanged since
        setup's last write and with a backup of what it was before setup.
        Returns the state when setup's part has to be taken out piece by
        piece: the file was changed since, or setup created it. A file
        setup created is never removed whole because its hash is the one
        setup recorded: that hash is of the whole file at setup's last
        write, with whatever others had written into it by then."""
        found = self._state(path, content=True)
        if found is None:
            return None
        ident, key, state = found
        original = entry.get("original")
        if state.kind == ABSENT:
            if original and not entry.get("created"):
                self._keep(key, "removed since setup edited it; the backup of the original is kept")
            else:
                self.entries[key] = None
            return None
        if state.kind != FILE:
            self._keep(key, f"is a {state.kind} now")
            return None
        if original and not entry.get("created") and fsio.sha256(state.data or b"") == original.get("sha256"):
            # What was there before setup is there again: nothing is left
            # to undo, and a removed line must not be put back twice.
            self._put_back_all(key, entry)
            self.entries[key] = None
            return None
        if fsio.sha256(state.data or b"") == entry.get("sha256") and not entry.get("created"):
            if original and self._restore(ident, key, state, original):
                # The file as it was before setup, with what setup replaced in it.
                self._put_back_all(key, entry)
                self.entries[key] = None
                return None
        return ident, key, state

    def _reverse_text(self, path: Path, entry: dict[str, Any]) -> None:
        found = self._reverse_owned(path, entry)
        if found is None:
            return
        ident, key, state = found
        data = state.data or b""
        syntax = entry.get("syntax")
        try:
            if entry.get("blocks") and syntax not in blocks.SYNTAXES:
                raise blocks.Refusal("the record does not say which comment syntax the file has")
            # A block that no longer holds what setup wrote is the user's
            # text between setup's markers: the file is kept as it is, with
            # everything else of setup's in it, until the user decides.
            edited = []
            for name, known in entry.get("blocks", {}).items():
                there = blocks.get(data, syntax, name)
                recorded = known.get("sha256") if isinstance(known, dict) else None
                if there is not None and recorded is not None and not blocks.as_written(data, there, recorded):
                    edited.append(name or "(unnamed)")
            if edited:
                self._keep(key, f"setup's block {', '.join(edited)} was edited since setup wrote it")
                return
            for name, known in entry.get("blocks", {}).items():
                dropped = self._take_out(key, data, syntax, name, known)
                if dropped is not None and isinstance(known, dict) and "replaced" in known:
                    self._detail(ident, f"block {name or '(unnamed)'}: put back what it replaced")
                data = data if dropped is None else dropped
            for run in reversed(entry.get("removed_lines", [])):
                data = blocks.restore_lines(data, run)
            if syntax == blocks.TOML:
                tomllib.loads(data.decode("utf-8-sig"))
        except (blocks.Refusal, ValueError, KeyError, TypeError) as exc:
            self._keep(key, " ".join(str(exc).split()))
            return
        if data != state.data and fsio.sha256(state.data or b"") != entry.get("sha256"):
            self._note(f"{key}: changed since setup edited it; setup's part was taken out and the rest left")
        self._undone(ident, key, state, entry, data, not blocks.split_bom(data)[1].strip())

    def _reverse_json(self, path: Path, entry: dict[str, Any]) -> None:
        found = self._reverse_owned(path, entry)
        if found is None:
            return
        ident, key, state = found
        try:
            text, current = jsonkeys.parse(state.data or b"")
            expected = dict(current)
            records = copy.deepcopy(entry.get("keys", {}))
            for name in list(records):
                if name in expected and not jsonkeys.same(expected[name], records[name].get("value")):
                    self._leave(key, f"the key {name} was changed since setup set it; it is the user's now")
                text = self._release(ident, key, name, records, expected, text)
            data = jsonkeys.checked(text, expected)
        except jsonkeys.Refusal as exc:
            self._keep(key, str(exc))
            return
        self._undone(ident, key, state, entry, data, not expected)

    def _undone(self, ident: str, key: str, state: _State, entry: dict[str, Any], data: bytes, empty: bool) -> None:
        """The outcome of taking setup's part out of a user-owned file. A
        file setup created goes only when nothing is left in it (white
        space, or a JSON object without a key); with anything else in it,
        it stays, as the user's."""
        if empty and entry.get("created"):
            if not self._absent(ident):
                return
        elif data != state.data:
            if not self._put(ident, key, _State(FILE, data=data, mode=state.mode, real=state.real)):
                return
        self.entries[key] = None

    def _reverse_removed_file(self, path: Path, entry: dict[str, Any]) -> None:
        found = self._state(path)
        if found is None:
            return
        ident, key, state = found
        original = entry.get("original") or {}
        if state.kind == ABSENT:
            if not self._restore(ident, key, state, original):
                self._keep(key, "the backup of the removed file is missing or damaged")
                return
        elif state.kind != FILE or fsio.sha256(state.data or b"") != original.get("sha256"):
            self._keep(key, "something is there again; the backup of the removed file is kept")
            return
        self.entries[key] = None

    def _reverse_removed_link(self, path: Path, entry: dict[str, Any]) -> None:
        found = self._state(path)
        if found is None:
            return
        ident, key, state = found
        try:
            texts = self.roots.target_texts(entry["target"])
        except (SetupError, KeyError) as exc:
            self._keep(key, " ".join(str(exc).split()))
            return
        # A link of the user's that led into the clone is put back with the
        # text it had: below where the clone was then. Where the clone was
        # moved since, that place is the one ``clone_was`` names; without
        # it the text the link had cannot be known, and a link into the
        # clone as it is now would not be the user's link.
        target = texts[-1]
        if state.kind == ABSENT and str(entry["target"]).startswith(f"{CLONE}:") and self.roots.clone_was is None:
            moved = self._clone_seems_moved()
            if moved is not None:
                self._keep(
                    key,
                    "the link that was removed led into the clone, and the clone seems to have been moved since "
                    f"(a link setup made leads into {moved}): the text the link had cannot be known, so it was not "
                    "put back. Run uninstall with --clone-was DIR, DIR being where the clone was, and it is put "
                    "back as it was",
                )
                return
        if state.kind == ABSENT and fsio.is_credentials(target):
            # Found before anything is changed: setup makes no link to a
            # credentials file, on the way back either.
            self._keep(key, "the link that was removed leads to a credentials file; setup makes no such link, so "
                            "it was not put back")
            return
        if state.kind == ABSENT:
            again = _State(
                LINK, target=target, directory=bool(entry.get("directory")), junction=bool(entry.get("junction"))
            )
            if not self._put(ident, key, again):
                return
        elif state.kind != LINK or not any(fsio.same_target(state.target or "", text) for text in texts):
            self._keep(key, "something is there again; the removed link was not put back")
            return
        self.entries[key] = None

    def _clone_seems_moved(self) -> str | None:
        """Where the clone seems to have been when this record was made,
        if not where it is now: the directory that a link setup made still
        leads into, with the very path below it that the record holds.
        None where every link of setup's leads into the clone as it is,
        or none is left to tell."""
        if self.roots.clone is None:
            return None
        for key, entry in self.record.entries.items():
            target = entry.get("target") if entry.get("kind") == "link" else None
            if not isinstance(target, str) or not target.startswith(f"{CLONE}:"):
                continue
            relative = target.partition(":")[2]
            try:
                seen = fsio.look(self.roots.path(key))
                here = self.roots.target_text(target)
            except SetupError:
                continue
            if seen.kind != LINK or not seen.target or relative in ("", "."):
                continue
            if fsio.same_target(seen.target, here):
                return None  # a link of setup's leads into the clone where it is: it was not moved
            text = os.path.normpath(paths.long_form(fsio.clean_target(seen.target)))
            tail = os.sep + relative.replace("/", os.sep)
            if paths.fold(text).endswith(paths.fold(tail)):
                return text[:len(text) - len(tail)] or os.sep
        return None

    def _reverse_removed_directory(self, path: Path, entry: dict[str, Any]) -> None:
        found = self._state(path)
        if found is None:
            return
        ident, key, state = found
        mode = entry.get("mode")
        mode = mode if isinstance(mode, int) and not isinstance(mode, bool) else None
        if state.kind == ABSENT:
            if not self._parents(ident, key):
                return
            self._half_way(ident, key)
            self.now[ident] = _State(DIRECTORY, mode=mode)
        elif state.kind != DIRECTORY:
            self._keep(key, "something is there again; the removed directory was not put back")
            return
        elif self.disk[ident].kind != DIRECTORY:
            # Made again earlier in this plan, as the parent of a file that
            # was put back into it.
            state.mode = mode
        # The user's again, and not a directory setup created.
        self.entries[key] = None

    # --- From the planned state to steps --------------------------------------

    def scopes(self, steps: list[_Step], temporaries: list[Path]) -> list[bool]:
        """Whose state this run writes: False for the home's, True for the
        project's. A record that lists a step, a record that an interrupted
        run left unsettled, and a record whose temporaries are removed."""
        found: set[bool] = set()
        for step in steps:
            found.add(records.scope_of(step.key) == PROJECT)
        for manifest in self.record.manifests():
            if manifest.dirty:
                found.add(manifest.scope == PROJECT)
        for path in temporaries:
            key = self.roots.key(path)
            found.add(key is not None and records.scope_of(key) == PROJECT)
        return sorted(found)

    def claim_state(self, scopes: list[bool]) -> None:
        """The directories that hold the records are part of the plan."""
        for project in scopes:
            state = self.roots.state_dir_of(project)
            self._directory(state, internal=True)
            mine = self.roots.manifest_file_of(project)
            found = self._state(mine, content=True, internal=True)
            if found is not None and found[2].kind not in (ABSENT, FILE):
                self._problem(CONFLICT, mine, f"{mine}: is a {found[2].kind}, where the record goes")
            wanted = records.backups_key(PROJECT if project else HOME)
            if self.roots.key(self.roots.backups_dir_of(project)) != wanted:
                self._problem(
                    STATE, state, f"{state}: lies below another root of this run; setup cannot keep its state there"
                )

    def check_state(self, scopes: list[bool]) -> None:
        """Every run that writes takes a lock in a state directory: that
        directory is where setup may keep its state, whatever the options
        (see ``lock.Lock.check_place``)."""
        for project in scopes:
            if any(problem.path == self.roots.state_dir_of(project) for problem in self.problems):
                continue
            state = self.roots.state_dir_of(project)
            found = None if self.plan.follow else symlink_in_the_way(self.roots, state)
            if found is not None:
                self._add(found)
                continue
            try:
                with fsio.confined(*self.roots.confinement(project)):
                    refused = fsio.admits(state / lock.LOCK_NAME)
            except SetupError as exc:
                refused = exc.lines[0]
            if refused is not None:
                self._problem(OUTSIDE, state, refused)
                continue
            link = _backup_link(self.roots, project)
            if link is not None:
                self._problem(STATE, link, _backup_refusal(link).lines[0])

    def unlisted_notes(self, scopes: list[bool]) -> list[str]:
        """One line for the backups that no record lists, where this run
        writes: setup removes none of them by itself."""
        lines: list[str] = []
        for project in scopes:
            found = unlisted_backups(self.roots, project, self.record)
            if found:
                where = self.roots.backups_dir_of(project)
                option = "uninstall --discard-backups" + (" --project DIR" if project else "")
                lines.append(
                    f"{len(found)} backup{'' if len(found) == 1 else 's'} under {where} that no record lists "
                    f"{'was' if len(found) == 1 else 'were'} left as {'it is' if len(found) == 1 else 'they are'}; "
                    f"`{option}` removes {'it' if len(found) == 1 else 'them'}"
                )
        return lines

    def _planned_place(self, path: Path) -> Path:
        """Where a change at ``path`` will be made once the plan has taken
        away the links it takes away: a path below setup's link that
        becomes the user's directory again is written in that directory,
        not where the link leads now. Every other link is followed."""
        key = self.roots.key(path)
        if key is None:
            return path
        chain = _chain_of(self.roots, key)
        real = Path(os.path.realpath(chain[0]))
        gone = False  # below a link the plan takes away: not on disk as it will be
        for part in chain[1:-1]:
            ident = self._ident(part)
            planned, disk = self.now.get(ident), self.disk.get(ident)
            gone = gone or (planned is not None and disk is not None and disk.kind == LINK and planned.kind != LINK)
            real = real / part.name if gone else Path(os.path.realpath(real / part.name))
        return real / path.name

    def _planned_entry(self, path: Path) -> Path:
        """The entry whose place decides whether a change at ``path`` may
        be made: the path itself, or, below a link the plan takes away,
        that link. What is made below it is made in the directory that
        takes the link's place, which is where the link itself is."""
        key = self.roots.key(path)
        if key is None:
            return path
        for part in _chain_of(self.roots, key)[1:-1]:
            ident = self._ident(part)
            planned, disk = self.now.get(ident), self.disk.get(ident)
            if planned is not None and disk is not None and disk.kind == LINK and planned.kind != LINK:
                return part
        return path

    def _outside_clone(self, path: Path, real: Path | None) -> bool:
        """Ask ``fsio`` now what it will be asked at the change: the real
        place is inside the bounds of the record that lists the path."""
        key = self.roots.key(path)
        project = key is not None and records.scope_of(key) == PROJECT
        refused = None
        try:
            with fsio.confined(*self.roots.confinement(project)):
                for one in [self._planned_entry(path), *([] if real is None else [real])]:
                    refused = refused or fsio.admits(one)
        except SetupError as exc:
            refused = exc.lines[0]
        if refused is None:
            return True
        self._problem(OUTSIDE, path, refused)
        return False

    def check_writable(self, steps: list[_Step]) -> None:
        """What the system would refuse, as far as it tells in advance, and
        what setup refuses of a place whatever the options."""
        for step in steps:
            if step.op == _RECORD:
                continue
            if not self._outside_clone(step.path, step.before.real):
                continue
            if step.after.kind == LINK and fsio.is_credentials(step.after.target or ""):
                self._problem(
                    CREDENTIALS, step.path,
                    f"{step.path}: a link to a credentials file ({step.after.target}); setup makes no such link",
                )
                continue
            parent = (step.before.real or step.path).parent
            if os.path.isdir(parent) and not os.access(parent, os.W_OK | os.X_OK):
                self._problem(NOT_WRITABLE, step.path, f"{step.path}: the directory {parent} cannot be written to")
            elif os.name == "nt" and step.before.kind == FILE and not os.access(step.before.real or step.path, os.W_OK):
                self._problem(NOT_WRITABLE, step.path, f"{step.path}: is read-only")
            copied = step.backup is not None and step.backup["kind"] == "file"
            if copied and step.users and step.before.links > 1:
                self._problem(
                    HARD_LINK, step.path,
                    f"{step.path}: has {step.before.links} names (hard links), so it may be a file setup must not "
                    "read under another name, and a write would leave the other names with the old bytes; setup "
                    "neither copies nor changes it",
                )
            mode = step.before.mode
            if os.name == "posix" and step.before.kind == FILE and mode is not None and not mode & 0o200:
                does = "removes" if step.after.kind != FILE else "changes"
                self._note(
                    f"{step.key}: is read-only (mode {mode:04o}); setup {does} it all the same, as its owner may"
                    + ("" if step.after.kind != FILE else ", and it keeps that mode")
                )

    def _backup_reference(self, key: str, before: _State) -> dict[str, Any]:
        return {
            "backup": records.backup_key(self.plan.stamp, key),
            "sha256": fsio.sha256(before.data or b""),
            "mode": before.mode,
        }

    def steps(self) -> list[_Step]:
        held = {
            self._ident(path)
            for project in (False, True)
            for path in self.roots.state_ancestors(project)
        }
        made: list[_Step] = []
        for ident in self.order:
            key, path = self.keys[ident], self.paths[ident]
            if self.roots.is_state(path) and ident not in held:
                continue  # the record files themselves: looked at, never planned
            before, after = self.disk[ident], self.now[ident]
            base = self.record.get(key)
            entry = copy.deepcopy(self.entries[key]) if key in self.entries else copy.deepcopy(base)
            op = _operation(before, after)
            need_original = False
            if entry is not None:
                # The hash is of the file as setup left it. A run that does
                # not write the file must not take the user's edits for
                # setup's own: the way back would then remove them.
                if after.kind == FILE and entry.get("kind") in _CONTENT:
                    if op == _WRITE or entry.get("sha256") is None:
                        entry["sha256"] = fsio.sha256(after.data or b"")
                if entry.get("original") == _PENDING:
                    need_original = before.kind == FILE and op in (_WRITE, _REMOVE, _SWAP)
                    entry["original"] = self._backup_reference(key, before) if need_original else None
                # The backup of text of the user's that the plan replaced:
                # the copy this step makes of the file, where it makes one.
                copies = before.kind == FILE and op in (_WRITE, _REMOVE, _SWAP) and self.plan.backup_all
                self._settle_replaced(entry, base, records.backup_key(self.plan.stamp, key) if copies else None)
            changed = entry != base
            if op is None and not changed:
                continue
            backup: dict[str, Any] | None = None
            users = False
            if before.kind == FILE and op in (_WRITE, _REMOVE, _SWAP):
                untouched = base is not None and base.get("sha256") == fsio.sha256(before.data or b"")
                users = not (untouched and base.get("kind") == "file")
                if self.plan.backup_all or need_original or not untouched:
                    reference = self._backup_reference(key, before)
                    backup = {"path": key, "kind": "file", **reference, "stamp": self.plan.stamp}
            elif before.kind == LINK and op in (_UNLINK, _RELINK, _SWAP) and self.plan.backup_all:
                backup = {
                    "path": key,
                    "kind": "link",
                    "target": self.roots.target_key(before.target or "", records.scope_of(key)),
                    "directory": before.directory,
                    "stamp": self.plan.stamp,
                }
            step = _Step(
                op or _RECORD, path, key, before, after, entry, changed, backup, [],
                state=ident in held and op == _MKDIR, premade=ident in self.ahead and op == _MKDIR, users=users,
                unlist=self._not_put_back(key, base, entry),
            )
            if op in (_SWAP, _RELINK) and (op == _SWAP or key in self.between):
                # The path is absent for a moment of the step: after what
                # is there is taken away, before the other is made.
                half = copy.deepcopy(self.between.get(key))
                if half is not None and half.get("original") == _PENDING:
                    half["original"] = self._backup_reference(key, before) if before.kind == FILE else None
                self._settle_replaced(half, base, None)
                step.between = [half]
            step.lines = self._lines(step, self.details.get(ident, []))
            made.append(step)
        # A path that becomes a directory is made with the directories, before
        # what goes into it; one that stops being a directory goes last, after
        # what was in it and the directories below it.
        def makes(step: _Step) -> bool:
            return step.op == _MKDIR or (step.op == _SWAP and step.after.kind == DIRECTORY)

        def clears(step: _Step) -> bool:
            return step.op == _SWAP and step.before.kind == DIRECTORY

        creations = sorted((step for step in made if makes(step)), key=lambda step: len(step.path.parts))
        removals = sorted((step for step in made if step.op == _RMDIR), key=lambda step: -len(step.path.parts))
        swaps = sorted((step for step in made if clears(step)), key=lambda step: -len(step.path.parts))
        others = [step for step in made if step.op not in (_MKDIR, _RMDIR) and not makes(step) and not clears(step)]
        return [*creations, *others, *removals, *swaps]

    def _not_put_back(self, key: str, base: dict[str, Any] | None, entry: dict[str, Any] | None) -> list[str]:
        """The backups, by key, that hold text of the user's which setup
        replaced at the path ``key`` on request, which its record gives up
        with this plan, and which the plan does not put back where it was:
        the block or the key is gone or was changed again, or the same
        place had text of the user's replaced a second time. Such a backup
        may be the only copy of that text. It leaves the record, so that
        nothing removes it with the record, and is named."""
        before, after = _held(base), _held(entry)
        gone = sorted({
            backup for (table, name), backup in before.items()
            if after.get((table, name)) != backup and (key, table, name) not in self.returned
        } - set(after.values()))
        for backup in gone:
            try:
                where = str(self.roots.path(backup))
            except SetupError:
                where = backup
            self._note(
                f"{key}: what setup replaced there because it was asked to (--overwrite-edited) could not be put "
                f"back where it was. It is in the backup {where}, which setup keeps: it is yours, it is no longer "
                "in the record, and no run removes it"
            )
        return gone

    def _lines(self, step: _Step, details: list[str]) -> list[str]:
        key, entry = step.key, step.entry
        owned = entry is not None and entry.get("kind") in ("text", "json")
        saved = " (backup)" if step.backup is not None else ""
        undoing = not self.plan.backup_all
        if undoing and step.op == _WRITE:
            head = f"restore file {key}{saved}"
        elif undoing and step.op in (_LINK, _RELINK):
            head = f"restore link {key} -> {self.roots.target_key(step.after.target or '')}"
        elif step.op == _SWAP and step.after.kind == DIRECTORY:
            head = f"{'restore' if undoing else 'create'} directory {key}, in place of the {step.before.kind} there"
        elif step.op == _SWAP and step.after.kind == LINK:
            head = (
                f"create link {key} -> {self.roots.target_key(step.after.target or '')}, in place of the "
                f"{step.before.kind} there{saved}"
            )
        elif step.op == _SWAP:
            head = f"{'restore' if undoing else 'create'} file {key}, in place of the {step.before.kind} there"
        elif step.op == _MKDIR:
            head = f"create directory {key}"
        elif step.op == _RMDIR:
            head = f"remove directory {key}"
        elif step.op == _WRITE and step.before.kind == ABSENT:
            head = f"create file {key}"
        elif step.op == _WRITE:
            head = f"{'edit' if owned or details else 'replace'} file {key}{saved}"
        elif step.op == _REMOVE:
            head = f"remove file {key}{saved}"
        elif step.op == _LINK:
            head = f"create link {key} -> {self.roots.target_key(step.after.target or '')}"
        elif step.op == _RELINK:
            head = f"replace link {key} -> {self.roots.target_key(step.after.target or '')}"
        elif step.op == _UNLINK:
            head = f"remove link {key}"
        else:
            head = f"update record {key}"
        return [head, *[f"    {detail}" for detail in details]]


# The entries of an ignore block that setup writes besides ``IGNORE_ALWAYS``:
# the role definitions it generates in a project.
_IGNORE_OWN = (".claude/agents/", ".codex/agents/")


def own_ignore_entry(line: str) -> bool:
    """Whether ``line`` is an entry setup itself writes into a project's
    ignore block: one it always writes, or a file it generates there."""
    if line in IGNORE_ALWAYS:
        return True
    for head in _IGNORE_OWN:
        rest = line[len(head):] if line.startswith(head) else ""
        if rest and all(char.isalnum() or char in "._-" for char in rest) and rest[0] != ".":
            return True
    return False


def _held(entry: Any) -> dict[tuple[str, str], str]:
    """The backups, by key, that the entry of a user-owned file names as
    holding text of the user's that setup replaced on request, each under
    the block (``("blocks", name)``) or the key (``("keys", name)``) whose
    record names it."""
    found: dict[tuple[str, str], str] = {}
    if not isinstance(entry, dict):
        return found
    for table in ("blocks", "keys"):
        items = entry.get(table)
        for name, known in (items.items() if isinstance(items, dict) else ()):
            replaced = known.get("replaced") if isinstance(known, dict) else None
            if isinstance(replaced, dict) and isinstance(replaced.get("backup"), str):
                found[(table, name)] = replaced["backup"]
    return found


def _joint_of(known: Any) -> dict[str, Any]:
    """How a recorded block was joined to its file; for one whose record
    does not say, nothing but the block is taken out."""
    how = known.get("joint") if isinstance(known, dict) else None
    return how if isinstance(how, dict) else {"where": None}


def _without_block(data: bytes, syntax: str, name: str, known: Any) -> bytes | None:
    """``data`` with setup's block ``name`` taken out: replaced by the
    text of the user's that it replaced, where the record holds one, and
    otherwise removed with the line ending that came with it. None when
    the block is not there."""
    replaced = known.get("replaced") if isinstance(known, dict) else None
    if isinstance(replaced, dict) and isinstance(replaced.get("text"), str):
        return blocks.swap(data, syntax, name, replaced["text"].encode("utf-8"))
    return blocks.drop(data, syntax, name, _joint_of(known))


def _operation(before: _State, after: _State) -> str | None:
    if before.kind == after.kind:
        if before.kind == FILE:
            # No mode asked for means the file keeps the one it has.
            return None if before.data == after.data and after.mode in (None, before.mode) else _WRITE
        if before.kind == LINK:
            return None if fsio.same_target(before.target or "", after.target or "") else _RELINK
        return None
    if before.kind == ABSENT:
        return {FILE: _WRITE, DIRECTORY: _MKDIR, LINK: _LINK}[after.kind]
    if after.kind == ABSENT:
        return {FILE: _REMOVE, DIRECTORY: _RMDIR, LINK: _UNLINK}[before.kind]
    if before.real is not None or after.real is not None:
        raise SetupError(f"setup cannot turn a {before.kind} into a {after.kind} through a link")
    return _SWAP
