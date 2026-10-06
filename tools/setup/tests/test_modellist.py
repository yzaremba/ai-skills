"""A provider's model list: reading it through a stub program, reading what
it prints leniently, and comparing it with the dictionary.

No real provider is started: ``provider_stub`` stands in for the program,
and the code under test finds it on ``PATH`` and starts it itself.
"""
from __future__ import annotations

import json
import os
import time
import unittest
from unittest import mock

import provider_stub
import support
from provider_stub import BUNDLED, LIVE
from wfsetup import dictionary, modellist

EQUAL = "model-list-equal.json"
MISSING = "model-list-missing-mapped.json"
NEW = "model-list-new-model.json"


class ListCase(support.ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.stub = provider_stub.StubProgram(self.root / "stub")
        self.codex = dictionary.load(self.locations(), "codex")
        self.claude = dictionary.load(self.locations(), "claude-code")

    def read(self, **options) -> modellist.Reading:
        return modellist.read(self.codex, self.stub.environ(), **options)


class ReadingTests(ListCase):
    def test_the_list_is_read_with_the_dictionarys_command(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(EQUAL))
        reading = self.read()
        self.assertEqual(reading.source, modellist.LIVE)
        self.assertEqual(reading.command, ("codex", "debug", "models"))
        self.assertEqual(self.stub.calls(), [["debug", "models"]])
        self.assertEqual(
            [entry.name for entry in reading.models],
            ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-reserve", "gpt-5.5"],
        )
        self.assertEqual(reading.model("gpt-6-luna").efforts, ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(reading.model("gpt-6.1-sol").default_effort, "low")
        self.assertEqual(reading.notes, ())
        self.assertIn("checked against the list of `codex debug models` (6 models, 1 of them hidden)", reading.describe())

    def test_the_program_gets_the_environment_given(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(EQUAL))
        modellist.read(self.codex, self.stub.environ(**{provider_stub.MARK: "the caller's"}))
        self.assertEqual(self.stub.marks(), ["the caller's"])

    def test_the_program_where_it_was_already_found_is_used(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(EQUAL))
        environ = {**self.stub.environ(), "PATH": str(self.root / "nowhere")}
        reading = modellist.read(self.codex, environ, program_file=str(self.stub.program))
        self.assertEqual(reading.source, modellist.LIVE)

    def test_hidden_entries_are_not_offered(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(NEW))
        reading = self.read()
        self.assertEqual(
            reading.offered(), ["gpt-7-nova", "gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.5"]
        )
        self.assertFalse(reading.model("gpt-reserve").offered)
        self.assertFalse(reading.model("gpt-internal").offered)

    def test_a_failed_refresh_falls_back_to_the_bundled_list(self) -> None:
        self.stub.answer(LIVE, "", code=1, stderr="Error: failed to refresh the models\nmore\n")
        self.stub.answer(BUNDLED, provider_stub.fixture(EQUAL))
        reading = self.read()
        self.assertEqual(reading.source, modellist.OFFLINE)
        self.assertEqual(reading.command, ("codex", "debug", "models", "--bundled"))
        self.assertEqual(self.stub.calls(), [["debug", "models"], ["debug", "models", "--bundled"]])
        (note,) = reading.notes
        self.assertTrue(note.startswith("`codex debug models` exited with code 1: "), note)
        if os.name == "posix":
            # On Windows the launcher is a command file, and the command
            # interpreter may put a line of its own before the program's.
            self.assertEqual(note, "`codex debug models` exited with code 1: Error: failed to refresh the models")
        self.assertIn("the list shipped with the program", reading.describe())
        self.assertIn("exited with code 1", reading.describe())
        self.assertEqual(len(reading.models), 6)

    def test_a_timeout_falls_back_and_the_program_is_ended(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(EQUAL), sleep=60)
        self.stub.answer(BUNDLED, provider_stub.fixture(EQUAL))
        started = time.monotonic()
        reading = self.read(timeout=1)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(reading.source, modellist.OFFLINE)
        self.assertEqual(reading.notes, ("`codex debug models` did not finish within 1 seconds",))

    def test_both_commands_timing_out_gives_no_list(self) -> None:
        self.stub.answer(LIVE, sleep=60)
        self.stub.answer(BUNDLED, sleep=60)
        started = time.monotonic()
        reading = self.read(timeout=0.5)
        self.assertLess(time.monotonic() - started, 30)
        self.assertFalse(reading.has_list)
        self.assertIn("`codex debug models` did not finish within 0.5 seconds", reading.reason)
        self.assertIn("`codex debug models --bundled` did not finish within 0.5 seconds", reading.reason)

    def test_the_default_timeout_is_read_at_the_call(self) -> None:
        self.stub.answer(LIVE, sleep=60)
        self.stub.answer(BUNDLED, provider_stub.fixture(EQUAL))
        with mock.patch.object(modellist, "DEFAULT_TIMEOUT", 0.5):
            self.assertEqual(self.read().source, modellist.OFFLINE)

    def test_output_that_is_not_json_falls_back_then_gives_no_list(self) -> None:
        self.stub.answer(LIVE, "Usage: codex debug <COMMAND>\n")
        self.stub.answer(BUNDLED, provider_stub.fixture(EQUAL))
        self.assertEqual(self.read().source, modellist.OFFLINE)
        self.stub.answer(BUNDLED, "<html>not found</html>")
        reading = self.read()
        self.assertEqual(reading.source, modellist.NONE)
        self.assertEqual(reading.models, ())
        self.assertIn("printed what is not a model list", reading.reason)
        self.assertEqual(
            reading.describe(),
            f"no model list: {reading.reason}; the dictionary alone is used",
        )
        self.assertIsNone(modellist.compare(self.codex, reading))
        self.assertIs(modellist.effective(self.codex, reading), self.codex)

    def test_json_of_another_shape_is_not_a_list(self) -> None:
        for text in ("[]", '{"error": "no"}', '{"models": {"a": 1}}', '"models"', "null", "17"):
            with self.subTest(text=text):
                self.stub.answer(LIVE, text)
                self.stub.answer(BUNDLED, text)
                self.assertFalse(self.read().has_list)

    def test_an_empty_list_is_not_a_list(self) -> None:
        self.stub.answer(LIVE, '{"models": []}')
        self.stub.answer(BUNDLED, provider_stub.fixture(EQUAL))
        reading = self.read()
        self.assertEqual(reading.source, modellist.OFFLINE)
        self.assertEqual(reading.notes, ("`codex debug models` printed a list with no model in it",))
        self.stub.answer(BUNDLED, '{"models": []}')
        self.assertFalse(self.read().has_list)

    def test_no_output_is_not_a_list(self) -> None:
        self.stub.answer(BUNDLED, " \n")
        reading = self.read()
        self.assertFalse(reading.has_list)
        self.assertIn("`codex debug models` printed nothing", reading.reason)

    def test_a_provider_with_no_command_has_no_list_and_starts_nothing(self) -> None:
        reading = modellist.read(self.claude, self.stub.environ())
        self.assertEqual(reading.source, modellist.NONE)
        self.assertEqual(
            reading.describe(),
            "no model list: claude-code has no command that lists models without starting a session; "
            "the dictionary alone is used",
        )
        self.assertEqual(self.stub.calls(), [])
        self.assertEqual(modellist.check(self.claude, self.stub.environ())[1], None)

    def test_a_program_that_is_not_on_path_gives_no_list(self) -> None:
        for environ in ({"PATH": str(self.root / "nowhere")}, {"PATH": ""}, {}):
            with self.subTest(environ=environ):
                reading = modellist.read(self.codex, environ)
                self.assertFalse(reading.has_list)
                self.assertEqual(reading.reason, "the program `codex` is not on PATH")
        self.assertEqual(self.stub.calls(), [])

    def test_a_program_that_cannot_be_started_gives_no_list(self) -> None:
        reading = modellist.read(self.codex, self.stub.environ(), program_file=str(self.root / "gone" / "codex"))
        self.assertFalse(reading.has_list)
        self.assertIn("could not be started", reading.reason)


class ParseTests(unittest.TestCase):
    def test_lines_around_the_object_are_skipped(self) -> None:
        body = json.dumps({"models": [{"slug": "a", "visibility": "list"}]}, indent=2)
        for text in (
            "WARNING: a newer version is available\n" + body + "\n",
            body + "\nnote: the catalog was refreshed\n",
            "warn {not json}\n{also not json\n" + body + "\ndone {\n",
            "notice\n" + json.dumps({"models": [{"slug": "a", "visibility": "list"}]}) + "\n",
            "﻿" + body,
        ):
            with self.subTest(text=text[:30]):
                self.assertEqual([entry.name for entry in modellist.parse(text.lstrip("﻿"))], ["a"])

    def test_an_object_without_models_before_the_list_is_passed_over(self) -> None:
        text = '{"level": "warn", "message": "slow"}\n{"models": [{"slug": "a"}]}\n'
        self.assertEqual([entry.name for entry in modellist.parse(text)], ["a"])

    def test_optional_keys_may_be_missing(self) -> None:
        (entry,) = modellist.parse('{"models": [{"slug": "bare"}]}')
        self.assertEqual(entry, modellist.Listed("bare", None, None, None))
        self.assertTrue(entry.offered)

    def test_unknown_keys_and_odd_entries_are_passed_over(self) -> None:
        found = modellist.parse(json.dumps({"models": [
            "a string",
            {"no_slug": True},
            {"slug": ""},
            {"slug": 7},
            {"slug": "a", "visibility": "list", "new_key": {"deep": [1, 2]},
             "supported_reasoning_levels": [{"effort": "low", "extra": 1}, {"effort": 3}, "high", {"effort": "low"}]},
            {"slug": "a", "visibility": "hide"},
            {"slug": "b", "visibility": 5, "default_reasoning_level": None, "supported_reasoning_levels": "none"},
        ]}))
        self.assertEqual(found, (
            modellist.Listed("a", ("low", "high"), "list", None),
            modellist.Listed("b", None, None, None),
        ))

    def test_what_is_not_a_list_says_why(self) -> None:
        for text, why in (
            ("", "printed nothing"),
            ("hello", "printed what is not a model list"),
            ('{"models": []}', "printed a list with no model in it"),
            ('{"models": [{"name": "x"}]}', "printed a list in which no entry names a model"),
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    modellist.parse(text)
                self.assertIn(why, str(caught.exception))


class ComparisonTests(ListCase):
    def compared(self, name: str, mapping=None) -> modellist.Comparison:
        self.stub.answer(LIVE, provider_stub.fixture(name))
        reading, found = modellist.check(self.codex, self.stub.environ(), mapping=mapping)
        self.assertTrue(reading.has_list)
        return found

    def test_a_list_that_holds_the_dictionarys_models_is_equal(self) -> None:
        found = self.compared(EQUAL)
        self.assertTrue(found.equal)
        self.assertTrue(found.dictionary_equal)
        self.assertEqual(found.lines(), [])

    def test_a_list_missing_a_mapped_model(self) -> None:
        found = self.compared(MISSING)
        self.assertEqual(found.missing_mapped, (("tiers.frontier", "gpt-6-astra"),))
        self.assertEqual(found.gone_models, ("gpt-6-astra",))
        self.assertEqual(found.new_models, ())
        self.assertFalse(found.equal)
        self.assertEqual(found.lines(), [
            'tiers.frontier = "gpt-6-astra": the model is not in the provider\'s list',
            "in the dictionary and not in the list: gpt-6-astra",
        ])

    def test_a_list_with_a_new_model(self) -> None:
        found = self.compared(NEW)
        self.assertEqual(found.new_models, ("gpt-7-nova",))
        self.assertEqual(found.new_hidden, ("gpt-internal",))
        self.assertEqual(found.missing_mapped, ())
        self.assertFalse(found.dictionary_equal)
        self.assertEqual(found.lines(), [
            "in the list and not in the dictionary: gpt-7-nova",
            "in the list as hidden entries and not in the dictionary: gpt-internal",
        ])

    def test_the_mapping_in_effect_is_what_is_compared(self) -> None:
        found = self.compared(EQUAL, {"tiers.deep": "gpt-9", "role_models.coder": "gpt-reserve", "tiers.fast": "gpt-6-luna"})
        self.assertEqual(found.missing_mapped, (("tiers.deep", "gpt-9"),))
        self.assertEqual(found.hidden_mapped, (("role_models.coder", "gpt-reserve"),))
        self.assertTrue(found.dictionary_equal)
        self.assertFalse(found.equal)

    def test_differences_of_efforts_visibility_and_default(self) -> None:
        data = json.loads(provider_stub.fixture(EQUAL))
        data["models"][3]["supported_reasoning_levels"].append({"effort": "ultra"})
        data["models"][5]["visibility"] = "hide"
        data["models"][0]["default_reasoning_level"] = "medium"
        del data["models"][1]["supported_reasoning_levels"]
        self.stub.answer(LIVE, json.dumps(data))
        reading, found = modellist.check(self.codex, self.stub.environ())
        self.assertEqual(found.effort_differences, (modellist.EffortDifference(
            "gpt-6-luna", ("low", "medium", "high", "xhigh", "max"), ("low", "medium", "high", "xhigh", "max", "ultra"),
        ),))
        self.assertEqual(found.visibility_differences, (("gpt-5.5", "list", "hide"),))
        self.assertEqual(found.default_effort_differences, (("gpt-6.1-sol", "low", "medium"),))
        self.assertEqual(len(found.lines()), 3)
        checked = modellist.effective(self.codex, reading)
        self.assertTrue(checked.accepts("gpt-6-luna", "ultra"))
        self.assertFalse(self.codex.accepts("gpt-6-luna", "ultra"))
        # An entry that does not say its efforts leaves the dictionary's.
        self.assertEqual(checked.model("gpt-6-astra").efforts, self.codex.model("gpt-6-astra").efforts)
        self.assertEqual(checked.model("gpt-5.5").visibility, "hide")

    def test_the_effective_dictionary_gains_the_new_models(self) -> None:
        self.stub.answer(LIVE, provider_stub.fixture(NEW))
        reading = self.read()
        checked = modellist.effective(self.codex, reading)
        self.assertTrue(checked.accepts("gpt-7-nova", "turbo"))
        self.assertIsNone(self.codex.accepts("gpt-7-nova", "turbo"))
        self.assertEqual(checked.tiers, self.codex.tiers)


class RepositoryTests(support.ScratchCase):
    """The repository's Codex dictionary beside the list saved with it."""

    def test_the_saved_list_equals_the_dictionary(self) -> None:
        known = dictionary.load(self.repository(), "codex")
        saved = support.FIXTURES / f"codex-debug-models-{known.checked_on_version}.json"
        if not saved.exists():
            self.skipTest(f"no list is saved for Codex {known.checked_on_version}")
        reading = modellist.Reading(
            "codex", modellist.LIVE, modellist.parse(saved.read_text(encoding="utf-8")), known.model_list.command
        )
        found = modellist.compare(known, reading)
        self.assertEqual(found.lines(), [])
        self.assertTrue(found.equal)
        self.assertEqual([entry.name for entry in reading.models], list(known.models))

    def test_every_dictionary_names_a_command_or_none(self) -> None:
        for provider, known in dictionary.load_all(self.repository()).items():
            with self.subTest(provider=provider):
                reading = modellist.read(known, {"PATH": ""})
                self.assertFalse(reading.has_list)
                self.assertTrue(reading.reason)


if __name__ == "__main__":
    unittest.main()
