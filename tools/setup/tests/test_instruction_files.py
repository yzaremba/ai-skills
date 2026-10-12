"""Tests for the check ``instruction-files`` of ``doctor --project DIR``:
whether both providers load the project's ``AGENTS.md`` (R7.3, R7.4, R8.5).

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

Every project is a scratch directory, and so is the home. The walk upward
from a project stops below the system's temporary directory (``support``).
"""
from __future__ import annotations

import json
import os
import shutil
import types
import unittest
from pathlib import Path
from unittest import mock

import support
from fileops_support import SYMLINKS
from test_doctor import SECRET, DoctorCase, snapshot
from wfsetup import doctor, homes, instructions

CHECK = instructions.NAME
INDEX = "# Project\n\n## Project memory\n\n- [A lesson](docs/memory/a-lesson.md): always; do it\n"
SETTING_ON = {"options": {"instructionFiles": "claude-md-and-agents-md"}}


class InstructionCase(DoctorCase):
    def setUp(self) -> None:
        super().setUp()
        self.agents = self.write(self.project / "AGENTS.md", INDEX)
        self.user_settings = self.claude / "settings.json"

    def found(self, *argv: str, project: Path | None = None) -> tuple[int, list[dict]]:
        return self.only(CHECK, "--project", str(project or self.project), *argv)

    def settings(self, file: Path, ident: str, value: object = None) -> None:
        self.write(file, json.dumps({
            "theme": SECRET, "pluginConfigs": {ident: SETTING_ON if value is None else value, "other@x": SECRET},
        }))

    def assertLoaded(self, findings: list[dict]) -> None:
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.OK, "claude-code:", "AGENTS.md")


class ClaudeFilesCase(InstructionCase):
    """For each of the three files: with the file and no remedy the project
    fails, and it passes once the import is added."""

    def one(self, file: Path, line: str) -> None:
        self.write(file, "# Mine\n\nSome instructions.\n")
        code, findings = self.found()
        self.assertEqual(code, 1)
        detail = self.assertFinding(findings, doctor.ERROR, str(file), "is not loaded", "neither remedy")
        # The message gives the line to add, and the setting.
        self.assertIn(f"`{line}`", detail)
        self.assertIn('pluginConfigs."agents-md@builtin".options.instructionFiles', detail)
        self.assertIn(str(self.user_settings), detail)

        self.write(file, f"# Mine\n\n{line}\n\nSome instructions.\n")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertLoaded(findings)
        self.assertFinding(findings, doctor.OK, "through the import in", str(file))

    def test_claude_md(self) -> None:
        self.one(self.project / "CLAUDE.md", "@AGENTS.md")

    def test_dot_claude_claude_md(self) -> None:
        self.one(self.project / ".claude" / "CLAUDE.md", "@../AGENTS.md")

    def test_claude_local_md(self) -> None:
        self.one(self.project / "CLAUDE.local.md", "@AGENTS.md")

    def test_a_file_in_a_directory_above_the_project(self) -> None:
        self.one(self.root / "CLAUDE.md", "@project/AGENTS.md")

    def test_none_of_the_three_is_fine(self) -> None:
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertLoaded(findings)
        self.assertFinding(findings, doctor.OK, "reads", "directly", "2.1.277", "2.1.281")

    def test_one_file_that_imports_is_enough_for_all(self) -> None:
        self.write(self.project / "CLAUDE.md", "@AGENTS.md\n")
        self.write(self.project / "CLAUDE.local.md", "My own notes.\n")
        self.assertLoaded(self.found()[1])

    def test_the_users_own_claude_md_does_not_count(self) -> None:
        project = self.home / "work"
        self.write(project / "AGENTS.md", INDEX)
        self.write(self.claude / "CLAUDE.md", "My own instructions.\n")
        code, findings = self.found(project=project)
        self.assertEqual(code, 0)
        self.assertLoaded(findings)
        # A CLAUDE.md beside the home's .claude directory does.
        self.write(self.home / "CLAUDE.md", "In the home directory.\n")
        code, findings = self.found(project=project)
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, str(self.home / "CLAUDE.md"), "`@work/AGENTS.md`")

    @unittest.skipUnless(SYMLINKS, "needs symbolic links")
    def test_a_project_claude_md_that_is_a_link_to_the_users_own_counts(self) -> None:
        own = self.write(self.claude / "CLAUDE.md", "My own instructions.\n")
        for parts in (("CLAUDE.md",), (".claude", "CLAUDE.md"), ("CLAUDE.local.md",)):
            file = self.project.joinpath(*parts)
            file.parent.mkdir(exist_ok=True)
            os.symlink(own, file)
            code, findings = self.found()
            self.assertEqual(code, 1, parts)
            self.assertFinding(findings, doctor.ERROR, str(file), "neither remedy")
            os.remove(file)

    @unittest.skipUnless(SYMLINKS, "needs symbolic links")
    def test_the_users_own_claude_md_is_own_whatever_it_leads_to(self) -> None:
        project = self.home / "work"
        self.write(project / "AGENTS.md", INDEX)
        kept = self.write(self.root / "dotfiles" / "CLAUDE.md", "My own instructions.\n")
        os.symlink(kept, self.claude / "CLAUDE.md")
        code, findings = self.found(project=project)
        self.assertEqual(code, 0)
        self.assertLoaded(findings)

    def context(self, claude_home: Path) -> types.SimpleNamespace:
        provider = types.SimpleNamespace(home=claude_home)
        return types.SimpleNamespace(homes=types.SimpleNamespace(home=self.home, provider=lambda name: provider))

    def test_with_the_claude_home_elsewhere_the_homes_dot_claude_file_counts(self) -> None:
        project = self.home / "work"
        self.write(project / "AGENTS.md", INDEX)
        in_home = self.write(self.home / ".claude" / "CLAUDE.md", "In the home directory.\n")
        elsewhere = self.root / "claude-config"
        own = self.write(elsewhere / "CLAUDE.md", "My own instructions.\n")
        # The Claude Code home is ~/.claude: the file in it is the user's own.
        self.assertEqual(instructions.claude_files(self.context(self.home / ".claude"), project), [])
        # CLAUDE_CONFIG_DIR names another directory: ~/.claude/CLAUDE.md is an
        # ordinary .claude/CLAUDE.md of the home directory, above the project.
        self.assertEqual(instructions.claude_files(self.context(elsewhere), project), [in_home])
        # And the own file, in that home, is not counted for a project in it.
        inside = elsewhere / "proj"
        self.write(inside / "AGENTS.md", INDEX)
        self.assertEqual(instructions.claude_files(self.context(elsewhere), inside), [])
        self.assertTrue(own.is_file())

    def test_what_is_no_import_is_no_remedy(self) -> None:
        for text in (
            "Read `@AGENTS.md` first.\n",                    # a code span
            "```\n@AGENTS.md\n```\n",                        # a fenced block
            "~~~text\n@AGENTS.md\n~~~\n",
            "Read AGENTS.md before anything else.\n",        # words
            "@docs/AGENTS.md\n",                             # another file
            "mail me@AGENTS.md\n",                           # not at the start of a word
            "Text.\n\n    @AGENTS.md\n",                     # an indented code block: four spaces
            "Text.\n\n\t@AGENTS.md\n",                       # ... a tab
            "    @AGENTS.md\n",                              # ... at the start of the file
            "# Heading\n    @AGENTS.md\n",                   # ... after a heading
            "> ~~~\n> @AGENTS.md\n> ~~~\n",                  # a fence in a block quote
            "> ```\n> @AGENTS.md\n> ```\n",
            "1. x\n\n    ~~~\n    @AGENTS.md\n    ~~~\n",    # a fence in a list item
            "- x\n\n  ```\n  @AGENTS.md\n  ```\n",
            "- ```\n  @AGENTS.md\n  ```\n",
            ">     @AGENTS.md\n",                            # indented code in a block quote
            "<!-- @AGENTS.md -->\n",                         # an HTML comment
            "<!--\n@AGENTS.md\n-->\n",                       # ... of several lines
            "Text <!-- see\n\n@AGENTS.md\n\nlater --> more.\n",
            "<!-- never closed\n\n@AGENTS.md\n",
            # What only one order of reading would take for an import.
            "`<!--`\n```\n-->\n@AGENTS.md\n```\n",
            "x `\n<!--\n\n@AGENTS.md\n\n-->\n",
            # A fence that is not closed where a nearer reading would close it.
            "```\n- ```\n@AGENTS.md\n```\n",
            "```\n    ```\n@AGENTS.md\n```\n",
            "> ```\n\n> ```\n> @AGENTS.md\n> ```\n",
            "- ```\n  code\n```\n@AGENTS.md\n```\n",
            "1. x\n\n   ```\n   code\n```\n@AGENTS.md\n```\n",
            "``` a`b\ntext\n```\n@AGENTS.md\n```\n",         # no fence: a backtick in the info string
            # A code span pairs within its own paragraph, and its own list item.
            "a ` b\n\nc ` @AGENTS.md `\n",
            "- a ` b\n- c ` @AGENTS.md `\n",
            "one `\n@AGENTS.md\ntwo `\n",
            "\\` a ` @AGENTS.md `\n",
            "`` a ``` @AGENTS.md ``\n",
        ):
            self.write(self.project / "CLAUDE.md", text)
            code, findings = self.found()
            self.assertEqual(code, 1, text)
            self.assertFinding(findings, doctor.ERROR, "neither remedy")

    def test_an_import_is_found_where_claude_code_reads_one(self) -> None:
        for text in (
            "See @AGENTS.md for the rest.\n",
            "﻿@./AGENTS.md\n",
            "```\ncode\n```\n\n@AGENTS.md\n",
            f"@{self.agents}\n",                             # an absolute path
            "- First.\n- @AGENTS.md\n",                      # in a list item
            "- See:\n    - @AGENTS.md\n",
            "> @AGENTS.md\n",                                # in a block quote
            "Text that goes on\n    @AGENTS.md\n",           # an indented line that continues a paragraph
            "<!-- a note -->\n\n@AGENTS.md\n",               # after a comment
            "Run `make <target>` and see @AGENTS.md too.\n",  # beside a code span
            "1. Build:\n\n   ```\n   make\n   ```\n\n@AGENTS.md\n",   # after a fence in a list item
            "a ` b\n\n@AGENTS.md\n",                         # a backtick with no pair, a paragraph before
            "    code\n\nText.\n\n@AGENTS.md\n",             # after an indented code block
        ):
            self.write(self.project / "CLAUDE.md", text)
            code, findings = self.found()
            self.assertEqual(code, 0, text)
            self.assertLoaded(findings)

    @unittest.skipUnless(SYMLINKS, "needs symbolic links")
    def test_a_claude_md_that_is_a_link_to_agents_md_is_a_remedy(self) -> None:
        os.symlink("AGENTS.md", self.project / "CLAUDE.md")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertLoaded(findings)

    def test_a_project_without_agents_md_is_info(self) -> None:
        os.remove(self.agents)
        self.write(self.project / "CLAUDE.md", "Mine.\n")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "no such file")

    def test_without_a_project_the_check_says_so(self) -> None:
        code, findings = self.only(CHECK)
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.INFO]))
        self.assertFinding(findings, doctor.INFO, "doctor --project DIR")

    def test_claude_code_not_installed_is_info(self) -> None:
        shutil.rmtree(self.claude)
        self.write(self.project / "CLAUDE.md", "Mine.\n")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.INFO, "claude-code: not installed")

    def test_the_check_writes_nothing_and_runs_with_the_others(self) -> None:
        self.write(self.project / "CLAUDE.md", "Mine.\n")
        before = snapshot(self.root)
        code, report = self.doctor(*self.project_arg)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(code, 1)
        by_name = {check["name"]: check["severity"] for check in report["checks"]}
        self.assertEqual(by_name[CHECK], doctor.ERROR)


class SettingCase(InstructionCase):
    """The other remedy: the user-level setting."""

    def setUp(self) -> None:
        super().setUp()
        self.write(self.project / "CLAUDE.local.md", "My own notes.\n")

    def test_the_setting_in_the_users_settings_is_a_remedy(self) -> None:
        self.assertEqual(self.found()[0], 1)
        self.settings(self.user_settings, instructions.PLUGIN_ID)
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertLoaded(findings)
        self.assertFinding(findings, doctor.OK, "claude-md-and-agents-md", str(self.user_settings))

    def both_ids(self, old: object, new: object) -> None:
        self.write(self.user_settings, json.dumps({"theme": SECRET, "pluginConfigs": {
            instructions.PLUGIN_ID: {"options": {"instructionFiles": old, "other": SECRET}},
            instructions.PLUGIN_ID_NEW: {"options": {"instructionFiles": new}},
        }}))

    def claude_ok(self, findings: list[dict]) -> list[str]:
        return [one for one in self.details(findings, doctor.OK) if one.startswith("claude-code")]

    def test_the_newer_plugin_id_alone_is_a_remedy_with_a_warning(self) -> None:
        self.settings(self.user_settings, instructions.PLUGIN_ID_NEW)
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertEqual(self.details(findings, doctor.ERROR), [])
        detail = self.assertFinding(
            findings, doctor.WARNING, "cc-plugin-agents-md@builtin", "alone", "before 2.1.285 ignores", "2.1.281",
        )
        self.assertIn('Set it under "agents-md@builtin"', detail)
        # A warning in place of the pass, not beside it.
        self.assertEqual(self.claude_ok(findings), [])

    def test_the_same_value_under_both_ids_is_a_remedy(self) -> None:
        self.both_ids("claude-md-and-agents-md", "claude-md-and-agents-md")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertLoaded(findings)

    def test_two_ids_that_disagree_are_no_remedy(self) -> None:
        for old, new in (("claude-md", "claude-md-and-agents-md"), ("claude-md-and-agents-md", "claude-md"),
                         ("claude-md-or-agents-md", "claude-md-and-agents-md"), ("claude-md-and-agents-md", 7)):
            self.both_ids(old, new)
            code, findings = self.found()
            self.assertEqual(code, 1, (old, new))
            self.assertFinding(findings, doctor.ERROR, "neither remedy")
            self.assertEqual(self.claude_ok(findings), [])
            detail = self.assertFinding(findings, doctor.WARNING, "the two ids disagree", "not counted as a remedy")
            self.assertIn(f'"{old}" under "agents-md@builtin"', detail)
            said = f'"{new}"' if isinstance(new, str) else "a value the setting does not take"
            self.assertIn(f'{said} under "cc-plugin-agents-md@builtin"', detail)
        # An import is a remedy all the same; the warning stays.
        self.write(self.project / "CLAUDE.local.md", "@AGENTS.md\n")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.OK, "through the import in")
        self.assertFinding(findings, doctor.WARNING, "the two ids disagree")

    def test_two_ids_that_disagree_with_managed_only_among_them(self) -> None:
        self.both_ids("claude-md-and-agents-md", "managed-only")
        code, findings = self.found()
        self.assertEqual(self.claude_ok(findings), [])
        self.assertFinding(findings, doctor.WARNING, "the two ids disagree")
        self.assertFinding(findings, doctor.WARNING, '"managed-only"', "is not loaded")

    def test_the_line_on_two_ids_prints_no_other_value(self) -> None:
        for old, new in ((SECRET, "claude-md-and-agents-md"), ("claude-md-and-agents-md", SECRET),
                         ({"deep": SECRET}, "claude-md"), ("claude-md", [SECRET])):
            self.both_ids(old, new)
            for argv in (("--json",), ()):
                code, out, err = self.run_doctor("--only", CHECK, *self.project_arg, *argv)
                self.assertEqual((code, err), (1, ""))
                self.assertIn("the two ids disagree", out)
                self.assertIn("a value the setting does not take", out)
                self.assertNotIn(SECRET, out)
                self.assertNotIn("sk-doctor", out)

    def test_the_setting_in_a_project_file_is_no_remedy(self) -> None:
        for parts in ((".claude", "settings.json"), (".claude", "settings.local.json")):
            file = self.project.joinpath(*parts)
            self.settings(file, instructions.PLUGIN_ID)
            code, findings = self.found()
            self.assertEqual(code, 1)
            self.assertFinding(findings, doctor.ERROR, "neither remedy", str(file), "ignores it")
            os.remove(file)

    def test_another_value_is_no_remedy(self) -> None:
        for value in ("claude-md-or-agents-md", "claude-md", "something", 7, None):
            self.settings(self.user_settings, instructions.PLUGIN_ID, {"options": {"instructionFiles": value}})
            self.assertEqual(self.found()[0], 1, value)
        self.settings(self.user_settings, instructions.PLUGIN_ID, "not a table")
        self.assertEqual(self.found()[0], 1)

    def test_no_other_value_of_the_settings_file_is_printed(self) -> None:
        self.settings(self.user_settings, instructions.PLUGIN_ID, {"options": {"instructionFiles": SECRET}})
        for argv in (("--json",), ()):
            code, out, err = self.run_doctor("--only", CHECK, *self.project_arg, *argv)
            self.assertEqual((code, err), (1, ""))
            self.assertNotIn(SECRET, out)
            self.assertNotIn("sk-doctor", out)

    def test_a_settings_file_that_cannot_be_read_is_a_warning_and_no_remedy(self) -> None:
        self.write(self.user_settings, f'{{"theme": "{SECRET}", broken')
        code, out, err = self.run_doctor("--only", CHECK, *self.project_arg)
        self.assertEqual((code, err), (1, ""))
        self.assertIn("is not a JSON object that can be read", out)
        self.assertNotIn(SECRET, out)

    def test_claude_md_only_warns_where_nothing_imports(self) -> None:
        os.remove(self.project / "CLAUDE.local.md")
        self.settings(self.user_settings, instructions.PLUGIN_ID, {"options": {"instructionFiles": "claude-md"}})
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, '"claude-md"', "is not loaded")
        self.write(self.project / "CLAUDE.md", "@AGENTS.md\n")
        self.assertLoaded(self.found()[1])


class CodexCase(InstructionCase):
    def test_an_override_file_in_the_project_root_warns(self) -> None:
        override = self.write(self.project / "AGENTS.override.md", "Use this instead.\n")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.WARNING, str(override), "replaces", "lesson index", "not loaded on Codex")
        os.remove(override)
        self.assertQuiet(self.found()[1])

    def test_an_empty_override_file_replaces_nothing(self) -> None:
        override = self.project / "AGENTS.override.md"
        override.write_bytes(b"")
        self.agents.write_bytes(b"x" * 100)
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertNotIn("replaces the", str(self.details(findings, doctor.INFO)).split("Once the file")[0])
        self.assertFinding(findings, doctor.INFO, str(override), "is empty", "first of the two files")
        # The same reading in the sum: the AGENTS.md beside it is the file counted.
        self.assertFinding(findings, doctor.OK, "codex:", "100 bytes together")

    def test_a_directory_named_as_the_override_file_is_no_file(self) -> None:
        os.mkdir(self.project / "AGENTS.override.md")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertNotIn("AGENTS.override.md", str(findings))

    @unittest.skipUnless(SYMLINKS, "needs symbolic links")
    def test_an_override_link_counts_as_what_it_leads_to(self) -> None:
        override = self.project / "AGENTS.override.md"
        os.symlink("nowhere", override)
        self.assertQuiet(self.found()[1])
        os.remove(override)
        self.write(self.project / "other.md", "Use this instead.\n")
        os.symlink("other.md", override)
        self.assertFinding(self.found()[1], doctor.WARNING, str(override), "replaces")

    def test_a_project_over_three_quarters_of_the_limit_warns(self) -> None:
        self.write(self.agents, INDEX + "x" * (24 * 1024))
        code, findings = self.found()
        self.assertEqual(code, 0)
        detail = self.assertFinding(findings, doctor.WARNING, "codex:", "over three quarters", "32,768")
        self.assertIn("project_doc_max_bytes is unset", detail)
        self.assertIn(str(self.agents), detail)

    def test_three_quarters_exactly_does_not_warn(self) -> None:
        self.agents.write_bytes(b"x" * (24 * 1024))
        code, findings = self.found()
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.OK, "codex:", "24,576", "32,768")
        self.agents.write_bytes(b"x" * (24 * 1024 + 1))
        self.assertFinding(self.found()[1], doctor.WARNING, "over three quarters")

    def test_the_files_are_counted_together(self) -> None:
        self.agents.write_bytes(b"x" * (13 * 1024))
        self.write(self.codex / "AGENTS.md", "y" * (13 * 1024))
        detail = self.assertFinding(self.found()[1], doctor.WARNING, "over three quarters", "26,624")
        self.assertIn(str(self.codex / "AGENTS.md"), detail)
        # In the Codex home an override that is not empty is the file taken.
        self.write(self.codex / "AGENTS.override.md", "short\n")
        self.assertQuiet(self.found()[1])

    def test_at_the_limit_the_warning_says_so(self) -> None:
        self.agents.write_bytes(b"x" * (32 * 1024))
        self.assertFinding(self.found()[1], doctor.WARNING, "at or over the limit", "not loaded")

    def test_the_limit_is_read_from_the_users_config(self) -> None:
        self.agents.write_bytes(b"x" * (30 * 1024))
        self.write(self.codex / "config.toml", f'model = "{SECRET}"\nproject_doc_max_bytes = 65536\n')
        code, out, err = self.run_doctor("--only", CHECK, *self.project_arg)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("0 warnings", out)
        self.assertIn("65,536 (project_doc_max_bytes in", out)
        self.assertNotIn(SECRET, out)
        self.write(self.codex / "config.toml", "project_doc_max_bytes = 4096\n")
        self.agents.write_bytes(b"x" * 3500)
        self.assertFinding(self.found()[1], doctor.WARNING, "over three quarters", "4,096", "project_doc_max_bytes in")

    def test_a_limit_that_is_no_size_is_a_warning(self) -> None:
        self.write(self.codex / "config.toml", f'project_doc_max_bytes = "{SECRET}"\n')
        code, out, err = self.run_doctor("--only", CHECK, *self.project_arg)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("is not a number of bytes", out)
        self.assertNotIn(SECRET, out)
        self.write(self.codex / "config.toml", "project_doc_max_bytes = 0\n")
        self.assertFinding(self.found()[1], doctor.WARNING, "project_doc_max_bytes = 0", "no room")

    def test_codex_not_installed_is_info(self) -> None:
        shutil.rmtree(self.codex)
        self.write(self.project / "AGENTS.override.md", "x\n")
        code, findings = self.found()
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "codex: not installed")


class ClaudeSizeCase(InstructionCase):
    def test_a_file_near_the_size_claude_code_skips_warns(self) -> None:
        self.agents.write_bytes(b"x" * (3 * 1024 * 1024 + 1))
        self.write(self.codex / "config.toml", "project_doc_max_bytes = 16777216\n")
        code, findings = self.found()
        self.assertEqual(code, 0)
        detail = self.assertFinding(findings, doctor.WARNING, "claude-code:", str(self.agents), "4 MiB")
        self.assertIn("over three quarters", detail)
        self.assertNotIn("is skipped", detail)

    def opened(self) -> tuple[list[str], mock._patch]:
        seen: list[str] = []
        real = instructions.fsio.read_bytes

        def read(path: Path) -> bytes:
            seen.append(str(path))
            return real(path)

        return seen, mock.patch.object(instructions.fsio, "read_bytes", read)

    def test_a_claude_md_over_the_size_is_skipped_and_its_import_is_no_remedy(self) -> None:
        file = self.project / "CLAUDE.md"
        file.write_bytes(b"@AGENTS.md\n" + b"x" * instructions.CLAUDE_FILE_LIMIT)
        seen, patch = self.opened()
        with patch:
            code, findings = self.found()
        self.assertEqual(code, 1)
        detail = self.assertFinding(findings, doctor.WARNING, "claude-code:", str(file), "4 MiB", "is skipped")
        self.assertNotIn("three quarters", detail)
        detail = self.assertFinding(findings, doctor.ERROR, "neither remedy", "over the size Claude Code skips")
        self.assertNotIn("through the import", str(findings))
        self.assertNotIn(str(file), seen)             # not opened
        # A second file within the size is the one the line goes into.
        other = self.write(self.project / "CLAUDE.local.md", "Mine.\n")
        detail = self.assertFinding(self.found()[1], doctor.ERROR, "neither remedy", f"to {other} ")
        self.assertNotIn("over the size", detail)
        self.write(other, "@AGENTS.md\n")
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.OK, "through the import in", str(other))
        self.assertFinding(findings, doctor.WARNING, str(file), "is skipped")

    def test_exactly_the_size_is_not_skipped(self) -> None:
        file = self.project / "CLAUDE.md"
        file.write_bytes(b"@AGENTS.md\n" + b"x" * (instructions.CLAUDE_FILE_LIMIT - 11))
        code, findings = self.found()
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.OK, "through the import in", str(file))
        self.assertFinding(findings, doctor.WARNING, str(file), "over three quarters")

    def test_an_agents_md_over_the_size_is_not_loaded_whatever_names_it(self) -> None:
        self.agents.write_bytes(b"x" * (instructions.CLAUDE_FILE_LIMIT + 1))
        self.write(self.codex / "config.toml", "project_doc_max_bytes = 16777216\n")
        for remedy in ("none", "import", "setting"):
            if remedy == "import":
                self.write(self.project / "CLAUDE.md", "@AGENTS.md\n")
            elif remedy == "setting":
                self.settings(self.claude / "settings.json", instructions.PLUGIN_ID)
            seen, patch = self.opened()
            with patch:
                code, findings = self.found()
            self.assertEqual(code, 1, remedy)
            self.assertFinding(findings, doctor.ERROR, "claude-code:", str(self.agents), "is not loaded", "skipped")
            self.assertEqual([one for one in findings if one["severity"] == doctor.OK
                              and one["detail"].startswith("claude-code")], [], remedy)
            self.assertNotIn(str(self.agents), seen)


class ImportsTests(unittest.TestCase):
    def test_the_paths_as_written(self) -> None:
        text = "@one.md and @two/three.md\n`@four`\n@Design\\ Docs/five.md\n``` \n@six\n```\nx@seven @~/eight.md\n"
        self.assertEqual(instructions.imports(text), ["one.md", "two/three.md", "Design Docs/five.md", "~/eight.md"])

    def test_what_is_code_or_a_comment_holds_no_import(self) -> None:
        for text, found in (
            ("@a\n\n    @b\n\n@c\n", ["a", "c"]),
            ("@a\n    @b\n", ["a", "b"]),                       # the paragraph goes on
            ("@a <!-- @b --> @c\n", ["a", "c"]),
            ("@a\n<!--\n@b\n-->\n@c\n", ["a", "c"]),
            ("@a\n\n> ~~~\n> @b\n> ~~~\n\n@c\n", ["a", "c"]),
            ("@a\n\n- x\n\n  ```\n  @b\n  ```\n\n@c\n", ["a", "c"]),
            ("@a\n\n> ~~~\n> @b\n\n@c\n", ["a"]),            # where the quote ended is not told: nothing after
            ("@a\n\n~~~\n@b\n", ["a"]),
            ("@a `x` @b `@c` @d\n", ["a", "b", "d"]),
            ("@a ` @b\n", ["a", "b"]),                          # one line: a backtick alone is a backtick
            ("@a ` x\n@b\n", []),                              # several: the block is left out
            ("@a\r\n\r\n    @b\r\n", ["a"]),
        ):
            self.assertEqual(instructions.imports(text), found, text)


if __name__ == "__main__":
    unittest.main()
