"""Tests for the screen of ``setup.py`` (``wfsetup/screen.py``): a terminal without
``--yes``, with standard input and the terminal faked.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

# The tests directory is on sys.path however this file is run (by path, by dotted name, discover, run.py).
import sys as _sys
from pathlib import Path as _Path
_sys.path[:0] = {str(_Path(__file__).resolve().parent)} - set(_sys.path)

import io
import os
import tomllib
import unittest
from unittest import mock

import test_program
from wfsetup import screen

CLAUDE = {
    "tiers": {"fast": "haiku", "standard": "sonnet", "deep": "opus", "frontier": "fable"},
    "efforts": {"low": "low", "medium": "medium", "high": "high", "max": "max"},
}


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class ScreenCase(test_program.ProgramCase):
    def typed(self, *lines: str, argv: tuple[str, ...] = ("--provider", "claude-code")) -> tuple[int, str, str]:
        """setup.py on a terminal with these lines typed."""
        with mock.patch("sys.stdin", Terminal("".join(f"{line}\n" for line in lines))):
            return self.setup(*argv)

    def written(self) -> dict:
        return tomllib.loads(self.user_file.read_text(encoding="utf-8"))


class ScreenTests(ScreenCase):
    def test_enter_enter_on_a_fresh_home_installs_and_writes_the_mappings_alone(self) -> None:
        code, out, err = self.typed("", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Apply? [Y/n]", out)
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertTrue((self.claude_agents / "worker.md").is_file())
        self.assertEqual(self.written(), {"schema_version": 1, "providers": {"claude-code": CLAUDE}})

    def test_the_screen_numbers_every_option_with_its_value_and_its_file(self) -> None:
        code, out, err = self.typed("", "n")
        self.assertEqual((code, err), (1, ""), out)
        lines = out.splitlines()
        row = next(line for line in lines if "process.questions" in line)
        self.assertTrue(row.lstrip().startswith("4 "), row)
        self.assertIn('"all-together"', row)
        self.assertIn("shipped: " + os.path.join("tools", "setup", "defaults.toml"), row)
        self.assertTrue(any(line.lstrip().startswith("1 ") and "this machine" in line for line in lines))
        self.assertTrue(any("claude-code tiers" in line and "fast=haiku" in line for line in lines))
        self.assertFalse(any("roles.enabled" in line for line in lines))

    def test_a_number_then_a_value_writes_it_and_r_takes_it_out(self) -> None:
        code, out, err = self.typed("4", "one-at-a-time", "", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.written()["process"], {"questions": "one-at-a-time"})
        # A re-run shows the value as it stands.
        code, out, err = self.typed("", "n")
        self.assertEqual(code, 1)
        row = next(line for line in out.splitlines() if "process.questions" in line)
        self.assertIn('"one-at-a-time"', row)
        self.assertIn(f"user: {self.user_file}", row)
        before = self.settled()
        code, out, err = self.typed("r 4", "", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("process", self.written())
        self.assertEqual(self.written()["providers"], {"claude-code": CLAUDE})
        self.assertNotEqual(self.settled(), before)

    def test_a_value_the_schema_refuses_is_asked_again(self) -> None:
        code, out, err = self.typed("4", "sometimes", "all-together", "", "n")
        self.assertEqual((code, err), (1, ""), out)
        self.assertIn("questions", out)
        self.assertFalse(self.user_file.exists())

    def test_n_is_exit_1_and_writes_nothing(self) -> None:
        self.claude.mkdir()
        before = self.settled()
        code, out, err = self.typed("4", "one-at-a-time", "", "n")
        self.assertEqual((code, err), (1, ""), out)
        self.assertEqual(self.settled(), before)

    def test_a_mapping_is_changed_by_its_row(self) -> None:
        number = next(
            line.split()[0] for line in self.typed("", "n")[1].splitlines() if "claude-code tiers" in line
        )
        code, out, err = self.typed(number, "fast=sonnet", "", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.written()["providers"]["claude-code"]["tiers"]["fast"], "sonnet")
        self.assertEqual(self.written()["providers"]["claude-code"]["efforts"], CLAUDE["efforts"])

    def test_a_re_run_shows_the_values_as_they_stand_and_writes_nothing(self) -> None:
        self.assertEqual(self.typed("", "")[0], 0)
        before = self.settled()
        code, out, err = self.typed("", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"user: {self.user_file}", out)
        self.assertEqual(self.settled(), before)

    def test_a_project_screen_has_the_manager_row_and_writes_no_file_without_a_value(self) -> None:
        code, out, err = self.typed("", "", argv=("--provider", "claude-code", str(self.project)))
        self.assertEqual((code, err), (0, ""), out)
        self.assertTrue(any("start as the Manager" in line for line in out.splitlines()))
        self.assertIn(str(self.project), out)
        self.assertFalse((self.project / ".agents" / "workflow.toml").exists())

    def test_r_takes_a_value_out_of_a_projects_file(self) -> None:
        argv = ("--provider", "claude-code", str(self.project))
        self.assertEqual(self.setup("--yes", "--docs-dir", "sprints", *argv[:2], argv[2])[0], 0)
        file = self.project / ".agents" / "workflow.toml"
        self.assertEqual(tomllib.loads(file.read_text(encoding="utf-8"))["process"], {"docs_dir": "sprints"})
        code, out, err = self.typed("r 4", "", "", argv=argv)
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("process", tomllib.loads(file.read_text(encoding="utf-8")))

    def test_a_refused_plan_brings_the_screen_back(self) -> None:
        code, out, err = self.typed("", argv=("--provider", "claude-code", "--docs-dir", "x\x07y"))
        # The plan is refused, the screen is shown again, and the input ends there.
        self.assertEqual(code, 2)
        self.assertIn("standard input ended", err)
        self.assertIn("error: --docs-dir", out)
        self.assertEqual(out.count("Enter: the plan."), 2)
        self.assertFalse(self.user_file.exists())

    def test_the_standard_input_ending_is_an_error_and_writes_nothing(self) -> None:
        before = self.settled()
        code, out, err = self.typed()
        self.assertEqual(code, 2)
        self.assertIn("standard input ended", err)
        self.assertEqual(self.settled(), before)

    def test_without_a_terminal_the_screen_is_not_shown(self) -> None:
        with mock.patch("sys.stdin", io.StringIO("\n\n")):
            code, out, err = self.setup("--provider", "claude-code")
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertFalse(self.user_file.exists())


class ItemsTests(ScreenCase):
    NEEDS = 'schema_version = 1\n\n[needs]\nbeta = ["alpha"]\n'

    def setUp(self) -> None:
        super().setUp()
        self.write(self.clone / "roles" / "dependencies.toml", self.NEEDS)

    def seed(self, *items: str) -> None:
        """The home's file as setup writes it, holding this ``install``."""
        self.assertEqual(self.setup("--yes", "--provider", "claude-code", "--install", *items)[0], 0)

    def number(self, out: str, name: str) -> str:
        """The number of an item on the last checklist shown."""
        return [line for line in out.splitlines() if line.rstrip().endswith(f"] {name}") or f"] {name}  (" in line][-1].split()[0]

    def test_unticking_roles_keeps_the_skills_it_brought(self) -> None:
        self.seed("roles", "solo")
        out = self.typed("2", "", "", "")[1]
        roles = self.number(out, "roles")
        self.assertIn("(needed by the roles)", out)
        code, out, err = self.typed("2", roles, "", "", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.written()["install"], ["solo", "alpha"])
        self.assertFalse((self.claude_agents / "worker.md").exists())
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")

    def test_ticking_a_skill_ticks_what_it_needs_and_that_cannot_be_unticked(self) -> None:
        self.seed("solo")
        out = self.typed("2", "", "", "n")[1]
        beta, alpha = self.number(out, "beta"), self.number(out, "alpha")
        code, out, err = self.typed("2", beta, alpha, "", "", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertRegex(out, rf"{alpha}  \[x\] alpha  \(needed by beta\)")
        self.assertIn("alpha: needed by beta; untick that first", out)
        self.assertIn("alpha: installed as a dependency of beta", out)
        self.assertEqual(self.written()["install"], ["solo", "beta"])
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        # Unticking beta frees it.
        code, out, err = self.typed("2", beta, "", "", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("untick that first", out)
        self.assertEqual(self.written()["install"], ["solo"])

    def test_a_projects_checklist_shows_the_homes_items_locked(self) -> None:
        self.seed("roles", "solo")
        argv = ("--provider", "claude-code", str(self.project))
        out = self.typed("2", "", "n", argv=argv)[1]
        for name in ("roles", "alpha", "solo"):
            self.assertRegex(out, rf"\[x\] {name}  \(from this machine\)")
        beta = self.number(out, "beta")
        self.assertRegex(out, rf"{beta}  \[ \] beta")
        solo = self.number(out, "solo")
        code, out, err = self.typed("2", solo, beta, "", "", "", argv=argv)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("solo: from this machine; it is changed there", out)
        project = tomllib.loads((self.project / ".agents" / "workflow.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["install"], ["beta"])

    def test_a_project_is_offered_roles_the_home_lacks_and_ticking_them_ticks_the_skills(self) -> None:
        self.seed("sample")
        argv = ("--provider", "claude-code", str(self.project))
        out = self.typed("2", "", "n", argv=argv)[1]
        self.assertRegex(out, r"\[ \] roles\n")
        self.assertNotIn("roles  (from this machine)", out)
        roles = self.number(out, "roles")
        code, out, err = self.typed("2", roles, "", "", "", argv=argv)
        self.assertEqual((code, err), (0, ""), out)
        self.assertRegex(out, r"\[x\] roles\n")
        self.assertRegex(out, r"\[x\] alpha  \(needed by the roles\)")
        self.assertEqual(
            tomllib.loads((self.project / ".agents" / "workflow.toml").read_text(encoding="utf-8"))["install"],
            ["roles"])
        self.assertLinked(self.project / ".claude" / "skills" / "alpha", self.clone / "alpha")

    def test_unticking_roles_on_a_project_keeps_only_skills_the_home_lacks(self) -> None:
        self.seed("alpha")
        argv = ("--provider", "claude-code", str(self.project))
        out = self.typed("2", "", "n", argv=argv)[1]
        roles = self.number(out, "roles")
        code, out, err = self.typed("2", roles, roles, "", "", "", argv=argv)
        self.assertEqual((code, err), (0, ""), out)
        file = self.project / ".agents" / "workflow.toml"
        found = tomllib.loads(file.read_text(encoding="utf-8")).get("install", []) if file.exists() else []
        self.assertNotIn("alpha", found)


class EditedTests(ScreenCase):
    def seed_and_edit(self) -> bytes:
        self.assertEqual(self.setup("--yes", "--provider", "claude-code")[0], 0)
        file = self.claude_agents / "worker.md"
        made = file.read_bytes()
        file.write_bytes(made + b"\nmy own line\n")
        return made

    def backups(self) -> list:
        base = self.home / ".agents" / "workflow-setup" / "backups"
        return [
            _Path(directory) / name for directory, _, names in os.walk(base) for name in names
            if _Path(directory, name).read_bytes().endswith(b"my own line\n")
        ] if base.is_dir() else []

    def test_an_edited_role_file_asked_and_replaced_with_a_backup(self) -> None:
        made = self.seed_and_edit()
        code, out, err = self.typed("", "y", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Replace, after a backup? [y/N]", out)
        self.assertEqual((self.claude_agents / "worker.md").read_bytes(), made)
        kept = self.backups()
        self.assertEqual(len(kept), 1, out)
        self.assertIn(b"my own line", kept[0].read_bytes())
        self.assertEqual(out.count("Enter: the plan."), 1)

    def test_an_edited_role_file_asked_and_kept(self) -> None:
        self.seed_and_edit()
        code, out, err = self.typed("", "n", "")
        self.assertEqual((code, err), (3, ""), out)
        self.assertIn(b"my own line", (self.claude_agents / "worker.md").read_bytes())
        self.assertEqual(self.backups(), [])
        self.assertEqual(out.count("Replace, after a backup?"), 1)

    def test_an_item_unattended_is_still_kept_and_reported(self) -> None:
        self.seed_and_edit()
        code, out, err = self.setup("--yes", "--provider", "claude-code")
        self.assertEqual(code, 3, out)
        self.assertNotIn("Replace, after a backup?", out)

    def test_overwrite_edited_on_the_command_line_asks_nothing(self) -> None:
        self.seed_and_edit()
        code, out, err = self.typed("", "", argv=("--provider", "claude-code", "--overwrite-edited"))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("Replace, after a backup?", out)
        self.assertEqual(len(self.backups()), 1)


class HandWrittenFileTests(ScreenCase):
    HAND_WRITTEN = "# my own notes, kept by hand\n[process]\n# where the docs are\ndocs_dir = \"sprints\"\n"
    ASK = "Rewrite it, after a backup? [y/N]"

    def hand_file(self) -> None:
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        self.user_file.write_bytes(self.HAND_WRITTEN.encode())

    def backups(self) -> list:
        base = self.home / ".agents" / "workflow-setup" / "backups"
        return [_Path(d) / n for d, _, names in os.walk(base) for n in names] if base.is_dir() else []

    def test_yes_rewrites_it_after_a_backup(self) -> None:
        self.hand_file()
        code, out, err = self.typed("4", "one-at-a-time", "", "y", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"{self.user_file}: written or edited by hand. {self.ASK}", out)
        self.assertEqual(out.count(self.ASK), 1)
        self.assertNotIn("needs --yes --rewrite-settings", out.split(self.ASK)[1])
        self.assertEqual(self.written()["process"], {"docs_dir": "sprints", "questions": "one-at-a-time"})
        kept = self.backups()
        self.assertEqual([file.read_bytes() for file in kept], [self.HAND_WRITTEN.encode()])

    def test_no_keeps_it_and_ends_with_exit_3_the_install_done(self) -> None:
        self.hand_file()
        code, out, err = self.typed("4", "one-at-a-time", "", "n", "")
        self.assertEqual((code, err), (3, ""), out)
        self.assertEqual(self.user_file.read_bytes(), self.HAND_WRITTEN.encode())
        self.assertEqual(self.backups(), [])
        self.assertIn(f"kept: {self.user_file}, written or edited by hand; not written:", out)
        self.assertIn("process.questions", out.split("not written:")[1])
        self.assertTrue((self.claude_agents / "worker.md").is_file())
        between = out.split(self.ASK)[1].split("Apply?")[0]
        self.assertIn("kept:", between)
        self.assertNotIn("--rewrite-settings", between)
        self.assertNotIn("changes to", between)
        self.assertNotIn("edited outside setup", between)
        # What the file holds is said to be in it; only the changed value is not written.
        self.assertIn('process.docs_dir = "sprints"  (in this file)', between)
        self.assertIn('process.questions = "one-at-a-time"  (not written)', between)

    def test_no_on_an_installed_home_does_not_say_everything_is_up_to_date(self) -> None:
        self.hand_file()
        self.assertEqual(self.typed("", "")[0], 0)
        code, out, err = self.typed("4", "one-at-a-time", "", "n", "")
        self.assertEqual((code, err), (3, ""), out)
        kept = out.split(self.ASK)[1]       # the plan shown before the question is the one that would write
        self.assertIn("plan:\n  nothing else to do: the rest is up to date\n", kept)
        self.assertNotIn("everything is up to date", kept)
        self.assertTrue(out.rstrip().endswith("; the settings file was kept as written or edited by hand"), out)

    def test_no_in_a_project_makes_the_plan_again_without_the_project_changes(self) -> None:
        file = self.project / ".agents" / "workflow.toml"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'# mine\n[process]\ndocs_dir = "sprints"\n')
        argv = ("--provider", "claude-code", str(self.project))
        code, out, err = self.typed("3", "true", "", "n", "", argv=argv)
        self.assertEqual((code, err), (3, ""), out)
        self.assertEqual(file.read_bytes(), b'# mine\n[process]\ndocs_dir = "sprints"\n')
        between = out.split(self.ASK)[1].split("Apply?")[0]
        self.assertIn("kept:", between)
        self.assertNotIn(".claude/settings.json", between)
        self.assertNotIn("starting-role", between)
        self.assertNotIn("everything is up to date", out)
        self.assertFalse((self.project / ".claude" / "settings.json").exists())

    def test_nothing_changed_asks_nothing(self) -> None:
        self.hand_file()
        code, out, err = self.typed("", "")
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn(self.ASK, out)
        self.assertTrue(self.user_file.read_bytes().startswith(self.HAND_WRITTEN.encode()))

    def test_yes_alone_unattended_still_stops(self) -> None:
        self.hand_file()
        code, out, err = self.setup("--yes", "--provider", "claude-code", "--memory-dir", "notes")
        self.assertEqual(code, 2)
        self.assertIn("--rewrite-settings", err)


class CodexItemTests(ScreenCase):
    ARGV = ("--provider", "codex")

    def number(self, out: str) -> str:
        return next(line.split()[0] for line in out.splitlines() if "Codex config item" in line)

    def test_the_item_set_to_profile_with_a_root_writes_both_blocks(self) -> None:
        number = self.number(self.typed("", "n", argv=self.ARGV)[1])
        root = str(self.home / "trees")
        code, out, err = self.typed(number, "profile", root, "", "", argv=self.ARGV)
        self.assertEqual((code, err), (0, ""), out)
        config = tomllib.loads((self.codex / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["default_permissions"], "workflow")
        self.assertIn(root, config["permissions"]["workflow"]["filesystem"])
        self.assertIn("agents", config)
        code, out, err = self.typed("", "n", argv=self.ARGV)
        self.assertIn("as the Codex config holds it", out)

    def test_an_edited_codex_block_is_asked_and_replaced_with_a_backup(self) -> None:
        code, out, err = self.setup("--yes", "--provider", "codex", "--codex-settings", "on")
        self.assertEqual((code, err), (0, ""), out)
        config = self.codex / "config.toml"
        text = config.read_text(encoding="utf-8")
        self.assertIn("max_concurrent_threads_per_session = 8", text)
        config.write_text(text.replace("max_concurrent_threads_per_session = 8",
                                       "max_concurrent_threads_per_session = 5"), encoding="utf-8")
        code, out, err = self.typed("", "y", "", argv=self.ARGV)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Replace, after a backup? [y/N]", out)
        self.assertIn("max_concurrent_threads_per_session = 8", config.read_text(encoding="utf-8"))
        kept = [path for path in (self.home / ".agents" / "workflow-setup" / "backups").rglob("*")
                if path.is_file() and b"threads_per_session = 5" in path.read_bytes()]
        self.assertEqual(len(kept), 1, out)

    def test_the_row_shows_the_mode_and_root_the_config_holds(self) -> None:
        root = str(self.home / "trees")
        self.assertEqual(self.setup("--yes", "--provider", "codex", "--codex-settings", "profile",
                                    "--worktree-root", root)[0], 0)
        code, out, err = self.typed("", "n", argv=self.ARGV)
        self.assertIn(f"profile, worktree root {root}", out)

    def test_a_root_the_profile_refuses_is_asked_again(self) -> None:
        number = self.number(self.typed("", "n", argv=self.ARGV)[1])
        code, out, err = self.typed(number, "on", "relative/dir", str(self.home / "trees"), "", "n", argv=self.ARGV)
        self.assertEqual((code, err), (1, ""), out)
        self.assertIn("not an absolute path", out)
        self.assertFalse((self.codex / "config.toml").exists())


if __name__ == "__main__":
    unittest.main()
