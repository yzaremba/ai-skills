"""Command-level tests of the second review's findings that no other test
file holds: a link to a credentials file at a v1 place (7), the same
``--remove-stale`` twice (10), and ``--clone-was`` (2).

Run from the repository root:
    python -B -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

import support
from fileops_support import SYMLINKS
from test_migrate import EDITED, MigrateCase, tree
from wfsetup import fileops, render, uninstall
from wfsetup.manifest import Roots


@unittest.skipUnless(SYMLINKS, "needs a symlink")
class CredentialsLinkTests(MigrateCase):
    """Setup makes no link to a credentials file, so it could not put one
    back: it never removes one either."""

    def plant(self) -> Path:
        self.data(self.claude / ".credentials.json", '{"token": "SECRET"}\n')
        self.rules.mkdir()
        link = self.rules / "prd-implementation.md"
        os.symlink("../.credentials.json", link)
        return link

    def test_it_is_kept_and_reported_without_the_option(self) -> None:
        link = self.plant()
        code, report, err = self.migrated()
        self.assertEqual(err, "")
        item = self.said(report, link)
        self.assertEqual(item["status"], "kept")
        self.assertIn("a credentials file", item["says"])
        self.assertEqual(os.readlink(link), "../.credentials.json")
        self.assertNotIn("SECRET", str(report))

    def test_the_option_does_not_remove_it_and_the_way_back_is_whole(self) -> None:
        link = self.plant()
        before = tree(self.home)
        code, out, err = self.migrate("--remove-stale", str(link))
        self.assertEqual(code, 2, out)
        self.assertIn("a link to a credentials file, which setup neither removes nor makes", err)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertNotIn("SECRET", out + err)
        self.assertEqual(tree(self.home), before)            # refused before anything was changed
        code, _, _ = self.migrated()                           # the rest of the migration goes through
        self.assertEqual(os.readlink(link), "../.credentials.json")
        self.assertEqual(self.backups(), {})
        code, out, err = support.run("uninstall", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)            # and can be undone to the end
        self.assertEqual(tree(self.home), before)

    def test_a_copy_that_holds_such_a_link_is_not_removed(self) -> None:
        self.data(self.claude / ".credentials.json", "SECRET\n")
        copy = self.old_skills / "self-reflection"
        self.data(copy / "SKILL.md", EDITED)
        os.symlink("../../../.claude/.credentials.json", copy / "token")
        before = tree(self.home)
        code, out, err = self.migrate("--remove-stale", str(copy))
        self.assertEqual(code, 2, out)
        self.assertIn("a link to a credentials file", err)
        self.assertEqual(tree(self.home), before)


class RemoveStaleTwiceTests(MigrateCase):
    def test_the_same_command_a_second_time_is_satisfied(self) -> None:
        copy = self.claude_skills / "self-reflection"
        self.data(copy / "SKILL.md", EDITED)
        self.data(copy / "notes.md", "the user's own\n")
        code, out, err = self.migrate("--remove-stale", str(copy))
        self.assertEqual((code, err), (0, ""), out)
        after = tree(self.home)
        code, out, err = self.migrate("--remove-stale", str(copy))   # the path holds setup's own link now
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("nothing to remove; setup's own entry is there", out)
        self.assertEqual(tree(self.home), after)                     # and nothing was written
        code, out, err = self.migrate("--remove-stale", str(copy), "--dry-run")
        self.assertEqual((code, err), (0, ""), out)

    def test_a_path_that_holds_something_else_is_still_refused(self) -> None:
        other = self.data(self.claude_skills / "self-reflection" / "SKILL.md", EDITED).parent
        self.migrate("--remove-stale", str(other))
        mine = self.data(self.rules / "prd-implementation.md" / "x", "a directory where a rule file would be\n").parent
        code, out, err = self.migrate("--remove-stale", str(mine))
        self.assertEqual(code, 2, out)
        self.assertIn("it is yours to move away", err)


class CloneWasTests(unittest.TestCase):
    """``uninstall --clone-was DIR`` names one more place a link of
    setup's may lead to. The clone stays the clone, and stays barred."""

    class Found:
        def __init__(self, roots: Roots) -> None:
            self._roots = roots

        def roots(self) -> Roots:
            return self._roots

    def test_the_clone_stays_the_one_setup_runs_from(self) -> None:
        base = Path(os.path.abspath(os.sep)) / "scratch"
        roots = Roots(base / "home", None, base / "clone")
        was = base / "where-it-was"
        made = uninstall.roots_of(self.Found(roots), was)
        self.assertEqual(made.clone, roots.clone)
        self.assertEqual(made.clone_was, was)
        self.assertIn(roots.clone, made.confinement(False)[1])
        self.assertIs(uninstall.roots_of(self.Found(roots)), roots)



class CloneWasCommandTests(MigrateCase):
    def test_the_command_writes_nothing_into_the_clone_with_the_option(self) -> None:
        code, out, err = self.migrate()
        self.assertEqual((code, err), (0, ""), out)
        self.assertTrue(fileops.read_record(self.roots()).entries)
        before = tree(self.clone)
        for was in (self.root / "nowhere", self.clone, self.home):
            code, out, err = support.run("uninstall", "--clone-was", str(was), "--dry-run", "--home", str(self.home))
            self.assertIn(code, (0, 3), err)
            self.assertEqual(tree(self.clone), before)
        code, out, err = support.run("uninstall", "--clone-was", str(self.root / "nowhere"), "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(tree(self.clone), before)
        self.assertFalse((self.home / ".agents" / "workflow-setup").exists())
        self.assertEqual(render.EXIT_NEEDS_FLAG, 3)


class MinorTests(support.ScratchCase):
    def test_the_worktree_root_is_not_the_home_by_its_absolute_path(self) -> None:
        from wfsetup import codexsettings
        from wfsetup.errors import SetupError

        own = os.path.expanduser("~")
        for text in (own, own + os.sep, os.path.join(own, "x", "..")):
            with self.assertRaises(SetupError) as caught:
                codexsettings.worktree_root(text)
            self.assertIn("the home directory itself", caught.exception.lines[0])
        self.assertEqual(codexsettings.worktree_root(os.path.join(own, "wt")), os.path.join(own, "wt"))

    def test_a_directory_setting_with_a_control_character_is_refused(self) -> None:
        for flag in ("--docs-dir", "--memory-dir"):
            for value in ("a\nb", "a\x1bb", "a\u2028b"):
                code, out, err = support.run("init", "--yes", "--user", flag, value, "--home", str(self.home))
                self.assertEqual(code, 2, out)
                self.assertEqual(len(err.strip().splitlines()), 1, err)
                self.assertIn("control character", err)
        self.assertFalse((self.home / ".agents").exists())

    def test_json_that_is_no_json_value_or_no_text_is_refused(self) -> None:
        from wfsetup import jsonkeys

        for data in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}', b'{"agent": "\\ud800"}'):
            with self.assertRaises(jsonkeys.Refusal):
                jsonkeys.parse(data)
        self.assertEqual(jsonkeys.parse(b'{"a": "\\ud83d\\ude00"}')[1], {"a": "\U0001f600"})

    def test_an_uninstall_with_nothing_to_do_touches_no_directory(self) -> None:
        project = self.root / "project"
        project.mkdir(exist_ok=True)
        (self.home / ".agents" / "workflow-setup").mkdir(parents=True)
        (project / ".agents").mkdir(exist_ok=True)
        watched = [self.home, self.home / ".agents", project, project / ".agents"]
        before = [os.stat(path).st_mtime_ns for path in watched]
        code, out, err = support.run("uninstall", "--project", str(project), "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual([os.stat(path).st_mtime_ns for path in watched], before)
        self.assertTrue((self.home / ".agents" / "workflow-setup").is_dir())   # the home's, not this command's


if __name__ == "__main__":
    unittest.main()
