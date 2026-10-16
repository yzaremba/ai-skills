"""Tests for the provider dictionaries (wfsetup.dictionary).

Exact content is tested on the fixture dictionaries of the fake clone
(``support.FIXTURE_DICTIONARIES``). The two that ship,
providers/claude-code/dictionary.toml and providers/codex/dictionary.toml,
are tested in ``RepositoryDictionaryTests`` and ``CodexListTests`` by what
holds whatever version, date and models they come to name.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import datetime
import json
import os
import unittest
from unittest import mock

import support
from wfsetup import definitions, dictionary, schema, settings, tomlio
from wfsetup.errors import SetupError

CODEX_LIST_PATTERN = "codex-debug-models-*.json"


class FixtureDictionaryTests(support.ScratchCase):
    """The two fixture dictionaries: the loader on files like the real ones."""

    def setUp(self) -> None:
        super().setUp()
        self.all = dictionary.load_all(self.locations())

    def test_both_validate(self) -> None:
        self.assertEqual(list(self.all), ["claude-code", "codex"])
        self.assertEqual(self.all["codex"].file, self.codex_dictionary)
        self.assertEqual(self.all["claude-code"].file, self.claude_code_dictionary)
        self.assertEqual(dictionary.load(self.locations(), "codex"), self.all["codex"])
        self.assertEqual(dictionary.load_file(self.claude_code_dictionary), self.all["claude-code"])
        self.assertIsNone(dictionary.load(self.locations(), "no-such-provider"))

    def test_the_mappings(self) -> None:
        self.assertEqual(
            self.all["claude-code"].tiers,
            {"fast": "haiku", "standard": "sonnet", "deep": "opus", "frontier": "fable"},
        )
        self.assertEqual(
            self.all["codex"].tiers,
            {"fast": "gpt-6-luna", "standard": "gpt-6.1-sol", "deep": "gpt-6.1-sol", "frontier": "gpt-6-astra"},
        )
        one_to_one = {effort: effort for effort in schema.EFFORTS}
        self.assertEqual(self.all["claude-code"].efforts, one_to_one)
        self.assertEqual(self.all["codex"].efforts, one_to_one)
        self.assertEqual(self.all["codex"].role_models, {})

    def test_the_versions_and_the_date(self) -> None:
        claude, codex = self.all["claude-code"], self.all["codex"]
        self.assertEqual(claude.checked_on_version, "2.1.289")
        self.assertEqual(claude.oldest_supported_version, "2.1.281")
        self.assertEqual(codex.checked_on_version, "0.160.0")
        self.assertIsNone(codex.oldest_supported_version)
        self.assertEqual(claude.checked_on_date, datetime.date(2026, 10, 5))
        self.assertEqual(codex.checked_on_date, datetime.date(2026, 10, 5))

    def test_how_each_model_list_is_read(self) -> None:
        claude, codex = self.all["claude-code"].model_list, self.all["codex"].model_list
        self.assertIsNone(claude.command)
        self.assertIsNone(claude.offline_command)
        self.assertFalse(claude.experimental)
        self.assertIn("no command", claude.note)
        self.assertEqual(codex.command, ("codex", "debug", "models"))
        self.assertEqual(codex.offline_command, ("codex", "debug", "models", "--bundled"))
        self.assertTrue(codex.experimental)
        self.assertIn("experimental", codex.note)

    def test_the_question_p3_3_asks(self) -> None:
        claude, codex = self.all["claude-code"], self.all["codex"]
        self.assertIs(codex.accepts("gpt-6-astra", "ultra"), True)
        self.assertIs(codex.accepts("gpt-6-luna", "ultra"), False)
        self.assertIs(codex.accepts("gpt-6-luna", "max"), True)
        self.assertIs(codex.accepts("gpt-5.5", "max"), False)
        self.assertIsNone(codex.accepts("gpt-7-not-yet", "low"))
        self.assertIs(claude.accepts("opus", "xhigh"), True)
        self.assertIs(claude.accepts("opus", "ultra"), False)
        self.assertIs(claude.accepts("haiku", "low"), False)
        self.assertFalse(claude.model("haiku").takes_effort)
        self.assertTrue(claude.model("sonnet").takes_effort)
        self.assertIsNone(claude.accepts("claude-opus-5-5", "high"))
        self.assertIsNone(claude.model("claude-opus-5-5"))

    def test_the_values_reached_only_by_an_override(self) -> None:
        """`xhigh` and `ultra` are accepted values and not framework names."""
        for name, extra in (("claude-code", {"xhigh"}), ("codex", {"xhigh", "ultra"})):
            with self.subTest(provider=name):
                loaded = self.all[name]
                accepted = {value for model in loaded.models.values() for value in model.efforts}
                self.assertEqual(accepted - set(loaded.efforts.values()), extra)

    def test_the_models_keep_the_files_order(self) -> None:
        self.assertEqual(list(self.all["claude-code"].models), ["haiku", "sonnet", "opus", "fable"])


class RepositoryDictionaryTests(support.ScratchCase):
    """The dictionaries that ship. Nothing here names a version, a date or
    a model: a dictionary brought up to a newer provider edits no test."""

    def setUp(self) -> None:
        super().setUp()
        self.all = dictionary.load_all(self.repository())
        self.files = dictionary.files(self.repository())

    def test_both_providers_have_one_and_each_validates(self) -> None:
        self.assertLessEqual({"claude-code", "codex"}, set(self.all))
        for name, loaded in self.all.items():
            with self.subTest(provider=name):
                self.assertEqual(loaded.provider, name)
                self.assertEqual(loaded.file, support.REPOSITORY / "providers" / name / "dictionary.toml")
                self.assertEqual(dictionary.load_file(loaded.file), loaded)

    def test_the_cache_each_maps(self) -> None:
        claude, codex = self.all["claude-code"], self.all["codex"]
        # Claude Code maps the long cache to a lifetime a definition takes;
        # Codex has no such setting and maps nothing.
        self.assertEqual(set(claude.cache), {"long"})
        self.assertIn(claude.cache["long"], definitions.CACHE_TTLS)
        self.assertNotEqual(claude.cache["long"], definitions.CACHE_TTLS[0])
        self.assertEqual(codex.cache, {})
        # The frontmatter key needs Claude Code 2.1.248: no supported version
        # is older, so nothing checks a version for it.
        self.assertGreaterEqual(dictionary.parse_version(claude.oldest_supported_version), (2, 1, 248))

    def test_the_compaction_limit_each_states(self) -> None:
        # Claude Code keeps the first 5,000 tokens of an invoked skill after
        # a compaction; Codex documents no such cut, so it has no limit.
        self.assertEqual(self.all["claude-code"].compaction_tokens, 5000)
        self.assertIsNone(self.all["codex"].compaction_tokens)

    def test_each_names_its_product(self) -> None:
        self.assertEqual((self.all["claude-code"].title, self.all["codex"].title), ("Claude Code", "Codex"))

    def test_each_has_line_feeds_only_and_a_comment_header(self) -> None:
        for name, file in self.files.items():
            with self.subTest(provider=name):
                raw = file.read_bytes()
                self.assertNotIn(b"\r", raw)
                header = raw.decode("utf-8").split("\n\n")[0]
                self.assertTrue(all(line.startswith("#") for line in header.splitlines()), header)
                self.assertIn("`init`", header)
                self.assertIn("confirms", header)

    def test_each_carries_the_schema_version(self) -> None:
        for name, file in self.files.items():
            with self.subTest(provider=name):
                self.assertEqual(tomlio.load(file)["schema_version"], dictionary.SCHEMA_VERSION)

    def test_every_tier_and_every_effort_name_is_mapped(self) -> None:
        for name, loaded in self.all.items():
            with self.subTest(provider=name):
                self.assertEqual(tuple(loaded.tiers), schema.TIERS)
                self.assertEqual(tuple(loaded.efforts), schema.EFFORTS)

    def test_the_versions_are_versions_and_the_oldest_is_not_newer(self) -> None:
        for name, loaded in self.all.items():
            with self.subTest(provider=name):
                checked = dictionary.parse_version(loaded.checked_on_version)
                self.assertIsInstance(loaded.checked_on_date, datetime.date)
                if loaded.oldest_supported_version is not None:
                    self.assertLessEqual(dictionary.parse_version(loaded.oldest_supported_version), checked)

    def test_a_list_command_is_given_or_a_note_says_why_not(self) -> None:
        for name, loaded in self.all.items():
            with self.subTest(provider=name):
                listing = loaded.model_list
                if listing.command is None:
                    self.assertIsNone(listing.offline_command)
                    self.assertTrue(listing.note)
                if listing.experimental:
                    self.assertIn("experimental", listing.note)

    def test_a_mapped_model_is_listed_and_not_hidden(self) -> None:
        for name, loaded in self.all.items():
            for tier, model in loaded.tiers.items():
                with self.subTest(provider=name, tier=tier):
                    self.assertIsNotNone(loaded.model(model))
                    self.assertNotEqual(loaded.model(model).visibility, "hide")

    def test_a_mapped_model_accepts_every_mapped_effort_or_takes_none(self) -> None:
        for name, loaded in self.all.items():
            for tier, model in loaded.tiers.items():
                entry = loaded.model(model)
                if not entry.takes_effort:
                    continue
                for effort, value in loaded.efforts.items():
                    with self.subTest(provider=name, tier=tier, effort=effort):
                        self.assertTrue(loaded.accepts(model, value))

    def test_the_comments_say_what_the_sources_say(self) -> None:
        """Review findings on the comments, pinned by their substance."""
        codex = " ".join(self.files["codex"].read_text(encoding="utf-8").replace("#", " ").split())
        self.assertNotIn("three current models", codex)
        self.assertIn("share a model by choice", codex)
        claude = " ".join(self.files["claude-code"].read_text(encoding="utf-8").replace("#", " ").split())
        self.assertNotIn("every kind of session", claude)
        self.assertIn("`agents-md` plugin is disabled", claude)
        self.assertIn("first session after an upgrade", claude)
        self.assertIn("read instead", claude)


class CodexListTests(support.ScratchCase):
    """The Codex dictionary against the saved `codex debug models` output of
    the version it was checked on. The saved list is found by that version,
    so a dictionary brought up to a newer one needs a new saved list beside
    the old (see fixtures/README.md) and no change here; until that list is
    saved, the comparison is skipped and says so."""

    def setUp(self) -> None:
        super().setUp()
        self.codex = dictionary.load(self.repository(), "codex")
        self.saved = support.FIXTURES / f"codex-debug-models-{self.codex.checked_on_version}.json"

    def listed(self) -> list:
        if not self.saved.is_file():
            self.skipTest(f"no saved model list for Codex {self.codex.checked_on_version}: {self.saved.name}")
        return json.loads(self.saved.read_text(encoding="utf-8"))["models"]

    def test_every_saved_list_is_named_in_the_fixtures_readme(self) -> None:
        readme = (support.FIXTURES / "README.md").read_text(encoding="utf-8")
        saved = sorted(support.FIXTURES.glob(CODEX_LIST_PATTERN))
        self.assertTrue(saved)
        for file in saved:
            with self.subTest(file=file.name):
                self.assertIn(file.name, readme)

    def test_every_saved_list_holds_only_the_reduced_keys(self) -> None:
        for file in sorted(support.FIXTURES.glob(CODEX_LIST_PATTERN)):
            with self.subTest(file=file.name):
                self.assertNotIn(b"\r", file.read_bytes())
                for entry in json.loads(file.read_text(encoding="utf-8"))["models"]:
                    self.assertEqual(
                        set(entry), {"slug", "visibility", "default_reasoning_level", "supported_reasoning_levels"}
                    )
                    for level in entry["supported_reasoning_levels"]:
                        self.assertEqual(set(level), {"effort"})

    def test_the_models_agree_in_name_and_order(self) -> None:
        self.assertEqual(list(self.codex.models), [entry["slug"] for entry in self.listed()])

    def test_each_models_efforts_visibility_and_default_agree(self) -> None:
        for entry in self.listed():
            with self.subTest(model=entry["slug"]):
                model = self.codex.model(entry["slug"])
                self.assertEqual(
                    list(model.efforts), [level["effort"] for level in entry["supported_reasoning_levels"]]
                )
                self.assertEqual(model.visibility, entry["visibility"])
                self.assertEqual(model.default_effort, entry["default_reasoning_level"])

    def test_every_mapped_model_is_listed_for_selection(self) -> None:
        offered = {entry["slug"] for entry in self.listed() if entry["visibility"] == "list"}
        self.assertLessEqual(set(self.codex.tiers.values()), offered)

    def test_every_mapped_effort_value_is_one_the_list_has(self) -> None:
        values = {level["effort"] for entry in self.listed() for level in entry["supported_reasoning_levels"]}
        self.assertLessEqual(set(self.codex.efforts.values()), values)


class LoadTests(support.CloneCase):
    """A fixture dictionary in a clone of the test's own."""

    def test_a_valid_dictionary(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY)
        loaded = dictionary.load(self.where(), "acme")
        self.assertEqual((loaded.provider, loaded.file), ("acme", self.dictionary))
        self.assertEqual(loaded.checked_on_version, "9.9.9")
        self.assertEqual(loaded.checked_on_date, datetime.date(2026, 10, 5))
        self.assertEqual(loaded.oldest_supported_version, "9.0")
        self.assertEqual(
            loaded.model_list,
            dictionary.ModelList(("acme", "models"), ("acme", "models", "--offline"), True, "May change."),
        )
        self.assertEqual(loaded.tiers["frontier"], "a.large")
        self.assertEqual(loaded.efforts["max"], "extreme")
        self.assertEqual(loaded.role_models, {})
        self.assertEqual(list(loaded.models), ["a-small", "a-mid", "a.large", "a-plain"])
        self.assertEqual(
            loaded.model("a-mid"),
            dictionary.Model("a-mid", ("minimal", "medium", "high", "extreme"), "list", "medium"),
        )
        self.assertEqual(loaded.model("a-small"), dictionary.Model("a-small", ("minimal", "medium")))
        self.assertIs(loaded.accepts("a.large", "beyond"), True)
        self.assertIs(loaded.accepts("a-small", "extreme"), False)
        self.assertIs(loaded.accepts("a-plain", "minimal"), False)
        self.assertFalse(loaded.model("a-plain").takes_effort)
        self.assertIsNone(loaded.accepts("a-unknown", "minimal"))
        self.assertEqual(loaded.settings, {"tiers": loaded.tiers, "efforts": loaded.efforts})
        self.assertIsNone(loaded.compaction_tokens)
        # No display name: a message names the provider by its directory.
        self.assertEqual((loaded.display_name, loaded.title), (None, "acme"))

    def test_a_compaction_limit(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY + "\n[skills]\ncompaction_tokens = 7\n")
        self.assertEqual(dictionary.load(self.where(), "acme").compaction_tokens, 7)
        self.write(self.dictionary, support.VALID_DICTIONARY + "\n[skills]\n")
        self.assertIsNone(dictionary.load(self.where(), "acme").compaction_tokens)

    def test_the_optional_keys_may_be_absent(self) -> None:
        text = support.VALID_DICTIONARY
        for line in (
            "schema_version = 1\n",
            'oldest_supported_version = "9.0"\n',
            'command = ["acme", "models"]\noffline_command = ["acme", "models", "--offline"]\n',
            "experimental = true\n",
            'note = "May change."\n',
        ):
            self.assertIn(line, text)
            text = text.replace(line, "")
        self.write(self.dictionary, text)
        loaded = dictionary.load_file(self.dictionary)
        self.assertEqual(loaded.provider, "acme")
        self.assertIsNone(loaded.oldest_supported_version)
        self.assertEqual(loaded.model_list, dictionary.ModelList(None, None, False, ""))

    def test_a_dictionarys_own_role_models(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY + '\n[role_models]\ncoder-hard = "a-full-model-id"\n')
        loaded = dictionary.load_file(self.dictionary)
        self.assertEqual(loaded.role_models, {"coder-hard": "a-full-model-id"})
        self.assertEqual(loaded.settings["role_models"], {"coder-hard": "a-full-model-id"})

    def test_a_dictionarys_cache_is_no_setting(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY)
        self.assertEqual(dictionary.load_file(self.dictionary).cache, {})
        self.write(self.dictionary, support.VALID_DICTIONARY + '\n[cache]\nlong = "1h"\n')
        loaded = dictionary.load_file(self.dictionary)
        self.assertEqual(loaded.cache, {"long": "1h"})
        self.assertEqual(set(loaded.settings), {"tiers", "efforts"})
        self.assertFalse([key for key in settings.resolve(self.where(), ("providers",)) if ".cache" in key])

    def test_a_cache_value_is_one_the_providers_definition_takes(self) -> None:
        self.assertEqual(dictionary.CACHE_VALUES, {"claude-code": ("5m", "1h")})
        self.assertIs(definitions.CACHE_TTLS, dictionary.CACHE_VALUES["claude-code"])
        for value in ("5m", "1h"):
            self.write(self.dictionary, support.VALID_DICTIONARY + f'\n[cache]\nlong = "{value}"\n')
            problems: list[str] = []
            self.assertEqual(dictionary.check_file(self.dictionary, "claude-code", problems).cache, {"long": value})
            self.assertEqual(problems, [])
        for value in ("2h", "1H", "1h ", " 1h", "60m", "1hr"):
            with self.subTest(value):
                self.write(self.dictionary, support.VALID_DICTIONARY + f'\n[cache]\nlong = "{value}"\n')
                problems = []
                self.assertIsNone(dictionary.check_file(self.dictionary, "claude-code", problems))
                self.assertEqual(problems, [
                    f'{self.dictionary}: cache.long: a claude-code definition does not take "{value}"; '
                    "accepted values: 5m, 1h"
                ])
                # A provider with no such key: the entry is used by nothing and not looked at.
                self.assertEqual(dictionary.load_file(self.dictionary).cache, {"long": value})

    def test_a_byte_order_mark_and_windows_line_endings_are_read(self) -> None:
        self.dictionary.parent.mkdir(parents=True)
        self.dictionary.write_bytes(b"\xef\xbb\xbf" + support.VALID_DICTIONARY.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(dictionary.load_file(self.dictionary).tiers["fast"], "a-small")

    def test_providers_without_a_dictionary_are_skipped(self) -> None:
        self.assertEqual(dictionary.load_all(self.where()), {})
        self.assertEqual(dictionary.files(self.where()), {})
        (self.clone / "providers" / "empty").mkdir(parents=True)
        self.write(self.dictionary, support.VALID_DICTIONARY)
        self.write(self.dictionary_file("zeta"), support.VALID_DICTIONARY)
        self.assertEqual(list(dictionary.load_all(self.where())), ["acme", "zeta"])
        self.assertIsNone(dictionary.load(self.where(), "empty"))

    def test_parse_version(self) -> None:
        self.assertEqual(dictionary.parse_version("2.1.289"), (2, 1, 289))
        self.assertLess(dictionary.parse_version("2.1.99"), dictionary.parse_version("2.1.281"))
        self.assertLess(dictionary.parse_version("0.160"), dictionary.parse_version("0.160.0"))
        for text in ("", "v2.1", "2.1.", "2..1", "2.1-beta", "codex-cli 0.160.0"):
            with self.subTest(text=text):
                with self.assertRaises(SetupError):
                    dictionary.parse_version(text)

    def test_a_version_part_has_a_bounded_number_of_digits(self) -> None:
        self.assertEqual(dictionary.parse_version("123456789.0"), (123456789, 0))
        for text in ("1234567890", "1.1234567890", "9" * 5000, "1." + "9" * 5000):
            with self.subTest(length=len(text)):
                with self.assertRaises(SetupError) as caught:
                    dictionary.parse_version(text)
                (line,) = caught.exception.lines
                self.assertTrue(line.endswith("not a version (a part has more than 9 digits)"), line[-80:])
                self.assertLess(len(line), 120)

    def test_find_version_reads_what_a_provider_prints(self) -> None:
        cases = {
            "2.1.289 (Claude Code)": "2.1.289",
            "codex-cli 0.160.0": "0.160.0",
            "codex-cli 0.160.0\n": "0.160.0",
            "0.161.0-alpha.2": "0.161.0",
            "codex-cli 0.161.0-alpha.2 (build 7)": "0.161.0",
            "2.2.0-beta.1 (Claude Code)": "2.2.0",
            "1.2.3+build5": "1.2.3",
            "1.2.3rc1": "1.2.3",
            "v2.1": "2.1",
            "version 10.0, built 2026.10.05": "10.0",
            "2.1.289": "2.1.289",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                found = dictionary.find_version(text)
                self.assertEqual(found, expected)
                dictionary.parse_version(found)
        self.assertEqual(
            dictionary.parse_version(dictionary.find_version("2.1.289 (Claude Code)")), (2, 1, 289)
        )
        self.assertEqual(dictionary.parse_version(dictionary.find_version("codex-cli 0.160.0")), (0, 160, 0))

    def test_find_version_finds_none(self) -> None:
        for text in ("", "Claude Code", "codex-cli", "build 7", "no version 5 here", "1." + "9" * 5000 + " x"):
            with self.subTest(text=text[:30]):
                self.assertIsNone(dictionary.find_version(text))


class FaultTests(support.CloneCase):
    """Each fault names the file and the key."""

    def problems(self, text: str) -> list[str]:
        self.write(self.dictionary, text)
        with self.assertRaises(SetupError) as caught:
            dictionary.load(self.where(), "acme")
        for line in caught.exception.lines:
            self.assertTrue(line.startswith(f"{self.dictionary}: "), line)
        found = [line[len(f"{self.dictionary}: "):] for line in caught.exception.lines]
        # The same faults stop a reader of the providers group, and no other.
        with self.assertRaises(SetupError) as through_settings:
            settings.resolve(self.where(), ("providers",))
        self.assertEqual(through_settings.exception.lines, caught.exception.lines)
        settings.resolve(self.where(), ("process", "roles", "memory"))
        return found

    def changed(self, old: str, new: str) -> list[str]:
        self.assertIn(old, support.VALID_DICTIONARY)
        return self.problems(support.VALID_DICTIONARY.replace(old, new))

    def test_a_compaction_limit_is_a_positive_integer(self) -> None:
        for value, fault in (
            ('"5000"', "expected an integer, got a string"),
            ("true", "expected an integer, got a boolean"),
            ("5000.0", "expected an integer, got a float"),
            ("0", "0 is too small; the least allowed is 1"),
            ("-3", "-3 is too small; the least allowed is 1"),
        ):
            with self.subTest(value):
                self.assertEqual(
                    self.problems(support.VALID_DICTIONARY + f"\n[skills]\ncompaction_tokens = {value}\n"),
                    [f"skills.compaction_tokens: {fault}"],
                )

    def test_a_display_name_is_a_string(self) -> None:
        self.assertEqual(
            self.changed("schema_version = 1\n", "schema_version = 1\ndisplay_name = 7\n"),
            ["display_name: expected a string, got an integer"],
        )

    def test_an_unknown_key(self) -> None:
        known = (
            "schema_version, display_name, checked_on_version, checked_on_date, oldest_supported_version, model_list, "
            "tiers, efforts, role_models, cache, skills, models"
        )
        self.assertEqual(
            self.problems(support.VALID_DICTIONARY + '\n[cache]\nlong = "1h"\nshort = "5m"\n'),
            ["cache.short: unknown key; known here: long"],
        )
        self.assertEqual(
            self.problems(support.VALID_DICTIONARY + "\n[skills]\nkept_tokens = 5000\n"),
            ["skills.kept_tokens: unknown key; known here: compaction_tokens"],
        )
        self.assertEqual(
            self.problems(support.VALID_DICTIONARY + "\n[cache]\nlong = 60\n"),
            ["cache.long: expected a string, got an integer"],
        )
        self.assertEqual(
            self.changed("schema_version = 1\n", 'schema_version = 1\nchecked_on = "9.9.9"\n'),
            [f"checked_on: unknown key; known here: {known}"],
        )
        self.assertEqual(
            self.changed("experimental = true", "experimental = true\nstable = false"),
            ["model_list.stable: unknown key; known here: command, offline_command, experimental, note"],
        )
        self.assertEqual(
            self.changed('fast = "a-small"', 'fast = "a-small"\nhuge = "a-mid"'),
            ["tiers.huge: unknown key; known here: fast, standard, deep, frontier"],
        )
        self.assertEqual(
            self.changed('max = "extreme"', 'max = "extreme"\nultra = "beyond"'),
            ["efforts.ultra: unknown key; known here: low, medium, high, max"],
        )
        self.assertEqual(
            self.changed('visibility = "hide"', 'visibility = "hide"\ncontext = 1'),
            ['models."a.large".context: unknown key; known here: efforts, visibility, default_effort'],
        )

    def test_a_wrong_type(self) -> None:
        cases = {
            ('checked_on_version = "9.9.9"', "checked_on_version = 9.9"):
                "checked_on_version: expected a string, got a float",
            ('checked_on_date = "2026-10-05"', "checked_on_date = 2026-10-05"):
                "checked_on_date: expected a string, got a date",
            ("experimental = true", 'experimental = "yes"'):
                "model_list.experimental: expected a boolean, got a string",
            ('command = ["acme", "models"]', 'command = "acme models"'):
                "model_list.command: expected an array of strings, got a string",
            ('command = ["acme", "models"]', 'command = ["acme", 1]'):
                "model_list.command: expected an array of strings, but item 2 is an integer",
            ('fast = "a-small"', "fast = 1"): "tiers.fast: expected a string, got an integer",
            ('low = "minimal"', "low = false"): "efforts.low: expected a string, got a boolean",
            ('efforts = ["minimal", "medium"]', 'efforts = "minimal"'):
                "models.a-small.efforts: expected an array of strings, got a string",
            ('visibility = "hide"', "visibility = true"):
                'models."a.large".visibility: expected a string, got a boolean',
            ('default_effort = "medium"', "default_effort = 2"):
                "models.a-mid.default_effort: expected a string, got an integer",
        }
        for (old, new), expected in cases.items():
            with self.subTest(new=new):
                self.assertEqual(self.changed(old, new), [expected])

    def test_a_table_where_a_value_belongs_and_the_reverse(self) -> None:
        text = support.VALID_DICTIONARY.split("[model_list]")[0]
        self.assertIn(
            "models: expected a table, got an array",
            self.problems(text + 'models = ["a-small"]\n[model_list]\n[tiers]\n[efforts]\n'),
        )
        self.assertIn(
            "models.a-small: expected a table, got a string",
            self.problems(text + '[model_list]\n[tiers]\n[efforts]\n[models]\na-small = "x"\n'),
        )
        self.assertIn(
            "tiers: expected a table, got a string",
            self.problems(text + 'tiers = "x"\n[model_list]\n[efforts]\n[models.m]\nefforts = []\n'),
        )

    def test_a_tier_mapped_to_a_model_the_file_does_not_list(self) -> None:
        self.assertEqual(
            self.changed('deep = "a-mid"', 'deep = "a-huge"'),
            ['tiers.deep: "a-huge" is not a model this file lists under models; '
             "listed: a-small, a-mid, a.large, a-plain"],
        )

    def test_an_effort_value_no_listed_model_accepts(self) -> None:
        self.assertEqual(
            self.changed('max = "extreme"', 'max = "ultra"'),
            ['efforts.max: no model this file lists accepts "ultra"; '
             "accepted values: minimal, medium, high, extreme, beyond"],
        )

    def test_a_default_effort_the_model_does_not_accept(self) -> None:
        self.assertEqual(
            self.changed('default_effort = "medium"', 'default_effort = "beyond"'),
            ['models.a-mid.default_effort: "beyond" is not among the model\'s efforts: minimal, medium, high, extreme'],
        )

    def test_a_missing_key(self) -> None:
        self.assertEqual(
            self.changed('checked_on_version = "9.9.9"\n', ""),
            ["checked_on_version: missing; a dictionary must have it"],
        )
        self.assertEqual(
            self.changed('checked_on_date = "2026-10-05"\n', ""),
            ["checked_on_date: missing; a dictionary must have it"],
        )
        self.assertEqual(
            self.changed('standard = "a-mid"\n', ""),
            ["tiers.standard: missing; a dictionary maps every one of fast, standard, deep, frontier"],
        )
        self.assertEqual(
            self.changed('high = "high"\n', ""),
            ["efforts.high: missing; a dictionary maps every one of low, medium, high, max"],
        )
        self.assertEqual(
            self.changed("[models.a-plain]\nefforts = []\n", "[models.a-plain]\n"),
            ["models.a-plain.efforts: missing; write an empty array for a model that takes no effort setting"],
        )
        self.assertEqual(
            self.problems('checked_on_version = "1"\nchecked_on_date = "2026-10-05"\n'),
            [f"{key}: missing; a dictionary must have it" for key in ("model_list", "tiers", "efforts", "models")],
        )
        self.assertEqual(
            self.problems(""),
            [
                f"{key}: missing; a dictionary must have it"
                for key in ("checked_on_version", "checked_on_date", "model_list", "tiers", "efforts", "models")
            ],
        )

    def test_versions_and_the_date(self) -> None:
        self.assertEqual(
            self.changed('checked_on_version = "9.9.9"', 'checked_on_version = "v9.9"'),
            ['checked_on_version: "v9.9" is not a version (digits separated by dots)'],
        )
        self.assertEqual(
            self.changed('oldest_supported_version = "9.0"', 'oldest_supported_version = "9.x"'),
            ['oldest_supported_version: "9.x" is not a version (digits separated by dots)'],
        )
        self.assertEqual(
            self.changed('oldest_supported_version = "9.0"', 'oldest_supported_version = "9.10"'),
            ["oldest_supported_version: 9.10 is newer than checked_on_version (9.9.9)"],
        )
        for bad in ("05.10.2026", "2026-13-01", "2026-02-30", "2026-10-5"):
            with self.subTest(date=bad):
                self.assertEqual(
                    self.changed('checked_on_date = "2026-10-05"', f'checked_on_date = "{bad}"'),
                    [f'checked_on_date: "{bad}" is not a date (YYYY-MM-DD)'],
                )
        self.assertEqual(
            self.changed('checked_on_version = "9.9.9"', 'checked_on_version = ""'),
            ["checked_on_version: must not be empty"],
        )

    def test_the_model_list(self) -> None:
        self.assertEqual(
            self.changed('command = ["acme", "models"]\n', ""),
            ["model_list.offline_command: is given without model_list.command"],
        )
        self.assertEqual(
            self.changed('command = ["acme", "models"]', "command = []"),
            ["model_list.command: must not be empty; leave the key out where there is no command"],
        )
        self.assertEqual(
            self.changed('command = ["acme", "models"]', 'command = ["acme", ""]'),
            ["model_list.command: item 2 must not be empty"],
        )

    def test_the_models(self) -> None:
        self.assertEqual(
            self.changed('efforts = ["minimal", "medium"]', 'efforts = ["minimal", "medium", "minimal"]'),
            ['models.a-small.efforts: "minimal" is given twice'],
        )
        self.assertEqual(
            self.changed("[models.a-plain]", '[models." "]'),
            ['models." ": a model name must not be empty'],
        )
        text = support.VALID_DICTIONARY.split("[models.a-small]")[0]
        self.assertIn("models: must list at least one model", self.problems(text + "[models]\n"))

    def test_the_schema_version(self) -> None:
        (line,) = self.changed("schema_version = 1", "schema_version = 2\nfuture_key = 1")
        self.assertTrue(line.startswith("schema_version: 2 is newer than this tool reads (1)"), line)
        self.assertEqual(
            self.changed("schema_version = 1", 'schema_version = "1"'),
            ["schema_version: expected an integer, got a string"],
        )
        self.assertEqual(
            self.changed("schema_version = 1", "schema_version = 0"),
            ["schema_version: 0 is not a schema version; the first is 1"],
        )

    def test_every_fault_of_a_file_is_reported_at_once(self) -> None:
        text = support.VALID_DICTIONARY.replace('deep = "a-mid"', 'deep = "a-huge"').replace(
            'max = "extreme"', 'max = "ultra"'
        ).replace('default_effort = "medium"', 'default_effort = "beyond"')
        self.assertEqual(
            [line.split(":")[0] for line in self.problems(text)],
            ["tiers.deep", "efforts.max", "models.a-mid.default_effort"],
        )
        shape = support.VALID_DICTIONARY.replace("experimental = true", "experimental = 1").replace(
            'low = "minimal"', "low = 1\nlowest = 2"
        )
        self.assertEqual(
            [line.split(":")[0] for line in self.problems(shape)],
            ["model_list.experimental", "efforts.low", "efforts.lowest"],
        )

    def test_a_file_that_does_not_parse_and_one_that_is_a_directory(self) -> None:
        (line,) = self.problems("this is [not toml\n")
        self.assertTrue(line.startswith("is not valid TOML"), line)
        self.dictionary.unlink()
        self.dictionary.mkdir()
        with self.assertRaises(SetupError) as caught:
            dictionary.load_all(self.where())
        self.assertEqual(caught.exception.lines, [f"{self.dictionary}: is not a file"])

    def test_a_version_of_thousands_of_digits(self) -> None:
        long = "9" * 5000
        (line,) = self.changed('checked_on_version = "9.9.9"', f'checked_on_version = "{long}"')
        self.assertEqual(
            line, f'checked_on_version: "{"9" * 40}..." is not a version (a part has more than 9 digits)'
        )
        (line,) = self.changed('oldest_supported_version = "9.0"', f'oldest_supported_version = "1.{long}"')
        self.assertTrue(line.startswith('oldest_supported_version: "1.999'), line[:60])
        self.assertTrue(line.endswith("is not a version (a part has more than 9 digits)"), line[-60:])

    def test_a_blank_version_or_note(self) -> None:
        self.assertEqual(
            self.changed('checked_on_version = "9.9.9"', 'checked_on_version = " "'),
            ["checked_on_version: must not be blank; it holds only white space"],
        )
        self.assertEqual(
            self.changed('command = ["acme", "models"]', 'command = ["acme", " "]'),
            ["model_list.command: item 2 must not be blank"],
        )


class OddPlacesTests(support.CloneCase):
    """What is at a dictionary's place and is not a readable file is said,
    never taken for a provider without a dictionary."""

    def problems(self) -> list[str]:
        with self.assertRaises(SetupError) as caught:
            dictionary.load_all(self.where())
        with self.assertRaises(SetupError) as through_settings:
            settings.resolve(self.where(), ("providers",))
        self.assertEqual(through_settings.exception.lines, caught.exception.lines)
        settings.resolve(self.where(), ("process", "roles", "memory"))
        return caught.exception.lines

    def link(self, target, link) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are not permitted here: {exc}")

    def test_a_dangling_link_where_a_dictionary_belongs(self) -> None:
        self.write(self.dictionary_file("beta"), support.VALID_DICTIONARY)
        self.link(self.root / "gone.toml", self.dictionary)
        self.assertIn("acme", dictionary.files(self.where()))
        self.assertEqual(self.problems(), [f"link target missing: {self.dictionary}"])

    def test_a_link_that_leads_back_to_itself(self) -> None:
        self.link(self.dictionary, self.dictionary)
        self.assertEqual(self.problems(), [f"link target missing: {self.dictionary}"])

    def test_a_dangling_link_as_the_providers_directory(self) -> None:
        self.link(self.root / "gone", self.dictionary.parent)
        self.assertEqual(self.problems(), [f"link target missing: {self.dictionary.parent}"])

    def test_a_link_to_a_real_dictionary_is_read(self) -> None:
        real = self.write(self.root / "real.toml", support.VALID_DICTIONARY)
        self.link(real, self.dictionary)
        self.assertEqual(dictionary.load(self.where(), "acme").tiers["fast"], "a-small")

    def test_a_file_among_the_provider_directories_is_skipped(self) -> None:
        self.write(self.clone / "providers" / "README.md", "# Providers\n")
        self.write(self.dictionary, support.VALID_DICTIONARY)
        self.assertEqual(list(dictionary.load_all(self.where())), ["acme"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no FIFOs here")
    def test_a_fifo_where_a_dictionary_belongs_is_not_opened(self) -> None:
        self.dictionary.parent.mkdir(parents=True)
        os.mkfifo(self.dictionary)
        self.assertEqual(self.problems(), [f"{self.dictionary}: is not a file"])

    @unittest.skipUnless(support.can_lock_directories(), "permissions do not keep this process out")
    def test_directories_that_cannot_be_read(self) -> None:
        self.write(self.dictionary, support.VALID_DICTIONARY)
        providers = self.clone / "providers"
        for directory, expected in (
            (providers, f"{providers}: cannot be read: "),
            (self.dictionary.parent, f"{self.dictionary}: cannot be read: "),
        ):
            with self.subTest(directory=directory.name):
                os.chmod(directory, 0)
                try:
                    (line,) = self.problems()
                finally:
                    os.chmod(directory, 0o755)
                self.assertTrue(line.startswith(expected), line)


class FilledIsolationTests(support.ScratchCase):
    def test_show_providers_and_a_bare_show_open_both(self) -> None:
        for argv in (("providers",), ()):
            with self.subTest(argv=argv):
                with mock.patch.object(tomlio, "load", wraps=tomlio.load) as load:
                    self.assertEqual(self.show(*argv)[0], 0)
                opened = {call.args[0] for call in load.call_args_list}
                self.assertLessEqual({self.claude_code_dictionary, self.codex_dictionary}, opened)


class IsolationTests(support.CloneCase):
    """R5.3: only a reader of the providers group opens a dictionary."""

    def test_show_process_does_not_open_the_dictionaries(self) -> None:
        with mock.patch.object(dictionary, "load_all", side_effect=AssertionError("opened")) as load_all:
            with mock.patch.object(tomlio, "load", wraps=tomlio.load) as load:
                # Not "roles" alone: it resolves the profiles (test_profiles.py).
                for key in ("process", "process.docs_dir", "roles.high_stakes", "roles.coder", "memory.dir"):
                    with self.subTest(key=key):
                        self.assertEqual(self.show(key)[0], 0)
        load_all.assert_not_called()
        self.assertEqual({call.args[0] for call in load.call_args_list}, {self.defaults_file})

    def test_a_broken_dictionary_breaks_no_other_group(self) -> None:
        self.write(self.dictionary, "this is [not toml\n")
        for group in ("process", "roles", "memory"):
            with self.subTest(group=group):
                settings.resolve(self.where(), (group,))
        with self.assertRaises(SetupError):
            settings.resolve(self.where(), ("providers",))
        with self.assertRaises(SetupError):
            settings.resolve(self.where())


if __name__ == "__main__":
    unittest.main()
