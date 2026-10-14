"""Take back what setup installed, in a home or in one project.

    uninstall [--project DIR] [--home DIR] [--dry-run] [--json]
              [--follow-config-symlinks] [--keep-settings]
              [--clone-was DIR]
    uninstall --discard-backups [--yes] [--project DIR] [--home DIR] [--dry-run]

What is undone
    Without --project: what setup did at the user level, in the providers'
    homes and in ~/.agents. With --project DIR: what setup did in that
    project, and nothing else; the homes stay installed. So one project can
    be taken out of the framework, and a whole install is taken back by
    `uninstall --project DIR` for each project and then `uninstall`.

    Only what the install record lists is touched, and each entry only
    while it is still as setup left it:

      - a link is removed if it still points where setup pointed it;
      - a generated file is removed if it still holds what setup wrote;
        a Codex profile that also holds what Codex or you added after
        setup's part (Codex writes your answer to "trust this project?"
        and flags of its interface there) loses setup's keys and is left
        holding the rest, as yours;
      - a file of yours that setup edited gets back, byte for byte, what it
        held before, if nothing changed it since. If it was changed, setup's
        blocks and keys are taken out, the lines setup removed are put back
        where they were, and the rest of the file is left as it is;
      - what the v1 migration removed is put back: a file from its backup,
        a link with its own text and form, a directory;
      - a directory setup created is removed once it is empty;
      - the settings file `init` wrote (see "The settings file" below).

    Nothing else is removed: not a v1 copy the migration kept, not the
    collaboration skill's links, not a settings file you wrote yourself,
    not a project's own settings file that `init` found and did not change.

The settings file
    No value you set in a settings file is removed by `uninstall`. The file
    `init` wrote (~/.agents/workflow.toml, or with --project
    DIR/.agents/workflow.toml) is

      - removed, when `init` created it and it holds exactly what `init`
        wrote from its own answers, with nothing else in it;
      - replaced, byte for byte, by the file that was there before the
        first `init`, when nothing but `init` has written it since;
      - left as it is, and yours from then on, in every other case: you
        edited it since `init` wrote it, or `init` rewrote a version you
        had edited (`init --rewrite-settings`, or the same confirmed at
        the prompt), so that it holds values you set. The backups of its
        earlier versions go with the record, as all backups do: copy one
        first if you want its comments back.

    A file that is left does not keep the uninstall from finishing. With
    --keep-settings the file is left in every case. --dry-run says which
    of the three it would be, and names --keep-settings on the line that
    would remove or replace the file.

What you had `render --overwrite-edited` replace
    Text of yours between setup's markers, and a value of yours at a key
    setup sets, that `render --overwrite-edited` replaced, is put back
    where it was when setup's block or key goes: your text takes the place
    of setup's block, and your value the place of setup's, and the file
    stays. Where that cannot be done exactly, the backup that holds your
    text is never removed, its path is printed, and the exit code is 3:

      - a block you edited again is kept as it is, like any edited block,
        with its record and that backup, until you deal with the block;
      - where the block or the key is gone, the key has another value
        again, or setup replaced text of yours at the same place more
        than once, the backup is taken out of the record and stays in
        the state directory. See "Backups setup does not remove" for how
        to clear it once you have what you need from it.

What is kept
    An entry that was changed since setup made it is kept, with the reason
    and what to do about it: a link that points elsewhere now, a generated
    file or a block that was edited by hand, a path where something is
    again that setup removed (its backup is kept, and its path is printed).
    A path that is, or lies under, a link is kept unless
    --follow-config-symlinks is given; where the link leads out of the
    home (or, for a project, out of the project) or into a clone, it is
    kept with the option too, since setup writes there under no option.
    A path of a home whose real place is on the other side of the machine
    (Windows and WSL) is always kept: this side never writes there.
    Everything else is still undone.

    Left to you, and no longer setup's to answer for: a directory setup
    created that holds something of yours, a key of a settings file whose
    value you changed since setup set it, and the settings file of `init`
    once it holds values you set (above). None of them keeps the uninstall
    from finishing.

The state
    Setup keeps its state where the record belongs: in
    ~/.agents/workflow-setup for the user level, and in
    DIR/.agents/workflow-setup for a project, each with its record
    (manifest.json), the backups of the files it replaced or removed
    (backups/<time of the run>/) and, while a run writes, its lock. A
    project's state is in the project, whole: undoing a project touches
    nothing of the home, and undoing the home nothing of a project.

    When every entry was removed or restored, the state goes too: the
    backups the record lists, the record, and the directories that held
    them. Nothing of setup's is then left.

    While an entry is kept the state stays, with the record of what was
    kept and the backups it still needs. Do what the output says for each
    kept entry (put it back as setup wrote it, or remove it) and run
    `uninstall` again: it finishes the job. The last resort, when an entry
    cannot be dealt with, is to remove the state directory by hand. What
    is kept is then yours.

Backups setup does not remove
    Setup removes a backup only together with the record that lists it. A
    file under a backups directory that no record lists (the record was
    removed by hand, or the file was put there by something else) is never
    removed by a run: it may be the only copy of a file of yours.
    `uninstall` then leaves the state directory, names the files, and ends
    with 3. Look at them, and when you need none of them:

        uninstall --discard-backups [--project DIR]

    lists the backups that no record lists and removes them after you
    confirm (or with --yes; --dry-run only lists). It removes nothing a
    record lists and undoes nothing.

A clone that moved
    A link that leads into another directory than the clone this command
    runs from is not the link setup made, and is kept. If the clone was
    moved since the install, --clone-was DIR names where it was: a link
    into DIR is then setup's, and is removed, and a link of yours into the
    clone that the v1 migration removed is put back with the text it had,
    into DIR. Without the option such a link of yours is kept, not put
    back, when a link setup made shows that the clone was elsewhere: the
    text it had cannot be known then, and the output names the option.
    The option changes nothing else: the clone is still the one this
    command runs from, and nothing is ever written, removed or linked
    inside it.

--dry-run prints what would be removed, restored, left and kept, and
changes nothing. A second `uninstall` finds no record, says that there is
nothing to do, and ends with 0. An interrupted run of another command is
completed in the record first, as every command does, and then undone.

The whole way back is checked before the first change, so one that is
refused changes nothing. It is not atomic: if a change fails part way, what
was undone before it stays undone and the record holds the rest; the error
says how many changes were made, and running `uninstall` again goes on. A
run that fails before its first change (a state directory that cannot be
written) says that nothing was changed.

The backups are full copies of your files as they were, with everything
they hold; the ones a record lists are removed with that record.

Known limit. The guards on where setup writes and removes (never inside
the clone, at a credentials file, or outside the home and the project) hold
against the disk as the run finds it, not against another program that
changes the same directories while the run is under way.

One run writes to a home at a time, and one to a project: a second one ends
at once with exit code 2 and names the run that holds the lock. A run that
was killed leaves its lock, its unfinished changes and perhaps a file under
a temporary name that its record lists; the next run that writes clears the
lock where that process is provably gone (else the message says how),
settles the changes from the disk, removes those temporary files, and says
so. A lock taken on another system (a project on a Windows drive, used from
Windows and from WSL) is never cleared from here: the message names the
file to remove once no setup run is using the project.

The output: the home or the project, the record, what was removed, what was
restored, what was left to you, what was kept (each with what it is, why,
the backup that belongs to it and how to finish), the state, and one line
that sums it up. With --json one object with the same facts ("scope",
"removed", "restored", "forgotten", "left", "kept", "plan", "notes",
"state", "errors", "summary", "exit_code").

Exit code 0 when everything was undone, or there was nothing to do; 3 when
the rest was done (or, with --dry-run, would be) and something stays that
you have to deal with: an entry was kept, or the state directory stays for
backups that no record lists or for something else in it that setup did
not put there (the output names it); 2 on an error, printed to stderr; 130
when interrupted with Ctrl-C, and 128 plus the signal's number when told to end by a signal (143
for SIGTERM): what was undone until then stays undone, and the next run goes
on; 141 when the reader of the output went away.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import fileops, homes, locations, paths, uninstall
from ..errors import SetupError

SUMMARY = "take back what setup installed in a home, or with --project in one project"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    locations.add_arguments(parser)
    fileops.add_arguments(parser)
    parser.add_argument(
        uninstall.KEEP_SETTINGS_OPTION,
        action="store_true",
        help="leave the settings file `init` wrote as it is, in every case; it is yours from then on. Without "
        "it the file is removed, or replaced by the one that was there before `init`, only while it holds "
        "exactly what `init` wrote and `init` never rewrote a version you had edited; else it is left as well",
    )
    parser.add_argument(
        uninstall.CLONE_WAS_OPTION,
        metavar="DIR",
        help="where the clone was when setup made its links, if it was moved since: a link into DIR is "
        "then taken for setup's, and a link of yours into the clone that setup removed is put back into DIR. "
        "An absolute path, or one that starts with ~; it need not exist",
    )
    parser.add_argument(
        uninstall.DISCARD_OPTION,
        action="store_true",
        help="undo nothing; list the backups under the state directory that no record lists, and remove them "
        "after a confirmation. Setup never removes such a file by itself: it may be the only copy of a file "
        "of yours",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=f"with {uninstall.DISCARD_OPTION}: remove what was listed without asking",
    )


def _clone_was(text: str) -> Path:
    if not text.strip():
        raise SetupError(f"{uninstall.CLONE_WAS_OPTION}: an empty value is not a directory")
    locations.path_argument(text, uninstall.CLONE_WAS_OPTION)
    try:
        path = Path(text).expanduser()
    except (RuntimeError, KeyError):
        raise SetupError(f"{uninstall.CLONE_WAS_OPTION}: {text}: the home directory of that user cannot be found") from None
    if not path.is_absolute():
        raise SetupError(f"{uninstall.CLONE_WAS_OPTION}: {text}: not an absolute path")
    return paths.absolute(path)


def _discard(args: argparse.Namespace, found: homes.Homes, project: bool) -> int:
    for name in ("keep_settings", "clone_was", "json"):
        if getattr(args, name):
            raise SetupError(f"{uninstall.DISCARD_OPTION}: is a command of its own; give it without --{name.replace('_', '-')}")

    def confirm(listed: list[Path]) -> bool:
        if args.yes:
            return True
        if not sys.stdin or not sys.stdin.isatty():
            raise SetupError(
                f"{uninstall.DISCARD_OPTION}: needs a confirmation: nothing was removed. Give --yes to remove what "
                "is listed above"
            )
        try:
            what = "this backup" if len(listed) == 1 else f"these {len(listed)} backups"
            return input(f"Remove {what} for good? [y/N] (--yes): ").strip().lower() in ("y", "yes")
        except EOFError:
            return False

    where = found.project if project else found.home
    listed = fileops.unlisted_backups(found.roots(), project)
    if not listed:
        print(f"nothing to do: no backup under {found.roots().state_dir_of(project)} is unlisted; nothing was changed")
        return 0
    print(f"backups of {where} that no record of setup's lists:")
    for path in listed:
        print(f"  {path}")
    if args.dry_run:
        print("dry run: nothing was removed")
        return 0
    removed, done = uninstall.discard(found, project=project, follow=args.follow_config_symlinks, confirm=confirm)
    print(f"removed: {len(removed)} backup{'' if len(removed) == 1 else 's'}" if done else "nothing was removed")
    return 0


def run(args: argparse.Namespace) -> int:
    where = locations.from_args(args)
    clone_was = None if args.clone_was is None else _clone_was(args.clone_was)
    found = homes.resolve(where)
    if args.discard_backups:
        return _discard(args, found, where.project is not None)
    if args.yes:
        raise SetupError(f"--yes: only confirms {uninstall.DISCARD_OPTION}; an uninstall asks nothing")
    outcome = uninstall.execute(
        found, project=where.project is not None, dry_run=args.dry_run, follow=args.follow_config_symlinks,
        keep_settings=args.keep_settings, clone_was=clone_was,
    )
    if args.json:
        print(json.dumps(outcome.report, indent=2, ensure_ascii=False))
    else:
        for line in uninstall.report_lines(outcome.report):
            print(line)
    if outcome.errors:
        raise SetupError(*outcome.errors)
    return outcome.code
