"""Setup's block in a file of the user's, over many made-up files (B3, S1,
and markers in a TOML multi-line string).

The files and the user's edits are drawn from a seeded generator, so a
failure names its seed and repeats. What must hold for every one:

    - a block that is put in and taken out again leaves the file's bytes;
    - whatever the user wrote before, after and around the block in
      between, taking the block out joins no two of the user's lines,
      drops none, and changes no byte of any of them: at most one blank
      line next to the block goes;
    - taken out with what ``blocks.joint`` said when it was put in, no line
      of the user's loses its own line ending either: the one ending that
      may go from a line of text is the one setup gave a last line that
      had none, and only while that line is still the last;
    - putting a block in, or changing it, changes no byte outside it;
    - a block that the record does not hold is never written over unless
      it holds exactly what setup writes.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import os
import random
import tomllib
import unittest

from fileops_support import OpsCase
from wfsetup import blocks, fileops, fsio

SEEDS = 400
WORDS = ["node_modules/", "*.log", "# Mine", "dist/", "x = 1", "- item", "  indented", "tab\there", "é中", "a\rb", "\r", " "]
ENDINGS = [b"\n", b"\r\n"]


def a_line(rng: random.Random) -> bytes:
    """One line of a user's file without its ending; a lone CR is text."""
    if rng.random() < 0.2:
        return b""
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 3))).encode("utf-8")


def a_file(rng: random.Random, toml: bool = False) -> bytes:
    """A file of the user's: LF or CRLF or both, with or without a byte
    order mark, with or without a last line ending, maybe empty."""
    main = rng.choice(ENDINGS)
    lines = []
    for _ in range(rng.randint(0, 6)):
        text = f"k{rng.randint(0, 99)} = {rng.randint(0, 9)}".encode() if toml else a_line(rng)
        if toml and rng.random() < 0.3:
            text = rng.choice([b"", b"# a comment", b"[table]"])
        ending = main if rng.random() < 0.85 else rng.choice(ENDINGS)
        lines.append(text + ending)
    body = b"".join(lines)
    if lines and rng.random() < 0.35:
        body = body[:-len(blocks._ending(body))] or body  # no last line ending
        if toml and not body.strip():
            body = b""
    if toml:
        # ``[table]`` twice is not TOML; keep the first.
        seen, kept = False, []
        for line in blocks._lines(body):
            if blocks._bare(line) == b"[table]":
                if seen:
                    continue
                seen = True
            kept.append(line)
        # Keys after the table must not repeat inside it; and none twice at all.
        names: set[bytes] = set()
        body = b""
        for line in kept:
            name = blocks._bare(line).split(b" = ")[0]
            if b" = " in line and name in names:
                continue
            names.add(name)
            body += line
    bom = blocks.BOM if rng.random() < 0.15 else b""
    return bom + body


def user_lines(data: bytes, syntax: str) -> list[bytes]:
    """The user's lines: those in no block, without their endings."""
    return [line.encode("utf-8") for line in blocks.outside(data, syntax)]


def edited(rng: random.Random, data: bytes, syntax: str, name: str) -> bytes:
    """``data``, which holds the block ``name``, after the user wrote
    before it, after it or around it, or removed lines of their own."""
    bom, body = blocks.split_bom(data)
    first, after = blocks.scan(body, syntax)[name]
    lines = blocks._lines(body)
    head, block, tail = lines[:first], lines[first:after], lines[after:]
    ending = rng.choice(ENDINGS)
    for _ in range(rng.randint(1, 3)):
        what = rng.randint(0, 7)
        new = (b"user" + str(rng.randint(0, 99)).encode()) if syntax != blocks.TOML else f"u{rng.randint(0, 9999)} = 1".encode()
        if what == 0:
            head.insert(rng.randint(0, len(head)), new + ending)
        elif what == 1:
            if head and not blocks._ending(head[-1]):
                head[-1] += ending
            head.append(new + ending)  # right before the block
        elif what == 2:
            tail.insert(0, new + ending)  # right after the block
        elif what == 3:
            if tail and not blocks._ending(tail[-1]):
                tail[-1] += ending
            tail.append(new + (ending if rng.random() < 0.6 else b""))  # at the end, maybe with no line ending
        elif what == 4 and tail:
            tail.insert(rng.randint(0, len(tail)), new + ending)
        elif what == 5 and head:
            del head[rng.randrange(len(head))]
            if not head or blocks._ending(head[-1]):
                continue
            head[-1] += ending  # the block still starts on a line of its own
        elif what == 6 and tail:
            del tail[rng.randrange(len(tail))]
        elif what == 7 and syntax != blocks.TOML:
            tail.insert(0, ending)  # a blank line after the block
    if tail and len(tail) > 1:
        # Every line but the last has an ending.
        tail = [line if blocks._ending(line) or index == len(tail) - 1 else line + ending for index, line in enumerate(tail)]
    return bom + b"".join([*head, *block, *tail])


def around(data: bytes, syntax: str, name: str) -> tuple[list[bytes], list[bytes]]:
    """The lines before and after the block ``name``, with their endings."""
    _, body = blocks.split_bom(data)
    first, after = blocks.scan(body, syntax)[name]
    lines = blocks._lines(body)
    return lines[:first], lines[after:]


def check_endings(case: unittest.TestCase, now: bytes, out: bytes, syntax: str, name: str, how: dict) -> bool:
    """``out`` is ``now`` without the block ``name``, which was put in
    with the joint ``how``: every line of text of the user's is there, in
    order, with the line ending it had in ``now``. One line may have lost
    its ending: the last one before the block, where nothing follows the
    block and it is the line that had no ending when the block was added
    (that ending was setup's). Returns whether it did."""
    head, tail = around(now, syntax, name)
    mine = [line for line in [*head, *tail] if blocks._bare(line)]
    left = [line for line in blocks._lines(blocks.split_bom(out)[1]) if blocks._bare(line)]
    case.assertEqual([blocks._bare(line) for line in left], [blocks._bare(line) for line in mine], (now, out))
    setups = None
    if head and not tail and how.get("where") == "before" and not how.get("blank"):
        if how.get("line") == fsio.sha256(blocks._bare(head[-1])):
            setups = len(mine) - 1
    gone = False
    for index, (after, before) in enumerate(zip(left, mine)):
        if blocks._ending(after) == blocks._ending(before):
            continue
        case.assertEqual(index, setups, (now, out, how))
        case.assertEqual(blocks._ending(after), b"", (now, out, how))
        gone = True
    return gone


class PureBlockProperties(unittest.TestCase):
    SYNTAXES = (blocks.MARKDOWN, blocks.GITIGNORE)

    def test_put_then_drop_is_the_identity(self) -> None:
        for seed in range(SEEDS):
            rng = random.Random(seed)
            syntax, name = rng.choice(self.SYNTAXES), rng.choice(["", "n1"])
            data, place = a_file(rng), rng.choice([blocks.END, blocks.HEAD])
            with self.subTest(seed=seed):
                with_block = blocks.put(data, syntax, name, "ours\nmore\n", place)
                self.assertEqual(blocks.drop(with_block, syntax, name), data)
                # And the same with what the record keeps of how it was joined.
                how = blocks.joint(data, syntax, name, place)
                self.assertEqual(blocks.drop(with_block, syntax, name, joint=how), data)
                # Every byte of the user's is where it was.
                bom, body = blocks.split_bom(data)
                self.assertTrue(with_block.startswith(bom))
                self.assertIn(body, with_block)
                self.assertEqual(user_lines(with_block, syntax)[:len(user_lines(data, syntax))] if place == blocks.END else
                                 user_lines(with_block, syntax)[-len(user_lines(data, syntax)) or len(with_block):],
                                 user_lines(data, syntax))
                # Changing the block changes nothing else.
                changed = blocks.put(with_block, syntax, name, "other\n", place)
                self.assertEqual(blocks.drop(changed, syntax, name), data)
                self.assertEqual(blocks.drop(changed, syntax, name, joint=how), data)

    def test_removal_never_joins_two_lines_of_the_users(self) -> None:
        joined = 0
        for seed in range(SEEDS * 3):
            rng = random.Random(seed)
            syntax, name = rng.choice(self.SYNTAXES), rng.choice(["", "n1"])
            data, place = a_file(rng), rng.choice([blocks.END, blocks.HEAD])
            with_block = blocks.put(data, syntax, name, "ours\n", place)
            now = edited(rng, with_block, syntax, name)
            with self.subTest(seed=seed):
                mine = user_lines(now, syntax)
                out = blocks.drop(now, syntax, name)
                self.assertIsNotNone(out)
                self.assertIsNone(blocks.get(out, syntax, name))
                left = user_lines(out, syntax)
                # The same lines of text, in the same order, each whole.
                self.assertEqual([line for line in left if line], [line for line in mine if line], (now, out))
                # And at most one blank line fewer.
                self.assertIn(len(mine) - len(left), (0, 1), (now, out))
                self.assertEqual(blocks.split_bom(now)[0], blocks.split_bom(out)[0])
                # What the old rule did to the same file: for the count below.
                bom, body = blocks.split_bom(now)
                first, after = blocks.scan(body, syntax)[name]
                lines = blocks._lines(body)
                before, tail = b"".join(lines[:first]), b"".join(lines[after:])
                if before and tail and not tail.startswith((b"\n", b"\r\n")):
                    shorter = before[:len(before) - len(blocks._ending(before))]
                    joined += bool(shorter) and not blocks._ending(shorter)
        # The generator does make the files in which lines were joined.
        self.assertGreater(joined, 50)

    def test_removal_never_takes_a_line_ending_of_the_users(self) -> None:
        """With the joint the record keeps: the user wrote around the
        block, and no line of theirs loses its ending, the last one of the
        file included."""
        stripped = restored = 0
        for seed in range(SEEDS * 3):
            rng = random.Random(seed)
            syntax, name = rng.choice(self.SYNTAXES), rng.choice(["", "n1"])
            data, place = a_file(rng), rng.choice([blocks.END, blocks.HEAD])
            how = blocks.joint(data, syntax, name, place)
            with_block = blocks.put(data, syntax, name, "ours\n", place)
            now = edited(rng, with_block, syntax, name)
            with self.subTest(seed=seed):
                mine = user_lines(now, syntax)
                out = blocks.drop(now, syntax, name, joint=how)
                self.assertIsNotNone(out)
                self.assertIsNone(blocks.get(out, syntax, name))
                left = user_lines(out, syntax)
                # No two lines joined, none dropped, at most one blank line fewer.
                self.assertEqual([line for line in left if line], [line for line in mine if line], (now, out))
                self.assertIn(len(mine) - len(left), (0, 1), (now, out))
                self.assertEqual(blocks.split_bom(now)[0], blocks.split_bom(out)[0])
                # Every line of text has the ending it had.
                restored += check_endings(self, now, out, syntax, name, how)
                # What the rule without a joint does to the same file: it
                # takes the ending before a block that is last, whose ever.
                head, tail = around(now, syntax, name)
                if head and not tail and blocks._bare(head[-1]) and blocks._ending(head[-1]):
                    theirs = how.get("line") != fsio.sha256(blocks._bare(head[-1]))
                    plain = blocks.drop(now, syntax, name)
                    if theirs and not blocks._ending(plain):
                        stripped += 1
                        self.assertTrue(blocks._ending(out), (now, out))
                        self.assertEqual(out, plain + blocks._ending(head[-1]), (now, out))
        # The generator does make both kinds of file: one whose last line
        # is the user's with its own ending, and one whose last line got
        # its ending from setup and gives it back.
        self.assertGreater(stripped, 50)
        self.assertGreater(restored, 20)

    def test_the_users_last_line_keeps_its_ending(self) -> None:
        for eol in (b"\n", b"\r\n"):
            for start in (b"a" + eol, b"a", b""):
                with self.subTest(start=start):
                    how = blocks.joint(start, blocks.MARKDOWN, "", blocks.END)
                    with_block = blocks.put(start, blocks.MARKDOWN, "", "x\n")
                    head, tail = around(with_block, blocks.MARKDOWN, "")
                    block = with_block[len(b"".join(head)):]
                    # The user writes a line of their own right before the block.
                    line = b"mine" + eol
                    now = (start + (eol if start and not blocks._ending(start) else b"")) + line + block
                    self.assertEqual(blocks.drop(now, blocks.MARKDOWN, "", joint=how), now[:-len(block)])
                    self.assertTrue(blocks.drop(now, blocks.MARKDOWN, "", joint=how).endswith(line))
        # A last line that had no ending has none again while it is the last ...
        how = blocks.joint(b"a\nb", blocks.MARKDOWN, "", blocks.END)
        with_block = blocks.put(b"a\nb", blocks.MARKDOWN, "", "x\n")
        self.assertEqual(blocks.drop(with_block, blocks.MARKDOWN, "", joint=how), b"a\nb")
        self.assertEqual(blocks.drop(b"new\n" + with_block, blocks.MARKDOWN, "", joint=how), b"new\na\nb")
        # ... and keeps the one it has once something follows the block.
        self.assertEqual(blocks.drop(with_block + b"c\n", blocks.MARKDOWN, "", joint=how), b"a\nb\nc\n")

    def test_the_file_of_the_finding(self) -> None:
        start = b"node_modules/\n*.log"
        with_block = blocks.put(start, blocks.GITIGNORE, "", ".agents/workflow.local.toml\n")
        self.assertEqual(blocks.drop(with_block + b"dist/\n", blocks.GITIGNORE), b"node_modules/\n*.log\ndist/\n")
        self.assertEqual(blocks.drop(with_block, blocks.GITIGNORE), start)
        crlf = b"a\r\nb"
        with_block = blocks.put(crlf, blocks.MARKDOWN, "", "x\n")
        self.assertEqual(blocks.drop(with_block + b"c", blocks.MARKDOWN), b"a\r\nb\r\nc")

    def test_two_blocks_go_in_either_order(self) -> None:
        for seed in range(SEEDS):
            rng = random.Random(seed)
            data = a_file(rng)
            places = [rng.choice([blocks.END, blocks.HEAD]) for _ in range(2)]
            both = blocks.put(blocks.put(data, blocks.MARKDOWN, "one", "1\n", places[0]), blocks.MARKDOWN, "two", "2\n", places[1])
            with self.subTest(seed=seed):
                for order in (("one", "two"), ("two", "one")):
                    out = both
                    for name in order:
                        out = blocks.drop(out, blocks.MARKDOWN, name)
                    self.assertEqual(out, data, order)


class TomlStringTests(unittest.TestCase):
    """A line of a multi-line string is that string's text, never a marker."""

    START, END = b"# workflow-setup:start codex-settings\n", b"# workflow-setup:end codex-settings\n"

    def strings(self) -> list[bytes]:
        marker_like = b"# workflow-setup:start codex-settings\n# workflow-setup:end other\n# workflow-setup:end\n"
        return [
            b'notes = """\n' + marker_like + b'"""\n',
            b"notes = '''\n" + marker_like + b"'''\n",
            b'notes = """ first\n\\\n' + marker_like + b'last """\n',
            b'notes = """\n' + marker_like + b'a "" b \\""" c\n""""\n',
            b"a = 'x' # ''' no string\nnotes = '''\n" + marker_like + b"'''\n",
            b'a = "\\"" # """ no string\nnotes = """\n' + marker_like + b'"""\n',
            b't = { s = """\n' + marker_like + b'""" }\n',
        ]

    def test_marker_like_lines_inside_a_string_are_not_markers(self) -> None:
        for text in self.strings():
            with self.subTest(text=text):
                tomllib.loads(text.decode())  # the case is TOML
                data = b"model = 1\n" + text + b"last = 2\n"
                self.assertEqual(blocks.scan(data, blocks.TOML), {})
                self.assertEqual(blocks.outside(data, blocks.TOML), [line.decode() for line in data.splitlines()])
                for place in (blocks.HEAD, blocks.END):
                    with_block = blocks.put(data, blocks.TOML, "codex-settings", "top = 1\n", place)
                    self.assertEqual(list(blocks.scan(with_block, blocks.TOML)), ["codex-settings"])
                    self.assertEqual(blocks.content_of(with_block, blocks.TOML, "codex-settings"), ["top = 1"])
                    self.assertEqual(tomllib.loads(with_block.decode())["top"], 1)
                    self.assertEqual(blocks.drop(with_block, blocks.TOML, "codex-settings"), data)
                # The same lines in a comment-syntax file that has no such strings are markers.
                with self.assertRaises(blocks.Refusal):
                    blocks.scan(data, blocks.GITIGNORE)

    def test_a_marker_outside_a_string_is_still_a_marker(self) -> None:
        string = self.strings()[0]
        cases = {
            "a start with no end": (string + self.START + b"x = 1\n", "without a workflow-setup:end"),
            "an end with no start": (self.END + string, "without a workflow-setup:start"),
            "an end inside a string does not close a block": (
                self.START + b'x = """\n' + self.END + b'"""\n', "without a workflow-setup:end"),
            "a start after a string that only looks open": (
                b'a = "x" # """\n' + self.START + b"y = 1\n", "without a workflow-setup:end"),
            "nested": (self.START + string + self.START + self.END, "inside the block opened on line 1"),
        }
        for name, (data, words) in cases.items():
            with self.subTest(name):
                with self.assertRaises(blocks.Refusal) as caught:
                    blocks.scan(data, blocks.TOML)
                self.assertIn(words, str(caught.exception))
        whole = string + self.START + b"x = 1\n" + self.END + b"y = 2\n"
        self.assertEqual(blocks.content_of(whole, blocks.TOML, "codex-settings"), ["x = 1"])
        # A block of setup's that holds a multi-line string of its own.
        inner = self.START + b'x = """\nline\n# workflow-setup:start other\n"""\n' + self.END
        self.assertEqual(list(blocks.scan(inner, blocks.TOML)), ["codex-settings"])

    def test_random_toml_files_keep_their_strings(self) -> None:
        for seed in range(SEEDS):
            rng = random.Random(seed)
            data = a_file(rng, toml=True)
            bom, body = blocks.split_bom(data)
            string = rng.choice(self.strings())
            # A top-level key goes before any table.
            data = bom + string.replace(b"notes", b"zz_notes").replace(b"a = ", b"zz_a = ").replace(b"t = ", b"zz_t = ") + body
            with self.subTest(seed=seed):
                tomllib.loads(data.decode("utf-8-sig"))
                for place in (blocks.HEAD, blocks.END):
                    with_block = blocks.put(data, blocks.TOML, "s", "# setup\n", place)
                    self.assertEqual(blocks.drop(with_block, blocks.TOML, "s"), data)
                    tomllib.loads(with_block.decode("utf-8-sig"))


class FileBlockProperties(OpsCase):
    """The same through a plan, its record and the way back."""

    def one(self, seed: int) -> None:
        rng = random.Random(seed)
        name = rng.choice(["CLAUDE.md", ".gitignore"])
        syntax = blocks.syntax_for(name)
        path = self.home / "p" / str(seed) / name
        start = a_file(rng)
        self.put(path, start)
        plan = self.plan()
        block = rng.choice(["", "n1"])
        place = rng.choice([fileops.END, fileops.HEAD])
        plan.edit_block(path, "ours\nmore\n", name=block, place=place)
        plan.apply()
        unchanged = rng.random() < 0.25
        if not unchanged:
            path.write_bytes(edited(rng, path.read_bytes(), syntax, block))
        now = path.read_bytes()
        mine = user_lines(now, syntax)
        # The record keeps how the block was joined to the file.
        how = self.record().get(self.roots.key(path))["blocks"][block]["joint"]
        self.assertEqual(how, blocks.joint(start, syntax, block, place))
        result = self.reversal().apply()
        self.assertEqual(result.kept, [])
        if unchanged:
            self.assertEqual(path.read_bytes(), start)
            return
        out = path.read_bytes() if path.exists() else b""
        left = user_lines(out, syntax)
        self.assertEqual([line for line in left if line], [line for line in mine if line])
        self.assertIn(len(mine) - len(left), (0, 1))
        check_endings(self, now, out, syntax, block, how)
        self.assertIsNone(self.record().get(self.roots.key(path)))

    def test_the_way_back_keeps_every_line_of_the_users(self) -> None:
        for seed in range(150):
            with self.subTest(seed=seed):
                self.one(seed)

    def test_a_toml_file_with_a_marker_like_line_in_a_string(self) -> None:
        text = b'model = "x"\nnotes = """\n[agents]\nmax_threads = 1\n# workflow-setup:start codex-settings\n"""\n\n[t]\na = 1\n'
        path = self.put(self.home / ".codex" / "config.toml", text)
        plan = self.plan()
        plan.edit_block(path, "top = 1\n", name="codex-settings", place=fileops.HEAD)
        self.assertEqual(plan.apply().lines[-2:], ["edit file home:.codex/config.toml (backup)", "    block codex-settings: add"])
        parsed = tomllib.loads(path.read_bytes().decode())
        self.assertEqual((parsed["top"], parsed["model"]), (1, "x"))
        self.assertIn("# workflow-setup:start codex-settings\n", parsed["notes"])
        self.assertFalse(self.plan_again(path).changed)
        self.assertEqual(self.reversal().apply().kept, [])
        self.assertEqual(path.read_bytes(), text)

    def plan_again(self, path) -> fileops.Result:
        plan = self.plan()
        plan.edit_block(path, "top = 1\n", name="codex-settings", place=fileops.HEAD)
        return plan.apply()


class UnrecordedBlockTests(OpsCase):
    """Markers of setup's with no record of the block between them (S1)."""

    START, END = b"<!-- workflow-setup:start -->\n", b"<!-- workflow-setup:end -->\n"
    THEIRS = b"MY OWN NOTES THAT I WROTE BETWEEN THE MARKERS\n"

    def setUp(self) -> None:
        super().setUp()
        self.file = self.home / ".codex" / "AGENTS.md"
        self.text = b"# Mine\n\n" + self.START + self.THEIRS + self.END + b"tail\n"
        self.put(self.file, self.text)

    def edit(self, **options) -> fileops.Plan:
        plan = self.plan()
        plan.edit_block(self.file, "what setup writes\n", **options)
        return plan

    def test_a_block_that_holds_other_text_is_the_users_and_a_conflict(self) -> None:
        problems = self.edit().check()
        self.assertEqual([problem.code for problem in problems], [fileops.CONFLICT])
        self.assertIn("holds a block between setup's markers", problems[0].message)
        self.assertIn("that setup did not write", problems[0].message)
        error = self.refused(self.edit())  # by the dry run and by the real one; the tree is as it was
        self.assertEqual(len(error.lines), 1)
        self.assertEqual(self.file.read_bytes(), self.text)
        self.assertFalse(self.state.exists())

    def test_it_is_replaced_only_when_asked_and_after_a_backup(self) -> None:
        result = self.edit(replace=fileops.ANY).apply()
        self.assertIn("edit file home:.codex/AGENTS.md (backup)", result.lines)
        self.assertEqual(self.file.read_bytes(), b"# Mine\n\n" + self.START + b"what setup writes\n" + self.END + b"tail\n")
        entry = self.record().get("home:.codex/AGENTS.md")
        backup = self.record().path(entry["original"]["backup"])
        self.assertEqual(backup.read_bytes(), self.text)
        # The way back gives the user's text again, markers and all.
        self.assertEqual(self.reversal().apply().kept, [])
        self.assertEqual(self.file.read_bytes(), self.text)

    def test_a_block_that_holds_exactly_setups_text_is_taken_into_the_record(self) -> None:
        same = b"# Mine\n\n" + self.START + b"what setup writes\n" + self.END + b"tail\n"
        for data in (same, same.replace(b"\n", b"\r\n")):
            with self.subTest(crlf=b"\r\n" in data):
                self.put(self.file, data)
                before = self.snap()
                result = self.edit().apply()
                self.assertEqual(result.lines, ["create directory home:.agents", "create directory home:.agents/workflow-setup",
                                                "update record home:.codex/AGENTS.md"])
                self.assertEqual(self.file.read_bytes(), data)
                self.assertEqual({name: value for name, value in self.snap().items() if "/.agents" not in name}, before)
                self.assertEqual(self.reversal().apply().kept, [])
                fileops.remove_state(self.roots)
                # It was setup's from then on, so the way back took it out:
                # the block and nothing else, since setup put no line
                # ending there with it. The blank line is the user's.
                eol = b"\r\n" if b"\r\n" in data else b"\n"
                self.assertEqual(self.file.read_bytes(), b"# Mine" + eol + eol + b"tail" + eol)

    def test_a_removal_leaves_a_block_the_record_does_not_hold(self) -> None:
        plan = self.plan()
        plan.remove_block(self.file)
        result = plan.apply()
        self.assertFalse(result.changed)
        self.assertEqual(self.file.read_bytes(), self.text)
        self.assertTrue(any("that the record does not hold; left as it is" in note for note in result.notes), result.notes)
        plan = self.plan()
        plan.remove_block(self.file, replace=fileops.ANY)
        self.assertTrue(plan.apply().changed)
        # Nothing says setup put a line ending there with it: none goes.
        self.assertEqual(self.file.read_bytes(), b"# Mine\n\ntail\n")

    def test_the_users_text_survives_a_lost_state_directory(self) -> None:
        """The case of the finding: setup wrote its block, the state
        directory was removed by hand, the user rewrote the block."""
        self.put(self.file, b"# Mine\n")
        self.edit().apply()
        self._clear(self.state)
        text = self.file.read_bytes().replace(b"what setup writes\n", self.THEIRS)
        self.file.write_bytes(text)
        self.refused(self.edit())
        self.assertEqual(self.reversal().apply().lines, [fileops.UP_TO_DATE])
        self.assertEqual(self.file.read_bytes(), text)
        self.assertIn(self.THEIRS, self.file.read_bytes())

    def _clear(self, path) -> None:
        for name in sorted(path.rglob("*"), key=lambda item: -len(item.parts)):
            name.rmdir() if name.is_dir() else name.unlink()
        path.rmdir()

    IGNORE_HEAD = b"node_modules/\n\n# workflow-setup:start\n"
    IGNORE_END = b"# workflow-setup:end\n"

    def ignore(self, **options) -> fileops.Result:
        plan = self.plan()
        plan.ignore(add=[".codex/agents/x.toml"], **options)
        return plan.apply()

    def test_the_ignore_block_of_a_checkout_is_taken_over(self) -> None:
        """A checkout has the block in its committed file and no record,
        which is ignored. Every line of it is an entry setup writes: its
        entries stay, and the fixed ones join them."""
        ignore = self.project / ".gitignore"
        text = self.IGNORE_HEAD + b".claude/agents/manager.md\n.codex/agents/old.toml\n" + self.IGNORE_END
        self.put(ignore, text)
        result = self.ignore()
        self.assertEqual(result.edited, [])
        self.assertIn("edit file project:.gitignore (backup)", result.lines)
        held = blocks.content_of(ignore.read_bytes(), blocks.GITIGNORE)
        self.assertEqual(
            held,
            sorted([*fileops.IGNORE_ALWAYS, ".claude/agents/manager.md", ".codex/agents/old.toml", ".codex/agents/x.toml"]),
        )
        self.assertEqual(blocks.outside(ignore.read_bytes(), blocks.GITIGNORE), ["node_modules/", ""])
        self.assertTrue(fsio.is_file(ignore))
        self.assertFalse(self.ignore().changed)
        # The way back gives the committed file again, byte for byte.
        self.assertEqual(self.reversal(project=True).apply().kept, [])
        self.assertEqual(ignore.read_bytes(), text)

    def test_an_ignore_block_with_a_line_of_the_users_is_left_and_named(self) -> None:
        """Any other line between the markers is the user's text: the
        block is left as it is and listed, and nothing at all is written."""
        ignore = self.project / ".gitignore"
        for line in (b"# a line of the team's\n", b"dist/\n", b".claude/agents/../secret\n", b"\n"):
            with self.subTest(line=line):
                text = self.IGNORE_HEAD + b".claude/agents/manager.md\n" + line + self.IGNORE_END
                self.put(ignore, text)
                before = self.snap()
                result = self.ignore()
                self.assertFalse(result.changed)
                self.assertEqual([key for key, _ in result.edited], ["project:.gitignore"])
                self.assertIn("holds lines between setup's markers that setup does not write", result.edited[0][1])
                self.assertIn("it was left as it is", result.edited[0][1])
                self.assertEqual(self.snap(), before)
                self.assertEqual(ignore.read_bytes(), text)
                self.assertFalse((self.project / ".agents").exists())
                self.assertFalse(self.state.exists())

    def test_it_is_written_only_when_asked_and_the_users_lines_come_back(self) -> None:
        ignore = self.project / ".gitignore"
        text = self.IGNORE_HEAD + b".claude/agents/manager.md\n# a line of the team's\n" + self.IGNORE_END
        self.put(ignore, text)
        result = self.ignore(replace=fileops.ANY)
        self.assertEqual(result.edited, [])
        self.assertIn("edit file project:.gitignore (backup)", result.lines)
        self.assertEqual(
            blocks.content_of(ignore.read_bytes(), blocks.GITIGNORE), sorted([*fileops.IGNORE_ALWAYS, ".codex/agents/x.toml"])
        )
        # What the block held is kept, in the record and in a backup of the file.
        entry = self.record().get("project:.gitignore")
        self.assertEqual(
            entry["blocks"][""]["replaced"],
            {
                "text": "# workflow-setup:start\n.claude/agents/manager.md\n# a line of the team's\n# workflow-setup:end\n",
                "backup": entry["original"]["backup"],
            },
        )
        self.assertEqual(self.record().path(entry["original"]["backup"]).read_bytes(), text)
        self.assertEqual(self.reversal(project=True).apply().kept, [])
        self.assertEqual(ignore.read_bytes(), text)


class RecordedBlockTests(OpsCase):
    """A block the record holds, edited by hand since: the text between
    the markers is the user's now."""

    START, END = b"<!-- workflow-setup:start -->\n", b"<!-- workflow-setup:end -->\n"

    def setUp(self) -> None:
        super().setUp()
        self.file = self.put(self.home / ".claude" / "CLAUDE.md", b"# Mine\n")
        self.edit("ours\n").apply()
        self.text = b"# Mine\n\n" + self.START + b"ours, and a line of mine\n" + self.END
        self.file.write_bytes(self.text)

    def edit(self, content: str, **options) -> fileops.Plan:
        plan = self.plan()
        plan.edit_block(self.file, content, **options)
        return plan

    def test_it_is_a_conflict_whatever_setup_would_write(self) -> None:
        for content in ("ours\n", "new\n"):
            with self.subTest(content=content):
                problems = self.edit(content).check()
                self.assertEqual([problem.code for problem in problems], [fileops.CONFLICT])
                self.assertIn("was edited since setup wrote it; it was left as it is", problems[0].message)
                self.assertEqual(self.refused(self.edit(content)).codes(), {fileops.CONFLICT})
                self.assertEqual(self.file.read_bytes(), self.text)

    def test_it_is_written_when_asked_after_a_backup(self) -> None:
        for policy in (fileops.EDITED, fileops.ANY):
            with self.subTest(policy=policy):
                self.file.write_bytes(self.text)
                result = self.edit("new\n", replace=policy).apply()
                self.assertIn("edit file home:.claude/CLAUDE.md (backup)", result.lines)
                self.assertEqual(self.file.read_bytes(), b"# Mine\n\n" + self.START + b"new\n" + self.END)
                held = [self.record().path(item["backup"]).read_bytes() for item in self.record().backups]
                self.assertIn(self.text, held)
                self.assertFalse(self.edit("new\n").apply().changed)
                self.edit("ours\n").apply()

    def test_the_way_back_keeps_it_and_its_entry(self) -> None:
        result = self.reversal().apply()
        self.assertEqual([key for key, _ in result.kept], ["home:.claude/CLAUDE.md"])
        self.assertEqual(self.file.read_bytes(), self.text)
        self.assertIsNotNone(self.record().get("home:.claude/CLAUDE.md"))


class CreatedFileTests(OpsCase):
    """A file setup created is removed again only when nothing but white
    space is left once setup's part is out, whatever its hash."""

    def setUp(self) -> None:
        super().setUp()
        self.file = self.home / ".claude" / "CLAUDE.md"
        self.key = "home:.claude/CLAUDE.md"

    def created(self) -> bytes:
        plan = self.plan()
        plan.edit_block(self.file, "ours\n")
        plan.apply()
        self.assertTrue(self.record().get(self.key)["created"])
        return self.file.read_bytes()

    def test_white_space_alone_goes_with_the_file(self) -> None:
        for more in (b"", b"\n\n", b" \t\r\n", b"\r\n   "):
            with self.subTest(more=more):
                block = self.created()
                self.file.write_bytes(block + more)
                self.assertEqual(self.reversal().apply().kept, [])
                self.assertFalse(os.path.lexists(self.file))
                self.assertIsNone(self.record().get(self.key))
                self.assertTrue(fileops.remove_state(self.roots))

    def test_anything_else_stays_as_the_user_wrote_it(self) -> None:
        for before, after in ((b"", b"mine\n"), (b"mine\n", b""), (b"mine\n\n", b"\n  more"), (b"", b"\n.\n")):
            with self.subTest(before=before, after=after):
                block = self.created()
                self.file.write_bytes(before + block + after)
                self.assertEqual([key for key, _ in self.reversal().apply().kept if key == self.key], [])
                self.assertEqual(self.file.read_bytes(), before + after)
                self.assertIsNone(self.record().get(self.key))
                self.file.unlink()
                self.reversal().apply()
                self.assertTrue(fileops.remove_state(self.roots))


if __name__ == "__main__":
    unittest.main()
