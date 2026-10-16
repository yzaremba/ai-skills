"""Tests for the ``show`` command and for the command line as a whole.

Exact output is tested on the fake clone of ``support.ScratchCase``; the
repository's own defaults are tested in ``RepositoryTests``, by what holds
whatever they say.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import support
from wfsetup import cli, locations, schema
from wfsetup.errors import EXIT_PIPE

PROCESS_TEXT = (
    'process.docs_dir = "docs"  (shipped)\n'
    'process.questions = "one-at-a-time"  (shipped)\n'
    "process.recommend = true  (shipped)\n"
)
ROLES_TEXT = (
    "roles.enabled = true  (shipped)\n"
    "roles.manager_default = false  (shipped)\n"
    "roles.high_stakes = false  (shipped)\n"
    "roles.max_parallel_coders = 3  (shipped)\n"
)
MEMORY_TEXT = 'memory.dir = "docs/memory"  (shipped)\n'
SETUP_TEXT = "setup.allow_unshared_clone = false  (shipped)\n"
SHIPPED_TEXT = PROCESS_TEXT + ROLES_TEXT + MEMORY_TEXT + support.SHIPPED_PROVIDERS_TEXT + SETUP_TEXT


class ShowTextTests(support.ScratchCase):
    def test_the_shipped_defaults(self) -> None:
        self.assertEqual(self.show(), (0, SHIPPED_TEXT, ""))
        self.assertEqual(self.show(project=False), (0, SHIPPED_TEXT, ""))

    def test_every_layer_is_named(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "u"\n[roles.coder]\ntier = "deep"\n')
        self.write(self.project_file, "[roles]\nmax_parallel_coders = 2\n")
        self.write(self.local_file, '[memory]\ndir = "notes/memory"\n')
        code, out, err = self.show()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            'process.docs_dir = "u"  (user)\n'
            'process.questions = "one-at-a-time"  (shipped)\n'
            "process.recommend = true  (shipped)\n"
            "roles.enabled = true  (shipped)\n"
            "roles.manager_default = false  (shipped)\n"
            "roles.high_stakes = false  (shipped)\n"
            "roles.max_parallel_coders = 2  (project)\n"
            'roles.coder.tier = "deep"  (user)\n'
            'memory.dir = "notes/memory"  (local)\n' + support.SHIPPED_PROVIDERS_TEXT + SETUP_TEXT,
        )

    def test_a_group(self) -> None:
        self.assertEqual(self.show("process")[1], PROCESS_TEXT)
        self.assertEqual(self.show("memory")[1], MEMORY_TEXT)

    def test_a_dotted_key(self) -> None:
        self.assertEqual(self.show("process.docs_dir"), (0, 'process.docs_dir = "docs"  (shipped)\n', ""))
        self.assertEqual(self.show("roles.max_parallel_coders")[1], "roles.max_parallel_coders = 3  (shipped)\n")

    def test_a_table_inside_a_group(self) -> None:
        self.write(self.project_file, '[roles.coder]\ntier = "deep"\neffort = "high"\n[roles.coder-hard]\ntier = "frontier"\n')
        self.assertEqual(
            self.show("roles.coder")[1],
            'roles.coder.tier = "deep"  (project)\nroles.coder.effort = "high"  (project)\n',
        )
        self.assertEqual(self.show("roles.coder-hard.tier")[1], 'roles.coder-hard.tier = "frontier"  (project)\n')

    def test_a_valid_key_that_no_layer_sets_prints_nothing(self) -> None:
        self.assertEqual(self.show("roles.coder.tier"), (0, "", ""))
        self.assertEqual(self.show("providers.codex.role_models"), (0, "", ""))
        self.assertEqual(self.show("providers.no-such-provider"), (0, "", ""))

    def test_providers_prints_the_dictionaries_mappings(self) -> None:
        self.assertEqual(self.show("providers"), (0, support.SHIPPED_PROVIDERS_TEXT, ""))
        self.assertEqual(self.show("providers", project=False), (0, support.SHIPPED_PROVIDERS_TEXT, ""))
        self.assertEqual(
            self.show("providers.codex.tiers"),
            (
                0,
                'providers.codex.tiers.fast = "gpt-6-luna"  (shipped)\n'
                'providers.codex.tiers.standard = "gpt-6.1-sol"  (shipped)\n'
                'providers.codex.tiers.deep = "gpt-6.1-sol"  (shipped)\n'
                'providers.codex.tiers.frontier = "gpt-6-astra"  (shipped)\n',
                "",
            ),
        )
        self.assertEqual(
            self.show("providers.claude-code.efforts.max"),
            (0, 'providers.claude-code.efforts.max = "max"  (shipped)\n', ""),
        )

    def test_a_settings_file_overrides_a_dictionary_key_by_key(self) -> None:
        self.write(self.user_file, '[providers.codex.efforts]\nmax = "ultra"\n[providers.codex.role_models]\ncoder-hard = "gpt-6-astra"\n')
        self.write(self.project_file, '[providers.claude-code.tiers]\ndeep = "fable"\n')
        self.assertEqual(
            self.show("providers.codex.efforts")[1],
            'providers.codex.efforts.low = "low"  (shipped)\n'
            'providers.codex.efforts.medium = "medium"  (shipped)\n'
            'providers.codex.efforts.high = "high"  (shipped)\n'
            'providers.codex.efforts.max = "ultra"  (user)\n',
        )
        self.assertEqual(
            self.show("providers.codex.role_models")[1],
            'providers.codex.role_models.coder-hard = "gpt-6-astra"  (user)\n',
        )
        self.assertEqual(
            self.show("providers.claude-code.tiers.deep")[1], 'providers.claude-code.tiers.deep = "fable"  (project)\n'
        )

    def test_a_value_stays_on_one_line(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "two\\nlines \\"q\\" café"\n')
        self.assertEqual(
            self.show("process.docs_dir")[1], 'process.docs_dir = "two\\nlines \\"q\\" café"  (user)\n'
        )

    def test_a_key_the_schema_does_not_have(self) -> None:
        cases = {
            "proces": "error: proces: no such setting; known groups: process, roles, memory, providers, setup\n",
            "process.nope": "error: process.nope: no such setting; known under process: docs_dir, questions, recommend\n",
            "process.docs_dir.more": "error: process.docs_dir.more: no such setting; process.docs_dir is a single value\n",
            "process.": "error: process.: no such setting; known under process: docs_dir, questions, recommend\n",
            "roles.Bad_Name": "error: roles.Bad_Name: no such setting; known under roles: "
            "enabled, manager_default, high_stakes, max_parallel_coders, <role id>\n",
        }
        for key, expected in cases.items():
            with self.subTest(key=key):
                self.assertEqual(self.show(key), (2, "", expected))


class SeveralKeysTests(support.ScratchCase):
    """``show process memory``: one process for a caller that needs both."""

    def test_two_groups_print_in_the_schemas_order(self) -> None:
        expected = (0, PROCESS_TEXT + MEMORY_TEXT, "")
        self.assertEqual(self.show("process", "memory"), expected)
        self.assertEqual(self.show("memory", "process"), expected)

    def test_it_is_what_each_key_prints_alone(self) -> None:
        self.write(self.user_file, '[process]\nquestions = "all-together"\n[memory]\ndir = "m"\n')
        self.assertEqual(self.show("process", "memory")[1], self.show("process")[1] + self.show("memory")[1])
        self.assertEqual(
            self.show("memory.dir", "process.questions")[1],
            'process.questions = "all-together"  (user)\nmemory.dir = "m"  (user)\n',
        )

    def test_duplicates_and_overlaps_are_merged(self) -> None:
        self.assertEqual(self.show("process", "process")[1], PROCESS_TEXT)
        self.assertEqual(self.show("process.docs_dir", "process", "process.docs_dir")[1], PROCESS_TEXT)
        self.assertEqual(self.show("roles.high_stakes", "roles.high_stakes")[1], "roles.high_stakes = false  (shipped)\n")

    def test_one_key_keeps_its_exact_output(self) -> None:
        self.assertEqual(self.show("process"), (0, PROCESS_TEXT, ""))
        self.assertEqual(
            json.loads(self.show("memory", "--json")[1]),
            {
                "schema_version": 1,
                "settings": {"memory.dir": {"value": "docs/memory", "layer": "shipped", "file": str(self.defaults_file)}},
            },
        )

    def test_json_holds_the_keys_of_all(self) -> None:
        code, out, err = self.show("process", "memory", "--json")
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(list(report), ["schema_version", "settings"])
        self.assertEqual(
            list(report["settings"]),
            ["process.docs_dir", "process.questions", "process.recommend", "memory.dir"],
        )
        merged = {
            **json.loads(self.show("process", "--json")[1])["settings"],
            **json.loads(self.show("memory", "--json")[1])["settings"],
        }
        self.assertEqual(report["settings"], merged)

    def test_only_the_groups_named_are_read(self) -> None:
        self.write(self.user_file, "[roles]\nno_such = 1\n[providers.x]\nwhat = 1\n")
        self.assertEqual(self.show("process", "memory")[0], 0)
        with mock.patch.object(schema, "validate", wraps=schema.validate) as validate:
            self.show("memory", "process.docs_dir")
        self.assertEqual({call.args[0] for call in validate.call_args_list}, {"process", "memory"})
        self.assertEqual(self.show("process", "roles")[0], 2)

    def test_every_bad_key_is_reported(self) -> None:
        code, out, err = self.show("proces", "process", "memory.nope")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            "error: proces: no such setting; known groups: process, roles, memory, providers, setup\n"
            "error: memory.nope: no such setting; known under memory: dir\n",
        )

    def test_roles_among_the_keys_still_adds_the_profiles(self) -> None:
        out = self.show("process", "roles")[1]
        self.assertTrue(out.startswith(PROCESS_TEXT + ROLES_TEXT + "\nresolved profiles"), out)
        self.assertIn("profiles", json.loads(self.show("roles", "memory", "--json")[1]))
        self.assertNotIn("profiles", json.loads(self.show("roles.coder", "memory", "--json")[1]))


class ShowJsonTests(support.ScratchCase):
    def test_value_layer_and_file_for_each_key(self) -> None:
        self.write(self.user_file, '[process]\nrecommend = false\n[roles.coder]\neffort = "max"\n')
        self.write(self.local_file, "[roles]\nmax_parallel_coders = 1\n")
        code, out, err = self.show("--json")
        self.assertEqual((code, err), (0, ""))
        shipped = str(self.defaults_file)
        report = json.loads(out)
        report["settings"] = {key: entry for key, entry in report["settings"].items()
                              if not key.startswith(("providers.", "setup."))}
        self.assertEqual(
            report,
            {
                "schema_version": 1,
                "settings": {
                    "process.docs_dir": {"value": "docs", "layer": "shipped", "file": shipped},
                    "process.questions": {"value": "one-at-a-time", "layer": "shipped", "file": shipped},
                    "process.recommend": {"value": False, "layer": "user", "file": str(self.user_file)},
                    "roles.enabled": {"value": True, "layer": "shipped", "file": shipped},
                    "roles.manager_default": {"value": False, "layer": "shipped", "file": shipped},
                    "roles.high_stakes": {"value": False, "layer": "shipped", "file": shipped},
                    "roles.max_parallel_coders": {"value": 1, "layer": "local", "file": str(self.local_file)},
                    "roles.coder.effort": {"value": "max", "layer": "user", "file": str(self.user_file)},
                    "memory.dir": {"value": "docs/memory", "layer": "shipped", "file": shipped},
                },
            },
        )

    def test_the_keys_keep_the_text_outputs_order(self) -> None:
        text_keys = [line.split(" = ")[0] for line in self.show()[1].splitlines()]
        self.assertEqual(list(json.loads(self.show("--json")[1])["settings"]), text_keys)

    def test_a_group_and_a_key(self) -> None:
        group = json.loads(self.show("process", "--json")[1])["settings"]
        self.assertEqual(list(group), ["process.docs_dir", "process.questions", "process.recommend"])
        one = json.loads(self.show("--json", "memory.dir")[1])["settings"]
        self.assertEqual({key: entry["value"] for key, entry in one.items()}, {"memory.dir": "docs/memory"})

    def test_nothing_set_is_an_empty_object(self) -> None:
        self.assertEqual(
            json.loads(self.show("providers.codex.role_models", "--json")[1]), {"schema_version": 1, "settings": {}}
        )

    def test_providers_names_each_dictionary_as_the_source(self) -> None:
        self.write(self.user_file, '[providers.codex.tiers]\nfast = "gpt-6-sol"\n')
        code, out, err = self.show("providers", "--json")
        self.assertEqual((code, err), (0, ""))
        found = json.loads(out)["settings"]
        self.assertEqual(list(found), list(support.SHIPPED_PROVIDERS))
        for key, value in support.SHIPPED_PROVIDERS.items():
            with self.subTest(key=key):
                source = self.codex_dictionary if key.startswith("providers.codex.") else self.claude_code_dictionary
                if key == "providers.codex.tiers.fast":
                    self.assertEqual(
                        found[key], {"value": "gpt-6-sol", "layer": "user", "file": str(self.user_file)}
                    )
                else:
                    self.assertEqual(found[key], {"value": value, "layer": "shipped", "file": str(source)})


class ShowErrorTests(support.ScratchCase):
    def test_a_fault_goes_to_stderr_with_exit_code_two(self) -> None:
        self.write(self.project_file, '[process]\nquestions = "sometimes"\n')
        code, out, err = self.show()
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            f'error: {self.project_file}: process.questions: "sometimes" is not allowed; '
            "allowed values: one-at-a-time, all-together\n",
        )
        self.assertNotIn("Traceback", err)

    def test_a_newer_schema_version(self) -> None:
        self.write(self.user_file, "schema_version = 2\n")
        code, out, err = self.show("process")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith(f"error: {self.user_file}: schema_version: 2 is newer"), err)

    def test_group_isolation_through_the_command(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "notes"\n[providers.x]\ntiers = 1\nwhat = "?"\n')
        self.assertEqual(
            self.show("process"),
            (
                0,
                'process.docs_dir = "notes"  (user)\n'
                'process.questions = "one-at-a-time"  (shipped)\n'
                "process.recommend = true  (shipped)\n",
                "",
            ),
        )
        self.assertEqual(self.show("process.docs_dir"), (0, 'process.docs_dir = "notes"  (user)\n', ""))
        self.assertEqual(json.loads(self.show("process", "--json")[1])["settings"]["process.docs_dir"]["value"], "notes")
        self.assertEqual(self.show("memory")[0], 0)
        self.assertEqual(self.show("roles.high_stakes")[0], 0)
        # "roles" alone also resolves the profiles, which read the providers.
        for argv in ((), ("providers",), ("providers.x.tiers",), ("roles",)):
            with self.subTest(argv=argv):
                code, out, err = self.show(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"error: {self.user_file}: providers.x.tiers: expected a table, got an integer\n", err)
                self.assertIn(f"error: {self.user_file}: providers.x.what: unknown key", err)

    def test_a_directory_that_does_not_exist(self) -> None:
        missing = str(self.root / "nowhere")
        self.assertEqual(
            support.run("show", "--home", str(self.home), "--project", missing),
            (2, "", f"error: --project: {missing}: not a directory\n"),
        )
        self.assertEqual(support.run("show", "--home", missing), (2, "", f"error: --home: {missing}: not a directory\n"))
        file = str(self.write(self.root / "a-file", "x"))
        self.assertEqual(support.run("show", "--home", file), (2, "", f"error: --home: {file}: not a directory\n"))

    def test_usage_errors_exit_with_two(self) -> None:
        self.assertEqual(support.run()[0], 2)
        self.assertEqual(support.run("no-such-command")[0], 2)
        self.assertEqual(self.show("--no-such-option")[0], 2)

    def test_help_says_how_the_project_is_chosen(self) -> None:
        code, out, _ = support.run("show", "--help")
        self.assertEqual(code, 0)
        flat = " ".join(out.split())
        self.assertIn("--project DIR", flat)
        self.assertIn("not taken from the working directory", flat)
        self.assertIn("--home DIR", flat)

    def test_help_says_an_explicit_tier_beats_high_stakes(self) -> None:
        flat = " ".join(support.run("show", "--help")[1].split())
        self.assertIn("An explicit \"tier\" under [roles.<id>] wins over roles.high_stakes, whichever layer sets each", flat)


class PlacesTests(support.ScratchCase):
    """``--home`` and ``--project``: what is refused, and never a traceback."""

    def refused(self, *argv: str) -> str:
        code, out, err = support.run("show", "process", *argv)
        self.assertEqual((code, out), (2, ""), err)
        self.assertNotIn("Traceback", err)
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

    def test_an_empty_project_is_refused_and_is_not_the_working_directory(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "from-the-working-directory"\n')
        before = os.getcwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, before)
        self.assertEqual(
            self.refused("--home", str(self.home), "--project", ""),
            "--project: an empty value is not a directory; name one, or leave the option out",
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
            self.refused("--home", str(self.home), "--project", "~no-such-user-here"),
            (f"--project: ~no-such-user-here: {unknown}", "--project: ~no-such-user-here: not a directory"),
        )

    def test_a_home_that_cannot_be_expanded(self) -> None:
        with mock.patch.object(Path, "expanduser", side_effect=RuntimeError("Could not determine home directory.")):
            self.assertEqual(
                self.refused("--home", "~someone/x"),
                "--home: ~someone/x: the home directory of that user cannot be found",
            )
            self.assertEqual(
                self.refused("--home", str(self.home), "--project", "~someone"),
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
            self.assertEqual(support.run("show", "process.docs_dir"), (0, 'process.docs_dir = "mine"  (user)\n', ""))

    def test_agents_that_is_a_regular_file_is_an_error_naming_it(self) -> None:
        agents = self.write(self.home / ".agents", "not a directory\n")
        self.assertEqual(
            self.refused("--home", str(self.home)),
            f"{agents}: is not a directory; workflow.toml is looked for in it",
        )
        agents.unlink()
        agents = self.write(self.project / ".agents", "")
        self.assertTrue(
            self.refused("--home", str(self.home), "--project", str(self.project)).startswith(
                f"{agents}: is not a directory"
            )
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
                    self.refused("--home", str(self.home), "--project", str(self.project)),
                    f"link target missing: {file}",
                )
                file.unlink()

    def test_a_link_that_leads_back_to_itself(self) -> None:
        self.link(self.user_file, self.user_file)
        self.assertEqual(self.refused("--home", str(self.home)), f"link target missing: {self.user_file}")

    def test_a_link_to_a_real_file_is_read(self) -> None:
        real = self.write(self.root / "real.toml", '[process]\ndocs_dir = "linked"\n')
        self.link(real, self.user_file)
        self.assertEqual(self.show("process.docs_dir")[1], 'process.docs_dir = "linked"  (user)\n')

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
            (locked, ["--home", str(self.home), "--project", str(locked)], f"{locked / '.agents'}: cannot be read: "),
            (
                locked / ".agents",
                ["--home", str(self.home), "--project", str(locked)],
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


class BackstopTests(support.ScratchCase):
    """What no module turned into a ``SetupError`` still ends in one line."""

    def test_an_os_error_names_the_file(self) -> None:
        error = PermissionError(13, "Permission denied", "/some/where/file.toml")
        with mock.patch.object(locations, "from_args", side_effect=error):
            self.assertEqual(self.show(), (2, "", "error: /some/where/file.toml: Permission denied\n"))

    def test_an_os_error_without_a_file(self) -> None:
        with mock.patch.object(locations, "from_args", side_effect=OSError(28, "No space left on device")):
            self.assertEqual(self.show(), (2, "", "error: No space left on device\n"))

    def test_a_recursion_error(self) -> None:
        with mock.patch.object(locations, "from_args", side_effect=RecursionError("too deep")):
            self.assertEqual(self.show(), (2, "", "error: the input is nested too deeply to read\n"))

    def test_a_broken_pipe_is_left_to_the_entry_point(self) -> None:
        with mock.patch.object(locations, "from_args", side_effect=BrokenPipeError(32, "Broken pipe")):
            with self.assertRaises(BrokenPipeError):
                cli.main(["show", "--home", str(self.home)])


class EntryPointTests(support.ScratchCase):
    """The script run by path, as a child process, from another directory:
    the tool copied into the fake clone, so the output is the fixtures'."""

    def setUp(self) -> None:
        super().setUp()
        self.script = self.install_tool()

    def child(self, *argv: str, cwd=None, script=None, **options) -> subprocess.CompletedProcess:
        options.setdefault("capture_output", True)
        return subprocess.run(
            [sys.executable, str(script or self.script), *argv],
            cwd=cwd or self.root,
            env=support.child_environment(),
            timeout=60,
            **options,
        )

    def test_show_from_another_working_directory(self) -> None:
        done = self.child("show", "--home", str(self.home))
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertEqual(done.stdout, SHIPPED_TEXT.encode("utf-8"))

    def test_the_repositorys_own_script_runs(self) -> None:
        done = self.child("show", "process", "--home", str(self.home), script=support.SCRIPT)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertIn(b"process.docs_dir = ", done.stdout)

    def test_the_project_is_not_taken_from_the_working_directory(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "p"\n')
        here = self.child("show", "process.docs_dir", "--home", str(self.home), cwd=self.project)
        self.assertEqual(here.stdout, b'process.docs_dir = "docs"  (shipped)\n')
        named = self.child("show", "process.docs_dir", "--home", str(self.home), "--project", ".", cwd=self.project)
        self.assertEqual(named.stdout, b'process.docs_dir = "p"  (project)\n')

    def test_output_is_utf8_with_line_feeds_whatever_the_locale(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "café/中"\n')
        env = {key: value for key, value in os.environ.items() if not key.startswith(("LC_", "PYTHON"))}
        env.update({"LANG": "C", "LC_ALL": "C", "PYTHONIOENCODING": "ascii"})
        done = subprocess.run(
            [sys.executable, str(self.script), "show", "process", "--home", str(self.home)],
            cwd=self.root, env=env, capture_output=True, timeout=60,
        )
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertIn('process.docs_dir = "café/中"  (user)\n'.encode("utf-8"), done.stdout)
        self.assertNotIn(b"\r", done.stdout)

    def test_json_from_a_child_process(self) -> None:
        done = self.child("show", "process", "--json", "--home", str(self.home), "--project", str(self.project))
        self.assertEqual(done.returncode, 0)
        report = json.loads(done.stdout.decode("utf-8"))
        self.assertEqual(report["settings"]["process.questions"], {
            "value": "one-at-a-time", "layer": "shipped", "file": str(self.defaults_file),
        })

    def test_an_error_has_no_traceback_and_exit_code_two(self) -> None:
        self.write(self.user_file, "[process]\ndocs_dir = 1\n")
        done = self.child("show", "--home", str(self.home))
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertEqual(
            done.stderr.decode("utf-8"),
            f"error: {self.user_file}: process.docs_dir: expected a string, got an integer\n",
        )

    def test_a_run_writes_no_bytecode_into_the_clone(self) -> None:
        """The shared clone is changed only by ``git pull``."""
        done = self.child("show", "roles", "--home", str(self.home))
        self.assertEqual(done.returncode, 0)
        self.assertEqual([str(found) for found in self.clone.rglob("__pycache__")], [])
        self.assertEqual([str(found) for found in self.clone.rglob("*.pyc")], [])

    def test_a_settings_file_nested_thousands_deep(self) -> None:
        self.write(self.user_file, "[process]\nx = " + "[" * 5000 + "]" * 5000 + "\n")
        done = self.child("show", "process", "--home", str(self.home))
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertEqual(
            done.stderr.decode("utf-8"),
            f"error: {self.user_file}: is not valid TOML: arrays or inline tables are nested too deeply\n",
        )

    def test_a_closed_stdout_is_an_error_and_not_an_empty_success(self) -> None:
        wrapper = (
            "import runpy, sys\n"
            "sys.stdout.close()\n"
            f"sys.argv = [{str(self.script)!r}, 'show', 'process', '--home', {str(self.home)!r}]\n"
            f"runpy.run_path({str(self.script)!r}, run_name='__main__')\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", wrapper], cwd=self.root, env=support.child_environment(),
            capture_output=True, timeout=60,
        )
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertEqual(done.stderr, b"error: the output cannot be written: standard output is closed\n")

    @unittest.skipUnless(os.path.exists("/dev/full"), "no full device here")
    def test_a_full_device_is_an_error_and_not_a_success(self) -> None:
        with open("/dev/full", "w") as full:
            done = self.child("show", "--home", str(self.home), stdout=full, stderr=subprocess.PIPE, capture_output=False)
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
            f"sys.argv = [{str(self.script)!r}, 'show', '--home', {str(self.home)!r}]\n"
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


class RepositoryTests(support.ScratchCase):
    """The repository's own defaults.toml: only what holds whatever else it
    comes to say."""

    def test_show_runs_on_the_repository(self) -> None:
        code, out, err = self.show_repository()
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        # The defaults the plan names (P3.1).
        for line in (
            'process.docs_dir = "docs"  (shipped)',
            'process.questions = "one-at-a-time"  (shipped)',
            "process.recommend = true  (shipped)",
            "roles.manager_default = false  (shipped)",
            "roles.high_stakes = false  (shipped)",
            "roles.max_parallel_coders = 3  (shipped)",
            'memory.dir = "docs/memory"  (shipped)',
            "roles.enabled = true  (shipped)",
            "setup.allow_unshared_clone = false  (shipped)",
        ):
            with self.subTest(line=line):
                self.assertIn(line, lines)
        self.assertTrue(all(line.endswith("  (shipped)") for line in lines), out)

    def test_the_two_remembered_choices_show_with_their_layer(self) -> None:
        self.write(self.user_file, "[roles]\nenabled = false\n[setup]\nallow_unshared_clone = true\n")
        code, out, err = self.show_repository("roles.enabled", "setup")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "roles.enabled = false  (user)\nsetup.allow_unshared_clone = true  (user)\n")
        report = json.loads(self.show_repository("setup", "--json")[1])
        self.assertEqual(report["settings"], {
            "setup.allow_unshared_clone": {"value": True, "layer": "user", "file": str(self.user_file)},
        })
        # A project may turn its roles off; it may not hold [setup].
        self.write(self.project_file, "[roles]\nenabled = true\n")
        with mock.patch.object(locations, "CLONE", support.REPOSITORY):
            code, out, err = self.show("roles.enabled")
        self.assertEqual((code, out, err), (0, "roles.enabled = true  (project)\n", ""))
        self.write(self.project_file, "[setup]\nallow_unshared_clone = true\n")
        with mock.patch.object(locations, "CLONE", support.REPOSITORY):
            code, out, err = self.show()
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"error: {self.project_file}: setup: read from the user's settings file alone", err)

    def test_every_group_shows_and_json_names_the_shipped_file(self) -> None:
        for group in schema.GROUPS:
            with self.subTest(group=group):
                self.assertEqual(self.show_repository(group)[0], 0)
        report = json.loads(self.show_repository("process", "--json")[1])
        self.assertEqual(report["schema_version"], schema.SCHEMA_VERSION)
        self.assertEqual(
            report["settings"]["process.docs_dir"], {"value": "docs", "layer": "shipped", "file": str(support.DEFAULTS)}
        )


if __name__ == "__main__":
    unittest.main()
