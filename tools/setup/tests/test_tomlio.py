"""Tests for wfsetup.tomlio: what the emitter writes reads back unchanged.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import datetime
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the package on the path)
from wfsetup import paths, tomlio
from wfsetup.errors import SetupError

HOSTILE = [
    "",
    "plain",
    'a "quoted" word',
    "back\\slash and \\n that is not a line feed",
    "\\\\server\\share\\dir\\file",
    "ends with a backslash\\",
    '"',
    '""',
    '"""',
    '""""""',
    "'''",
    "line one\nline two",
    "\n",
    "\n\n",
    "\nstarts with a line feed",
    "ends with a line feed\n",
    'a line\nthen """ three quotes\nand more',
    'a line\nthen """" four',
    'ends with a quote after a line feed\n"',
    'ends with quotes after a line feed\n"""',
    "backslash at a line's end \\\nnext line",
    "carriage return \r\n and a lone \r one",
    "tab\there",
    "  leading and trailing spaces  ",
    "trailing spaces before a line feed   \nnext",
    "".join(chr(code) for code in range(0x20)),
    "delete \x7f and escape \x1b[0m",
    "next line \x85, line separator \u2028, paragraph separator \u2029",
    "caf\u00e9 \u4e2d\u6587 \u0440\u0443\u0441\u0441\u043a\u0438\u0439 \U0001f600",
    "zero width \u200b and a byte order mark \ufeff",
    "# not a comment",
    "[not.a.table]",
    "key = \"value\"",
    "\\u0041 stays six characters",
    "${HOME} $(command) `ticks`",
    "x" * 5000,
]


class StringRoundTripTests(unittest.TestCase):
    def test_every_hostile_string_as_a_value(self) -> None:
        for text in HOSTILE:
            with self.subTest(text=text[:40]):
                self.assertEqual(tomllib.loads(tomlio.dumps({"key": text})), {"key": text})

    def test_every_hostile_string_on_one_line(self) -> None:
        for text in HOSTILE:
            with self.subTest(text=text[:40]):
                written = tomlio.format_value(text)
                self.assertNotIn("\n", written)
                self.assertNotIn("\r", written)
                self.assertEqual(tomllib.loads(f"key = {written}"), {"key": text})

    def test_every_hostile_string_in_an_array(self) -> None:
        document = {"items": list(HOSTILE)}
        self.assertEqual(tomllib.loads(tomlio.dumps(document)), document)

    def test_every_hostile_string_as_a_key_and_a_table_name(self) -> None:
        for text in HOSTILE:
            with self.subTest(text=text[:40]):
                document = {text: "value", "table": {text: {"inner": 1}}}
                self.assertEqual(tomllib.loads(tomlio.dumps(document)), document)

    def test_all_hostile_strings_in_one_document(self) -> None:
        document = {"section": {f"k{index}": text for index, text in enumerate(HOSTILE)}}
        self.assertEqual(tomllib.loads(tomlio.dumps(document)), document)

    def test_every_pair_of_awkward_characters(self) -> None:
        awkward = ['"', "\\", "\n", "\r", "\t", "'", " ", "#", "a", "\x00", "\u00e9"]
        for first in awkward:
            for second in awkward:
                for third in awkward:
                    text = first + second + third
                    self.assertEqual(tomllib.loads(tomlio.dumps({"k": text})), {"k": text}, repr(text))

    def test_a_string_with_a_line_feed_is_written_on_several_lines(self) -> None:
        written = tomlio.dumps({"text": "first\nsecond\n"})
        self.assertEqual(written, 'text = """\nfirst\nsecond\n"""\n')

    def test_a_lone_surrogate_is_refused_and_the_key_named(self) -> None:
        with self.assertRaises(SetupError) as caught:
            tomlio.dumps({"a": {"b": "bad \ud800 text"}})
        self.assertIn("a.b", str(caught.exception))


class TypeTests(unittest.TestCase):
    def test_every_supported_type_round_trips(self) -> None:
        document = {
            "string": "text",
            "integer": 42,
            "negative": -7,
            "zero": 0,
            "large": 2**62,
            "yes": True,
            "no": False,
            "array": ["a", "b c", ""],
            "empty_array": [],
            "table": {
                "inner": "value",
                "nested": {"deep": 1, "deeper": {"flag": False, "names": ["x"]}},
            },
            "only_tables": {"one": {"a": 1}, "two": {"b": 2}},
            "empty_table": {},
            "outer": {"empty_inner": {}},
        }
        self.assertEqual(tomllib.loads(tomlio.dumps(document)), document)

    def test_exact_text(self) -> None:
        document = {
            "schema_version": 1,
            "process": {"docs_dir": "docs", "recommend": True},
            "roles": {"max_parallel_coders": 3, "coder": {"tier": "deep"}},
            "providers": {"codex": {"tiers": {"fast": "m1"}}},
            "list": {"names": ["a", "b"]},
        }
        self.assertEqual(
            tomlio.dumps(document),
            "schema_version = 1\n"
            "\n"
            "[process]\n"
            'docs_dir = "docs"\n'
            "recommend = true\n"
            "\n"
            "[roles]\n"
            "max_parallel_coders = 3\n"
            "\n"
            "[roles.coder]\n"
            'tier = "deep"\n'
            "\n"
            "[providers.codex.tiers]\n"
            'fast = "m1"\n'
            "\n"
            "[list]\n"
            'names = ["a", "b"]\n',
        )

    def test_a_boolean_is_not_written_as_an_integer(self) -> None:
        self.assertEqual(tomlio.dumps({"flag": True, "count": 1}), "flag = true\ncount = 1\n")

    def test_an_empty_document_is_empty(self) -> None:
        self.assertEqual(tomlio.dumps({}), "")

    def test_key_order_is_kept(self) -> None:
        self.assertEqual(tomlio.dumps({"b": 1, "a": 2}), "b = 1\na = 2\n")

    def test_unsupported_values_are_refused_and_the_key_named(self) -> None:
        cases = {
            "float": 1.5,
            "nothing": None,
            "date": datetime.date(2026, 1, 1),
            "array of integers": [1, 2],
            "array of arrays": [["a"]],
            "array of tables": [{"a": 1}],
        }
        for name, value in cases.items():
            with self.subTest(name):
                with self.assertRaises(SetupError) as caught:
                    tomlio.dumps({"group": {"key": value}})
                self.assertIn("group.key", str(caught.exception))

    def test_a_key_that_is_not_a_string_is_refused(self) -> None:
        with self.assertRaises(SetupError):
            tomlio.dumps({"group": {1: "value"}})

    def test_a_lone_surrogate_in_a_key_is_refused_like_one_in_a_value(self) -> None:
        with self.assertRaises(SetupError) as caught:
            tomlio.format_key("bad \ud800 key")
        self.assertEqual(caught.exception.lines, ["key: holds a character that UTF-8 cannot encode"])
        with self.assertRaises(SetupError) as caught:
            tomlio.dotted(("a", "bad \ud800 key"))
        for document, place in (
            ({"bad \ud800 key": 1}, "document: a key"),
            ({"group": {"bad \ud800 key": 1}}, "group: a key"),
            ({"group": {"bad \ud800 table": {"inner": 1}}}, "group: a key"),
        ):
            with self.subTest(place=place, document=repr(document)):
                with self.assertRaises(SetupError) as caught:
                    tomlio.dumps(document)
                self.assertEqual(caught.exception.lines, [f"{place}: holds a character that UTF-8 cannot encode"])
        # A key that only needs quoting is still written.
        self.assertEqual(tomlio.format_key("café key"), '"café key"')

    def test_an_integer_outside_the_signed_64_bit_range_is_refused(self) -> None:
        for value in (2**63 - 1, -(2**63)):
            with self.subTest(value=value):
                self.assertEqual(tomllib.loads(tomlio.dumps({"n": value})), {"n": value})
        for value in (2**63, -(2**63) - 1, 10**30, 10**5000, -(10**5000)):
            with self.subTest(digits=len(str(abs(value))) if abs(value) < 10**100 else "thousands"):
                with self.assertRaises(SetupError) as caught:
                    tomlio.dumps({"group": {"n": value}})
                self.assertEqual(
                    caught.exception.lines, ["group.n: cannot write an integer outside the signed 64-bit range"]
                )
                with self.assertRaises(SetupError):
                    tomlio.format_value(value)

    def test_the_messages_take_the_right_article(self) -> None:
        cases = {
            "an array that holds an integer": [1, 2],
            "an array that holds an array": [["a"]],
            "an array that holds a table": [{"a": 1}],
            "an array that holds a boolean": [True],
            "a float value": 1.5,
            "a date value": datetime.date(2026, 1, 1),
        }
        for expected, value in cases.items():
            with self.subTest(expected):
                with self.assertRaises(SetupError) as caught:
                    tomlio.dumps({"key": value})
                self.assertEqual(caught.exception.lines, [f"key: cannot write {expected}"])
        self.assertEqual(
            [tomlio.article(noun) for noun in ("integer", "array", "string", "table", "boolean", "float")],
            ["an integer", "an array", "a string", "a table", "a boolean", "a float"],
        )


class FileTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def test_dump_writes_utf8_with_line_feeds_only(self) -> None:
        file = self.root / "out.toml"
        document = {"a": {"text": "caf\u00e9\r\nsecond", "n": 1}, "b": {"flag": True}}
        tomlio.dump(file, document)
        raw = file.read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertIn("caf\u00e9".encode("utf-8"), raw)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(tomlio.load(file), document)

    def test_load_accepts_crlf_and_a_byte_order_mark(self) -> None:
        file = self.root / "in.toml"
        file.write_bytes(b"\xef\xbb\xbf[process]\r\ndocs_dir = \"d\"\r\n")
        self.assertEqual(tomlio.load(file), {"process": {"docs_dir": "d"}})

    def test_a_missing_file_is_absent(self) -> None:
        self.assertIsNone(tomlio.load_if_present(self.root / "none.toml"))

    def test_a_directory_in_the_files_place_is_an_error(self) -> None:
        with self.assertRaises(SetupError) as caught:
            tomlio.load_if_present(self.root)
        self.assertIn(str(self.root), str(caught.exception))

    def test_bad_toml_names_the_file(self) -> None:
        file = self.root / "bad.toml"
        file.write_bytes(b"[process\n")
        with self.assertRaises(SetupError) as caught:
            tomlio.load(file)
        self.assertIn(str(file), str(caught.exception))
        self.assertIn("not valid TOML", str(caught.exception))

    def test_a_link_with_no_target_is_not_an_absent_file(self) -> None:
        link = self.root / "link.toml"
        try:
            os.symlink(self.root / "gone.toml", link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are not permitted here: {exc}")
        self.assertTrue(os.path.lexists(link))
        with self.assertRaises(SetupError) as caught:
            tomlio.load_if_present(link)
        self.assertEqual(caught.exception.lines, [f"link target missing: {link}"])
        (self.root / "gone.toml").write_bytes(b"a = 1\n")
        self.assertEqual(tomlio.load_if_present(link), {"a": 1})

    def test_what_is_at_a_path(self) -> None:
        file = self.root / "f.toml"
        file.write_bytes(b"")
        self.assertEqual(paths.kind(file), paths.FILE)
        self.assertEqual(paths.kind(self.root), paths.DIRECTORY)
        self.assertEqual(paths.kind(self.root / "none"), paths.ABSENT)
        # Under a file there is nothing, on every system.
        self.assertEqual(paths.kind(file / "below"), paths.ABSENT)
        self.assertEqual(paths.entries(self.root / "none"), [])
        self.assertEqual(paths.entries(file), [])
        self.assertEqual(paths.entries(self.root), [file])

    def test_nesting_too_deep_and_an_integer_too_long_name_the_file(self) -> None:
        file = self.root / "deep.toml"
        for text, expected in (
            ("x = " + "[" * 5000 + "]" * 5000 + "\n", "arrays or inline tables are nested too deeply"),
            ("x = " + "1" * 5000 + "\n", "it holds an integer with too many digits"),
        ):
            with self.subTest(expected=expected):
                file.write_bytes(text.encode("utf-8"))
                with self.assertRaises(SetupError) as caught:
                    tomlio.load(file)
                self.assertEqual(caught.exception.lines, [f"{file}: is not valid TOML: {expected}"])

    def test_bytes_that_are_not_utf8_name_the_file(self) -> None:
        file = self.root / "latin.toml"
        file.write_bytes(b'x = "caf\xe9"\n')
        with self.assertRaises(SetupError) as caught:
            tomlio.load(file)
        self.assertIn(str(file), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
