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
from unittest import mock

import provider_stub
import support
import test_definitions
from test_render import tree
from wfsetup import dictionary, gitrepo, homes, program, render


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
        code, out, err = self.setup()
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertEqual(self.settled(), before)

    def test_an_old_key_stops_and_writes_nothing(self) -> None:
        self.claude.mkdir()
        self.write(self.user_file, '[setup]\nenabled = ["alpha"]\n')
        before = self.settled()
        code, out, err = self.setup("--yes")
        self.assertEqual(code, 2)
        self.assertIn("setup.enabled", err)
        self.assertIn("install in ~/.agents/workflow.toml", err)
        self.assertIn(str(self.user_file), err)
        self.assertEqual(self.settled(), before)

    def test_an_old_key_in_the_project_stops_too(self) -> None:
        self.claude.mkdir()
        self.write(self.project_file, '[project]\nenabled = ["alpha"]\n')
        before = self.settled()
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("project.enabled", err)
        self.assertEqual(self.settled(), before)
        self.assertFalse((self.project / ".agents" / "workflow-setup").exists())

    def test_a_source_problem_stops_the_run(self) -> None:
        self.claude.mkdir()
        self.write(self.clone / "alpha" / "SKILL.md", "no front matter\n")
        before = self.settled()
        code, out, err = self.setup("--yes")
        self.assertEqual(code, 2)
        self.assertIn("alpha", err)
        self.assertEqual(self.settled(), before)

    def test_a_bad_dir_is_named_dir_and_render_keeps_its_option(self) -> None:
        self.claude.mkdir()
        missing = str(self.root / "nowhere")
        code, out, err = self.setup("--yes", missing)
        self.assertEqual(code, 2)
        self.assertIn(f"DIR: {missing}: not a directory", err)
        self.assertNotIn("--project", err)
        code, out, err = self.render("--project", missing)
        self.assertIn(f"--project: {missing}: not a directory", err)

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

    def test_a_default_turned_off_by_hand_leaves_them_until_a_run_writes_the_file(self) -> None:
        self.assertEqual(self.setup("--yes", "--manager-default", str(self.project))[0], 0)
        data, entry = self.settings.read_bytes(), self.record_entry()
        self.write(self.project_file, "[roles]\nmanager_default = false\n")
        code, out, err = self.setup("--yes", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual((self.settings.read_bytes(), self.record_entry()), (data, entry))
        self.assertTrue(self.left_note(out), out)


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
        self.assertIn("was not checked: git could not be started", out)
        self.assertIn("will not start as lead", out)

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
            code, out, err = self.setup("--yes", "--manager-default", str(self.project))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertIn("was not checked", out)
        # A directory with no repository is not tracked.
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
