"""Tests for ``render``: the skills and the rules, linked into scratch homes.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

Every home is a scratch directory and the clone is the clean fixture clone
of ``test_validate.TreeCase``: two shared skills (alpha, beta), a skill for
Claude Code only (solo), a skill with a setup of its own, and one rule. The
machine is a ``Host`` made by hand, with an empty PATH, so a provider counts
as installed only when its scratch home exists. Links are symlinks on Linux
and junctions on Windows.
"""
from __future__ import annotations

# The tests directory is on sys.path however this file is run (by path, by dotted name, discover, run.py).
import sys as _sys
from pathlib import Path as _Path
_sys.path[:0] = {str(_Path(__file__).resolve().parent)} - set(_sys.path)

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

import provider_stub
import support
from fileops_support import POSIX, SYMLINKS
from test_validate import TreeCase
from wfsetup import blocks, fileops, fsio, gitrepo, homes, locations, paths, render
from wfsetup.locations import Locations

WINDOWS = os.name == "nt"
LINKS = SYMLINKS or WINDOWS
SIDE = homes.WINDOWS if WINDOWS else homes.LINUX
USER_TEXT = "the user's own text\n"


def tree(root: Path) -> dict[str, tuple]:
    """Every path below ``root``: a link with its text (a junction too), a
    directory, or a file with its bytes. A link is not followed."""
    found: dict[str, tuple] = {}
    for directory, names, files in os.walk(root):
        for name in [*names, *files]:
            path = Path(directory) / name
            seen = fsio.look(path)
            relative = path.relative_to(root).as_posix()
            if seen.kind == fsio.LINK:
                found[relative] = ("link", os.path.normcase(seen.target or ""))
            elif seen.kind == fsio.DIRECTORY:
                found[relative] = ("directory",)
            else:
                found[relative] = ("file", path.read_bytes())
    return found


class RenderCase(TreeCase):
    """Both providers installed in a scratch home, by their homes alone."""

    def setUp(self) -> None:
        super().setUp()
        if not LINKS:
            self.skipTest("this system makes neither a symlink nor a junction")
        self.claude = self.home / ".claude"
        self.codex = self.home / ".codex"
        self.claude.mkdir()
        self.codex.mkdir()
        self.claude_skills = self.claude / "skills"
        self.codex_skills = self.home / ".agents" / "skills"
        self.rules = self.claude / "rules"
        self.manifest_file = self.home / ".agents" / "workflow-setup" / "manifest.json"
        self.host = homes.Host(SIDE, {"PATH": ""}, ())
        if not self.ROLES_ON:
            self.write(self.defaults_file, support.NO_ROLES_INSTALL + support.FIXTURE_DEFAULTS)

    # These tests are about the links. The fixture clone has roles and no
    # dictionary for either provider, so the shipped ``install`` here lacks
    # ``roles`` and every run asks for no role definition; ``test_definitions``
    # covers those.
    ROLES_ON = False

    ROLES_LEFT_OUT = support.NO_ROLES_INSTALL

    def leave_clone(self, *names: str) -> None:
        """A skill or rule gone from the clone, and from the shipped ``install``, as one change."""
        for name in names:
            shutil.rmtree(self.clone / ("rules" if name == "sample" else "") / name)
        kept = [unit for unit in support.TREE_UNITS.replace('"', "").split(", ") if unit not in names]
        listed = ", ".join(f'"{unit}"' for unit in kept)
        self.write(self.defaults_file, f"install = [{listed}]\n" + support.FIXTURE_DEFAULTS)

    def roles_off(self) -> None:
        """The home's ``install`` without ``roles``, above what its settings file already holds."""
        self.roles_on()
        text = self.user_file.read_text(encoding="utf-8") if self.user_file.exists() else ""
        self.write(self.user_file, self.ROLES_LEFT_OUT + text)

    def roles_on(self) -> None:
        """Back to the shipped ``install``, which holds ``roles``."""
        if self.user_file.exists():
            text = self.user_file.read_text(encoding="utf-8").removeprefix(self.ROLES_LEFT_OUT)
            if text:
                self.write(self.user_file, text)
            else:
                self.user_file.unlink()

    def render(self, *argv: str, host: homes.Host | None = None, home: bool = True) -> tuple[int, str, str]:
        host = host or self.host
        places = ["--home", str(self.home)] if home else []
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: host)):
            return support.run("render", *argv, *places)

    def report(self, *argv: str, **how) -> tuple[int, dict, str]:
        code, out, err = self.render("--json", *argv, **how)
        return code, json.loads(out), err

    def keep(self, path: Path, text: str = USER_TEXT) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def assertLinked(self, link: Path, target: Path) -> None:
        seen = fsio.look(link)
        self.assertEqual(seen.kind, fsio.LINK, link)
        self.assertTrue(fsio.same_target(seen.target or "", str(target)), (seen.target, str(target)))

    def assertNothingAt(self, path: Path) -> None:
        self.assertEqual(fsio.look(path).kind, fsio.ABSENT, path)

    def items(self, report: dict, provider: str, place: str) -> dict[str, str]:
        for found in report["providers"]:
            if found["name"] == provider:
                for where in found["places"]:
                    if where["name"] == place:
                        return {item["name"]: item["status"] for item in where["items"]}
        return {}

    def roots(self):
        return homes.resolve(Locations(home=self.home, clone=self.clone), self.host).roots()


class LinksCase(RenderCase):
    def test_each_provider_gets_the_skills_that_name_it(self) -> None:
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        for name in ("alpha", "beta", "solo"):
            self.assertLinked(self.claude_skills / name, self.clone / name)
        for name in ("alpha", "beta"):
            self.assertLinked(self.codex_skills / name, self.clone / name)
        self.assertEqual(sorted(os.listdir(self.claude_skills)), ["alpha", "beta", "solo"])
        self.assertEqual(sorted(os.listdir(self.codex_skills)), ["alpha", "beta"])
        # The skill is read through the link.
        self.assertTrue((self.claude_skills / "alpha" / "SKILL.md").read_text(encoding="utf-8").startswith("---\n"))
        self.assertIn("done: 6 links created, 0 removed", out.splitlines()[-1])

    def test_a_skill_for_one_provider_is_not_linked_for_the_other(self) -> None:
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertNothingAt(self.codex_skills / "solo")
        self.assertEqual(self.items(report, "claude-code", "skills")["solo"], render.CREATE)
        self.assertNotIn("solo", self.items(report, "codex", "skills"))

    def test_the_rule_directory_is_linked_for_claude_code_only(self) -> None:
        self.put("rules/second/second.md", "Another rule.\n")
        self.put("rules/loose.md", "Not a rule: a rule is a directory.\n")
        self.write(self.defaults_file, 'install = ["alpha", "beta", "solo", "sample", "second"]\n' + support.FIXTURE_DEFAULTS)
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertLinked(self.rules / "sample", self.clone / "rules" / "sample")
        self.assertLinked(self.rules / "second", self.clone / "rules" / "second")
        self.assertEqual(sorted(os.listdir(self.rules)), ["sample", "second"])
        self.assertEqual((self.rules / "sample" / "sample.md").read_bytes(), (self.clone / "rules/sample/sample.md").read_bytes())
        self.assertEqual(self.items(report, "codex", "rules"), {})
        self.assertNothingAt(self.codex / "rules")

    def test_the_collaboration_skill_is_skipped_whatever_is_at_its_path(self) -> None:
        mine = self.keep(self.claude_skills / "multiagent-collab" / "SKILL.md")
        other = self.keep(self.codex_skills / "multiagent-collab")  # a file where a skill would be
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(mine.read_text(encoding="utf-8"), USER_TEXT)
        self.assertEqual(other.read_text(encoding="utf-8"), USER_TEXT)
        self.assertEqual(out.count("multiagent-collab: skipped: managed by its own setup"), 2)
        self.assertNotIn("multiagent-collab", self.manifest_file.read_text(encoding="utf-8"))

    def test_the_collaboration_skill_is_not_created_where_nothing_is(self) -> None:
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertNothingAt(self.claude_skills / "multiagent-collab")
        self.assertNothingAt(self.codex_skills / "multiagent-collab")
        self.assertEqual(self.items(report, "claude-code", "skills")["multiagent-collab"], render.SKIPPED)
        self.assertEqual(self.items(report, "codex", "skills")["multiagent-collab"], render.SKIPPED)

    def test_a_provider_that_is_not_installed_gets_nothing(self) -> None:
        self.codex.rmdir()
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.codex_skills)
        self.assertNothingAt(self.codex)
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        line = next(line for line in out.splitlines() if line.startswith("codex:"))
        self.assertIn("not installed", line)
        self.assertIn("nothing is installed for it", line)

    def test_a_program_on_path_makes_a_provider_installed(self) -> None:
        from test_homes import stub_program
        self.codex.rmdir()
        stub_program(self.root / "bin", "codex")
        code, _, _ = self.render(host=homes.Host(SIDE, {"PATH": str(self.root / "bin")}, ()))
        self.assertEqual(code, 0)
        self.assertLinked(self.codex_skills / "alpha", self.clone / "alpha")

    def test_the_text_of_the_report(self) -> None:
        code, out, _ = self.render("--dry-run")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "dry run: nothing is changed")
        self.assertIn(f"clone: {self.clone}", lines)
        self.assertIn(f"claude-code: {self.claude}", lines)
        self.assertIn(f"  skills: {self.claude_skills}", lines)
        self.assertIn("    alpha: create: link to clone:alpha", lines)
        self.assertIn(f"  rules: {self.rules}", lines)
        self.assertIn("    sample: create: link to clone:rules/sample", lines)
        self.assertIn(f"  skills: {self.codex_skills}", lines)
        self.assertIn("plan:", lines)
        self.assertIn("  create link home:.claude/skills/alpha -> clone:alpha", lines)
        self.assertIn("  create link home:.agents/skills/beta -> clone:beta", lines)
        self.assertEqual(
            lines[-1],
            "dry run: would create 6 links and remove 0; nothing was written; 2 skipped (each is listed as skipped, "
            "with the reason)",
        )

    def test_help_states_the_exit_codes_and_the_cowork_limit(self) -> None:
        code, out, _ = support.run("render", "--help")
        flat = " ".join(out.split())
        self.assertEqual(code, 0)
        for option in ("--dry-run", "--follow-config-symlinks", "--home", "--project", "--json"):
            self.assertIn(option, flat)
        self.assertIn("A Cowork session on the desktop does not load a linked user-level rule", flat)
        self.assertIn("3 when the rest was done", flat)
        self.assertIn("2 on an error or a conflict", flat)


class IdempotenceCase(RenderCase):
    def test_a_second_run_plans_nothing_and_writes_nothing(self) -> None:
        self.assertEqual(self.render()[0], 0)
        before = tree(self.root)
        code, report, err = self.report()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.root), before)
        self.assertEqual(report["plan"], [])
        self.assertFalse(report["changed"])
        self.assertEqual(report["counts"]["create"], 0)
        self.assertEqual(report["counts"]["up_to_date"], 6)
        self.assertEqual(self.items(report, "claude-code", "skills")["alpha"], render.UP_TO_DATE)

        code, out, _ = self.render()
        self.assertEqual(code, 0)
        self.assertEqual(tree(self.root), before)
        self.assertIn(f"  {fileops.UP_TO_DATE}", out.splitlines())
        self.assertTrue(out.splitlines()[-1].startswith(f"{fileops.UP_TO_DATE}; nothing was written"))

    def test_a_dry_run_changes_nothing(self) -> None:
        self.keep(self.claude / "CLAUDE.md")
        before = tree(self.root)
        code, report, err = self.report("--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.root), before)
        self.assertTrue(report["dry_run"] and report["changed"] and not report["applied"])
        self.assertIn("create link home:.claude/rules/sample -> clone:rules/sample", report["plan"])
        self.assertNothingAt(self.home / ".agents")

    def test_a_dry_run_after_a_run_says_there_is_nothing_to_do(self) -> None:
        self.render()
        before = tree(self.root)
        code, out, _ = self.render("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(tree(self.root), before)
        self.assertIn(fileops.UP_TO_DATE, out)


class ConflictCase(RenderCase):
    def refused(self, *expected: str) -> str:
        before = tree(self.root)
        for argv in (("--dry-run",), ()):
            code, out, err = self.render(*argv)
            self.assertEqual(code, 2, out)
            self.assertEqual(tree(self.root), before)
            for text in expected:
                self.assertIn(text, err)
            self.assertIn("stopped: ", out.splitlines()[-1])
            self.assertIn("nothing was written", out.splitlines()[-1])
        return err

    def test_a_plain_directory_stops_the_run_for_both_providers(self) -> None:
        mine = self.keep(self.codex_skills / "beta" / "SKILL.md")
        err = self.refused(f"{self.codex_skills / 'beta'}: a directory of its own, not a link, and setup did not make it")
        self.assertEqual(mine.read_text(encoding="utf-8"), USER_TEXT)
        # Nothing for Claude Code either, and no record.
        self.assertNothingAt(self.claude_skills)
        self.assertNothingAt(self.manifest_file)
        self.assertEqual(len([line for line in err.splitlines() if str(self.codex_skills) in line]), 1)

    def test_a_plain_file_is_a_conflict(self) -> None:
        self.keep(self.claude_skills / "alpha")
        self.refused(f"{self.claude_skills / 'alpha'}: a file of its own, not a link")

    def test_a_foreign_link_is_a_conflict_that_names_its_target(self) -> None:
        theirs = self.root / "another-home" / "skills" / "solo"
        self.keep(theirs / "SKILL.md")
        self.claude_skills.mkdir()
        fsio.make_link(str(theirs), self.claude_skills / "solo", True)
        err = self.refused(f"{self.claude_skills / 'solo'}: a link to elsewhere on this side: ")
        self.assertIn("solo, and setup did not make it", err)
        self.assertIn(theirs.name, err)
        self.assertEqual((theirs / "SKILL.md").read_text(encoding="utf-8"), USER_TEXT)

    def test_a_rule_in_the_way_is_a_conflict(self) -> None:
        self.keep(self.rules / "sample" / "sample.md")
        self.refused(f"{self.rules / 'sample'}: a directory of its own, not a link")

    def test_every_conflict_has_a_line(self) -> None:
        self.keep(self.claude_skills / "alpha" / "SKILL.md")
        self.keep(self.codex_skills / "alpha" / "SKILL.md")
        err = self.refused(str(self.claude_skills / "alpha"), str(self.codex_skills / "alpha"))
        self.assertEqual(len(err.splitlines()), 2)

    def test_the_json_report_lists_the_conflicts(self) -> None:
        self.keep(self.claude_skills / "alpha" / "SKILL.md")
        code, report, err = self.report()
        self.assertEqual(code, 2)
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(report["counts"]["conflict"], 1)
        self.assertEqual(self.items(report, "claude-code", "skills")["alpha"], render.CONFLICT)
        self.assertEqual(report["plan"], [])
        self.assertEqual(len(report["errors"]), 1)
        self.assertIn(report["errors"][0], err)

    def test_setups_own_link_pointed_elsewhere_is_a_conflict(self) -> None:
        self.assertEqual(self.render()[0], 0)
        elsewhere = self.root / "elsewhere"
        self.keep(elsewhere / "SKILL.md")
        fsio.remove_link(self.claude_skills / "alpha")
        fsio.make_link(str(elsewhere), self.claude_skills / "alpha", True)
        self.refused(f"{self.claude_skills / 'alpha'}: ", "it was changed since")
        self.assertLinked(self.claude_skills / "alpha", elsewhere)

    def test_a_link_removed_by_hand_is_made_again(self) -> None:
        self.render()
        fsio.remove_link(self.claude_skills / "alpha")
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(report["plan"], ["create link home:.claude/skills/alpha -> clone:alpha"])
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")


@unittest.skipUnless(SYMLINKS and POSIX, "the view from WSL is rebuilt from symlinks on a POSIX file system")
class OtherSideCase(RenderCase):
    """As in ``test_homes.TwoSidesCase``: ``drive`` stands in for the
    Windows drive, and the host says it is one."""

    def setUp(self) -> None:
        super().setUp()
        self.drive = self.root / "drive"
        self.win = self.drive / "Users" / "someone" / ".claude"
        self.keep(self.win / "rules" / "a-rule.md")
        self.keep(self.win / "skills" / "solo" / "SKILL.md")
        os.symlink(str(self.win / "rules"), self.rules)
        self.wsl = homes.Host(homes.WSL, {"PATH": ""}, (str(self.drive),))

    def test_a_place_of_the_other_side_is_skipped_and_reported(self) -> None:
        drive_before = tree(self.drive)
        code, out, err = self.render(host=self.wsl)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.drive), drive_before)
        self.assertEqual(os.readlink(self.rules), str(self.win / "rules"))
        lines = out.splitlines()
        self.assertIn(
            f"    skipped: other side (windows): a link to {self.win / 'rules'}; skipped here, the windows side owns it",
            lines,
        )
        self.assertIn("    not linked here: sample", lines)
        # The rest of the run is done.
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertLinked(self.codex_skills / "beta", self.clone / "beta")
        self.assertNotIn("rules", self.manifest_file.read_text(encoding="utf-8"))

    def test_the_json_report_says_whose_the_place_is(self) -> None:
        code, report, _ = self.report("--dry-run", host=self.wsl)
        self.assertEqual(code, 0)
        self.assertEqual(self.items(report, "claude-code", "rules"), {"sample": render.SKIPPED})
        place = next(
            place for provider in report["providers"] if provider["name"] == "claude-code"
            for place in provider["places"] if place["name"] == "rules"
        )
        self.assertEqual(place["standing"], homes.OTHER_SIDE)
        self.assertEqual(report["counts"]["needs_flag"], 0)

    def test_the_flag_does_not_make_the_other_sides_place_this_runs(self) -> None:
        drive_before = tree(self.drive)
        code, _, _ = self.render("--follow-config-symlinks", host=self.wsl)
        self.assertEqual(code, 0)
        self.assertEqual(tree(self.drive), drive_before)

    def test_a_link_to_the_other_sides_copy_is_a_conflict(self) -> None:
        self.claude_skills.mkdir()
        os.symlink(str(self.win / "skills" / "solo"), self.claude_skills / "solo")
        before = tree(self.root)
        code, out, err = self.render(host=self.wsl)
        self.assertEqual(code, 2)
        self.assertEqual(tree(self.root), before)
        self.assertIn(
            f"{self.claude_skills / 'solo'}: a link to the other side (windows): {self.win / 'skills' / 'solo'}, "
            "and setup did not make it",
            err,
        )
        self.assertIn("    solo: conflict: a link to the other side (windows)", out)


class SharedPlaceCase(RenderCase):
    """The rules place is a link to a directory elsewhere on this side,
    inside the home (a directory of dotfiles): a run may write there, when
    it is told to follow the link."""

    def setUp(self) -> None:
        super().setUp()
        self.elsewhere = self.home / "dotfiles" / "rules"
        self.keep(self.elsewhere / "theirs.md")
        fsio.make_link(str(self.elsewhere), self.rules, True)

    def test_without_the_flag_it_is_skipped_and_the_exit_code_says_so(self) -> None:
        code, out, err = self.render()
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        self.assertEqual(code, 3)
        self.assertEqual(os.listdir(self.elsewhere), ["theirs.md"])
        # The run was not failed for that alone.
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertLinked(self.codex_skills / "alpha", self.clone / "alpha")
        flat = " ".join(out.split())
        self.assertIn("skipped, needs --follow-config-symlinks: shared, on this side: a link to", flat)
        self.assertIn("give --follow-config-symlinks to write there", flat)
        self.assertIn("not linked here: sample", flat)
        self.assertIn("1 skipped that --follow-config-symlinks would write", out.splitlines()[-1])

    def test_the_code_is_the_same_when_nothing_else_is_left_to_do(self) -> None:
        self.render()
        before = tree(self.root)
        code, report, _ = self.report()
        self.assertEqual(code, 3)
        self.assertEqual(report["plan"], [])
        self.assertEqual(report["counts"]["needs_flag"], 1)
        self.assertEqual(tree(self.root), before)
        self.assertEqual(self.render("--dry-run")[0], 3)

    def test_with_the_flag_it_is_written_where_the_link_leads(self) -> None:
        code, out, err = self.render("--follow-config-symlinks")
        self.assertEqual((code, err), (0, ""))
        self.assertLinked(self.elsewhere / "sample", self.clone / "rules" / "sample")
        self.assertEqual(sorted(os.listdir(self.elsewhere)), ["sample", "theirs.md"])
        self.assertEqual(fsio.look(self.rules).kind, fsio.LINK)  # the place stays a link
        before = tree(self.root)
        code, report, _ = self.report("--follow-config-symlinks")
        self.assertEqual((code, report["plan"]), (0, []))
        self.assertEqual(tree(self.root), before)


class PlaceOutOfTheHomeCase(RenderCase):
    """The rules place is a link to a directory outside the home: another
    home's. No option makes a run write there."""

    def setUp(self) -> None:
        super().setUp()
        self.outside = self.root / "another-home"
        self.elsewhere = self.outside / "rules"
        self.keep(self.elsewhere / "theirs.md")
        self.keep(self.outside / ".agents" / "workflow.toml", "# theirs\n")
        fsio.make_link(str(self.elsewhere), self.rules, True)
        self.held = tree(self.outside)

    def test_it_is_skipped_with_and_without_the_flag_and_is_not_changed_by_a_byte(self) -> None:
        for argv in ((), ("--dry-run",), ("--follow-config-symlinks", "--dry-run"), ("--follow-config-symlinks",)):
            with self.subTest(argv=argv):
                code, out, err = self.render(*argv)
                # No option would write there, so the code does not ask for one.
                self.assertEqual((code, err), (0, ""), out)
                self.assertEqual(tree(self.outside), self.held)
                flat = " ".join(out.split())
                self.assertIn(f"skipped: a link to {self.elsewhere}, which leads out of the directories this run may "
                              "write to: skipped, whatever the options", flat)
                self.assertIn("it leads out of the home and the project of this run", flat)
                self.assertIn("not linked here: sample", flat)
                self.assertNotIn("give --follow-config-symlinks", flat)
                self.assertNotIn("--follow-config-symlinks would write", out.splitlines()[-1])
                self.assertLinked(self.rules, self.elsewhere)   # the place stays the user's link
        # The run was not failed for that alone.
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertLinked(self.codex_skills / "alpha", self.clone / "alpha")

    def test_the_report_says_skipped_and_plans_nothing_for_it(self) -> None:
        for argv in ((), ("--follow-config-symlinks",)):
            with self.subTest(argv=argv):
                code, report, err = self.report(*argv, "--dry-run")
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(report["counts"]["needs_flag"], 0)
                self.assertEqual([line for line in report["plan"] if "rules" in line], [])
                self.assertEqual(self.items(report, "claude-code", "rules"), {"sample": render.SKIPPED})
        self.assertEqual(self.render("--follow-config-symlinks")[0], 0)
        self.assertNotIn("rules/", self.manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(tree(self.outside), self.held)
        # A second run plans nothing and changes nothing.
        before = tree(self.root)
        code, report, _ = self.report("--follow-config-symlinks")
        self.assertEqual((code, report["plan"]), (0, []))
        self.assertEqual(tree(self.root), before)


class StaleCase(RenderCase):
    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.render()[0], 0)

    def test_a_skill_that_left_the_clone_is_unlinked(self) -> None:
        self.leave_clone("solo")
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.claude_skills / "solo")
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertIn("no longer installed:", out.splitlines())
        self.assertIn("  remove link home:.claude/skills/solo", out.splitlines())
        self.assertNotIn("solo", json.loads(self.manifest_file.read_text(encoding="utf-8"))["entries"])
        before = tree(self.root)
        code, report, _ = self.report()
        self.assertEqual((code, report["plan"], report["stale"]), (0, [], []))
        self.assertEqual(tree(self.root), before)

    def test_a_skill_that_no_longer_names_a_provider_is_unlinked_there(self) -> None:
        self.skill("alpha", compatibility="compatibility: claude-code")
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertNothingAt(self.codex_skills / "alpha")
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertLinked(self.codex_skills / "beta", self.clone / "beta")
        self.assertEqual([(item["key"], item["status"]) for item in report["stale"]],
                         [("home:.agents/skills/alpha", render.REMOVE)])
        self.assertEqual((self.clone / "alpha" / "SKILL.md").exists(), True)  # only the link went

    def test_a_rule_that_left_the_clone_is_unlinked(self) -> None:
        self.leave_clone("sample")
        self.assertEqual(self.render()[0], 0)
        self.assertNothingAt(self.rules / "sample")

    def test_a_stale_link_the_user_changed_is_kept_and_reported(self) -> None:
        elsewhere = self.root / "elsewhere"
        self.keep(elsewhere / "SKILL.md")
        fsio.remove_link(self.claude_skills / "solo")
        fsio.make_link(str(elsewhere), self.claude_skills / "solo", True)
        self.leave_clone("solo")
        before = tree(self.root)
        code, report, err = self.report()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.root), before)
        self.assertLinked(self.claude_skills / "solo", elsewhere)
        self.assertEqual([(item["key"], item["status"]) for item in report["stale"]],
                         [("home:.claude/skills/solo", render.KEPT)])
        self.assertIn("kept, it is yours", report["stale"][0]["says"])
        self.assertEqual(report["counts"]["kept"], 1)
        code, out, _ = self.render()
        self.assertIn("  home:.claude/skills/solo: kept: no longer installed, and no longer the link setup made", out)
        self.assertIn("1 kept", out.splitlines()[-1])

    def test_a_stale_link_replaced_by_a_directory_is_kept(self) -> None:
        fsio.remove_link(self.claude_skills / "solo")
        mine = self.keep(self.claude_skills / "solo" / "SKILL.md")
        self.leave_clone("solo")
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(report["stale"][0]["status"], render.KEPT)
        self.assertEqual(mine.read_text(encoding="utf-8"), USER_TEXT)

    def test_a_stale_link_that_is_gone_is_taken_out_of_the_record(self) -> None:
        fsio.remove_link(self.claude_skills / "solo")
        self.leave_clone("solo")
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(report["stale"][0]["status"], render.FORGET)
        self.assertNotIn("home:.claude/skills/solo", json.loads(self.manifest_file.read_text(encoding="utf-8"))["entries"])
        self.assertEqual(self.report()[1]["stale"], [])

    def test_the_links_of_a_provider_that_went_away_are_removed(self) -> None:
        self.codex.rmdir()
        code, out, _ = self.render()
        self.assertEqual(code, 0)
        self.assertEqual(os.listdir(self.codex_skills), [])
        self.assertLinked(self.claude_skills / "beta", self.clone / "beta")
        self.assertIn("codex: not installed", out)

    def test_a_stale_removal_and_a_conflict_together_write_nothing(self) -> None:
        self.leave_clone("solo")
        self.put("gamma/SKILL.md", (self.clone / "beta" / "SKILL.md").read_text(encoding="utf-8").replace("beta", "gamma"))
        self.write(self.defaults_file, 'install = ["alpha", "beta", "gamma"]\n' + support.FIXTURE_DEFAULTS)
        self.keep(self.codex_skills / "gamma" / "SKILL.md")
        before = tree(self.root)
        code, _, err = self.render()
        self.assertEqual(code, 2)
        self.assertIn(str(self.codex_skills / "gamma"), err)
        self.assertEqual(tree(self.root), before)
        self.assertLinked(self.claude_skills / "solo", self.clone / "solo")


class ListsCase(RenderCase):
    """``install``: the skills and rules a home gets are the ones it names. In
    the fixture clone alpha is a process skill (the binding table names it),
    beta and solo are optional, and the rule is sample; multiagent-collab has a
    setup of its own and is no item."""

    ALL = ("alpha", "beta", "solo", "sample")

    def lists(self, *disabled: str, enabled: tuple[str, ...] | None = None) -> None:
        enabled = tuple(name for name in self.ALL if name not in disabled) if enabled is None else enabled
        quoted = lambda names: ", ".join(f'"{name}"' for name in names)
        self.write(self.user_file, f"install = [{quoted(enabled)}]\n")

    def test_a_disabled_skill_and_rule_are_not_linked(self) -> None:
        self.lists("beta", "sample")
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(sorted(os.listdir(self.claude_skills)), ["alpha", "solo"])
        self.assertEqual(sorted(os.listdir(self.codex_skills)), ["alpha"])
        self.assertNothingAt(self.rules / "sample")

    def test_a_link_an_earlier_run_made_is_removed_and_comes_back_when_enabled(self) -> None:
        self.assertEqual(self.render()[0], 0)
        self.lists("solo", "sample")
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertIn("  remove link home:.claude/skills/solo", out.splitlines())
        self.assertIn("  remove link home:.claude/rules/sample", out.splitlines())
        self.assertNothingAt(self.claude_skills / "solo")
        self.assertNothingAt(self.rules / "sample")
        self.assertLinked(self.claude_skills / "beta", self.clone / "beta")
        self.lists()
        self.assertEqual(self.render()[0], 0)
        self.assertLinked(self.claude_skills / "solo", self.clone / "solo")
        self.assertLinked(self.rules / "sample", self.clone / "rules" / "sample")

    def test_a_link_removed_by_hand_stays_removed(self) -> None:
        self.assertEqual(self.render()[0], 0)
        fsio.remove_link(self.rules / "sample")
        self.lists("sample")
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.rules / "sample")
        self.assertNotIn("rules/sample", self.manifest_file.read_text(encoding="utf-8"))

    def test_a_fault_of_install_stops_the_run_before_anything_is_written(self) -> None:
        self.assertEqual(self.render()[0], 0)
        for enabled, line in (
            ((*self.ALL, "multiagent-collab"), "install: multiagent-collab has a setup of its own"),
            ((*self.ALL, "gamma"), "install: gamma is no skill or rule of this clone"),
        ):
            with self.subTest(line=line):
                self.lists(enabled=enabled)
                before = tree(self.root)
                code, out, err = self.render()
                self.assertNotEqual(code, 0)
                self.assertIn(f"{self.user_file}: {line}", out + err)
                self.assertEqual(tree(self.root), before)

    def test_a_skill_brings_what_it_needs(self) -> None:
        self.put("roles/dependencies.toml", 'schema_version = 1\n\n[needs]\nbeta = ["solo"]\n')
        self.lists(enabled=("beta",))
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(sorted(os.listdir(self.claude_skills)), ["beta", "solo"])
        self.assertIn("solo: installed as a dependency of beta", out)


class GateCase(RenderCase):
    def test_a_source_problem_stops_the_run_before_any_write(self) -> None:
        self.skill("alpha", name="name: other")
        before = tree(self.root)
        for argv in ((), ("--dry-run",), ("--json",)):
            code, out, err = self.render(*argv)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("alpha/SKILL.md", err)
            self.assertIn("[skill-name]", err)
            self.assertEqual(tree(self.root), before)

    def test_validation_comes_before_the_clone_check(self) -> None:
        self.skill("alpha", name="name: other")
        wsl = homes.Host(homes.WSL, {"PATH": ""}, ())
        with mock.patch.object(locations, "_own_home", lambda: self.home):
            code, out, err = self.render(host=wsl, home=False)
        self.assertEqual(code, 2)
        self.assertIn("[skill-name]", err)
        self.assertNotIn("Windows can't read this clone", out + err)

    def test_a_clone_inside_wsl_is_a_warning_for_the_real_home(self) -> None:
        wsl = homes.Host(homes.WSL, {"PATH": ""}, ())
        with mock.patch.object(locations, "_own_home", lambda: self.home):
            code, out, err = self.render(host=wsl, home=False)
            self.assertEqual((code, err), (0, ""))
            self.assertIn(f"  warning: {homes.CLONE_WARNING}", out.splitlines())
            code, out, err = self.render("--dry-run", host=wsl, home=False)
            self.assertEqual((code, err), (0, ""))
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")

    def test_a_scratch_home_is_not_asked_about_the_clone(self) -> None:
        wsl = homes.Host(homes.WSL, {"PATH": ""}, ())
        code, _, err = self.render(host=wsl)
        self.assertEqual((code, err), (0, ""))
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")

    def test_an_unknown_option_is_a_usage_error(self) -> None:
        before = tree(self.root)
        code, _, err = self.render("--follow")
        self.assertEqual(code, 2)
        self.assertIn("--follow", err)
        self.assertEqual(tree(self.root), before)


class RecordCase(RenderCase):
    def test_the_record_holds_anchors_and_no_machine_path(self) -> None:
        self.assertEqual(self.render()[0], 0)
        raw = self.manifest_file.read_bytes().decode("utf-8")
        entries = json.loads(raw)["entries"]
        self.assertEqual(entries["home:.claude/skills/alpha"], {"kind": "link", "target": "clone:alpha"})
        self.assertEqual(entries["home:.agents/skills/beta"], {"kind": "link", "target": "clone:beta"})
        self.assertEqual(entries["home:.claude/rules/sample"], {"kind": "link", "target": "clone:rules/sample"})
        self.assertEqual(entries["home:.claude/skills"], {"kind": "directory"})
        self.assertEqual(
            sorted(key for key, entry in entries.items() if entry["kind"] == "link"),
            [
                "home:.agents/skills/alpha", "home:.agents/skills/beta",
                "home:.claude/rules/sample",
                "home:.claude/skills/alpha", "home:.claude/skills/beta", "home:.claude/skills/solo",
            ],
        )
        for machine in (str(self.root), self.root.as_posix(), str(self.root).replace("\\", "\\\\"), self.root.name):
            self.assertNotIn(machine, raw)

    def test_the_reversal_restores_the_home_byte_for_byte(self) -> None:
        self.keep(self.claude / "CLAUDE.md")
        self.keep(self.claude / "settings.json", '{"model": "x"}\n')
        self.keep(self.claude_skills / "mine" / "SKILL.md")
        self.keep(self.codex / "AGENTS.md")
        self.keep(self.codex / "config.toml", 'model = "x"\n')
        home_before, clone_before = tree(self.home), tree(self.clone)
        self.assertEqual(self.render()[0], 0)
        self.assertNotEqual(tree(self.home), home_before)

        roots = self.roots()
        result = fileops.plan_reversal(roots).apply()
        self.assertEqual(result.kept, [])
        self.assertTrue(fileops.remove_state(roots))
        self.assertEqual(tree(self.home), home_before)
        self.assertEqual(tree(self.clone), clone_before)

    def test_a_run_writes_nothing_into_the_clone(self) -> None:
        before = tree(self.clone)
        self.render()
        self.render()
        self.assertEqual(tree(self.clone), before)


class PartsCase(RenderCase):
    """The seam the later steps use: a part fills the same plan."""

    def found(self) -> homes.Homes:
        return homes.resolve(Locations(home=self.home, clone=self.clone), self.host)

    def sources(self):
        from wfsetup import validate
        return validate.require(Locations(home=self.home, clone=self.clone))

    def test_the_parts_of_this_step(self) -> None:
        # The first four keep their places: tests slice ``PARTS`` by position.
        names = [part.name for part in render.PARTS]
        self.assertEqual(names[:4], ["skills", "rules", "roles", "entry"])
        self.assertEqual(names[4:], ["codex-settings", "model-list"])

    def test_a_part_adds_to_the_one_plan_and_reads_its_own_option(self) -> None:
        import argparse

        def fill(run: render.Run) -> None:
            if run.option("with_notes"):
                file = run.homes.provider(homes.CLAUDE_CODE).home / "agents" / "note.md"
                run.want(file)
                run.plan.write_file(file, "generated\n")

        extra = render.Part("notes", fill, lambda parser: parser.add_argument("--with-notes", action="store_true"))
        parser = argparse.ArgumentParser()
        extra.add_arguments(parser)
        render.PARTS[0].add_arguments(parser)  # a part without options adds none
        render.PARTS[2].add_arguments(parser)
        options = parser.parse_args(["--with-notes"])
        outcome = render.execute(self.found(), self.sources(), options, parts=(*render.PARTS, extra))
        self.assertEqual((outcome.code, outcome.errors), (0, []))
        self.assertIn("create file home:.claude/agents/note.md", outcome.report["plan"])
        self.assertIn("create link home:.claude/skills/alpha -> clone:alpha", outcome.report["plan"])
        self.assertEqual((self.claude / "agents" / "note.md").read_text(encoding="utf-8"), "generated\n")

    def test_one_parts_conflict_stops_every_part(self) -> None:
        def fill(run: render.Run) -> None:
            run.plan.write_file(run.homes.provider(homes.CLAUDE_CODE).home / "agents" / "note.md", "generated\n")

        self.keep(self.claude / "agents" / "note.md")
        before = tree(self.root)
        outcome = render.execute(self.found(), self.sources(), parts=(*render.PARTS[:2], render.Part("notes", fill)))
        self.assertEqual(outcome.code, 2)
        self.assertIn("is there and setup did not write it", outcome.errors[0])
        self.assertEqual(tree(self.root), before)

    def test_execute_with_a_dry_run_writes_nothing(self) -> None:
        before = tree(self.root)
        outcome = render.execute(self.found(), self.sources(), dry_run=True, parts=render.PARTS[:2])
        self.assertEqual(outcome.code, 0)
        self.assertTrue(outcome.report["changed"])
        self.assertEqual(tree(self.root), before)


UNSHARED_WHY = "inside WSL, where the Windows side's links cannot lead"


class UnsharedCloneWarningCase(RenderCase):
    """A clone the Windows side cannot read is one warning line, never a
    refusal. A scratch home is never asked, so the standing is given by hand."""

    def setUp(self) -> None:
        super().setUp()
        self.standing = homes.CloneStanding(self.clone, self.clone, False, UNSHARED_WHY)
        patch = mock.patch.object(homes, "clone_standing", side_effect=lambda found: self.standing)
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_warns_and_installs(self) -> None:
        code, out, err = self.render("--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[1:3], [f"clone: {self.clone}", f"  warning: {homes.CLONE_WARNING}"])
        code, out, err = self.render()
        self.assertEqual(code, 0, err)
        self.assertIn(f"  warning: {homes.CLONE_WARNING}", out.splitlines())
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        code, report, _ = self.report("--dry-run")
        self.assertEqual(report["clone_warning"], homes.CLONE_WARNING)
        self.assertNotIn("unshared_clone", report)

    def test_the_flag_is_gone(self) -> None:
        code, _, err = self.render("--allow-unshared-clone")
        self.assertEqual(code, 2)
        self.assertIn("--allow-unshared-clone", err)

    def test_a_clone_both_sides_read_says_nothing_of_it(self) -> None:
        self.standing = homes.CloneStanding(self.clone, self.clone, True, "on a Windows drive, which both sides read")
        code, report, _ = self.report("--dry-run")
        self.assertEqual(code, 0)
        self.assertIsNone(report["clone_warning"])
        self.assertFalse([line for line in render.report_lines(report) if "warning" in line])

    def test_the_old_setting_is_no_fault_in_any_file(self) -> None:
        self.write(self.user_file, "[setup]\nallow_unshared_clone = true\n")
        self.write(self.project_file, "[setup]\nallow_unshared_clone = true\n")
        code, out, err = self.render("--dry-run", "--project", str(self.project))
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"  warning: {homes.CLONE_WARNING}", out.splitlines())

    def test_the_help_of_each_command_names_the_settings(self) -> None:
        for command, words in (
            ("render", ("The roles are an item of `install`", "Put `roles` back in `install`")),
        ):
            code, out, _ = support.run(command, "--help")
            self.assertEqual(code, 0)
            flat = " ".join(out.split())
            for word in words:
                with self.subTest(command=command, word=word):
                    self.assertIn(" ".join(word.split()), flat)
            self.assertNotIn("allow-unshared", flat)
            self.assertNotIn("allow_unshared", flat)


class ModelListCase(RenderCase):
    """``render`` reads Codex's list and prints the new-model note (R3.2)."""

    def setUp(self) -> None:
        super().setUp()
        for provider, text in support.FIXTURE_DICTIONARIES.items():
            file = self.clone / "providers" / provider / "dictionary.toml"
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(text.encode("utf-8"))
            (file.parent / "actions.md").write_bytes(
                f"## How actions are done on {provider}\n\n- Dispatch a role.\n".encode("utf-8"))
        self.stub = provider_stub.StubProgram(self.root / "stubs" / "codex", "codex")
        self.at = homes.Host(SIDE, {**os.environ, "PATH": str(self.stub.bin)}, ())

    def note(self, *argv: str, host: homes.Host | None = None) -> tuple[int, str]:
        code, out, err = self.render(*argv, host=host or self.at)
        self.assertEqual(err, "", out)
        return code, out

    def test_a_new_model_prints_the_line_at_the_end(self) -> None:
        self.stub.answer(provider_stub.LIVE, provider_stub.fixture("model-list-new-model.json"))
        code, out = self.note()
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[-2], "note: codex: in the list and not in the dictionary: gpt-7-nova "
                                    "(the dictionary may be stale)")
        self.assertEqual(self.stub.calls(), [["debug", "models"]])

    def test_a_dry_run_reads_it_too(self) -> None:
        self.stub.answer(provider_stub.LIVE, provider_stub.fixture("model-list-new-model.json"))
        code, out = self.note("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("gpt-7-nova", out)
        self.assertEqual(self.stub.calls(), [["debug", "models"]])

    def test_a_list_that_equals_the_dictionary_prints_nothing(self) -> None:
        self.stub.answer(provider_stub.LIVE, provider_stub.fixture("model-list-equal.json"))
        code, out = self.note()
        self.assertEqual(code, 0)
        self.assertNotIn("dictionary may be stale", out)
        self.assertNotIn("note: codex", out)

    def test_an_unreadable_list_is_one_line_and_exit_0(self) -> None:
        self.stub.answer(provider_stub.LIVE, "", code=1, stderr="boom")
        self.stub.answer(provider_stub.BUNDLED, "", code=1, stderr="boom")
        code, out = self.note()
        self.assertEqual(code, 0)
        self.assertEqual(len([line for line in out.splitlines() if line.startswith("note: codex")]), 1)

    def test_a_home_with_no_program_on_path_is_one_line_and_exit_0(self) -> None:
        code, out = self.note(host=self.host)  # the home exists, no codex program on PATH
        self.assertEqual(code, 0)
        self.assertEqual(self.stub.calls(), [])
        lines = [line for line in out.splitlines() if line.startswith("note: codex")]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("not on PATH", lines[0])

    def test_the_note_comes_after_every_other_note(self) -> None:
        self.stub.answer(provider_stub.LIVE, provider_stub.fixture("model-list-new-model.json"))
        real = fileops.Plan.run

        def with_a_note(plan, dry_run):
            result = real(plan, dry_run)
            result.notes.append("a note of the plan")
            return result

        with mock.patch.object(fileops.Plan, "run", with_a_note):
            code, out = self.note()
        self.assertEqual(code, 0)
        lines = [line for line in out.splitlines() if line.startswith("note: ")]
        self.assertIn("a note of the plan", lines[-2], out)
        self.assertIn("gpt-7-nova", lines[-1], out)

    def test_a_run_with_no_codex_home_starts_nothing(self) -> None:
        shutil.rmtree(self.codex)
        code, out = self.note(host=self.host)  # Codex: no home, and no program on PATH
        self.assertEqual(code, 0)
        self.assertEqual(self.stub.calls(), [])
        self.assertNotIn("note: codex", out)



class ProjectCase(RenderCase):
    """A project whose list names alpha and solo, beside a home that may
    leave them out."""

    ONLY_BETA = 'install = ["beta"]\n'
    LIST = 'install = ["alpha", "solo"]\n'

    def setUp(self) -> None:
        super().setUp()
        self.project_claude = self.project / ".claude" / "skills"
        self.project_agents = self.project / ".agents" / "skills"
        self.arg = ("--project", str(self.project))

    def ignored(self) -> list[str]:
        text = self.exclude_file.read_text(encoding="utf-8")
        return [line for line in text.splitlines() if "skills/" in line]

    def wsl(self, *drives: Path) -> homes.Host:
        return homes.Host(homes.WSL, {"PATH": ""}, tuple(str(drive) for drive in drives))


class ProjectLinksCase(ProjectCase):
    """``render --project``: the project's skills, linked in the form for the
    side and listed in the project's ignore block."""

    def test_the_links_are_made_in_both_places(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertLinked(self.project_claude / "alpha", self.clone / "alpha")
        self.assertLinked(self.project_claude / "solo", self.clone / "solo")
        self.assertLinked(self.project_agents / "alpha", self.clone / "alpha")
        self.assertNothingAt(self.project_agents / "solo")   # a skill for Claude Code only
        self.assertEqual(
            {item["name"]: item["status"] for item in report["project"]["items"] if item["kind"] == "link"},
            {".claude/skills/alpha": render.CREATE, ".claude/skills/solo": render.CREATE,
             ".agents/skills/alpha": render.CREATE},
        )
        self.assertEqual(self.ignored(), [
            ".agents/skills/alpha", ".claude/skills/alpha", ".claude/skills/solo",
        ])
        record = json.loads((self.project / ".agents" / "workflow-setup" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            record["entries"]["project:.claude/skills/alpha"]["target"], "clone:alpha")
        # A second run changes nothing.
        before = tree(self.project)
        code, report, _ = self.report(*self.arg)
        self.assertEqual(code, 0)
        self.assertFalse(report["changed"])
        self.assertEqual(tree(self.project), before)

    def test_a_skill_the_home_has_is_skipped_and_said(self) -> None:
        self.write(self.project_file, self.LIST)    # the home installs everything
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.project_claude)
        self.assertNothingAt(self.project_agents)
        items = {(item["provider"], item["name"]): item for item in report["project"]["items"] if item["kind"] == "link"}
        self.assertEqual(set(items), {("claude-code", ".claude/skills/alpha"), ("claude-code", ".claude/skills/solo"),
                                      ("codex", ".agents/skills/alpha")})
        for item in items.values():
            self.assertEqual((item["status"], item["says"]), (render.SKIPPED, "the home has it"))
        self.assertFalse(self.ignored())

    def test_a_skill_that_is_needed_comes_with_it_and_is_said(self) -> None:
        self.put("roles/dependencies.toml", 'schema_version = 1\n\n[needs]\nalpha = ["beta"]\n')
        self.write(self.user_file, 'install = ["solo"]\n')
        self.write(self.project_file, 'install = ["alpha"]\n')
        self.write(self.local_file, 'install = ["alpha"]\n')    # replaces the project's, whole
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertLinked(self.project_claude / "beta", self.clone / "beta")
        self.assertLinked(self.project_agents / "beta", self.clone / "beta")
        self.assertIn("note: project: beta: installed as a dependency of alpha", out)

    def test_the_block_that_lists_the_links_is_taken_over_without_a_record(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg)[0], 0)
        exclude = self.exclude_file.read_bytes()
        shutil.rmtree(self.project / ".agents" / "workflow-setup")
        for name in ("alpha", "solo"):
            (self.project_claude / name).unlink()
        (self.project_agents / "alpha").unlink()
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.exclude_file.read_bytes(), exclude)

    def test_a_project_without_the_group_gets_nothing(self) -> None:
        self.write(self.project_file, "[roles]\nmanager_default = false\n")
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.project_claude)
        self.assertNothingAt(self.project_agents)
        self.assertEqual([item for item in report["project"]["items"] if item["kind"] == "link"], [])

    def test_a_fault_of_the_list_stops_the_run(self) -> None:
        self.write(self.project_file, 'install = ["nothing"]\n')
        before = tree(self.project)
        code, out, err = self.render(*self.arg)
        self.assertEqual(code, 2)
        self.assertIn("nothing is no skill or rule of this clone", err)
        self.assertEqual(tree(self.project), before)

    def test_an_item_removed_leaves_the_ignore_block(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.write(self.project_file, 'install = ["alpha"]\n')
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.assertNothingAt(self.project_claude / "solo")
        self.assertEqual(self.ignored(), [".agents/skills/alpha", ".claude/skills/alpha"])

    @unittest.skipUnless(POSIX, "the view from WSL is rebuilt on a POSIX file system")
    def test_from_wsl_on_one_drive_the_link_is_relative(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        code, out, err = self.render(*self.arg, host=self.wsl(self.root))
        self.assertEqual((code, err), (0, ""), out)
        seen = fsio.look(self.project_claude / "alpha")
        self.assertEqual(seen.target, "../../../fake-clone/alpha")
        self.assertEqual(fsio.look(self.project_agents / "alpha").target, "../../../fake-clone/alpha")
        self.assertEqual(os.path.realpath(self.project_claude / "alpha"), str(self.clone / "alpha"))
        self.assertNotIn("Windows sessions", out)
        # The link is setup's own: a second run is up to date.
        code, report, _ = self.report(*self.arg, host=self.wsl(self.root))
        self.assertEqual(code, 0)
        self.assertFalse(report["changed"])

    @unittest.skipUnless(POSIX, "the view from WSL is rebuilt on a POSIX file system")
    def test_from_wsl_a_clone_on_another_drive_is_not_linked(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        code, report, err = self.report(*self.arg, host=self.wsl(self.clone, self.project))
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.project_claude)
        self.assertNothingAt(self.project_agents)
        links = [item for item in report["project"]["items"] if item["kind"] == "link"]
        self.assertEqual({item["status"] for item in links}, {render.SKIPPED})
        self.assertEqual(len(links), 3)
        lines = [note for note in report["notes"] if "not linked into" in note]
        self.assertEqual(len(lines), 1)
        self.assertIn("alpha, solo not linked into", lines[0])
        self.assertIn(f"run `render --project {self.project}` from Windows", lines[0])

    def test_a_wsl_drive_path_is_named_as_windows_names_it(self) -> None:
        self.assertEqual(render._windows_path("/mnt/d/proj/sub"), "D:\\proj\\sub")
        self.assertEqual(render._windows_path("/mnt/d"), "D:\\")
        self.assertEqual(render._windows_path("/home/me/proj"), "/home/me/proj")

    @unittest.skipUnless(POSIX, "the view from WSL is rebuilt on a POSIX file system")
    def test_from_wsl_a_clone_in_the_linux_file_system_gets_an_absolute_link_and_a_note(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        code, out, err = self.render(*self.arg, host=self.wsl(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(fsio.look(self.project_claude / "alpha").target, str(self.clone / "alpha"))
        self.assertIn("note: project: the clone is in the Linux file system: Windows sessions will not see the links", out)

    def test_the_help_says_what_a_project_gets(self) -> None:
        code, out, _ = support.run("render", "--help")
        self.assertEqual(code, 0)
        self.assertIn("With --project, the skills the project lists", out)


class ProjectLinkThereCase(ProjectCase):
    """What is already at a project's link path, and what the sweep keeps
    (P3.4)."""

    def by_hand(self, link: Path, target: Path | str) -> Path:
        link.parent.mkdir(parents=True, exist_ok=True)
        fsio.make_link(str(target), link, True)
        return link

    def record(self) -> dict:
        return json.loads((self.project / ".agents" / "workflow-setup" / "manifest.json").read_text(encoding="utf-8"))

    def link_items(self, report: dict) -> dict[str, dict]:
        return {item["name"]: item for item in report["project"]["items"] if item["kind"] == "link"}

    def stale_paths(self, report: dict) -> dict[str, str]:
        return {item["path"]: item["status"] for item in report["stale"]}

    @unittest.skipUnless(POSIX, "a relative link is made on a POSIX file system")
    def test_setups_link_with_another_text_to_the_unit_is_up_to_date(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg)[0], 0)
        link = self.project_claude / "alpha"
        link.unlink()
        os.symlink("../../../fake-clone/alpha", link)    # as the other side writes it
        before = tree(self.project)
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.link_items(report)[".claude/skills/alpha"]["status"], render.UP_TO_DATE)
        self.assertFalse(report["changed"])
        self.assertEqual(report["plan"], [])
        self.assertEqual(tree(self.project), before)
        # And from WSL, which would write a relative text, an absolute one
        # is kept as it is.
        link.unlink()
        os.symlink(str(self.clone / "alpha"), link)
        before = tree(self.project)
        code, report, err = self.report(*self.arg, host=self.wsl(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertFalse(report["changed"])
        self.assertEqual(tree(self.project), before)

    def test_a_link_made_by_hand_is_taken_over_and_removed_once_off_the_list(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        link = self.by_hand(self.project_claude / "alpha", self.clone / "alpha")
        text = fsio.look(link).target
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        item = self.link_items(report)[".claude/skills/alpha"]
        self.assertEqual(item["status"], render.UP_TO_DATE)
        self.assertIn("a link made by hand, which setup takes over", item["says"])
        self.assertIn("`uninstall --project` leaves it", item["says"])
        self.assertIn("taking the skill off the project's list removes it", item["says"])
        self.assertEqual(self.record()["entries"]["project:.claude/skills/alpha"],
                         {"kind": "link", "target": "clone:alpha", "adopted": True})
        self.assertEqual(fsio.look(link).target, text)
        self.assertIn(".claude/skills/alpha", self.ignored())
        # A second run changes nothing.
        code, report, _ = self.report(*self.arg)
        self.assertEqual((code, report["changed"]), (0, False))
        # Off the list: removed and forgotten.
        self.write(self.project_file, 'install = ["solo"]\n')
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.stale_paths(report)[str(link)], render.REMOVE)
        self.assertNothingAt(link)
        self.assertNotIn("project:.claude/skills/alpha", self.record()["entries"])
        self.assertNotIn(".claude/skills/alpha", self.ignored())
        self.assertTrue((self.clone / "alpha" / "SKILL.md").is_file())

    @unittest.skipUnless(POSIX, "a relative link is made on a POSIX file system")
    def test_a_link_of_the_other_side_with_another_text_is_removed_once_its_unit_leaves(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg)[0], 0)
        link = self.project_claude / "alpha"
        alias = self.root / "alias"
        os.symlink(str(self.clone), alias)
        link.unlink()
        os.symlink(str(alias / "alpha"), link)    # the other side reaches the clone through a link
        self.assertNotIn("adopted", self.record()["entries"]["project:.claude/skills/alpha"])
        self.write(self.project_file, 'install = ["solo"]\n')
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.stale_paths(report)[str(link)], render.REMOVE)
        self.assertNothingAt(link)
        self.assertNotIn("project:.claude/skills/alpha", self.record()["entries"])

    @unittest.skipUnless(POSIX, "a link through a link is made on a POSIX file system")
    def test_a_link_taken_over_is_removed_by_where_it_leads(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        alias = self.root / "alias"
        os.symlink(str(self.clone), alias)
        link = self.by_hand(self.project_claude / "alpha", alias / "alpha")
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(self.record()["entries"]["project:.claude/skills/alpha"]["adopted"])
        self.write(self.project_file, 'install = ["solo"]\n')
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.stale_paths(report)[str(link)], render.REMOVE)
        self.assertNothingAt(link)
        self.assertNotIn("project:.claude/skills/alpha", self.record()["entries"])

    def test_a_link_to_elsewhere_is_a_conflict(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        elsewhere = self.root / "elsewhere" / "alpha"
        elsewhere.mkdir(parents=True)
        self.by_hand(self.project_claude / "alpha", elsewhere)
        before = tree(self.project)
        code, out, err = self.render(*self.arg)
        self.assertEqual(code, 2, out)
        self.assertIn(f"{self.project_claude / 'alpha'}: a link to elsewhere on this side", err)
        self.assertIn("and setup did not make it", err)
        self.assertEqual(tree(self.project), before)

    def test_a_link_of_a_provider_not_installed_here_is_kept(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg)[0], 0)
        shutil.rmtree(self.codex)                      # Codex is no longer installed on this side
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertLinked(self.project_agents / "alpha", self.clone / "alpha")
        self.assertNotIn(str(self.project_agents / "alpha"), self.stale_paths(report))
        self.assertIn(".agents/skills/alpha", self.ignored())

    def test_on_a_one_sided_host_a_link_of_a_unit_the_home_gained_is_removed(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.write(self.user_file, 'install = ["alpha", "beta"]\n')
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.link_items(report)[".claude/skills/alpha"]["says"], "the home has it")
        for link in (self.project_claude / "alpha", self.project_agents / "alpha"):
            self.assertEqual(self.stale_paths(report)[str(link)], render.REMOVE)
            self.assertNothingAt(link)
        self.assertLinked(self.project_claude / "solo", self.clone / "solo")
        self.assertEqual(self.ignored(), [".claude/skills/solo"])

    @unittest.skipUnless(POSIX, "the view from WSL is rebuilt on a POSIX file system")
    def test_with_another_side_the_link_of_a_unit_the_home_has_is_kept(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg, host=self.wsl(self.root))[0], 0)
        self.write(self.user_file, 'install = ["alpha", "beta"]\n')
        before = tree(self.project)
        code, report, err = self.report(*self.arg, host=self.wsl(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.link_items(report)[".claude/skills/alpha"]["says"], "the home has it")
        self.assertEqual([item for item in report["stale"] if item["path"].startswith(str(self.project))], [])
        self.assertEqual(tree(self.project), before)

    @unittest.skipUnless(POSIX, "the view from WSL is rebuilt on a POSIX file system")
    def test_a_relative_link_whose_unit_left_the_list_is_removed(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg, host=self.wsl(self.root))[0], 0)
        link = self.project_claude / "alpha"
        self.assertFalse(os.path.isabs(fsio.look(link).target))
        self.write(self.project_file, 'install = ["solo"]\n')
        code, report, err = self.report(*self.arg, host=self.wsl(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.stale_paths(report)[str(link)], render.REMOVE)
        self.assertNothingAt(link)
        self.assertNothingAt(self.project_agents / "alpha")
        self.assertEqual(self.ignored(), [".claude/skills/solo"])

    @unittest.skipUnless(POSIX, "the view from WSL is rebuilt on a POSIX file system")
    def test_a_link_whose_provider_the_compatibility_no_longer_names_is_removed(self) -> None:
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.assertEqual(self.render(*self.arg, host=self.wsl(self.root))[0], 0)
        skill = self.clone / "alpha" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8").replace("claude-code, codex", "claude-code"),
                         encoding="utf-8")
        code, report, err = self.report(*self.arg, host=self.wsl(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.stale_paths(report)[str(self.project_agents / "alpha")], render.REMOVE)
        self.assertNothingAt(self.project_agents / "alpha")
        self.assertFalse(os.path.isabs(fsio.look(self.project_claude / "alpha").target))

    def test_the_help_says_what_is_kept_at_a_projects_path(self) -> None:
        code, out, _ = support.run("render", "--help")
        self.assertEqual(code, 0)
        self.assertIn("A link already at a project's path that leads to the skill's", out)


class ProjectRuleCopyCase(ProjectCase):
    """A project's rules are copied, not linked (P3.5)."""

    RULE_LIST = 'install = ["sample"]\n'
    NO_SAMPLE = 'install = ["alpha", "beta", "solo"]\n'

    def setUp(self) -> None:
        super().setUp()
        self.copy = self.project / ".claude" / "rules" / "sample" / "sample.md"
        self.write(self.user_file, self.NO_SAMPLE)
        self.write(self.project_file, self.RULE_LIST)

    def ignored_rules(self) -> list[str]:
        text = self.exclude_file.read_text(encoding="utf-8")
        return [line for line in text.splitlines() if "rules/" in line]

    def test_the_copy_is_made_and_listed(self) -> None:
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.copy.read_bytes(), (self.clone / "rules/sample/sample.md").read_bytes())
        self.assertEqual(fsio.look(self.copy.parent).kind, fsio.DIRECTORY)
        self.assertEqual(self.ignored_rules(), [".claude/rules/sample/sample.md"])
        self.assertEqual({item["name"]: item["status"] for item in report["project"]["items"] if item["kind"] == "file"},
                         {".claude/rules/sample/sample.md": render.CREATE})
        before = tree(self.project)
        code, report, _ = self.report(*self.arg)
        self.assertEqual(code, 0)
        self.assertFalse(report["changed"])
        self.assertEqual(tree(self.project), before)

    def test_a_clone_file_with_crlf_is_copied_with_lf(self) -> None:
        self.put("rules/sample/sample.md", b"\xef\xbb\xbfA rule.\r\nTwo lines.\r\n")
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.assertEqual(self.copy.read_bytes(), b"A rule.\nTwo lines.\n")

    def test_a_change_in_the_clone_reaches_the_copy(self) -> None:
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.put("rules/sample/sample.md", "A changed rule.\n")
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.assertEqual(self.copy.read_text(encoding="utf-8"), "A changed rule.\n")

    def test_an_edited_copy_is_kept_and_reported(self) -> None:
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.copy.write_text("mine\n", encoding="utf-8")
        self.put("rules/sample/sample.md", "A changed rule.\n")
        code, report, _ = self.report(*self.arg)
        self.assertEqual(code, 3)
        self.assertEqual(self.copy.read_text(encoding="utf-8"), "mine\n")
        statuses = {item["name"]: item["status"] for item in report["project"]["items"] if item["kind"] == "file"}
        self.assertEqual(statuses[".claude/rules/sample/sample.md"], render.EDITED)
        self.assertEqual(self.render(*self.arg, "--overwrite-edited")[0], 0)
        self.assertEqual(self.copy.read_text(encoding="utf-8"), "A changed rule.\n")

    def test_a_rule_leaving_the_list_removes_the_copy(self) -> None:
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.write(self.project_file, 'install = ["alpha"]\n')
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.assertNothingAt(self.copy)
        self.assertNothingAt(self.copy.parent)
        self.assertEqual(self.ignored_rules(), [])

    def test_a_file_the_rule_no_longer_has_is_removed(self) -> None:
        self.put("rules/sample/extra.md", "More.\n")
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.assertTrue((self.copy.parent / "extra.md").is_file())
        (self.clone / "rules/sample/extra.md").unlink()
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.assertNothingAt(self.copy.parent / "extra.md")
        self.assertTrue(self.copy.is_file())

    def test_a_home_with_the_rule_copies_nothing(self) -> None:
        self.write(self.user_file, "")
        code, report, err = self.report(*self.arg)
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.project / ".claude" / "rules")
        skipped = [item for item in report["project"]["items"] if item["name"] == ".claude/rules/sample"]
        self.assertEqual([(item["status"], item["says"]) for item in skipped], [(render.SKIPPED, "the home has it")])

    def test_the_block_that_lists_a_copy_is_taken_over_without_a_record(self) -> None:
        self.assertEqual(self.render(*self.arg)[0], 0)
        exclude = self.exclude_file.read_bytes()
        shutil.rmtree(self.project / ".agents" / "workflow-setup")
        shutil.rmtree(self.copy.parent)
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.exclude_file.read_bytes(), exclude)

    def test_the_copy_of_the_other_side_is_kept_while_claude_code_is_not_here(self) -> None:
        self.assertEqual(self.render(*self.arg)[0], 0)
        shutil.rmtree(self.claude)     # Claude Code is not on this side
        self.assertEqual(self.render(*self.arg, host=self.wsl(self.root))[0], 0)
        self.assertTrue(self.copy.is_file())
        # With Claude Code here and the home now installing the rule, the copy is stale.
        self.claude.mkdir()
        self.write(self.user_file, "")
        self.assertEqual(self.render(*self.arg)[0], 0)
        self.assertNothingAt(self.copy)

    def test_the_help_says_a_project_gets_a_copy(self) -> None:
        code, out, _ = support.run("render", "--help")
        self.assertEqual(code, 0)
        self.assertIn("are copied, not", out)


class ExcludeFileCase(ProjectCase):
    """The project's ignore block is in the repository's exclude file,
    ``info/exclude`` in its common git directory (R6.3), never in
    ``.gitignore``; a project that is no repository gets no list."""

    def setUp(self) -> None:
        super().setUp()
        self.write(self.user_file, self.ONLY_BETA)
        self.write(self.project_file, self.LIST)
        self.links = [".agents/skills/alpha", ".claude/skills/alpha", ".claude/skills/solo"]

    def listed(self, exclude: Path) -> list[str]:
        return [line for line in blocks.content_of(exclude.read_bytes(), blocks.GITIGNORE) or [] if "skills/" in line]

    def record(self, project: Path) -> dict:
        return json.loads((project / ".agents" / "workflow-setup" / "manifest.json").read_text(encoding="utf-8"))

    def worktree(self) -> tuple[Path, Path]:
        """A linked worktree of a repository beside it, with the project's
        settings; its exclude file is in the common directory, outside it."""
        repository, worktree = self.root / "repository", self.root / "worktree"
        exclude = support.make_repository(repository)
        support.make_worktree(repository, worktree)
        self.write(worktree / ".agents" / "workflow.toml", self.LIST)
        return worktree, exclude

    def uninstall(self, project: Path) -> tuple[int, str, str]:
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            return support.run("uninstall", "--home", str(self.home), "--project", str(project))

    def test_the_block_lands_in_the_exclude_file(self) -> None:
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        data = self.exclude_file.read_bytes()
        self.assertTrue(data.startswith(support.GIT_EXCLUDE + b"\n# workflow-setup:start\n"), data)
        self.assertEqual(self.listed(self.exclude_file), self.links)
        self.assertEqual(blocks.content_of(data, blocks.GITIGNORE), sorted([*fileops.IGNORE_ALWAYS, *self.links]))
        self.assertNothingAt(self.project / ".gitignore")
        entry = self.record(self.project)["entries"]["git-info:exclude"]
        self.assertEqual((entry["kind"], entry["created"]), ("text", False))
        self.assertIn("edit file git-info:exclude (backup)", out)

    def test_a_linked_worktree_lists_in_the_common_directory_and_the_way_back_takes_it_out(self) -> None:
        worktree, exclude = self.worktree()
        code, out, err = self.render("--project", str(worktree))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.listed(exclude), self.links)
        self.assertNothingAt(worktree / ".gitignore")
        self.assertIn("git-info:exclude", self.record(worktree)["entries"])
        # Its backup is the project's, inside the project.
        backups = [item for item in self.record(worktree)["backups"] if item["path"] == "git-info:exclude"]
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0]["backup"].startswith("project:.agents/workflow-setup/backups/"), backups)
        self.assertEqual(self.render("--project", str(worktree))[0], 0)
        self.assertEqual(self.listed(exclude), self.links)
        code, out, err = self.uninstall(worktree)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(exclude.read_bytes(), support.GIT_EXCLUDE)

    def test_a_gitfile_whose_back_pointer_names_another_checkout_gives_no_list(self) -> None:
        worktree, exclude = self.worktree()
        admin = self.root / "repository" / ".git" / "worktrees" / "wt"
        (admin / "gitdir").write_bytes(str(self.root / "elsewhere" / ".git").encode("utf-8") + b"\n")
        code, out, err = self.render("--project", str(worktree))
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("does not name this project's .git file back; setup lists nothing in an exclude file", out)
        self.assertEqual(exclude.read_bytes(), support.GIT_EXCLUDE)
        self.assertNothingAt(worktree / ".gitignore")
        self.assertLinked(worktree / ".claude" / "skills" / "alpha", self.clone / "alpha")
        self.assertNotIn("git-info:exclude", self.record(worktree)["entries"])

    def test_a_gitfile_the_other_side_wrote_or_with_no_commondir_gives_no_list(self) -> None:
        worktree, exclude = self.worktree()
        admin = self.root / "repository" / ".git" / "worktrees" / "wt"
        (worktree / ".git").write_bytes(b"gitdir: Q:/work/repository/.git/worktrees/wt\n")
        found = gitrepo.find(worktree)
        self.assertIsNone(found.info)
        self.assertIn("which this side of the machine cannot read", found.note)
        (worktree / ".git").write_bytes(b"gitdir: " + str(admin).encode("utf-8") + b"\n")
        self.assertEqual(gitrepo.find(worktree).info, exclude.parent)
        (admin / "commondir").unlink()   # a submodule's or a separate git directory's
        self.assertIn("no commondir", gitrepo.find(worktree).note)

    def test_no_repository_no_list_and_a_recorded_block_is_left_as_it_is(self) -> None:
        self.assertEqual(self.render(*self.arg)[0], 0)
        listed = self.exclude_file.read_bytes()
        shutil.move(self.project / ".git", self.root / "moved-git")
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(sum("not a git repository's top (no .git)" in line for line in out.splitlines()), 1, out)
        self.assertIn("the block the record lists in git-info:exclude is left as it is", out)
        self.assertIn("git-info:exclude", self.record(self.project)["entries"])
        self.assertEqual((self.root / "moved-git" / "info" / "exclude").read_bytes(), listed)
        self.assertNothingAt(self.project / ".gitignore")
        # A project that never was one: no list, and no .gitignore either.
        fresh = self.root / "fresh"
        self.write(fresh / ".agents" / "workflow.toml", self.LIST)
        code, out, err = self.render("--project", str(fresh))
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("not a git repository's top (no .git)", out)
        self.assertNotIn("left as it is", out)
        self.assertEqual(sorted(os.listdir(fresh)), [".agents", ".claude"])

    OLD_BLOCK = b"# workflow-setup:start\n.agents/workflow.local.toml\n.claude/skills/alpha\n# workflow-setup:end\n"

    def old_block_recorded(self) -> bytes:
        """A project as an earlier setup left it: its ignore block in
        ``.gitignore`` and the record entry for it."""
        gitignore = b"build/\n" + self.OLD_BLOCK + b"dist/\n"
        (self.project / ".gitignore").write_bytes(gitignore)
        manifest = self.project / ".agents" / "workflow-setup" / "manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["entries"]["project:.gitignore"] = {
            "kind": "text", "sha256": fsio.sha256(gitignore), "created": False, "original": None,
            "syntax": "gitignore", "removed_lines": [],
            "blocks": {"": {"sha256": fsio.sha256(self.OLD_BLOCK), "joint": {}}},
        }
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return gitignore

    def test_a_recorded_old_block_in_gitignore_is_named_and_forgotten(self) -> None:
        self.assertEqual(self.render(*self.arg)[0], 0)
        gitignore = self.old_block_recorded()
        self.assertIn("project:.gitignore", self.record(self.project)["entries"])
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"{self.project / '.gitignore'}: lines 2-5 are setup's old ignore block", out)
        self.assertIn("remove those lines", out)
        self.assertEqual((self.project / ".gitignore").read_bytes(), gitignore)
        self.assertNotIn("project:.gitignore", self.record(self.project)["entries"])
        self.assertEqual(self.listed(self.exclude_file), self.links)
        # Named again while it is there; nothing left in the record to change.
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("lines 2-5 are setup's old ignore block", out)
        self.assertEqual((self.project / ".gitignore").read_bytes(), gitignore)

    def test_a_checkout_without_a_record_gets_the_line_too(self) -> None:
        gitignore = b"# workflow-setup:start\n.claude/skills/alpha\n# workflow-setup:end\n"
        (self.project / ".gitignore").write_bytes(gitignore)
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("lines 1-3 are setup's old ignore block", out)
        self.assertEqual((self.project / ".gitignore").read_bytes(), gitignore)
        self.assertNotIn("project:.gitignore", self.record(self.project)["entries"])
        # A .gitignore without setup's markers is not named.
        (self.project / ".gitignore").write_bytes(b"build/\n")
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("old ignore block", out)

    def test_the_backup_of_an_edited_exclude_file_is_inside_the_project(self) -> None:
        self.assertEqual(self.render(*self.arg)[0], 0)
        with self.exclude_file.open("ab") as stream:
            stream.write(b"build/\n")
        edited = self.exclude_file.read_bytes()
        self.write(self.project_file, 'install = ["alpha"]\n')
        code, out, err = self.render(*self.arg)
        self.assertEqual((code, err), (0, ""), out)
        backups = [item for item in self.record(self.project)["backups"] if item["path"] == "git-info:exclude"]
        self.assertEqual(len(backups), 2)
        last = self.project.joinpath(*backups[-1]["backup"].partition(":")[2].split("/"))
        self.assertEqual(last.read_bytes(), edited)
        self.assertTrue(paths.inside(last, self.project / ".agents" / "workflow-setup" / "backups"))
        self.assertEqual(self.listed(self.exclude_file), [".agents/skills/alpha", ".claude/skills/alpha"])
        self.assertTrue(self.exclude_file.read_bytes().endswith(b"build/\n"))


if __name__ == "__main__":
    unittest.main()
