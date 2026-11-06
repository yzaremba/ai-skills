"""Tests for the file operations: plan, dry run, apply, the record, undo.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

# The tests directory is on sys.path however this file is run (by path, by dotted name, discover, run.py).
import sys as _sys
from pathlib import Path as _Path
_sys.path[:0] = {str(_Path(__file__).resolve().parent)} - set(_sys.path)

import errno
import json
import os
import stat
import unittest
from pathlib import Path
from unittest import mock

from fileops_support import POSIX, SYMLINKS, OpsCase
from wfsetup import fileops, fsio, manifest
from wfsetup.errors import SetupError
from wfsetup.manifest import Manifest, Roots


LINKS = SYMLINKS or os.name == "nt"


class Crash(BaseException):
    """Stands in for the process being killed: nothing catches it."""


class FullPlanCase(OpsCase):
    """A home and a project that hold user files, and a plan that uses
    every kind of action on them."""

    CLAUDE_MD = b"# Mine\r\n@rules/prd-implementation.md\r\n@rules/epic-implementation.md\r\nkeep this\r\n"
    AGENTS_MD = b"<!-- other-tool:start -->\nnot setup's\n<!-- other-tool:end -->\nno final newline"
    CONFIG_TOML = b'model = "x"\n\n[agents]\nmax_threads = 2\n'
    SETTINGS = b'{\n    "permissions": {"allow": ["a", "b"]},\n    "theme": "dark"\n}'
    IGNORE = b"node_modules\n"
    WORKFLOW = b'schema_version = 1\n# by hand\n'

    def setUp(self) -> None:
        super().setUp()
        (self.clone / "json-tools").mkdir()
        (self.clone / "old-skill").mkdir()
        self.claude_md = self.put(self.home / ".claude" / "CLAUDE.md", self.CLAUDE_MD)
        self.agents_md = self.put(self.home / ".codex" / "AGENTS.md", self.AGENTS_MD)
        self.config = self.put(self.home / ".codex" / "config.toml", self.CONFIG_TOML, 0o600 if POSIX else None)
        self.settings = self.put(self.project / ".claude" / "settings.json", self.SETTINGS)
        self.ignore = self.put(self.exclude_file, self.IGNORE)
        self.workflow = self.put(self.home / ".agents" / "workflow.toml", self.WORKFLOW)
        self.stale = self.put(self.home / ".claude" / "rules" / "prd-implementation.md", "v1\n")
        self.user_link = self.home / ".claude" / "agents-old"
        if SYMLINKS:
            os.symlink(str(self.clone / "old-skill"), self.user_link, target_is_directory=True)

    def full(self, **options) -> fileops.Plan:
        plan = self.plan(**options)
        plan.create_directory(self.home / ".claude" / "commands" / "deep")
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated\n", inputs="digest-1")
        plan.write_file(self.workflow, "schema_version = 1\n", replace=fileops.ANY)
        plan.remove_file(self.stale)
        if SYMLINKS:
            plan.create_link(self.home / ".claude" / "skills" / "json-tools", self.clone / "json-tools")
            plan.remove_link(self.user_link)
        plan.remove_lines(self.claude_md, ["@rules/prd-implementation.md", "@rules/epic-implementation.md"])
        plan.edit_block(self.claude_md, "Sprint work follows the two skills.\n")
        plan.edit_block(self.agents_md, "Sprint work follows the two skills.\n")
        plan.edit_block(self.config, "top = 1\n", name="codex-settings", place=fileops.HEAD)
        plan.edit_block(self.project / ".codex" / "config.toml", 'model = "m"\n', place=fileops.HEAD)
        plan.edit_json(self.settings, set={"agent": "manager"})
        plan.ignore(self.ignore, add=[".claude/agents/manager.md"])
        return plan

    def undo(self) -> list[tuple[str, str]]:
        """Reverse the project, then the home, and remove the state."""
        kept: list[tuple[str, str]] = []
        for project in (True, False):
            kept += self.reversal(project=project).apply().kept
            fileops.remove_state(self.roots, project=project)
        return kept


class DryRunTests(FullPlanCase):
    def test_a_dry_run_changes_nothing(self) -> None:
        before = self.snap()
        result = self.full().run(dry_run=True)
        self.assertEqual(self.snap(), before)
        self.assertTrue(result.changed)
        self.assertFalse(result.applied)

    def test_the_dry_run_names_every_change_by_its_anchored_path(self) -> None:
        lines = self.full().describe().lines
        text = "\n".join(lines)
        self.assertNotIn(str(self.root), text)
        for expected in (
            "create directory home:.claude/commands/deep",
            "create directory home:.agents/workflow-setup",
            "create file home:.claude/agents/coder.md",
            "replace file home:.agents/workflow.toml (backup)",
            "remove file home:.claude/rules/prd-implementation.md (backup)",
            "edit file home:.claude/CLAUDE.md (backup)",
            "    line 2: remove: @rules/prd-implementation.md",
            "    block (unnamed): add",
            "    block codex-settings: add",
            "create file project:.codex/config.toml",
            "edit file project:.claude/settings.json (backup)",
            "    key agent: set",
            "edit file git-info:exclude (backup)",
        ):
            self.assertIn(expected, lines)
        if SYMLINKS:
            self.assertIn("create link home:.claude/skills/json-tools -> clone:json-tools", lines)
            self.assertIn("remove link home:.claude/agents-old", lines)

    def test_the_dry_run_is_the_same_each_time(self) -> None:
        self.assertEqual(self.full().describe().lines, self.full().describe().lines)

    def test_the_lines_of_a_real_run_are_those_of_the_dry_run(self) -> None:
        dry = self.full().describe().lines
        self.assertEqual(self.full().apply().lines, dry)


class IdempotenceTests(FullPlanCase):
    def test_a_second_run_plans_nothing_and_writes_nothing(self) -> None:
        self.assertTrue(self.full().apply().changed)
        after = self.snap()
        again = self.full().describe()
        self.assertEqual(again.lines, [fileops.UP_TO_DATE])
        self.assertFalse(again.changed)
        self.assertFalse(self.full().apply().changed)
        self.assertEqual(self.snap(), after)

    def test_a_plan_with_nothing_to_do_leaves_no_state_behind(self) -> None:
        plan = self.plan()
        plan.create_directory(self.home / ".claude")
        plan.remove_file(self.home / "not-there")
        plan.remove_block(self.claude_md)
        before = self.snap()
        self.assertFalse(plan.apply().changed)
        self.assertEqual(self.snap(), before)

    def test_only_what_changed_is_written_again(self) -> None:
        self.full().apply()
        plan = self.full()
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated, again\n", inputs="digest-2")
        with self.assertRaises(fileops.PlanError):  # the same file twice, with different text
            plan.describe()
        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated, again\n", inputs="digest-2")
        self.assertEqual(plan.apply().lines, ["replace file home:.claude/agents/coder.md (backup)"])
        entry = self.record().get("home:.claude/agents/coder.md")
        self.assertEqual(entry["inputs"], "digest-2")
        self.assertEqual(entry["sha256"], fsio.sha256(b"generated, again\n"))


class ValidationTests(FullPlanCase):
    def test_one_fault_anywhere_stops_everything(self) -> None:
        self.put(self.home / "broken.md", "<!-- workflow-setup:start -->\nno end\n")
        plan = self.full()
        plan.edit_block(self.home / "broken.md", "x\n")
        error = self.refused(plan)
        self.assertEqual(error.codes(), {fileops.MARKERS})
        self.assertFalse(self.state.exists())

    def test_every_fault_is_reported_at_once(self) -> None:
        self.put(self.home / "a-file", "x")
        plan = self.plan()
        plan.write_file(self.home / "a-file" / "below.md", "x\n")
        plan.write_file(self.root / "elsewhere.md", "x\n")
        plan.write_file(self.clone / "in-clone.md", "x\n")
        plan.write_file(self.claude_md, "x\n")
        plan.write_file(self.state / "manifest.json", "{}\n")
        plan.edit_json(self.home / "settings.json", set={"agent": "m"})
        error = self.refused(plan)
        self.assertEqual(
            [problem.code for problem in error.problems],
            [fileops.PARENT, fileops.OUTSIDE, fileops.OUTSIDE, fileops.CONFLICT, fileops.STATE, fileops.KEY],
        )
        self.assertEqual(len(error.lines), 6)
        for line in error.lines:
            self.assertNotIn("\n", line)

    def test_a_directory_where_a_file_is_wanted(self) -> None:
        plan = self.plan()
        plan.write_file(self.home / ".claude", "x\n")
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})

    def test_a_file_where_a_directory_is_wanted(self) -> None:
        plan = self.plan()
        plan.create_directory(self.claude_md)
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})

    def test_text_that_is_not_lf(self) -> None:
        plan = self.plan()
        plan.write_file(self.home / "x.md", "a\r\nb\r\n")
        self.assertEqual(self.refused(plan).codes(), {fileops.BAD_ACTION})

    def test_check_lists_the_problems_without_raising(self) -> None:
        plan = self.plan()
        plan.write_file(self.root / "elsewhere.md", "x\n")
        self.assertEqual([problem.code for problem in plan.check()], [fileops.OUTSIDE])
        self.assertEqual(self.full().check(), [])

    @unittest.skipUnless(POSIX and os.geteuid() != 0, "needs permission bits that bind")
    def test_a_directory_that_cannot_be_written_to(self) -> None:
        locked = self.home / "locked"
        locked.mkdir()
        os.chmod(locked, 0o500)
        self.addCleanup(os.chmod, locked, 0o700)
        plan = self.full()
        plan.write_file(locked / "x.md", "x\n")
        self.assertEqual(self.refused(plan).codes(), {fileops.NOT_WRITABLE})


class WholeFileTests(OpsCase):
    def test_a_file_setup_did_not_write_is_a_conflict(self) -> None:
        mine = self.put(self.home / "agents" / "coder.md", "mine\n")
        for policy in (fileops.OWN, fileops.EDITED):
            plan = self.plan()
            plan.write_file(mine, "generated\n", replace=policy)
            self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})

    def test_any_replaces_a_users_file_and_keeps_the_original(self) -> None:
        mine = self.put(self.home / "workflow.toml", "mine\n", 0o640 if POSIX else None)
        mode = stat.S_IMODE(os.stat(mine).st_mode)
        plan = self.plan()
        plan.write_file(mine, "setup's\n", replace=fileops.ANY)
        plan.apply()
        self.assertEqual(mine.read_bytes(), b"setup's\n")
        self.assertEqual(stat.S_IMODE(os.stat(mine).st_mode), mode)
        entry = self.record().get("home:workflow.toml")
        backup = self.record().path(entry["original"]["backup"])
        self.assertEqual(backup.read_bytes(), b"mine\n")
        self.assertEqual(backup, self.state / "backups" / "20260101T000001000000Z" / "home" / "workflow.toml")
        self.assertEqual(entry["original"]["mode"], mode)
        self.reversal().apply()
        self.assertEqual(mine.read_bytes(), b"mine\n")
        self.assertEqual(stat.S_IMODE(os.stat(mine).st_mode), mode)

    def test_any_leaves_a_users_file_that_already_says_it(self) -> None:
        mine = self.put(self.home / "workflow.toml", "same\n")
        plan = self.plan()
        plan.write_file(mine, "same\n", replace=fileops.ANY)
        before = self.snap()
        self.assertFalse(plan.apply().changed)
        self.assertEqual(self.snap(), before)

    def test_a_hand_edit_is_a_conflict_unless_asked(self) -> None:
        target = self.home / "agents" / "coder.md"
        plan = self.plan()
        plan.write_file(target, "one\n")
        plan.apply()
        target.write_bytes(b"one, edited\n")
        plan = self.plan()
        plan.write_file(target, "two\n")
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})
        plan = self.plan()
        plan.write_file(target, "two\n", replace=fileops.EDITED)
        plan.apply()
        self.assertEqual(target.read_bytes(), b"two\n")
        backups = [item for item in self.record().backups if item["path"] == "home:agents/coder.md"]
        self.assertEqual(self.record().path(backups[-1]["backup"]).read_bytes(), b"one, edited\n")

    @unittest.skipUnless(POSIX, "permission bits")
    def test_a_replaced_file_keeps_its_mode_and_a_new_one_gets_the_default(self) -> None:
        target = self.home / "agents" / "coder.md"
        plan = self.plan()
        plan.write_file(target, "one\n")
        plan.write_file(self.home / "private.md", "p\n", mode=0o600)
        plan.apply()
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), fsio.default_mode())
        self.assertEqual(stat.S_IMODE(os.stat(self.home / "private.md").st_mode), 0o600)
        os.chmod(target, 0o640)
        plan = self.plan()
        plan.write_file(target, "two\n")
        plan.apply()
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o640)
        self.assertEqual(target.read_bytes(), b"two\n")

    def test_a_removed_file_is_backed_up_and_comes_back(self) -> None:
        mine = self.put(self.home / "rules" / "old.md", "old\n", 0o640 if POSIX else None)
        mode = stat.S_IMODE(os.stat(mine).st_mode)
        plan = self.plan()
        plan.remove_file(mine, expect_sha256=fsio.sha256(b"old\n"))
        self.assertEqual(plan.apply().lines, ["create directory home:.agents", "create directory home:.agents/workflow-setup", "remove file home:rules/old.md (backup)"])
        self.assertFalse(mine.exists())
        record = self.record()
        self.assertEqual(record.get("home:rules/old.md")["kind"], "removed-file")
        self.assertEqual(record.path(record.backups[0]["backup"]).read_bytes(), b"old\n")
        self.reversal().apply()
        self.assertEqual(mine.read_bytes(), b"old\n")
        self.assertEqual(stat.S_IMODE(os.stat(mine).st_mode), mode)

    def test_a_file_of_other_content_is_not_removed(self) -> None:
        mine = self.put(self.home / "rules" / "old.md", "edited by hand\n")
        plan = self.plan()
        plan.remove_file(mine, expect_sha256=fsio.sha256(b"old\n"))
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})

    def test_a_file_made_and_removed_in_one_plan_leaves_nothing(self) -> None:
        before = self.snap()
        plan = self.plan()
        plan.edit_block(self.home / "notes.md", "x\n")
        plan.write_file(self.home / "agents" / "coder.md", "one\n")
        plan.remove_file(self.home / "notes.md")
        plan.remove_file(self.home / "agents" / "coder.md")
        result = plan.apply()
        self.assertEqual(result.lines, [
            "create directory home:agents", "create directory home:.agents", "create directory home:.agents/workflow-setup",
        ])
        self.assertIsNone(self.record().get("home:notes.md"))
        self.reversal().apply()
        fileops.remove_state(self.roots)
        self.assertEqual(self.snap(), before)

    def test_a_block_taken_out_and_the_file_removed_in_one_plan_restores_the_original(self) -> None:
        mine = self.put(self.home / "CLAUDE.md", "a")
        plan = self.plan()
        plan.edit_block(mine, "x\n")
        plan.apply()
        plan = self.plan()
        plan.remove_block(mine)
        plan.remove_file(mine)
        plan.apply()
        self.assertFalse(mine.exists())
        self.reversal().apply()
        self.assertEqual(mine.read_bytes(), b"a")

    def test_removing_setups_own_file_leaves_no_entry(self) -> None:
        target = self.home / "agents" / "coder.md"
        plan = self.plan()
        plan.write_file(target, "one\n")
        plan.apply()
        plan = self.plan()
        plan.remove_file(target)
        plan.apply()
        self.assertFalse(target.exists())
        self.assertIsNone(self.record().get("home:agents/coder.md"))

    def test_a_changed_generated_file_is_kept_on_the_way_back(self) -> None:
        target = self.home / "agents" / "coder.md"
        plan = self.plan()
        plan.write_file(target, "one\n")
        plan.apply()
        target.write_bytes(b"mine now\n")
        result = self.reversal().apply()
        self.assertEqual(result.kept, [("home:agents/coder.md", "changed since setup wrote it")])
        self.assertEqual(target.read_bytes(), b"mine now\n")
        self.assertIsNotNone(self.record().get("home:agents/coder.md"))
        self.assertFalse(fileops.remove_state(self.roots))
        self.assertTrue(self.manifest_file.exists())

    def test_a_created_directory_goes_when_empty_and_stays_when_not(self) -> None:
        plan = self.plan()
        plan.create_directory(self.home / "a" / "b")
        plan.create_directory(self.home / "c")
        plan.apply()
        self.put(self.home / "c" / "mine.txt", "mine\n")
        result = self.reversal().apply()
        self.assertFalse((self.home / "a").exists())
        self.assertTrue((self.home / "c" / "mine.txt").exists())
        self.assertEqual(result.kept, [("home:c", "the directory is not empty; it is the user's now")])
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertFalse((self.home / ".agents").exists())

    def test_a_directory_that_was_there_is_never_recorded(self) -> None:
        (self.home / ".claude").mkdir()
        plan = self.plan()
        plan.create_directory(self.home / ".claude")
        plan.write_file(self.home / ".claude" / "agents" / "x.md", "x\n")
        plan.apply()
        self.assertIsNone(self.record().get("home:.claude"))
        self.assertEqual(self.record().get("home:.claude/agents"), {"kind": "directory"})


@unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
class RemoveDirectoryTests(OpsCase):
    """A directory setup created goes again once the plan leaves it empty."""

    def made(self) -> tuple[Path, Path]:
        outer = self.home / ".claude" / "skills" / "lead"
        plan = self.plan()
        plan.write_file(outer / "SKILL.md", "one\n", inputs="render:x")
        plan.write_file(outer / "agents" / "openai.yaml", "two\n", inputs="render:x")
        plan.apply()
        return outer, outer / "agents"

    def test_it_goes_with_the_files_it_held(self) -> None:
        outer, inner = self.made()
        plan = self.plan()
        plan.remove_file(outer / "SKILL.md")
        plan.remove_file(inner / "openai.yaml")
        plan.remove_directory(inner)
        plan.remove_directory(outer)
        result = plan.apply()
        self.assertIn("remove directory home:.claude/skills/lead/agents", result.lines)
        self.assertIn("remove directory home:.claude/skills/lead", result.lines)
        self.assertLess(result.lines.index("remove directory home:.claude/skills/lead/agents"),
                        result.lines.index("remove directory home:.claude/skills/lead"))
        self.assertFalse(outer.exists())
        self.assertTrue(outer.parent.is_dir())  # not asked for
        entries = self.record().entries
        self.assertNotIn("home:.claude/skills/lead", entries)
        self.assertNotIn("home:.claude/skills/lead/agents", entries)
        self.assertEqual(entries["home:.claude/skills"], {"kind": "directory"})
        # Asked again, there is nothing to do.
        again = self.plan()
        again.remove_directory(outer)
        self.assertEqual(again.describe().lines, [fileops.UP_TO_DATE])

    def test_one_that_still_holds_something_stays(self) -> None:
        outer, inner = self.made()
        self.put(outer / "mine.txt", "mine\n")
        before = self.snap()
        plan = self.plan()
        plan.remove_file(inner / "openai.yaml")
        plan.remove_directory(inner)
        plan.remove_directory(outer)
        plan.apply()
        self.assertFalse(inner.exists())
        self.assertEqual((outer / "mine.txt").read_bytes(), b"mine\n")
        self.assertEqual((outer / "SKILL.md").read_bytes(), b"one\n")
        self.assertEqual(self.record().entries["home:.claude/skills/lead"], {"kind": "directory"})
        self.assertEqual({name for name in before if name not in self.snap()},
                         {"home/.claude/skills/lead/agents", "home/.claude/skills/lead/agents/openai.yaml"})

    def test_one_that_setup_did_not_create_stays(self) -> None:
        mine = self.home / ".claude" / "skills"
        mine.mkdir(parents=True)
        plan = self.plan()
        plan.remove_directory(mine)
        plan.remove_directory(self.home / "nowhere")
        self.assertEqual(plan.check(), [])
        self.assertEqual(plan.describe().lines, [fileops.UP_TO_DATE])
        self.assertTrue(mine.is_dir())

    def test_one_that_is_filled_again_in_the_same_plan_stays(self) -> None:
        outer, inner = self.made()
        plan = self.plan()
        plan.remove_file(inner / "openai.yaml")
        plan.write_file(inner / "other.yaml", "three\n", inputs="render:x")
        plan.remove_directory(inner)
        plan.apply()
        self.assertEqual(sorted(os.listdir(inner)), ["other.yaml"])

    def test_one_that_is_gone_is_forgotten(self) -> None:
        outer, inner = self.made()
        os.unlink(inner / "openai.yaml")
        os.rmdir(inner)
        plan = self.plan()
        plan.remove_file(inner / "openai.yaml")
        plan.remove_directory(inner)
        plan.apply()
        self.assertNotIn("home:.claude/skills/lead/agents", self.record().entries)

    def linked(self) -> tuple[Path, Path, Path]:
        """setup's skill directory replaced by its owner with a link to a
        directory of theirs, which has an empty ``agents``: the record still
        lists ``agents`` as a directory setup created."""
        outer, inner = self.made()
        plan = self.plan()
        plan.remove_file(outer / "SKILL.md")
        plan.remove_file(inner / "openai.yaml")
        plan.apply()
        os.rmdir(inner)
        os.rmdir(outer)
        mine = self.home / "mine"
        (mine / "agents").mkdir(parents=True)
        os.symlink(mine, outer)
        self.assertEqual(self.record().entries["home:.claude/skills/lead/agents"], {"kind": "directory"})
        return outer, inner, mine

    def test_nothing_is_removed_through_a_directory_of_setups_that_is_a_link_now(self) -> None:
        outer, inner, mine = self.linked()
        for optional in (False, True):
            plan = self.plan(follow_config_symlinks=True)
            plan.remove_directory(inner, optional=optional)
            plan.remove_directory(outer, optional=optional)
            result = plan.apply()
            self.assertTrue((mine / "agents").is_dir())
            self.assertTrue(any("is a link now" in note for note in result.notes), result.notes)
            self.assertFalse(any(line.startswith("remove directory home:.claude/skills/lead/agents")
                                 for line in result.lines), result.lines)

    def test_the_way_back_leaves_what_is_below_such_a_link(self) -> None:
        outer, inner, mine = self.linked()
        result = self.reversal(follow_config_symlinks=True).apply()
        self.assertTrue((mine / "agents").is_dir())
        self.assertIn("home:.claude/skills/lead/agents", [key for key, _ in result.left])
        self.assertNotIn("home:.claude/skills/lead/agents", self.record().entries)

    def test_a_clean_up_the_system_refuses_is_skipped_and_the_run_goes_on(self) -> None:
        outer, inner = self.made()
        refused = OSError(errno.ENOTEMPTY, "Directory not empty")
        real = os.rmdir

        def rmdir(path, *args, **kwargs):
            if Path(path) == inner:
                raise refused
            return real(path, *args, **kwargs)

        plan = self.plan()
        plan.remove_file(outer / "SKILL.md")
        plan.remove_file(inner / "openai.yaml")
        plan.write_file(self.home / ".claude" / "other.md", "x\n", inputs="render:x")
        plan.remove_directory(inner, optional=True)
        plan.remove_directory(outer, optional=True)
        with mock.patch.object(fsio.os, "rmdir", rmdir):
            result = plan.apply()
        self.assertTrue(inner.is_dir())
        self.assertTrue(any("left as it is, and still setup's" in note and "lead/agents" in note
                            for note in result.notes), result.notes)
        entries = self.record().entries
        self.assertEqual(entries["home:.claude/skills/lead/agents"], {"kind": "directory"})
        self.assertEqual(entries["home:.claude/skills/lead"], {"kind": "directory"})
        self.assertNotIn("home:.claude/skills/lead/SKILL.md", entries)
        self.assertIn("home:.claude/other.md", entries)
        self.assertIsNone(self.record().home.pending or None)

    def test_a_removal_that_is_no_clean_up_still_fails(self) -> None:
        outer, inner = self.made()
        refused = OSError(errno.EBUSY, "Device or resource busy")

        def rmdir(path, *args, **kwargs):
            raise refused

        plan = self.plan()
        plan.remove_file(inner / "openai.yaml")
        plan.remove_directory(inner)
        with mock.patch.object(fsio.os, "rmdir", rmdir), self.assertRaises(SetupError) as caught:
            plan.apply()
        self.assertIn("cannot be removed", caught.exception.lines[0])

    def test_the_directories_that_hold_a_record_stay(self) -> None:
        self.made()
        plan = self.plan()
        plan.remove_directory(self.state)
        plan.remove_directory(self.home / ".agents")
        self.assertEqual(plan.describe().lines, [fileops.UP_TO_DATE])
        self.assertTrue(self.manifest_file.is_file())

    def test_the_way_back_is_as_before(self) -> None:
        before = self.snap()
        outer, inner = self.made()
        plan = self.plan()
        plan.remove_file(inner / "openai.yaml")
        plan.remove_directory(inner)
        plan.apply()
        self.reversal().apply()
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(self.snap(), before)


class LinkTests(OpsCase):
    def setUp(self) -> None:
        super().setUp()
        (self.clone / "json-tools").mkdir()
        (self.clone / "csv-tools").mkdir()
        self.link = self.home / ".claude" / "skills" / "json-tools"

    def make(self, target: str = "json-tools") -> None:
        plan = self.plan()
        plan.create_link(self.link, self.clone / target)
        plan.apply()

    def test_a_link_is_made_recorded_and_made_once(self) -> None:
        self.make()
        self.assertTrue(fsio.same_target(os.readlink(self.link), str(self.clone / "json-tools")))
        self.assertEqual(self.record().get("home:.claude/skills/json-tools"), {"kind": "link", "target": "clone:json-tools"})
        after = self.snap()
        self.make()
        self.assertEqual(self.snap(), after)

    def test_setups_own_link_is_repointed(self) -> None:
        self.make()
        self.make("csv-tools")
        self.assertTrue(fsio.same_target(os.readlink(self.link), str(self.clone / "csv-tools")))
        self.assertEqual(self.record().get("home:.claude/skills/json-tools")["target"], "clone:csv-tools")
        self.assertEqual(self.record().backups[-1]["target"], "clone:json-tools")

    def test_anything_setup_did_not_make_is_a_conflict(self) -> None:
        self.link.parent.mkdir(parents=True)
        for make in (
            lambda: self.link.mkdir(),
            lambda: self.link.write_bytes(b"x"),
            lambda: os.symlink(str(self.clone / "json-tools"), self.link, target_is_directory=True),
        ):
            make()
            plan = self.plan()
            plan.create_link(self.link, self.clone / "json-tools")
            self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})
            self.link.rmdir() if self.link.is_dir() and not self.link.is_symlink() else self.link.unlink()

    def test_a_link_the_user_repointed_is_a_conflict_and_is_kept(self) -> None:
        self.make()
        self.link.unlink()
        os.symlink(str(self.clone / "csv-tools"), self.link, target_is_directory=True)
        plan = self.plan()
        plan.create_link(self.link, self.clone / "json-tools")
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})
        self.assertEqual(self.reversal().apply().kept, [("home:.claude/skills/json-tools", "no longer the link setup made")])
        self.assertTrue(self.link.is_symlink())

    def test_a_target_must_be_there_and_below_a_root(self) -> None:
        plan = self.plan()
        plan.create_link(self.link, self.clone / "missing")
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})
        plan = self.plan()
        plan.create_link(self.link, self.root)
        self.assertEqual(self.refused(plan).codes(), {fileops.OUTSIDE})

    def test_a_users_link_is_recorded_by_its_target_and_comes_back(self) -> None:
        self.link.parent.mkdir(parents=True)
        elsewhere = "../../somewhere/else"
        os.symlink(elsewhere, self.link, target_is_directory=True)
        plan = self.plan()
        plan.remove_link(self.link, expect_target=elsewhere)
        plan.apply()
        self.assertFalse(os.path.lexists(self.link))
        record = self.record()
        self.assertEqual(record.get("home:.claude/skills/json-tools"), {"kind": "removed-link", "target": "raw:" + elsewhere, "directory": False})
        self.assertEqual(record.backups[0]["kind"], "link")
        self.assertFalse((self.state / "backups").exists())  # a link is recorded, nothing is copied
        self.reversal().apply()
        self.assertEqual(os.readlink(self.link), elsewhere)

    def test_a_link_to_somewhere_else_is_not_removed(self) -> None:
        self.link.parent.mkdir(parents=True)
        os.symlink(str(self.clone / "csv-tools"), self.link, target_is_directory=True)
        plan = self.plan()
        plan.remove_link(self.link, expect_target=self.clone / "json-tools")
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})

    def test_removing_a_link_never_touches_what_it_leads_to(self) -> None:
        self.put(self.clone / "json-tools" / "SKILL.md", "skill\n")
        self.make()
        plan = self.plan()
        plan.remove_link(self.link)
        plan.apply()
        self.assertFalse(os.path.lexists(self.link))
        self.assertEqual((self.clone / "json-tools" / "SKILL.md").read_bytes(), b"skill\n")
        self.assertIsNone(self.record().get("home:.claude/skills/json-tools"))

    def test_a_file_is_not_removed_as_a_link_nor_a_link_as_a_file(self) -> None:
        self.make()
        plan = self.plan()
        plan.remove_file(self.link)
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})
        mine = self.put(self.home / "plain.md", "x\n")
        plan = self.plan()
        plan.remove_link(mine)
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})


@unittest.skipUnless(SYMLINKS and POSIX, "a relative link is made on Linux and from WSL only")
class ProjectLinkTests(OpsCase):
    """A link from a project into the clone: a skill's directory, recorded
    as ``clone:<name>``, with a relative text where it is asked for."""

    KEY = "project:.claude/skills/json-tools"

    def setUp(self) -> None:
        super().setUp()
        (self.clone / "json-tools").mkdir()
        self.link = self.project / ".claude" / "skills" / "json-tools"

    def make(self) -> fileops.Result:
        plan = self.plan()
        plan.create_link(self.link, self.clone / "json-tools", relative=True)
        return plan.apply()

    def test_a_relative_link_is_made_and_recorded_by_its_target(self) -> None:
        lines = self.make().lines
        self.assertIn(f"create link {self.KEY} -> clone:json-tools", lines)
        self.assertEqual(os.readlink(self.link), os.path.join("..", "..", "..", "fake-clone", "json-tools"))
        self.assertTrue(os.path.samefile(self.link, self.clone / "json-tools"))
        self.assertEqual(self.record().get(self.KEY), {"kind": "link", "target": "clone:json-tools"})
        self.assertNotIn(str(self.root), self.project_manifest_file.read_text(encoding="utf-8"))

    def test_a_second_plan_is_up_to_date(self) -> None:
        self.make()
        after = self.snap()
        plan = self.plan()
        plan.create_link(self.link, self.clone / "json-tools", relative=True)
        self.assertEqual(plan.describe().lines, [fileops.UP_TO_DATE])
        plan.apply()
        self.assertEqual(self.snap(), after)

    def test_it_is_removed_as_setups_own(self) -> None:
        self.put(self.clone / "json-tools" / "SKILL.md", "skill\n")
        self.make()
        plan = self.plan()
        plan.remove_link(self.link, expect_target=self.clone / "json-tools")
        plan.apply()
        self.assertFalse(os.path.lexists(self.link))
        self.assertIsNone(self.record().get(self.KEY))
        self.assertEqual((self.clone / "json-tools" / "SKILL.md").read_bytes(), b"skill\n")

    def test_the_way_back_removes_it(self) -> None:
        before = self.snap()
        self.make()
        result = self.reversal(project=True).apply()
        self.assertEqual(result.kept, [])
        self.assertIn(f"remove link {self.KEY}", result.lines)
        fileops.remove_state(self.roots, project=True)
        self.assertEqual(self.snap(), before)

    def test_a_killed_run_is_settled_by_the_text_written(self) -> None:
        real = Manifest.save
        saved: set[Path] = set()

        def save(manifest: Manifest) -> None:
            if manifest.file in saved:
                raise Crash()
            saved.add(manifest.file)
            real(manifest)

        with mock.patch.object(Manifest, "save", autospec=True, side_effect=save):
            with self.assertRaises(Crash):
                self.make()
        pending = json.loads(self.project_manifest_file.read_bytes())["pending"]
        self.assertIn(self.KEY, [item["path"] for item in pending])
        self.assertEqual(self.record().get(self.KEY), {"kind": "link", "target": "clone:json-tools"})
        plan = self.plan()
        plan.create_link(self.link, self.clone / "json-tools", relative=True)
        self.assertRegex(plan.apply().lines[0], r"complete the record of an interrupted run: \d+ changes were made, 0 were not")

    def test_a_relative_link_is_not_asked_of_windows(self) -> None:
        with mock.patch("os.name", "nt"):
            with self.assertRaises(ValueError):
                self.plan().create_link(self.link, self.clone / "json-tools", relative=True)

    def test_the_project_record_names_only_a_skills_directory_of_the_clone(self) -> None:
        (self.clone / "a" / "b").mkdir(parents=True)
        self.link.parent.mkdir(parents=True)
        os.symlink(str(self.clone / "json-tools"), self.link, target_is_directory=True)

        def record_with(target: str) -> None:
            self.put(self.project_manifest_file, json.dumps({
                "schema_version": 1, "entries": {self.KEY: {"kind": "link", "target": target}},
            }))

        record_with("clone:json-tools")
        self.assertEqual(self.record().get(self.KEY), {"kind": "link", "target": "clone:json-tools"})
        for target in ("clone:.", "clone:a/b", "home:.claude/skills/json-tools"):
            record_with(target)
            with self.assertRaises(SetupError) as caught:
                self.record()
            self.assertIn(f"entry {self.KEY}", caught.exception.lines[0], target)
        # The key is given for a skill's directory only; any other place in
        # the clone is kept as the link's text.
        self.assertEqual(self.roots.target_key(str(self.clone / "json-tools"), manifest.PROJECT), "clone:json-tools")
        self.assertEqual(self.roots.target_key(str(self.clone / "a" / "b"), manifest.PROJECT), f"raw:{self.clone / 'a' / 'b'}")
        self.assertEqual(self.roots.target_key(str(self.clone), manifest.PROJECT), f"raw:{self.clone}")
        self.assertEqual(self.roots.target_key(str(self.clone / "a" / "b"), manifest.HOME), "clone:a/b")


@unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
class AdoptedLinkTests(OpsCase):
    """A link in a project that the user made by hand to a skill of the
    clone, taken over (R3.4): its text goes through another link to the
    clone, so it leads there by its real path only."""

    KEY = "project:.claude/skills/json-tools"

    def setUp(self) -> None:
        super().setUp()
        self.put(self.clone / "json-tools" / "SKILL.md", "skill\n")
        self.alias = self.root / "alias"
        os.symlink(str(self.clone), self.alias, target_is_directory=True)
        self.link = self.project / ".claude" / "skills" / "json-tools"
        self.link.parent.mkdir(parents=True)
        self.text = str(self.alias / "json-tools")
        os.symlink(self.text, self.link, target_is_directory=True)

    def adopt(self) -> fileops.Result:
        plan = self.plan()
        plan.adopt_link(self.link, self.clone / "json-tools")
        return plan.apply()

    def outside_state(self) -> dict[str, tuple]:
        return {name: what for name, what in self.snap().items() if not name.startswith("project/.agents")}

    def test_an_adoption_writes_only_the_record(self) -> None:
        before = self.outside_state()
        plan = self.plan()
        plan.adopt_link(self.link, self.clone / "json-tools")
        self.assertEqual(plan.describe().lines, [
            "create directory project:.agents", "create directory project:.agents/workflow-setup",
            f"take over link {self.KEY} -> clone:json-tools, made by hand",
        ])
        self.adopt()
        self.assertEqual(self.outside_state(), before)
        self.assertEqual(os.readlink(self.link).removeprefix("\\\\?\\"), self.text)
        self.assertEqual(
            self.record().get(self.KEY), {"kind": "link", "target": "clone:json-tools", "adopted": True}
        )
        # Once taken over, setup's link to the skill is up to date as it is.
        after = self.snap()
        plan = self.plan()
        plan.create_link(self.link, self.clone / "json-tools")
        self.assertEqual(plan.describe().lines, [fileops.UP_TO_DATE])
        plan.apply()
        self.assertEqual(self.snap(), after)

    def test_uninstall_leaves_it_and_forgets_it(self) -> None:
        self.adopt()
        result = self.reversal(project=True).apply()
        self.assertIn(f"forget link {self.KEY}, made by hand; it stays, the user's", result.lines)
        self.assertIn(self.KEY, [key for key, _ in result.left])
        self.assertEqual(os.readlink(self.link).removeprefix("\\\\?\\"), self.text)
        self.assertIsNone(self.record().get(self.KEY))
        fileops.remove_state(self.roots, project=True)
        self.assertFalse(self.project_state.exists())
        self.assertEqual(os.readlink(self.link).removeprefix("\\\\?\\"), self.text)

    def test_a_removal_removes_it_and_the_way_back_puts_nothing_back(self) -> None:
        self.adopt()
        plan = self.plan()
        plan.remove_link(self.link, expect_target=self.clone / "json-tools")
        self.assertEqual(plan.apply().lines, [f"remove link {self.KEY}"])
        self.assertFalse(os.path.lexists(self.link))
        self.assertIsNone(self.record().get(self.KEY))
        self.assertEqual((self.clone / "json-tools" / "SKILL.md").read_bytes(), b"skill\n")
        result = self.reversal(project=True).apply()
        self.assertNotIn(self.KEY, " ".join(result.lines))
        self.assertFalse(os.path.lexists(self.link))

    def test_a_project_link_of_setup_with_another_text_is_removed_by_where_it_leads(self) -> None:
        os.unlink(self.link)
        plan = self.plan()
        plan.create_link(self.link, self.clone / "json-tools")
        plan.apply()
        self.assertNotIn("adopted", self.record().get(self.KEY))
        os.unlink(self.link)    # the other side writes it through a link to the clone
        os.symlink(self.text, self.link, target_is_directory=True)
        plan = self.plan()
        plan.remove_link(self.link, expect_target=self.clone / "json-tools")
        self.assertEqual(plan.apply().lines, [f"remove link {self.KEY}"])
        self.assertFalse(os.path.lexists(self.link))
        self.assertIsNone(self.record().get(self.KEY))

    def test_one_already_gone_is_forgotten(self) -> None:
        self.adopt()
        os.unlink(self.link)
        plan = self.plan()
        plan.remove_link(self.link)
        plan.apply()
        self.assertIsNone(self.record().get(self.KEY))
        self.reversal(project=True).apply()
        self.assertFalse(os.path.lexists(self.link))

    def test_it_is_refused_unless_a_link_of_the_users_leads_there(self) -> None:
        (self.clone / "csv-tools").mkdir()
        plan = self.plan()
        plan.adopt_link(self.link, self.clone / "csv-tools")
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})
        absent = self.project / ".claude" / "skills" / "csv-tools"
        plan = self.plan()
        plan.adopt_link(absent, self.clone / "csv-tools")
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})
        self.adopt()
        plan = self.plan()
        plan.adopt_link(self.link, self.clone / "json-tools")
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})
        home = self.home / ".claude" / "skills" / "json-tools"
        home.parent.mkdir(parents=True)
        os.symlink(str(self.clone / "json-tools"), home, target_is_directory=True)
        plan = self.plan()
        plan.adopt_link(home, self.clone / "json-tools")
        self.assertEqual(self.refused(plan).codes(), {fileops.BAD_ACTION})

    def test_adopted_is_a_mark_of_a_project_record_only(self) -> None:
        def record_with(file: Path, key: str, adopted: object) -> None:
            self.put(file, json.dumps({
                "schema_version": 1,
                "entries": {key: {"kind": "link", "target": "clone:json-tools", "adopted": adopted}},
            }))

        record_with(self.project_manifest_file, self.KEY, True)
        self.assertTrue(self.record().get(self.KEY)["adopted"])
        record_with(self.project_manifest_file, self.KEY, "yes")
        with self.assertRaises(SetupError):
            self.record()
        self.project_manifest_file.unlink()
        record_with(self.manifest_file, "home:.claude/skills/json-tools", True)
        with self.assertRaises(SetupError) as caught:
            self.record()
        self.assertIn("adopted", caught.exception.lines[0])

    def test_a_killed_adoption_is_settled_by_the_link_on_disk(self) -> None:
        real = Manifest.save
        saved: set[Path] = set()

        def save(manifest: Manifest) -> None:
            if manifest.file in saved:
                raise Crash()
            saved.add(manifest.file)
            real(manifest)

        with mock.patch.object(Manifest, "save", autospec=True, side_effect=save):
            with self.assertRaises(Crash):
                self.adopt()
        pending = json.loads(self.project_manifest_file.read_bytes())["pending"]
        self.assertIn(self.KEY, [item["path"] for item in pending])
        self.assertEqual(
            self.record().get(self.KEY), {"kind": "link", "target": "clone:json-tools", "adopted": True}
        )
        # The link went before the record was settled: the adoption was not made.
        os.unlink(self.link)
        self.assertIsNone(self.record().get(self.KEY))


@unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
class SymlinkedConfigTests(OpsCase):
    """``CLAUDE.md`` and ``rules`` are links to a directory of the user's
    inside the home (a dotfiles checkout). A link that leads out of the
    home is never written through: ``OutsideLinkTests``."""

    def setUp(self) -> None:
        super().setUp()
        self.other = self.home / "dotfiles"
        self.put(self.other / "CLAUDE.md", "theirs\n")
        (self.other / "rules").mkdir()
        (self.home / ".claude").mkdir()
        self.claude_md = self.home / ".claude" / "CLAUDE.md"
        os.symlink(str(self.other / "CLAUDE.md"), self.claude_md)
        os.symlink(str(self.other / "rules"), self.home / ".claude" / "rules", target_is_directory=True)

    def test_a_linked_file_is_refused_as_its_own_condition(self) -> None:
        plan = self.plan()
        plan.edit_block(self.claude_md, "pointer\n")
        with self.assertRaises(fileops.SymlinkedConfigPath) as caught:
            plan.apply()
        self.assertIsInstance(caught.exception, SetupError)
        problem = caught.exception.problems[0]
        self.assertEqual(problem.code, fileops.SYMLINK)
        self.assertEqual(problem.path, self.claude_md)
        self.assertEqual(problem.link, self.claude_md)
        self.assertTrue(fsio.same_target(problem.resolves_to, str(self.other / "CLAUDE.md")))
        self.assertIn("--follow-config-symlinks", str(caught.exception))
        self.assertEqual((self.other / "CLAUDE.md").read_bytes(), b"theirs\n")

    def test_a_path_under_a_linked_directory_is_refused(self) -> None:
        target = self.home / ".claude" / "rules" / "new" / "rule.md"
        plan = self.plan()
        plan.write_file(target, "rule\n")
        error = self.refused(plan)
        self.assertIsInstance(error, fileops.SymlinkedConfigPath)
        self.assertEqual(error.problems[0].link, self.home / ".claude" / "rules")
        self.assertEqual(os.listdir(self.other / "rules"), [])

    def test_a_linked_home_is_refused(self) -> None:
        linked = self.root / "linked-home"
        os.symlink(str(self.home), linked, target_is_directory=True)
        plan = fileops.Plan(Roots(linked, None, self.clone))
        plan.write_file(linked / "x.md", "x\n")
        with self.assertRaises(fileops.SymlinkedConfigPath) as caught:
            plan.describe()
        self.assertEqual(caught.exception.problems[0].link, linked)

    def test_mixed_with_another_fault_it_is_a_plain_plan_error(self) -> None:
        plan = self.plan()
        plan.edit_block(self.claude_md, "pointer\n")
        plan.write_file(self.root / "elsewhere", "x\n")
        error = self.refused(plan)
        self.assertNotIsInstance(error, fileops.SymlinkedConfigPath)
        self.assertEqual(error.codes(), {fileops.SYMLINK, fileops.OUTSIDE})

    def test_the_question_can_be_asked_without_a_plan(self) -> None:
        found = fileops.symlink_in_the_way(self.roots, self.home / ".claude" / "rules" / "x.md")
        self.assertEqual((found.code, found.link), (fileops.SYMLINK, self.home / ".claude" / "rules"))
        self.assertEqual(fileops.symlink_in_the_way(self.roots, self.claude_md).link, self.claude_md)
        self.assertIsNone(fileops.symlink_in_the_way(self.roots, self.home / ".claude" / "agents" / "x.md"))

    def test_with_the_flag_the_file_is_written_where_the_link_leads(self) -> None:
        before_link = os.readlink(self.claude_md)
        plan = self.plan(follow_config_symlinks=True)
        plan.edit_block(self.claude_md, "pointer\n")
        plan.write_file(self.home / ".claude" / "rules" / "rule.md", "rule\n")
        plan.apply()
        self.assertEqual(os.readlink(self.claude_md), before_link)
        self.assertEqual(
            (self.other / "CLAUDE.md").read_bytes(),
            b"theirs\n\n<!-- workflow-setup:start -->\npointer\n<!-- workflow-setup:end -->\n",
        )
        self.assertEqual((self.other / "rules" / "rule.md").read_bytes(), b"rule\n")
        self.assertIsNotNone(self.record().get("home:.claude/CLAUDE.md"))
        after = self.snap()
        again = self.plan(follow_config_symlinks=True)
        again.edit_block(self.claude_md, "pointer\n")
        self.assertFalse(again.apply().changed)
        self.assertEqual(self.snap(), after)
        self.reversal(follow_config_symlinks=True).apply()
        self.assertEqual((self.other / "CLAUDE.md").read_bytes(), b"theirs\n")
        self.assertEqual(os.readlink(self.claude_md), before_link)
        self.assertFalse((self.other / "rules" / "rule.md").exists())

    def test_a_link_the_plan_makes_is_not_a_link_in_the_way(self) -> None:
        (self.clone / "json-tools").mkdir()
        plan = self.plan()
        plan.create_link(self.home / ".claude" / "skills" / "json-tools", self.clone / "json-tools")
        plan.apply()
        # A symlink on Linux, a junction on Windows (P5.2).
        self.assertEqual(fsio.look(self.home / ".claude" / "skills" / "json-tools").kind, fsio.LINK)


@unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
class OutsideLinkTests(OpsCase):
    """``CLAUDE.md`` and ``rules`` are links into another home, beside this
    one: nothing is written there, with the option or without."""

    def setUp(self) -> None:
        super().setUp()
        self.other = self.root / "other-home"
        self.put(self.other / "CLAUDE.md", "theirs\n")
        (self.other / "rules").mkdir()
        (self.home / ".claude").mkdir()
        self.claude_md = self.home / ".claude" / "CLAUDE.md"
        os.symlink(str(self.other / "CLAUDE.md"), self.claude_md)
        os.symlink(str(self.other / "rules"), self.home / ".claude" / "rules", target_is_directory=True)

    def actions(self):
        return (
            ("edit a block", lambda plan: plan.edit_block(self.claude_md, "pointer\n")),
            ("write a file", lambda plan: plan.write_file(self.home / ".claude" / "rules" / "rule.md", "rule\n")),
            ("make a directory", lambda plan: plan.create_directory(self.home / ".claude" / "rules" / "new")),
        )

    def test_a_link_out_of_the_home_is_refused_whatever_the_option(self) -> None:
        before_link = os.readlink(self.claude_md)
        for follow, code in ((False, fileops.SYMLINK), (True, fileops.OUTSIDE)):
            for label, action in self.actions():
                with self.subTest(label, follow=follow):
                    plan = self.plan(follow_config_symlinks=follow)
                    action(plan)
                    error = self.refused(plan)  # the whole tree is as it was
                    self.assertEqual(error.codes(), {code})
                    if follow:
                        self.assertNotIsInstance(error, fileops.SymlinkedConfigPath)
                        self.assertIn("is outside the directories this run may write to", str(error))
        self.assertEqual((self.other / "CLAUDE.md").read_bytes(), b"theirs\n")
        self.assertEqual(os.listdir(self.other / "rules"), [])
        self.assertEqual(sorted(os.listdir(self.other)), ["CLAUDE.md", "rules"])
        self.assertEqual(os.readlink(self.claude_md), before_link)
        self.assertFalse((self.home / ".agents").exists())

    def test_the_whole_plan_is_refused_with_it(self) -> None:
        plan = self.plan(follow_config_symlinks=True)
        plan.write_file(self.home / ".claude" / "agents" / "coder.md", "generated\n")
        plan.edit_block(self.claude_md, "pointer\n")
        self.assertEqual(self.refused(plan).codes(), {fileops.OUTSIDE})
        self.assertFalse((self.home / ".claude" / "agents").exists())


class CredentialsTests(OpsCase):
    NAMES = (".credentials.json", "auth.json", "AUTH.JSON")

    def test_no_action_takes_a_credentials_file(self) -> None:
        for name in self.NAMES:
            secret = self.put(self.home / ".codex" / name, '{"token": "t"}')
            actions = (
                lambda plan: plan.write_file(secret, "x\n", replace=fileops.ANY),
                lambda plan: plan.remove_file(secret),
                lambda plan: plan.edit_block(secret, "x\n", syntax="toml"),
                lambda plan: plan.remove_lines(secret, ["x"]),
                lambda plan: plan.edit_json(secret, set={"agent": "m"}),
                lambda plan: plan.remove_link(secret),
                lambda plan: plan.create_link(self.home / "link", secret, directory=False),
            )
            for action in actions:
                plan = self.plan()
                action(plan)
                with mock.patch.object(fsio, "read_bytes", side_effect=AssertionError("opened")):
                    self.assertEqual({problem.code for problem in plan.check()}, {fileops.CREDENTIALS})
                self.assertEqual(self.refused(plan).codes(), {fileops.CREDENTIALS})
            secret.unlink()

    def test_the_primitives_refuse_them_too(self) -> None:
        secret = self.put(self.home / "auth.json", "{}")
        for call in (
            lambda: fsio.read_bytes(secret),
            lambda: fsio.atomic_write(secret, b"x"),
            lambda: fsio.remove_file(secret),
            lambda: fsio.make_link(str(secret), self.home / "l", False),
        ):
            with self.assertRaises(fsio.CredentialsRefused):
                call()
        self.assertEqual(secret.read_bytes(), b"{}")

    @unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
    def test_a_link_that_leads_to_one_is_not_followed(self) -> None:
        secret = self.put(self.home / ".codex" / "auth.json", "{}")
        link = self.home / "notes.md"
        os.symlink(str(secret), link)
        plan = self.plan(follow_config_symlinks=True)
        plan.edit_block(link, "x\n")
        self.assertEqual(self.refused(plan).codes(), {fileops.CREDENTIALS})


class FailureTests(FullPlanCase):
    def fail_at(self, target: Path, error: BaseException):
        real = fsio.atomic_write

        def write(path, data, mode=None):
            if Path(path) == target:
                raise error
            return real(path, data, mode)

        return mock.patch.object(fsio, "atomic_write", side_effect=write)

    def test_a_write_that_fails_leaves_no_partial_file_and_an_exact_record(self) -> None:
        with self.fail_at(self.agents_md, SetupError(f"{self.agents_md}: cannot be written: disk full")):
            with self.assertRaises(SetupError) as caught:
                self.full().apply()
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertRegex(caught.exception.lines[0], r"disk full; \d+ of \d+ changes were made and are recorded")
        self.assertEqual(self.agents_md.read_bytes(), self.AGENTS_MD)
        self.assertEqual(self.temporaries(), [])
        # What came before the failure was done, what came after was not.
        self.assertTrue((self.home / ".claude" / "agents" / "coder.md").exists())
        self.assertIn(b"workflow-setup:start", self.claude_md.read_bytes())
        self.assertEqual(self.config.read_bytes(), self.CONFIG_TOML)
        self.assertEqual(self.settings.read_bytes(), self.SETTINGS)
        record = self.record()
        self.assertEqual((record.recovered, record.dropped), (0, 0))
        self.assertNotIn(b'"pending"', self.manifest_file.read_bytes())
        for key, entry in record:
            path = record.path(key)
            if "sha256" in entry:
                self.assertEqual(fsio.sha256(path.read_bytes()), entry["sha256"], key)
            elif entry["kind"] == "directory":
                self.assertTrue(path.is_dir(), key)
        for key in ("home:.codex/AGENTS.md", "home:.codex/config.toml", "project:.claude/settings.json", "git-info:exclude"):
            self.assertIsNone(record.get(key), key)
        self.assertIsNotNone(record.get("home:.claude/CLAUDE.md"))
        # The next run finishes the work, and the way back is still exact.
        self.assertTrue(self.full().apply().changed)
        self.assertEqual(self.full().describe().lines, [fileops.UP_TO_DATE])

    def test_a_failure_before_the_first_change_leaves_only_setups_own_state(self) -> None:
        """The user's files are as they were and no change is recorded.
        What is there besides is setup's state: the records, closed, and
        the backups that were written, which stay and stay listed."""
        before = self.snap()
        backups = self.state / "backups" / "20260101T000001000000Z" / "home"
        with self.fail_at(backups / ".codex" / "config.toml", SetupError("no room for the backup")):
            with self.assertRaises(SetupError):
                self.full().apply()
        after = self.snap()
        states = ("home/.agents/workflow-setup", "project/.agents")
        for name, was in before.items():
            self.assertEqual(after.get(name), was, name)
        new = sorted(name for name in after if name not in before)
        self.assertTrue(new)
        for name in new:
            self.assertTrue(any(name == state or name.startswith(state + "/") for state in states), name)
        self.assertEqual(self.temporaries(), [])
        self.assertFalse(os.path.lexists(self.state / "lock"))
        self.assertFalse(os.path.lexists(self.project_state / "lock"))
        # The records are closed, and hold the state directories alone.
        home = json.loads(self.manifest_file.read_bytes())
        project = json.loads(self.project_manifest_file.read_bytes())
        self.assertNotIn("pending", home)
        self.assertNotIn("pending", project)
        self.assertEqual(list(home["entries"]), ["home:.agents/workflow-setup"])
        self.assertEqual(sorted(project["entries"]), ["project:.agents", "project:.agents/workflow-setup"])
        # Every backup that was written is listed, and holds the user's bytes.
        written = sorted(
            name[len("home/"):] for name, found in after.items()
            if name.startswith("home/.agents/workflow-setup/backups/") and found[0] == "file"
        )
        self.assertEqual(sorted(item["backup"].split(":", 1)[1] for item in home["backups"]), written)
        self.assertEqual(project["backups"], [])
        self.assertTrue(written)
        for item in home["backups"]:
            kept = self.home / item["backup"].split(":", 1)[1]
            self.assertEqual(kept.read_bytes(), (self.home / item["path"].split(":", 1)[1]).read_bytes(), item["path"])
        self.assertFalse((backups / ".codex" / "config.toml").exists())
        self.assertFalse(fileops.leftovers(self.roots))
        # The next run does the whole work, and the way back is exact.
        self.assertTrue(self.full().apply().changed)
        self.assertEqual(self.undo(), [])
        self.assertEqual(self.snap(), before)

    def test_another_runs_backups_are_never_taken_for_this_runs(self) -> None:
        theirs = self.put(self.state / "backups" / "20260101T000001000000Z" / "home" / "kept.md", "theirs\n")
        before = self.snap()
        with self.assertRaises(SetupError) as caught:
            self.full().apply()
        self.assertIn("backups of this run's stamp are already there", caught.exception.lines[0])
        self.assertEqual(self.snap(), before)
        self.assertEqual(theirs.read_bytes(), b"theirs\n")

    def test_a_record_that_cannot_be_saved_first_stops_the_run(self) -> None:
        before = self.snap()
        with self.fail_at(self.manifest_file, SetupError("no room for the record")):
            with self.assertRaises(SetupError):
                self.full().apply()
        self.assertEqual(self.snap(), before)

    def test_a_crash_in_the_middle_is_settled_by_the_next_run(self) -> None:
        with self.fail_at(self.agents_md, Crash()):
            with mock.patch.object(Manifest, "save", autospec=True, side_effect=self._save_once()):
                with self.assertRaises(Crash):
                    self.full().apply()
        self.assertIn(b'"pending"', self.manifest_file.read_bytes())
        self.assertEqual(self.agents_md.read_bytes(), self.AGENTS_MD)
        self.assertEqual(self.temporaries(), [])
        record = self.record()
        self.assertGreater(record.recovered, 0)
        self.assertGreater(record.dropped, 0)
        self.assertIsNotNone(record.get("home:.claude/CLAUDE.md"))
        self.assertIsNotNone(record.get("home:.claude/agents/coder.md"))
        self.assertIsNone(record.get("home:.codex/AGENTS.md"))
        lines = self.full().describe().lines
        self.assertRegex(lines[0], r"complete the record of an interrupted run: \d+ changes were made, \d+ were not")
        self.assertIn("edit file home:.codex/AGENTS.md (backup)", lines)
        self.assertNotIn("create file home:.claude/agents/coder.md", lines)
        self.full().apply()
        self.assertNotIn(b'"pending"', self.manifest_file.read_bytes())
        self.assertEqual(self.full().describe().lines, [fileops.UP_TO_DATE])

    def _save_once(self):
        """Each record is saved once, with its pending list, and never
        again: the process is gone before the closing save."""
        real = Manifest.save
        saved: set[Path] = set()

        def save(manifest: Manifest) -> None:
            if manifest.file in saved:
                raise Crash()
            saved.add(manifest.file)
            real(manifest)

        return save

    def test_a_crash_after_the_last_change_only_needs_the_record_completed(self) -> None:
        with mock.patch.object(Manifest, "save", autospec=True, side_effect=self._save_once()):
            with self.assertRaises(Crash):
                self.full().apply()
        reference = self.snap()
        result = self.full().apply()
        self.assertRegex(result.lines[0], r"complete the record of an interrupted run: \d+ changes were made, 0 were not")
        self.assertEqual(len(result.lines), 1)
        after = self.snap()
        changed = sorted(name for name in after if after[name] != reference.get(name))
        self.assertEqual(changed, ["home/.agents/workflow-setup/manifest.json", "project/.agents/workflow-setup/manifest.json"])
        self.assertEqual(self.undo(), [])

    def test_a_file_changed_between_validation_and_the_write_is_left(self) -> None:
        plan = self.full()
        real = fsio.atomic_write

        def write(path, data, mode=None):
            if Path(path) == self.claude_md:
                self.agents_md.write_bytes(b"changed under setup's feet\n")
            return real(path, data, mode)

        with mock.patch.object(fsio, "atomic_write", side_effect=write):
            with self.assertRaises(SetupError) as caught:
                plan.apply()
        self.assertIn("changed while setup was running", caught.exception.lines[0])
        self.assertEqual(self.agents_md.read_bytes(), b"changed under setup's feet\n")
        self.assertIsNone(self.record().get("home:.codex/AGENTS.md"))


class AtomicWriteTests(OpsCase):
    def test_a_failed_replace_leaves_the_old_file_and_no_temporary(self) -> None:
        target = self.put(self.home / "f.md", "old\n")
        with mock.patch.object(fsio, "_replace", side_effect=PermissionError(13, "Access is denied")):
            with self.assertRaises(SetupError) as caught:
                fsio.atomic_write(target, b"new\n")
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn("read-only, or open in another program?", caught.exception.lines[0])
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(os.listdir(self.home), ["f.md"])

    def test_a_missing_directory_is_one_line(self) -> None:
        with self.assertRaises(SetupError) as caught:
            fsio.atomic_write(self.home / "none" / "f.md", b"x")
        self.assertEqual(len(caught.exception.lines), 1)

    def test_what_is_written_is_what_was_given(self) -> None:
        target = self.home / "f.md"
        fsio.atomic_write(target, b"a\r\nb\n\xef\xbb\xbf")
        self.assertEqual(target.read_bytes(), b"a\r\nb\n\xef\xbb\xbf")


class RecordTests(FullPlanCase):
    def test_no_record_holds_a_path_of_this_machine(self) -> None:
        self.full().apply()
        for file in (self.manifest_file, self.project_manifest_file):
            text = file.read_text(encoding="utf-8")
            self.assertNotIn(str(self.root), text)
            self.assertNotIn(self.root.as_posix(), text)
            data = json.loads(text)
            for key in data["entries"]:
                self.assertRegex(key, r"^(home|project|git-info):[^/\\:]")
            for backup in data["backups"]:
                if backup["kind"] == "file":
                    scope = "home" if file == self.manifest_file else "project"
                    anchors = "home" if scope == "home" else "project|git-info"
                    self.assertRegex(backup["backup"], rf"^{scope}:\.agents/workflow-setup/backups/[^/]+/({anchors})/")
                else:
                    self.assertRegex(backup["target"], r"^(clone|home|project):")
                self.assertRegex(backup["path"], r"^(home|project|git-info):")

    def test_a_projects_entries_are_in_the_projects_record(self) -> None:
        self.full().apply()
        home = json.loads(self.manifest_file.read_bytes())
        project = json.loads(self.project_manifest_file.read_bytes())
        self.assertTrue(all(key.startswith("home:") for key in home["entries"]))
        self.assertEqual(
            sorted(project["entries"]),
            [
                "git-info:exclude", "project:.agents", "project:.agents/workflow-setup", "project:.claude/settings.json",
                "project:.codex", "project:.codex/config.toml",
            ],
        )
        self.assertEqual(project["entries"]["project:.agents/workflow-setup"]["kind"], "directory")
        # The exclude file is the project's, and so is its backup.
        self.assertTrue(all(item["path"].startswith(("project:", "git-info:")) for item in project["backups"]))
        # The project's backups are in the project, the home's in the home.
        self.assertTrue(all(item["backup"].startswith("project:") for item in project["backups"] if "backup" in item))
        self.assertTrue(all(item["backup"].startswith("home:") for item in home["backups"] if "backup" in item))
        held = sorted(name for name in self.snap() if "/backups/" in name and not name.endswith(("/home", "/project")))
        self.assertTrue(any(name.startswith("project/.agents/workflow-setup/backups/") for name in held))
        self.assertFalse(any(name.startswith("home/") and "/project/" in name for name in held))

    def test_the_record_gives_each_file_its_hash_and_its_inputs(self) -> None:
        self.full().apply()
        record = self.record()
        entry = record.get("home:.claude/agents/coder.md")
        self.assertEqual(entry, {"kind": "file", "sha256": fsio.sha256(b"generated\n"), "inputs": "digest-1", "original": None})
        self.assertEqual(record.path("home:.claude/agents/coder.md"), self.home / ".claude" / "agents" / "coder.md")
        for key, entry in record:
            if "sha256" in entry:
                self.assertEqual(entry["sha256"], fsio.sha256(record.path(key).read_bytes()), key)
        text = record.get("home:.claude/CLAUDE.md")
        self.assertEqual(list(text["blocks"]), [""])
        self.assertEqual(
            text["removed_lines"],
            [[
                {"index": 1, "text": "@rules/prd-implementation.md", "eol": "\r\n"},
                {"index": 2, "text": "@rules/epic-implementation.md", "eol": "\r\n"},
            ]],
        )

    def test_a_newer_record_is_refused_and_left_alone(self) -> None:
        newer = json.dumps({"schema_version": manifest.SCHEMA_VERSION + 1, "entries": {}}).encode()
        self.put(self.manifest_file, newer)
        before = self.snap()
        with self.assertRaises(SetupError) as caught:
            self.full().apply()
        self.assertIn("written by a newer setup", caught.exception.lines[0])
        with self.assertRaises(SetupError):
            self.full().describe()
        with self.assertRaises(SetupError):
            fileops.read_record(self.roots)
        self.assertEqual(self.snap(), before)

    def test_a_record_that_is_not_one_is_refused_and_left_alone(self) -> None:
        for bad in (b"{not json", b"[]", b'{"entries": {}}', b'{"schema_version": 1, "entries": []}', b'{"schema_version": true}'):
            self.put(self.manifest_file, bad)
            with self.assertRaises(SetupError) as caught:
                self.full().apply()
            self.assertIn("is not a setup record", caught.exception.lines[0])
            self.assertEqual(self.manifest_file.read_bytes(), bad)

    def test_the_current_version_is_written(self) -> None:
        self.full().apply()
        self.assertEqual(json.loads(self.manifest_file.read_bytes())["schema_version"], 1)
        self.assertTrue(self.manifest_file.read_bytes().endswith(b"}\n"))
        self.assertNotIn(b"\r", self.manifest_file.read_bytes())

    def test_a_record_cannot_lead_out_of_its_root(self) -> None:
        for key in ("home:../outside", "home:/etc/passwd", "home:a//b", "home:", "nowhere:x", "home:a\\..\\b"):
            with self.assertRaises(SetupError):
                self.roots.path(key)
        self.put(self.root / "outside.md", "x\n")
        self.put(self.manifest_file, json.dumps({
            "schema_version": 1,
            "entries": {"home:../outside.md": {"kind": "file", "sha256": fsio.sha256(b"x\n"), "original": None}},
        }))
        # A record that names such a path is refused whole when it is read,
        # in one line that names the file and the entry; nothing is done.
        before = self.snap()
        for run in (lambda: self.reversal().apply(), lambda: self.reversal().describe(), self.record):
            with self.assertRaises(SetupError) as caught:
                run()
            self.assertEqual(len(caught.exception.lines), 1)
            self.assertIn(str(self.manifest_file), caught.exception.lines[0])
            self.assertIn("entry home:../outside.md: not a path a record may hold", caught.exception.lines[0])
        self.assertEqual(self.snap(), before)
        self.assertEqual((self.root / "outside.md").read_bytes(), b"x\n")


    def test_the_exclude_file_is_the_one_path_of_the_git_directory_a_record_names(self) -> None:
        from wfsetup import manifest
        entry_ = {"kind": "text", "sha256": fsio.sha256(b"x\n"), "created": True, "original": None,
                  "syntax": "gitignore", "blocks": {}, "removed_lines": []}
        self.assertIsNone(manifest._path_fault("git-info:exclude", manifest.PROJECT))
        self.assertEqual(manifest.scope_of("git-info:exclude"), manifest.PROJECT)
        for key in ("git-info:attributes", "git-info:exclude/x", "git-info:."):
            for scope in (manifest.PROJECT, manifest.HOME, None):
                self.assertIsNotNone(manifest._path_fault(key, scope), (key, scope))
        # The user-level record names none of it.
        self.put(self.manifest_file, json.dumps({"schema_version": 1, "entries": {"git-info:exclude": entry_}}))
        with self.assertRaises(SetupError) as caught:
            self.record()
        self.assertIn("entry git-info:exclude: the user-level record lists no path of a project's git directory",
                      caught.exception.lines[0])
        self.manifest_file.unlink()
        # A project's record that names another file there is refused whole.
        self.put(self.project_manifest_file, json.dumps({"schema_version": 1, "entries": {"git-info:config": entry_}}))
        with self.assertRaises(SetupError) as caught:
            self.record()
        self.assertIn("other than its exclude file", caught.exception.lines[0])
        # A link's target is never there.
        self.assertIsNotNone(manifest._target_fault("git-info:exclude", manifest.PROJECT))
        self.assertTrue(self.roots.target_key(str(self.exclude_file), manifest.HOME).startswith("raw:"))

    def test_the_exclude_files_backup_is_in_the_project_and_the_way_back_restores_it(self) -> None:
        self.full().apply()
        record = json.loads(self.project_manifest_file.read_bytes())
        backups = [item for item in record["backups"] if item["path"] == "git-info:exclude"]
        self.assertEqual(len(backups), 1)
        self.assertRegex(backups[0]["backup"], r"^project:\.agents/workflow-setup/backups/[^/]+/git-info/exclude$")
        self.assertEqual(self.roots.path(backups[0]["backup"]).read_bytes(), self.IGNORE)
        self.assertNotIn("git-info:exclude", json.loads(self.manifest_file.read_bytes())["entries"])
        self.undo()
        self.assertEqual(self.ignore.read_bytes(), self.IGNORE)


class StateTests(FullPlanCase):
    def test_a_file_setup_edited_and_then_removed_comes_back_as_it_first_was(self) -> None:
        self.full().apply()
        plan = self.plan()
        plan.remove_file(self.agents_md)
        plan.remove_file(self.home / ".claude" / "agents" / "coder.md")
        plan.apply()
        record = self.record()
        self.assertEqual(record.get("home:.codex/AGENTS.md")["kind"], "removed-file")
        self.assertIsNone(record.get("home:.claude/agents/coder.md"))
        self.reversal().apply()
        self.assertEqual(self.agents_md.read_bytes(), self.AGENTS_MD)

    @unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
    def test_state_under_a_link_is_refused_like_any_config_path(self) -> None:
        home = self.root / "home-two"
        elsewhere = home / "dotfiles" / "agents"
        elsewhere.mkdir(parents=True)
        os.symlink(str(elsewhere), home / ".agents", target_is_directory=True)
        roots = Roots(home, None, self.clone)
        plan = fileops.Plan(roots)
        plan.write_file(home / "x.md", "x\n")
        with self.assertRaises(fileops.SymlinkedConfigPath):
            plan.apply()
        self.assertEqual(os.listdir(elsewhere), [])
        self.assertFalse((home / "x.md").exists())
        plan = fileops.Plan(roots, follow_config_symlinks=True)
        plan.write_file(home / "x.md", "x\n")
        plan.apply()
        self.assertTrue((elsewhere / "workflow-setup" / "manifest.json").exists())
        self.assertEqual((home / "x.md").read_bytes(), b"x\n")

    @unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")
    def test_state_under_a_link_that_leads_out_of_the_home_is_refused_whatever_the_option(self) -> None:
        home = self.root / "home-two"
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        home.mkdir()
        os.symlink(str(elsewhere), home / ".agents", target_is_directory=True)
        roots = Roots(home, None, self.clone)
        before = self.snap()
        for follow, code in ((False, fileops.SYMLINK), (True, fileops.OUTSIDE)):
            with self.subTest(follow=follow):
                plan = fileops.Plan(roots, follow_config_symlinks=follow)
                plan.write_file(home / "x.md", "x\n")
                self.assertEqual({problem.code for problem in plan.check()}, {code})
                with self.assertRaises(fileops.PlanError) as caught:
                    plan.apply()
                self.assertEqual(caught.exception.codes(), {code})
                self.assertEqual(self.snap(), before)
        self.assertEqual(os.listdir(elsewhere), [])
        self.assertFalse((home / "x.md").exists())

    def test_the_options_of_a_command_that_writes(self) -> None:
        import argparse
        parser = argparse.ArgumentParser(allow_abbrev=False)
        fileops.add_arguments(parser)
        self.assertEqual(vars(parser.parse_args([])), {"dry_run": False, "follow_config_symlinks": False})
        args = parser.parse_args(["--dry-run", "--follow-config-symlinks"])
        self.assertTrue(args.dry_run and args.follow_config_symlinks)

    def test_remove_state_does_nothing_where_there_is_none(self) -> None:
        before = self.snap()
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertTrue(fileops.remove_state(self.roots, project=True))
        self.assertEqual(self.snap(), before)

    def test_the_users_own_agents_directory_survives_the_state(self) -> None:
        self.full().apply()
        self.undo()
        self.assertEqual(self.workflow.read_bytes(), self.WORKFLOW)
        self.assertEqual(os.listdir(self.home / ".agents"), ["workflow.toml"])


class RootsTests(OpsCase):
    def test_a_path_belongs_to_the_deepest_root(self) -> None:
        inside = Roots(self.home, self.home / "work" / "project", self.home / "work" / "clone")
        self.assertEqual(inside.key(self.home / ".claude" / "x"), "home:.claude/x")
        self.assertEqual(inside.key(self.home / "work" / "project" / ".gitignore"), "project:.gitignore")
        self.assertEqual(inside.key(self.home / "work" / "clone" / "json-tools", target=True), "clone:json-tools")
        self.assertEqual(inside.key(self.home), "home:.")
        self.assertIsNone(inside.key(self.root))
        for key in ("home:.claude/x", "project:.gitignore", "clone:json-tools", "home:."):
            self.assertEqual(inside.key(inside.path(key), target=key.startswith("clone")), key)

    def test_a_project_that_is_the_clone(self) -> None:
        same = Roots(self.home, self.clone, self.clone)
        self.assertEqual(same.key(self.clone / ".gitignore"), "project:.gitignore")
        self.assertEqual(same.key(self.clone / "json-tools", target=True), "clone:json-tools")

    def test_a_further_root_has_its_own_name(self) -> None:
        elsewhere = self.root / "claude-config"
        elsewhere.mkdir()
        roots = Roots(self.home, None, self.clone, (("claude-home", elsewhere),))
        self.assertEqual(roots.key(elsewhere / "agents" / "x.md"), "claude-home:agents/x.md")
        plan = fileops.Plan(roots, stamp=self.stamp())
        plan.write_file(elsewhere / "agents" / "x.md", "x\n")
        plan.apply()
        self.assertIn("claude-home:agents/x.md", fileops.read_record(roots).entries)
        with self.assertRaises(SetupError):
            Roots(self.home, extra=(("home", elsewhere),))

    def test_roots_come_from_the_locations_of_a_run(self) -> None:
        roots = Roots.of(self.locations())
        self.assertEqual((roots.home, roots.project, roots.clone), (self.home, self.project, self.clone))


class RoundTripTests(FullPlanCase):
    """R8.1 at this layer: apply everything, undo from the record and the
    backups, and every path, link target, byte and mode is as at the start."""

    def test_apply_then_undo_leaves_the_tree_as_it_was(self) -> None:
        start = self.snap()
        self.full().apply()
        self.assertNotEqual(self.snap(), start)
        self.assertEqual(self.undo(), [])
        self.assertEqual(self.snap(), start)

    def test_the_way_back_has_a_dry_run_too(self) -> None:
        self.full().apply()
        applied = self.snap()
        lines = self.reversal().describe().lines
        self.assertEqual(self.snap(), applied)
        self.assertIn("restore file home:.claude/CLAUDE.md", lines)
        self.assertIn("remove file home:.claude/agents/coder.md", lines)
        self.assertIn("restore file home:.claude/rules/prd-implementation.md", lines)
        self.assertIn("remove directory home:.claude/commands", lines)

    def test_two_runs_then_undo(self) -> None:
        start = self.snap()
        self.full().apply()
        plan = self.plan()
        plan.edit_block(self.claude_md, "Sprint work follows the two skills, v2.\n")
        plan.edit_block(self.claude_md, "second\n", name="second")
        plan.write_file(self.workflow, "schema_version = 1\n# v2\n", replace=fileops.ANY)
        plan.edit_json(self.settings, set={"agent": "coder"})
        plan.ignore(self.ignore, add=[".codex/agents/manager.toml"], remove=[".claude/agents/manager.md"])
        plan.apply()
        self.assertEqual(self.undo(), [])
        self.assertEqual(self.snap(), start)

    def test_undo_twice_is_harmless(self) -> None:
        start = self.snap()
        self.full().apply()
        self.undo()
        self.assertEqual(self.undo(), [])
        self.assertEqual(self.snap(), start)

    def test_what_the_user_changed_in_between_is_kept(self) -> None:
        start = self.snap()
        self.full().apply()
        # The user edits around setup's block, in a text file and a JSON file.
        self.claude_md.write_bytes(self.claude_md.read_bytes().replace(b"keep this", b"keep this, edited"))
        self.settings.write_bytes(self.settings.read_bytes().replace(b'"dark"', b'"light"'))
        self.undo()
        self.assertEqual(self.claude_md.read_bytes(), self.CLAUDE_MD.replace(b"keep this", b"keep this, edited"))
        self.assertEqual(self.settings.read_bytes(), self.SETTINGS.replace(b'"dark"', b'"light"'))
        after = self.snap()
        different = sorted(name for name in set(start) | set(after) if start.get(name) != after.get(name))
        self.assertEqual(different, ["home/.claude/CLAUDE.md", "project/.claude/settings.json"])

    def test_the_state_stays_while_an_entry_is_kept(self) -> None:
        self.full().apply()
        coder = self.home / ".claude" / "agents" / "coder.md"
        coder.write_bytes(b"edited\n")
        kept = self.undo()
        self.assertEqual(kept, [("home:.claude/agents/coder.md", "changed since setup wrote it")])
        self.assertTrue(self.manifest_file.exists())
        self.assertFalse(self.project_manifest_file.exists())
        self.assertEqual(list(json.loads(self.manifest_file.read_bytes())["entries"]), [
            "home:.agents/workflow-setup", "home:.claude/agents", "home:.claude/agents/coder.md",
        ])
        # Once the user gives the file up, the next undo finishes the job.
        coder.write_bytes(b"generated\n")
        self.assertEqual(self.undo(), [])
        self.assertFalse((self.home / ".claude" / "agents").exists())
        self.assertFalse(self.state.exists())

    def test_a_home_that_was_empty_is_empty_again(self) -> None:
        home = self.root / "empty-home"
        home.mkdir()
        roots = Roots(home, None, self.clone)
        plan = fileops.Plan(roots, stamp=self.stamp())
        plan.write_file(home / ".claude" / "agents" / "coder.md", "x\n")
        plan.edit_block(home / ".codex" / "AGENTS.md", "pointer\n")
        plan.apply()
        fileops.plan_reversal(roots, stamp=self.stamp()).apply()
        self.assertTrue(fileops.remove_state(roots))
        self.assertEqual(os.listdir(home), [])


# --- fileops: setup's link where something of the user's was --------------------------

@unittest.skipUnless(LINKS, "needs links to directories")
class ReplacedCase(OpsCase):
    def setUp(self) -> None:
        super().setUp()
        self.target = self.clone / "skill"
        self.put(self.target / "SKILL.md", "the clone's\n")
        self.path = self.home / ".claude" / "skills" / "skill"
        self.key = "home:.claude/skills/skill"

    def users_link(self) -> Path:
        theirs = self.root / "theirs" / "skill"
        self.put(theirs / "SKILL.md", "theirs\n")
        self.path.parent.mkdir(parents=True)
        fsio.make_link(str(theirs), self.path, True)
        return theirs

    def users_directory(self) -> None:
        self.put(self.path / "SKILL.md", "a copy\n")
        self.put(self.path / "scripts" / "deep" / "tool.py", "print()\n", 0o750 if POSIX else None)

    def remove_copy(self, plan: fileops.Plan) -> None:
        plan.remove_file(self.path / "SKILL.md")
        plan.remove_file(self.path / "scripts" / "deep" / "tool.py")
        for directory in (self.path / "scripts" / "deep", self.path / "scripts", self.path):
            plan.remove_directory(directory, users=True)

    def test_a_users_link_then_setups_link_in_one_plan_and_back(self) -> None:
        theirs = self.users_link()
        before = self.snap()
        plan = self.plan()
        plan.remove_link(self.path)
        plan.create_link(self.path, self.target)
        result = plan.apply()
        self.assertEqual(result.lines[-1], f"replace link {self.key} -> clone:skill")
        self.assertTrue(fsio.same_target(fsio.look(self.path).target, str(self.target)))
        entry = self.record().entries[self.key]
        self.assertEqual((entry["kind"], entry["target"]), ("link", "clone:skill"))
        self.assertEqual((entry["replaced"]["kind"], entry["replaced"]["target"]), ("removed-link", f"raw:{theirs}"))
        self.assertEqual((theirs / "SKILL.md").read_text(encoding="utf-8"), "theirs\n")
        # Asked again, the link is up to date and still carries what it took the place of.
        again = self.plan()
        again.create_link(self.path, self.target)
        self.assertFalse(again.apply().changed)
        self.assertEqual(self.record().entries[self.key], entry)
        back = self.reversal().apply()
        self.assertEqual(back.lines[0], f"restore link {self.key} -> raw:{theirs}")
        self.assertEqual(back.kept, [])
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(self.snap(), before)

    def test_without_the_removal_the_users_link_is_still_a_conflict(self) -> None:
        self.users_link()
        plan = self.plan()
        plan.create_link(self.path, self.target)
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})

    def test_a_users_directory_then_setups_link_in_one_plan_and_back(self) -> None:
        self.users_directory()
        before = self.snap()
        plan = self.plan()
        self.remove_copy(plan)
        plan.create_link(self.path, self.target)
        result = plan.apply()
        self.assertEqual(result.lines[-1], f"create link {self.key} -> clone:skill, in place of the directory there")
        self.assertEqual((self.path / "SKILL.md").read_text(encoding="utf-8"), "the clone's\n")
        entries = self.record().entries
        self.assertEqual(entries[self.key]["replaced"], {"kind": "removed-directory"})
        self.assertEqual(entries[self.key + "/scripts"], {"kind": "removed-directory"})
        self.assertEqual(entries[self.key + "/SKILL.md"]["kind"], "removed-file")
        back = self.reversal().apply()
        self.assertEqual(back.kept, [])
        self.assertIn(f"restore directory {self.key}, in place of the link there", back.lines)
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(self.snap(), before)
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), "the clone's\n")   # never followed

    def test_setups_link_removed_later_leaves_the_users_entry_for_the_way_back(self) -> None:
        self.users_directory()
        before = self.snap()
        plan = self.plan()
        self.remove_copy(plan)
        plan.create_link(self.path, self.target)
        plan.apply()
        later = self.plan()   # the skill left the clone: the stale sweep
        later.remove_link(self.path, expect_target=self.target)
        later.apply()
        self.assertEqual(self.record().entries[self.key], {"kind": "removed-directory"})
        self.assertEqual(fsio.look(self.path).kind, fsio.ABSENT)
        # And it can be linked again, by a later run.
        again = self.plan()
        again.create_link(self.path, self.target)
        again.apply()
        self.assertEqual(self.record().entries[self.key]["replaced"], {"kind": "removed-directory"})
        self.reversal().apply()
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(self.snap(), before)

    def test_a_directory_that_still_holds_something_is_not_removed(self) -> None:
        self.users_directory()
        plan = self.plan()
        plan.remove_file(self.path / "SKILL.md")
        plan.remove_directory(self.path, users=True)
        error = self.refused(plan)
        self.assertEqual(error.codes(), {fileops.CONFLICT})
        self.assertIn("still holds something the plan does not remove", error.lines[0])

    def test_a_link_changed_since_is_kept_and_nothing_is_put_back_through_it(self) -> None:
        self.users_directory()
        plan = self.plan()
        self.remove_copy(plan)
        plan.create_link(self.path, self.target)
        plan.apply()
        elsewhere = self.root / "elsewhere"
        self.put(elsewhere / "keep.md", "the user's\n")
        fsio.remove_link(self.path)
        fsio.make_link(str(elsewhere), self.path, True)
        before = self.snap()
        back = self.reversal().apply()
        kept = dict(back.kept)
        self.assertIn(self.key, kept)
        self.assertIn(self.key + "/SKILL.md", kept)
        self.assertEqual(sorted(os.listdir(elsewhere)), ["keep.md"])   # nothing was written through the link
        self.assertFalse(fileops.remove_state(self.roots))
        self.assertEqual({name: what for name, what in self.snap().items() if "workflow-setup" not in name},
                         {name: what for name, what in before.items() if "workflow-setup" not in name})


if __name__ == "__main__":
    unittest.main()
