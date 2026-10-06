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

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

import support
from fileops_support import POSIX, SYMLINKS
from test_validate import TreeCase
from wfsetup import fileops, fsio, homes, locations, render
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

    # These tests are about the links. The fixture clone has roles and no
    # dictionary for either provider, so every run here asks for no role
    # definition; ``test_definitions`` covers those.
    ROLES = ("--no-roles",)

    def render(self, *argv: str, host: homes.Host | None = None, home: bool = True) -> tuple[int, str, str]:
        host = host or self.host
        places = ["--home", str(self.home)] if home else []
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: host)):
            return support.run("render", *argv, *self.ROLES, *places)

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
        for option in ("--dry-run", "--follow-config-symlinks", "--allow-unshared-clone", "--home", "--project", "--json"):
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

    def test_every_conflict_has_a_line_and_the_hint_points_to_migration(self) -> None:
        self.keep(self.claude_skills / "alpha" / "SKILL.md")
        self.keep(self.codex_skills / "alpha" / "SKILL.md")
        err = self.refused(str(self.claude_skills / "alpha"), str(self.codex_skills / "alpha"), "--migrate-v1")
        lines = err.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(render.MIGRATION_AVAILABLE)
        self.assertIn("render --migrate-v1 --dry-run", lines[-1])
        self.assertNotIn("not have yet", lines[-1])
        with mock.patch.object(render, "MIGRATION_AVAILABLE", False):
            self.assertIn("does not have yet", render.migration_hint())

    def test_the_json_report_lists_the_conflicts(self) -> None:
        self.keep(self.claude_skills / "alpha" / "SKILL.md")
        code, report, err = self.report()
        self.assertEqual(code, 2)
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(report["counts"]["conflict"], 1)
        self.assertEqual(self.items(report, "claude-code", "skills")["alpha"], render.CONFLICT)
        self.assertEqual(report["plan"], [])
        self.assertEqual(len(report["errors"]), 2)
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
        self.assertIn("--migrate-v1", err)
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
        shutil.rmtree(self.clone / "solo")
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
        shutil.rmtree(self.clone / "rules" / "sample")
        self.assertEqual(self.render()[0], 0)
        self.assertNothingAt(self.rules / "sample")

    def test_a_stale_link_the_user_changed_is_kept_and_reported(self) -> None:
        elsewhere = self.root / "elsewhere"
        self.keep(elsewhere / "SKILL.md")
        fsio.remove_link(self.claude_skills / "solo")
        fsio.make_link(str(elsewhere), self.claude_skills / "solo", True)
        shutil.rmtree(self.clone / "solo")
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
        shutil.rmtree(self.clone / "solo")
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(report["stale"][0]["status"], render.KEPT)
        self.assertEqual(mine.read_text(encoding="utf-8"), USER_TEXT)

    def test_a_stale_link_that_is_gone_is_taken_out_of_the_record(self) -> None:
        fsio.remove_link(self.claude_skills / "solo")
        shutil.rmtree(self.clone / "solo")
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
        shutil.rmtree(self.clone / "solo")
        self.put("gamma/SKILL.md", (self.clone / "beta" / "SKILL.md").read_text(encoding="utf-8").replace("beta", "gamma"))
        self.keep(self.codex_skills / "gamma" / "SKILL.md")
        before = tree(self.root)
        code, _, err = self.render()
        self.assertEqual(code, 2)
        self.assertIn(str(self.codex_skills / "gamma"), err)
        self.assertEqual(tree(self.root), before)
        self.assertLinked(self.claude_skills / "solo", self.clone / "solo")


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
            code, _, err = self.render(host=wsl, home=False)
        self.assertEqual(code, 2)
        self.assertIn("[skill-name]", err)
        self.assertNotIn("--allow-unshared-clone", err)

    def test_an_unshared_clone_is_refused_for_the_real_home(self) -> None:
        wsl = homes.Host(homes.WSL, {"PATH": ""}, ())
        before = tree(self.root)
        with mock.patch.object(locations, "_own_home", lambda: self.home):
            code, out, err = self.render(host=wsl, home=False)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("--allow-unshared-clone", err)
            self.assertIn("the clone setup runs from is", err)
            self.assertEqual(tree(self.root), before)
            self.assertEqual(self.render("--dry-run", host=wsl, home=False)[0], 2)

            code, _, err = self.render("--allow-unshared-clone", host=wsl, home=False)
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
        self.assertIn("migrate", names)

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
        options = parser.parse_args(["--with-notes", *self.ROLES])
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


if __name__ == "__main__":
    unittest.main()
