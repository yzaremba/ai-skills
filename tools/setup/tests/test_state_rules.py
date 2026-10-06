"""The rules of setup's state that keep a user's data (the second review).

    - A project's state is in the project: its record, its backups, its
      lock. A copy of a project is a project of its own; two homes that
      use one project see one record.
    - Setup removes no backup but with the record that lists it, and no
      file that is only named like one of its temporaries.
    - A file setup created is never removed whole once it holds anything
      setup did not write.

Run from the repository root:
    python -B -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401
from crash_support import KILL, Disk, stopped
from fileops_support import POSIX, SYMLINKS, OpsCase, snapshot
from wfsetup import blocks, fileops, fsio, lock, manifest as records
from wfsetup.errors import SetupError
from wfsetup.manifest import Roots

STATE = Path(".agents") / "workflow-setup"


def gone_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def orphan(roots: Roots) -> None:
    """Make every lock this process left under ``roots`` the lock of a
    process that is gone, as a kill leaves it."""
    lock._HELD.clear()
    for project in roots.scopes():
        path = lock.lock_file(roots, project)
        if not path.is_file():
            continue
        said = json.loads(path.read_text(encoding="utf-8"))
        said["pid"], said["start"] = gone_pid(), "0"
        path.write_bytes((json.dumps(said) + "\n").encode("utf-8"))


class Case(OpsCase):
    def setUp(self) -> None:
        super().setUp()
        self.put(self.project / ".gitignore", b"node_modules/\n*.log")
        self.put(self.project / ".claude" / "settings.json", b'{\n  "theme": "dark"\n}\n')
        self.put(self.project / "src" / "main.py", b"print(1)\n")
        self.put(self.home / ".codex" / "config.toml", b'model = "x"\n')
        self.put(self.home / ".claude" / "CLAUDE.md", b"# Mine\nkeep\n")

    def project_plan(self, roots: Roots | None = None) -> fileops.Plan:
        roots = roots or self.roots
        plan = fileops.Plan(roots, stamp=self.stamp())
        project = roots.project
        assert project is not None
        plan.edit_json(project / ".claude" / "settings.json", set={"agent": "manager"})
        plan.write_file(project / ".claude" / "agents" / "manager.md", "generated\n", inputs="d")
        plan.edit_block(project / ".codex" / "config.toml", 'model = "m"\n', place=fileops.HEAD)
        plan.ignore(add=[".claude/agents/manager.md"])
        return plan

    def home_plan(self) -> fileops.Plan:
        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated\n", inputs="d")
        plan.edit_block(self.home / ".claude" / "CLAUDE.md", "pointer\n")
        plan.edit_block(self.home / ".codex" / "config.toml", "top = 1\n", name="codex-settings", place=fileops.HEAD)
        return plan

    def undo(self, roots: Roots | None = None, project: bool = True) -> list:
        roots = roots or self.roots
        kept = fileops.plan_reversal(roots, project=project, stamp=self.stamp()).apply().kept
        fileops.remove_state(roots, project=project)
        return kept

    def files(self, root: Path) -> list[str]:
        return sorted(name for name, value in snapshot(root).items() if value[0] == "file")


class ProjectStateTests(Case):
    def test_a_run_on_a_project_keeps_all_of_its_state_in_the_project(self) -> None:
        before_home = snapshot(self.home)
        self.project_plan().apply()
        self.assertEqual(snapshot(self.home), before_home)   # no state directory, no lock, no backup in the home
        state = self.project / STATE
        self.assertTrue((state / "manifest.json").is_file())
        self.assertFalse((state / "lock").exists())
        held = [name for name in self.files(state) if name != "manifest.json"]
        self.assertTrue(held and all(name.startswith("backups/") for name in held), held)
        record = json.loads((state / "manifest.json").read_text(encoding="utf-8"))
        text = json.dumps(record)
        self.assertNotIn('"home:', text)
        self.assertNotIn('"clone:', text)
        for key in record["entries"]:
            self.assertTrue(key.startswith("project:"), key)
        for backup in record["backups"]:
            self.assertRegex(backup["backup"], r"^project:\.agents/workflow-setup/backups/[^/]+/project/")
        self.assertEqual(record["entries"]["project:.agents"], {"kind": "directory"})
        self.assertEqual(record["entries"]["project:.agents/workflow-setup"], {"kind": "directory"})

    def test_the_ignore_block_lists_the_state_directory(self) -> None:
        self.project_plan().apply()
        held = blocks.content_of((self.project / ".gitignore").read_bytes(), blocks.GITIGNORE)
        self.assertEqual(
            held, [".agents/workflow-setup/", ".agents/workflow.local.toml", ".claude/agents/manager.md", ".wfsetup-*.tmp"]
        )
        self.assertNotIn(".agents/workflow.manifest.json", held)

    def test_a_home_run_and_a_project_run_take_their_own_locks(self) -> None:
        taken: list[bool] = []
        real = lock.held

        def held(roots, **options):
            taken.append(bool(options.get("project", False)))
            return real(roots, **options)

        with mock.patch.object(lock, "held", side_effect=held):
            self.project_plan().apply()
            self.assertEqual(taken, [True])
            del taken[:]
            self.home_plan().apply()
            self.assertEqual(taken, [False])
        with lock.held(self.roots):   # the home is locked: the project is not
            self.undo()
        self.assertFalse((self.project / ".agents").exists())

    def test_a_copy_of_a_project_is_a_project_of_its_own(self) -> None:
        pristine = snapshot(self.project)
        self.project_plan().apply()
        copy = self.root / "copy"
        shutil.copytree(self.project, copy, symlinks=True)
        other = Roots(self.home, copy, self.clone)
        self.assertEqual(self.undo(other), [])
        self.assertEqual(snapshot(copy), pristine)
        # The original still has its record and its backups, and goes back exactly.
        self.assertTrue((self.project / STATE / "manifest.json").is_file())
        self.assertEqual(self.undo(), [])
        self.assertEqual(snapshot(self.project), pristine)

    def test_two_homes_use_one_project_one_after_the_other(self) -> None:
        pristine = snapshot(self.project)
        second = self.root / "second-home"
        second.mkdir()
        other = Roots(second, self.project, self.clone)
        self.project_plan().apply()
        after = snapshot(self.project)
        again = self.project_plan(other).apply()
        self.assertEqual(again.lines, [fileops.UP_TO_DATE])
        self.assertEqual(snapshot(self.project), after)
        self.assertEqual(os.listdir(second), [])
        self.assertEqual(self.undo(other), [])               # either home can take it back
        self.assertEqual(snapshot(self.project), pristine)
        self.assertEqual(self.project_plan().describe().changed, True)

    def test_a_run_killed_from_one_home_is_finished_from_the_other(self) -> None:
        pristine = snapshot(self.project)
        second = self.root / "second-home"
        second.mkdir()
        other = Roots(second, self.project, self.clone)
        counter = Disk()
        self.assertFalse(stopped(lambda: self.project_plan().apply(), counter))
        self.undo()
        self.assertEqual(snapshot(self.project), pristine)
        for point in range(1, counter.count + 1):
            with self.subTest(point=point):
                self.assertTrue(stopped(lambda: self.project_plan().apply(), Disk(point, KILL)))
                orphan(self.roots)
                with Disk():
                    self.project_plan(other).apply()
                    self.assertEqual(self.project_plan(other).describe().lines, [fileops.UP_TO_DATE])
                    self.assertEqual(self.undo(other), [])
                self.assertEqual(snapshot(self.project), pristine)
                self.assertEqual(os.listdir(second), [])

    def test_a_lock_taken_on_another_system_is_never_cleared(self) -> None:
        state = self.project / STATE
        state.mkdir(parents=True)
        theirs = {**lock.identity(), "system": "win32" if sys.platform != "win32" else "linux"}
        data = (json.dumps({"schema_version": 1, "pid": 999999, "start": "1", "identity": theirs, "token": "ab" * 8}) + "\n").encode()
        (state / "lock").write_bytes(data)
        before = self.snap()
        with self.assertRaises(fileops.LockHeld) as caught:
            self.project_plan().apply()
        line = caught.exception.lines[0]
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn(str(state / "lock"), line)
        self.assertIn("remove that file", line)
        self.assertIn("project", line)
        self.assertEqual(self.snap(), before)

    def test_uninstalling_the_home_and_the_project_are_independent_in_either_order(self) -> None:
        pristine = self.snap()
        for first in (False, True):
            with self.subTest(home_first=not first):
                self.home_plan().apply()
                self.project_plan().apply()
                self.assertEqual(self.undo(project=first), [])
                self.assertFalse((self.roots.state_dir_of(first)).exists())
                self.assertTrue((self.roots.manifest_file_of(not first)).is_file())
                self.assertEqual(self.undo(project=not first), [])
                self.assertEqual(self.snap(), pristine)


class RecordReachTests(Case):
    """A record is data from the disk: a project's names the project and
    nothing else, and the user-level one no project."""

    SHA = "0" * 64

    def refused(self, project: bool, record: dict, word: str) -> None:
        file = self.roots.manifest_file_of(project)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({"schema_version": 1, "backups": [], **record}), encoding="utf-8")
        before = self.snap()
        for run in (
            lambda: fileops.read_record(self.roots),
            lambda: fileops.plan_reversal(self.roots, project=project, stamp=self.stamp()).apply(),
            lambda: self.project_plan().apply(),
            lambda: fileops.remove_state(self.roots, project=project),
        ):
            with self.assertRaises(SetupError) as caught:
                run()
            self.assertEqual(len(caught.exception.lines), 1)
            self.assertIn("is not a setup record", caught.exception.lines[0])
            self.assertIn(word, caught.exception.lines[0])
        self.assertEqual(self.snap(), before)
        shutil.rmtree(file.parent.parent)

    def test_a_projects_record(self) -> None:
        backup = {"sha256": self.SHA, "mode": 420}
        for name, record, word in (
            ("a home path", {"entries": {"home:.bashrc": {"kind": "file", "sha256": self.SHA}}}, "only paths of the project"),
            ("a clone path", {"entries": {"clone:x": {"kind": "file", "sha256": self.SHA}}}, "clone"),
            ("a backup in the home", {"entries": {"project:x": {"kind": "removed-file", "original": {
                "backup": "home:.agents/workflow-setup/backups/s/project/x", **backup}}}}, "its backup is not under"),
            ("another path's backup", {"entries": {"project:x": {"kind": "removed-file", "original": {
                "backup": "project:.agents/workflow-setup/backups/s/project/y", **backup}}}}, "not the backup of this path"),
            ("a link into the home", {"entries": {"project:l": {"kind": "link", "target": "home:.ssh"}}}, "outside the project"),
            ("a link into the clone", {"entries": {"project:l": {"kind": "link", "target": "clone:x"}}}, "outside the project"),
            ("a removed link into the home", {"entries": {"project:l": {"kind": "removed-link", "target": "home:x"}}},
             "outside the project"),
            ("git's own files", {"entries": {"project:.git/config": {"kind": "text", "blocks": {}}}}, ".git"),
            ("git's own files, deeper", {"entries": {"project:sub/.git/hooks/pre-commit": {"kind": "file"}}}, ".git"),
            ("the state, as a file", {"entries": {"project:.agents/workflow-setup": {"kind": "file"}}}, "state"),
            ("in the state", {"entries": {"project:.agents/workflow-setup/manifest.json": {"kind": "file"}}}, "state"),
            ("a pending home path", {"entries": {}, "pending": [{"path": "home:.bashrc", "after": {"kind": "absent"}}]},
             "only paths of the project"),
            ("a listed home backup", {"entries": {}, "backups": [{
                "path": "project:x", "kind": "file", "backup": "home:.agents/workflow-setup/backups/s/project/x",
                **backup, "stamp": "s"}]}, "its backup is not under"),
            ("a run that is no token", {"entries": {}, "run": {"token": "../../x"}}, "run"),
            ("not a number", {"entries": {"project:x": {"kind": "removed-directory", "mode": float("nan")}}}, "NaN"),
        ):
            with self.subTest(name=name):
                self.refused(True, record, word)

    def test_the_user_level_record(self) -> None:
        for name, record, word in (
            ("a project path", {"entries": {"project:x": {"kind": "file"}}}, "no path of a project"),
            ("a link into a project", {"entries": {"home:l": {"kind": "link", "target": "project:x"}}}, "in a project"),
            ("a backup in a project", {"entries": {"home:x": {"kind": "removed-file", "original": {
                "backup": "project:.agents/workflow-setup/backups/s/home/x", "sha256": self.SHA, "mode": 420}}}},
             "its backup is not under"),
            ("git's own files", {"entries": {"home:.git/config": {"kind": "file"}}}, ".git"),
        ):
            with self.subTest(name=name):
                self.refused(False, record, word)

    def test_a_link_out_of_the_project_is_recorded_by_its_own_text(self) -> None:
        if not SYMLINKS:
            self.skipTest("needs a symlink")
        os.symlink(self.home / ".claude", self.project / "theirs", target_is_directory=True)
        plan = self.plan()
        plan.remove_link(self.project / "theirs")
        plan.apply()
        entry = self.record().get("project:theirs")
        self.assertEqual(entry["target"], f"raw:{self.home / '.claude'}")
        for backup in self.record().project.backups:
            self.assertTrue(backup["target"].startswith(("raw:", "project:")), backup)
        self.undo()
        self.assertEqual(fsio.read_link(self.project / "theirs"), str(self.home / ".claude"))

    def test_a_plan_changes_nothing_under_a_git_directory(self) -> None:
        config = self.put(self.project / ".git" / "config", "[core]\n")
        for fill in (
            lambda plan: plan.edit_block(config, "x\n", syntax=blocks.GITIGNORE),
            lambda plan: plan.write_file(self.project / ".git" / "hooks" / "pre-commit", "x\n"),
            lambda plan: plan.remove_file(config),
        ):
            plan = self.plan()
            fill(plan)
            error = self.refused_plan(plan)
            self.assertIn(".git", error.lines[0])

    def refused_plan(self, plan: fileops.Plan) -> fileops.PlanError:
        before = self.snap()
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertEqual(self.snap(), before)
        return caught.exception


class BackupTests(Case):
    """No backup is removed but with the record that lists it."""

    def backups(self, project: bool = False) -> list[str]:
        base = self.roots.backups_dir_of(project)
        return sorted(name for name, value in snapshot(base).items() if value[0] == "file") if base.is_dir() else []

    def test_with_the_record_gone_no_run_touches_a_backup(self) -> None:
        self.home_plan().apply()
        held = self.backups()
        self.assertTrue(held)
        self.manifest_file.unlink()
        saved = {name: (self.roots.backups_dir / name).read_bytes() for name in held}
        plan = self.plan()
        plan.write_file(self.home / ".agents" / "workflow.toml", "schema_version = 1\n", replace=fileops.ANY)
        described = plan.describe()
        self.assertTrue(any("no record lists" in note and "--discard-backups" in note for note in described.notes))
        result = plan.apply()
        self.assertTrue(any("no record lists" in note for note in result.notes), result.notes)
        self.assertEqual({name: (self.roots.backups_dir / name).read_bytes() for name in held}, saved)
        self.assertEqual(len(fileops.unlisted_backups(self.roots)), len(held))
        # The way back removes its own record and leaves them still.
        fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(self.backups(), held)
        self.assertFalse(self.manifest_file.exists())
        self.assertTrue(self.state.is_dir())
        self.assertFalse((self.state / "lock").exists())

    def test_only_the_explicit_command_removes_them_and_only_them(self) -> None:
        self.home_plan().apply()
        listed = self.backups()
        stray = self.put(self.roots.backups_dir / "20200101T000000000000Z" / "home" / ".bashrc", "the only copy\n")
        self.assertEqual(fileops.unlisted_backups(self.roots), [stray])
        self.assertEqual(fileops.leftovers(self.roots).unlisted, [stray])
        removed = fileops.discard_backups(self.roots)
        self.assertEqual(removed, [stray])
        self.assertEqual(self.backups(), listed)
        self.assertFalse(stray.parent.parent.exists())
        self.assertEqual(fileops.discard_backups(self.roots), [])
        self.assertEqual(self.backups(), listed)

    def test_remove_state_removes_the_listed_backups_and_no_other_file(self) -> None:
        for project in (False, True):
            with self.subTest(project=project):
                (self.project_plan() if project else self.home_plan()).apply()
                base = self.roots.backups_dir_of(project)
                stray = self.put(base / "20200101T000000000000Z" / ("project" if project else "home") / "mine.txt", "mine\n")
                beside = self.put(base / sorted(os.listdir(base))[-1] / "note.txt", "also mine\n")
                fileops.plan_reversal(self.roots, project=project, stamp=self.stamp()).apply()
                self.assertTrue(fileops.remove_state(self.roots, project=project))
                self.assertEqual(self.backups(project), sorted(
                    path.relative_to(base).as_posix() for path in (stray, beside)
                ))
                self.assertFalse(self.roots.manifest_file_of(project).exists())
                self.assertEqual(sorted(os.listdir(self.roots.state_dir_of(project))), ["backups"])
                shutil.rmtree(self.roots.state_dir_of(project).parent)

    def test_a_removal_that_was_made_keeps_its_backup_when_something_is_there_again(self) -> None:
        mine = self.put(self.home / ".claude" / "rules" / "mine.md", "the user's own, edited\n")
        counter = Disk()

        def run() -> None:
            plan = self.plan()
            plan.remove_file(mine)
            plan.apply()

        stopped(run, counter)
        point = next(index + 1 for index, call in enumerate(counter.calls) if call == f"unlink {mine}")
        self.put(mine, "the user's own, edited\n")
        fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        fileops.remove_state(self.roots)
        self.assertTrue(stopped(run, Disk(point, KILL, after=True)))
        orphan(self.roots)
        self.assertFalse(mine.exists())
        self.put(mine, "another file, put there after the crash\n")
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered, record.dropped), (1, 0))
        entry = record.get("home:.claude/rules/mine.md")
        self.assertEqual(entry["kind"], "removed-file")
        backup = record.path(entry["original"]["backup"])
        self.assertEqual(backup.read_bytes(), b"the user's own, edited\n")
        # Any run that writes, and the way back, leave the only copy where it is.
        fileops.recover(self.roots)
        result = fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        self.assertEqual([key for key, _ in result.kept], ["home:.claude/rules/mine.md"])
        self.assertFalse(fileops.remove_state(self.roots))
        self.assertEqual(backup.read_bytes(), b"the user's own, edited\n")
        self.assertEqual(mine.read_bytes(), b"another file, put there after the crash\n")
        # A second removal of what is there now is refused: one backup to go back to.
        plan = self.plan()
        plan.remove_file(mine)
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertIn("a file is there again where setup removed one of yours", caught.exception.lines[0])
        # Once the user takes the new file away, the old one comes back.
        mine.unlink()
        self.assertEqual(fileops.plan_reversal(self.roots, stamp=self.stamp()).apply().kept, [])
        self.assertEqual(mine.read_bytes(), b"the user's own, edited\n")

    def test_a_removal_that_was_not_made_is_dropped_and_its_backup_stays_listed(self) -> None:
        mine = self.put(self.home / ".claude" / "rules" / "mine.md", "the user's own\n")
        counter = Disk()

        def run() -> None:
            plan = self.plan()
            plan.remove_file(mine)
            plan.apply()

        stopped(run, counter)
        point = next(index + 1 for index, call in enumerate(counter.calls) if call == f"unlink {mine}")
        self.put(mine, "the user's own\n")
        fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        fileops.remove_state(self.roots)
        self.assertTrue(stopped(run, Disk(point, KILL)))   # before the removal: the backup is written, the file is there
        orphan(self.roots)
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered, record.dropped), (0, 1))
        self.assertIsNone(record.get("home:.claude/rules/mine.md"))
        fileops.recover(self.roots)
        saved = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        self.assertEqual([item["path"] for item in saved["backups"]], ["home:.claude/rules/mine.md"])
        self.assertTrue(self.roots.path(saved["backups"][0]["backup"]).is_file())
        self.assertNotIn("pending", saved)
        self.assertNotIn("run", saved)
        self.assertEqual(fileops.unlisted_backups(self.roots), [])
        fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertFalse((self.home / ".agents").exists())
        self.assertEqual(mine.read_bytes(), b"the user's own\n")

    def test_a_failure_while_the_backups_are_written_changes_nothing_of_the_users(self) -> None:
        before = {name: value for name, value in self.snap().items() if "/.agents" not in name}
        real = fsio.atomic_write
        written: list[Path] = []

        def write(path, data, mode=None):
            if "backups" in Path(path).parts:
                written.append(Path(path))
                if len(written) == 2:
                    raise SetupError(f"{path}: cannot be written: No space left on device")
            return real(path, data, mode)

        with mock.patch.object(fsio, "atomic_write", side_effect=write):
            with self.assertRaises(SetupError):
                self.home_plan().apply()
        self.assertEqual({name: value for name, value in self.snap().items() if "/.agents" not in name}, before)
        saved = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        self.assertNotIn("pending", saved)
        self.assertEqual(sorted(saved["entries"]), ["home:.agents", "home:.agents/workflow-setup"])
        self.assertEqual(len(saved["backups"]), 1)                       # the one that was written: listed, not removed
        self.assertEqual(fileops.unlisted_backups(self.roots), [])
        self.assertFalse((self.state / "lock").exists())
        self.home_plan().apply()                                          # the same run again goes through
        fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertFalse((self.home / ".agents").exists())

    def test_the_state_stays_while_a_change_is_pending(self) -> None:
        self.home_plan().apply()
        data = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        data["entries"] = {key: entry for key, entry in data["entries"].items() if entry["kind"] == "directory" and "agents" in key.split(":")[1].split("/")[0:1] and key.startswith("home:.agents")}
        data["pending"] = [{"path": "other:x", "after": {"kind": "file", "sha256": "0" * 64}, "set": True, "entry": None}]
        self.manifest_file.write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(fileops.remove_state(self.roots))
        self.assertTrue(self.manifest_file.is_file())


class TemporaryTests(Case):
    """Only a temporary the record lists is removed."""

    LOOKALIKES = (
        ".claude/.wfsetup-cafe.tmp", ".claude/agents/.wfsetup-deadbeef.tmp", ".codex/.wfsetup-12345678.tmp",
        ".wfsetup-abcd.tmp",
    )

    def plant(self) -> dict[str, tuple]:
        for name in self.LOOKALIKES:
            self.put(self.home / name, "the user's own data, named unluckily\n")
        (self.home / ".claude" / "rules").mkdir(parents=True, exist_ok=True)
        (self.home / ".claude" / "rules" / ".wfsetup-beef.tmp").mkdir()
        self.put(self.project / ".wfsetup-abcdabcd.tmp", "mine\n")
        self.put(self.home / ".wfsetup-f00d.tmp" / "workflow-setup" / "lock", "a file of the user's called lock\n")
        return self.snap()

    def test_a_file_that_is_only_named_like_one_is_never_removed(self) -> None:
        before = self.plant()
        self.home_plan().apply()
        self.project_plan().apply()
        found = fileops.leftovers(self.roots)
        self.assertEqual(found.temporaries, [])
        self.assertGreaterEqual(len(found.lookalikes), 4)
        fileops.recover(self.roots)
        self.assertEqual(self.undo(project=True), [])
        self.assertEqual(self.undo(project=False), [])
        self.assertEqual(self.snap(), before)

    def test_what_a_killed_run_left_under_its_recorded_name_is_removed_and_nothing_else(self) -> None:
        self.plant()
        counter = Disk()
        stopped(lambda: self.home_plan().apply(), counter)
        target = self.home / ".claude" / "agents"
        point = next(
            index + 1 for index, call in enumerate(counter.calls)
            if call.startswith("create ") and Path(call.split(" ", 1)[1]).parent == target
        )
        fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        fileops.remove_state(self.roots)
        before = self.snap()
        plan = self.home_plan()
        self.assertTrue(stopped(plan.apply, Disk(point, KILL, after=True)))
        orphan(self.roots)
        left = target / fsio.temporary_names(plan.token)[0]
        self.assertTrue(left.is_file())                       # under the name the record lists
        self.assertEqual(json.loads(self.manifest_file.read_text(encoding="utf-8"))["run"], {"token": plan.token})
        self.assertEqual(fileops.leftovers(self.roots).temporaries, [left])
        described = self.home_plan().describe()
        self.assertIn("1 temporary files it recorded", " ".join(described.lines))
        self.assertTrue(left.is_file())                       # a dry run removes nothing
        result = fileops.recover(self.roots)
        self.assertTrue(result.changed)
        self.assertFalse(left.exists())
        self.assertTrue((target / ".wfsetup-deadbeef.tmp").is_file())
        self.assertEqual(self.undo(project=False), [])
        self.assertEqual(self.snap(), before)

    def test_a_recorded_temporary_counts_as_absent_in_a_directory_that_is_to_go(self) -> None:
        self.home_plan().apply()
        token = "0123abcd"
        data = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        data["run"] = {"token": token}
        data["pending"] = [{"path": "home:.claude/agents/coder.md", "after": None, "set": False, "entry": None}]
        self.manifest_file.write_text(json.dumps(data), encoding="utf-8")
        left = self.put(self.home / ".claude" / "agents" / fsio.temporary_names(token)[0], "half written\n")
        result = fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        self.assertEqual(result.kept, [])
        self.assertFalse(left.exists())
        self.assertFalse((self.home / ".claude" / "agents").exists())

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_recorded_temporary_is_not_removed_through_a_link_out_of_the_home(self) -> None:
        self.home_plan().apply()
        token = "0123abcd"
        outside = self.root / "outside"
        outside.mkdir()
        left = self.put(outside / fsio.temporary_names(token)[0], "not setup's to remove\n")
        shutil.rmtree(self.home / ".claude" / "agents")
        os.symlink(outside, self.home / ".claude" / "agents", target_is_directory=True)
        data = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        data["run"] = {"token": token}
        data["pending"] = [{"path": "home:.claude/agents/coder.md", "after": None, "set": False, "entry": None}]
        self.manifest_file.write_text(json.dumps(data), encoding="utf-8")
        for follow in (False, True):
            fileops.recover(self.roots, follow_config_symlinks=follow)
            self.assertEqual(left.read_bytes(), b"not setup's to remove\n")

    @unittest.skipUnless(POSIX, "permission bits")
    def test_a_temporary_file_is_its_owners_alone_while_it_is_written(self) -> None:
        seen: list[int] = []
        real = os.open

        def opened(path, flags, mode=0o777, **options):
            if flags & os.O_CREAT:
                seen.append(mode)
            return real(path, flags, mode, **options)

        old = os.umask(0)
        self.addCleanup(os.umask, old)
        with mock.patch.object(fsio.os, "open", side_effect=opened):
            fsio.atomic_write(self.home / "world-readable.txt", b"x", 0o644)
            fsio.write_new(self.home / "new.txt", b"x")
        self.assertEqual(seen, [0o600, 0o600])
        self.assertEqual(os.stat(self.home / "world-readable.txt").st_mode & 0o777, 0o644)


class CreatedFileTests(Case):
    """A file setup created is the user's as soon as others write into it."""

    def test_a_created_file_that_others_wrote_into_is_never_removed_whole(self) -> None:
        cases = {
            "toml": (self.home / ".codex" / "fresh.toml",
                     lambda plan, path: plan.edit_block(path, "top = 1\n", name="codex-settings", place=fileops.HEAD),
                     lambda data: b'[projects."/home/me/work"]\ntrust = "yes"\n\n' + data + b'model = "mine"\n',
                     lambda plan, path: plan.edit_block(path, "top = 2\n", name="codex-settings", place=fileops.HEAD),
                     b'[projects."/home/me/work"]\ntrust = "yes"\n\nmodel = "mine"\n'),
            "markdown": (self.home / ".codex" / "AGENTS.md",
                         lambda plan, path: plan.edit_block(path, "pointer\n"),
                         lambda data: b"# My rules\nBe brief.\n" + data,
                         lambda plan, path: plan.edit_block(path, "pointer, again\n"),
                         b"# My rules\nBe brief.\n"),
            "json": (self.home / ".claude" / "fresh.json",
                     lambda plan, path: plan.edit_json(path, set={"agent": "manager"}),
                     lambda data: b'{\n  "agent": "manager",\n  "theme": "dark"\n}\n',
                     lambda plan, path: plan.edit_json(path, set={"agent": "lead"}),
                     b'{\n  "theme": "dark"\n}\n'),
        }
        keys = {"home:.claude/fresh.json": ("agent",)}
        for name, (path, first, others, second, expected) in cases.items():
            with self.subTest(name=name):
                plan = fileops.Plan(self.roots, stamp=self.stamp(), key_list=keys)
                first(plan, path)
                plan.apply()
                self.assertTrue(self.record().get(self.roots.key(path))["created"])
                path.write_bytes(others(path.read_bytes()))            # another program, or the user
                plan = fileops.Plan(self.roots, stamp=self.stamp(), key_list=keys)
                second(plan, path)
                plan.apply()                                           # setup writes again: its hash is of the whole file
                entry = self.record().get(self.roots.key(path))
                self.assertEqual(entry["sha256"], fsio.sha256(path.read_bytes()))
                reversal = fileops.plan_reversal(self.roots, stamp=self.stamp())
                reversal.key_list = keys
                result = reversal.apply()
                self.assertEqual(result.kept, [])
                self.assertEqual(path.read_bytes(), expected)
                self.assertIsNone(self.record().get(self.roots.key(path)))

    def test_a_created_file_with_nothing_but_setups_part_goes(self) -> None:
        path = self.home / ".codex" / "AGENTS.md"
        plan = self.plan()
        plan.edit_block(path, "pointer\n")
        plan.apply()
        fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        self.assertFalse(path.exists())

    def test_white_space_left_by_the_user_does_not_keep_it(self) -> None:
        path = self.home / ".codex" / "AGENTS.md"
        plan = self.plan()
        plan.edit_block(path, "pointer\n")
        plan.apply()
        path.write_bytes(b"\n\n" + path.read_bytes() + b"  \n")
        fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        self.assertFalse(path.exists())

    def test_removing_a_created_file_that_holds_more_than_setups_part_keeps_a_backup(self) -> None:
        path = self.home / ".codex" / "AGENTS.md"
        plan = self.plan()
        plan.edit_block(path, "pointer\n")
        plan.apply()
        path.write_bytes(b"# My rules\n" + path.read_bytes())
        plan = self.plan()
        plan.edit_block(path, "pointer, again\n")
        plan.apply()
        held = path.read_bytes()
        plan = self.plan()
        plan.remove_file(path)
        plan.apply()
        entry = self.record().get("home:.codex/AGENTS.md")
        self.assertEqual(entry["kind"], "removed-file")
        self.assertEqual(self.record().path(entry["original"]["backup"]).read_bytes(), held)


class StateDirectoryTests(Case):
    """Whose a directory is: nothing on disk is believed but the marker."""

    def test_the_users_own_agents_directory_stays_with_what_is_in_it(self) -> None:
        for project in (False, True):
            with self.subTest(project=project):
                root = self.project if project else self.home
                mine = self.put(root / ".agents" / "skills" / "mine" / "SKILL.md", "mine\n")
                (self.project_plan() if project else self.home_plan()).apply()
                self.assertIsNone(self.record().get(f"{'project' if project else 'home'}:.agents"))
                self.undo(project=project)
                self.assertEqual(mine.read_bytes(), b"mine\n")
                self.assertEqual(sorted(os.listdir(root / ".agents")), ["skills"])

    def test_a_record_that_claims_agents_does_not_take_a_users_file_with_it(self) -> None:
        for project in (False, True):
            with self.subTest(project=project):
                root = self.project if project else self.home
                (self.project_plan() if project else self.home_plan()).apply()
                self.assertIsNotNone(self.record().get(f"{'project' if project else 'home'}:.agents"))
                mine = self.put(root / ".agents" / "notes.txt", "mine\n")   # put there after setup made the directory
                fileops.plan_reversal(self.roots, project=project, stamp=self.stamp()).apply()
                self.assertTrue(fileops.remove_state(self.roots, project=project))
                self.assertEqual(mine.read_bytes(), b"mine\n")
                self.assertEqual(sorted(os.listdir(root / ".agents")), ["notes.txt"])
                self.assertFalse((root / lock.MARKER_NAME).exists())

    def test_giving_the_lock_back_leaves_an_agents_directory_that_holds_something(self) -> None:
        with lock.held(self.roots) as mine:
            self.assertEqual(mine.created, {lock.AGENTS, lock.STATE})
            self.assertTrue((self.home / lock.MARKER_NAME).is_dir())
            note = self.put(self.home / ".agents" / "notes.txt", "mine\n")
        self.assertEqual(note.read_bytes(), b"mine\n")
        self.assertEqual(sorted(os.listdir(self.home / ".agents")), ["notes.txt"])
        self.assertFalse((self.home / lock.MARKER_NAME).exists())
        with lock.held(self.roots):
            pass
        self.assertEqual(sorted(os.listdir(self.home / ".agents")), ["notes.txt"])

    def test_a_lock_that_saved_nothing_leaves_nothing(self) -> None:
        before = self.snap()
        with lock.held(self.roots), lock.held(self.roots, project=True):
            pass
        self.assertEqual(self.snap(), before)

    def test_a_planted_list_of_created_directories_removes_none(self) -> None:
        state = self.home / STATE
        state.mkdir(parents=True)                                  # the user's own, empty .agents with a state directory
        said = {"schema_version": 1, "pid": gone_pid(), "start": "0", "identity": lock.identity(), "token": "ab" * 8,
                "created": ["agents", "state", "/etc", "../../.claude", "home"]}
        (state / "lock").write_text(json.dumps(said) + "\n", encoding="utf-8")
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertTrue((self.home / ".agents").is_dir())           # not setup's, whatever the lock said
        self.assertFalse(state.exists())                            # exactly the state directory, and empty
        self.assertTrue((self.home / ".claude").is_dir())

    def test_the_marker_of_a_killed_start_is_settled_by_the_next_run_or_by_the_way_back(self) -> None:
        pristine = self.snap()
        for stage in ("marker", "agents", "state"):
            with self.subTest(left=stage):
                (self.home / lock.MARKER_NAME).mkdir()
                if stage != "marker":
                    (self.home / ".agents").mkdir()
                if stage == "state":
                    (self.home / STATE).mkdir()
                self.assertTrue(fileops.remove_state(self.roots))   # the way back, with no record
                self.assertEqual(self.snap(), pristine)
                (self.home / lock.MARKER_NAME).mkdir()
                if stage != "marker":
                    (self.home / ".agents").mkdir()
                if stage == "state":
                    (self.home / STATE).mkdir()
                self.home_plan().apply()                             # or the next run, which records what it finds
                self.assertFalse((self.home / lock.MARKER_NAME).exists())
                self.assertEqual(self.record().get("home:.agents"), {"kind": "directory"})
                self.assertEqual(self.undo(project=False), [])
                self.assertEqual(self.snap(), pristine)


class SmallGuardTests(Case):
    def test_a_toml_string_of_three_single_quotes_that_ends_in_a_backslash(self) -> None:
        # In a literal string a backslash escapes nothing: the string ends
        # at the quotes, and the marker after it is a marker.
        data = b"a = '''\nx\\'''\n# workflow-setup:start\ny = 1\n# workflow-setup:end\n"
        self.assertEqual(blocks.content_of(data, blocks.TOML), ["y = 1"])
        inside = b'a = """\nx\\"""\n# workflow-setup:start\n"""\n'
        self.assertEqual(blocks.scan(blocks.split_bom(inside)[1], blocks.TOML), {})

    @unittest.skipUnless(SYMLINKS and POSIX, "needs a symlink and a hard link")
    def test_a_file_with_two_names_is_refused_through_a_followed_link_too(self) -> None:
        real = self.put(self.home / "dotfiles" / "config.toml", 'model = "x"\n')
        os.link(real, self.home / "dotfiles" / "second-name")
        os.unlink(self.home / ".codex" / "config.toml")
        os.symlink(real, self.home / ".codex" / "config.toml")
        plan = self.plan(follow_config_symlinks=True)
        plan.edit_block(self.home / ".codex" / "config.toml", "top = 1\n", name="codex-settings", place=fileops.HEAD)
        before = self.snap()
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertIn(fileops.HARD_LINK, caught.exception.codes())
        self.assertEqual(self.snap(), before)

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_half_made_swap_below_setups_own_link_is_not_read_through_it(self) -> None:
        skill = self.put(self.clone / "json-tools" / "SKILL.md", "the clone's\n").parent
        plan = self.plan()
        plan.create_link(self.home / ".claude" / "skills" / "json-tools", skill)
        plan.apply()
        data = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        data["pending"] = [{
            "path": "home:.claude/skills/json-tools/inner", "after": {"kind": "directory"}, "set": True,
            "entry": {"kind": "directory"}, "between": {"entry": {"kind": "removed-directory"}},
        }]
        self.manifest_file.write_text(json.dumps(data), encoding="utf-8")
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered, record.dropped), (0, 1))
        self.assertIsNone(record.get("home:.claude/skills/json-tools/inner"))

    def test_a_link_to_a_credentials_file_is_not_made_on_the_way_back(self) -> None:
        if not SYMLINKS:
            self.skipTest("needs a symlink")
        self.home_plan().apply()
        data = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        data["entries"]["home:.claude/rules/prd.md"] = {"kind": "removed-link", "target": "raw:../.credentials.json", "directory": False}
        self.manifest_file.write_text(json.dumps(data), encoding="utf-8")
        result = fileops.plan_reversal(self.roots, stamp=self.stamp()).apply()
        self.assertEqual([key for key, _ in result.kept], ["home:.claude/rules/prd.md"])
        self.assertIn("credentials", result.kept[0][1])
        self.assertFalse(os.path.lexists(self.home / ".claude" / "rules" / "prd.md"))
        self.assertFalse((self.home / ".claude" / "agents").exists())   # the rest was undone

    def test_a_plan_makes_no_link_to_a_credentials_file(self) -> None:
        secret = self.put(self.clone / "auth.json", "s")
        plan = self.plan()
        plan.create_link(self.home / ".claude" / "x", secret, directory=False)
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertIn(fileops.CREDENTIALS, caught.exception.codes())


if __name__ == "__main__":
    unittest.main()
