"""One test for each guard of the write path, which fails when the guard
is taken out (S14), and the guards the review of Phase 5 added: the clone
is never written to (B6), no directory above a path may turn into a link
under a run (S2), of what an interrupted run left only what its record
names is removed, and no backup (S4), and the smaller ones.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import support
from fileops_support import POSIX, SYMLINKS, OpsCase, snapshot
from wfsetup import blocks, cli, fileops, fsio, jsonkeys
from wfsetup.errors import EXIT_ERROR, EXIT_INTERRUPT, SetupError
from wfsetup.manifest import BACKUPS_KEY, PROJECT, PROJECT_BACKUPS_KEY, Manifest


class GuardCase(OpsCase):
    def link(self, target: Path, link: Path) -> None:
        """A link to a directory as this system makes one without asking
        for a privilege: a symlink, or on Windows a junction."""
        link.parent.mkdir(parents=True, exist_ok=True)
        fsio.make_link(str(target), link, True)

    def undo(self) -> list[tuple[str, str]]:
        kept: list[tuple[str, str]] = []
        for project in (True, False):
            kept += self.reversal(project=project).apply().kept
            fileops.remove_state(self.roots, project=project)
        return kept


class OriginalAndBackupTests(GuardCase):
    """What a way back restores, and from where."""

    def test_the_original_is_given_up_once_someone_else_changed_the_file(self) -> None:
        """The backup is the file without setup only while nobody else
        wrote to it. After the user did, restoring the backup would undo
        the user's change."""
        file = self.put(self.home / ".claude" / "CLAUDE.md", "a\n")
        plan = self.plan()
        plan.edit_block(file, "one\n")
        plan.apply()
        self.assertIsNotNone(self.record().get("home:.claude/CLAUDE.md")["original"])
        file.write_bytes(file.read_bytes() + b"the user's new line\n")
        plan = self.plan()
        plan.edit_block(file, "two\n")
        plan.apply()
        self.assertIsNone(self.record().get("home:.claude/CLAUDE.md")["original"])
        self.assertEqual(self.undo(), [])
        self.assertEqual(file.read_bytes(), b"a\nthe user's new line\n")

    def test_the_backup_is_kept_when_the_user_removed_the_file(self) -> None:
        text = self.put(self.home / ".claude" / "CLAUDE.md", "mine\n")
        whole = self.put(self.home / ".agents" / "workflow.toml", "mine = 1\n")
        plan = self.plan()
        plan.edit_block(text, "one\n")
        plan.write_file(whole, "setup = 1\n", replace=fileops.ANY)
        plan.apply()
        text.unlink()
        whole.unlink()
        kept = dict(self.reversal().apply().kept)
        self.assertIn("the backup of the original is kept", kept["home:.claude/CLAUDE.md"])
        self.assertIn("the backup of what was there before is kept", kept["home:.agents/workflow.toml"])
        record = self.record()
        for key, data in (("home:.claude/CLAUDE.md", b"mine\n"), ("home:.agents/workflow.toml", b"mine = 1\n")):
            entry = record.get(key)
            self.assertIsNotNone(entry, key)
            self.assertEqual(record.path(entry["original"]["backup"]).read_bytes(), data)
        self.assertFalse(fileops.remove_state(self.roots))  # the state stays with them
        # A removal asked of setup leaves the entry too, while it has an original.
        plan = self.plan()
        plan.remove_file(text)
        plan.remove_file(whole)
        plan.apply()
        self.assertIsNotNone(self.record().get("home:.claude/CLAUDE.md"))
        self.assertIsNotNone(self.record().get("home:.agents/workflow.toml"))

    def test_a_backup_that_is_not_what_it_was_is_never_restored(self) -> None:
        file = self.put(self.home / ".agents" / "workflow.toml", "mine = 1\n")
        gone = self.put(self.home / ".claude" / "rules" / "old.md", "v1\n")
        plan = self.plan()
        plan.write_file(file, "setup = 1\n", replace=fileops.ANY)
        plan.remove_file(gone)
        plan.apply()
        record = self.record()
        for key in ("home:.agents/workflow.toml", "home:.claude/rules/old.md"):
            record.path(record.get(key)["original"]["backup"]).write_bytes(b"damaged\n")
        kept = dict(self.reversal().apply().kept)
        self.assertIn("missing or damaged", kept["home:.agents/workflow.toml"])
        self.assertIn("missing or damaged", kept["home:.claude/rules/old.md"])
        self.assertEqual(file.read_bytes(), b"setup = 1\n")
        self.assertFalse(gone.exists())
        self.assertNotIn(b"damaged", b"".join(value[1] for name, value in self.snap().items()
                                               if value[0] == "file" and "/backups/" not in name))

    @unittest.skipUnless(POSIX, "permission bits")
    def test_a_backup_is_its_owners_alone_and_the_file_gets_its_own_bits_back(self) -> None:
        secret = self.put(self.home / ".codex" / "config.toml", 'key = "SECRET"\n', 0o644)
        script = self.put(self.home / ".claude" / "rules" / "run.sh", "#!/bin/sh\n", 0o755)
        plan = self.plan()
        plan.edit_block(secret, "top = 1\n", name="s", place=fileops.HEAD)
        plan.remove_file(script)
        plan.apply()
        backups = self.state / "backups"
        record = self.record()
        for key in ("home:.codex/config.toml", "home:.claude/rules/run.sh"):
            backup = record.path(record.get(key)["original"]["backup"])
            self.assertEqual(stat.S_IMODE(os.lstat(backup).st_mode), 0o600, key)
            for directory in [backup.parent, *backup.parent.parents]:
                if directory == self.state:
                    break
                self.assertEqual(stat.S_IMODE(os.lstat(directory).st_mode), 0o700, directory)
        self.assertEqual(stat.S_IMODE(os.lstat(backups).st_mode), 0o700)
        self.assertEqual(record.get("home:.codex/config.toml")["original"]["mode"], 0o644)
        self.assertEqual(self.undo(), [])
        self.assertEqual(stat.S_IMODE(os.lstat(secret).st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(os.lstat(script).st_mode), 0o755)
        self.assertEqual((secret.read_bytes(), script.read_bytes()), (b'key = "SECRET"\n', b"#!/bin/sh\n"))

    def test_removing_the_backups_of_a_record_removes_nothing_else(self) -> None:
        victim = self.put(self.home / "victim.md", "the user's\n")
        other = self.put(self.project / "src.py", "x\n")
        # A backup of the home's, which a project's record has no say over.
        homes = self.put(self.state / "backups" / "S1" / "home" / "c.md", "x\n")
        manifest = Manifest(self.project_manifest_file, PROJECT)
        manifest.backups = [
            {"path": "project:x", "kind": "file", "backup": "home:victim.md"},
            {"path": "project:x", "kind": "file", "backup": "project:src.py"},
            {"path": "project:x", "kind": "file", "backup": f"{BACKUPS_KEY}/../../../victim.md"},
            {"path": "project:x", "kind": "file", "backup": f"{PROJECT_BACKUPS_KEY}/../../../src.py"},
            {"path": "project:x", "kind": "file", "backup": f"{BACKUPS_KEY}/S1/home/c.md"},
        ]
        before = self.snap()
        fileops._remove_backups_of(self.roots, manifest)
        self.assertEqual(self.snap(), before)
        self.assertEqual((victim.read_bytes(), other.read_bytes()), (b"the user's\n", b"x\n"))
        self.assertTrue(homes.exists())
        # And what it is for: a listed backup goes, with the directories it
        # leaves empty. A project's backups are in the project's state.
        backups = self.project_state / "backups"
        real = self.put(backups / "S1" / "project" / "a" / "b.md", "x\n")
        kept = self.put(backups / "S1" / "project" / "c.md", "x\n")  # no record lists it
        alone = self.put(backups / "S2" / "project" / "d.md", "x\n")
        manifest.backups = [
            {"path": "project:a/b.md", "kind": "file", "backup": f"{PROJECT_BACKUPS_KEY}/S1/project/a/b.md"},
            {"path": "project:d.md", "kind": "file", "backup": f"{PROJECT_BACKUPS_KEY}/S2/project/d.md"},
        ]
        fileops._remove_backups_of(self.roots, manifest)
        self.assertFalse(real.exists())
        self.assertFalse((backups / "S1" / "project" / "a").exists())
        self.assertFalse(alone.exists())
        self.assertFalse((backups / "S2").exists())
        self.assertTrue(kept.exists())
        self.assertTrue(homes.exists())


class VerifyTests(GuardCase):
    """Each path is looked at again immediately before it is changed."""

    def during(self, when, do):
        """Call ``do`` once, right before the first change ``when`` accepts."""
        real, done = fileops.Plan._perform, []

        def perform(plan, step):
            if not done and when(step):
                done.append(step)
                do()
            return real(plan, step)

        return mock.patch.object(fileops.Plan, "_perform", perform)

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_a_link_the_user_repointed_under_the_run_is_left(self) -> None:
        (self.clone / "one").mkdir()
        (self.clone / "two").mkdir()
        mine = self.root / "mine"
        mine.mkdir()
        link = self.home / ".claude" / "skills" / "s"
        plan = self.plan()
        plan.create_link(link, self.clone / "one")
        plan.apply()

        def repoint() -> None:
            fsio.remove_link(link)
            fsio.make_link(str(mine), link, True)

        plan = self.plan()
        plan.create_link(link, self.clone / "two")
        with self.during(lambda step: step.path == link, repoint):
            with self.assertRaises(SetupError) as caught:
                plan.apply()
        self.assertIn("changed while setup was running; it was left as it is", caught.exception.lines[0])
        self.assertTrue(fsio.same_target(fsio.read_link(link), str(mine)))

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_a_directory_that_turns_into_a_link_under_the_run_is_not_written_through(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "users-file.txt").write_bytes(b"outside every root\n")
        agents = self.home / ".claude" / "agents"
        agents.mkdir(parents=True)
        other = self.home / ".claude" / "other.md"

        def swap() -> None:
            agents.rmdir()
            fsio.make_link(str(outside), agents, True)

        plan = self.plan()
        plan.write_file(other, "first\n")
        for name in ("coder.md", "manager.md"):
            plan.write_file(agents / name, "generated\n")
        with self.during(lambda step: step.path.parent == agents, swap):
            with self.assertRaises(SetupError) as caught:
                plan.apply()
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn("became a link while setup was running; nothing is written through it", caught.exception.lines[0])
        self.assertIn("1 of 3 changes were made and are recorded", caught.exception.lines[0])
        self.assertEqual(sorted(os.listdir(outside)), ["users-file.txt"])
        self.assertEqual(other.read_bytes(), b"first\n")
        self.assertIsNone(self.record().get("home:.claude/agents/coder.md"))
        # The link leads out of the home: nothing is written there with
        # the option either.
        before = self.snap()
        plan = self.plan(follow_config_symlinks=True)
        plan.write_file(agents / "coder.md", "generated\n")
        self.assertEqual({problem.code for problem in plan.check()}, {fileops.OUTSIDE})
        with self.assertRaises(fileops.PlanError) as refused:
            plan.apply()
        self.assertIn("is outside the directories this run may write to", refused.exception.lines[0])
        self.assertEqual(self.snap(), before)
        self.assertEqual(sorted(os.listdir(outside)), ["users-file.txt"])
        self.assertEqual((outside / "users-file.txt").read_bytes(), b"outside every root\n")
        # With the option, a link to a place inside the home is what the
        # user asked setup to follow.
        inside = self.home / "dotfiles" / "agents"
        inside.mkdir(parents=True)
        fsio.remove_link(agents)
        fsio.make_link(str(inside), agents, True)
        plan = self.plan(follow_config_symlinks=True)
        plan.write_file(agents / "coder.md", "generated\n")
        plan.apply()
        self.assertEqual((inside / "coder.md").read_bytes(), b"generated\n")
        self.assertEqual(sorted(os.listdir(outside)), ["users-file.txt"])

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_a_directory_that_turns_into_a_link_out_of_the_home_with_the_option_that_follows(self) -> None:
        """With the option that follows links the check for a new link is
        off: what is left is the question ``fsio`` asks of every change,
        and it refuses the place outside the home."""
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "users-file.txt").write_bytes(b"outside every root\n")
        agents = self.home / ".claude" / "agents"
        agents.mkdir(parents=True)
        other = self.home / ".claude" / "other.md"

        def swap() -> None:
            agents.rmdir()
            fsio.make_link(str(outside), agents, True)

        plan = self.plan(follow_config_symlinks=True)
        plan.write_file(other, "first\n")
        for name in ("coder.md", "manager.md"):
            plan.write_file(agents / name, "generated\n")
        with self.during(lambda step: step.path.parent == agents, swap):
            with self.assertRaises(SetupError) as caught:
                plan.apply()
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn("is outside the directories this run may write to", caught.exception.lines[0])
        self.assertIn("1 of 3 changes were made and are recorded", caught.exception.lines[0])
        self.assertEqual(sorted(os.listdir(outside)), ["users-file.txt"])
        self.assertEqual((outside / "users-file.txt").read_bytes(), b"outside every root\n")
        self.assertEqual(other.read_bytes(), b"first\n")
        self.assertIsNone(self.record().get("home:.claude/agents/coder.md"))
        self.assertNotIn(b'"pending"', self.manifest_file.read_bytes())

    def test_a_file_changed_under_the_run_is_left(self) -> None:
        one = self.put(self.home / "a.md", "a\n")
        two = self.put(self.home / "b.md", "b\n")
        plan = self.plan()
        plan.edit_block(one, "x\n")
        plan.edit_block(two, "x\n")
        with self.during(lambda step: step.path == two, lambda: two.write_bytes(b"changed under setup's feet\n")):
            with self.assertRaises(SetupError) as caught:
                plan.apply()
        self.assertIn("changed while setup was running", caught.exception.lines[0])
        self.assertEqual(two.read_bytes(), b"changed under setup's feet\n")


class CloneTests(GuardCase):
    """Nothing is written, removed or linked where the real place is
    inside the clone, whatever the options (B6)."""

    def setUp(self) -> None:
        super().setUp()
        for name in ("csv-tools", "json-tools"):
            self.put(self.clone / name / "SKILL.md", f"the clone's own {name}\n")
            self.put(self.clone / name / "scripts" / "run.py", "print(1)\n")
        self.skills = self.home / ".claude" / "skills"

    def says_the_clone(self, line: str) -> None:
        """``line`` is the refusal of a real place inside the clone of this
        run, which ``fsio`` names by its path."""
        self.assertRegex(line, r"its real place, .+, is inside .+, which setup never writes to")
        self.assertIn(f"{self.clone.name}, which setup never writes to", line)

    def actions(self, inside: Path) -> dict:
        """Every kind of change, at a path whose real place is the clone."""
        return {
            "remove a file": lambda plan: plan.remove_file(inside / "csv-tools" / "SKILL.md"),
            "write a file": lambda plan: plan.write_file(inside / "new.md", "x\n"),
            "replace a file": lambda plan: plan.write_file(inside / "csv-tools" / "SKILL.md", "x\n", replace=fileops.ANY),
            "edit a block": lambda plan: plan.edit_block(inside / "csv-tools" / "SKILL.md", "x\n"),
            "make a directory": lambda plan: plan.create_directory(inside / "made"),
            "make a link": lambda plan: plan.create_link(inside / "linked", self.clone / "json-tools"),
            "remove the users directory": lambda plan: (
                plan.remove_file(inside / "csv-tools" / "SKILL.md"),
                plan.remove_file(inside / "csv-tools" / "scripts" / "run.py"),
                plan.remove_directory(inside / "csv-tools" / "scripts", users=True),
                plan.remove_directory(inside / "csv-tools", users=True),
                plan.create_link(inside / "csv-tools", self.clone / "csv-tools"),
            ),
        }

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_a_skills_directory_that_is_a_link_to_the_clone(self) -> None:
        self.link(self.clone, self.skills)
        before = self.snap()
        for name, action in self.actions(self.skills).items():
            for follow in (True, False):
                with self.subTest(name, follow=follow):
                    plan = self.plan(follow_config_symlinks=follow)
                    action(plan)
                    problems = plan.check()
                    self.assertTrue(problems, "the plan was not refused")
                    if follow:
                        self.assertEqual({problem.code for problem in problems}, {fileops.OUTSIDE})
                        for item in problems:
                            self.says_the_clone(item.message)
                    with self.assertRaises(fileops.PlanError):
                        plan.apply()
                    with self.assertRaises(fileops.PlanError):
                        plan.describe()
                    self.assertEqual(self.snap(), before)

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_a_link_deeper_down_that_leads_into_the_clone(self) -> None:
        self.link(self.clone / "csv-tools", self.skills / "mine")
        before = self.snap()
        for change in (
            lambda plan: plan.write_file(self.skills / "mine" / "new.md", "x\n"),
            lambda plan: plan.remove_file(self.skills / "mine" / "SKILL.md"),
            lambda plan: plan.remove_file(self.skills / "mine" / "scripts" / "run.py"),
        ):
            plan = self.plan(follow_config_symlinks=True)
            change(plan)
            self.assertEqual({problem.code for problem in plan.check()}, {fileops.OUTSIDE})
            with self.assertRaises(fileops.PlanError):
                plan.apply()
        self.assertEqual(self.snap(), before)

    @unittest.skipUnless(SYMLINKS, "needs a link to a file")
    def test_a_file_that_is_a_link_into_the_clone(self) -> None:
        link = self.home / ".claude" / "CLAUDE.md"
        link.parent.mkdir(parents=True)
        os.symlink(self.clone / "csv-tools" / "SKILL.md", link)
        before = self.snap()
        plan = self.plan(follow_config_symlinks=True)
        plan.edit_block(link, "x\n")
        problems = plan.check()
        self.assertEqual([problem.code for problem in problems], [fileops.OUTSIDE])
        self.says_the_clone(problems[0].message)
        with self.assertRaises(fileops.PlanError):
            plan.apply()
        self.assertEqual(self.snap(), before)

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_it_is_asked_again_immediately_before_each_change(self) -> None:
        """The directory becomes a link into the clone after validation:
        with the option that follows links, only this check is left."""
        self.skills.mkdir(parents=True)
        made = self.put(self.skills / "csv-tools" / "SKILL.md", "the user's copy\n")
        aside = self.root / "aside"

        def swap() -> None:
            os.rename(self.skills, aside)
            fsio.make_link(str(self.clone), self.skills, True)

        plan = self.plan(follow_config_symlinks=True)
        plan.write_file(self.home / "first.md", "x\n")
        plan.remove_file(made)
        real, done = fileops.Plan._perform, []
        clone = snapshot(self.clone)

        def perform(plan_, step):
            if not done and step.path == made:
                done.append(step)
                swap()
            return real(plan_, step)

        with mock.patch.object(fileops.Plan, "_perform", perform):
            with self.assertRaises(SetupError) as caught:
                plan.apply()
        self.says_the_clone(caught.exception.lines[0])
        self.assertIn("1 of 2 changes were made and are recorded", caught.exception.lines[0])
        self.assertEqual(snapshot(self.clone), clone)
        self.assertEqual((self.clone / "csv-tools" / "SKILL.md").read_bytes(), b"the clone's own csv-tools\n")
        self.assertEqual((aside / "csv-tools" / "SKILL.md").read_bytes(), b"the user's copy\n")

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_the_state_is_not_kept_in_the_clone_either(self) -> None:
        (self.clone / "state" / "workflow-setup").mkdir(parents=True)  # there already: no step makes it
        self.link(self.clone / "state", self.home / ".agents")
        before = self.snap()
        plan = self.plan(follow_config_symlinks=True)
        plan.write_file(self.home / "x.md", "x\n")
        self.assertIn(fileops.OUTSIDE, {problem.code for problem in plan.check()})
        with self.assertRaises(fileops.PlanError):
            plan.apply()
        self.assertEqual(self.snap(), before)

    def test_a_link_to_the_clone_is_what_setup_makes(self) -> None:
        plan = self.plan()
        plan.create_link(self.skills / "csv-tools", self.clone / "csv-tools")
        self.assertTrue(plan.apply().changed)
        # And taking it away again, or repointing it, is no write to the clone.
        plan = self.plan()
        plan.create_link(self.skills / "csv-tools", self.clone / "json-tools")
        self.assertTrue(plan.apply().changed)
        self.assertEqual(self.undo(), [])
        self.assertEqual((self.clone / "csv-tools" / "SKILL.md").read_bytes(), b"the clone's own csv-tools\n")

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_the_way_back_below_setups_own_link_is_not_taken_for_the_clone(self) -> None:
        """A directory of the user's that setup replaced by its link comes
        back with its files: they are planned below a path that is still
        the link into the clone when the plan is validated."""
        copy = self.skills / "csv-tools"
        self.put(copy / "SKILL.md", "the user's copy\n")
        self.put(copy / "notes" / "deep" / "mine.md", "mine\n")
        start = self.snap()
        plan = self.plan()
        for file in (copy / "SKILL.md", copy / "notes" / "deep" / "mine.md"):
            plan.remove_file(file)
        for directory in (copy / "notes" / "deep", copy / "notes", copy):
            plan.remove_directory(directory, users=True)
        plan.create_link(copy, self.clone / "csv-tools")
        plan.apply()
        self.assertEqual((copy / "SKILL.md").read_bytes(), b"the clone's own csv-tools\n")
        self.assertEqual(self.undo(), [])
        self.assertEqual(self.snap(), start)


class FailedStepTests(GuardCase):
    def test_a_swap_that_fails_half_way_is_recorded_as_it_is_on_disk(self) -> None:
        """The user's directory is taken away, the link cannot be made, and
        the directory cannot be made again either: the record must say that
        setup removed it, or the way back would not make it again."""
        copy = self.home / ".claude" / "skills" / "csv-tools"
        self.put(copy / "SKILL.md", "the user's copy\n")
        (self.clone / "csv-tools").mkdir()
        if POSIX:
            os.chmod(copy, 0o750)
        start = self.snap()
        plan = self.plan()
        plan.remove_file(copy / "SKILL.md")
        plan.remove_directory(copy, users=True)
        plan.create_link(copy, self.clone / "csv-tools")
        refuse = SetupError(f"{copy}: the link cannot be created: no room")
        with mock.patch.object(fileops.Plan, "_put_there", side_effect=refuse):
            with self.assertRaises(SetupError) as caught:
                plan.apply()
        self.assertIn("1 of 2 changes were made and are recorded", caught.exception.lines[0])
        self.assertFalse(copy.exists())
        entry = self.record().get("home:.claude/skills/csv-tools")
        self.assertEqual(entry["kind"], "removed-directory")
        self.assertEqual(self.undo(), [])
        self.assertEqual(self.snap(), start)

    def test_a_file_that_is_not_utf8_is_a_refusal_in_every_action(self) -> None:
        ignore = self.put(self.project / ".gitignore", b"caf\xe9\n")
        plan = self.plan()
        plan.ignore(add=[".claude/x"])
        error = self.refused(plan)
        self.assertEqual(error.codes(), {fileops.NOT_TEXT})
        self.assertEqual(len(error.lines), 1)
        self.assertIn(str(ignore), error.lines[0])
        for read in (blocks.get, blocks.content_of, blocks.outside):
            with self.assertRaises(blocks.Refusal):
                read(b"caf\xe9\n", blocks.GITIGNORE)

    def test_the_backup_of_a_change_that_was_not_made_stays_and_stays_listed(self) -> None:
        """A project's backup of a pending change that the next run finds
        not made: no run removes a backup by itself, so it stays where it
        is, in the project's own state, and the record goes on listing it.
        It goes with the record, when the project is uninstalled."""
        notes = self.put(self.project / "notes.md", "mine\n")
        plan = self.plan()
        plan.write_file(self.project / "made.md", "x\n")
        plan.apply()
        self.assertFalse(self.state.exists())  # a run that writes to a project alone keeps nothing in the home
        key = f"{PROJECT_BACKUPS_KEY}/S5/project/notes.md"
        backup = self.put(self.roots.path(key), "mine\n")
        reference = {"backup": key, "sha256": fsio.sha256(b"mine\n"), "mode": 0o644}
        data = json.loads(self.project_manifest_file.read_bytes())
        data["pending"] = [{
            "path": "project:notes.md", "after": {"kind": "file", "sha256": fsio.sha256(b"never written\n")}, "set": True,
            "entry": {"kind": "text", "sha256": None, "created": False, "original": reference},
            "backup": {"path": "project:notes.md", "kind": "file", **reference, "stamp": "S5"},
        }]
        self.project_manifest_file.write_bytes(json.dumps(data).encode())
        self.assertEqual(backup, self.project_state / "backups" / "S5" / "project" / "notes.md")
        # The pending change names it: it is no backup that nothing lists.
        self.assertEqual(list(fileops.leftovers(self.roots)), [])
        line = "complete the record of an interrupted run: 0 changes were made, 1 were not"
        self.assertEqual(self.plan().describe().lines, [line])
        result = self.plan().apply()
        self.assertEqual(result.lines, [line])
        self.assertEqual(result.notes, [])
        self.assertEqual(backup.read_bytes(), b"mine\n")
        data = json.loads(self.project_manifest_file.read_bytes())
        self.assertNotIn("pending", data)
        self.assertEqual(data["backups"], [{"path": "project:notes.md", "kind": "file", **reference, "stamp": "S5"}])
        self.assertIsNone(self.record().get("project:notes.md"))
        self.assertEqual(fileops.unlisted_backups(self.roots, project=True), [])
        self.assertEqual(list(fileops.leftovers(self.roots)), [])
        self.assertEqual(self.plan().describe().lines, [fileops.UP_TO_DATE])
        self.assertEqual(notes.read_bytes(), b"mine\n")
        self.assertFalse(self.state.exists())
        # The way back and the removal of the state take it along.
        self.assertEqual(self.undo(), [])
        self.assertFalse(backup.exists())
        self.assertEqual(sorted(os.listdir(self.project)), ["notes.md"])
        self.assertEqual(notes.read_bytes(), b"mine\n")


class StateTests(GuardCase):
    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_state_under_a_link_is_not_removed_through_it(self) -> None:
        elsewhere = self.home / "dotfiles" / "agents"
        elsewhere.mkdir(parents=True)
        self.link(elsewhere, self.home / ".agents")
        plan = self.plan(follow_config_symlinks=True)
        plan.create_directory(self.home / "d")
        plan.apply()
        self.assertEqual(self.reversal(follow_config_symlinks=True).apply().kept, [])
        before = self.snap()
        with self.assertRaises(SetupError) as caught:
            fileops.remove_state(self.roots)
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn("does not write through a link unless --follow-config-symlinks is given", caught.exception.lines[0])
        self.assertEqual(self.snap(), before)
        self.assertTrue((elsewhere / "workflow-setup" / "manifest.json").is_file())
        self.assertTrue(fileops.remove_state(self.roots, follow_config_symlinks=True))
        self.assertEqual(os.listdir(elsewhere), [])

    @unittest.skipUnless(SYMLINKS or os.name == "nt", "needs a link")
    def test_state_under_a_link_that_leads_out_of_the_home_is_never_touched(self) -> None:
        """``.agents`` is a link to a directory beside the home that holds
        what looks like setup's state: no run writes, removes or locks
        anything there, with the option that follows links or without."""
        elsewhere = self.root / "elsewhere"
        record = {"schema_version": 1, "entries": {"home:.agents/workflow-setup": {"kind": "directory"}}, "backups": []}
        self.put(elsewhere / "workflow-setup" / "manifest.json", json.dumps(record))
        self.put(elsewhere / "workflow-setup" / "backups" / "S1" / "home" / "x.md", "a backup no record lists\n")
        self.link(elsewhere, self.home / ".agents")
        before = self.snap()

        def write(follow: bool) -> None:
            plan = self.plan(follow_config_symlinks=follow)
            plan.create_directory(self.home / "d")
            plan.apply()

        for follow in (False, True):
            for name, run in (
                ("a plan", write),
                ("remove_state", lambda follow: fileops.remove_state(self.roots, follow_config_symlinks=follow)),
                ("discard_backups", lambda follow: fileops.discard_backups(self.roots, follow_config_symlinks=follow)),
            ):
                with self.subTest(name, follow=follow):
                    with self.assertRaises(SetupError) as caught:
                        run(follow)
                    for line in caught.exception.lines:
                        self.assertIn(
                            "is outside the directories this run may write to" if follow
                            else "does not write through a link unless --follow-config-symlinks is given",
                            line,
                        )
                    self.assertEqual(self.snap(), before)
        plan = self.plan(follow_config_symlinks=True)
        plan.create_directory(self.home / "d")
        self.assertEqual({problem.code for problem in plan.check()}, {fileops.OUTSIDE})
        self.assertFalse((self.home / "d").exists())

    def interrupted(self) -> str:
        """A run that was killed after its last change and before its
        records were closed. Returns the token of its temporary names,
        which both records hold with its pending changes."""
        real, saved = Manifest.save, set()

        class Killed(BaseException):
            """Stands in for the process being killed: nothing catches it."""

        def save(manifest: Manifest) -> None:
            if manifest.file in saved:
                raise Killed()
            saved.add(manifest.file)
            real(manifest)

        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "manager.md", "generated\n")
        plan.edit_block(self.project / "notes.md", "y\n")
        with mock.patch.object(Manifest, "save", autospec=True, side_effect=save):
            with self.assertRaises(Killed):
                plan.apply()
        tokens = set()
        for file in (self.manifest_file, self.project_manifest_file):
            data = json.loads(file.read_bytes())
            self.assertTrue(data["pending"])
            tokens.add(data["run"]["token"])
        self.assertEqual(len(tokens), 1)
        return tokens.pop()

    def test_what_an_interrupted_run_left_is_named_and_only_what_it_recorded_is_removed(self) -> None:
        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated\n")
        plan.edit_block(self.put(self.project / "notes.md", "mine\n"), "x\n")
        plan.apply()
        token = self.interrupted()
        file_name, directory_name = fsio.temporary_names(token)
        self.assertEqual((file_name, directory_name), (f".wfsetup-{token}.tmp", f".wfsetup-{token[:4]}.tmp"))
        stamp = "20260101T000001000000Z"
        other = "0123abcd" if token != "0123abcd" else "0123abce"
        # Under the names the record gives, where the record says the run worked.
        recorded = [
            self.put(self.home / ".claude" / "agents" / file_name, "half\n"),
            self.put(self.project / file_name, "half\n"),
        ]
        (self.home / ".claude" / "agents" / directory_name).mkdir()
        recorded.append(self.home / ".claude" / "agents" / directory_name)
        # Backups that no record lists: nothing of setup's answers for them.
        unlisted = [
            self.put(self.state / "backups" / "S9" / "home" / ".claude" / "x.md", "of a change that was not made\n"),
            self.put(self.state / "backups" / stamp / "home" / "other.md", "of a change that was not made\n"),
            self.put(self.project_state / "backups" / "S9" / "project" / "other.md", "of a change that was not made\n"),
        ]
        # Named like a temporary of setup's beside a path of the record, and not recorded.
        lookalikes = [
            self.put(self.home / ".claude" / "agents" / f".wfsetup-{other}.tmp", "the user's\n"),
            self.put(self.project / f".wfsetup-{other}.tmp", "the user's\n"),
        ]
        (self.home / f".wfsetup-{other}.tmp").mkdir()
        self.put(self.home / f".wfsetup-{other}.tmp" / "the-users.md", "a directory with something in it\n")
        lookalikes.append(self.home / f".wfsetup-{other}.tmp")
        # What is not setup's, though it looks a little like it.
        stays = [
            self.put(self.home / ".claude" / "agents" / ".wfsetup-notes.tmp", "the user's\n"),
            self.put(self.home / "unrelated" / file_name, "beside no path of the record\n"),
            self.put(self.home / "unrelated" / f".wfsetup-{other}.tmp", "beside no path of the record\n"),
        ]
        found = fileops.leftovers(self.roots)
        self.assertEqual(sorted(found.temporaries), sorted(recorded))
        self.assertEqual(sorted(found.unlisted), sorted(unlisted))
        self.assertEqual(sorted(found.lookalikes), sorted(lookalikes))
        self.assertEqual(found.lock, [])
        self.assertEqual(sorted(found), sorted([*recorded, *unlisted, *lookalikes]))
        self.assertEqual(fileops.unlisted_backups(self.roots), sorted(unlisted[:2]))
        self.assertEqual(fileops.unlisted_backups(self.roots, project=True), unlisted[2:])
        with_them = self.snap()
        lines = [
            "complete the record of an interrupted run: 2 changes were made, 0 were not",
            "complete the cleanup of an interrupted run: remove 3 temporary files it recorded",
        ]
        dry = self.plan().describe()
        self.assertEqual(dry.lines, lines)
        self.assertEqual(self.snap(), with_them)
        result = self.plan().apply()
        self.assertEqual(result.lines, lines)
        # The backups no record lists are named, each place in one line, and left.
        for where, count, option in (
            (self.state / "backups", "2 backups", "`uninstall --discard-backups`"),
            (self.project_state / "backups", "1 backup", "`uninstall --discard-backups --project DIR`"),
        ):
            mine = [note for note in result.notes if f"under {where} that no record lists" in note]
            self.assertEqual(len(mine), 1, result.notes)
            self.assertTrue(mine[0].startswith(count + " under "), mine[0])
            self.assertIn(option, mine[0])
        self.assertEqual(dry.notes, result.notes)
        after = self.snap()
        gone = sorted(name for name in with_them if name not in after)
        self.assertEqual(gone, sorted(path.relative_to(self.root).as_posix() for path in recorded))
        changed = sorted(name for name in after if after[name] != with_them.get(name))
        self.assertEqual(changed, ["home/.agents/workflow-setup/manifest.json", "project/.agents/workflow-setup/manifest.json"])
        for path, data in ((path, b"of a change that was not made\n") for path in unlisted):
            self.assertEqual(path.read_bytes(), data, path)
        for path in [*lookalikes[:2], *stays]:
            self.assertTrue(path.is_file(), path)
        self.assertEqual((lookalikes[2] / "the-users.md").read_bytes(), b"a directory with something in it\n")
        found = fileops.leftovers(self.roots)
        self.assertEqual(found.temporaries, [])
        self.assertEqual(sorted(found.unlisted), sorted(unlisted))
        self.assertEqual(sorted(found.lookalikes), sorted(lookalikes))
        for file in (self.manifest_file, self.project_manifest_file):
            data = json.loads(file.read_bytes())
            self.assertNotIn("pending", data)
            self.assertNotIn("run", data)
        # A run after that has nothing to do, and still names the backups.
        again = self.plan().apply()
        self.assertEqual(again.lines, [fileops.UP_TO_DATE])
        self.assertEqual(self.snap(), after)
        # They go when the user asks for exactly that, and nothing else does.
        self.assertEqual(sorted(fileops.discard_backups(self.roots)), sorted(unlisted[:2]))
        self.assertEqual(fileops.discard_backups(self.roots, project=True), unlisted[2:])
        end = self.snap()
        for path in [*lookalikes[:2], *stays]:
            self.assertTrue(path.is_file(), path)
        listed = [item["backup"] for file in (self.manifest_file, self.project_manifest_file)
                  for item in json.loads(file.read_bytes())["backups"]]
        self.assertTrue(listed)
        for key in listed:
            self.assertTrue(self.roots.path(key).is_file(), key)
        self.assertEqual(sorted(name for name in after if name not in end and after[name][0] == "file"),
                         sorted(path.relative_to(self.root).as_posix() for path in unlisted))

    def installed_and_interrupted(self) -> str:
        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated\n")
        plan.edit_block(self.put(self.project / "notes.md", "mine\n"), "x\n")
        plan.apply()
        return fsio.temporary_names(self.interrupted())[0]

    def test_a_recorded_temporary_in_the_state_or_among_the_backups_goes_too(self) -> None:
        name = self.installed_and_interrupted()
        stamp = "20260101T000001000000Z"
        recorded = [
            self.put(self.state / name, "half a record\n"),
            self.put(self.project_state / name, "half a record\n"),
            self.put(self.state / "backups" / stamp / "home" / name, "half a backup\n"),
            self.put(self.project_state / "backups" / stamp / "project" / name, "half a backup\n"),
        ]
        # Among the backups they are the plan's to remove; in the state
        # directory itself they are pieces of a record, which the run that
        # takes the lock removes (``lock``).
        found = fileops.leftovers(self.roots)
        self.assertEqual(sorted(found.temporaries), sorted(recorded[2:]))
        self.assertEqual(sorted(found.lock), sorted(recorded[:2]))
        self.assertEqual(len(list(found)), 4)   # each named once
        with_them = self.snap()
        self.assertIn("complete the cleanup of an interrupted run: remove 2 temporary files it recorded", self.plan().describe().lines)
        self.assertEqual(self.snap(), with_them)
        self.plan().apply()
        after = self.snap()
        self.assertEqual(sorted(name for name in with_them if name not in after),
                         sorted(path.relative_to(self.root).as_posix() for path in recorded))
        self.assertEqual(list(fileops.leftovers(self.roots)), [])

    def test_a_recorded_temporary_among_the_backups_is_not_called_a_backup_that_was_left(self) -> None:
        """The run removes it as the temporary it is; a line that says a
        backup "was left as it is" and how to discard it would send the
        user after a file that is no longer there."""
        name = self.installed_and_interrupted()
        left = self.put(self.state / "backups" / "20260101T000001000000Z" / "home" / name, "half a backup\n")
        found = fileops.leftovers(self.roots)
        self.assertEqual(found.temporaries, [left])
        self.assertEqual(found.unlisted, [])
        self.assertEqual(fileops.unlisted_backups(self.roots), [])
        for result in (self.plan().describe(), self.plan().apply()):
            self.assertEqual([note for note in result.notes if "that no record lists" in note], [])
        self.assertFalse(left.exists())

    def test_the_dry_run_counts_the_recorded_temporaries_as_the_real_run_does(self) -> None:
        name = self.installed_and_interrupted()
        self.put(self.state / name, "half a record\n")
        self.put(self.home / ".claude" / "agents" / name, "half\n")
        dry = self.plan().describe().lines
        self.assertIn("complete the cleanup of an interrupted run: remove 1 temporary files it recorded", dry)
        self.assertEqual(self.plan().apply().lines, dry)
        self.assertFalse((self.state / name).exists())   # the lock's to remove, and removed
        self.assertFalse((self.home / ".claude" / "agents" / name).exists())

    def test_a_file_named_like_a_temporary_is_never_removed_where_no_run_was_interrupted(self) -> None:
        """The same names with no interrupted run in the record: they are
        the user's as far as setup can tell."""
        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated\n")
        plan.apply()
        theirs = [
            self.put(self.home / ".claude" / "agents" / ".wfsetup-0123abcd.tmp", "the user's\n"),
            self.put(self.home / ".wfsetup-89abcdef.tmp", "the user's\n"),
            self.put(self.state / "backups" / "S9" / "home" / ".wfsetup-00000000.tmp", "the user's\n"),
        ]
        (self.home / ".wfsetup-1111.tmp").mkdir()
        before = self.snap()
        self.assertEqual(fileops.leftovers(self.roots).temporaries, [])
        self.assertEqual(self.plan().describe().lines, [fileops.UP_TO_DATE])
        self.assertFalse(self.plan().apply().changed)
        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "manager.md", "generated\n")
        plan.apply()
        self.assertEqual(self.reversal().apply().kept, [("home:.claude/agents", mock.ANY), ("home:.claude", mock.ANY)])
        for path in theirs:
            self.assertEqual(path.read_bytes(), b"the user's\n", path)
        self.assertTrue((self.home / ".wfsetup-1111.tmp").is_dir())
        self.assertEqual({name: value for name, value in self.snap().items() if name in before and "manifest" not in name
                          and value[0] == "file"},
                         {name: value for name, value in before.items() if "manifest" not in name and value[0] == "file"
                          and not name.endswith("coder.md")})

    def test_the_entries_the_ignore_block_always_holds_cover_them(self) -> None:
        self.assertIn(fsio.TEMP_PATTERN, fileops.IGNORE_ALWAYS)
        self.assertEqual(fsio.TEMP_PATTERN, ".wfsetup-*.tmp")
        self.assertTrue(Path(fsio._temporary_name(self.home)).name.startswith(".wfsetup-"))
        self.assertTrue(fsio.is_temporary(Path(fsio._temporary_name(self.home)).name))


class UsersFileTests(GuardCase):
    @unittest.skipUnless(POSIX, "permission bits")
    def test_a_read_only_file_is_edited_with_a_word_about_it(self) -> None:
        file = self.put(self.home / ".codex" / "AGENTS.md", "mine\n", 0o444)
        gone = self.put(self.home / ".claude" / "rules" / "old.md", "v1\n", 0o400)
        plain = self.put(self.home / ".claude" / "CLAUDE.md", "mine\n", 0o644)
        plan = self.plan()
        for path in (file, plain):
            plan.edit_block(path, "x\n")
        plan.remove_file(gone)
        dry = plan.describe()
        self.assertEqual(dry.notes, [
            "home:.codex/AGENTS.md: is read-only (mode 0444); setup changes it all the same, as its owner may, and it "
            "keeps that mode",
            "home:.claude/rules/old.md: is read-only (mode 0400); setup removes it all the same, as its owner may",
        ])
        self.assertEqual(plan.apply().notes, dry.notes)
        self.assertEqual(stat.S_IMODE(os.lstat(file).st_mode), 0o444)

    def test_a_users_file_with_a_second_name_is_neither_copied_nor_changed(self) -> None:
        secret = self.put(self.root / "elsewhere" / "auth.json", '{"token": "SECRET"}\n')
        rule = self.home / ".claude" / "rules" / "prd-implementation.md"
        rule.parent.mkdir(parents=True)
        try:
            os.link(secret, rule)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("this file system has no hard links")
        for change in (
            lambda plan: plan.remove_file(rule),
            lambda plan: plan.edit_block(rule, "x\n"),
            lambda plan: plan.write_file(rule, "x\n", replace=fileops.ANY),
        ):
            plan = self.plan()
            change(plan)
            error = self.refused(plan)
            self.assertEqual(error.codes(), {fileops.HARD_LINK})
            self.assertEqual(len(error.lines), 1)
            self.assertIn("has 2 names (hard links)", error.lines[0])
        self.assertFalse(self.state.exists())
        self.assertEqual(secret.read_bytes(), b'{"token": "SECRET"}\n')
        self.assertNotIn(b"SECRET", b"".join(value[1] for name, value in self.snap().items()
                                              if value[0] == "file" and "elsewhere" not in name and "rules" not in name))
        # A file setup wrote whole, and finds as it left it, may have one.
        made = self.home / ".claude" / "agents" / "coder.md"
        plan = self.plan()
        plan.write_file(made, "generated\n")
        plan.apply()
        os.link(made, self.root / "elsewhere" / "second-name.md")
        plan = self.plan()
        plan.write_file(made, "generated again\n")
        self.assertTrue(plan.apply().changed)


class JsonTests(unittest.TestCase):
    def test_an_edit_that_changes_more_than_was_asked_is_refused(self) -> None:
        """The check after every edit of a settings file: the new text must
        parse to exactly the old data with the asked change."""
        self.assertEqual(jsonkeys.checked('{"a": 1, "b": 2}', {"a": 1, "b": 2}), b'{"a": 1, "b": 2}')
        for text, expected in (
            ('{"a": 1, "b": 2}', {"a": 1}),                 # a key more than expected
            ('{"a": 1}', {"a": 1, "b": 2}),                 # a key fewer
            ('{"a": 1, "b": 3}', {"a": 1, "b": 2}),         # another value
            ('{"b": 2, "a": 1}', {"a": 1, "b": 2}),         # another order
            ('{"a": true}', {"a": 1}),                      # true is not 1
        ):
            with self.assertRaises(jsonkeys.Refusal) as caught:
                jsonkeys.checked(text, expected)
            self.assertIn("would change more than the keys asked for", str(caught.exception))
        with self.assertRaises(jsonkeys.Refusal):
            jsonkeys.checked('{"a": 1', {"a": 1})

    def test_an_object_that_holds_only_white_space_keeps_it(self) -> None:
        for text in ("{\n}", "{\n}\n", "{ }", "{\r\n}\r\n", "{\n\n  }", "\ufeff{\n\t}", "{}", "{}\n", "{   \n }"):
            with self.subTest(text=text):
                with_key = jsonkeys.set_key(text, "agent", "manager")
                self.assertEqual(jsonkeys.parse(with_key.encode("utf-8"))[1], {"agent": "manager"})
                inner = text[text.index("{") + 1:text.index("}")]
                self.assertIn(inner, with_key)
                self.assertEqual(jsonkeys.remove_key(with_key, "agent"), text)
                # A table as the value is laid out on lines of its own and still goes.
                table = jsonkeys.set_key(text, "agent", {"k": [1, 2]})
                self.assertEqual(jsonkeys.parse(table.encode("utf-8"))[1], {"agent": {"k": [1, 2]}})
                self.assertEqual(jsonkeys.remove_key(table, "agent"), text)
        self.assertEqual(jsonkeys.set_key("{}", "agent", "m"), '{\n  "agent": "m"\n}')
        self.assertEqual(jsonkeys.set_key("{\n}", "agent", "m"), '{\n  "agent": "m"}')


class JsonFileTests(GuardCase):
    def test_the_same_through_a_plan_when_the_user_edits_in_between(self) -> None:
        settings = self.put(self.project / ".claude" / "settings.json", "{\n}\n")
        plan = self.plan()
        plan.edit_json(settings, set={"agent": "manager"})
        plan.apply()
        settings.write_bytes(settings.read_bytes() + b"\n")  # the user's change: the backup no longer applies
        self.assertEqual(self.undo(), [])
        self.assertEqual(settings.read_bytes(), b"{\n}\n\n")


class TimeoutTests(unittest.TestCase):
    def test_the_child_that_makes_a_junction_is_not_waited_for_for_ever(self) -> None:
        seen: dict = {}

        def run(argv, **options):
            seen.update(options)
            raise subprocess.TimeoutExpired(argv, options["timeout"])

        with mock.patch.dict(os.environ, {"SystemRoot": "C:\\Windows"}), \
                mock.patch.object(os.path, "isfile", return_value=True), \
                mock.patch.object(subprocess, "run", side_effect=run):
            with self.assertRaises(OSError) as caught:
                fsio._mklink("C:\\target", Path("C:\\link"))
        self.assertEqual(seen["timeout"], fsio.MKLINK_TIMEOUT)
        self.assertLessEqual(fsio.MKLINK_TIMEOUT, 60)
        self.assertIn("did not end within", str(caught.exception))


class InterruptTests(support.ScratchCase):
    """An interrupt ends every command with one line and 130 (B4)."""

    def interrupted(self, *argv: str, error: BaseException) -> tuple[int, str, str]:
        with mock.patch.object(fileops.Plan, "prepare", side_effect=error), \
                mock.patch.object(fileops, "read_record", side_effect=error):
            return support.run(*argv)

    def test_every_command_says_so_in_one_line(self) -> None:
        home = ["--home", str(self.home)]
        seen = 0
        for argv in (["uninstall", *home], ["uninstall", "--dry-run", *home], ["render", *home], ["render", "--dry-run", *home],
                     ["init", "--yes", *home], ["doctor", *home], ["homes", *home], ["show", *home], ["validate"]):
            with self.subTest(command=argv[0]):
                module = cli.commands.load(argv[0])
                with mock.patch.object(module, "run", side_effect=KeyboardInterrupt()):
                    code, out, err = support.run(*argv)
                self.assertEqual(code, EXIT_INTERRUPT, (out, err))
                self.assertEqual(code, 130)
                self.assertEqual(len(err.splitlines()), 1, err)
                self.assertTrue(err.startswith("error: interrupted: the run was stopped before it ended."), err)
                self.assertNotIn("Traceback", err)
                seen += 1
        self.assertEqual(seen, 9)

    def test_an_interrupt_inside_a_run_that_writes(self) -> None:
        code, out, err = self.interrupted("uninstall", "--home", str(self.home), error=KeyboardInterrupt())
        self.assertEqual((code, len(err.splitlines())), (EXIT_INTERRUPT, 1), err)

    def test_a_signal_that_asks_the_process_to_end_is_an_interrupt_with_its_own_code(self) -> None:
        self.assertTrue(issubclass(cli.Signalled, KeyboardInterrupt))
        module = cli.commands.load("uninstall")
        with mock.patch.object(module, "run", side_effect=cli.Signalled(int(signal.SIGTERM))):
            code, out, err = support.run("uninstall", "--home", str(self.home))
        self.assertEqual(code, 128 + int(signal.SIGTERM))
        self.assertEqual(len(err.splitlines()), 1)
        self.assertIn("interrupted by SIGTERM", err)

    def test_a_real_process_takes_the_signal_and_gives_the_lock_back(self) -> None:
        """A process that is told to end while it holds the lock: one line,
        128 plus the signal, no traceback, and no lock left."""
        script = self.root / "child.py"
        script.write_text(textwrap.dedent(f"""
            import signal, sys
            sys.dont_write_bytecode = True
            sys.path.insert(0, {str(support.SETUP)!r})
            from pathlib import Path
            from wfsetup import cli, fileops, lock
            from wfsetup.manifest import Roots

            def run(args):
                roots = Roots(Path({str(self.home)!r}))
                with lock.held(roots):
                    assert (roots.state_dir / "lock").is_file()
                    signal.raise_signal(signal.SIGTERM)
                    for _ in range(10 ** 8):
                        pass
                return 0

            module = cli.commands.load("uninstall")
            module.run = run
            sys.argv = ["workflow_setup.py", "uninstall", "--home", {str(self.home)!r}]
            sys.exit(cli.run_from_command_line())
        """), encoding="utf-8")
        done = subprocess.run([sys.executable, "-B", str(script)], stdin=subprocess.DEVNULL, capture_output=True,
                              env=support.child_environment(), timeout=120)
        err = done.stderr.decode("utf-8", "replace")
        self.assertEqual(done.returncode, 128 + int(signal.SIGTERM), err)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("error: interrupted by SIGTERM: the run was stopped before it ended.", err)
        self.assertFalse((self.home / ".agents").exists(), "the lock, or the directory made for it, was left")

    def test_the_exit_codes_are_the_documented_ones(self) -> None:
        self.assertEqual((EXIT_ERROR, EXIT_INTERRUPT), (2, 130))
        text = " ".join((cli.__doc__ or "").split())
        for words in ("``EXIT_INTERRUPT`` (130)", "never a traceback", "128 plus the signal's number"):
            self.assertIn(words, text)


if __name__ == "__main__":
    unittest.main()
