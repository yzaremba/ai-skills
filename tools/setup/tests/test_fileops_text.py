"""Tests for setup's part of a user-owned file: marked blocks, exact lines,
JSON keys, and the project's ignore block.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from fileops_support import OpsCase
from wfsetup import blocks, fileops, fsio, jsonkeys
from wfsetup.errors import SetupError

START = b"<!-- workflow-setup:start -->"
END = b"<!-- workflow-setup:end -->"
BLOCK = START + b"\nours\n" + END + b"\n"
BOM = b"\xef\xbb\xbf"


class BlockCase(OpsCase):
    def setUp(self) -> None:
        super().setUp()
        self.file = self.home / ".claude" / "CLAUDE.md"

    def edit(self, content: str = "ours\n", path: Path | None = None, **options) -> fileops.Result:
        plan = self.plan()
        plan.edit_block(path or self.file, content, **options)
        return plan.apply()

    def remove(self, path: Path | None = None, **options) -> fileops.Result:
        plan = self.plan()
        plan.remove_block(path or self.file, **options)
        return plan.apply()

    def round_trip(self, original: bytes, expected: bytes, **options) -> None:
        """Adding gives ``expected``; removing gives ``original`` back."""
        self.put(self.file, original)
        self.edit(**options)
        self.assertEqual(self.file.read_bytes(), expected)
        after = self.snap()
        self.assertFalse(self.edit(**options).changed)
        self.assertEqual(self.snap(), after)
        self.remove(name=options.get("name", ""))
        self.assertEqual(self.file.read_bytes(), original)
        self.assertIsNone(self.record().get("home:.claude/CLAUDE.md"))


class BlockTests(BlockCase):
    def test_add_at_the_end(self) -> None:
        self.round_trip(b"# Mine\n\ntext\n", b"# Mine\n\ntext\n\n" + BLOCK)

    def test_update_changes_only_the_block(self) -> None:
        self.put(self.file, b"before\n\n" + BLOCK + b"\nafter\n")
        self.edit()  # the block holds what setup writes: it is taken into the record
        result = self.edit("new line one\nnew line two\n")
        self.assertIn("    block (unnamed): update", result.lines)
        self.assertEqual(
            self.file.read_bytes(),
            b"before\n\n" + START + b"\nnew line one\nnew line two\n" + END + b"\n\nafter\n",
        )

    def test_a_block_setup_did_not_record_is_taken_over_without_a_write(self) -> None:
        self.put(self.file, b"before\n\n" + BLOCK)
        result = self.edit()
        self.assertEqual(result.lines[-1], "update record home:.claude/CLAUDE.md")
        self.assertEqual(self.file.read_bytes(), b"before\n\n" + BLOCK)
        entry = self.record().get("home:.claude/CLAUDE.md")
        # Setup put no line ending there with it, and so takes none out.
        self.assertEqual(entry["blocks"], {"": {"sha256": fsio.sha256(BLOCK), "joint": {"where": None}}})
        self.assertIsNone(entry["original"])
        self.assertFalse(self.edit().changed)

    def test_no_final_newline(self) -> None:
        self.round_trip(b"# Mine\ntext", b"# Mine\ntext\n" + BLOCK)

    def test_crlf_file_gets_a_crlf_block(self) -> None:
        self.round_trip(b"# Mine\r\ntext\r\n", b"# Mine\r\ntext\r\n\r\n" + BLOCK.replace(b"\n", b"\r\n"))

    def test_crlf_without_a_final_line_ending(self) -> None:
        self.round_trip(b"# Mine\r\ntext", b"# Mine\r\ntext\r\n" + BLOCK.replace(b"\n", b"\r\n"))

    def test_bom_stays_first(self) -> None:
        self.round_trip(BOM + b"text\n", BOM + b"text\n\n" + BLOCK)
        self.round_trip(BOM + b"text\n", BOM + BLOCK + b"\ntext\n", place=fileops.HEAD)
        self.round_trip(BOM, BOM + BLOCK)

    def test_head_placement(self) -> None:
        self.round_trip(b"\n# Mine\n", BLOCK + b"\n\n# Mine\n", place=fileops.HEAD)

    def test_an_empty_file_of_the_user_is_left_empty_and_not_removed(self) -> None:
        self.round_trip(b"", BLOCK)
        self.assertTrue(self.file.exists())

    def test_odd_bytes_around_the_block_stay_as_they_are(self) -> None:
        original = "tabs\t \n\n\n  indented\r\nmixed\né中 \rlone cr\n\n\n".encode("utf-8")
        self.round_trip(original, original + b"\n" + BLOCK)

    def test_user_text_after_the_block_survives_update_and_removal(self) -> None:
        self.put(self.file, b"before\n")
        self.edit()
        self.file.write_bytes(self.file.read_bytes() + b"\nadded later\n")
        self.edit("changed\n")
        self.assertEqual(self.file.read_bytes(), b"before\n\n" + START + b"\nchanged\n" + END + b"\n\nadded later\n")
        self.remove()
        self.assertEqual(self.file.read_bytes(), b"before\n\nadded later\n")

    def test_two_named_blocks_in_one_file(self) -> None:
        self.put(self.file, b"mine\n")
        plan = self.plan()
        plan.edit_block(self.file, "one\n", name="first")
        plan.edit_block(self.file, "two\n", name="second")
        plan.edit_block(self.file, "plain\n")
        plan.apply()
        text = self.file.read_bytes()
        self.assertEqual(
            text,
            b"mine\n\n<!-- workflow-setup:start first -->\none\n<!-- workflow-setup:end first -->\n"
            b"\n<!-- workflow-setup:start second -->\ntwo\n<!-- workflow-setup:end second -->\n"
            b"\n" + START + b"\nplain\n" + END + b"\n",
        )
        self.assertEqual(sorted(self.record().get("home:.claude/CLAUDE.md")["blocks"]), ["", "first", "second"])
        self.edit("two, changed\n", name="second")
        self.assertEqual(self.file.read_bytes(), text.replace(b"two\n", b"two, changed\n"))
        self.remove(name="first")
        self.assertNotIn(b"first", self.file.read_bytes())
        self.assertIn(b"two, changed", self.file.read_bytes())
        self.remove(name="second")
        self.remove()
        self.assertEqual(self.file.read_bytes(), b"mine\n")

    def test_a_file_setup_created_is_removed_when_emptied(self) -> None:
        self.edit()
        self.assertEqual(self.file.read_bytes(), BLOCK)
        self.assertTrue(self.record().get("home:.claude/CLAUDE.md")["created"])
        self.remove()
        self.assertFalse(self.file.exists())
        self.assertIsNone(self.record().get("home:.claude/CLAUDE.md"))

    def test_a_file_setup_created_stays_once_the_user_writes_in_it(self) -> None:
        self.edit()
        self.file.write_bytes(self.file.read_bytes() + b"mine\n")
        self.remove()
        self.assertEqual(self.file.read_bytes(), b"mine\n")

    def test_a_run_that_writes_nothing_does_not_take_the_users_edits_for_setups(self) -> None:
        self.edit()
        recorded = self.record().get("home:.claude/CLAUDE.md")["sha256"]
        self.file.write_bytes(self.file.read_bytes() + b"mine\n")
        self.edit()
        self.assertEqual(self.record().get("home:.claude/CLAUDE.md")["sha256"], recorded)
        self.reversal().apply()
        self.assertEqual(self.file.read_bytes(), b"mine\n")

    def test_another_tools_block_is_not_setups(self) -> None:
        other = b"<!-- multiagent-collab:start -->\ntheirs\n<!-- multiagent-collab:end -->\n"
        self.round_trip(other, other + b"\n" + BLOCK)

    def test_a_sentence_that_mentions_the_marker_is_not_a_marker(self) -> None:
        prose = b"The block starts at <!-- workflow-setup:start --> in this file.\n"
        self.round_trip(prose, prose + b"\n" + BLOCK)

    def test_removing_what_is_not_there_does_nothing(self) -> None:
        self.put(self.file, b"mine\n")
        before = self.snap()
        self.assertFalse(self.remove().changed)
        self.assertFalse(self.remove(path=self.home / "none.md").changed)
        self.assertEqual(self.snap(), before)

    def test_every_setup_file_is_utf8_with_lf(self) -> None:
        self.edit("café\n")
        self.assertEqual(self.file.read_bytes(), START + "\ncafé\n".encode("utf-8") + END + b"\n")


class MarkerErrorTests(BlockCase):
    FAULTS = {
        "start without end": (b"a\n" + START + b"\nx\n", "line 2: workflow-setup:start without a workflow-setup:end"),
        "end without start": (b"a\n" + END + b"\n", "line 2: workflow-setup:end without a workflow-setup:start before it"),
        "nested": (START + b"\n" + START + b"\n" + END + b"\n" + END + b"\n", "line 2: workflow-setup:start inside the block opened on line 1"),
        "doubled": (BLOCK + BLOCK, "line 4: workflow-setup:start: a second block of that name"),
        "wrong name closes": (b"<!-- workflow-setup:start a -->\n<!-- workflow-setup:end b -->\n", "line 2: workflow-setup:end b does not close the block opened on line 1"),
        "not a name": (b"<!-- workflow-setup:start Not_A_Name -->\n<!-- workflow-setup:end Not_A_Name -->\n", "not a block name setup writes"),
        "another block's fault": (BLOCK + b"<!-- workflow-setup:start other -->\n", "line 4: workflow-setup:start other without"),
    }

    def test_each_fault_stops_an_edit_and_a_removal(self) -> None:
        for label, (content, message) in self.FAULTS.items():
            with self.subTest(label):
                self.put(self.file, content)
                for build in (
                    lambda plan: plan.edit_block(self.file, "ours\n"),
                    lambda plan: plan.remove_block(self.file),
                    lambda plan: plan.edit_block(self.file, "ours\n", name="third"),
                ):
                    plan = self.plan()
                    build(plan)
                    error = self.refused(plan)
                    self.assertEqual(error.codes(), {fileops.MARKERS})
                    self.assertIn(message, error.lines[0])
                    self.assertTrue(error.lines[0].startswith(str(self.file)))
                self.assertEqual(self.file.read_bytes(), content)

    def test_the_hash_syntax_has_the_same_faults(self) -> None:
        config = self.put(self.home / ".codex" / "config.toml", b"# workflow-setup:start\nx = 1\n")
        plan = self.plan()
        plan.edit_block(config, "y = 2\n")
        self.assertEqual(self.refused(plan).codes(), {fileops.MARKERS})

    def test_a_block_cannot_hold_a_marker_or_a_bad_name(self) -> None:
        for build in (
            lambda plan: plan.edit_block(self.file, "x\n<!-- workflow-setup:end -->\n"),
            lambda plan: plan.edit_block(self.file, "x\n", name="Bad Name"),
            lambda plan: plan.edit_block(self.file, "x\r\n"),
            lambda plan: plan.edit_block(self.file, "x\n", place="middle"),
            lambda plan: plan.edit_block(self.home / "notes.txt", "x\n"),
        ):
            plan = self.plan()
            build(plan)
            self.assertEqual(self.refused(plan).codes(), {fileops.BAD_ACTION})

    def test_a_file_that_is_not_utf8_is_refused(self) -> None:
        self.put(self.file, b"caf\xe9\n")
        plan = self.plan()
        plan.edit_block(self.file, "ours\n")
        self.assertEqual(self.refused(plan).codes(), {fileops.NOT_TEXT})


class TomlBlockTests(BlockCase):
    def setUp(self) -> None:
        super().setUp()
        self.config = self.home / ".codex" / "config.toml"

    def test_a_block_at_the_head_holds_top_level_keys(self) -> None:
        original = b'model = "x"\n\n[agents]\nmax = 2\n'
        self.put(self.config, original)
        self.edit('model_reasoning_effort = "high"\n', path=self.config, name="project-default", place=fileops.HEAD)
        self.assertEqual(
            self.config.read_bytes(),
            b'# workflow-setup:start project-default\nmodel_reasoning_effort = "high"\n'
            b"# workflow-setup:end project-default\n\n" + original,
        )
        self.remove(path=self.config, name="project-default")
        self.assertEqual(self.config.read_bytes(), original)

    def test_a_file_that_does_not_parse_is_never_written(self) -> None:
        self.put(self.config, b"model = \n")
        plan = self.plan()
        plan.edit_block(self.config, "x = 1\n")
        error = self.refused(plan)
        self.assertEqual(error.codes(), {fileops.PARSE})
        self.assertIn("is not valid TOML", error.lines[0])

    def test_a_block_that_would_break_the_file_is_refused(self) -> None:
        self.put(self.config, b'model = "x"\n\n[agents]\nmax = 2\n')
        for content, place in (('model = "y"\n', fileops.HEAD), ("[agents]\nmax = 8\n", fileops.END)):
            plan = self.plan()
            plan.edit_block(self.config, content, place=place)
            error = self.refused(plan)
            self.assertEqual(error.codes(), {fileops.PARSE})
            self.assertIn("would not be valid TOML with setup's block", error.lines[0])


class LineTests(BlockCase):
    LINES = ["@rules/prd-implementation.md", "@rules/epic-implementation.md"]

    def take(self, lines: list[str] | None = None) -> fileops.Result:
        plan = self.plan()
        plan.remove_lines(self.file, self.LINES if lines is None else lines)
        return plan.apply()

    def test_exact_lines_go_and_are_recorded_with_their_places(self) -> None:
        original = b"# Mine\n@rules/prd-implementation.md\nkeep\n@rules/epic-implementation.md"
        self.put(self.file, original)
        result = self.take()
        self.assertEqual(self.file.read_bytes(), b"# Mine\nkeep\n")
        self.assertIn("    line 2: remove: @rules/prd-implementation.md", result.lines)
        self.assertIn("    line 4: remove: @rules/epic-implementation.md", result.lines)
        self.assertEqual(result.notes, [])
        self.assertEqual(
            self.record().get("home:.claude/CLAUDE.md")["removed_lines"],
            [[
                {"index": 1, "text": "@rules/prd-implementation.md", "eol": "\n"},
                {"index": 3, "text": "@rules/epic-implementation.md", "eol": ""},
            ]],
        )
        self.assertFalse(self.take().changed)
        self.reversal().apply()
        self.assertEqual(self.file.read_bytes(), original)

    def test_only_a_whole_exact_line_matches(self) -> None:
        original = (
            b" @rules/prd-implementation.md\n@rules/prd-implementation.md \n"
            b"see @rules/prd-implementation.md\n@Rules/prd-implementation.md\n"
        )
        self.put(self.file, original)
        before = self.snap()
        result = self.take()
        self.assertFalse(result.changed)
        self.assertEqual(result.notes, [f"home:.claude/CLAUDE.md: line not found: {line}" for line in self.LINES])
        self.assertEqual(self.snap(), before)

    def test_what_was_found_and_what_was_not(self) -> None:
        self.put(self.file, b"a\r\n@rules/epic-implementation.md\r\nb\r\n")
        result = self.take()
        self.assertEqual(self.file.read_bytes(), b"a\r\nb\r\n")
        self.assertEqual(result.notes, ["home:.claude/CLAUDE.md: line not found: @rules/prd-implementation.md"])
        self.assertEqual(self.record().get("home:.claude/CLAUDE.md")["removed_lines"][0][0]["eol"], "\r\n")

    def test_a_line_written_twice_goes_twice(self) -> None:
        self.put(self.file, b"@rules/prd-implementation.md\nx\n@rules/prd-implementation.md\n")
        self.take(["@rules/prd-implementation.md"])
        self.assertEqual(self.file.read_bytes(), b"x\n")
        self.assertEqual(blocks.restore_lines(b"x\n", self.record().get("home:.claude/CLAUDE.md")["removed_lines"][0]),
                         b"@rules/prd-implementation.md\nx\n@rules/prd-implementation.md\n")

    def test_lines_and_a_block_in_one_run_are_one_write_and_undo_exactly(self) -> None:
        original = b"\xef\xbb\xbf# Mine\r\n@rules/prd-implementation.md\r\n@rules/epic-implementation.md\r\nkeep"
        self.put(self.file, original)
        plan = self.plan()
        plan.remove_lines(self.file, self.LINES)
        plan.edit_block(self.file, "pointer\n")
        result = plan.apply()
        self.assertEqual(len([line for line in result.lines if "CLAUDE.md" in line]), 1)
        self.assertEqual(len(self.record().backups), 1)
        self.assertEqual(
            self.file.read_bytes(),
            b"\xef\xbb\xbf# Mine\r\nkeep\r\n" + START + b"\r\npointer\r\n" + END + b"\r\n",
        )
        self.reversal().apply()
        self.assertEqual(self.file.read_bytes(), original)

    def test_undo_after_the_user_edited_puts_the_lines_back_in_place(self) -> None:
        self.put(self.file, b"# Mine\n@rules/prd-implementation.md\n@rules/epic-implementation.md\nkeep\n")
        plan = self.plan()
        plan.remove_lines(self.file, self.LINES)
        plan.edit_block(self.file, "pointer\n")
        plan.apply()
        self.file.write_bytes(self.file.read_bytes() + b"added by the user\n")
        result = self.reversal().apply()
        self.assertEqual(
            self.file.read_bytes(),
            b"# Mine\n@rules/prd-implementation.md\n@rules/epic-implementation.md\nkeep\nadded by the user\n",
        )
        self.assertIn("home:.claude/CLAUDE.md: changed since setup edited it; setup's part was taken out and the rest left", result.notes)

    def test_a_line_to_remove_is_one_line(self) -> None:
        self.put(self.file, b"a\n")
        for lines in ([""], ["a\nb"], ["a\r"]):
            plan = self.plan()
            plan.remove_lines(self.file, lines)
            self.assertEqual(self.refused(plan).codes(), {fileops.BAD_ACTION})


class JsonTests(OpsCase):
    ORIGINAL = b'{\n    "permissions": {"allow": ["a",   "b"]},\n    "theme": "dark",\n    "n": 1.50\n}'

    def setUp(self) -> None:
        super().setUp()
        self.file = self.project / ".claude" / "settings.json"
        self.key = "project:.claude/settings.json"

    def edit(self, **changes) -> fileops.Result:
        plan = self.plan()
        plan.edit_json(self.file, **changes)
        return plan.apply()

    def test_a_key_is_added_and_every_other_byte_stays(self) -> None:
        self.put(self.file, self.ORIGINAL)
        result = self.edit(set={"agent": "manager"})
        self.assertIn("    key agent: set", result.lines)
        self.assertEqual(
            self.file.read_bytes(),
            b'{\n    "permissions": {"allow": ["a",   "b"]},\n    "theme": "dark",\n    "n": 1.50,\n    "agent": "manager"\n}',
        )
        self.assertEqual(list(json.loads(self.file.read_bytes())), ["permissions", "theme", "n", "agent"])
        self.assertEqual(self.record().get(self.key)["keys"], {"agent": {"value": "manager", "had": False}})
        after = self.snap()
        self.assertFalse(self.edit(set={"agent": "manager"}).changed)
        self.assertEqual(self.snap(), after)

    def test_a_key_is_changed_in_place(self) -> None:
        self.put(self.file, self.ORIGINAL)
        self.edit(set={"agent": "manager"})
        self.edit(set={"agent": "coder"})
        self.assertEqual(self.file.read_bytes(), self.ORIGINAL[:-2] + b',\n    "agent": "coder"\n}')
        self.assertEqual(self.record().get(self.key)["keys"]["agent"], {"value": "coder", "had": False})

    def test_a_key_is_removed_and_the_bytes_are_the_original_ones(self) -> None:
        self.put(self.file, self.ORIGINAL)
        self.edit(set={"agent": "manager"})
        result = self.edit(remove=["agent"])
        self.assertIn("    key agent: remove", result.lines)
        self.assertEqual(self.file.read_bytes(), self.ORIGINAL)
        self.assertIsNone(self.record().get(self.key))

    def test_a_users_value_is_kept_in_the_record_and_put_back(self) -> None:
        original = b'{"agent": "mine", "theme": "dark"}\r\n'
        self.put(self.file, original)
        self.edit(set={"agent": "manager"})
        self.assertEqual(self.file.read_bytes(), b'{"agent": "manager", "theme": "dark"}\r\n')
        known = self.record().get(self.key)["keys"]["agent"]
        # The record says which backup holds the file as it was with the user's value.
        backup = known.pop("replaced")["backup"]
        self.assertEqual(self.record().path(backup).read_bytes(), original)
        self.assertEqual(known, {"value": "manager", "had": True, "previous": "mine"})
        result = self.edit(remove=["agent"])
        self.assertIn("    key agent: restore", result.lines)
        self.assertEqual(self.file.read_bytes(), original)

    def test_a_key_the_user_set_is_not_setups_to_remove(self) -> None:
        self.put(self.file, b'{"agent": "mine"}')
        before = self.snap()
        result = self.edit(remove=["agent"])
        self.assertFalse(result.changed)
        self.assertEqual(result.notes, [f"{self.key}: key agent was not set by setup; left as it is"])
        self.assertEqual(self.snap(), before)

    def test_a_key_the_user_changed_since_is_left_and_no_longer_setups(self) -> None:
        self.put(self.file, self.ORIGINAL)
        self.edit(set={"agent": "manager"})
        self.file.write_bytes(self.file.read_bytes().replace(b'"manager"', b'"reviewer"'))
        result = self.edit(remove=["agent"])
        self.assertEqual(result.notes, [f"{self.key}: key agent was changed since setup set it; left as it is"])
        self.assertIn(b'"agent": "reviewer"', self.file.read_bytes())
        self.assertIsNone(self.record().get(self.key))

    def test_a_key_the_user_already_set_to_the_same_value_stays_the_users(self) -> None:
        self.put(self.file, b'{"agent": "manager"}')
        before = self.snap()
        self.assertFalse(self.edit(set={"agent": "manager"}).changed)
        self.assertEqual(self.snap(), before)

    def test_a_new_file_and_its_removal(self) -> None:
        self.edit(set={"agent": "manager"})
        self.assertEqual(self.file.read_bytes(), b'{\n  "agent": "manager"\n}\n')
        self.assertTrue(self.record().get(self.key)["created"])
        self.edit(remove=["agent"])
        self.assertFalse(self.file.exists())

    def test_a_file_setup_created_stays_once_the_user_adds_a_key(self) -> None:
        self.edit(set={"agent": "manager"})
        self.file.write_bytes(b'{\n  "agent": "manager",\n  "theme": "dark"\n}\n')
        self.edit(remove=["agent"])
        self.assertEqual(self.file.read_bytes(), b'{\n  "theme": "dark"\n}\n')

    def test_odd_layouts_keep_their_bytes(self) -> None:
        for original, expected in (
            (b"{}", b'{\n  "agent": "manager"\n}'),
            (b'{"a":1}', b'{"a":1, "agent": "manager"}'),
            (b'\xef\xbb\xbf{\r\n\t"a": [1,\r\n\t\t2],\r\n\t"b": "}\\"{"\r\n}\r\n',
             b'\xef\xbb\xbf{\r\n\t"a": [1,\r\n\t\t2],\r\n\t"b": "}\\"{",\r\n\t"agent": "manager"\r\n}\r\n'),
            (b'  {  "x" : { "agent" : 1 } ,"y":null  }  ', b'  {  "x" : { "agent" : 1 } ,"y":null, "agent": "manager"  }  '),
        ):
            with self.subTest(original):
                self.put(self.file, original)
                self.edit(set={"agent": "manager"})
                self.assertEqual(self.file.read_bytes(), expected)
                self.edit(remove=["agent"])
                self.assertEqual(self.file.read_bytes(), original)

    def test_a_key_in_the_middle_is_removed_cleanly(self) -> None:
        text = '{\n  "a": 1,\n  "agent": "manager",\n  "b": 2\n}\n'
        self.assertEqual(jsonkeys.remove_key(text, "agent"), '{\n  "a": 1,\n  "b": 2\n}\n')
        self.assertEqual(jsonkeys.remove_key(text, "a"), '{\n  "agent": "manager",\n  "b": 2\n}\n')
        self.assertEqual(jsonkeys.remove_key(text, "b"), '{\n  "a": 1,\n  "agent": "manager"\n}\n')
        self.assertEqual(jsonkeys.remove_key(text, "none"), text)

    def test_a_value_that_is_a_table_is_laid_out_like_the_file(self) -> None:
        text = jsonkeys.set_key('{\n    "a": 1\n}\n', "agent", {"name": "m", "tools": ["x"]})
        self.assertEqual(json.loads(text), {"a": 1, "agent": {"name": "m", "tools": ["x"]}})
        self.assertIn('\n    "agent": {\n      "name": "m",', text)

    def test_a_file_that_does_not_parse_is_refused_and_never_overwritten(self) -> None:
        for bad, message in (
            (b'{"a": 1,}', "is not valid JSON"),
            (b'{"a": 1} // note', "is not valid JSON"),
            (b"[1, 2]", "is not a JSON object at the top level"),
            (b'{"agent": "a", "agent": "b"}', 'holds the key "agent" twice'),
            (b'{"a": "caf\xe9"}', "is not UTF-8 text"),
            (b"", "is not valid JSON"),
        ):
            with self.subTest(bad):
                self.put(self.file, bad)
                for changes in ({"set": {"agent": "manager"}}, {"remove": ["agent"]}):
                    plan = self.plan()
                    plan.edit_json(self.file, **changes)
                    error = self.refused(plan)
                    self.assertEqual(error.codes(), {fileops.PARSE})
                    self.assertIn(message, error.lines[0])
                self.assertEqual(self.file.read_bytes(), bad)

    def test_a_key_that_is_not_listed_is_refused(self) -> None:
        self.put(self.file, self.ORIGINAL)
        for changes in ({"set": {"theme": "light"}}, {"remove": ["theme"]}, {"set": {"agent": "m", "model": "x"}}):
            plan = self.plan()
            plan.edit_json(self.file, **changes)
            error = self.refused(plan)
            self.assertEqual(error.codes(), {fileops.KEY})
            self.assertIn("manifest-keys.json", error.lines[0])

    def test_a_file_that_is_not_listed_is_refused(self) -> None:
        for path in (self.home / ".claude" / "settings.json", self.project / ".claude" / "settings.local.json"):
            self.put(path, b"{}")
            plan = self.plan()
            plan.edit_json(path, set={"agent": "manager"})
            self.assertEqual(self.refused(plan).codes(), {fileops.KEY})

    def test_the_shipped_list_names_the_one_key(self) -> None:
        self.assertEqual(jsonkeys.load_key_list(), {"project:.claude/settings.json": ("agent",)})

    def test_a_plan_can_be_given_another_list(self) -> None:
        path = self.put(self.home / ".claude" / "settings.json", b"{}")
        plan = self.plan(key_list={"home:.claude/settings.json": ("x",)})
        plan.edit_json(path, set={"x": True})
        plan.apply()
        self.assertEqual(path.read_bytes(), b'{\n  "x": true\n}')

    def test_a_key_list_that_is_not_one_is_refused(self) -> None:
        for bad in ("{", "[]", '{"schema_version": 2, "files": {}}', '{"schema_version": 1, "files": {"k": {"path": 1}}}'):
            file = self.put(self.root / "keys.json", bad)
            with self.assertRaises(SetupError):
                jsonkeys.load_key_list(file)

    def test_true_is_not_one(self) -> None:
        self.assertFalse(jsonkeys.same(True, 1))
        self.assertTrue(jsonkeys.same({"a": [1, "x"]}, {"a": [1, "x"]}))

    def test_undo_restores_the_exact_bytes(self) -> None:
        self.put(self.file, self.ORIGINAL)
        self.edit(set={"agent": "manager"})
        self.reversal(project=True).apply()
        self.assertEqual(self.file.read_bytes(), self.ORIGINAL)


class IgnoreTests(OpsCase):
    ALWAYS = b".agents/workflow-setup/\n.agents/workflow.local.toml\n.wfsetup-*.tmp\n"

    def setUp(self) -> None:
        super().setUp()
        self.file = self.project / ".gitignore"

    def ignore(self, **changes) -> fileops.Result:
        plan = self.plan()
        plan.ignore(**changes)
        return plan.apply()

    def block(self, body: bytes) -> bytes:
        return b"# workflow-setup:start\n" + body + b"# workflow-setup:end\n"

    def listed(self, *more: str, less: tuple[str, ...] = ()) -> bytes:
        """The block that holds the fixed entries and ``more``, sorted."""
        entries = sorted((set(fileops.IGNORE_ALWAYS) | set(more)) - set(less))
        return self.block("".join(f"{entry}\n" for entry in entries).encode("utf-8"))

    def test_the_fixed_entries(self) -> None:
        self.assertEqual(
            fileops.IGNORE_ALWAYS,
            (".agents/workflow.local.toml", ".agents/workflow-setup/", ".wfsetup-*.tmp"),
        )
        self.assertTrue(fsio.is_temporary(".wfsetup-0123abcd.tmp"))
        for name in (".wfsetup-.tmp", ".wfsetup-0123abcd.tmp.md", "x.wfsetup-0123abcd.tmp", ".wfsetup-0123ABCZ.tmp"):
            self.assertFalse(fsio.is_temporary(name), name)

    def test_the_block_always_lists_the_local_settings_and_the_record(self) -> None:
        self.ignore()
        self.assertEqual(self.file.read_bytes(), self.block(self.ALWAYS))
        self.assertFalse(self.ignore().changed)

    def test_entries_are_added_sorted_and_once(self) -> None:
        self.put(self.file, b"node_modules\n")
        self.ignore(add=[".codex/agents/manager.toml", ".claude/agents/manager.md", ".claude/agents/manager.md"])
        self.assertEqual(
            self.file.read_bytes(),
            b"node_modules\n\n" + self.listed(".claude/agents/manager.md", ".codex/agents/manager.toml"),
        )

    def test_one_caller_does_not_drop_what_another_added(self) -> None:
        self.ignore(add=[".claude/agents/manager.md"])
        self.ignore()
        self.ignore(add=[".codex/agents/manager.toml"])
        self.assertEqual(
            self.file.read_bytes(),
            self.listed(".claude/agents/manager.md", ".codex/agents/manager.toml"),
        )
        self.ignore(remove=[".claude/agents/manager.md", ".agents/workflow.local.toml"])
        self.assertEqual(self.file.read_bytes(), self.listed(".codex/agents/manager.toml"))

    def test_a_line_the_user_has_is_not_written_again(self) -> None:
        self.put(self.file, b".agents/workflow.local.toml\n.claude/agents/manager.md  \n")
        self.ignore(add=[".claude/agents/manager.md", ".codex/x"])
        self.assertEqual(
            self.file.read_bytes(),
            b".agents/workflow.local.toml\n.claude/agents/manager.md  \n\n"
            + self.listed(".codex/x", less=(".agents/workflow.local.toml",)),
        )

    def test_there_is_only_ever_one_block(self) -> None:
        self.put(self.file, b"a\r\n")
        for add in ([".claude/agents/x.md"], [".claude/agents/y.md"], []):
            self.ignore(add=add)
        self.assertEqual(self.file.read_bytes().count(b"workflow-setup:start"), 1)
        self.assertEqual(
            self.file.read_bytes(),
            b"a\r\n\r\n" + self.listed(".claude/agents/x.md", ".claude/agents/y.md").replace(b"\n", b"\r\n"),
        )

    def test_undo_takes_the_block_out_and_a_created_file_away(self) -> None:
        self.ignore(add=["x"])
        self.reversal(project=True).apply()
        self.assertFalse(self.file.exists())
        self.put(self.file, b"mine")
        self.ignore(add=["x"])
        self.reversal(project=True).apply()
        self.assertEqual(self.file.read_bytes(), b"mine")

    def test_what_is_not_an_entry_is_refused(self) -> None:
        for entry in ("", " x", "a\nb", "# comment", "!negated"):
            plan = self.plan()
            plan.ignore(add=[entry])
            self.assertEqual(self.refused(plan).codes(), {fileops.BAD_ACTION})

    def test_without_a_project_there_is_no_ignore_block(self) -> None:
        plan = fileops.Plan(fileops.Roots(self.home, None, self.clone))
        plan.ignore()
        with self.assertRaises(fileops.PlanError):
            plan.describe()


class PureBlockTests(unittest.TestCase):
    def test_put_then_drop_is_the_identity(self) -> None:
        bodies = [b"", b"a", b"a\n", b"a\n\n", b"\n", b"\n\na", b"a\r\nb", b"a\r\nb\r\n", b"\r\n", b"a\rb\n"]
        for body in bodies:
            for bom in (b"", BOM):
                for syntax in blocks.SYNTAXES:
                    for place in (blocks.END, blocks.HEAD):
                        for name in ("", "n-1"):
                            data = bom + body
                            with self.subTest(data=data, syntax=syntax, place=place, name=name):
                                added = blocks.put(data, syntax, name, "one\ntwo\n", place)
                                self.assertNotEqual(added, data)
                                self.assertEqual(blocks.put(added, syntax, name, "one\ntwo\n", place), added)
                                self.assertEqual(blocks.content_of(added, syntax, name), ["one", "two"])
                                self.assertEqual(blocks.drop(added, syntax, name), data)
                                self.assertTrue(added.startswith(bom))

    def test_a_new_file_gets_lf(self) -> None:
        self.assertEqual(blocks.put(None, blocks.GITIGNORE, "", "x"), b"# workflow-setup:start\nx\n# workflow-setup:end\n")

    def test_the_line_ending_is_the_files_majority(self) -> None:
        self.assertEqual(blocks.eol_of(b"a\r\nb\r\nc\n"), b"\r\n")
        self.assertEqual(blocks.eol_of(b"a\r\nb\nc\n"), b"\n")
        self.assertEqual(blocks.eol_of(b""), b"\n")

    def test_remove_then_restore_lines_is_the_identity(self) -> None:
        for data in (b"x\na\nx\nb\nx", b"x\r\na\r\nx\r\n", b"x", BOM + b"a\nx\n"):
            with self.subTest(data):
                new, removed, missing = blocks.remove_lines(data, ["x", "zz"])
                self.assertNotIn(b"x", new)
                self.assertEqual(missing, ["zz"])
                self.assertEqual(blocks.restore_lines(new, removed), data)

    def test_the_syntax_is_told_by_the_name(self) -> None:
        self.assertEqual(blocks.syntax_for("CLAUDE.md"), blocks.MARKDOWN)
        self.assertEqual(blocks.syntax_for("AGENTS.MD"), blocks.MARKDOWN)
        self.assertEqual(blocks.syntax_for(".gitignore"), blocks.GITIGNORE)
        self.assertEqual(blocks.syntax_for("config.toml"), blocks.TOML)
        self.assertIsNone(blocks.syntax_for("settings.json"))


if __name__ == "__main__":
    unittest.main()
