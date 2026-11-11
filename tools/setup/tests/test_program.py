"""Tests for ``setup.py``'s program (``wfsetup/program.py``): its options and
an unattended install of a home or a project.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

The clone is the fixture clone of ``test_definitions`` (skills, a rule, roles
and both providers' dictionaries); the machine is a ``Host`` made by hand with
an empty PATH, so a provider counts as installed by its scratch home alone.
"""
from __future__ import annotations

# The tests directory is on sys.path however this file is run (by path, by dotted name, discover, run.py).
import sys as _sys
from pathlib import Path as _Path
_sys.path[:0] = {str(_Path(__file__).resolve().parent)} - set(_sys.path)

import json
import os
import shutil
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import provider_stub
import support
import test_definitions
from test_render import tree
from wfsetup import cli, dictionary, gitrepo, homes, locations, program, render
from wfsetup.errors import EXIT_PIPE


class ProgramCase(test_definitions.DefinitionsCase):
    PARTS = None   # every part of a real run

    def setUp(self) -> None:
        super().setUp()
        # Both homes are gone, so a test names its provider.
        shutil.rmtree(self.claude)
        shutil.rmtree(self.codex)

    def setup(self, *argv: str, home: bool = True) -> tuple[int, str, str]:
        places = ["--home", str(self.home)] if home else []
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            return support.setup(*argv, *places)

    def settled(self) -> dict:
        return tree(self.home)


class InstallTests(ProgramCase):
    def test_a_fresh_home_with_a_named_provider_gets_the_shipped_set_and_the_roles(self) -> None:
        code, out, err = self.setup("--yes", "--provider", "claude-code")
        self.assertEqual((code, err), (0, ""), out)
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertLinked(self.claude_skills / "beta", self.clone / "beta")
        self.assertLinked(self.rules / "sample", self.clone / "rules" / "sample")
        self.assertTrue((self.claude_agents / "worker.md").is_file())
        self.assertTrue((self.claude_agents / "lead.md").is_file())
        self.assertTrue((self.claude_skills / "lead" / "SKILL.md").is_file())   # the loaded role
        self.assertNothingAt(self.codex)
        self.assertNothingAt(self.codex_skills)

    def test_two_named_providers_are_both_installed(self) -> None:
        code, out, err = self.setup("--yes", "--provider", "claude-code", "--provider", "codex")
        self.assertEqual((code, err), (0, ""), out)
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertLinked(self.codex_skills / "alpha", self.clone / "alpha")
        self.assertTrue((self.codex_agents / "worker.toml").is_file())

    def test_a_second_run_changes_nothing(self) -> None:
        self.assertEqual(self.setup("--yes", "--provider", "claude-code")[0], 0)
        before = self.settled()
        code, out, err = self.setup("--yes", "--provider", "claude-code")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.settled(), before)

    def test_a_project_is_set_up_as_well(self) -> None:
        self.write(self.project_file, 'install = ["alpha", "beta", "sample"]\n')
        self.write(self.user_file, 'install = ["alpha"]\n')
        code, out, err = self.setup("--yes", "--provider", "claude-code", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertLinked(self.project / ".claude" / "skills" / "beta", self.clone / "beta")
        self.assertNothingAt(self.project / ".claude" / "skills" / "alpha")   # the home has it
        self.assertTrue((self.project / ".agents" / "workflow-setup" / "manifest.json").is_file())
        # Listed in the repository's exclude file, not in .gitignore (R6.3).
        self.assertIn(b"\n.claude/skills/beta\n", self.exclude_file.read_bytes())
        self.assertNothingAt(self.project / ".gitignore")

    def test_a_provider_that_is_there_needs_no_option(self) -> None:
        self.claude.mkdir()
        code, out, err = self.setup("--yes")
        self.assertEqual((code, err), (0, ""), out)
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertNothingAt(self.codex)


class StopTests(ProgramCase):
    def test_no_provider_is_exit_2_naming_the_option(self) -> None:
        code, out, err = self.setup("--yes")
        self.assertEqual(code, 2)
        self.assertIn("--provider", err)
        self.assertEqual(out, "")
        self.assertNothingAt(self.claude)
        self.assertNothingAt(self.home / ".agents")

    def test_no_terminal_and_no_yes_stops_naming_yes(self) -> None:
        self.claude.mkdir()
        before = self.settled()
        with mock.patch("wfsetup.screen.terminal", return_value=False):
            code, out, err = self.setup()
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertEqual(self.settled(), before)

    def test_an_old_key_is_an_unknown_key_and_stops_writing_nothing(self) -> None:
        self.claude.mkdir()
        self.write(self.user_file, '[setup]\nenabled = ["alpha"]\n')
        before = self.settled()
        code, out, err = self.setup("--yes")
        self.assertEqual(code, 2)
        self.assertIn(f"{self.user_file}: setup: unknown key", err)
        self.assertEqual(self.settled(), before)

    def test_an_unknown_key_in_the_project_stops_too(self) -> None:
        self.claude.mkdir()
        self.write(self.project_file, '[project]\nenabled = ["alpha"]\n')
        before = self.settled()
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn(f"{self.project_file}: project: unknown key", err)
        self.assertEqual(self.settled(), before)
        self.assertFalse((self.project / ".agents" / "workflow-setup").exists())

    def test_no_terminal_names_a_settings_fault_before_yes(self) -> None:
        self.claude.mkdir()
        self.write(self.project_file, "x = [\n")
        with mock.patch("wfsetup.screen.terminal", return_value=False):
            code, out, err = self.setup(str(self.project))
        self.assertEqual(code, 2)
        self.assertIn(str(self.project_file), err)
        self.assertNotIn("--yes", err)

    def test_a_source_problem_stops_the_run(self) -> None:
        self.claude.mkdir()
        self.write(self.clone / "alpha" / "SKILL.md", "no front matter\n")
        before = self.settled()
        code, out, err = self.setup("--yes")
        self.assertEqual(code, 2)
        self.assertIn("alpha", err)
        self.assertEqual(self.settled(), before)

    def test_a_bad_dir_is_named_dir(self) -> None:
        self.claude.mkdir()
        missing = str(self.root / "nowhere")
        code, out, err = self.setup("--yes", missing)
        self.assertEqual(code, 2)
        self.assertIn(f"DIR: {missing}: not a directory", err)
        self.assertNotIn("--project", err)

    def test_an_option_is_never_abbreviated(self) -> None:
        self.claude.mkdir()
        code, out, err = self.setup("--ye")
        self.assertEqual(code, 2)
        self.assertIn("unrecognized arguments", err)

    def test_a_provider_setup_does_not_know_is_a_usage_error(self) -> None:
        code, out, err = self.setup("--yes", "--provider", "gemini")
        self.assertEqual(code, 2)
        self.assertIn("gemini", err)

    def test_the_clone_check_stops_a_dry_run_too(self) -> None:
        self.claude.mkdir()
        with mock.patch.object(homes, "require_linkable_clone", side_effect=homes.SetupError("stop here")):
            code, out, err = self.setup("--dry-run")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("stop here", err)


class SettingsTests(ProgramCase):
    """The settings file a run writes (R4.3, R4.4, R9.2), before it installs."""

    def data(self, file=None) -> dict:
        return tomllib.loads((file or self.user_file).read_text(encoding="utf-8"))

    def test_a_first_home_run_writes_the_mappings_and_nothing_else(self) -> None:
        code, out, err = self.setup("--yes", "--provider", "claude-code")
        self.assertEqual((code, err), (0, ""), out)
        data = self.data()
        self.assertEqual(sorted(data), ["providers", "schema_version"])
        self.assertEqual(list(data["providers"]), ["claude-code"])
        self.assertEqual(sorted(data["providers"]["claude-code"]), ["efforts", "tiers"])
        self.assertIn(f"written: {self.user_file}", out)

    def test_a_second_run_writes_nothing(self) -> None:
        self.assertEqual(self.setup("--yes", "--provider", "claude-code")[0], 0)
        before = self.settled()
        code, out, err = self.setup("--yes", "--provider", "claude-code")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"nothing to write: {self.user_file} already holds these settings", out)
        self.assertEqual(self.settled(), before)

    def test_install_writes_the_list_and_installs_it(self) -> None:
        code, out, err = self.setup("--yes", "--provider", "claude-code", "--install", "alpha")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.data()["install"], ["alpha"])
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertNothingAt(self.claude_skills / "beta")
        self.assertNothingAt(self.claude_agents / "worker.md")   # `roles` is not in the list

    def test_reset_takes_a_key_out(self) -> None:
        self.write(self.user_file, '[process]\ndensity = "full"\ndocs_dir = "sprints"\n')
        code, out, err = self.setup("--yes", "--provider", "claude-code", "--rewrite-settings", "--reset", "process.density")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.data()["process"], {"docs_dir": "sprints"})

    def test_a_tier_equal_to_the_dictionary_stays_in_a_project_file(self) -> None:
        self.claude.mkdir()
        shipped = dictionary.load_all(self.locations())["claude-code"].settings["tiers"]["deep"]
        code, out, err = self.setup("--yes", "--tier", f"claude-code:deep={shipped}", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.data(self.project_file)["providers"], {"claude-code": {"tiers": {"deep": shipped}}})
        self.assertFalse(self.user_file.exists())   # a run with DIR writes the project's file alone

    def test_the_manager_default_is_for_a_project(self) -> None:
        self.claude.mkdir()
        code, out, err = self.setup("--yes", "--manager-default")
        self.assertEqual(code, 2)
        self.assertIn("give it with DIR", err)
        self.assertNothingAt(self.home / ".agents")

    def test_a_dry_run_shows_both_plans_and_writes_neither(self) -> None:
        self.claude.mkdir()
        before = self.settled()
        code, out, err = self.setup("--dry-run", "--install", "alpha")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("create file home:.agents/workflow.toml", out)
        self.assertIn("create link home:.claude/skills/alpha", out)
        self.assertNotIn("home:.claude/skills/beta", out)   # the list it would write, not the file there now
        self.assertEqual(self.settled(), before)

    def test_a_settings_file_written_by_hand_needs_the_option(self) -> None:
        self.claude.mkdir()
        self.write(self.user_file, "# mine\n")
        before = self.settled()
        code, out, err = self.setup("--yes", "--docs-dir", "sprints")
        self.assertEqual(code, 2)
        self.assertIn("--rewrite-settings", err)
        self.assertEqual(self.settled(), before)
        code, out, err = self.setup("--yes", "--rewrite-settings", "--docs-dir", "sprints")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.data()["process"], {"docs_dir": "sprints"})

    def test_an_unlisted_model_is_an_error_unless_allowed(self) -> None:
        stub = provider_stub.StubProgram(self.root / "stubs" / "codex", "codex")
        stub.answer(provider_stub.LIVE, provider_stub.fixture("model-list-missing-mapped.json"))
        self.host = homes.Host(self.host.side, {**os.environ, "PATH": str(stub.bin)}, ())
        self.codex.mkdir()
        before = self.settled()
        code, out, err = self.setup("--yes")
        self.assertEqual(code, 2)
        self.assertIn("--allow-unlisted", err)
        self.assertEqual(self.settled(), before)
        code, out, err = self.setup("--yes", "--allow-unlisted")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("kept, as --allow-unlisted says", out)

    def test_the_help_lists_the_new_options(self) -> None:
        code, out, err = self.setup("--help", home=False)
        self.assertEqual((code, err), (0, ""))
        flat = " ".join(out.split())
        for word in ("--install NAME [NAME ...]", "--reset KEY", "--tier PROVIDER:TIER=MODEL", "--manager-default",
                     "--rewrite-settings", "--allow-unlisted"):
            self.assertIn(word, flat)
        for gone in ("--unset", "--roles", "--skills", " init ", "`init`", "DIR/.gitignore"):
            self.assertNotIn(gone, flat)
        self.assertIn("exclude file, info/exclude in its git directory", flat)
        self.assertIn("CLAUDE_CONFIG_DIR and CODEX_HOME are ignored", flat)
        self.assertIn("DIR/.claude and DIR/.codex", flat)

    def test_a_check_names_the_negative_option_given(self) -> None:
        for given in ("--no-manager-default", "--no-high-stakes", "--manager-default"):
            for mode in ("--check", "--uninstall"):
                code, out, err = self.setup(mode, given)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"takes no {given}", err)


class ProjectKeysTests(ProgramCase):
    """The keys "agent" and "effortLevel" of a project's tracked
    .claude/settings.json move only with a run that writes the project's
    settings file (R6.1)."""

    SETTINGS = ".claude/settings.json"

    def setUp(self) -> None:
        super().setUp()
        self.claude.mkdir()
        self.settings = self.project / self.SETTINGS

    def keys(self) -> dict:
        return json.loads(self.settings.read_bytes())

    def record_entry(self) -> dict | None:
        record = self.project / ".agents" / "workflow-setup" / "manifest.json"
        return json.loads(record.read_text(encoding="utf-8"))["entries"].get(f"project:{self.SETTINGS}")

    def left_note(self, out: str) -> bool:
        return (
            f"note: {self.SETTINGS}: agent and effortLevel are left as they are, and so is what the record holds "
            f"of them: this run did not write {self.project_file}" in out
        )

    def test_a_refresh_leaves_both_keys_and_their_entries_after_the_mapping_changes_the_effort(self) -> None:
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "lead", "effortLevel": "medium"})
        data, entry = self.settings.read_bytes(), self.record_entry()
        self.assertEqual(sorted(entry["keys"]), ["agent", "effortLevel"])
        # The home's mapping now gives the role another effort.
        self.write(self.user_file, '[providers.claude-code.efforts]\nmedium = "high"\n')
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"nothing to write: {self.project_file} already holds these settings", out)
        self.assertEqual(self.settings.read_bytes(), data)
        self.assertEqual(self.record_entry(), entry)
        self.assertTrue(self.left_note(out), out)
        self.assertNotIn("key effortLevel", out)
        # A dry run of the same refresh plans nothing for them either.
        code, out, err = self.setup("--dry-run", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn(self.SETTINGS + ":", out.replace(f"note: {self.SETTINGS}:", ""))
        # A run that writes the project's file sets the effort of today.
        code, out, err = self.setup("--yes", "--docs-dir", "sprints", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "lead", "effortLevel": "high"})
        self.assertEqual(self.record_entry()["keys"]["effortLevel"]["value"], "high")
        self.assertFalse(self.left_note(out), out)

    def test_turning_the_manager_default_on_sets_them_and_off_removes_them(self) -> None:
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.settings)
        self.assertFalse(self.left_note(out), out)   # nothing to leave
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "lead", "effortLevel": "medium"})
        code, out, err = self.setup("--yes", "--no-manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.settings)
        self.assertIsNone(self.record_entry())

    def test_the_flag_counts_as_a_change_though_the_file_holds_the_value(self) -> None:
        self.write(self.project_file, "[roles]\nmanager_default = true\n")
        data = self.project_file.read_bytes()
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "lead", "effortLevel": "medium"})
        self.assertEqual(self.project_file.read_bytes(), data)
        self.assertIn("  git add -- .claude/settings.json\n", out + "\n")
        self.assertNotIn(".agents/workflow.toml", out.split("git add")[1])
        # A refresh with no flag still leaves them.
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "lead", "effortLevel": "medium"})
        self.assertTrue(self.left_note(out), out)

    def test_no_manager_default_removes_keys_though_the_file_does_not_hold_the_key(self) -> None:
        self.assertEqual(self.setup("--yes", "--manager-default", str(self.project))[0], 0)
        self.write(self.project_file, "[process]\ndocs_dir = \"sprints\"\n")
        self.assertTrue(self.settings.is_file())
        code, out, err = self.setup("--yes", "--rewrite-settings", "--no-manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.settings)
        self.assertIsNone(self.record_entry())

    def test_no_manager_default_removes_keys_of_an_earlier_run_though_the_file_says_false(self) -> None:
        self.assertEqual(self.setup("--yes", "--manager-default", str(self.project))[0], 0)
        self.assertEqual(self.keys(), {"agent": "lead", "effortLevel": "medium"})
        self.write(self.project_file, "[roles]\nmanager_default = false\n")
        code, out, err = self.setup("--yes", "--no-manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.settings)
        self.assertIsNone(self.record_entry())

    def test_a_first_run_with_no_value_makes_no_project_file(self) -> None:
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.project_file)
        self.assertIn(
            f"nothing to write: no value is given for {self.project_file}, and it is not created", out)
        self.assertNotIn("git add", out)
        code, out, err = self.setup("--yes", "--docs-dir", "sprints", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertTrue(self.project_file.is_file())

    def test_a_default_turned_off_by_hand_in_the_project_removes_the_keys_on_a_refresh(self) -> None:
        self.with_keys()
        self.write(self.project_file, self.ROLES_ON.replace("manager_default = true", "manager_default = false"))
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.settings)
        self.assertIsNone(self.record_entry())
        self.assertFalse(self.left_note(out), out)
        # The roles stay: only the keys went.
        self.assertTrue((self.project / ".claude" / "agents" / "lead.md").is_file())
        self.assertIn('install = ["alpha", "roles"]', self.project_file.read_text(encoding="utf-8"))

    def test_a_default_turned_off_by_hand_with_roles_from_the_home_removes_the_keys_on_a_refresh(self) -> None:
        self.assertEqual(self.setup("--yes", "--manager-default", str(self.project))[0], 0)
        self.write(self.project_file, "[roles]\nmanager_default = false\n")
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.settings)
        self.assertIsNone(self.record_entry())
        self.assertFalse(self.left_note(out), out)

    def test_a_default_turned_off_in_the_home_removes_the_keys_and_keeps_the_rest(self) -> None:
        self.with_keys()
        data = self.keys()
        data["permissions"] = {"allow": ["Bash(ls)"]}
        self.settings.write_text(json.dumps(data), encoding="utf-8")
        self.write(self.user_file, 'install = ["alpha"]\n[roles]\nmanager_default = false\n')
        self.write(self.project_file, 'install = ["alpha", "roles"]\n')
        project_bytes = self.project_file.read_bytes()
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"permissions": {"allow": ["Bash(ls)"]}})
        self.assertEqual(self.project_file.read_bytes(), project_bytes)
        self.assertFalse(self.left_note(out), out)

    def test_a_users_own_keys_stay_when_the_default_is_off(self) -> None:
        self.write(self.project_file, 'install = ["alpha", "roles"]\n[roles]\nmanager_default = false\n')
        self.write(self.settings, '{"agent": "mine", "effortLevel": "low"}\n')
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "mine", "effortLevel": "low"})

    ROLES_ON = 'install = ["alpha", "roles"]\n[roles]\nmanager_default = true\n'

    def with_keys(self) -> None:
        """Roles on in the project, the keys set by a run that changed its choices."""
        self.write(self.user_file, 'install = ["alpha"]\n')
        self.write(self.project_file, self.ROLES_ON)
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "lead", "effortLevel": "medium"})
        self.assertTrue((self.project / ".claude" / "agents" / "lead.md").is_file())

    def test_roles_taken_out_by_hand_remove_the_keys_setup_set_on_a_refresh(self) -> None:
        self.with_keys()
        self.write(self.project_file, 'install = ["alpha"]\n[roles]\nmanager_default = true\n')
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertFalse((self.project / ".claude" / "agents" / "lead.md").exists())
        self.assertNothingAt(self.settings)
        self.assertIsNone(self.record_entry())
        self.assertFalse(self.left_note(out), out)

    def test_the_rest_of_the_settings_file_stays_when_the_keys_go(self) -> None:
        self.with_keys()
        data = self.keys()
        data["permissions"] = {"allow": ["Bash(ls)"]}
        self.settings.write_text(json.dumps(data), encoding="utf-8")
        self.write(self.project_file, 'install = ["alpha"]\n')
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"permissions": {"allow": ["Bash(ls)"]}})

    def test_a_refresh_with_roles_still_on_leaves_the_keys(self) -> None:
        self.with_keys()
        data = self.settings.read_bytes()
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.settings.read_bytes(), data)
        self.assertTrue(self.left_note(out), out)

    def test_a_users_own_agent_key_stays_when_roles_are_not_installed(self) -> None:
        self.write(self.user_file, 'install = ["alpha"]\n')
        self.write(self.project_file, 'install = ["alpha"]\n')
        self.write(self.settings, '{"agent": "mine"}\n')
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "mine"})

    def test_roles_on_from_the_home_only_then_taken_out_remove_the_keys(self) -> None:
        self.write(self.user_file, 'install = ["alpha", "roles"]\n')
        self.write(self.project_file, 'install = ["alpha"]\n[roles]\nmanager_default = true\n')
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.keys(), {"agent": "lead", "effortLevel": "medium"})
        self.write(self.user_file, 'install = ["alpha"]\n')
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.settings)


class GitLinesTests(ProgramCase):
    """After applying: the git lines for the project's files this run wrote
    (R6.2), the Codex default only where git does not track the file
    (R6.4, R10.3), and the other side's command (R2.3)."""

    CODEX_CONFIG = ".codex/config.toml"

    def setUp(self) -> None:
        super().setUp()
        self.claude.mkdir()
        self.codex.mkdir()
        self.config = self.project / self.CODEX_CONFIG

    def git(self, *argv: str) -> None:
        subprocess.run(["git", "-C", str(self.project), *argv], check=True, capture_output=True)

    def track_config(self, text: str = "model = \"x\"\n") -> None:
        self.write(self.config, text)
        shutil.rmtree(self.project / ".git")
        self.git("init", "-q")
        self.git("add", "--", self.CODEX_CONFIG)

    def block(self, out: str) -> bool:
        return self.config.is_file() and "workflow-setup" in self.config.read_text(encoding="utf-8")

    def test_turning_the_manager_default_on_prints_the_git_lines_for_both_files(self) -> None:
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("  git add -- .agents/workflow.toml .claude/settings.json", out)
        self.assertIn(
            '  git commit -m "Set the project\'s workflow settings" -- .agents/workflow.toml .claude/settings.json', out
        )
        # A refresh that wrote neither prints none.
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("git add", out)
        # A dry run prints none.
        code, out, err = self.setup("--dry-run", "--docs-dir", "sprints", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("git add", out)

    def test_only_the_file_written_is_named(self) -> None:
        code, out, err = self.setup("--yes", "--docs-dir", "sprints", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("  git add -- .agents/workflow.toml\n", out + "\n")
        self.assertNotIn("settings.json", out.split("git add")[1])

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_dropped_keys_of_a_tracked_settings_file_print_the_git_lines(self) -> None:
        self.write(self.user_file, 'install = ["alpha"]\n')
        self.write(self.project_file, 'install = ["alpha", "roles"]\n[roles]\nmanager_default = true\n')
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        shutil.rmtree(self.project / ".git")
        self.git("init", "-q")
        self.git("add", "-f", "--", ".claude/settings.json")
        self.write(self.project_file, 'install = ["alpha"]\n')
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("  git add -- .claude/settings.json", out)
        self.assertIn("git commit -m", out)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_a_file_git_does_not_track_gets_the_codex_default(self) -> None:
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertTrue(self.block(out), out)
        self.assertNotIn("will not start as", out)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_a_tracked_file_gets_nothing_and_a_line(self) -> None:
        self.track_config()
        before = self.config.read_bytes()
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertIn(f"{self.config} is tracked by git, so setup writes nothing there: Codex sessions in the "
                      "project will not start as lead", out)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_an_old_block_in_a_tracked_file_is_named_and_forgotten(self) -> None:
        # Setup wrote its block while git did not track the file.
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        text = self.config.read_text(encoding="utf-8")
        self.assertIn("workflow-setup", text)
        record = self.project / ".agents" / "workflow-setup" / "manifest.json"
        self.assertIn(f"project:{self.CODEX_CONFIG}", json.loads(record.read_text(encoding="utf-8"))["entries"])
        shutil.rmtree(self.project / ".git")
        self.git("init", "-q")
        self.git("add", "-f", "--", self.CODEX_CONFIG)
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)
        self.assertRegex(out, r"lines \d+-\d+ are setup's old Codex block")
        entries = json.loads(record.read_text(encoding="utf-8"))["entries"]
        self.assertNotIn(f"project:{self.CODEX_CONFIG}", entries)
        # Turned off, the tracked file is still not edited, and the block is named again.
        code, out, err = self.setup("--yes", "--no-manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)
        self.assertRegex(out, r"lines \d+-\d+ are setup's old Codex block")

    def test_git_that_cannot_be_started_writes_nothing_and_says_so(self) -> None:
        with mock.patch.object(gitrepo.subprocess, "run", side_effect=FileNotFoundError("git")):
            code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNothingAt(self.config)
        self.assertIn("was not checked: git could not be started, did not answer or failed", out)
        self.assertIn("will not start as lead", out)

    @unittest.skipUnless(os.name == "posix", "the view from WSL: a POSIX path under a mount point")
    def test_the_other_sides_command_from_wsl_and_from_windows(self) -> None:
        from types import SimpleNamespace
        from pathlib import Path
        # A scratch home names no command, whatever the machine.
        self.host = homes.Host(homes.WSL, {"PATH": ""}, ("/mnt/c",))
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn(", run: ", out)
        done = SimpleNamespace(written=(), errors=[])
        wanted = SimpleNamespace(changed=False, target=None)
        # From WSL, a clone on a Windows drive.
        wsl = SimpleNamespace(
            host=homes.Host(homes.WSL, {"PATH": ""}, ("/mnt/c", "/mnt/d")), clone=Path("/mnt/d/ai skills"),
            project=Path("/mnt/c/proj"), scratch=False,
        )
        self.assertEqual(
            program._after(wsl, None, wanted, done),
            ["", 'for windows, run: py -3 "D:\\ai skills\\tools\\setup\\setup.py" C:\\proj'],
        )
        # From WSL, a project in the Linux file system: Windows reads it by no path, so none is named.
        wsl.project = Path("/home/me/proj")
        self.assertEqual(
            program._after(wsl, None, wanted, done),
            ["", 'for windows, run: py -3 "D:\\ai skills\\tools\\setup\\setup.py"'],
        )
        # From WSL, a clone in the Linux file system: the Windows side cannot read it.
        wsl.clone = Path("/home/me/clone")
        self.assertEqual(program._after(wsl, None, wanted, done), [])
        # A refused run gets none.
        wsl.clone = Path("/mnt/d/ai skills")
        self.assertEqual(program._after(wsl, None, wanted, SimpleNamespace(written=(), errors=["x"])), [])
        # From Windows (the run itself is refused here for a clone off a drive).
        windows = SimpleNamespace(
            host=homes.Host(homes.WINDOWS), clone=Path("C:/clone"), project=Path("C:/proj"), scratch=False,
        )
        with mock.patch.object(homes, "clone_standing", return_value=SimpleNamespace(shared=True)):
            windows.clone = Path("/mnt/d/ai skills")
            windows.project = Path("/mnt/c/proj")
            self.assertEqual(
                program._after(windows, None, wanted, done),
                ["", "for wsl, run: python3 '/mnt/d/ai skills/tools/setup/setup.py' /mnt/c/proj"],
            )
        self.assertNotIn(", run: ", self.setup("--dry-run", str(self.project))[1])

    def test_paths_between_the_sides(self) -> None:
        self.assertEqual(render._windows_path("/mnt/d/proj"), "D:\\proj")
        self.assertEqual(render._wsl_path("D:\\proj"), "/mnt/d/proj")
        self.assertEqual(render._wsl_path("C:\\"), "/mnt/c")
        self.assertEqual(render._wsl_path("\\\\wsl.localhost\\Ubuntu\\home\\me\\x"), "/home/me/x")
        self.assertEqual(render._wsl_path("/home/me"), "/home/me")


    # The adversarial review of Phase 4: a relative DIR, a refused install that
    # writes nothing, a git that fails, a file taken out again.

    def test_a_relative_dir_is_the_same_project_on_both_sides(self) -> None:
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.project.parent)
        code, out, err = self.setup("--yes", "--manager-default", self.project.name)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("  git add -- .agents/workflow.toml .claude/settings.json", out)
        self.assertTrue((self.project / ".agents" / "workflow.toml").is_file())
        os.chdir(self.project)
        code, out, err = self.setup("--yes", "--no-manager-default", ".")
        self.assertEqual((code, err), (0, ""), out)

    def test_a_refused_install_writes_no_settings_and_a_later_run_sets_the_keys(self) -> None:
        self.claude.mkdir(exist_ok=True)
        conflict = self.claude_skills / "alpha"
        conflict.mkdir(parents=True)
        (conflict / "mine.txt").write_text("mine", encoding="utf-8")
        before = (self.settled(), tree(self.project))
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual(code, 2, out)
        self.assertIn("a directory of its own", err)
        self.assertEqual((self.settled(), tree(self.project)), before)
        self.assertFalse((self.project / ".agents" / "workflow.toml").exists())
        shutil.rmtree(conflict)
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        settings = json.loads((self.project / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings.get("agent"), "lead")

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_a_git_that_fails_for_another_reason_does_not_edit_a_tracked_file(self) -> None:
        self.track_config()
        before = self.config.read_bytes()
        self.git("config", "user.email", "a@b")
        # Not the repository's owner: git exits 128, which is no answer.
        with mock.patch.dict(os.environ, {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}):
            self.assertIsNone(gitrepo.tracked(self.project, self.CODEX_CONFIG))
            # Nor is it an answer for a subdirectory of the repository.
            (self.project / "sub").mkdir()
            self.assertIsNone(gitrepo.tracked(self.project / "sub", self.CODEX_CONFIG))
            code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertIn("was not checked", out)
        # A directory with no repository at all is not tracked.
        with mock.patch.object(gitrepo.os.path, "lexists", return_value=False):
            self.assertIs(gitrepo.tracked(self.project.parent, "x"), False)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_a_file_taken_out_again_is_listed_only_if_git_tracks_it(self) -> None:
        code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        code, out, err = self.setup("--yes", "--no-manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertFalse((self.project / ".claude" / "settings.json").exists())
        self.assertNotIn("settings.json", out.partition("git add")[2])

    def test_the_json_settings_hold_the_install_lists(self) -> None:
        self.write(self.project_file, 'install = ["alpha"]\n')
        code, out, err = self.setup("--dry-run", "--json", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        held = json.loads(out)["settings"]["install"]
        self.assertEqual([entry["value"] for entry in held][-1], ["alpha"])
        self.assertEqual(held[-1]["file"], str(self.project_file))


class DryRunTests(ProgramCase):
    def test_a_dry_run_writes_nothing_and_shows_the_plan(self) -> None:
        before = self.settled()
        code, out, err = self.setup("--dry-run", "--provider", "claude-code")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("dry run: nothing is changed", out)
        self.assertIn("alpha", out)
        self.assertEqual(self.settled(), before)
        self.assertNothingAt(self.claude)

    def test_a_dry_run_needs_no_yes(self) -> None:
        self.claude.mkdir()
        self.assertEqual(self.setup("--dry-run")[0], 0)


class JsonTests(ProgramCase):
    def test_json_is_one_object_of_settings_and_the_install_report(self) -> None:
        code, out, err = self.setup("--yes", "--json", "--provider", "claude-code")
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(list(report), ["schema_version", "settings", "install"])
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["settings"]["process.density"]["layer"], "shipped")
        self.assertEqual(report["install"]["exit_code"], 0)
        self.assertFalse(report["install"]["dry_run"])
        self.assertIn("providers", report["install"])

    def test_json_of_a_dry_run(self) -> None:
        code, out, err = self.setup("--dry-run", "--json", "--provider", "codex")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(json.loads(out)["install"]["dry_run"])
        self.assertNothingAt(self.codex)

    def test_json_is_refused_with_the_screen(self) -> None:
        self.claude.mkdir()
        code, out, err = self.setup("--json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--json needs", err)


class CheckTests(ProgramCase):
    """``--check``: the checks, on the one parser."""

    def test_check_reports_and_writes_nothing(self) -> None:
        self.claude.mkdir()
        self.assertEqual(self.setup("--yes")[0], 0)
        before = self.settled()
        code, out, err = self.setup("--check", "--no-versions", "--no-collab", "--skip", "models")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("check: setup itself writes nothing", out)
        self.assertIn("summary: 0 errors", out)
        self.assertEqual(self.settled(), before)

    def test_check_json_and_exit_1_on_an_error(self) -> None:
        self.claude.mkdir()
        self.assertEqual(self.setup("--yes")[0], 0)
        (self.claude_skills / "alpha").unlink()
        code, out, err = self.setup("--check", "--json", "--only", "links")
        self.assertEqual((code, err), (1, ""), out)
        self.assertEqual(json.loads(out)["exit_code"], 1)

    def test_check_with_dir_checks_the_project(self) -> None:
        self.claude.mkdir()
        code, out, err = self.setup("--check", "--only", "sources", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"project: {self.project}", out)

    def test_check_refuses_what_writes_and_the_check_options_need_it(self) -> None:
        for argv in (("--check", "--yes"), ("--check", "--dry-run"), ("--check", "--docs-dir", "x"), ("--check", "--provider", "codex")):
            code, out, err = self.setup(*argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertIn("--check writes nothing and takes no", err)
        for option in ("--no-versions", "--no-collab", "--codex-probe"):
            code, out, err = self.setup("--yes", option)
            self.assertEqual(code, 2, option)
            self.assertIn("are for --check", err)
        code, out, err = self.setup("--check", "--only", "nothing")
        self.assertEqual(code, 2)
        self.assertIn("nothing: not a check", err)


class UninstallTests(ProgramCase):
    """``--uninstall``: the old ``uninstall`` on the one parser."""

    def test_uninstall_takes_back_a_home_and_a_project(self) -> None:
        self.claude.mkdir()
        start = self.settled()
        self.assertEqual(self.setup("--yes", str(self.project))[0], 0)
        self.assertNotEqual(self.settled(), start)
        code, out, err = self.setup("--uninstall", "--dry-run", "--json", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(json.loads(out)["scope"], "project")
        code, out, err = self.setup("--uninstall", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        code, out, err = self.setup("--uninstall")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.settled(), start)

    def test_uninstall_refuses_what_installs_and_its_options_need_it(self) -> None:
        for argv in (("--uninstall", "--provider", "codex"), ("--uninstall", "--docs-dir", "x"), ("--uninstall", "--check"),
                     ("--uninstall", "--overwrite-edited"), ("--uninstall", "--only", "links")):
            code, out, err = self.setup(*argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertRegex(err, "takes no|writes nothing")
        for option in ("--keep-settings", "--discard-backups"):
            code, out, err = self.setup("--yes", option)
            self.assertEqual(code, 2, option)
            self.assertIn("are for --uninstall", err)
        code, out, err = self.setup("--uninstall", "--yes")
        self.assertEqual(code, 2)
        self.assertIn("--yes: only confirms --discard-backups", err)


class PlacesTests(ProgramCase):
    """``--home`` and ``DIR``: what is refused, and never a traceback. Each
    run is a dry run that names a provider, so that the settings files are
    read and nothing else is needed."""

    def run_setup(self, *argv: str) -> tuple[int, str, str]:
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            return support.setup("--dry-run", "--provider", "claude-code", *argv)

    def refused(self, *argv: str) -> str:
        code, out, err = self.run_setup(*argv)
        self.assertEqual((code, out), (2, ""), err)
        self.assertNotIn("Traceback", err)
        # A fault of a settings file is followed by the line that says nothing was changed.
        err = err.removesuffix("error: setup changes nothing while a settings file has a fault; correct the file first\n")
        self.assertEqual(err.count("\n"), 1, err)
        self.assertTrue(err.startswith("error: "), err)
        return err[len("error: "):-1]

    def test_an_empty_home_is_refused_and_is_not_the_real_home(self) -> None:
        with mock.patch.object(Path, "home", side_effect=AssertionError("the real home was asked for")):
            self.assertEqual(
                self.refused("--home", ""),
                "--home: an empty value is not a directory; name one, or leave the option out",
            )
            self.assertTrue(self.refused("--home", "  ").startswith("--home: an empty value"))
            self.assertTrue(self.refused("--home=").startswith("--home: an empty value"))

    def test_an_empty_dir_is_refused_and_is_not_the_working_directory(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "from-the-working-directory"\n')
        before = os.getcwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, before)
        self.assertEqual(
            self.refused("--home", str(self.home), ""),
            "DIR: an empty value is not a directory; name one, or leave the option out",
        )

    def test_a_user_that_does_not_exist(self) -> None:
        # Linux cannot expand the name. Windows guesses a directory beside
        # the user's own, which is then not there. Either way: one line.
        unknown = "the home directory of that user cannot be found"
        self.assertIn(
            self.refused("--home", "~no-such-user-here/x"),
            (f"--home: ~no-such-user-here/x: {unknown}", "--home: ~no-such-user-here/x: not a directory"),
        )
        self.assertIn(
            self.refused("--home", str(self.home), "~no-such-user-here"),
            (f"DIR: ~no-such-user-here: {unknown}", "DIR: ~no-such-user-here: not a directory"),
        )

    def test_a_home_that_cannot_be_expanded(self) -> None:
        with mock.patch.object(Path, "expanduser", side_effect=RuntimeError("Could not determine home directory.")):
            self.assertEqual(
                self.refused("--home", "~someone/x"),
                "--home: ~someone/x: the home directory of that user cannot be found",
            )
            self.assertEqual(
                self.refused("--home", str(self.home), "~someone"),
                f"--home: {self.home}: the home directory of that user cannot be found",
            )

    def test_no_home_given_and_none_to_be_found(self) -> None:
        for error in (RuntimeError("Could not determine home directory."), KeyError("getpwuid(): uid not found")):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(Path, "home", side_effect=error):
                    self.assertEqual(
                        self.refused(), "the user's home directory cannot be found; name one with --home DIR"
                    )

    def test_without_home_the_users_own_is_used(self) -> None:
        with mock.patch.object(Path, "home", return_value=self.home):
            self.write(self.user_file, '[process]\ndocs_dir = "mine"\n')
            code, out, err = self.run_setup("--json")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(json.loads(out)["settings"]["process.docs_dir"]["value"], "mine")

    def test_agents_that_is_a_regular_file_is_an_error_naming_it(self) -> None:
        agents = self.write(self.home / ".agents", "not a directory\n")
        self.assertEqual(
            self.refused("--home", str(self.home)),
            f"{agents}: is not a directory; workflow.toml is looked for in it",
        )
        agents.unlink()
        agents = self.write(self.project / ".agents", "")
        self.assertTrue(
            self.refused("--home", str(self.home), str(self.project)).startswith(f"{agents}: is not a directory")
        )

    def test_a_directory_where_a_settings_file_belongs(self) -> None:
        self.user_file.mkdir(parents=True)
        self.assertEqual(self.refused("--home", str(self.home)), f"{self.user_file}: is not a file")

    def link(self, target: Path, link: Path) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are not permitted here: {exc}")

    def test_a_dangling_link_where_a_settings_file_belongs(self) -> None:
        for file in (self.user_file, self.project_file, self.local_file):
            with self.subTest(file=file.name):
                self.link(self.root / "gone.toml", file)
                self.assertEqual(
                    self.refused("--home", str(self.home), str(self.project)),
                    f"link target missing: {file}",
                )
                file.unlink()

    def test_a_link_that_leads_back_to_itself(self) -> None:
        self.link(self.user_file, self.user_file)
        self.assertEqual(self.refused("--home", str(self.home)), f"link target missing: {self.user_file}")

    def test_a_link_to_a_real_file_is_read(self) -> None:
        real = self.write(self.home / "real.toml", '[process]\ndocs_dir = "linked"\n')
        self.link(real, self.user_file)
        code, out, err = self.run_setup("--json", "--follow-config-symlinks", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(json.loads(out)["settings"]["process.docs_dir"]["value"], "linked")

    def test_a_dangling_link_as_the_agents_directory(self) -> None:
        self.link(self.root / "gone", self.home / ".agents")
        self.assertEqual(self.refused("--home", str(self.home)), f"link target missing: {self.home / '.agents'}")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no FIFOs here")
    def test_a_fifo_where_a_settings_file_belongs_is_not_opened(self) -> None:
        self.user_file.parent.mkdir(parents=True)
        os.mkfifo(self.user_file)
        self.assertEqual(self.refused("--home", str(self.home)), f"{self.user_file}: is not a file")

    @unittest.skipUnless(support.can_lock_directories(), "permissions do not keep this process out")
    def test_directories_that_cannot_be_read(self) -> None:
        agents = self.home / ".agents"
        agents.mkdir()
        locked = self.root / "locked"
        (locked / ".agents").mkdir(parents=True)
        cases = [
            (agents, ["--home", str(self.home)], f"{self.user_file}: cannot be read: "),
            (locked, ["--home", str(self.home), str(locked)], f"{locked / '.agents'}: cannot be read: "),
            (
                locked / ".agents",
                ["--home", str(self.home), str(locked)],
                f"{locked / '.agents' / 'workflow.toml'}: cannot be read: ",
            ),
        ]
        for directory, argv, expected in cases:
            with self.subTest(directory=directory):
                os.chmod(directory, 0)
                try:
                    self.assertTrue(self.refused(*argv).startswith(expected))
                finally:
                    os.chmod(directory, 0o755)

    @unittest.skipUnless(support.can_lock_directories(), "permissions do not keep this process out")
    def test_a_settings_file_that_cannot_be_read(self) -> None:
        self.write(self.user_file, "[process]\n")
        os.chmod(self.user_file, 0)
        self.assertTrue(self.refused("--home", str(self.home)).startswith(f"{self.user_file}: cannot be read: "))

    def test_home_ignores_the_variables_for_the_homes(self) -> None:
        elsewhere = self.root / "elsewhere"
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(elsewhere), "CODEX_HOME": str(elsewhere)}):
            code, out, err = self.run_setup("--json", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("elsewhere", out)


class BackstopTests(ProgramCase):
    """What no module turned into a ``SetupError`` still ends in one line."""

    def test_an_os_error_names_the_file(self) -> None:
        error = PermissionError(13, "Permission denied", "/some/where/file.toml")
        with mock.patch.object(locations, "from_args", side_effect=error):
            self.assertEqual(self.setup("--dry-run"), (2, "", "error: /some/where/file.toml: Permission denied\n"))

    def test_an_os_error_without_a_file(self) -> None:
        with mock.patch.object(locations, "from_args", side_effect=OSError(28, "No space left on device")):
            self.assertEqual(self.setup("--dry-run"), (2, "", "error: No space left on device\n"))

    def test_a_recursion_error(self) -> None:
        with mock.patch.object(locations, "from_args", side_effect=RecursionError("too deep")):
            self.assertEqual(self.setup("--dry-run"), (2, "", "error: the input is nested too deeply to read\n"))

    def test_a_broken_pipe_is_left_to_the_entry_point(self) -> None:
        with mock.patch.object(locations, "from_args", side_effect=BrokenPipeError(32, "Broken pipe")):
            with self.assertRaises(BrokenPipeError):
                cli.main(["--dry-run", "--home", str(self.home)], program.main)


class EntryPointTests(ProgramCase):
    """``setup.py`` run by path, as a child process, from another directory:
    the tool copied into the fake clone, so the output is the fixtures'."""

    def setUp(self) -> None:
        super().setUp()
        self.claude.mkdir()
        self.script = self.install_tool()

    def child(self, *argv: str, cwd=None, script=None, **options) -> subprocess.CompletedProcess:
        options.setdefault("capture_output", True)
        options.setdefault("stdin", subprocess.DEVNULL)
        return subprocess.run(
            [sys.executable, "-B", str(script or self.script), *argv],
            cwd=cwd or self.root,
            env=support.child_environment(),
            timeout=60,
            **options,
        )

    def test_json_from_a_child_process(self) -> None:
        done = self.child("--dry-run", "--json", "--home", str(self.home), str(self.project))
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertIn("settings", json.loads(done.stdout.decode("utf-8")))

    def test_a_dry_run_from_another_working_directory(self) -> None:
        done = self.child("--dry-run", "--json", "--home", str(self.home))
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        report = json.loads(done.stdout.decode("utf-8"))
        self.assertEqual(report["settings"]["process.questions"]["value"], "all-together")

    def test_the_repositorys_own_script_runs(self) -> None:
        done = self.child("--dry-run", "--provider", "claude-code", "--home", str(self.home), script=support.SETUP_SCRIPT)
        self.assertEqual((done.returncode, done.stderr), (0, b""))

    def test_the_project_is_not_taken_from_the_working_directory(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "p"\n')
        here = self.child("--dry-run", "--json", "--home", str(self.home), cwd=self.project)
        self.assertEqual(json.loads(here.stdout)["settings"]["process.docs_dir"]["value"], "docs")
        named = self.child("--dry-run", "--json", "--home", str(self.home), ".", cwd=self.project)
        self.assertEqual(json.loads(named.stdout)["settings"]["process.docs_dir"]["value"], "p")

    def test_output_is_utf8_with_line_feeds_whatever_the_locale(self) -> None:
        home = self.root / "hôme café中"
        (home / ".claude").mkdir(parents=True)
        env = {key: value for key, value in os.environ.items() if not key.startswith(("LC_", "PYTHON"))}
        env.update({"LANG": "C", "LC_ALL": "C", "PYTHONIOENCODING": "ascii"})
        done = subprocess.run(
            [sys.executable, "-B", str(self.script), "--dry-run", "--home", str(home)],
            cwd=self.root, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
        )
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertIn("café中".encode("utf-8"), done.stdout)
        self.assertNotIn(b"\r", done.stdout)

    def test_an_error_has_no_traceback_and_exit_code_two(self) -> None:
        self.write(self.user_file, "[process]\ndocs_dir = 1\n")
        done = self.child("--dry-run", "--home", str(self.home))
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertEqual(
            done.stderr.decode("utf-8"),
            f"error: {self.user_file}: process.docs_dir: expected a string, got an integer\n"
            "error: setup changes nothing while a settings file has a fault; correct the file first\n",
        )

    def test_a_run_writes_no_bytecode_into_the_clone(self) -> None:
        """The shared clone is changed only by ``git pull``."""
        done = self.child("--dry-run", "--home", str(self.home))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([str(found) for found in self.clone.rglob("__pycache__")], [])
        self.assertEqual([str(found) for found in self.clone.rglob("*.pyc")], [])

    def test_a_settings_file_nested_thousands_deep(self) -> None:
        self.write(self.user_file, "[process]\nx = " + "[" * 5000 + "]" * 5000 + "\n")
        done = self.child("--dry-run", "--home", str(self.home))
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertEqual(
            done.stderr.decode("utf-8"),
            f"error: {self.user_file}: is not valid TOML: arrays or inline tables are nested too deeply\n"
            "error: setup changes nothing while a settings file has a fault; correct the file first\n",
        )

    def test_a_closed_stdout_is_an_error_and_not_an_empty_success(self) -> None:
        wrapper = (
            "import runpy, sys\n"
            "sys.stdout.close()\n"
            f"sys.argv = [{str(self.script)!r}, '--dry-run', '--home', {str(self.home)!r}]\n"
            f"runpy.run_path({str(self.script)!r}, run_name='__main__')\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", wrapper], cwd=self.root, env=support.child_environment(),
            capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
        )
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertEqual(done.stderr, b"error: the output cannot be written: standard output is closed\n")

    @unittest.skipUnless(os.path.exists("/dev/full"), "no full device here")
    def test_a_full_device_is_an_error_and_not_a_success(self) -> None:
        with open("/dev/full", "w") as full:
            done = self.child("--dry-run", "--home", str(self.home), stdout=full, stderr=subprocess.PIPE, capture_output=False)
        self.assertEqual(done.returncode, 2)
        err = done.stderr.decode("utf-8")
        self.assertTrue(err.startswith("error: the output cannot be written: "), err)
        self.assertEqual(err.count("\n"), 1, err)

    def test_a_reader_that_went_away_is_quiet_and_not_a_success(self) -> None:
        # The child waits for a line on stdin, so the pipe it writes to is
        # closed before it writes.
        wrapper = (
            "import runpy, sys\n"
            "sys.stdin.readline()\n"
            f"sys.argv = [{str(self.script)!r}, '--dry-run', '--home', {str(self.home)!r}]\n"
            f"runpy.run_path({str(self.script)!r}, run_name='__main__')\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", wrapper], cwd=self.root, env=support.child_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        child.stdout.close()
        child.stdin.write(b"go\n")
        child.stdin.close()
        err = child.stderr.read()
        child.stderr.close()
        code = child.wait(timeout=60)
        self.assertNotIn(b"Traceback", err)
        self.assertNotIn(b"Exception ignored", err)
        if os.name == "posix":
            self.assertEqual((code, err), (EXIT_PIPE, b""))
        else:
            # Windows reports the closed pipe as a failed write.
            self.assertIn(code, (EXIT_PIPE, 2))


class ScriptTests(unittest.TestCase):
    def test_the_script_runs_by_path_and_prints_its_help(self) -> None:
        done = subprocess.run(
            [sys.executable, "-B", str(support.SETUP_SCRIPT), "--help"], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, env=support.child_environment(), timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("usage: setup.py", done.stdout)
        self.assertIn("--provider", done.stdout)


if __name__ == "__main__":
    unittest.main()
