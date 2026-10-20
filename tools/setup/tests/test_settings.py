"""Tests for the settings schema and layers (wfsetup.schema, wfsetup.settings).

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import tomllib
import unittest
from unittest import mock

import support
from wfsetup import schema, settings, tomlio
from wfsetup.errors import SetupError


class ShippedDefaultsTests(support.ScratchCase):
    def test_the_shipped_values(self) -> None:
        entries = settings.resolve(self.locations())
        self.assertEqual(
            {key: entry.value for key, entry in entries.items()},
            {
                "process.docs_dir": "docs",
                "process.questions": "all-together",
                "process.recommend": True,
                "roles.enabled": True,
                "roles.manager_default": False,
                "roles.high_stakes": False,
                "roles.max_parallel_coders": 3,
                "memory.dir": "docs/memory",
                **support.SHIPPED_PROVIDERS,
                "setup.allow_unshared_clone": False,
            },
        )
        self.assertEqual({entry.layer for entry in entries.values()}, {"shipped"})
        self.assertEqual(
            {entry.file for key, entry in entries.items() if not key.startswith("providers.")}, {self.defaults_file}
        )

    def test_the_shipped_provider_sections_come_from_the_dictionaries(self) -> None:
        entries = settings.resolve(self.locations(), ("providers",))
        self.assertEqual(list(entries), list(support.SHIPPED_PROVIDERS))
        for key, entry in entries.items():
            with self.subTest(key=key):
                expected = self.codex_dictionary if key.startswith("providers.codex.") else self.claude_code_dictionary
                self.assertEqual((entry.layer, entry.file), ("shipped", expected))

    def test_the_repositorys_file_carries_the_schema_version(self) -> None:
        shipped = tomllib.loads(support.DEFAULTS.read_text(encoding="utf-8"))
        self.assertEqual(shipped["schema_version"], schema.SCHEMA_VERSION)

    def test_the_repositorys_file_has_line_feeds_only(self) -> None:
        self.assertNotIn(b"\r", support.DEFAULTS.read_bytes())

    def test_the_repositorys_file_resolves_and_sets_every_fixed_key(self) -> None:
        """Whatever the repository's defaults come to hold: they validate,
        all of it is the shipped layer, and no fixed key is left unset."""
        entries = settings.resolve(self.repository(), ("process", "roles", "memory"))
        self.assertEqual({entry.layer for entry in entries.values()}, {"shipped"})
        self.assertEqual({entry.file for entry in entries.values()}, {support.DEFAULTS})
        for group in ("process", "roles", "memory"):
            for key in schema.SCHEMA[group].keys:
                with self.subTest(key=f"{group}.{key}"):
                    self.assertIn(f"{group}.{key}", entries)

    def test_the_repositorys_comments_say_how_the_directories_are_taken(self) -> None:
        text = " ".join(support.DEFAULTS.read_text(encoding="utf-8").replace("#", " ").split())
        self.assertIn("relative to the project unless absolute", text)
        self.assertIn("may point outside the project", text)

    def test_keys_come_in_the_schemas_order(self) -> None:
        self.write(self.user_file, '[roles.zeta]\neffort = "low"\ntier = "fast"\n[roles.alpha]\ntier = "deep"\n')
        keys = [key for key in settings.resolve(self.locations()) if key.startswith("roles.")]
        self.assertEqual(
            keys,
            [
                "roles.enabled",
                "roles.manager_default",
                "roles.high_stakes",
                "roles.max_parallel_coders",
                "roles.alpha.tier",
                "roles.zeta.tier",
                "roles.zeta.effort",
            ],
        )


class LayerTests(support.ScratchCase):
    def value(self, key: str) -> tuple:
        entry = settings.resolve(self.locations())[key]
        return entry.value, entry.layer, entry.file

    def test_each_layer_overrides_the_one_before(self) -> None:
        key = "process.docs_dir"
        self.assertEqual(self.value(key), ("docs", "shipped", self.defaults_file))
        self.write(self.user_file, '[process]\ndocs_dir = "from-user"\n')
        self.assertEqual(self.value(key), ("from-user", "user", self.user_file))
        self.write(self.project_file, '[process]\ndocs_dir = "from-project"\n')
        self.assertEqual(self.value(key), ("from-project", "project", self.project_file))
        self.write(self.local_file, '[process]\ndocs_dir = "from-local"\n')
        self.assertEqual(self.value(key), ("from-local", "local", self.local_file))

    def test_layers_merge_key_by_key(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "u"\nquestions = "all-together"\nrecommend = false\n')
        self.write(self.project_file, '[process]\nquestions = "one-at-a-time"\n')
        self.write(self.local_file, "[process]\nrecommend = true\n[roles]\nmax_parallel_coders = 5\n")
        entries = settings.resolve(self.locations(), ("process", "roles", "memory"))
        self.assertEqual(
            {key: (entry.value, entry.layer) for key, entry in entries.items()},
            {
                "process.docs_dir": ("u", "user"),
                "process.questions": ("one-at-a-time", "project"),
                "process.recommend": (True, "local"),
                "roles.enabled": (True, "shipped"),
                "roles.manager_default": (False, "shipped"),
                "roles.high_stakes": (False, "shipped"),
                "roles.max_parallel_coders": (5, "local"),
                "memory.dir": ("docs/memory", "shipped"),
            },
        )

    def test_without_a_project_only_shipped_and_user_are_read(self) -> None:
        self.write(self.user_file, '[memory]\ndir = "u"\n')
        self.write(self.project_file, '[memory]\ndir = "p"\n')
        entry = settings.resolve(self.locations(project=False))["memory.dir"]
        self.assertEqual((entry.value, entry.layer), ("u", "user"))

    def test_a_role_override(self) -> None:
        self.write(self.user_file, '[roles.coder]\ntier = "deep"\neffort = "high"\n')
        self.write(self.project_file, '[roles.coder]\neffort = "max"\n[roles.coder-hard]\ntier = "frontier"\n')
        entries = settings.resolve(self.locations(), ("roles",))
        self.assertEqual(
            {key: (entry.value, entry.layer) for key, entry in entries.items() if key.count(".") == 2},
            {
                "roles.coder.tier": ("deep", "user"),
                "roles.coder.effort": ("max", "project"),
                "roles.coder-hard.tier": ("frontier", "project"),
            },
        )

    def test_a_provider_section(self) -> None:
        self.write(
            self.user_file,
            '[providers.codex.tiers]\nfast = "m-small"\ndeep = "m-large"\n'
            '[providers.codex.efforts]\nmax = "xhigh"\n'
            '[providers.codex.role_models]\ncoder-hard = "m-special"\n',
        )
        self.write(self.project_file, '[providers.codex.tiers]\ndeep = "m-larger"\n')
        entries = settings.resolve(self.locations(), ("providers",))
        self.assertEqual(
            {key: (entry.value, entry.layer) for key, entry in entries.items() if entry.layer != "shipped"},
            {
                "providers.codex.tiers.fast": ("m-small", "user"),
                "providers.codex.tiers.deep": ("m-larger", "project"),
                "providers.codex.efforts.max": ("xhigh", "user"),
                "providers.codex.role_models.coder-hard": ("m-special", "user"),
            },
        )
        # What no file overrides is still the dictionary's.
        self.assertEqual(entries["providers.codex.tiers.standard"].value, "gpt-6.1-sol")
        self.assertEqual(entries["providers.codex.tiers.standard"].file, self.codex_dictionary)
        self.assertEqual(entries["providers.claude-code.tiers.fast"].layer, "shipped")

    def test_an_empty_file_and_an_empty_group_change_nothing(self) -> None:
        self.write(self.user_file, "")
        self.write(self.project_file, "[process]\n[roles.coder]\n")
        entries = settings.resolve(self.locations())
        self.assertEqual({entry.layer for entry in entries.values()}, {"shipped"})

    def test_a_missing_schema_version_is_version_one(self) -> None:
        self.write(self.user_file, '[memory]\ndir = "a"\n')
        self.write(self.project_file, 'schema_version = 1\n[memory]\ndir = "b"\n')
        self.assertEqual(self.value("memory.dir")[0], "b")


class ValidationTests(support.ScratchCase):
    def problems(self, text: str, file=None, groups=schema.GROUPS) -> list[str]:
        file = self.write(file or self.user_file, text)
        with self.assertRaises(SetupError) as caught:
            settings.resolve(self.locations(), groups)
        for line in caught.exception.lines:
            self.assertTrue(line.startswith(f"{file}: "), line)
        return [line[len(f"{file}: "):] for line in caught.exception.lines]

    def test_an_unknown_key_names_the_file_and_the_key(self) -> None:
        self.assertEqual(
            self.problems('[process]\ndocs_directory = "x"\n'),
            ["process.docs_directory: unknown key; known here: docs_dir, questions, recommend"],
        )

    def test_an_unknown_key_in_each_layer_names_that_layers_file(self) -> None:
        for file in (self.user_file, self.project_file, self.local_file):
            with self.subTest(file=file.name):
                self.assertEqual(len(self.problems("[memory]\nplace = 1\n", file=file)), 1)
                file.unlink()

    def test_an_unknown_top_level_key(self) -> None:
        self.assertEqual(
            self.problems("[proces]\nrecommend = true\n"),
            ["proces: unknown key; known here: schema_version, process, roles, memory, providers, setup"],
        )

    def test_an_unknown_key_in_a_role_override(self) -> None:
        self.assertEqual(
            self.problems('[roles.coder]\nmodel = "x"\n'),
            ["roles.coder.model: unknown key; known here: tier, effort"],
        )

    def test_an_unknown_scalar_under_roles_is_not_taken_for_a_role(self) -> None:
        self.assertEqual(
            self.problems("[roles]\nmax_coders = 2\n"),
            ["roles.max_coders: unknown key; known here: enabled, manager_default, high_stakes, max_parallel_coders, <role id>"],
        )

    def test_a_table_that_is_not_a_role_id(self) -> None:
        (line,) = self.problems('[roles.Bad_Name]\ntier = "fast"\n')
        self.assertTrue(line.startswith("roles.Bad_Name: not a role id"), line)

    def test_an_unknown_key_in_a_provider_section(self) -> None:
        self.assertEqual(
            self.problems('[providers.codex]\nmodels = "x"\n'),
            ["providers.codex.models: unknown key; known here: tiers, efforts, role_models"],
        )
        self.assertEqual(
            self.problems('[providers.codex.tiers]\nhuge = "x"\n'),
            ["providers.codex.tiers.huge: unknown key; known here: fast, standard, deep, frontier"],
        )
        self.assertEqual(
            self.problems('[providers.codex.efforts]\nultra = "x"\n'),
            ["providers.codex.efforts.ultra: unknown key; known here: low, medium, high, max"],
        )

    def test_a_wrong_type_names_the_file_and_the_key(self) -> None:
        cases = {
            "[process]\ndocs_dir = 3\n": "process.docs_dir: expected a string, got an integer",
            '[process]\nrecommend = "yes"\n': "process.recommend: expected a boolean, got a string",
            "[process]\nrecommend = 1\n": "process.recommend: expected a boolean, got an integer",
            "[roles]\nmax_parallel_coders = true\n": "roles.max_parallel_coders: expected an integer, got a boolean",
            "[roles]\nmax_parallel_coders = 2.0\n": "roles.max_parallel_coders: expected an integer, got a float",
            '[roles]\nmax_parallel_coders = "3"\n': "roles.max_parallel_coders: expected an integer, got a string",
            "[roles]\nmanager_default = []\n": "roles.manager_default: expected a boolean, got an array",
            "[roles.manager_default]\n": "roles.manager_default: expected a boolean, got a table",
            "[roles.coder]\ntier = 1\n": "roles.coder.tier: expected a string, got an integer",
            'process = "x"\n': "process: expected a table, got a string",
            "[memory]\ndir = 2026-01-01\n": "memory.dir: expected a string, got a date",
            "[providers]\ncodex = 1\n": "providers.codex: expected a table, got an integer",
            "[providers]\nsome_key = 1\n": "providers.some_key: unknown key; known here: <provider name>",
            '[providers.codex]\ntiers = "x"\n': "providers.codex.tiers: expected a table, got a string",
            "[providers.codex.tiers]\nfast = 1\n": "providers.codex.tiers.fast: expected a string, got an integer",
            "[providers.codex.role_models]\ncoder = false\n":
                "providers.codex.role_models.coder: expected a string, got a boolean",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.problems(text), [expected])

    def test_a_value_outside_an_enumeration_names_the_allowed_values(self) -> None:
        cases = {
            '[process]\nquestions = "in-bulk"\n':
                'process.questions: "in-bulk" is not allowed; allowed values: one-at-a-time, all-together',
            '[roles.coder]\ntier = "huge"\n':
                'roles.coder.tier: "huge" is not allowed; allowed values: fast, standard, deep, frontier',
            '[roles.coder]\neffort = "xhigh"\n':
                'roles.coder.effort: "xhigh" is not allowed; allowed values: low, medium, high, max',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.problems(text), [expected])

    def test_values_out_of_range(self) -> None:
        self.assertEqual(
            self.problems("[roles]\nmax_parallel_coders = 0\n"),
            ["roles.max_parallel_coders: 0 is too small; the least allowed is 1"],
        )
        self.assertEqual(self.problems('[process]\ndocs_dir = ""\n'), ["process.docs_dir: must not be empty"])

    def test_a_string_of_white_space_only_is_not_a_value(self) -> None:
        for blank in (" ", "   ", "\\t", " \\n "):
            with self.subTest(blank=blank):
                self.assertEqual(
                    self.problems(f'[process]\ndocs_dir = "{blank}"\n'),
                    ["process.docs_dir: must not be blank; it holds only white space"],
                )
        self.assertEqual(
            self.problems('[memory]\ndir = " "\n'), ["memory.dir: must not be blank; it holds only white space"]
        )
        self.assertEqual(
            self.problems('[providers.codex.tiers]\nfast = "  "\n'),
            ["providers.codex.tiers.fast: must not be blank; it holds only white space"],
        )

    def test_the_directories_are_taken_as_given(self) -> None:
        """Relative, absolute, or outside the project: only blank is refused."""
        for value in ("docs", "../planning/docs", "/srv/shared/docs", "C:/planning/docs", "~/notes", " padded "):
            with self.subTest(value=value):
                self.write(self.user_file, f'[process]\ndocs_dir = "{value}"\n[memory]\ndir = "{value}"\n')
                entries = settings.resolve(self.locations(), ("process", "memory"))
                self.assertEqual((entries["process.docs_dir"].value, entries["memory.dir"].value), (value, value))

    def test_an_integer_with_too_many_digits_names_the_file(self) -> None:
        self.assertEqual(
            self.problems("[roles]\nmax_parallel_coders = " + "9" * 5000 + "\n"),
            ["is not valid TOML: it holds an integer with too many digits"],
        )

    def test_nesting_thousands_deep_names_the_file(self) -> None:
        self.assertEqual(
            self.problems("[process]\nx = " + "[" * 5000 + "]" * 5000 + "\n"),
            ["is not valid TOML: arrays or inline tables are nested too deeply"],
        )
        self.assertEqual(
            self.problems("[process]\nx = " + "{a=" * 5000 + "1" + "}" * 5000 + "\n"),
            ["is not valid TOML: arrays or inline tables are nested too deeply"],
        )

    def test_a_newer_schema_version_is_refused(self) -> None:
        for file in (self.user_file, self.project_file, self.local_file):
            with self.subTest(file=file.name):
                (line,) = self.problems('schema_version = 2\n[process]\ndocs_dir = "x"\n[future]\nkey = 1\n', file=file)
                self.assertTrue(line.startswith("schema_version: 2 is newer than this tool reads (1)"), line)
                file.unlink()

    def test_a_newer_schema_version_is_refused_for_any_group(self) -> None:
        (line,) = self.problems("schema_version = 7\n", groups=("memory",))
        self.assertIn("schema_version: 7 is newer", line)

    def test_a_schema_version_that_is_not_one(self) -> None:
        self.assertEqual(
            self.problems('schema_version = "1"\n'), ["schema_version: expected an integer, got a string"]
        )
        self.assertEqual(
            self.problems("schema_version = true\n"), ["schema_version: expected an integer, got a boolean"]
        )
        self.assertEqual(
            self.problems("schema_version = 0\n"), ["schema_version: 0 is not a schema version; the first is 1"]
        )

    def test_every_fault_is_reported_at_once(self) -> None:
        self.write(self.user_file, "[process]\ndocs_dir = 1\nextra = 2\n")
        self.write(self.project_file, '[memory]\ndir = false\n[roles.coder]\ntier = "x"\n')
        with self.assertRaises(SetupError) as caught:
            settings.resolve(self.locations())
        lines = caught.exception.lines
        self.assertEqual(len(lines), 4)
        self.assertEqual([line.startswith(str(self.user_file)) for line in lines], [True, True, False, False])
        self.assertTrue(all(line.startswith(str(self.project_file)) for line in lines[2:]))

    def test_a_file_that_does_not_parse_names_the_file(self) -> None:
        self.write(self.project_file, "[process\n")
        with self.assertRaises(SetupError) as caught:
            settings.resolve(self.locations())
        self.assertIn(str(self.project_file), str(caught.exception))

    def test_a_key_that_needs_quoting_is_shown_quoted(self) -> None:
        self.assertEqual(
            self.problems('[process]\n"odd key.x" = 1\n'),
            ['process."odd key.x": unknown key; known here: docs_dir, questions, recommend'],
        )


class GroupIsolationTests(support.ScratchCase):
    """R5.3: a reader of one group does not depend on another group."""

    BROKEN_PROVIDER = (
        '[process]\ndocs_dir = "notes"\n'
        "[providers.x]\n"
        'tiers = "not a table"\n'
        "unknown_key = 1\n"
        "[providers.x.efforts]\nlow = 5\n"
    )

    def test_a_malformed_provider_section_does_not_break_the_process_group(self) -> None:
        self.write(self.user_file, self.BROKEN_PROVIDER)
        entries = settings.resolve(self.locations(), ("process",))
        self.assertEqual(entries["process.docs_dir"].value, "notes")
        self.assertEqual(entries["process.docs_dir"].layer, "user")
        self.assertEqual(sorted(entries), ["process.docs_dir", "process.questions", "process.recommend"])

    def test_the_same_file_fails_for_the_providers_group_and_for_everything(self) -> None:
        self.write(self.user_file, self.BROKEN_PROVIDER)
        for groups in (("providers",), schema.GROUPS):
            with self.subTest(groups=groups):
                with self.assertRaises(SetupError) as caught:
                    settings.resolve(self.locations(), groups)
                text = str(caught.exception)
                self.assertIn("providers.x.tiers: expected a table", text)
                self.assertIn("providers.x.unknown_key: unknown key", text)

    def test_a_group_that_is_not_even_a_table_is_not_looked_at(self) -> None:
        self.write(self.user_file, 'providers = 3\nroles = "x"\n[memory]\ndir = "m"\n')
        self.assertEqual(settings.resolve(self.locations(), ("memory",))["memory.dir"].value, "m")
        self.assertEqual(settings.resolve(self.locations(), ("process",))["process.docs_dir"].value, "docs")

    def test_only_the_group_asked_for_is_validated(self) -> None:
        self.write(self.user_file, "[process]\n[roles]\n[memory]\n[providers.x]\n")
        with mock.patch.object(schema, "validate", wraps=schema.validate) as validate:
            settings.resolve(self.locations(), ("process",))
        self.assertEqual({call.args[0] for call in validate.call_args_list}, {"process"})

    def test_each_group_is_shielded_from_each_other_group(self) -> None:
        broken = {
            "process": "[process]\nnope = 1\n",
            "roles": "[roles]\nnope = 1\n",
            "memory": "[memory]\nnope = 1\n",
            "providers": "[providers.x]\nnope = 1\n",
        }
        for bad, text in broken.items():
            self.write(self.user_file, text)
            for group in schema.GROUPS:
                with self.subTest(broken=bad, read=group):
                    if group == bad:
                        with self.assertRaises(SetupError):
                            settings.resolve(self.locations(), (group,))
                    else:
                        settings.resolve(self.locations(), (group,))


class RememberedChoiceTests(support.ScratchCase):
    """``roles.enabled`` and ``setup.allow_unshared_clone``: what the schema
    takes, and which layers may hold each."""

    def problems(self, file, text: str, groups=schema.GROUPS) -> list[str]:
        self.write(file, text)
        with self.assertRaises(SetupError) as caught:
            settings.resolve(self.locations(), groups)
        return list(caught.exception.lines)

    def test_both_take_a_boolean_only(self) -> None:
        for text, line in (
            ('[roles]\nenabled = "no"\n', "roles.enabled: expected a boolean, got a string"),
            ("[roles]\nenabled = 0\n", "roles.enabled: expected a boolean, got an integer"),
            ("[setup]\nallow_unshared_clone = 1\n", "setup.allow_unshared_clone: expected a boolean, got an integer"),
            ("[setup]\nshared = true\n", "setup.shared: unknown key; known here: allow_unshared_clone"),
            ("setup = true\n", "setup: expected a table, got a boolean"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.problems(self.user_file, text), [f"{self.user_file}: {line}"])

    def test_the_repositorys_defaults_set_both_and_ship_the_safe_values(self) -> None:
        entries = settings.resolve(self.repository(), ("roles", "setup"))
        self.assertEqual((entries["roles.enabled"].value, entries["roles.enabled"].layer), (True, "shipped"))
        found = entries["setup.allow_unshared_clone"]
        self.assertEqual((found.value, found.layer, found.file), (False, "shipped", support.DEFAULTS))

    def test_roles_enabled_is_layered_like_any_key(self) -> None:
        def value(project: bool = True) -> tuple:
            entry = settings.resolve(self.locations(project), ("roles",)).get("roles.enabled")
            return None if entry is None else (entry.value, entry.layer)

        self.assertEqual(value(), (True, "shipped"))
        self.write(self.user_file, "[roles]\nenabled = false\n")
        self.assertEqual(value(), (False, "user"))
        self.write(self.project_file, "[roles]\nenabled = true\n")
        self.assertEqual(value(), (True, "project"))
        self.assertEqual(value(project=False), (False, "user"))  # a home reads the user's file alone
        self.write(self.local_file, "[roles]\nenabled = false\n")
        self.assertEqual(value(), (False, "local"))

    def test_the_setup_group_is_read_from_the_users_file(self) -> None:
        self.write(self.user_file, "[setup]\nallow_unshared_clone = true\n")
        entry = settings.resolve(self.locations(), ("setup",))["setup.allow_unshared_clone"]
        self.assertEqual((entry.value, entry.layer, entry.file), (True, "user", self.user_file))

    def test_a_projects_file_may_not_hold_the_setup_group(self) -> None:
        for file in (self.project_file, self.local_file):
            with self.subTest(file=file.name):
                (line,) = self.problems(file, "[setup]\nallow_unshared_clone = true\n", ("setup",))
                self.assertTrue(line.startswith(f"{file}: setup: read from the user's settings file alone"), line)
                self.assertIn("~/.agents/workflow.toml", line)
                self.assertIn("not of a project", line)
                # Refused in the same words when every group is read, as by show.
                self.assertEqual(self.problems(file, "[setup]\nallow_unshared_clone = false\n"), [line])
                file.unlink()

    def test_a_projects_setup_group_does_not_stop_a_reader_of_another_group(self) -> None:
        self.write(self.project_file, "[setup]\nallow_unshared_clone = true\n[process]\ndocs_dir = \"p\"\n")
        self.assertEqual(settings.resolve(self.locations(), ("process",))["process.docs_dir"].value, "p")


class DictionarySeamTests(support.CloneCase):
    """A provider's dictionary file is the shipped layer of its section.
    What a dictionary may hold is tested in test_dictionary.py."""

    def test_no_dictionary_means_no_provider_section(self) -> None:
        self.assertEqual(settings.resolve(self.where(), ("providers",)), {})
        (self.clone / "providers" / "acme").mkdir(parents=True)
        self.assertEqual(settings.resolve(self.where(), ("providers",)), {})

    def test_the_repository_resolves_with_the_dictionaries_it_has(self) -> None:
        entries = settings.resolve(self.repository(), ("providers",))
        self.assertTrue(entries)
        self.assertEqual({entry.layer for entry in entries.values()}, {"shipped"})

    def test_a_dictionary_is_the_shipped_layer_and_a_user_file_overrides_it(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY)
        self.write(self.user_file, '[providers.acme.tiers]\ndeep = "a-huge"\n[providers.acme.role_models]\ncoder = "x"\n')
        entries = settings.resolve(self.where())
        self.assertEqual(
            {key: (entry.value, entry.layer, entry.file) for key, entry in entries.items() if key.startswith("prov")},
            {
                "providers.acme.tiers.fast": ("a-small", "shipped", self.dictionary),
                "providers.acme.tiers.standard": ("a-mid", "shipped", self.dictionary),
                "providers.acme.tiers.deep": ("a-huge", "user", self.user_file),
                "providers.acme.tiers.frontier": ("a.large", "shipped", self.dictionary),
                "providers.acme.efforts.low": ("minimal", "shipped", self.dictionary),
                "providers.acme.efforts.medium": ("medium", "shipped", self.dictionary),
                "providers.acme.efforts.high": ("high", "shipped", self.dictionary),
                "providers.acme.efforts.max": ("extreme", "shipped", self.dictionary),
                "providers.acme.role_models.coder": ("x", "user", self.user_file),
            },
        )

    def test_only_the_three_settings_keys_are_lifted(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY + '\n[role_models]\ncoder-hard = "a.large"\n')
        keys = set(settings.resolve(self.where(), ("providers",)))
        self.assertIn("providers.acme.role_models.coder-hard", keys)
        self.assertEqual({key.split(".")[2] for key in keys}, {"tiers", "efforts", "role_models"})

    def test_a_fault_in_a_dictionary_names_the_dictionary_and_its_own_key(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY.replace('fast = "a-small"', 'fast = "a-small"\nhuge = "x"'))
        with self.assertRaises(SetupError) as caught:
            settings.resolve(self.where(), ("providers",))
        self.assertEqual(
            caught.exception.lines,
            [f"{self.dictionary}: tiers.huge: unknown key; known here: fast, standard, deep, frontier"],
        )

    def test_the_faults_of_every_dictionary_are_reported_together(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY + "\n[extra]\n")
        other = self.write(self.dictionary_file("beta"), "this is [not toml\n")
        with self.assertRaises(SetupError) as caught:
            settings.resolve(self.where(), ("providers",))
        lines = caught.exception.lines
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith(f"{self.dictionary}: extra: unknown key"), lines[0])
        self.assertTrue(lines[1].startswith(f"{other}: is not valid TOML"), lines[1])

    def test_a_process_lookup_does_not_open_a_dictionary(self) -> None:
        self.write(self.dictionary, "this is [not toml\n")
        with mock.patch.object(tomlio, "load", wraps=tomlio.load) as load:
            for group in ("process", "roles", "memory"):
                settings.resolve(self.where(), (group,))
        self.assertEqual({call.args[0] for call in load.call_args_list}, {self.where().defaults_file})
        self.assertEqual(settings.resolve(self.where(), ("process",))["process.docs_dir"].value, "docs")
        with self.assertRaises(SetupError):
            settings.resolve(self.where(), ("providers",))

    def test_missing_shipped_defaults_are_an_error(self) -> None:
        (self.clone / "tools" / "setup" / "defaults.toml").unlink()
        with self.assertRaises(SetupError) as caught:
            settings.resolve(self.where())
        self.assertIn("shipped defaults are missing", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
