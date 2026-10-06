"""Tests for what the Phase 5 review found in the command modules: one class
a finding, named by the finding's id in the sprint's review list. Each test
fails on the code as it was reviewed.

Run from the repository root:
    python -B -m unittest discover -s tools/setup/tests

No test touches a real home or starts a real provider: a provider's program
is a stub that says what it was started with (``discovery_stub``).
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import unittest
from pathlib import Path
from unittest import mock

import support
from discovery_stub import DiscoveryStub
from fileops_support import POSIX, SYMLINKS, snapshot
from provider_stub import LIVE, VERSION, fixture
from test_codexsettings import APPLY, DEFAULT, ROOT, SettingsCase
from test_doctor import DoctorCase
from test_entry import CONFIG, DEFAULT_ON, SETTINGS, EntryCase
from test_migrate import BLOCK_END, BLOCK_START, MigrateCase
from test_render import tree
from wfsetup import blocks, codexsettings, discovery, doctor, entry, fileops, fsio, homes, locations, migrate, modellist
from wfsetup import render, uninstall
from wfsetup.commands import init
from wfsetup.errors import SetupError
from wfsetup.locations import Locations

LINKABLE = unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink")


def one_line(case: unittest.TestCase, err: str, *words: str) -> None:
    """A fault of the input is one line on stderr, with these words."""
    case.assertEqual(len(err.strip().splitlines()), 1, err)
    case.assertTrue(err.startswith("error: "), err)
    for word in words:
        case.assertIn(word, err)


# --- Minor: the directories a run is given ---------------------------------------

class LocationsTests(support.ScratchCase):
    """A project or a home that is the clone or lies inside it, and a
    project that is the home, were accepted; ``init`` and ``render`` then
    wrote into the clone."""

    def refused(self, *argv: str) -> str:
        before = snapshot(self.root)
        code, out, err = support.run(*argv)
        self.assertEqual((code, out), (2, ""), err)
        self.assertEqual(snapshot(self.root), before)
        return err

    def test_a_project_that_is_the_clone_or_lies_inside_it(self) -> None:
        home = ("--home", str(self.home))
        for project, how in ((self.clone, "is the clone"), (self.clone / "roles", "lies inside the clone")):
            for argv in (("init", "--yes"), ("init", "--yes", "--dry-run"), ("render", "--dry-run"), ("render",),
                         ("uninstall",), ("uninstall", "--dry-run")):
                with self.subTest(project=project.name, command=argv):
                    err = self.refused(*argv, *home, "--project", str(project))
                    one_line(self, err, "--project", how, "setup writes nothing inside the clone")

    def test_a_command_that_only_reads_may_be_given_the_clone_as_its_project(self) -> None:
        # The repository is worked on like any project: a session in it asks `show`.
        self.write(self.clone / ".agents" / "workflow.toml", '[process]\ndocs_dir = "sprints"\n')
        before = snapshot(self.root)
        home = ("--home", str(self.home))
        code, out, err = support.run("show", "process.docs_dir", *home, "--project", str(self.clone))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, 'process.docs_dir = "sprints"  (project)\n')
        for argv in (("homes",), ("validate",), ("doctor", "--only", "sources")):
            with self.subTest(argv):
                code, _, err = support.run(*argv, *home, "--project", str(self.clone))
                self.assertNotEqual(code, 2, err)
        self.assertEqual(snapshot(self.root), before)
        with self.assertRaises(SetupError):
            locations.from_args(mock.Mock(home=str(self.home), project=str(self.clone)))

    def test_a_home_that_is_the_clone_or_lies_inside_it(self) -> None:
        for home, how in ((self.clone, "is the clone"), (self.clone / "tools", "lies inside the clone")):
            for argv in (("show",), ("init", "--yes"), ("render",), ("uninstall", "--dry-run"), ("homes",)):
                with self.subTest(home=home.name, command=argv[0]):
                    one_line(self, self.refused(*argv, "--home", str(home)), "--home", how)

    def test_a_project_that_is_the_home(self) -> None:
        for argv in (("uninstall",), ("init", "--yes"), ("render", "--dry-run")):
            err = self.refused(*argv, "--home", str(self.home), "--project", str(self.home))
            one_line(self, err, "--project", "is the home directory itself")
        # A command that only reads answers, as the skills' own scripts do.
        code, _, err = support.run("show", "--home", str(self.home), "--project", str(self.home))
        self.assertEqual((code, err), (0, ""))

    def test_a_project_inside_the_home_is_a_project_like_any_other(self) -> None:
        inner = self.home / "work" / "project"
        inner.mkdir(parents=True)
        code, _, err = support.run("show", "--home", str(self.home), "--project", str(inner))
        self.assertEqual((code, err), (0, ""))
        where = locations.from_args(mock.Mock(home=str(self.home), project=str(inner)))
        self.assertEqual((where.project, where.real_home), (inner, False))

    @LINKABLE
    def test_a_link_to_the_clone_is_the_clone(self) -> None:
        link = self.root / "by-another-name"
        os.symlink(str(self.clone), link, target_is_directory=True)
        one_line(self, self.refused("render", "--dry-run", "--home", str(self.home), "--project", str(link)),
                 "the clone setup runs from")
        one_line(self, self.refused("show", "--home", str(link / "tools")), "lies inside the clone")


# --- Minor: path arguments --------------------------------------------------------

class PathArgumentTests(MigrateCase):
    """A line break in a path argument split the error over two lines, and
    ``--remove-stale ""`` named the working directory."""

    BAD = ("a\nb", "a\rb", "a\x1bb", "a\x00b", "a b", "a\u0085b", "a\x7fb")

    def refused(self, *argv: str) -> str:
        before = snapshot(self.root)
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, out, err = support.run(*argv)
        self.assertEqual(code, 2, out + err)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(len(err.strip().split("\n")), 1, err)
        self.assertTrue(err.isprintable() or err.rstrip("\n").isprintable(), err)
        return err

    def test_a_control_character_in_a_path_argument(self) -> None:
        home = ("--home", str(self.home))
        for bad in self.BAD:
            with self.subTest(repr(bad)):
                self.assertIn("--home", self.refused("show", "--home", str(self.home) + bad))
                self.assertIn("--project", self.refused("show", *home, "--project", bad))
                self.assertIn("--remove-stale", self.refused(
                    "render", "--no-roles", "--migrate-v1", "--remove-stale", str(self.rules / "x") + bad, *home))
                self.assertIn("--clone-was", self.refused("uninstall", "--dry-run", "--clone-was", os.sep + bad, *home))
                self.assertIn("--save-probe", self.refused("doctor", "--only", "sources", "--save-probe", bad, *home))
                self.assertIn("--worktree-root", self.refused(
                    "render", "--no-roles", "--apply-codex-settings", "--worktree-root", os.sep + bad, *home))

    def test_an_empty_value_is_no_path(self) -> None:
        home = ("--home", str(self.home))
        for empty in ("", "   "):
            with self.subTest(repr(empty)):
                err = self.refused("render", "--no-roles", "--migrate-v1", "--remove-stale", empty, *home)
                self.assertIn("--remove-stale: an empty value is not a path", err)
                self.assertNotIn(os.getcwd(), err)
                self.assertIn("--save-probe", self.refused("doctor", "--only", "sources", "--save-probe", empty, *home))
                self.assertIn("--clone-was", self.refused("uninstall", "--clone-was", empty, *home))
                self.assertIn("--home", self.refused("show", "--home", empty))
                self.assertIn("--project", self.refused("show", *home, "--project", empty))

    def test_a_probe_is_not_saved_inside_the_clone(self) -> None:
        err = self.refused("doctor", "--only", "sources", "--save-probe", str(self.clone / "probes"),
                           "--home", str(self.home))
        self.assertIn("--save-probe", err)
        self.assertIn("inside the clone setup runs from", err)
        self.assertEqual(discovery.save_directory(str(self.root / "probes"), self.clone), str(self.root / "probes"))


# --- S5: the v1 link rule ----------------------------------------------------------

@LINKABLE
class OwnSkillLinkTests(MigrateCase):
    """A user's own skill link into any git tree, with a v1 skill's name,
    was taken for a link into a clone and replaced without being asked."""

    OWN = "---\nname: json-tools\ndescription: My own, unrelated.\n---\n\nMine.\n"

    def own_link(self) -> tuple[Path, Path]:
        mine = self.root / "dotfiles"
        self.data(mine / ".git" / "HEAD", "ref: refs/heads/main\n")
        skill = self.data(mine / "json-tools" / "SKILL.md", self.OWN).parent
        self.claude_skills.mkdir(parents=True)
        link = self.claude_skills / "json-tools"
        os.symlink(str(skill), link, target_is_directory=True)
        return link, skill

    def test_it_is_kept_and_reported_and_nothing_is_written(self) -> None:
        link, skill = self.own_link()
        before = tree(self.root)
        for more in ((), ("--dry-run",)):
            code, out, err = self.migrate(*more)
            self.assertEqual(code, 2, out)
            self.assertEqual(tree(self.root), before)
            self.assertIn("a directory setup does not recognise as a copy or a clone of the skill", err)
            self.assertIn(f"--remove-stale {migrate.quoted(link)}", err)
        self.assertLinked(link, skill)
        code, findings = self.v1_check()
        self.assertEqual(code, 1)
        self.assertTrue(any("migration keeps it until you decide" in found["detail"] and str(link) in found["detail"]
                            for found in findings), findings)

    def test_remove_stale_removes_it_and_the_way_back_puts_it_back(self) -> None:
        link, skill = self.own_link()
        before = tree(self.claude)
        code, report, err = self.migrated("--remove-stale", str(link))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("because --remove-stale names it", self.said(report, link)["says"])
        self.assertLinked(link, self.clone / "json-tools")
        self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), self.OWN)
        self.undo()
        self.assertEqual(tree(self.claude), before)

    def test_a_link_into_the_clone_this_run_uses_is_still_a_v1_link(self) -> None:
        self.claude_skills.mkdir(parents=True)
        link = self.claude_skills / "json-tools"
        os.symlink(str(self.clone / "json-tools"), link, target_is_directory=True)
        gone = self.codex / "skills" / "csv-tools"           # a place render does not link into
        gone.parent.mkdir(parents=True)
        os.symlink(str(self.clone / "skills" / "csv-tools"), gone, target_is_directory=True)   # where v1 had it
        before = tree(self.clone)
        code, report, err = self.migrated()
        self.assertEqual((code, err), (0, ""))
        item = self.said(report, link)
        self.assertEqual(item["status"], migrate.REMOVE)
        self.assertIn("as a link into the clone setup runs from, which setup did not make", item["says"])
        self.assertLinked(link, self.clone / "json-tools")
        item = self.said(report, gone)
        self.assertEqual(item["status"], migrate.REMOVE)
        self.assertIn("as a link into the clone setup runs from, which no longer has it", item["says"])
        self.assertNothingAt(gone)
        self.assertEqual(tree(self.clone), before)

    def test_a_link_into_another_clone_of_this_repository_is_kept_until_it_is_named(self) -> None:
        for marks in (False, True):
            with self.subTest(marks=marks):
                old = self.root / f"old-clone-{marks}"             # a clone from before the setup tool
                self.data(old / ".git" / "HEAD", "ref: refs/heads/main\n")
                if marks:                                          # and one that holds the tool
                    self.data(old / "tools" / "setup" / "workflow_setup.py", "# the tool\n")
                    (old / "roles").mkdir()
                self.data(old / "json-tools" / "SKILL.md", "Changed in that clone.\n")
                self.data(old / "csv-tools" / "SKILL.md", "Another skill of the repository.\n")
                self.claude_skills.mkdir(parents=True, exist_ok=True)
                link = self.claude_skills / "json-tools"
                os.symlink(str(old / "json-tools"), link, target_is_directory=True)
                before, held = tree(self.root), tree(old)
                # It is in the way of the link render makes there, so the run stops; nothing is written.
                for more in ((), ("--dry-run",)):
                    code, out, err = self.migrate(*more)
                    self.assertEqual(code, 2, out)
                    self.assertEqual(tree(self.root), before)
                    self.assertIn(f"--remove-stale {migrate.quoted(link)}", err)
                self.assertLinked(link, old / "json-tools")
                code, report, err = self.migrated("--remove-stale", str(link))
                self.assertEqual((code, err), (0, ""))
                self.assertIn("because --remove-stale names it", self.said(report, link)["says"])
                self.assertLinked(link, self.clone / "json-tools")
                self.assertEqual(tree(old), held)   # removed as a link: what it led to is as it was
                self.undo()
                self.assertLinked(link, old / "json-tools")
                os.unlink(link)

    def test_a_link_that_leads_nowhere_in_a_git_tree_that_is_no_clone_is_kept(self) -> None:
        mine = self.root / "dotfiles"
        self.data(mine / ".git" / "HEAD", "ref: refs/heads/main\n")
        self.data(mine / "notes.md", "Mine.\n")
        link = self.codex / "skills" / "json-tools"           # a place render does not link into
        link.parent.mkdir(parents=True)
        os.symlink(str(mine / "json-tools"), link, target_is_directory=True)
        code, report, err = self.migrated()
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        item = self.said(report, link)
        self.assertEqual(item["status"], migrate.KEPT)
        self.assertIn("which leads nowhere, outside the clone setup runs from", item["says"])
        self.assertEqual(item["flag"], f"--remove-stale {migrate.quoted(link)}")
        self.assertLinked(link, mine / "json-tools")


# --- B6: a skills place that leads into a clone -----------------------------------

@LINKABLE
class ClonePlaceTests(MigrateCase):
    """With ``--follow-config-symlinks`` and a clone that has no ``.git``,
    migration replaced the clone's own skill directories by links."""

    def archive(self, inside: bool = True) -> Path:
        """A clone as an archive copy gives it: the marks, and no ``.git``.
        In the home, where a run may write; or beside it, where no run may."""
        archive = (self.home if inside else self.root) / "archive"
        self.data(archive / "tools" / "setup" / "workflow_setup.py", "# the tool\n")
        (archive / "roles").mkdir()
        self.copy(archive / "json-tools", "json-tools")              # by its bytes, a known v1 copy
        self.data(archive / "csv-tools" / "SKILL.md", "Not a committed version.\n")
        return archive

    def test_nothing_in_it_is_removed_or_linked_with_any_option(self) -> None:
        archive = self.archive()
        os.symlink(str(archive), self.claude_skills, target_is_directory=True)
        before = tree(archive)
        stale = [part for name in ("json-tools", "csv-tools") for part in ("--remove-stale", str(self.claude_skills / name))]
        for argv in ((), ("--dry-run",), ("--follow-config-symlinks",), ("--follow-config-symlinks", "--dry-run")):
            with self.subTest(argv):
                code, report, err = self.migrated(*argv)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(tree(archive), before)
                item = self.said(report, self.claude_skills)
                self.assertEqual(item["status"], migrate.NEVER)
                self.assertIn("leads into a clone", item["says"])
                self.assertEqual(set(self.items(report, "claude-code", "skills").values()), {render.SKIPPED})
        # The entries in it are no v1 locations: naming one stops the run.
        code, out, err = self.migrate("--follow-config-symlinks", *stale)
        self.assertEqual(code, 2, out)
        self.assertIn("not a place a v1 install used", err)
        self.assertEqual(tree(archive), before)
        # The other provider's place is installed as always.
        self.assertLinked(self.codex_skills / "json-tools", self.clone / "json-tools")

    def test_one_outside_the_home_is_skipped_as_a_place_no_run_writes_to(self) -> None:
        archive = self.archive(inside=False)
        os.symlink(str(archive), self.claude_skills, target_is_directory=True)
        before = tree(archive)
        stale = [part for name in ("json-tools", "csv-tools") for part in ("--remove-stale", str(self.claude_skills / name))]
        for argv in ((), ("--dry-run",), ("--follow-config-symlinks",), ("--follow-config-symlinks", "--dry-run")):
            with self.subTest(argv):
                code, report, err = self.migrated(*argv)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(tree(archive), before)
                item = self.said(report, self.claude_skills)
                self.assertEqual(item["status"], migrate.SKIPPED)
                self.assertIn("leads into a clone", item["says"])
                self.assertIn("which leads out of the directories this run may write to: skipped, whatever the options",
                              item["says"])
                self.assertEqual(set(self.items(report, "claude-code", "skills").values()), {render.SKIPPED})
        code, out, err = self.migrate("--follow-config-symlinks", *stale)
        self.assertEqual(code, 2, out)
        self.assertEqual(tree(archive), before)
        self.assertLinked(self.codex_skills / "json-tools", self.clone / "json-tools")
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, out, err = support.run("render", "--no-roles", "--follow-config-symlinks", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(tree(archive), before)
        self.assertIn("which leads out of the directories this run may write to: skipped, whatever the options",
                      " ".join(out.split()))

    def test_the_clone_setup_runs_from_is_such_a_clone(self) -> None:
        os.symlink(str(self.clone), self.claude_skills, target_is_directory=True)
        before = tree(self.clone)
        code, report, err = self.migrated("--follow-config-symlinks")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.clone), before)
        self.assertIn("the clone setup runs from", self.said(report, self.claude_skills)["says"])
        code, findings = self.v1_check()
        self.assertEqual(code, 1)   # doctor says it until the user moves the link away

    def test_render_without_migration_writes_nothing_there_either(self) -> None:
        archive = self.archive()
        os.symlink(str(archive), self.claude_skills, target_is_directory=True)
        before = tree(archive)
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, out, err = support.run("render", "--no-roles", "--follow-config-symlinks", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(tree(archive), before)
        self.assertIn("setup writes nothing into a clone", " ".join(out.split()))

    def test_a_place_the_user_keeps_under_git_is_no_clone_of_this_repository(self) -> None:
        # Dotfiles under git: the home's own directories are written as always.
        for directory in (self.claude, self.claude_skills, self.codex):
            self.data(directory / ".git" / "HEAD", "ref: refs/heads/main\n")
        for _ in range(2):   # the second run meets setup's own links beside the .git entry
            with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
                code, out, err = support.run("render", "--no-roles", "--home", str(self.home))
            self.assertEqual((code, err), (0, ""), out)
            self.assertLinked(self.claude_skills / "json-tools", self.clone / "json-tools")
            self.assertNotIn("setup writes nothing into a clone", " ".join(out.split()))

    def test_a_shared_directory_in_the_home_that_is_no_clone_is_written_as_before(self) -> None:
        shared = self.home / "dotfiles" / "shared-skills"
        shared.mkdir(parents=True)
        os.symlink(str(shared), self.claude_skills, target_is_directory=True)
        code, report, err = self.migrated()
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        self.assertEqual(os.listdir(shared), [])
        code, report, err = self.migrated("--follow-config-symlinks")
        self.assertEqual((code, err), (0, ""))
        self.assertLinked(shared / "json-tools", self.clone / "json-tools")
        self.assertLinked(self.claude_skills, shared)   # the place stays the user's link

    def test_a_shared_directory_outside_the_home_is_skipped_and_not_changed_by_a_byte(self) -> None:
        shared = self.root / "shared-skills"
        self.data(shared / "theirs" / "SKILL.md", "Another home's.\n")
        self.copy(shared / "json-tools", "json-tools")   # by its bytes a known v1 copy: not removed there either
        os.symlink(str(shared), self.claude_skills, target_is_directory=True)
        before = tree(shared)
        for argv in ((), ("--dry-run",), ("--follow-config-symlinks", "--dry-run"), ("--follow-config-symlinks",)):
            with self.subTest(argv):
                code, report, err = self.migrated(*argv)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(tree(shared), before)
                self.assertEqual(set(self.items(report, "claude-code", "skills").values()), {render.SKIPPED})
                self.assertEqual([line for line in report["plan"] if ".claude/skills" in line], [])
                self.assertEqual(report["counts"]["needs_flag"], 0)
        self.assertLinked(self.claude_skills, shared)
        # The other provider's place is installed as always.
        self.assertLinked(self.codex_skills / "json-tools", self.clone / "json-tools")


# --- S3: a migration that was interrupted ----------------------------------------

class ResumeTests(MigrateCase):
    """After a run stopped between the files of a copy and its directory,
    the same command refused the directory as "edited by hand"."""

    def half_removed(self) -> tuple[Path, Path, dict]:
        one = self.copy(self.claude_skills / "self-reflection", "self-reflection")
        two = self.copy(self.claude_skills / "usage-cost", "usage-cost")
        before = tree(self.claude)
        # What such a run leaves: the files gone and recorded, the directories there.
        plan = fileops.Plan(self.roots())
        for file in (one / "SKILL.md", two / "scripts" / "usage_cost.py"):
            plan.remove_file(file, expect_sha256=fsio.sha256(file.read_bytes()))
        plan.apply()
        self.assertEqual((os.listdir(one), sorted(os.listdir(two))), ([], ["SKILL.md", "scripts"]))
        return one, two, before

    def test_the_same_command_finishes_and_the_way_back_restores_every_file(self) -> None:
        one, two, before = self.half_removed()
        code, report, err = self.migrated("--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.said(report, one)["status"], migrate.REMOVE)
        self.assertIn("what an interrupted run of setup left of a copy of", self.said(report, one)["says"])
        code, report, err = self.migrated()
        self.assertEqual((code, err), (0, ""))
        self.assertLinked(one, self.clone / "self-reflection")
        self.assertLinked(two, self.clone / "usage-cost")
        code, report, err = self.migrated()
        self.assertEqual((code, report["changed"]), (0, False))
        self.undo()
        self.assertEqual(tree(self.claude), before)

    def test_doctor_names_it_as_work_in_progress(self) -> None:
        one, _, _ = self.half_removed()
        code, findings = self.v1_check()
        self.assertEqual(code, 1)
        said = [found["detail"] for found in findings if found["subject"] == str(one)]
        self.assertEqual(len(said), 1)
        self.assertIn("what an interrupted run of setup left of a copy of", said[0])
        self.assertIn("`render --migrate-v1` removes it", said[0])
        self.assertNotIn("edited by hand", said[0])

    def test_an_empty_directory_with_nothing_in_the_record_is_still_not_a_known_copy(self) -> None:
        empty = self.old_skills / "json-tools"
        empty.mkdir(parents=True)
        code, report, _ = self.migrated()
        self.assertEqual(code, render.EXIT_NEEDS_FLAG)
        self.assertEqual(self.said(report, empty)["status"], migrate.KEPT)
        self.assertIn("(it holds no file)", self.said(report, empty)["says"])

    def test_what_is_left_must_still_be_known(self) -> None:
        one, two, _ = self.half_removed()
        self.data(two / "SKILL.md", "Edited meanwhile.\n")
        code, out, err = self.migrate()
        self.assertEqual(code, 2, out)   # kept, and in the way of the link
        self.assertIn("matches no committed version (SKILL.md)", err)
        self.assertTrue((two / "SKILL.md").is_file())


# --- S1: markers the record does not hold ----------------------------------------

class UnrecordedBlockTests(MigrateCase):
    """A marker pair with other text between the markers and no record was
    "written again", and the user's text was gone."""

    MINE = f"# Mine\n\n{BLOCK_START}\nmy own words, kept between the markers\n{BLOCK_END}\n"

    def test_the_pointer_block_is_kept_reported_and_replaced_only_on_request(self) -> None:
        self.data(self.claude_md, self.MINE)
        for more in (("--dry-run",), (), ()):
            code, report, err = self.migrated(*more)
            self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
            self.assertEqual(self.claude_md.read_text(encoding="utf-8"), self.MINE)
            says = self.said(report, self.claude_md)["says"]
            self.assertIn("the install record does not hold the block: it is kept as it is", says)
            self.assertIn("--overwrite-edited", says)
        code, report, err = self.migrated("--overwrite-edited")
        self.assertEqual((code, err), (0, ""))
        self.assertIn(migrate.POINTER, self.claude_md.read_text(encoding="utf-8"))
        self.assertNotIn("my own words", self.claude_md.read_text(encoding="utf-8"))
        self.assertIn(self.MINE.encode("utf-8"), self.backups().values())
        self.undo()
        self.assertEqual(self.claude_md.read_text(encoding="utf-8"), self.MINE)

    def test_a_block_that_is_exactly_setups_is_taken_up_and_no_byte_changes(self) -> None:
        # As after the state directory was removed by hand: the block, and no record of it.
        text = b"# Mine\n\n" + blocks.render(blocks.MARKDOWN, migrate.BLOCK_NAME, migrate.POINTER)
        self.data(self.claude_md, text)
        code, report, err = self.migrated()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.claude_md.read_bytes(), text)
        entry = fileops.read_record(self.roots()).entries["home:.claude/CLAUDE.md"]
        self.assertIn(migrate.BLOCK_NAME, entry["blocks"])


class UnrecordedProjectBlockTests(EntryCase):
    MINE = b'# workflow-setup:start starting-role\nmodel = "my-own"\n# workflow-setup:end starting-role\n\n[features]\nfast = true\n'

    def test_a_projects_block_that_is_not_setups_is_kept(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".codex").mkdir()
        (self.project / CONFIG).write_bytes(self.MINE)
        for more in (("--dry-run",), ()):
            code, out, err = self.render(*self.project_arg, *more)
            self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""), out)
            self.assertEqual((self.project / CONFIG).read_bytes(), self.MINE)
            self.assertIn("the install record does not hold the block: kept as it is", " ".join(out.split()))
        code, out, err = self.render(*self.project_arg, "--overwrite-edited")
        self.assertEqual((code, err), (0, ""), out)
        data = (self.project / CONFIG).read_bytes()
        self.assertNotIn(b"my-own", data)
        self.assertTrue(data.endswith(b"\n[features]\nfast = true\n"))
        backups = [file.read_bytes()
                   for file in (self.project / ".agents" / "workflow-setup" / "backups").rglob("config.toml")]
        self.assertIn(self.MINE, backups)
        # A project's backups are in the project, and none of them in the home.
        self.assertEqual(list((self.home / ".agents" / "workflow-setup").rglob("config.toml")), [])

    def test_doctor_says_what_render_keeps(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".codex").mkdir()
        (self.project / CONFIG).write_bytes(self.MINE)
        (self.project / ".claude").mkdir()
        (self.project / SETTINGS).write_bytes(b'{"agent": "reviewer"}\n')
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, out, err = support.run("doctor", "--only", "missing", "--json", "--home", str(self.home), *self.project_arg)
        details = [found["detail"] for found in json.loads(out)["checks"][0]["findings"] if found["severity"] == "warning"]
        self.assertTrue(any("key agent" in line and "which setup did not set" in line for line in details), details)
        self.assertTrue(any("block starting-role" in line and "kept as it is" in line for line in details), details)


class UnrecordedCodexSettingsTests(SettingsCase):
    """The review's case: the user's own table between setup's markers in
    the Codex ``config.toml``."""

    MINE = ('model = "x"\n# workflow-setup:start codex-settings\n[mcp_servers.mine]\ncommand = "keep-me"\n'
            '# workflow-setup:end codex-settings\n')

    def test_the_users_text_between_the_markers_survives_apply_and_uninstall(self) -> None:
        original = self.user(self.MINE)
        out = self.apply(code=render.EXIT_NEEDS_FLAG)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertIn("the install record does not hold the block: kept as it is", out)
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, _, err = support.run("uninstall", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.config.read_bytes(), original)

    def test_overwrite_edited_replaces_it_after_a_backup(self) -> None:
        original = self.user(self.MINE)
        self.apply("--overwrite-edited")
        self.assertNotIn(b"keep-me", self.config.read_bytes())
        self.assertEqual(self.limit(), 8)
        backups = [file.read_bytes() for file in (self.home / ".agents" / "workflow-setup" / "backups").rglob("config.toml")]
        self.assertEqual(backups, [original])


# --- S13: a project and a loaded role ---------------------------------------------

class LoadedRoleProjectTests(EntryCase):
    """A project override does not reach a loaded role; the report and the
    loaded skill's own text now say so."""

    def test_the_report_names_each_loaded_role_the_project_gives_another_profile(self) -> None:
        self.write(self.project_file, '[roles.lead]\ntier = "frontier"\n')
        user_level = self.home_files_after_plain_render()
        code, report, err = self.report(*self.project_arg)
        self.assertEqual((code, err), (0, ""))
        found = {(one["provider"], one["role"]): one for one in report["project"]["loaded_roles"]}
        self.assertEqual(set(found), {("claude-code", "lead"), ("codex", "lead")})
        claude = found[("claude-code", "lead")]
        self.assertEqual((claude["model"], claude["loaded_model"]), ("fable", "sonnet"))
        # No behaviour change: the home's files are those of a run without the project.
        self.assertEqual(self.home_files(), user_level)
        self.assertFalse(any("skills" in name for name in self.project_files()))
        out = self.with_project()
        line = next(line for line in out.splitlines() if line.startswith("  loaded role lead on claude-code"))
        for words in ("the project's settings give it model fable", "the loaded skill keeps model sonnet",
                      "nothing is generated for it here", f"show roles --project {self.project}"):
            self.assertIn(words, line)

    def home_files_after_plain_render(self) -> dict[str, bytes]:
        self.ok()
        return self.home_files()

    def test_a_project_that_changes_no_loaded_role_gets_no_such_line(self) -> None:
        self.write(self.project_file, '[roles.worker]\ntier = "frontier"\n')
        code, report, _ = self.report(*self.project_arg)
        self.assertEqual((code, report["project"]["loaded_roles"]), (0, []))
        self.assertNotIn("loaded role", self.with_project())

    def test_the_profile_paragraph_says_what_is_true_of_a_project(self) -> None:
        self.ok()
        for name in (".claude/skills/lead/SKILL.md", ".agents/skills/lead/SKILL.md"):
            text = " ".join(self.text(name).split())
            self.assertIn("That profile is the user-level one", text)
            self.assertIn("A project may set another profile for this role", text)
            self.assertIn("show roles --project <the project>", text)
            self.assertNotIn(str(self.root), text)

    def test_a_skill_made_with_the_earlier_format_is_reported_as_drift(self) -> None:
        self.assertEqual(entry.LOADED_SCHEME, "render:loaded-role:2")
        self.ok()
        record = self.manifest_file
        data = json.loads(record.read_text(encoding="utf-8"))
        key = "home:.claude/skills/lead/SKILL.md"
        data["entries"][key]["inputs"] = data["entries"][key]["inputs"].replace("loaded-role:2", "loaded-role:1")
        record.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, out, err = support.run("doctor", "--only", "drift", "--json", "--home", str(self.home))
        findings = json.loads(out)["checks"][0]["findings"]
        self.assertEqual([found["subject"] for found in findings if found["severity"] == "warning"], [key])


# --- S18: which option's absence took a part out ---------------------------------

class AbsentOptionTests(SettingsCase):
    def test_the_change_itself_names_the_option_that_was_not_given(self) -> None:
        self.user('model = "x"\n')
        trees = self.root / "trees"
        self.apply(ROOT, str(trees), DEFAULT)
        code, out, err = self.go(APPLY, "--json")
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        says = {item["name"]: item["says"] for provider in report["providers"] for place in provider["places"]
                for item in place["items"] if item["kind"] == codexsettings.KIND}
        self.assertIn(f"the worktree root {trees} is taken out of the profile, because --worktree-root was not given "
                      "to this run", says[codexsettings.BLOCK])
        gone = {item["name"]: item["says"] for item in report["stale"]}
        self.assertEqual(
            gone[codexsettings.TOP_BLOCK],
            "removed, with nothing else in it: default_permissions is taken out, because "
            "--default-codex-permissions was not given to this run",
        )
        notes = " ".join(report["notes"])
        self.assertIn("this run was given no --worktree-root", notes)
        self.assertIn("this run was given no --default-codex-permissions", notes)

    def test_a_run_with_the_same_options_says_no_such_thing(self) -> None:
        self.user('model = "x"\n')
        trees = self.root / "trees"
        self.apply(ROOT, str(trees), DEFAULT)
        out = self.apply(ROOT, str(trees), DEFAULT)
        self.assertNotIn("was not given to this run", out)
        self.assertNotIn("this run was given no", out)


# --- S8: the environment of a provider's program ---------------------------------

class ChildEnvironmentTests(DoctorCase):
    """``--home`` did not reach the programs ``init`` and ``doctor`` start
    for the model list and the version: they read the real provider home."""

    CALLER = {"HOME": "the-callers-home", "CODEX_HOME": "the-callers-codex", "CLAUDE_CONFIG_DIR": "the-callers-claude",
              **({"USERPROFILE": "the-callers-home"} if os.name == "nt" else {})}

    def setUp(self) -> None:
        super().setUp()
        self.codex_stub = DiscoveryStub(self.stubs / "codex", "codex")
        self.claude_stub = DiscoveryStub(self.stubs / "claude", "claude")
        self.codex_stub.answer(LIVE, fixture("model-list-equal.json"))
        self.codex_stub.answer(VERSION, "codex-cli 0.160.0\n")
        self.claude_stub.answer(VERSION, "2.1.289 (Claude Code)\n")
        search = os.pathsep.join(str(one.bin) for one in (self.codex_stub, self.claude_stub))
        self.at = homes.Host(self.host.side, {**os.environ, **self.CALLER, "PATH": search}, ())

    def assertScratch(self, starts: list[dict]) -> None:
        self.assertTrue(starts)
        for start in starts:
            given = start["environ"]
            self.assertEqual(given["HOME"], str(self.home), start["argv"])
            self.assertEqual(given["CODEX_HOME"], str(self.codex), start["argv"])
            self.assertEqual(given["CLAUDE_CONFIG_DIR"], str(self.claude), start["argv"])
            if os.name == "nt":
                self.assertEqual(given["USERPROFILE"], str(self.home), start["argv"])
            self.assertNotIn("the-callers", json.dumps(given))

    def test_the_model_list_and_the_version_are_asked_in_the_scratch_home(self) -> None:
        self.rendered()
        self.only("models", host=self.at)
        self.assertEqual(self.codex_stub.calls(), [["debug", "models"]])
        self.only("versions", host=self.at)
        self.assertEqual(self.claude_stub.calls(), [["--version"]])
        self.assertScratch([*self.codex_stub.starts(), *self.claude_stub.starts()])

    def test_init_asks_the_model_list_in_the_scratch_home(self) -> None:
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.at)), \
                mock.patch.object(init, "_terminal", return_value=False):
            code, out, err = support.run("init", "--yes", "--dry-run", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.codex_stub.calls(), [["debug", "models"]])
        self.assertScratch(self.codex_stub.starts())

    def test_the_collaboration_skills_doctor_is_started_with_it_too(self) -> None:
        self.rendered()
        self.collab(self.collab_report(("argv", True, "warning", "ok")))
        seen: list[dict] = []
        real = modellist.run_program

        def run_program(argv, environ, timeout):
            seen.append(dict(environ))
            return real(argv, environ, timeout)

        with mock.patch.object(modellist, "run_program", run_program):
            self.only("collaboration-skill", host=self.at)
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0]["HOME"], seen[0]["CODEX_HOME"]), (str(self.home), str(self.codex)))

    def test_one_helper_builds_it_and_the_real_home_gets_the_callers_untouched(self) -> None:
        found = homes.resolve(self.locations(project=False), self.at)
        scratch = homes.child_environment(found)
        self.assertEqual((scratch["HOME"], scratch["CODEX_HOME"], scratch["CLAUDE_CONFIG_DIR"]),
                         (str(self.home), str(self.codex), str(self.claude)))
        self.assertEqual(scratch["PATH"], self.at.environ["PATH"])
        context = doctor.Context(self.locations(project=False), None, self.at)
        self.assertEqual(context.child_environ, scratch)
        self.assertEqual(discovery.child_environment(context), scratch)
        # The real home: the provider finds its home as it always does.
        callers = homes.Host(self.host.side, {"PATH": "x", "CODEX_HOME": str(self.root / "their-codex")}, ())
        real = homes.resolve(Locations(home=self.home, clone=self.clone, real_home=True), callers)
        self.assertFalse(real.scratch)
        self.assertEqual(homes.child_environment(real), dict(callers.environ))
        self.assertIsNot(homes.child_environment(real), callers.environ)


# --- S9: what doctor says of itself ------------------------------------------------

class BannerTests(DoctorCase):
    """The first line said "reads only; nothing is changed" while the
    default checks start provider programs that write into their home."""

    def banner(self, *argv: str) -> str:
        code, out, err = self.run_doctor(*argv)
        self.assertEqual(err, "", out)
        return out.splitlines()[0]

    def test_it_names_the_checks_that_start_a_program_and_how_to_leave_them_out(self) -> None:
        line = self.banner()
        self.assertIn("setup itself writes nothing", line)
        self.assertIn("models, versions, discovery, collaboration-skill", line)
        self.assertIn("may write state of their own into their own home", line)
        self.assertIn("--no-model-list, --no-versions, --skip discovery, --no-collab", line)
        self.assertNotIn("nothing is changed", line)

    def test_a_run_that_starts_none_says_so(self) -> None:
        line = self.banner("--no-model-list", "--no-versions", "--skip", "discovery", "--no-collab")
        self.assertEqual(line, "doctor: setup itself writes nothing, and this run starts no program of a provider")
        self.assertIn("The check versions starts a program", self.banner("--only", "versions"))
        code, report = self.doctor("--only", "sources", "--only", "models")
        self.assertEqual(report["starts_programs"], ["models"])
        self.assertEqual(set(doctor.STARTERS), {"models", "versions", "discovery", "collaboration-skill"})
        self.assertLessEqual(set(doctor.STARTERS), set(doctor.names()))

    def test_a_run_that_saves_its_probes_says_that_it_writes_them(self) -> None:
        probes = self.root / "probes"
        line = self.banner("--only", "discovery", "--save-probe", str(probes))
        self.assertIn(f"setup itself writes nothing but the probe output asked for, into {probes}", line)
        self.assertNotIn("probe output", self.banner("--only", "sources", "--save-probe", str(probes)))

    def test_what_codex_writes_for_itself_is_no_finding(self) -> None:
        self.rendered()
        # Codex's bundled skills, as a start of the program leaves them.
        system = self.codex / "skills" / ".system"
        for name in ("alpha", "skill-creator"):
            (system / name).mkdir(parents=True)
            (system / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Codex's own.\n---\n", encoding="utf-8")
        (system / ".git").mkdir()
        (self.codex / "installation_id").write_text("an id\n", encoding="utf-8")
        for name in ("duplicate-skills", "other-clones", "v1", "missing", "links"):
            with self.subTest(name):
                code, findings = self.only(name)
                self.assertEqual(code, 0)
                self.assertQuiet(findings)
                self.assertFalse(any(".system" in found["detail"] for found in findings), findings)


# --- S7: a FIFO where a file is read ----------------------------------------------

@unittest.skipUnless(POSIX and hasattr(os, "mkfifo"), "needs a FIFO")
class FifoTests(DoctorCase):
    """A FIFO at the Codex ``config.toml`` or at the list of v1 hashes hung
    ``doctor`` and every dry run: it was opened, and no one writes to it."""

    def soon(self, call):
        """What ``call`` returns, or a failure when it does not return."""
        result: dict = {}

        def run() -> None:
            try:
                result["value"] = call()
            except BaseException as exc:   # handed to the test's own thread
                result["error"] = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(30)
        if thread.is_alive():
            self.fail("the call did not return: it waits on the FIFO")
        if "error" in result:
            raise result["error"]
        return result["value"]

    def test_the_codex_config(self) -> None:
        os.mkfifo(self.codex / "config.toml")
        code, findings = self.soon(lambda: self.only("codex-settings"))
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, "config.toml", "is not a file that can be read")
        code, out, err = self.soon(lambda: self.render("--dry-run", "--no-roles", "--apply-codex-settings"))
        self.assertEqual(code, 2)
        with self.assertRaises(SetupError):
            self.soon(lambda: codexsettings._bytes(self.codex / "config.toml"))

    def test_the_list_of_v1_hashes(self) -> None:
        fifo = self.root / "v1-known-hashes.json"
        os.mkfifo(fifo)
        with self.assertRaises(SetupError) as caught:
            self.soon(lambda: migrate.load_known(fifo))
        self.assertIn("not a file", str(caught.exception))
        with mock.patch.object(migrate, "KNOWN_FILE", fifo), mock.patch.dict(migrate._cache, clear=True):
            code, findings = self.soon(lambda: self.only("v1"))
            self.assertEqual(code, 1)
            self.assertFinding(findings, doctor.ERROR, "the check v1 could not be made", "not a file")
            code, out, err = self.soon(lambda: self.render("--dry-run", "--no-roles", "--migrate-v1"))
            self.assertEqual(code, 2)
            one_line(self, err, "v1-known-hashes.json", "not a file")


# --- Minor: the script that builds the hash table -----------------------------------

class HashScriptTests(support.ScratchCase):
    def test_a_run_of_the_script_leaves_no_bytecode_in_the_clone(self) -> None:
        import subprocess
        import sys

        copy = self.root / "copy" / "tools" / "setup"
        shutil.copytree(support.SETUP, copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        environment = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
        done = subprocess.run([sys.executable, str(copy / "build_v1_hashes.py"), "--help"], env=environment,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([str(path) for path in copy.rglob("__pycache__")], [])

    def test_a_git_command_that_does_not_finish_is_an_error_of_one_line(self) -> None:
        import subprocess
        from test_migrate import BUILDER

        self.assertGreater(BUILDER.GIT_TIMEOUT, 0)
        seen: dict = {}

        def run(argv, **options):
            seen.update(options)
            raise subprocess.TimeoutExpired(argv, options["timeout"])

        with mock.patch.object(BUILDER.subprocess, "run", run):
            with self.assertRaises(BUILDER.BuildError) as caught:
                BUILDER.git(self.root, "rev-list", "HEAD")
        self.assertEqual(seen["timeout"], BUILDER.GIT_TIMEOUT)
        self.assertIn("did not finish within", str(caught.exception))
        self.assertNotIn("\n", str(caught.exception))


# --- S14: a removal by the committed table ----------------------------------------

class CommittedTableTests(MigrateCase):
    """Every removal test patched ``migrate.known``. This one reads the
    committed ``v1-known-hashes.json`` and needs no git history: its v1
    file is the rule as the working tree holds it, whose committed versions
    the table lists."""

    def test_a_copy_of_a_committed_version_is_removed_by_the_committed_table(self) -> None:
        self.known_patch.stop()
        self.addCleanup(migrate._cache.clear)
        migrate._cache.clear()
        data = (support.REPOSITORY / migrate.BASH_RULE_NOW).read_bytes()
        table = migrate.known()
        self.assertIsNot(table, None)
        self.assertGreater(len(table.files), 10)
        if not table.matches(migrate.V1_RULES[migrate.BASH_RULE], fsio.sha256(data)):
            self.skipTest("the rule was changed since the table was built; build_v1_hashes.py builds it again")
        for form in (data.replace(b"\r\n", b"\n"), data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")):
            with self.subTest(crlf=b"\r\n" in form):
                copy = self.data(self.rules / migrate.BASH_RULE, form)
                edited = self.data(self.rules / "prd-implementation.md", form)   # not a version of that file
                code, report, err = self.migrated()
                self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
                self.assertEqual(self.said(report, copy)["status"], migrate.REMOVE)
                self.assertEqual(self.said(report, edited)["status"], migrate.KEPT)
                self.assertNothingAt(copy)
                self.assertEqual(edited.read_bytes(), form)
                self.assertIn(form, self.backups().values())
                self.undo()
                self.assertEqual(copy.read_bytes(), form)
                copy.unlink()
                edited.unlink()


# --- Minor: what a failed uninstall says ------------------------------------------

@unittest.skipUnless(support.can_lock_directories(), "needs a directory this process cannot write")
class UninstallSaysTests(EntryCase):
    """With a state directory that cannot be written, ``uninstall`` said
    "part way" when nothing had been done."""

    def test_a_run_that_fails_before_its_first_change_says_that_nothing_was_changed(self) -> None:
        self.ok()
        state = self.home / ".agents" / "workflow-setup"
        before = tree(self.claude)
        os.chmod(state, 0o555)
        self.addCleanup(os.chmod, state, 0o755)
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, out, err = support.run("uninstall", "--home", str(self.home))
        os.chmod(state, 0o755)
        self.assertEqual(code, 2, out)
        self.assertEqual(tree(self.claude), before)
        self.assertEqual(out.splitlines()[-1], "stopped: 1 error; nothing was changed")
        self.assertNotIn("part way", out)

    def test_a_run_that_did_change_something_is_still_part_way(self) -> None:
        self.ok()
        found = homes.resolve(Locations(home=self.home, clone=self.clone), self.host)
        with mock.patch.object(uninstall, "_touched", return_value=True), \
                mock.patch.object(fileops.Plan, "run", side_effect=SetupError("x: 3 of 9 changes were made")):
            outcome = uninstall.execute(found)
        self.assertEqual(outcome.report["summary"], "stopped: 1 error, part way; the error says what was done")
        record = fileops.read_record(found.roots())
        self.assertFalse(uninstall._touched(found.roots(), False, dict(record.home.entries)))
        self.assertTrue(uninstall._touched(found.roots(), False, {}))


if __name__ == "__main__":
    unittest.main()
