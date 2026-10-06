"""Take an install back: one record undone, reported, and its state removed.

How the command uses it

    found = homes.resolve(locations.from_args(args))
    outcome = uninstall.execute(found, project=args.project is not None,
                                dry_run=args.dry_run, follow=args.follow_config_symlinks)
    for line in uninstall.report_lines(outcome.report): print(line)
    return outcome.code

One call undoes one record: the user-level one, or with ``project`` the one
of ``found.project``. The way back itself is ``fileops.plan_reversal``; this
module decides what it is asked to leave alone, removes the state when
nothing is left to answer for, and says what happened.

What is kept, and why (``report["kept"]``; the entry stays in the record)
    - whatever ``fileops`` keeps: a link that no longer points where setup
      pointed it, a generated file that was edited, a block that was edited,
      a path where something is again that setup removed, a backup that is
      missing;
    - a path that is, or lies under, a link, without ``follow``: the plan
      would be refused for it, so it is taken out of the plan and the rest
      is done, as ``render`` skips such a place;
    - a path of a home whose real place is on the other side of the
      machine: never written from this side, with or without ``follow``.
      A project's paths are the project's on either side, as for
      ``render``.

What is left (``report["left"]``; the user's from now on, no entry stays)
    - a directory setup created that holds something of the user's;
    - a key of a JSON file whose value was changed since setup set it;
    - the settings file ``init`` wrote, once it holds anything its owner
      put there, and with ``keep_settings`` in every case; see below.

The state
    Each record has its own state directory, in the place it is the record
    of: ``~/.agents/workflow-setup`` for the user level, and
    ``DIR/.agents/workflow-setup`` for a project, each with its record, the
    backups of its files and its lock. When a record lists nothing more,
    its state goes: the backups it lists, the record, and the directories
    that held them. Undoing a project touches nothing of the home, and
    undoing the home nothing of a project.

    Setup removes no backup but the ones the record lists, and those only
    with the record. A file under the backups directory that no record
    lists (``fileops.unlisted_backups``) is left where it is, the state
    directory stays for it, it is named, and the code is ``EXIT_KEPT``.
    ``discard_backups`` removes such files, when the user asks for exactly
    that.

    A state directory that holds anything else setup did not put there (a
    file of the user's) stays as well, with what it holds named, and the
    code is ``EXIT_KEPT``: the uninstall is not finished while the
    directory is there.

The settings file ``init`` wrote
    Removed, or replaced by the file that was there before the first
    ``init``, only while it holds exactly what ``init`` wrote and ``init``
    never wrote it over a version its owner had edited
    (``fileops.REWRITTEN``). In every other case it holds values its owner
    set: it is left as it is (``report["left"]``), with ``keep_settings``
    or without.

What ``render --overwrite-edited`` replaced
    ``fileops`` puts it back where it was. A backup that holds such text
    which could not be put back is taken out of the record by the way back
    (``fileops.Result.unlisted``) and so stays, like any backup no record
    lists: named, the state directory stays, ``EXIT_KEPT``.

The code: 0 when everything was undone or nothing was recorded;
``EXIT_KEPT`` when an entry was kept or the state directory stays (for
backups that no record lists, or for something setup did not put there);
``errors.EXIT_ERROR`` when the plan was refused or a change failed.

A run that stops on an error says what is true of it: "nothing was
changed" where the record on disk is as it was before the run
and holds no change of an interrupted run (a state directory that cannot be
written stops the run before its first change), and "part way" otherwise.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import fileops, fsio, homes, lock, paths
from .errors import EXIT_ERROR, SetupError
from .locations import SETTINGS_DIR, SETTINGS_FILE
from .manifest import BACKUPS_NAME, MANIFEST_NAME, Manifest, Roots
import dataclasses

REPORT_SCHEMA_VERSION = 1
EXIT_KEPT = 3
PROG = "workflow_setup.py"

HOME = "home"
PROJECT = "project"

FOLLOW_OPTION = "--follow-config-symlinks"
KEEP_SETTINGS_OPTION = "--keep-settings"
DISCARD_OPTION = "--discard-backups"
CLONE_WAS_OPTION = "--clone-was"

_WHAT = {
    "link": "a link setup made",
    "file": "a file setup wrote",
    "text": "a text file of yours with setup's block or line edits in it",
    "json": "a settings file of yours with a key setup set in it",
    "removed-file": "a file of yours that setup removed",
    "removed-link": "a link of yours that setup removed",
    "removed-directory": "a directory of yours that setup removed",
    "directory": "a directory setup created",
}


@dataclass
class Outcome:
    report: dict[str, Any]
    code: int
    errors: list[str]


def _holders(roots: Roots, project: bool) -> set[str]:
    return {roots.key(path) or "" for path in roots.state_ancestors(project)}


def _listed(roots: Roots, manifest: Manifest, project: bool) -> list[str]:
    """The entries of a record that are not the directories that hold it."""
    holders = {paths.fold_key(key) for key in _holders(roots, project)}
    return [
        key for key, entry in manifest.entries.items()
        if not (paths.fold_key(key) in holders and entry.get("kind") == "directory")
    ]


def _path(roots: Roots, key: str) -> Path | None:
    try:
        return roots.path(key)
    except SetupError:
        return None


def _other_side(found: homes.Homes, roots: Roots, manifest: Manifest, project: bool) -> dict[Path, str]:
    """The paths of the user-level record whose real place is on the other
    side. A link is an entry of the directory it is in, so it is asked of
    that. A project is the project's on either side of the machine, as it
    is for ``render``: there only a link in the way is asked about."""
    kept: dict[Path, str] = {}
    if project or found.host.other is None:
        return kept
    for key in _listed(roots, manifest, project):
        path = _path(roots, key)
        if path is None:
            continue
        kind = manifest.entries[key].get("kind")
        probe = path.parent if kind in ("link", "removed-link") else path
        try:
            side = found.host.other_side(probe)
        except (OSError, ValueError):
            continue
        if side is not None:
            kept[path] = (
                f"its real place, {os.path.realpath(probe)}, is on the other side ({side}); this side "
                "writes nothing there"
            )
    return kept


def _settings_file(found: homes.Homes, project: bool) -> Path | None:
    root = found.project if project else found.home
    return None if root is None else root / SETTINGS_DIR / SETTINGS_FILE


def _settings_yours(path: Path, entry: dict[str, Any], keep_settings: bool, follow: bool) -> str | None:
    """Why the settings file ``init`` wrote is left where it is, as the
    user's, or None where it is undone like any file setup wrote.

    It is undone (removed, or replaced by the file that was there before
    the first ``init``) only while it holds exactly what ``init`` wrote and
    ``init`` never wrote it over a version its owner had edited. In every
    other case it holds something its owner put there, and no hash says
    which part: it stays, whole."""
    if keep_settings:
        return f"the settings file stays as it is, and is yours, as {KEEP_SETTINGS_OPTION} says"
    if entry.get(fileops.REWRITTEN) is True:
        return (
            "`init` rewrote it from a version you had edited, so it holds values you set; the settings file stays "
            "as it is, and is yours"
        )
    try:
        seen = fsio.look(path)
        if seen.kind == fsio.ABSENT or (seen.kind == fsio.LINK and not follow) or not fsio.is_file(path):
            return None  # gone, or not a file to read: the way back says what it says of any file
        digest = fsio.sha256(fsio.read_bytes(path))
    except SetupError:
        return None
    original = entry.get("original")
    if digest == entry.get("sha256") or (isinstance(original, dict) and digest == original.get("sha256")):
        return None
    return "it was edited since `init` wrote it, so it holds what you put there; the settings file stays as it is, and is yours"


def _backup_of(roots: Roots, entry: dict[str, Any] | None) -> str | None:
    """The backup that belongs to a kept entry: of the file as it was
    before setup, or else of the file as it was before setup replaced text
    of the user's in it on request (``render --overwrite-edited``)."""
    original = (entry or {}).get("original")
    found = original.get("backup") if isinstance(original, dict) else None
    if not isinstance(found, str):
        for table in ("blocks", "keys"):
            items = (entry or {}).get(table)
            for known in (items.values() if isinstance(items, dict) else ()):
                replaced = known.get("replaced") if isinstance(known, dict) else None
                if isinstance(replaced, dict) and isinstance(replaced.get("backup"), str):
                    found = found if isinstance(found, str) else replaced["backup"]
    if not isinstance(found, str):
        return None
    path = _path(roots, found)
    return None if path is None else str(path)


def _clone_hint(roots: Roots, path: Path | None, entry: dict[str, Any] | None) -> str | None:
    """Where the clone was, if the link at ``path`` still names the place
    the record holds, below another directory."""
    target = (entry or {}).get("target")
    if path is None or not isinstance(target, str) or not target.startswith("clone:"):
        return None
    try:
        seen = fsio.look(path)
    except SetupError:
        return None
    if seen.kind != fsio.LINK or not seen.target:
        return None
    relative = target.partition(":")[2].replace("/", os.sep)
    text = os.path.normpath(paths.long_form(fsio.clean_target(seen.target)))
    tail = os.sep + relative
    if relative in ("", ".") or not paths.fold(text).endswith(paths.fold(tail)):
        return None
    return text[:len(text) - len(tail)] or None


def _finish(roots: Roots, key: str, path: Path | None, entry: dict[str, Any] | None, why: str,
            settings_file: Path | None) -> str:
    """What the user does about one kept entry, in one line."""
    kind = (entry or {}).get("kind")
    if FOLLOW_OPTION in why:
        return f"give {FOLLOW_OPTION} to undo it where the link leads, or take the link away"
    if "on the other side" in why:
        return "take away the link that leads there, or undo this entry by hand; this side never writes there"
    if "is outside the directories this run may write to" in why or "which setup never writes to" in why:
        return "take away the link that leads there, or undo this entry by hand; setup writes there under no option"
    if "is a link now, which was kept" in why:
        return "deal with the link above it first"
    if kind == "removed-link" and CLONE_WAS_OPTION in why:
        return f"run uninstall again with {CLONE_WAS_OPTION} DIR, DIR being the directory the clone was in when setup removed the link"
    if "missing or damaged" in why:
        return "what was there cannot be put back; remove the file, or the record by hand (see --help)"
    if kind == "link":
        was = _clone_hint(roots, path, entry)
        if was is not None:
            return (
                f"it leads into {was}: if that is where the clone was when setup made the link, run uninstall "
                f"with {CLONE_WAS_OPTION} {was}; else remove the link"
            )
        return "remove what is there, or point the link back where setup pointed it"
    if kind == "file":
        if "removed since" in why:
            return "copy the backup back to the path"
        settings = "" if path is None or settings_file is None or not paths.same(
            path, settings_file) else f", or give {KEEP_SETTINGS_OPTION} to keep it as yours"
        return "remove the file, or put back what setup wrote" + settings
    if kind in ("text", "json"):
        if "was edited since setup wrote it" in why:
            return "remove the block with its markers, or put back between them what setup wrote"
        if "removed since" in why:
            return "copy the backup back to the path"
        return "correct the file so that setup can read it, or take setup's part out by hand and remove the file's entry"
    if kind == "removed-file":
        return "remove what is there and the backup is put back, or make it the same as the backup"
    if kind in ("removed-link", "removed-directory"):
        return "remove what is there, and what setup removed is put back"
    return "deal with it as said"


def _what(entry: dict[str, Any] | None) -> str:
    return _WHAT.get(str((entry or {}).get("kind")), "an entry of the record")


def _groups(lines: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """The plan's lines as what is removed, what is restored, what only
    leaves the record, and what is said of the record itself. A detail line
    stays with its change."""
    removed: list[str] = []
    restored: list[str] = []
    forgotten: list[str] = []
    record: list[str] = []
    current = record
    for line in lines:
        if line.startswith(" "):
            current.append(line)
            continue
        word = line.split(" ", 1)[0]
        if line == fileops.UP_TO_DATE:
            continue
        if word == "remove":
            current = removed
        elif word == "update":
            current = forgotten
        elif word == "complete":
            current = record
        else:
            current = restored  # restore, and a directory made again
        current.append(line)
    return removed, restored, forgotten, record


def _names(line: str, key: str) -> bool:
    """Whether a line of the plan is the change of the path ``key``."""
    words = line.split(" ")
    return (
        not line.startswith(" ") and len(words) >= 3 and words[1] == "file"
        and paths.fold_key(words[2]) == paths.fold_key(key)
    )


def _heads(lines: list[str]) -> int:
    return sum(1 for line in lines if not line.startswith(" "))


def roots_of(found: homes.Homes, clone_was: Path | None = None) -> Roots:
    """The roots of an uninstall. ``clone_was`` is where the clone was when
    setup made its links: one more place a link of setup's may lead to.
    The clone itself stays the one setup runs from, and stays barred."""
    roots = found.roots()
    return roots if clone_was is None else dataclasses.replace(roots, clone_was=clone_was)


def execute(found: homes.Homes, *, project: bool = False, dry_run: bool = False, follow: bool = False,
            keep_settings: bool = False, clone_was: Path | None = None,
            stamp: str | None = None) -> Outcome:
    """Undo one record of ``found`` and remove its state; see the module."""
    roots = roots_of(found, clone_was)
    if project and found.project is None:
        raise SetupError("no project was named, so there is no project record to undo")
    recovered: fileops.Result | None = None
    if not dry_run:
        # What an interrupted run left is settled first, as in every
        # command that writes.
        recovered = fileops.recover(roots, follow_config_symlinks=follow)
    record = fileops.read_record(roots)
    manifest = record.project if project else record.home
    assert manifest is not None
    scope = PROJECT if project else HOME
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "dry_run": dry_run,
        "applied": False,
        "changed": False,
        "exit_code": 0,
        "scope": scope,
        "side": found.host.side,
        "home": str(found.home),
        "project": None if found.project is None else str(found.project),
        "clone": str(found.clone),
        "record": str(manifest.file),
        "recorded": manifest.on_disk,
        "entries": 0,
        "removed": [], "restored": [], "forgotten": [], "left": [], "kept": [],
        "plan": [], "notes": [], "errors": [],
        "state": None,
    }
    if recovered is not None and recovered.changed:
        report["notes"].extend([*recovered.lines, *recovered.notes])
    if not manifest.on_disk:
        if not dry_run:
            # No record, but a killed run may have left its lock, an empty
            # state directory or the marker beside ``.agents``:
            # ``remove_state`` takes those away, and does nothing where
            # there is nothing.
            fileops.remove_state(roots, project=project, follow_config_symlinks=follow)
        unlisted = fileops.unlisted_backups(roots, project)
        report["state"] = {
            "path": str(roots.state_dir_of(project)), "removed": False, "would_remove": False, "why": None,
            "unlisted_backups": [str(path) for path in unlisted],
        }
        report["summary"] = (
            f"nothing to do: setup has no record for this {'project' if project else 'home'}; nothing was changed"
        )
        if unlisted:
            report["state"]["why"] = _unlisted_why(len(unlisted))
            report["summary"] += f"; {_count(len(unlisted), 'backup')} that no record lists stay"
            report["exit_code"] = EXIT_KEPT
            return Outcome(report, EXIT_KEPT, [])
        directory = roots.state_dir_of(project)
        foreign = _foreign(directory)
        if foreign:
            # No record, and the state directory is still there for
            # something setup did not put into it: said, and not "done".
            report["state"]["why"] = _foreign_why(directory, foreign)
            report["summary"] = (
                f"not finished: setup has no record for this {'project' if project else 'home'}, and its state "
                "directory stays for what it holds; nothing was changed"
            )
            report["exit_code"] = EXIT_KEPT
            return Outcome(report, EXIT_KEPT, [])
        return Outcome(report, 0, [])

    before = dict(manifest.entries)
    report["entries"] = len(_listed(roots, manifest, project))
    settings_file = _settings_file(found, project)
    keep = _other_side(found, roots, manifest, project)
    release: dict[Path, str] = {}
    settings_key: str | None = None
    if settings_file is not None:
        known = manifest.find(roots.key(settings_file) or "")
        if known is not None and before[known].get("kind") == "file":
            settings_key = known
            yours = _settings_yours(settings_file, before[known], keep_settings, follow)
            if yours is not None:
                release[settings_file] = yours

    errors: list[str] = []
    part_way = False
    result: fileops.Result | None = None
    while True:
        plan = fileops.plan_reversal(
            roots, project=project, follow_config_symlinks=follow, stamp=stamp, keep=keep, release=release
        )
        try:
            result = plan.run(dry_run)
        except fileops.SymlinkedConfigPath as exc:
            # A path that is, or lies under, a link: left where it is, and
            # the rest is undone. One the record does not list (the state's
            # own directory, a parent to be made again) stops the run.
            more: dict[Path, str] = {}
            for problem in exc.problems:
                path = problem.path
                key = None if path is None else roots.key(path)
                if path is None or key is None or manifest.find(key) is None or path in keep:
                    more = {}
                    break
                # Where the link leads out of what this run may write to,
                # the option would not help: say that, not "give the option".
                out = fileops.refusal(roots, path) if fileops.symlink_in_the_way(roots, path.parent) else None
                more[path] = problem.message[len(str(path)) + 2:] if out is None else out[len(str(path)) + 2:]
            if more:
                keep.update(more)
                continue
            errors = list(exc.lines)
        except fileops.PlanError as exc:
            # A listed path whose real place setup changes under no option
            # (through a link, out of the roots or into a clone) is kept
            # like one on the other side, and the rest is undone.
            more = {}
            for problem in exc.problems:
                path = problem.path
                key = None if path is None else roots.key(path)
                listed = key is not None and manifest.find(key) is not None
                if problem.code != fileops.OUTSIDE or not listed or path in keep or path is None \
                        or fileops.symlink_in_the_way(roots, path) is None:
                    more = {}
                    break
                more[path] = problem.message[len(str(path)) + 2:]
            if more:
                keep.update(more)
                continue
            errors = list(exc.lines)
        except SetupError as exc:
            errors, part_way = list(exc.lines), _touched(roots, project, before)
        break

    now = fileops.read_record(roots) if result is not None and result.applied else record
    after = now.project if project else now.home
    assert after is not None
    left_keys = {key for key, _ in (result.left if result else [])}
    kept = [(key, why) for key, why in (result.kept if result else []) if key not in left_keys]
    if result is not None and result.applied:
        remaining = _listed(roots, after, project)
    else:
        remaining = [key for key, _ in kept]

    def entry_of(key: str) -> dict[str, Any] | None:
        known = manifest.find(key)
        return None if known is None else before[known]

    if result is not None:
        removed, restored, forgotten, said = _groups(result.lines if result.changed else [])
        # What is left to the user is said once, under its own heading.
        forgotten = [line for line in forgotten if line.removeprefix("update record ") not in left_keys]
        if dry_run and settings_key is not None:
            # Before it goes, the one file of the plan the user may have
            # meant to keep is said to be keepable.
            hint = f"  (the settings file `init` wrote; {KEEP_SETTINGS_OPTION} leaves it as it is, as yours)"
            removed, restored = (
                [line + hint if _names(line, settings_key) else line for line in lines]
                for lines in (removed, restored)
            )
        report.update({
            "applied": result.applied,
            "changed": result.changed,
            "removed": removed, "restored": restored, "forgotten": forgotten,
            "plan": list(result.lines) if result.changed else [],
            "notes": [*report["notes"], *said, *[note for note in result.notes if not note.startswith("kept ")]],
            "left": [
                {"key": key, "path": None if _path(roots, key) is None else str(_path(roots, key)), "why": why}
                for key, why in result.left
            ],
            "kept": [
                {
                    "key": key,
                    "path": None if _path(roots, key) is None else str(_path(roots, key)),
                    "what": _what(entry_of(key)),
                    "why": why,
                    "backup": _backup_of(roots, entry_of(key)),
                    "finish": _finish(roots, key, _path(roots, key), entry_of(key), why, settings_file),
                }
                for key, why in kept
            ],
        })

    # --- The state --------------------------------------------------------------
    waits = False  # the state stays for backups that no record lists
    if result is not None:
        try:
            report["state"] = _state(roots, project, remaining, dry_run, follow, result.unlisted)
            # The state stays for backups that no record lists, or for
            # something in it that setup did not put there: not finished.
            waits = not remaining and not (report["state"]["removed"] or report["state"]["would_remove"])
        except SetupError as exc:
            errors, part_way = list(exc.lines), True

    report["errors"] = list(errors)
    code = EXIT_ERROR if errors else EXIT_KEPT if remaining or waits else 0
    report["exit_code"] = code
    report["summary"] = _summary(report, part_way)
    return Outcome(report, code, errors)


def _touched(roots: Roots, project: bool, before: dict[str, Any]) -> bool:
    """Whether a run that failed changed anything: the record on disk
    differs from what it was, or lists changes that were under way. A run
    saves its record, with every change listed, before its first change,
    so a record that is as it was means that none was made. Where the
    record cannot be read the answer is yes: nothing is claimed."""
    try:
        now = fileops.read_record(roots)
        manifest = now.project if project else now.home
        if manifest is None:
            return True
        return bool(now.recovered or now.dropped) or dict(manifest.entries) != before
    except Exception:
        return True


def _unlisted_why(count: int) -> str:
    return (
        f"it holds {_count(count, 'backup')} that no record lists, which setup does not remove by itself; "
        f"`{PROG} uninstall {DISCARD_OPTION}` removes them"
    )


def _state(roots: Roots, project: bool, remaining: list[str], dry_run: bool, follow: bool,
           leaving: list[Path] | None = None) -> dict[str, Any]:
    """Remove the state of the record that was undone, or say why it
    stays. Only the backups the record lists go with it. ``leaving`` are
    the backups the way back takes out of the record (they hold text of
    the user's that could not be put back): a real run has done so by now,
    and a dry run counts them as it would find them."""
    directory = roots.state_dir_of(project)
    unlisted = fileops.unlisted_backups(roots, project)
    if dry_run:
        known = {paths.fold(path) for path in unlisted}
        unlisted = [*unlisted, *[path for path in leaving or [] if paths.fold(path) not in known]]
    state: dict[str, Any] = {
        "path": str(directory), "removed": False, "would_remove": False, "why": None,
        "unlisted_backups": [str(path) for path in unlisted],
    }
    if remaining:
        state["why"] = "it holds the record of what was kept, and the backups that still belong to it"
    elif dry_run:
        foreign = _foreign(directory)
        if unlisted:
            state["why"] = _unlisted_why(len(unlisted))
        elif foreign:
            state["why"] = _foreign_why(directory, foreign)
        else:
            state["would_remove"] = True
    elif not fileops.remove_state(roots, project=project, follow_config_symlinks=follow):
        state["why"] = "its record still lists something"
    elif fsio.look(directory).kind == fsio.ABSENT:
        state["removed"] = True
    elif unlisted:
        state["why"] = "the record is removed; " + _unlisted_why(len(unlisted))
    else:
        state["why"] = "the record is removed; " + _foreign_why(directory)
    return state


def _foreign(directory: Path) -> list[str]:
    """What a state directory holds, by name, that is not setup's and
    that no run removes: anything but the record, the backups directory,
    the lock, and the pieces of a lock that a killed run left (files under
    a temporary name, claims on a lock), which the next run clears."""
    try:
        if fsio.look(directory).kind != fsio.DIRECTORY:
            return []
        held = fsio.names(directory)
    except SetupError:
        return []
    found: list[str] = []
    for name in held:
        try:
            kind = fsio.look(directory / name).kind
        except SetupError:
            kind = fsio.OTHER
        own = (
            (name in (MANIFEST_NAME, lock.LOCK_NAME) and kind == fsio.FILE)
            or (name == BACKUPS_NAME and kind == fsio.DIRECTORY)
            or (kind == fsio.FILE and (fsio.is_temporary(name) or name.startswith(lock.CLAIM_PREFIX)))
        )
        if not own:
            found.append(name)
    return found


def _foreign_why(directory: Path, held: list[str] | None = None) -> str:
    """Why a state directory with no record in it stays: what it holds,
    by name, which setup did not put there and does not remove."""
    if held is None:
        try:
            held = fsio.names(directory)
        except SetupError:
            held = []
    shown = ", ".join(held[:6]) + (f", and {len(held) - 6} more" if len(held) > 6 else "")
    return (
        f"the directory holds something setup did not put there ({shown or 'it cannot be listed'}), which setup "
        "does not remove. Move it away or remove it, and run uninstall again: the directory then goes"
    )


def discard(found: homes.Homes, *, project: bool = False, dry_run: bool = False, follow: bool = False,
            confirm: Any = None) -> tuple[list[Path], bool]:
    """What ``uninstall --discard-backups`` does: name the backups that the
    record of the home, or of the project, does not list, and remove them
    once ``confirm`` (called with the list) says yes. Returns the list, and
    whether it was removed. A backup a record lists is never touched."""
    roots = found.roots()
    if project and found.project is None:
        raise SetupError("no project was named, so there are no project backups to discard")
    listed = fileops.unlisted_backups(roots, project)
    if not listed or dry_run or confirm is None or not confirm(listed):
        return listed, False
    removed = fileops.discard_backups(roots, project=project, follow_config_symlinks=follow)
    # Nothing is left to answer for where no record is: the empty state goes.
    fileops.remove_state(roots, project=project, follow_config_symlinks=follow)
    return removed, True


def _count(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _summary(report: dict[str, Any], part_way: bool = False) -> str:
    if report["errors"]:
        if part_way:
            return f"stopped: {_count(len(report['errors']), 'error')}, part way; the error says what was done"
        return f"stopped: {_count(len(report['errors']), 'error')}; nothing was changed"
    removed, restored = _heads(report["removed"]), _heads(report["restored"])
    forgotten, kept, left = _heads(report["forgotten"]), len(report["kept"]), len(report["left"])
    state = report["state"] or {}
    dry = report["dry_run"]
    parts = [f"would remove {removed} and restore {restored}" if dry else f"{removed} removed, {restored} restored"]
    if forgotten:
        parts.append(f"{forgotten} {'would only leave' if dry else 'only left'} the record")
    if left:
        parts.append(f"{left} left as yours")
    parts.append(f"{kept} kept" if kept else "nothing kept")
    what = "the project's state directory" if report["scope"] == PROJECT else "the state directory"
    if state.get("removed") or state.get("would_remove"):
        parts.append(f"{what} {'would be' if dry else 'was'} removed")
    else:
        parts.append(f"{what} stays")
    head = "dry run" if dry else "done" if not kept and (state.get("removed") or state.get("would_remove")) else "not finished"
    if dry:
        parts.append("nothing was changed")
    return f"{head}: " + "; ".join(parts)


def report_lines(report: dict[str, Any]) -> list[str]:
    """The report as text: what was removed, restored, left and kept, the
    state, and one line that sums it up."""
    lines: list[str] = []
    dry = report["dry_run"]
    if dry:
        lines.append("dry run: nothing is changed")
    if report["scope"] == PROJECT:
        lines.append(f"project: {report['project']}")
    else:
        lines.append(f"home: {report['home']}")
    if not report["recorded"]:
        lines.append(f"record: {report['record']}: not there")
        lines.extend(f"note: {note}" for note in report["notes"])
        state = report["state"]
        if state is not None and state["why"]:
            lines.append(f"state directory: {state['path']}: stays: {state['why']}")
            lines.extend(f"    {path}" for path in state["unlisted_backups"])
        lines.append(report["summary"])
        return lines
    lines.append(f"record: {report['record']} ({report['entries']} {'entry' if report['entries'] == 1 else 'entries'})")
    if report["errors"]:
        lines.append(report["summary"])
        return lines
    for title, name in ((f"{'would remove' if dry else 'removed'}:", "removed"),
                        (f"{'would restore' if dry else 'restored'}:", "restored"),
                        ("no longer there, or left as it is; taken out of the record:", "forgotten")):
        if report[name]:
            lines.append(title)
            lines.extend(f"  {line}" for line in report[name])
    if report["left"]:
        lines.append("left, and yours from now on:")
        lines.extend(f"  {item['key']}: {item['why']}" for item in report["left"])
    if report["kept"]:
        lines.append("kept:")
        for item in report["kept"]:
            lines.append(f"  {item['key']}: {item['what']}: {item['why']}")
            if item["path"]:
                lines.append(f"    path: {item['path']}")
            if item["backup"]:
                lines.append(f"    backup: {item['backup']}")
            lines.append(f"    to finish: {item['finish']}")
    lines.extend(f"note: {note}" for note in report["notes"])
    again = f"`{PROG} uninstall" + (f" --project {report['project']}`" if report["scope"] == PROJECT else "`")
    state = report["state"]
    if state is not None:
        what = "state directory"
        if state["removed"] or state["would_remove"]:
            lines.append(f"{what}: {state['path']}: {'would be removed' if dry else 'removed'}")
        else:
            lines.append(f"{what}: {state['path']}: stays: {state['why']}")
            if report["kept"]:
                lines.append(f"to finish: do what is said for each kept entry, then run {again} again")
            for path in state["unlisted_backups"]:
                lines.append(f"    {path}")
    lines.append(report["summary"])
    return lines
