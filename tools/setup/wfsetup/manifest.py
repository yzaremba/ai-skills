"""The install record: what setup made, and where its state is kept.

Places
    <home>/.agents/workflow-setup/manifest.json        the user-level record
    <home>/.agents/workflow-setup/backups/<stamp>/     one directory per run
    <home>/.agents/workflow-setup/lock                 while a run writes
    <project>/.agents/workflow-setup/manifest.json     a project's record
    <project>/.agents/workflow-setup/backups/<stamp>/  its backups
    <project>/.agents/workflow-setup/lock              its lock

A project's state is in the project, whole: its record, the backups of its
files and its lock. A copy of a project directory therefore carries its own
state, and a project that two homes use (the two sides of one machine) has
one record whichever home runs setup. Nothing of a project is kept in a
home, and nothing of a home in a project.

A path is never stored as this machine writes it (R6.10). It is stored as
``<anchor>:<relative path>`` with ``/`` between the parts, ``.`` for the
anchor's own directory:

    home:     the user's home (``--home``)
    project:  the project (``--project``)
    clone:    the repository setup runs from; only ever a link's target,
              never written to
    <name>:   a further directory a command names in ``Roots.extra``, for a
              provider home that an environment variable puts outside the
              user's home (P5.2)

A path belongs to the deepest anchor that holds it. What lies under
``project:`` is recorded in the project's record, everything else in the
user-level one. A link's target is stored the same way; the target of a
link the user made, which setup removed and must be able to put back, may
point anywhere and is stored as ``raw:<the link's own text>``. That is the
one place a machine's path form can appear, and it is the user's data, kept
like the bytes of a file in a backup.

The file
    {"schema_version": 1,
     "entries": {"<path>": {"kind": ...}},   what setup is answerable for
     "backups": [...],                       every backup taken, in order
     "pending": [...],                       only while a run is under way
     "run": {"token": "<8 hex digits>"}}     with ``pending``: the run's token

``run`` names the temporary files of the run that is under way
(``fsio.temporary_names``): it is saved before the first of them is made, so
a later run removes exactly those, beside the paths ``pending`` lists, and
nothing that merely looks like one.

    kind          further keys
    directory     (setup created it)
    link          target, replaced            ``replaced``, where setup's link
                                              took the place of a link or a
                                              directory of the user's: the
                                              ``removed-link`` or
                                              ``removed-directory`` entry
                                              of what was there, put back
                                              when the link goes
    file          sha256, inputs, original,   a file setup wrote whole.
                  rewritten                   ``rewritten``, true once setup
                                              wrote it over a version its
                                              owner had edited (a settings
                                              file): it then holds what its
                                              owner put there, whatever its
                                              hash says
    text          sha256, created, original, syntax, blocks, removed_lines
    json          sha256, created, original, keys
    removed-file  original                    a user's file setup removed
    removed-link  target, directory           a user's link setup removed;
                  junction                    true when it was a Windows
                                              junction, so that it is put
                                              back as one
    removed-directory  mode                   a user's directory setup
                                              removed once the same run had
                                              emptied it; what it held is
                                              listed by its own entries.
                                              ``mode``, its permission bits,
                                              only where they are not the
                                              ones a new directory gets

``sha256`` is the hash of the whole file as setup last left it. ``inputs``
is the digest the caller gave for what a generated file was made from.
``original`` points at the backup of the bytes that were there before setup
first touched the path: ``{"backup": <path>, "sha256": ..., "mode": ...}``,
or null when nothing was there. For ``text`` and ``json`` it is dropped to
null as soon as the file is found changed by someone else, because the
backup is then no longer what the file would be without setup. ``blocks``
maps a block's name to the hash of its bytes; ``removed_lines`` is a list
of runs, each a list of ``{"index", "text", "eol"}``; ``keys`` maps a key
to ``{"value": <what setup set>, "had": <was it there>, "previous": ...}``.
A block or a key that setup wrote over text of the user's, because it was
asked to, says so as ``replaced``: for a block ``{"text": <the lines that
were there, markers included>, "backup": <path>}``, for a key (whose
``previous`` is the value that was there) ``{"backup": <path>}``. The
backup is the copy of the file as it was before that run. Where the text
cannot be put back in its place when setup's part goes, the change that
gives the record up names that backup under ``unlist``: it is taken out of
``backups`` and so is not removed with the record.

A backup is ``{"path", "kind": "file", "backup", "sha256", "mode", "stamp"}``
or, for a link, ``{"path", "kind": "link", "target", "directory", "stamp"}``:
a link is recorded, and what it leads to is never copied.

A record with a ``schema_version`` above ``SCHEMA_VERSION`` was written by
a newer setup and is refused. A record that does not parse is refused and
never overwritten.

A record is data from the disk, and setup acts on it
    A project's record travels with a checkout, so it may have been written
    by anyone. Every record is therefore checked whole when it is loaded,
    and one that fails is refused in one line that names the file and the
    entry; nothing is done with any part of it.

    - The form: each entry, backup and pending change has the keys of its
      kind, of the types setup writes. An entry of a kind this setup does
      not know is let through and left alone by every command.
    - The reach of a record. A project's record names only paths of the
      project: every entry, every listed backup and every pending change
      has a ``project:`` path, and no other anchor appears in it at all (a
      link's target is ``project:`` or ``raw:``). The user-level record
      names no ``project:`` path, as a path or as a target. Neither names a
      root itself, the clone, setup's own state, or anything under a
      ``.git`` directory.
    - Backups. A backup is where setup wrote it and nowhere else: under the
      ``backups/<stamp>/<anchor>/`` of the record's own state directory, at
      the very path of the entry it belongs to. So a project's record can
      make setup read, and later remove, only a backup inside that project,
      of that same project path.

    What is left to a project's record is the project: its own files, the
    links in it, the keys of its settings files that ``manifest-keys.json``
    lists. A link it asks to be put back may point anywhere, as a link in
    a checkout may; where it is made is still inside the project (``fsio``
    refuses any change whose real place is not).

An interrupted run: see ``fileops`` for the order of writes. ``pending``
lists the changes a run was about to make, each with the state the path was
to have ``after`` it. ``Record`` settles the list when it loads, in memory;
the next run that writes saves the outcome:

    made      the path is as the change was to leave it: its entry and its
              backup are taken into the record. A removal counts as made
              as soon as the path does not hold what was removed: where
              something else is there again, the backup is the only copy
              of the user's file, and its entry keeps it.
    half      a path that was to hold a thing of another kind (a directory
              and then setup's link) holds nothing: what was there was
              taken away and the other was not made. The entry that the
              taking away alone leaves (``between``) is recorded.
    not made  anything else: the change is dropped. Its backup, where one
              was written, stays on disk and stays listed in ``backups``:
              no backup is ever removed but with the record that lists it.
    unknown   the path is under a root this run was not given: the change
              stays pending for a run that has the root.

    Reading the disk for this never goes through a link that setup itself
    makes or removes: below a path that this record lists as a link, or
    that the pending list changes, a path that now lies under a link is
    read as absent. What the disk shows there is what the link leads to
    (the clone's own files), not what the run did. A link of the user's,
    which ``--follow-config-symlinks`` writes through, is followed. A
    change whose file backup is not on disk was not made: every backup of
    a run is written before its first change.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from . import fsio, paths
from .errors import SetupError

SCHEMA_VERSION = 1

HOME = "home"
PROJECT = "project"
CLONE = "clone"
RAW = "raw"

STATE_PARTS = (".agents", "workflow-setup")
MANIFEST_NAME = "manifest.json"
BACKUPS_NAME = "backups"
STATE_RELATIVE = "/".join(STATE_PARTS)

# Where the backups of the user level are, as a record writes it, and
# those of a project.
BACKUPS_KEY = f"{HOME}:{STATE_RELATIVE}/{BACKUPS_NAME}"
PROJECT_BACKUPS_KEY = f"{PROJECT}:{STATE_RELATIVE}/{BACKUPS_NAME}"


def scope_of(key: str) -> str:
    """Whose record lists the path ``key``: ``PROJECT`` or ``HOME``."""
    return PROJECT if key.partition(":")[0] == PROJECT else HOME


def backups_key(scope: str | None) -> str:
    return PROJECT_BACKUPS_KEY if scope == PROJECT else BACKUPS_KEY

_ANCHOR = re.compile(r"[a-z][a-z0-9-]*")
_STAMP = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[0-9a-f]{8}")

# What a pending change was found to be; see the module.
MADE, HALF, NOT_MADE, UNKNOWN = "made", "half", "not-made", "unknown"


# --- The form of a record ----------------------------------------------------------

def split_key(key: Any) -> tuple[str, str] | None:
    """The anchor and the relative path of a key a record may hold, or None
    for anything else: no anchor, a part that leads up or out, a separator
    of another system."""
    if not isinstance(key, str):
        return None
    anchor, colon, relative = key.partition(":")
    if not colon or not _ANCHOR.fullmatch(anchor) or anchor == RAW:
        return None
    if relative == ".":
        return anchor, relative
    parts = relative.split("/")
    if not relative or any(part in ("", ".", "..") or "\\" in part or ":" in part or "\0" in part for part in parts):
        return None
    return anchor, relative


def backup_key(stamp: str, key: str) -> str:
    """Where the backup of the path ``key`` taken by the run ``stamp`` is:
    in the state of the record that lists the path."""
    anchor, _, relative = key.partition(":")
    return f"{backups_key(scope_of(key))}/{stamp}/{anchor}/{relative}"


def is_state_key(key: str, itself: bool = True) -> bool:
    """Whether ``key`` names setup's own state: what lies below a state
    directory and, with ``itself``, that directory."""
    anchor, _, relative = key.partition(":")
    if anchor not in (HOME, PROJECT):
        return False
    folded, state = paths.fold_key(relative), paths.fold_key(STATE_RELATIVE)
    return folded.startswith(state + "/") or (itself and folded == state)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _path_fault(key: Any, scope: str | None) -> str | None:
    found = split_key(key)
    if found is None:
        return "not a path a record may hold"
    anchor, relative = found
    if relative == ".":
        return "a root itself, which setup never changes"
    if anchor == CLONE:
        return "a path in the clone, which setup never changes"
    if scope == PROJECT and anchor != PROJECT:
        return "a project's record lists only paths of the project"
    if scope == HOME and anchor == PROJECT:
        return "the user-level record lists no path of a project"
    if is_state_key(key, itself=False):
        return "setup's own state, which no record lists"
    if any(paths.fold_key(part) == ".git" for part in relative.split("/")):
        return "a path in a .git directory, which setup never changes"
    if fsio.is_credentials(relative):
        return "a credentials file, which setup never touches"
    return None


def _target_fault(target: Any, scope: str | None = None) -> str | None:
    if not isinstance(target, str):
        return "its target is not text"
    if target.startswith(f"{RAW}:"):
        return None if "\0" not in target else "its target is not a link's text"
    found = split_key(target)
    if found is None:
        return "its target is not a path a record may hold"
    if scope == PROJECT and found[0] != PROJECT:
        return "its target is outside the project; a project's record names only the project"
    if scope == HOME and found[0] == PROJECT:
        return "its target is in a project; the user-level record names no project"
    return None


def _reference_fault(reference: Any, key: str) -> str | None:
    """A pointer at the backup of ``key``: in the state directory of the
    record that lists ``key``, and nowhere else."""
    if not isinstance(reference, dict):
        return "its backup is not in the form setup writes"
    backup = reference.get("backup")
    base = backups_key(scope_of(key)) if isinstance(key, str) else BACKUPS_KEY
    if not isinstance(backup, str) or not backup.startswith(f"{base}/"):
        return "its backup is not under the backups directory of this record's own state"
    stamp, _, rest = backup[len(base) + 1:].partition("/")
    anchor, _, relative = rest.partition("/")
    if not _STAMP.fullmatch(stamp) or split_key(backup) is None:
        return "its backup is not under the backups directory of this record's own state"
    if paths.fold_key(f"{anchor}:{relative}") != paths.fold_key(key):
        return "its backup is not the backup of this path"
    if not isinstance(reference.get("sha256"), str) or not _SHA256.fullmatch(reference["sha256"]):
        return "its backup has no hash"
    if reference.get("mode") is not None and not _is_int(reference["mode"]):
        return "its backup's mode is not a number"
    return None


def _held_fault(backup: Any, key: str) -> str | None:
    """The key of a backup that holds text of the user's which setup
    replaced at the path ``key``: a backup of that very path, in the state
    of the record that lists it."""
    base = backups_key(scope_of(key)) if isinstance(key, str) else BACKUPS_KEY
    if not isinstance(backup, str) or not backup.startswith(f"{base}/") or split_key(backup) is None:
        return "not under the backups directory of this record's own state"
    stamp, _, rest = backup[len(base) + 1:].partition("/")
    anchor, _, relative = rest.partition("/")
    if not _STAMP.fullmatch(stamp) or paths.fold_key(f"{anchor}:{relative}") != paths.fold_key(key):
        return "not the backup of this path"
    return None


def _hash_fault(entry: dict[str, Any]) -> str | None:
    value = entry.get("sha256")
    return None if value is None or isinstance(value, str) else "its hash is not text"


def _original_fault(entry: dict[str, Any], key: str) -> str | None:
    original = entry.get("original")
    return None if original is None else _reference_fault(original, key)


def _removed_fault(entry: dict[str, Any], scope: str | None = None) -> str | None:
    """An entry of a link or a directory of the user's that setup removed."""
    if entry.get("kind") == "removed-link":
        for name in ("directory", "junction"):
            if name in entry and not isinstance(entry[name], bool):
                return f"its {name} is not true or false"
        return _target_fault(entry.get("target"), scope)
    if "mode" in entry and entry["mode"] is not None and not _is_int(entry["mode"]):
        return "its mode is not a number"
    return None


def entry_fault(key: str, entry: Any) -> str | None:
    """Why ``entry`` is not an entry setup writes for the path ``key``."""
    if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str):
        return "not an entry with a kind"
    kind = entry["kind"]
    scope = scope_of(key) if isinstance(key, str) else None
    if kind == "directory":
        return None
    if isinstance(key, str) and is_state_key(key):
        return "setup's own state directory, which a record lists only as a directory setup created"
    if kind == "link":
        replaced = entry.get("replaced")
        if replaced is not None:
            if not isinstance(replaced, dict) or replaced.get("kind") not in ("removed-link", "removed-directory"):
                return "what it took the place of is not a link or a directory setup removed"
            fault = _removed_fault(replaced, scope)
            if fault is not None:
                return f"what it took the place of: {fault}"
        return _target_fault(entry.get("target"), scope)
    if kind in ("removed-link", "removed-directory"):
        return _removed_fault(entry, scope)
    if kind == "removed-file":
        return _original_fault(entry, key)
    if kind == "file":
        if entry.get("inputs") is not None and not isinstance(entry["inputs"], str):
            return "its inputs digest is not text"
        if "rewritten" in entry and not isinstance(entry["rewritten"], bool):
            return "its rewritten mark is not true or false"
        return _hash_fault(entry) or _original_fault(entry, key)
    if kind in ("text", "json"):
        if "created" in entry and not isinstance(entry["created"], bool):
            return "its created mark is not true or false"
        fault = _hash_fault(entry) or _original_fault(entry, key)
        if fault is not None:
            return fault
    if kind == "text":
        if entry.get("syntax") is not None and not isinstance(entry["syntax"], str):
            return "its syntax is not text"
        found = entry.get("blocks", {})
        if not isinstance(found, dict):
            return "its blocks are not a table"
        for name, block in found.items():
            if not isinstance(block, dict) or not isinstance(block.get("sha256"), str):
                return f"its block {name or '(unnamed)'} has no hash"
            how = block.get("joint")
            if how is not None and (
                not isinstance(how, dict) or how.get("where") not in (None, "before", "after")
                or not isinstance(how.get("blank", False), bool)
                or not isinstance(how.get("line", ""), str)
            ):
                return f"its block {name or '(unnamed)'} does not say how it was joined in the form setup writes"
            replaced = block.get("replaced")
            if replaced is not None and (
                not isinstance(replaced, dict) or not isinstance(replaced.get("text"), str)
                or ("backup" in replaced and _held_fault(replaced["backup"], key) is not None)
            ):
                return f"its block {name or '(unnamed)'} does not hold what it replaced in the form setup writes"
        runs = entry.get("removed_lines", [])
        if not isinstance(runs, list):
            return "its removed lines are not a list"
        for run in runs:
            if not isinstance(run, list):
                return "its removed lines are not a list of runs"
            for line in run:
                if (
                    not isinstance(line, dict) or not _is_int(line.get("index")) or line["index"] < 0
                    or not isinstance(line.get("text"), str) or "\n" in line["text"] or "\r" in line["text"]
                    or line.get("eol", "") not in ("", "\n", "\r\n")
                ):
                    return "a removed line is not in the form setup writes"
        return None
    if kind == "json":
        keys = entry.get("keys", {})
        if not isinstance(keys, dict):
            return "its keys are not a table"
        for name, known in keys.items():
            if not isinstance(known, dict) or "value" not in known or not isinstance(known.get("had", False), bool):
                return f"its key {name} is not in the form setup writes"
            replaced = known.get("replaced")
            if replaced is not None and (
                not isinstance(replaced, dict)
                or ("backup" in replaced and _held_fault(replaced["backup"], key) is not None)
            ):
                return f"its key {name} does not say what it replaced in the form setup writes"
        return None
    return None  # a kind of a later setup: listed, and left alone


def _backup_fault(item: Any, scope: str | None, path: str | None = None) -> str | None:
    """One line of ``backups``, or the backup of a pending change."""
    if not isinstance(item, dict):
        return "not a backup in the form setup writes"
    fault = _path_fault(item.get("path"), scope)
    if fault is not None:
        return fault
    if path is not None and paths.fold_key(item["path"]) != paths.fold_key(path):
        return "the backup of another path"
    if item.get("kind") == "file":
        return _reference_fault(item, item["path"])
    if item.get("kind") == "link":
        if "directory" in item and not isinstance(item["directory"], bool):
            return "its directory mark is not true or false"
        return _target_fault(item.get("target"), scope_of(item["path"]))
    return "a backup of neither a file nor a link"


def _pending_fault(item: Any, scope: str | None) -> str | None:
    if not isinstance(item, dict):
        return "not a change in the form setup writes"
    fault = _path_fault(item.get("path"), scope)
    if fault is not None:
        return fault
    key = item["path"]
    after = item.get("after")
    if after is not None:
        if not isinstance(after, dict) or after.get("kind") not in (fsio.ABSENT, fsio.FILE, fsio.DIRECTORY, fsio.LINK):
            return "the state it was to leave is not one setup writes"
        if after["kind"] == fsio.FILE and not isinstance(after.get("sha256"), str):
            return "the file it was to leave has no hash"
        if after["kind"] == fsio.LINK and _target_fault(after.get("target"), scope_of(key)) is not None:
            return "the link it was to leave has no target a record may hold"
        if "mode" in after and after["mode"] is not None and not _is_int(after["mode"]):
            return "the mode it was to leave is not a number"
    if "set" in item and not isinstance(item["set"], bool):
        return "its set mark is not true or false"
    gone = item.get("unlist")
    if gone is not None and (not isinstance(gone, list) or any(_held_fault(one, key) for one in gone)):
        return "the backups it takes out of the record are not backups of this path"
    holders = [item]
    between = item.get("between")
    if between is not None:
        if not isinstance(between, dict):
            return "its half-way entry is not in the form setup writes"
        holders.append(between)
    for holder in holders:
        if holder.get("entry") is not None:
            fault = entry_fault(key, holder["entry"])
            if fault is not None:
                return fault
    if item.get("backup") is not None:
        return _backup_fault(item["backup"], scope, key)
    return None


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a value JSON has")


def _absolute(path: Path | str) -> Path:
    return paths.absolute(path)


def _relative(path: Path, root: Path) -> str | None:
    """``path`` below ``root`` with ``/`` between the parts, ``.`` for the
    root itself, None when it is elsewhere."""
    text, base = str(path), str(root)
    folded, folded_base = paths.fold(text), paths.fold(base)
    if folded == folded_base:
        return "."
    stem = folded_base.rstrip(os.sep)
    if not folded.startswith(stem + os.sep):
        return None
    return text[len(stem) + 1:].replace(os.sep, "/")


@dataclass(frozen=True)
class Roots:
    """The directories setup may write below, and the clone it links to."""

    home: Path
    project: Path | None = None
    clone: Path | None = None
    extra: tuple[tuple[str, Path], ...] = ()
    # Where the clone was when setup made its links, if it was moved since
    # (``uninstall --clone-was``). It is one more place a link of setup's
    # may lead to, and nothing else: the clone stays the clone.
    clone_was: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "home", _absolute(self.home))
        for name in ("project", "clone", "clone_was"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _absolute(getattr(self, name)))
        extra = tuple((name, _absolute(path)) for name, path in dict(self.extra).items())
        for name, _ in extra:
            if not _ANCHOR.fullmatch(name) or name in (HOME, PROJECT, CLONE, RAW):
                raise SetupError(f"{name}: not a name for a further root")
        object.__setattr__(self, "extra", extra)

    @classmethod
    def of(cls, locations: Any, extra: dict[str, Path] | None = None) -> "Roots":
        """The roots of a run's ``Locations``."""
        return cls(locations.home, locations.project, locations.clone, tuple((extra or {}).items()))

    def anchors(self) -> list[tuple[str, Path]]:
        found = [(HOME, self.home)]
        if self.project is not None:
            found.append((PROJECT, self.project))
        found.extend(self.extra)
        if self.clone is not None:
            found.append((CLONE, self.clone))
        return found

    def root(self, anchor: str) -> Path:
        for name, root in self.anchors():
            if name == anchor:
                return root
        raise SetupError(f"{anchor}: the record names a root this run was not given")

    def key(self, path: Path | str, target: bool = False) -> str | None:
        """``path`` as the record writes it, or None when no root holds it.
        Where two roots are the same directory, a link's target (``target``)
        is the clone's and anything else is not."""
        path = _absolute(path)
        best: tuple[int, int, str] | None = None
        for name, root in self.anchors():
            relative = _relative(path, root)
            if relative is None:
                continue
            rank = (len(root.parts), int((name == CLONE) == target), f"{name}:{relative}")
            if best is None or rank[:2] > best[:2]:
                best = rank
        return None if best is None else best[2]

    def path(self, key: str) -> Path:
        """The path a record entry names. An entry that would lead out of
        its root is refused: a record is data, and setup acts on it."""
        anchor, _, relative = key.partition(":")
        root = self.root(anchor)
        if relative == ".":
            return root
        parts = relative.split("/")
        if not relative or any(part in ("", ".", "..") or "\\" in part or ":" in part for part in parts):
            raise SetupError(f"{key}: not a path the record may hold")
        return root.joinpath(*parts)

    def target_key(self, text: str, scope: str | None = None) -> str:
        """A link's text as the record of ``scope`` writes it. A project's
        record names the project and nothing else, and the user-level one
        no project: a target the record may not name by an anchor is kept
        as the link's own text."""
        if os.path.isabs(text):
            key = self.key(text, target=True)
            if key is not None:
                inside = key.partition(":")[0] == PROJECT
                if scope is None or (scope == PROJECT) == inside:
                    return key
        return f"{RAW}:{text}"

    def target_text(self, key: str) -> str:
        """The text of a link whose target the record holds as ``key``."""
        anchor, _, rest = key.partition(":")
        return rest if anchor == RAW else str(self.path(key))

    def target_texts(self, key: str) -> list[str]:
        """Every text a link of setup's to ``key`` may have: the one above
        and, for a target in the clone, the same place below ``clone_was``."""
        texts = [self.target_text(key)]
        anchor, _, relative = key.partition(":")
        if anchor == CLONE and self.clone_was is not None:
            was = self.clone_was if relative == "." else self.clone_was.joinpath(*relative.split("/"))
            texts.append(str(was))
        return texts

    def state_dir_of(self, project: bool) -> Path:
        """The state directory of the user level, or of the project."""
        root = self.project if project else self.home
        if root is None:
            raise SetupError("no project was named, so there is no project state")
        return root.joinpath(*STATE_PARTS)

    def manifest_file_of(self, project: bool) -> Path:
        return self.state_dir_of(project) / MANIFEST_NAME

    def backups_dir_of(self, project: bool) -> Path:
        return self.state_dir_of(project) / BACKUPS_NAME

    @property
    def state_dir(self) -> Path:
        return self.state_dir_of(False)

    @property
    def manifest_file(self) -> Path:
        return self.manifest_file_of(False)

    @property
    def backups_dir(self) -> Path:
        return self.backups_dir_of(False)

    @property
    def project_state_dir(self) -> Path | None:
        return None if self.project is None else self.state_dir_of(True)

    @property
    def project_manifest_file(self) -> Path | None:
        return None if self.project is None else self.manifest_file_of(True)

    def scopes(self) -> list[bool]:
        """False for the user level, and True for the project where one
        was named: the argument ``project`` of the functions above."""
        return [False] if self.project is None else [False, True]

    def is_state(self, path: Path) -> bool:
        """Whether ``path`` is setup's own state, which no command edits:
        a state directory, or anything in one."""
        path = _absolute(path)
        return any(_relative(path, self.state_dir_of(project)) is not None for project in self.scopes())

    def state_ancestors(self, project: bool) -> list[Path]:
        """The directories that hold a record, outermost first: they can go
        only after the record itself."""
        if project and self.project is None:
            return []
        state = self.state_dir_of(project)
        return [state.parent, state]

    def confinement(self, project: bool) -> tuple[list[Path], list[Path]]:
        """Where a change of the user level, or of the project, may be made
        (``fsio.confined``): the roots, and what is barred besides the
        clone the tool runs from. A change of a project stays in the
        project; a change of the home is made in no project and in no
        clone."""
        barred = [] if self.clone is None else [self.clone]
        if project:
            if self.project is None:
                raise SetupError("no project was named, so nothing of a project is changed")
            # The home's state is never a project's to change, and where
            # the home lies inside the project, nothing of the home is.
            barred.append(self.state_dir)
            if _relative(self.home, self.project) is not None:
                barred.append(self.home)
            return [self.project], barred
        if self.project is not None:
            barred.append(self.project)
        return [self.home, *[path for _, path in self.extra]], barred


class Manifest:
    """One record file. ``scope`` says whose it is, ``HOME`` or ``PROJECT``,
    and so which paths it may list; see the module."""

    def __init__(self, file: Path, scope: str | None = None) -> None:
        self.file = file
        self.scope = scope
        self.entries: dict[str, dict[str, Any]] = {}
        self.backups: list[dict[str, Any]] = []
        self.pending: list[dict[str, Any]] = []
        # The token of the run whose changes are pending; see the module.
        self.run: str | None = None
        self.on_disk = False
        self.dirty = False

    @classmethod
    def load(cls, file: Path, scope: str | None = None) -> "Manifest":
        manifest = cls(file, scope)
        try:
            # Looked at before it is opened: a FIFO there would be waited on.
            found = os.stat(file)
            if not stat.S_ISREG(found.st_mode):
                what = "a directory" if stat.S_ISDIR(found.st_mode) else "not a file"
                raise SetupError(f"{file}: is not a setup record: it is {what}")
            raw = file.read_bytes()
        except (FileNotFoundError, NotADirectoryError):
            return manifest
        except (OSError, ValueError) as exc:
            raise SetupError(f"{file}: cannot be read: {paths.reason(exc)}") from None
        try:
            data = json.loads(raw.decode("utf-8"), parse_constant=_no_constant)
        except RecursionError:
            raise SetupError(f"{file}: is not a setup record: it is nested too deeply") from None
        except ValueError as exc:
            raise SetupError(f"{file}: is not a setup record: {' '.join(str(exc).split())}") from None
        version = data.get("schema_version") if isinstance(data, dict) else None
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise SetupError(f"{file}: is not a setup record: it has no schema_version")
        if version > SCHEMA_VERSION:
            raise SetupError(
                f"{file}: written by a newer setup (schema_version {version}; this one reads up to "
                f"{SCHEMA_VERSION}); use the newer setup"
            )
        entries, backups, pending = data.get("entries", {}), data.get("backups", []), data.get("pending", [])
        if not isinstance(entries, dict) or not isinstance(backups, list) or not isinstance(pending, list):
            raise SetupError(f"{file}: is not a setup record: its entries are not in the form setup writes")
        manifest.entries, manifest.backups, manifest.pending = entries, backups, pending
        run = data.get("run")
        if run is not None:
            if not isinstance(run, dict) or not isinstance(run.get("token"), str) or not _TOKEN.fullmatch(run["token"]):
                raise SetupError(f"{file}: is not a setup record: its run is not in the form setup writes")
            manifest.run = run["token"]
        fault = manifest.fault()
        if fault is not None:
            raise SetupError(f"{file}: is not a setup record: {fault}")
        manifest.on_disk = True
        return manifest

    def fault(self) -> str | None:
        """The first thing in this record that setup would not write, as
        ``<where>: <why>``; None for a record that is in order."""
        def shown(key: Any) -> str:
            text = key if isinstance(key, str) else json.dumps(key, default=str)
            text = " ".join(text.split())
            return text if len(text) <= 120 else text[:117] + "..."

        folded: set[str] = set()
        for key, entry in self.entries.items():
            fault = _path_fault(key, self.scope) or entry_fault(key, entry)
            if fault is not None:
                return f"entry {shown(key)}: {fault}"
            if paths.fold_key(key) in folded:
                return f"entry {shown(key)}: listed twice, in two letter cases"
            folded.add(paths.fold_key(key))
        for index, item in enumerate(self.backups, 1):
            fault = _backup_fault(item, self.scope)
            if fault is not None:
                where = shown(item.get("path")) if isinstance(item, dict) else "?"
                return f"backup {index} ({where}): {fault}"
        for index, item in enumerate(self.pending, 1):
            fault = _pending_fault(item, self.scope)
            if fault is not None:
                where = shown(item.get("path")) if isinstance(item, dict) else "?"
                return f"pending change {index} ({where}): {fault}"
        return None

    def to_bytes(self) -> bytes:
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "entries": self.entries,
            "backups": self.backups,
        }
        if self.pending:
            data["pending"] = self.pending
        if self.run is not None:
            data["run"] = {"token": self.run}
        try:
            return (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        except (ValueError, UnicodeEncodeError) as exc:
            raise SetupError(f"{self.file}: the record cannot be saved: {' '.join(str(exc).split())}") from None

    def save(self) -> None:
        """Write the record. It is checked like one that is read: setup
        never saves a record it would refuse to load."""
        fault = self.fault()
        if fault is not None:
            raise SetupError(f"{self.file}: the record cannot be saved: {fault}")
        fsio.atomic_write(self.file, self.to_bytes())
        self.on_disk = True
        self.dirty = False

    def find(self, key: str) -> str | None:
        """The key as this record spells it. Windows ignores letter case in
        a path, so the lookup does there."""
        if key in self.entries:
            return key
        if not paths.CASE_SENSITIVE:
            folded = paths.fold_key(key)
            for known in self.entries:
                if paths.fold_key(known) == folded:
                    return known
        return None

    def commit(self, item: dict[str, Any]) -> None:
        """Take one change of a run into the record."""
        if item.get("set"):
            known = self.find(item["path"])
            if item.get("entry") is None:
                if known is not None:
                    del self.entries[known]
            else:
                self.entries[known or item["path"]] = item["entry"]
        self.keep_backup(item.get("backup"))
        gone = item.get("unlist")
        if isinstance(gone, list) and gone:
            # Backups that hold text of the user's which was not put back:
            # they leave the list, and so stay on disk when the record goes.
            self.backups = [
                backup for backup in self.backups
                if not (isinstance(backup, dict) and backup.get("backup") in gone)
            ]

    def keep_backup(self, backup: Any) -> None:
        """List a backup, once: a backup that was written stays listed
        whether its change was made or not, and goes only with the record."""
        if isinstance(backup, dict) and backup not in self.backups:
            self.backups.append(backup)

    def needed_backups(self) -> set[str]:
        """Every backup this record points at, by its key: the listed ones,
        the originals of its entries and those of its pending changes."""
        found: set[str] = set()

        def of(entry: Any) -> None:
            if isinstance(entry, dict):
                for value in (entry.get("original"), entry.get("backup")):
                    if isinstance(value, dict) and isinstance(value.get("backup"), str):
                        found.add(value["backup"])
                    elif isinstance(value, str):
                        found.add(value)

        for item in self.backups:
            of({"backup": item.get("backup")})
        for entry in self.entries.values():
            of(entry)
        for item in self.pending:
            of(item.get("backup"))
            of({"backup": (item.get("backup") or {}).get("backup")})
            of(item.get("entry"))
            of((item.get("between") or {}).get("entry"))
        return found


class Record:
    """Both records of a run, read as one.

    ``entries`` and ``backups`` are what a command such as ``doctor`` reads;
    ``path(key)`` turns an entry's key into a path of this machine.
    ``recovered`` and ``dropped`` count the changes of an interrupted run
    that were found made (wholly, or half), and not made, when the record
    was loaded; ``recovered_paths`` and ``dropped_paths`` name them. The
    backup of a dropped change stays on disk and stays listed.
    ``interrupted`` holds, for each record, the token of the run that was
    interrupted and the paths its pending changes named: where that run
    may have left a file under its temporary name.
    """

    def __init__(self, roots: Roots) -> None:
        self.roots = roots
        self.home = Manifest.load(roots.manifest_file, HOME)
        mine = roots.project_manifest_file
        self.project = None if mine is None else Manifest.load(mine, PROJECT)
        self.recovered = 0
        self.dropped = 0
        # The same changes by the path each names, for a report.
        self.recovered_paths: list[str] = []
        self.dropped_paths: list[str] = []
        # Every path a pending change named, settled or not: where a killed
        # run may have left a temporary file.
        self.pending_paths: list[str] = [
            str(item.get("path")) for manifest in self.manifests() for item in manifest.pending
        ]
        self.interrupted: list[tuple[Manifest, str, list[str]]] = [
            (manifest, manifest.run, [str(item.get("path")) for item in manifest.pending])
            for manifest in self.manifests() if manifest.run is not None
        ]
        self._recover()

    def manifests(self) -> list[Manifest]:
        return [self.home] if self.project is None else [self.home, self.project]

    def manifest_for(self, key: str) -> Manifest:
        if key.partition(":")[0] == PROJECT and self.project is not None:
            return self.project
        return self.home

    def get(self, key: str) -> dict[str, Any] | None:
        manifest = self.manifest_for(key)
        known = manifest.find(key)
        return None if known is None else manifest.entries[known]

    def path(self, key: str) -> Path:
        return self.roots.path(key)

    @property
    def entries(self) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for manifest in self.manifests():
            merged.update(manifest.entries)
        return merged

    @property
    def backups(self) -> list[dict[str, Any]]:
        return [backup for manifest in self.manifests() for backup in manifest.backups]

    def __iter__(self) -> Iterator[tuple[str, dict[str, Any]]]:
        return iter(self.entries.items())

    @property
    def dirty(self) -> bool:
        return any(manifest.dirty for manifest in self.manifests())

    # --- An interrupted run -------------------------------------------------------

    def _recover(self) -> None:
        # The paths setup itself was making or removing links at: nothing
        # below one of them is read through it.
        concerned = {
            paths.fold_key(str(item.get("path"))) for manifest in self.manifests() for item in manifest.pending
        }
        concerned |= {
            paths.fold_key(key) for manifest in self.manifests()
            for key, entry in manifest.entries.items() if entry.get("kind") == "link"
        }
        for manifest in self.manifests():
            if not manifest.pending:
                continue
            waiting: list[dict[str, Any]] = []
            for item in manifest.pending:
                outcome = self.settle(item, concerned)
                name = str(item.get("path"))
                if outcome == UNKNOWN:
                    waiting.append(item)
                    continue
                if outcome == MADE:
                    manifest.commit(item)
                elif outcome == HALF:
                    between = item.get("between") or {}
                    manifest.commit({
                        "path": item["path"], "set": True, "entry": between.get("entry"), "backup": item.get("backup"),
                    })
                if outcome in (MADE, HALF):
                    self.recovered += 1
                    self.recovered_paths.append(name)
                else:
                    self.dropped += 1
                    self.dropped_paths.append(name)
                    # The change goes; its backup, where one was written,
                    # stays where it is and stays listed.
                    backup = item.get("backup") or {}
                    if backup.get("kind") == "file" and self._backup_there(backup):
                        manifest.keep_backup(backup)
            if len(waiting) != len(manifest.pending):
                manifest.dirty = True
            manifest.pending = waiting
        for manifest in self.manifests():
            if manifest.run is not None and not manifest.pending:
                # The token goes with the list, once this record is saved;
                # ``interrupted`` keeps it for the run that cleans up.
                manifest.run = None
                manifest.dirty = True

    def _backup_there(self, backup: dict[str, Any]) -> bool:
        try:
            return fsio.is_file(self.roots.path(backup["backup"]))
        except (SetupError, KeyError, TypeError):
            return False

    def _seen(self, key: str, concerned: set[str]) -> tuple[fsio.Seen, bool]:
        """What is at the path ``key``, and whether it was read as absent
        because it lies under a link that setup itself makes or removes;
        see the module."""
        anchor, _, relative = key.partition(":")
        path = self.roots.path(key)
        parts = relative.split("/")
        above = self.roots.root(anchor)
        for index, part in enumerate(parts[:-1]):
            above = above / part
            if paths.fold_key(f"{anchor}:{'/'.join(parts[:index + 1])}") in concerned:
                if fsio.look(above).kind == fsio.LINK:
                    return fsio.Seen(fsio.ABSENT), True
        return fsio.look(path), False

    def settle(self, item: dict[str, Any], concerned: set[str] | None = None) -> str:
        """Whether the pending change ``item`` was made: ``MADE``, ``HALF``,
        ``NOT_MADE`` or ``UNKNOWN``; see the module."""
        after = item.get("after")
        if after is None:  # a change to the record alone
            return MADE
        if concerned is None:
            concerned = {paths.fold_key(str(item.get("path")))}
        try:
            self.roots.root(str(item["path"]).partition(":")[0])
        except SetupError:
            return UNKNOWN
        try:
            backup = item.get("backup") or {}
            if backup.get("kind") == "file" and not fsio.is_file(self.roots.path(backup["backup"])):
                return NOT_MADE  # nothing is changed before its backup is written
            path = self.roots.path(item["path"])
            seen, behind = self._seen(item["path"], concerned)
            kind = after.get("kind")
            if seen.kind == fsio.ABSENT and kind != fsio.ABSENT:
                return HALF if isinstance(item.get("between"), dict) and not behind else NOT_MADE
            if kind == fsio.ABSENT and seen.kind != fsio.ABSENT:
                # A removal, and something is there. It was not made only
                # if what is there is what was to be removed; anything else
                # was put there since, and the backup is the only copy.
                if backup.get("kind") == "file":
                    same = seen.kind == fsio.FILE and fsio.sha256(fsio.read_bytes(path)) == backup.get("sha256")
                    return NOT_MADE if same else MADE
                if backup.get("kind") == "link":
                    same = seen.kind == fsio.LINK and fsio.same_target(
                        seen.target or "", self.roots.target_text(backup["target"])
                    )
                    return NOT_MADE if same else MADE
                return NOT_MADE
            if kind == fsio.FILE:
                if seen.kind == fsio.LINK and os.path.isfile(path):
                    path = Path(os.path.realpath(path))
                elif seen.kind != fsio.FILE:
                    return NOT_MADE
                return MADE if fsio.sha256(fsio.read_bytes(path)) == after.get("sha256") else NOT_MADE
            if kind == fsio.LINK:
                same = seen.kind == fsio.LINK and fsio.same_target(
                    seen.target or "", self.roots.target_text(after["target"])
                )
                return MADE if same else NOT_MADE
            return MADE if seen.kind == kind else NOT_MADE
        except (SetupError, KeyError, TypeError):
            return NOT_MADE
