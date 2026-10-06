"""The file operations on many made-up homes: whatever the runs, a dry run
changes nothing, a second run writes nothing, a refused plan leaves the
tree alone, and the way back gives every path, link target, byte and mode
of the start (R8.1).

The homes and the plans are drawn from a seeded generator, so a failure
names its seed and repeats.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import os
import random
import unittest
from pathlib import Path

from fileops_support import SYMLINKS, OpsCase
from wfsetup import fileops

SEEDS = 120

TEXTS = [b"", b"a", b"a\n", b"a\r\nb\r\n", b"\xef\xbb\xbfx\n", b"x\n@line\ny", b"@line\n", b"\n\n"]
JSONS = [b"{}", b'{"a": 1}', b'{\n  "agent": "mine",\n  "z": [1, 2]\n}\n', b'{"a":{"agent":1}}\r\n']
TOMLS = [b"", b"a = 1\n", b"a = 1\n\n[t]\nb = 2", b"# c\r\n[t]\r\nb = 2\r\n"]


class RandomRoundTripTests(OpsCase):
    def fill(self, rng: random.Random) -> None:
        for directory in (self.home / "sub", self.project / ".claude", self.clone / "s1", self.clone / "s2"):
            directory.mkdir(parents=True)
        for path, choices, chance in (
            (self.home / "CLAUDE.md", TEXTS, 0.8),
            (self.home / "sub" / "AGENTS.md", TEXTS, 0.6),
            (self.project / ".claude" / "settings.json", JSONS, 0.7),
            (self.home / "config.toml", TOMLS, 0.6),
            (self.project / ".gitignore", [b"x\n", b"q", b"a\r\n"], 0.5),
            (self.home / "user.toml", [b"mine = 1\n"], 0.5),
            (self.home / "stale.md", [b"stale\n"], 0.5),
        ):
            if rng.random() < chance:
                path.write_bytes(rng.choice(choices))
        if SYMLINKS and rng.random() < 0.5:
            os.symlink("../nowhere", self.home / "userlink")
        if rng.random() < 0.3:
            (self.home / ".agents").mkdir()

    def actions(self, rng: random.Random) -> list[tuple[str, tuple, dict]]:
        """One plan's actions. A plan either puts blocks in or takes them
        out: doing both to one block in one plan moves it each time, which
        no command does."""
        home, project, clone = self.home, self.project, self.clone
        texts = [home / "CLAUDE.md", home / "sub" / "AGENTS.md", home / "new" / "deep" / "N.md"]
        taking_out = rng.random() < 0.3
        made: list[tuple[str, tuple, dict]] = []
        for _ in range(rng.randint(1, 7)):
            pick = rng.randint(0, 11)
            if pick == 0:
                made.append(("write_file", (home / "gen" / rng.choice(["a.md", "b.md"]), "one\n"), {"inputs": "d"}))
            elif pick == 1:
                made.append(("write_file", (home / "user.toml", rng.choice(["s = 1\n", "s = 2\n"])), {"replace": fileops.ANY}))
            elif pick == 2:
                made.append(("remove_file", (rng.choice([home / "stale.md", home / "gen" / "a.md", home / "CLAUDE.md"]),), {}))
            elif pick in (3, 4) and taking_out:
                made.append(("remove_block", (rng.choice(texts),), {"name": rng.choice(["", "n1"])}))
            elif pick in (3, 4):
                made.append(("edit_block", (rng.choice(texts), rng.choice(["p\n", "q\nr\n", ""])), {
                    "name": rng.choice(["", "n1"]), "place": rng.choice([fileops.END, fileops.HEAD]),
                }))
            elif pick == 5:
                made.append(("remove_lines", (rng.choice(texts), ["@line"]), {}))
            elif pick == 6:
                made.append(("edit_json", (project / ".claude" / "settings.json",), {"set": {"agent": rng.choice(["m", {"k": [1]}])}}))
            elif pick == 7:
                made.append(("edit_json", (project / ".claude" / "settings.json",), {"remove": ["agent"]}))
            elif pick == 8:
                made.append(("ignore", (), {"add": rng.sample(["x", "y", "z"], rng.randint(0, 2)), "remove": rng.sample(["x", "y"], rng.randint(0, 1))}))
            elif pick == 9:
                made.append(("edit_block", (home / "config.toml", rng.choice(["k = 1\n", "k = 2\n"])), {"name": "s", "place": fileops.HEAD}))
            elif pick == 10 and SYMLINKS:
                made.append(("create_link", (home / "skills" / "s1", clone / rng.choice(["s1", "s2"])), {}))
            elif pick == 11 and SYMLINKS:
                made.append(("remove_link", (rng.choice([home / "skills" / "s1", home / "userlink"]),), {}))
            else:
                made.append(("create_directory", (home / "d" / "e",), {}))
        return made

    def build(self, actions: list[tuple[str, tuple, dict]]) -> fileops.Plan:
        plan = self.plan()
        for name, arguments, options in actions:
            getattr(plan, name)(*arguments, **options)
        return plan

    def one(self, seed: int) -> None:
        rng = random.Random(seed)
        self.fill(rng)
        start = self.snap()
        for _ in range(rng.randint(1, 4)):
            actions = self.actions(rng)
            before = self.snap()
            try:
                dry = self.build(actions).describe()
            except fileops.PlanError:
                with self.assertRaises(fileops.PlanError):
                    self.build(actions).apply()
                self.assertEqual(self.snap(), before, "a refused plan changed the tree")
                continue
            self.assertEqual(self.snap(), before, "a dry run changed the tree")
            self.assertEqual(self.build(actions).apply().lines, dry.lines)
            after = self.snap()
            try:
                again = self.build(actions).apply()
            except fileops.PlanError:
                # The plan undid its own precondition: it removed a file it
                # also edits. Refused, and nothing written.
                self.assertEqual(self.snap(), after)
                continue
            self.assertEqual(again.lines, [fileops.UP_TO_DATE])
            self.assertEqual(self.snap(), after, "a second run wrote something")
            record = self.record()
            for key, entry in record:
                if "sha256" in entry:
                    self.assertEqual(entry["sha256"], fileops.fsio.sha256(record.path(key).read_bytes()), key)
        kept: list[tuple[str, str]] = []
        for project in (True, False):
            kept += self.reversal(project=project).apply().kept
            fileops.remove_state(self.roots, project=project)
        self.assertEqual(kept, [])
        self.assertEqual(self.snap(), start, "the way back did not end at the start")

    def test_many_homes_and_many_plans(self) -> None:
        for seed in range(SEEDS):
            with self.subTest(seed=seed):
                for name in os.listdir(self.root):
                    self._clear(self.root / name)
                for directory in (self.home, self.project, self.clone):
                    directory.mkdir()
                self.one(seed)

    def _clear(self, path: Path) -> None:
        if path.is_symlink() or not path.is_dir():
            path.unlink()
            return
        for name in os.listdir(path):
            self._clear(path / name)
        path.rmdir()


if __name__ == "__main__":
    unittest.main()
