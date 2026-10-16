"""One run that writes at a time (B5): the lock of a home's state.

The runs that race here are real processes (``lock_child.py``). What must
hold after any race: every run ended with 0 or with 2; one that ended with
2 printed one line and left nothing on disk and nothing in the record;
everything a run that ended with 0 wrote is there and is in the record; no
lock, no temporary file and no pending change is left; and the way back
gives the starting tree.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import support
from crash_support import World, differences, gone_pid, tree
from lock_child import FILES, plan_of
from wfsetup import blocks, fileops, fsio, lock
from wfsetup.errors import EXIT_ERROR, SetupError

CHILD = support.TESTS / "lock_child.py"
TRIALS = 20


class LockCase(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.top = Path(scratch.name).resolve()
        self.world = World(self.top / "w")
        self.world.reset()
        self.roots = self.world.roots
        self.lock = self.roots.state_dir / "lock"
        self.children: list[subprocess.Popen] = []
        self.addCleanup(self._reap)

    def _reap(self) -> None:
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.communicate()
        lock._HELD.clear()

    def start(self, *argv: str | Path) -> subprocess.Popen:
        child = subprocess.Popen(
            [sys.executable, "-B", str(CHILD), *[str(part) for part in argv]],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=support.child_environment(), cwd=str(self.top),
        )
        self.children.append(child)
        return child

    def holder(self) -> tuple[subprocess.Popen, Path]:
        """A process that holds the lock, and the file that lets it go."""
        ready, release = self.top / "ready", self.top / "release"
        child = self.start("hold", self.world.root, ready, release)
        for _ in range(3000):
            if ready.exists() or child.poll() is not None:
                break
            time.sleep(0.01)
        if not ready.exists():
            self.fail(f"the holder did not take the lock: {child.communicate()}")
        return child, release

    def killed(self) -> int:
        """A run that took the lock and ended without giving it back."""
        child = self.start("die", self.world.root)
        child.communicate()
        self.assertEqual(child.returncode, 9)
        self.assertTrue(self.lock.is_file())
        return child.pid

    def temporaries(self) -> list[str]:
        return [name for name in tree(self.world.root) if any(fsio.is_temporary(part) for part in name.split("/"))]


class RaceTests(LockCase):
    def race(self, names: list[str], trial: int, pristine: dict | None = None) -> tuple[list[str], list[str]]:
        """Start one writing run per name at the same moment. Returns the
        names of the runs that wrote and of those that were refused, after
        checking everything that must hold."""
        pristine = tree(self.world.root) if pristine is None else pristine
        start = self.top / f"start-{trial}"
        running = [(name, self.start("write", self.world.root, name, start)) for name in names]
        start.write_bytes(b"")
        won, lost = [], []
        for name, child in running:
            out, err = child.communicate(timeout=120)
            lines = err.decode("utf-8", "replace").splitlines()
            self.assertIn(child.returncode, (0, EXIT_ERROR), (name, lines[-5:]))
            self.assertNotIn("Traceback", err.decode("utf-8", "replace"))
            if child.returncode == 0:
                self.assertEqual(lines, [], name)
                won.append(name)
            else:
                self.assertEqual(len(lines), 1, (name, lines))
                self.assertTrue(lines[0].startswith("error: "), lines)
                self.assertIn("nothing was changed", lines[0])
                lost.append(name)
        self.assertTrue(won, "no run got through")
        now = tree(self.world.root)
        self.assertFalse(self.lock.exists(), "a lock was left")
        self.assertEqual(self.temporaries(), [])
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered, record.dropped), (0, 0))
        self.assertNotIn(b'"pending"', self.roots.manifest_file.read_bytes())
        text = (self.world.home / ".claude" / "CLAUDE.md").read_bytes()
        for name in won:
            for index in range(FILES):
                key = f"home:gen/{name}-{index}.md"
                self.assertEqual(now.get(f"home/gen/{name}-{index}.md", (None, None))[1], f"by {name}\n".encode(), key)
                self.assertEqual(record.get(key)["kind"], "file", key)
            self.assertEqual(record.get(f"home:made/{name}")["kind"], "directory")
            self.assertIsNotNone(blocks.get(text, blocks.MARKDOWN, name), name)
            self.assertIn(name, record.get("home:.claude/CLAUDE.md")["blocks"])
        for name in lost:
            self.assertEqual([path for path in now if f"/{name}-" in path or path.endswith(f"made/{name}")], [], name)
            self.assertIsNone(blocks.get(text, blocks.MARKDOWN, name), name)
            self.assertEqual([key for key, _ in record if f"/{name}-" in key or key.endswith(f"made/{name}")], [], name)
        self.assertEqual(text.count(b"workflow-setup:start"), len(won))
        # The way back: nothing kept, and the tree of the start.
        self.assertEqual(self.world.uninstall(), [])
        self.assertEqual(differences(pristine, tree(self.world.root)), [])
        return won, lost

    def test_runs_that_start_together_never_interleave(self) -> None:
        refused = 0
        for trial in range(TRIALS):
            with self.subTest(trial=trial):
                self.world.reset()
                won, lost = self.race(["a1", "b2", "c3"], trial)
                refused += len(lost)
        # The race is real: with three runs at once, most are turned away.
        self.assertGreater(refused, TRIALS // 2)

    def test_runs_that_find_a_stale_lock_together(self) -> None:
        cleared = 0
        for trial in range(TRIALS // 2):
            with self.subTest(trial=trial):
                self.world.reset()
                pristine = tree(self.world.root)
                self.killed()
                # The way back, in ``race``, ends at the tree before the
                # killed run: the state directories it had made go too.
                won, lost = self.race(["a1", "b2", "c3", "d4"], trial, pristine)
                cleared += 1
        self.assertEqual(cleared, TRIALS // 2)


class HeldTests(LockCase):
    def setUp(self) -> None:
        super().setUp()
        plan_of(self.world, "mine").apply()  # a record, so that there is something to undo
        self.before = tree(self.world.root)

    def test_a_run_that_writes_is_refused_at_once_with_one_line(self) -> None:
        child, release = self.holder()
        plan = plan_of(self.world, "late")
        with self.assertRaises(fileops.LockHeld) as caught:
            plan.apply()
        self.assertIsInstance(caught.exception, SetupError)
        self.assertEqual(len(caught.exception.lines), 1)
        line = caught.exception.lines[0]
        self.assertIn(str(self.lock), line)
        self.assertIn("another setup run is writing to this home", line)
        self.assertIn(f"process {child.pid}", line)
        self.assertIn("nothing was changed", line)
        after = tree(self.world.root)
        self.assertEqual(differences(self.before, {name: value for name, value in after.items() if not name.endswith("/lock")}), [])
        # The way back and the removal of the state are runs that write too.
        with self.assertRaises(fileops.LockHeld):
            self.world.uninstall()
        with self.assertRaises(fileops.LockHeld):
            fileops.remove_state(self.roots)
        # A run that only reads is not held up, and sees the record whole.
        self.assertIn("create file home:gen/late-0.md", plan_of(self.world, "late").describe().lines)
        self.assertIsNotNone(fileops.read_record(self.roots).get("home:gen/mine-0.md"))
        self.assertEqual(lock.holder(self.roots)[1], lock.RUNNING)
        release.write_bytes(b"")
        child.communicate(timeout=60)
        self.assertEqual(child.returncode, 0)
        self.assertFalse(self.lock.exists())
        self.assertTrue(plan_of(self.world, "late").apply().changed)

    def test_the_command_line_says_it_in_one_line_and_exits_with_2(self) -> None:
        child, release = self.holder()
        code, out, err = support.run("uninstall", "--home", str(self.world.home))
        release.write_bytes(b"")
        child.communicate(timeout=60)
        self.assertEqual(code, EXIT_ERROR, (out, err))
        lines = err.splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], r"^error: .*lock: another setup run is writing to this home \(process \d+ ")
        self.assertEqual(differences(self.before, tree(self.world.root)), [])

    def test_the_lock_is_the_same_one_inside_itself(self) -> None:
        with lock.held(self.roots) as outer:
            with lock.held(self.roots) as inner:
                self.assertIs(inner, outer)
                self.assertTrue(plan_of(self.world, "inside").apply().changed)
            self.assertTrue(self.lock.is_file())
        self.assertFalse(self.lock.exists())

    def test_a_plan_with_nothing_to_do_takes_no_lock(self) -> None:
        child, release = self.holder()
        result = plan_of(self.world, "mine").apply()
        self.assertEqual(result.lines, [fileops.UP_TO_DATE])
        release.write_bytes(b"")
        child.communicate(timeout=60)


class StaleTests(LockCase):
    def test_the_lock_of_a_process_that_is_gone_is_cleared_and_said(self) -> None:
        pristine = tree(self.world.root)
        pid = self.killed()
        self.assertEqual(lock.holder(self.roots)[1], lock.GONE)
        # A dry run names it and changes nothing.
        before = tree(self.world.root)
        self.assertIn("its lock", plan_of(self.world, "next").describe().lines[0])
        self.assertEqual(tree(self.world.root), before)
        result = plan_of(self.world, "next").apply()
        self.assertTrue(any(f"process {pid}" in note and "cleared the lock" in note for note in result.notes), result.notes)
        self.assertFalse(self.lock.exists())
        # The directories the killed run had made are in the record now.
        record = fileops.read_record(self.roots)
        self.assertEqual(record.get("home:.agents")["kind"], "directory")
        self.assertEqual(record.get("home:.agents/workflow-setup")["kind"], "directory")
        self.assertEqual(self.world.uninstall(), [])
        self.assertEqual(differences(pristine, tree(self.world.root)), [])

    def test_what_a_killed_run_made_goes_when_nothing_was_recorded(self) -> None:
        pristine = tree(self.world.root)
        self.killed()
        self.assertTrue((self.world.home / ".agents" / "workflow-setup").is_dir())
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(differences(pristine, tree(self.world.root)), [])

    def test_uninstall_on_the_command_line_takes_it_away_too(self) -> None:
        pristine = tree(self.world.root)
        self.killed()
        code, out, err = support.run("uninstall", "--home", str(self.world.home))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(differences(pristine, tree(self.world.root)), [])

    def test_a_users_own_agents_directory_is_not_taken_for_setups(self) -> None:
        (self.world.home / ".agents").mkdir()
        pristine = tree(self.world.root)
        self.killed()
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(differences(pristine, tree(self.world.root)), [])
        self.assertTrue((self.world.home / ".agents").is_dir())

    def test_what_a_lock_file_says_it_created_removes_no_directory(self) -> None:
        """Nothing on disk is believed about who made a directory: a lock
        that lists ``.agents`` as created does not make it setup's."""
        (self.world.home / ".agents").mkdir()
        pristine = tree(self.world.root)
        self.killed()
        self.rewrite(lambda said: said.update(created=[lock.AGENTS, lock.STATE]))
        self.assertEqual(lock.holder(self.roots)[1], lock.GONE)
        with lock.held(self.roots) as mine:
            self.assertEqual(mine.created, {lock.STATE})
        self.assertEqual(differences(pristine, tree(self.world.root)), [])
        self.assertTrue((self.world.home / ".agents").is_dir())

    def rewrite(self, change) -> bytes:
        said = json.loads(self.lock.read_bytes())
        change(said)
        raw = (json.dumps(said) + "\n").encode()
        self.lock.write_bytes(raw)
        return raw

    def refused(self, raw: bytes, *words: str) -> None:
        before = tree(self.world.root)
        for run in (lambda: plan_of(self.world, "next").apply(), lambda: fileops.remove_state(self.roots)):
            with self.assertRaises(fileops.LockHeld) as caught:
                run()
            self.assertEqual(len(caught.exception.lines), 1)
            line = caught.exception.lines[0]
            for word in (str(self.lock), "cannot tell", "Nothing was changed", "remove that file and run again", *words):
                self.assertIn(word, line)
        self.assertEqual(tree(self.world.root), before)
        self.assertEqual(self.lock.read_bytes(), raw)

    def test_a_lock_taken_on_another_system_is_never_cleared(self) -> None:
        self.killed()
        changes = {
            "host": (lambda said: said["identity"].update(host="another-machine"), "another system (host another-machine"),
            "system": (lambda said: said["identity"].update(system="another-os"), "another system (system another-os"),
            "no identity": (lambda said: said.pop("identity"), "does not say on which system"),
            "no pid": (lambda said: said.update(pid="x"), "names no process"),
        }
        if sys.platform.startswith("linux"):
            changes["boot"] = (
                lambda said: said["identity"].update(boot="00000000-0000-0000-0000-000000000000"),
                "before this system was started, or on another system of the same name",
            )
            changes["pidns"] = (lambda said: said["identity"].update(pidns="pid:[1]"), "another system (pidns")
            changes["no boot"] = (lambda said: said["identity"].pop("boot"), "does not say its boot")
        original = self.lock.read_bytes()
        for name, (change, words) in changes.items():
            with self.subTest(name):
                self.lock.write_bytes(original)
                self.refused(self.rewrite(change), words)

    def test_a_lock_file_that_says_nothing_is_never_cleared(self) -> None:
        self.killed()
        for raw in (b"", b"not json\n", b"[]\n", b"{}\n"):
            with self.subTest(raw=raw):
                self.lock.write_bytes(raw)
                self.refused(raw)

    def test_an_id_given_to_another_process_is_not_taken_for_the_holder(self) -> None:
        self.killed()
        exists, start = lock.process(os.getppid())
        if not exists or start is None:
            self.skipTest("this system gives no start time for a process")
        # The id of a process that runs, with the start of another one.
        self.rewrite(lambda said: said.update(pid=os.getppid(), start="1"))
        self.assertEqual(lock.holder(self.roots)[1], lock.GONE)
        # With its own start it is the holder, and it is running.
        self.rewrite(lambda said: said.update(pid=os.getppid(), start=start))
        self.assertEqual(lock.holder(self.roots)[1], lock.RUNNING)
        with self.assertRaises(fileops.LockHeld):
            plan_of(self.world, "next").apply()

    def test_where_the_system_cannot_say_the_lock_stays(self) -> None:
        self.killed()
        raw = self.lock.read_bytes()
        with mock.patch.object(lock, "process", return_value=(None, None)):
            self.refused(raw, "does not say whether process")
        # A process of that id that cannot be asked about counts as running.
        with mock.patch.object(lock, "process", return_value=(True, None)):
            self.assertEqual(lock.verdict(json.loads(raw))[0], lock.RUNNING)

    def test_the_verdict_on_a_process_that_is_gone(self) -> None:
        said = {"pid": gone_pid(), "start": "0", "identity": lock.identity()}
        self.assertEqual(lock.verdict(said), (lock.GONE, ""))
        self.assertEqual(lock.verdict({**said, "pid": os.getpid()})[0], lock.RUNNING)
        self.assertEqual(lock.verdict(None)[0], lock.UNKNOWN)
        self.assertEqual(lock.verdict({**said, "pid": True})[0], lock.UNKNOWN)

    def test_a_stale_lock_that_another_run_replaced_is_given_back(self) -> None:
        """Two runs judge the same stale lock; the faster one clears it and
        takes its own; the slower one must not take that one away."""
        self.killed()
        stale = self.lock.read_bytes()
        said = json.loads(stale)
        live = (json.dumps({**said, "pid": os.getppid(), "start": lock.process(os.getppid())[1], "token": "theirs"}) + "\n").encode()
        slow = lock.Lock(self.roots)
        self.lock.write_bytes(live)  # the faster run's lock, in place of the stale one
        self.assertFalse(slow._clear(stale, said))
        self.assertEqual(self.lock.read_bytes(), live)
        self.assertEqual(self.temporaries(), [])


class DocumentedTests(unittest.TestCase):
    def test_the_rule_is_written_down_where_it_is_made(self) -> None:
        text = " ".join((lock.__doc__ or "").split())
        for words in (
            "PROVABLY not running", "the same platform and the same host name", "boot_id", "process-id namespace",
            "started at another moment", "When in doubt the lock is not cleared", "exit code of every refusal, 2",
            "remove the file it names", "A run that only reads",
        ):
            self.assertIn(words, text)
        self.assertEqual(EXIT_ERROR, 2)
        self.assertIn("ends with one line and exit code 2", " ".join((fileops.__doc__ or "").split()))


if __name__ == "__main__":
    unittest.main()
