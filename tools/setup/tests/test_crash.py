"""A run that is stopped at any point loses nothing (R6.5, R8.1).

Each scenario is run once to count the changes it makes to the disk, and
then once for every one of them, stopped before it: killed (nothing after
that point touches the disk, as when the process is gone), and interrupted
before and after it (a ``KeyboardInterrupt``, whose handlers run). After
each stop:

    - no path is half made: each is as it was at the start or as the run
      leaves it, or absent where the run swaps one kind for another. A
      kill, and only a kill, may leave the marker beside ``.agents``
      (``lock.MARKER_NAME``); an interrupt leaves nothing under a temporary
      name and no marker;
    - the same run, started again, completes, and a third has nothing to do;
    - the whole way back then gives the starting tree: every path, link
      text, byte and mode, with nothing kept and no state left.

For ``uninstall`` the run that is stopped is the way back itself. A sample
of the same points is run again in child processes that really end there
(``os._exit``), so that the lock they leave is one of a process that is
gone.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support
from crash_support import EXIT_CODE, INTERRUPT, KILL, Disk, World, clear, differences, orphan, stopped, tree
from wfsetup import fileops, fsio, lock

STATE = ".agents/workflow-setup"
# Setup's own state: the home's and the project's, each in its own place.
STATES = (f"home/{STATE}/", f"project/{STATE}/")
# What says "setup made the ``.agents`` beside me" until a record does; see
# ``lock``. A kill may leave it, and the next run takes it away.
MARKERS = (f"home/{lock.MARKER_NAME}", f"project/{lock.MARKER_NAME}")


def in_state(name: str) -> bool:
    return f"{name}/".startswith(STATES)


class CrashCase(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.world = World(Path(scratch.name).resolve() / "w")
        self.addCleanup(self._unlock)

    def _unlock(self) -> None:
        if os.name == "posix":
            for directory, _, _ in os.walk(self.world.root):
                os.chmod(directory, 0o700)

    def users(self, snap: dict[str, tuple]) -> dict[str, tuple]:
        """A tree without setup's own state."""
        return {name: value for name, value in snap.items() if not in_state(name)}

    def begin(self, scenario: str) -> None:
        """The starting tree of a scenario: for ``uninstall``, an install."""
        self.world.reset()
        if scenario == "uninstall":
            self.world.everything().apply()

    def restore(self, scenario: str) -> None:
        """The starting tree of ``scenario`` again, from a copy taken the
        first time, which is cheaper than the install ``begin`` makes. Under
        Windows ``begin`` runs again: a copy would follow a junction into
        its target."""
        if os.name != "posix":
            self.begin(scenario)
            return
        snapshot = self.world.root.parent / "snapshots" / scenario
        if not snapshot.exists():
            with Disk():
                self.begin(scenario)
            shutil.copytree(self.world.root, snapshot, symlinks=True)
        clear(self.world.root)
        shutil.copytree(snapshot, self.world.root, symlinks=True)

    def measure(self, scenario: str) -> tuple[dict, dict, dict, int]:
        """The tree before the user had setup, the tree the scenario starts
        from, the tree it ends with, and the number of changes it makes."""
        self.world.reset()
        pristine = tree(self.world.root)
        self.restore(scenario)
        start = tree(self.world.root)
        counter = Disk()
        self.assertFalse(stopped(lambda: self.world.run(scenario), counter))
        end = tree(self.world.root)
        self.assertGreater(counter.count, 10)
        return pristine, start, end, counter.count

    def check_not_half_made(self, start: dict, end: dict, now: dict, where: str, killed: bool = True) -> None:
        for name in sorted(set(start) | set(end) | set(now)):
            if in_state(name):
                continue
            if name in MARKERS and killed:
                # Left by a kill between making ``.agents`` and the record
                # that lists it: an empty directory, and nothing else.
                self.assertEqual(now[name][0], "directory", f"{where}: {name}")
                continue
            base = os.path.basename(name)
            if fsio.is_temporary(base) or any(fsio.is_temporary(part) for part in name.split("/")):
                continue  # under a temporary name, never under the path's own
            was, will, there = start.get(name), end.get(name), now.get(name)
            allowed = [was, will]
            if was is not None and will is not None and was != will and "file" not in (was[0], will[0]):
                allowed.append(None)  # one taken away, the other not made yet: a link, a directory
            if there is not None and there[0] == "directory":
                # A directory is as it was or as it will be; one that is on
                # the way out may be there still, with any bits it had.
                self.assertTrue(any(item is not None and item[0] == "directory" for item in allowed), f"{where}: {name}")
                continue
            self.assertIn(there, allowed, f"{where}: {name} is neither as it was nor as the run leaves it")

    def one(self, scenario: str, point: int, mode: str, after: bool, pristine: dict, start: dict, end: dict) -> None:
        where = f"{scenario}, {mode} {'after' if after else 'before'} change {point}"
        self.restore(scenario)
        disk = Disk(point, mode, after)
        self.assertTrue(stopped(lambda: self.world.run(scenario), disk), where)
        with Disk():  # not stopped any more; and not waiting for the disk to sync
            self.after_the_stop(scenario, where, disk, pristine, start, end)

    def after_the_stop(self, scenario: str, where: str, disk: Disk, pristine: dict, start: dict, end: dict) -> None:
        mode = disk.mode
        # The process is gone, after a kill and after an interrupt alike.
        orphan(self.world.roots)
        now = tree(self.world.root)
        if mode == INTERRUPT:
            self.assertEqual(self.temporaries(now), [], f"{where}: an interrupt left something under a temporary name")
        self.check_not_half_made(start, end, now, where, killed=mode != INTERRUPT)
        # The same run again completes, and then there is nothing to do.
        try:
            self.world.run(scenario)
        except BaseException as exc:
            self.fail(f"{where}: the next run did not complete: {type(exc).__name__}: {exc}\n" + "\n".join(disk.calls[-4:]))
        after_rerun = tree(self.world.root)
        if scenario == "uninstall":
            self.assertEqual(differences(pristine, after_rerun), [], where)
            return
        self.assertEqual(differences(self.users(end), self.users(after_rerun)), [], where)
        again = getattr(self.world, scenario)().describe()
        self.assertEqual(again.lines, [fileops.UP_TO_DATE], where)
        self.assertEqual(self.temporaries(after_rerun), [], where)
        # And the whole way back ends at the start, with nothing kept.
        self.assertEqual(self.world.uninstall(), [], where)
        self.assertEqual(differences(pristine, tree(self.world.root)), [], where)

    def temporaries(self, snap: dict[str, tuple]) -> list[str]:
        return [name for name in snap if any(fsio.is_temporary(part) for part in name.split("/"))]

    def every_point(self, scenario: str, mode: str, after: bool) -> int:
        """``scenario`` stopped before each change it makes, or after it
        with ``after``, in ``mode``. The three modes are three tests, so
        that they run side by side."""
        pristine, start, end, count = self.measure(scenario)
        points = 0
        for point in range(1, count + 1):
            with self.subTest(scenario=scenario, point=point, mode=mode, after=after):
                self.one(scenario, point, mode, after, pristine, start, end)
            points += 1
        # The control: the run that is not stopped, and its way back.
        self.restore(scenario)
        self.world.run(scenario)
        if scenario != "uninstall":
            self.assertEqual(self.world.uninstall(), [])
        self.assertEqual(differences(pristine, tree(self.world.root)), [])
        return points


class EveryPointTests(CrashCase):
    """Each scenario stopped at every change it makes to the disk: killed,
    interrupted before the change, and interrupted after it, each a test
    of its own."""

    def test_a_plain_render_killed(self) -> None:
        self.assertGreater(self.every_point("render", KILL, False), 20)

    def test_a_plain_render_interrupted_before(self) -> None:
        self.assertGreater(self.every_point("render", INTERRUPT, False), 20)

    def test_a_plain_render_interrupted_after(self) -> None:
        self.assertGreater(self.every_point("render", INTERRUPT, True), 20)

    def test_a_migration_that_replaces_a_directory_by_a_link_killed(self) -> None:
        self.assertGreater(self.every_point("migrate", KILL, False), 50)

    def test_a_migration_that_replaces_a_directory_by_a_link_interrupted_before(self) -> None:
        self.assertGreater(self.every_point("migrate", INTERRUPT, False), 50)

    def test_a_migration_that_replaces_a_directory_by_a_link_interrupted_after(self) -> None:
        self.assertGreater(self.every_point("migrate", INTERRUPT, True), 50)

    def test_a_project_render_killed(self) -> None:
        self.assertGreater(self.every_point("project_render", KILL, False), 33)

    def test_a_project_render_interrupted_before(self) -> None:
        self.assertGreater(self.every_point("project_render", INTERRUPT, False), 33)

    def test_a_project_render_interrupted_after(self) -> None:
        self.assertGreater(self.every_point("project_render", INTERRUPT, True), 33)

    def test_an_uninstall_killed(self) -> None:
        self.assertGreater(self.every_point("uninstall", KILL, False), 50)

    def test_an_uninstall_interrupted_before(self) -> None:
        self.assertGreater(self.every_point("uninstall", INTERRUPT, False), 50)

    def test_an_uninstall_interrupted_after(self) -> None:
        self.assertGreater(self.every_point("uninstall", INTERRUPT, True), 50)


class TheUsersFilesTests(CrashCase):
    """What B1 and B4 lost: the files of the user's copy of a skill, whose
    directory setup replaces by a link into the clone."""

    NOTES = "home/.claude/skills/json-tools/notes/deep/mine.md"
    SKILL = "home/.claude/skills/json-tools/SKILL.md"

    def points(self, name: str) -> list[int]:
        """The changes of a migration whose description holds ``name``."""
        self.world.reset()
        counter = Disk()
        stopped(lambda: self.world.run("migrate"), counter)
        return [index + 1 for index, call in enumerate(counter.calls) if name in call]

    def held(self) -> dict[str, bytes]:
        """Every copy of the user's two files, wherever it is now."""
        found: dict[str, bytes] = {}
        for name, value in tree(self.world.root).items():
            if value[0] == "file" and value[1] in (b"IRREPLACEABLE NOTES\n", b"the user's copy, edited\n"):
                found[name] = value[1]
        return found

    def test_a_kill_before_the_last_record_save_keeps_the_removed_files_in_the_record(self) -> None:
        saves = self.points("manifest.json")
        self.world.reset()
        pristine = tree(self.world.root)
        # The last change of the run is the rename of the final record.
        self.assertTrue(stopped(lambda: self.world.run("migrate"), Disk(saves[-1], KILL)))
        orphan(self.world.roots)
        # The directory is setup's link now, and the clone's own SKILL.md
        # is what the disk shows below it.
        skill = self.world.home / ".claude" / "skills" / "json-tools"
        self.assertEqual(fsio.look(skill).kind, fsio.LINK)
        self.assertEqual((skill / "SKILL.md").read_bytes(), b"the clone's own\n")
        record = fileops.read_record(self.world.roots)
        self.assertEqual(record.dropped, 0, record.dropped_paths)
        for inner in ("SKILL.md", "scripts/run.py", "notes/deep/mine.md"):
            entry = record.get(f"home:.claude/skills/json-tools/{inner}")
            self.assertIsNotNone(entry, inner)
            self.assertEqual(entry["kind"], "removed-file")
        self.assertEqual(self.world.uninstall(), [])
        self.assertEqual(differences(pristine, tree(self.world.root)), [])

    def test_a_record_save_that_fails_at_the_end_loses_nothing(self) -> None:
        self.world.reset()
        pristine = tree(self.world.root)
        real, calls = fsio.atomic_write, []

        def write(path, data, mode=None):
            if Path(path).name == "manifest.json":
                calls.append(path)
                if len(calls) > 1:
                    raise fileops.SetupError(f"{path}: cannot be written: No space left on device")
            return real(path, data, mode)

        from unittest import mock
        with mock.patch.object(fsio, "atomic_write", side_effect=write):
            with self.assertRaises(fileops.SetupError) as caught:
                self.world.run("migrate")
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn("every change was made, and the next run completes the record", caught.exception.lines[0])
        self.assertEqual(self.world.uninstall(), [])
        self.assertEqual(differences(pristine, tree(self.world.root)), [])

    def test_an_interrupt_right_after_a_removal_keeps_the_removed_file(self) -> None:
        for point in self.points("unlink"):
            with self.subTest(point=point):
                self.world.reset()
                pristine = tree(self.world.root)
                if not stopped(lambda: self.world.run("migrate"), Disk(point, INTERRUPT, after=True)):
                    continue
                # Wherever the run was: each of the user's files is in its
                # place, or in a backup that the record still points at.
                record = fileops.read_record(self.world.roots)
                for name, inner in ((self.NOTES, "notes/deep/mine.md"), (self.SKILL, "SKILL.md")):
                    if name in tree(self.world.root):
                        continue
                    entry = record.get(f"home:.claude/skills/json-tools/{inner}")
                    self.assertIsNotNone(entry, f"{inner} is gone and the record does not say so")
                    backup = record.path(entry["original"]["backup"])
                    self.assertTrue(backup.is_file(), inner)
                self.assertEqual(self.world.uninstall(), [])
                self.assertEqual(differences(pristine, tree(self.world.root)), [])

    def test_a_kill_between_taking_the_directory_away_and_making_the_link(self) -> None:
        self.world.reset()
        pristine = tree(self.world.root)
        skill = self.world.home / ".claude" / "skills" / "json-tools"
        made = [point for point in self.points("json-tools") if point]
        self.world.reset()
        counter = Disk()
        stopped(lambda: self.world.run("migrate"), counter)
        # The removal of the emptied directory itself, and the link after it.
        swap = [
            index + 1 for index, call in enumerate(counter.calls)
            if call.startswith("rmdir ") and call.endswith(os.path.join("skills", "json-tools"))
        ]
        self.assertEqual(len(swap), 1, counter.calls)
        self.assertTrue(made)
        self.world.reset()
        self.assertTrue(stopped(lambda: self.world.run("migrate"), Disk(swap[0] + 1, KILL)))
        orphan(self.world.roots)
        self.assertEqual(fsio.look(skill).kind, fsio.ABSENT)
        record = fileops.read_record(self.world.roots)
        entry = record.get("home:.claude/skills/json-tools")
        self.assertEqual(entry["kind"], "removed-directory")
        if os.name == "posix":
            self.assertEqual(entry["mode"], 0o750)
        self.assertEqual(self.world.uninstall(), [])
        self.assertEqual(differences(pristine, tree(self.world.root)), [])

    def test_a_kill_between_removing_the_users_link_and_making_setups(self) -> None:
        self.world.reset()
        pristine = tree(self.world.root)
        link = self.world.home / ".claude" / "skills" / "csv-tools"
        counter = Disk()
        stopped(lambda: self.world.run("migrate"), counter)
        gone = [
            index + 1 for index, call in enumerate(counter.calls)
            if call.split(" ", 1)[0] in ("unlink", "rmdir") and call.endswith(os.path.join("skills", "csv-tools"))
        ]
        self.assertEqual(len(gone), 1, counter.calls)
        self.world.reset()
        self.assertTrue(stopped(lambda: self.world.run("migrate"), Disk(gone[0] + 1, KILL)))
        orphan(self.world.roots)
        self.assertEqual(fsio.look(link).kind, fsio.ABSENT)
        entry = fileops.read_record(self.world.roots).get("home:.claude/skills/csv-tools")
        self.assertEqual(entry["kind"], "removed-link")
        self.assertEqual(self.world.uninstall(), [])
        self.assertEqual(differences(pristine, tree(self.world.root)), [])


class RealKillTests(CrashCase):
    """The same, with processes that really end: the lock they leave names
    a process that is gone, and the next run clears it by itself."""

    STEP = 9  # every ninth change, and the last ones

    def child(self, scenario: str, point: int, prefix: str) -> int:
        script = support.TESTS / "crash_support.py"
        done = subprocess.run(
            [sys.executable, "-B", str(script), str(self.world.root), scenario, str(point), prefix],
            stdin=subprocess.DEVNULL, capture_output=True, env=support.child_environment(), timeout=120,
        )
        if done.returncode not in (0, EXIT_CODE):
            self.fail(f"{scenario} at {point}: the child ended with {done.returncode}: {done.stderr.decode()[-600:]}")
        return done.returncode

    def sample(self, scenario: str) -> None:
        pristine, start, end, count = self.measure(scenario)
        points = sorted({*range(1, count + 1, self.STEP), count - 1, count})
        for number, point in enumerate(points):
            with self.subTest(scenario=scenario, point=point):
                self.restore(scenario)
                self.assertEqual(self.child(scenario, point, f"C{number:02d}"), EXIT_CODE)
                locks = [lock.lock_file(self.world.roots, project) for project in self.world.roots.scopes()]
                locked = any(file.exists() for file in locks)
                self.check_not_half_made(start, end, tree(self.world.root), f"{scenario} at {point}")
                result = self.world.run(scenario)
                if scenario != "uninstall":
                    self.assertEqual([str(file) for file in locks if file.exists()], [], "the lock is still there")
                    if locked:
                        self.assertIn(
                            "cleared the lock of a setup run that ended without giving it back", " ".join(result.notes)
                        )
                    self.assertEqual(self.world.uninstall(), [])
                self.assertEqual(differences(pristine, tree(self.world.root)), [], f"{scenario} at {point}")

    def test_a_migration_killed_for_real(self) -> None:
        self.sample("everything")

    def test_an_uninstall_killed_for_real(self) -> None:
        self.sample("uninstall")


if __name__ == "__main__":
    unittest.main()
