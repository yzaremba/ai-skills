"""Tests of the STATE size limits of scripts/check.py.

Run from the repository root:

    python -B -m unittest discover -s prd-implementation/tests
"""
import unittest

import check
from test_check import Case

STATE = "SPRINT01-STATE-sample.md"
CUT = "cut it to the present: what happened is in git log"


def state(lines: int, characters: int) -> str:
    """A file of exactly ``lines`` lines and ``characters`` characters,
    each line counted with its line break."""
    body = ["x"] * lines
    spare = characters - 2 * lines
    assert spare >= 0
    body[0] += "y" * spare
    text = "\n".join(body) + "\n"
    assert len(text) == characters, (len(text), characters)
    return text


class StateLimits(Case):
    def found(self, text, name=STATE):
        self.write(name, text)
        return [(line, rule) for file, line, rule in self.rules() if file == name]

    def test_exactly_at_the_limits_is_clean(self):
        self.assertEqual(self.found(state(70, 8000)), [])
        self.assertEqual(self.found(state(1, 8000)), [])
        self.assertEqual(self.found(state(70, 140)), [])

    def test_one_line_over(self):
        self.assertEqual(self.found(state(71, 8000)), [(71, "state-too-many-lines")])

    def test_one_character_over(self):
        self.assertEqual(self.found(state(70, 8001)), [(None, "state-too-long")])

    def test_both_over(self):
        self.assertEqual(self.found(state(71, 8001)),
                         [(None, "state-too-long"), (71, "state-too-many-lines")])

    def test_characters_are_code_points_and_crlf_is_not_counted(self):
        text = "é" * 7997 + "\n"
        self.assertEqual(self.found(text + "\U0001d4b3\n"), [])
        self.assertEqual(self.found(text + "\U0001d4b3x\n"), [(None, "state-too-long")])
        self.assertEqual(self.found(state(70, 8000).replace("\n", "\r\n")), [])

    def test_fenced_lines_count(self):
        self.assertEqual(self.found("```\n" + "x\n" * 69 + "```\n"), [(71, "state-too-many-lines")])

    def test_a_state_in_done_is_not_checked(self):
        self.assertEqual(self.found(state(80, 9000), "DONE/SPRINT00-STATE-a.md"), [])

    def test_messages(self):
        self.write(STATE, state(71, 8001))
        _, report = self.run_check()
        messages = {v["rule"]: v["message"] for v in report["violations"]}
        self.assertEqual(messages["state-too-many-lines"], f"71 lines; the limit is 70; {CUT}")
        self.assertEqual(messages["state-too-long"], f"8001 characters; the limit is 8000; {CUT}")

    def test_text_output(self):
        self.write(STATE, state(71, 8001))
        code, text = check.run(self.arguments())
        self.assertEqual(code, 1)
        self.assertIn(f"{STATE}:71", text)
        self.assertIn("state-too-many-lines", text)
        self.assertIn("state-too-long", text)
        self.assertIn(f"8001 characters; the limit is 8000; {CUT}", text)


HOTFIX = "HOTFIX-STATE-sample.md"


class HotfixState(Case):
    def test_limits_apply(self):
        self.write(HOTFIX, state(70, 8000))
        self.assertEqual([r for r in self.rules() if r[0] == HOTFIX], [])
        self.write(HOTFIX, state(71, 8001))
        self.assertEqual([(line, rule) for file, line, rule in self.rules() if file == HOTFIX],
                         [(None, "state-too-long"), (71, "state-too-many-lines")])

    def test_listed_by_name(self):
        self.write("HOTFIX-STATE-b.md", state(3, 100))
        self.write("HOTFIX-STATE-a.md", state(3, 100))
        self.write("HOTFIX-NOTES-c.md", state(3, 100))
        _, report = self.run_check()
        self.assertEqual(report["hotfix_states"], ["HOTFIX-STATE-a.md", "HOTFIX-STATE-b.md"])
        _, text = check.run(self.arguments())
        self.assertIn("\nHotfix STATE files: 2\nHOTFIX-STATE-a.md\nHOTFIX-STATE-b.md\n", text)

    def test_none_present(self):
        _, report = self.run_check()
        self.assertEqual(report["hotfix_states"], [])
        _, text = check.run(self.arguments())
        self.assertNotIn("Hotfix STATE", text)

    def test_one_in_done_is_not_read(self):
        self.write("DONE/" + HOTFIX, state(80, 9000))
        _, report = self.run_check()
        self.assertEqual((report["hotfix_states"], report["violations"]), ([], []))


if __name__ == "__main__":
    unittest.main()
