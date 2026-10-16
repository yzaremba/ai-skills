"""Tests of the third review's findings.

S1  the settings file ``init`` wrote is removed by ``uninstall`` only while
    it holds exactly what ``init`` wrote; with anything of the user's in it,
    it is left.
S2  what ``--overwrite-edited`` replaced in a recorded block or at a key is
    put back in its place, and its backup is never removed where it cannot be.
S3  the gaps the mutation pass showed (``MutationGapTests``).
M1-M9  the minor findings, each under its own name.

Run from the repository root:
    python -B -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import stat
import threading
import unittest
from pathlib import Path
from unittest import mock

import support
from crash_support import gone_pid
from fileops_support import POSIX, SYMLINKS, OpsCase
from test_doctor import DoctorCase, limit_loaded_skills
from test_migrate import MigrateCase
from test_uninstall import USER_SETTINGS, UninstallCase
from wfsetup import blocks, doctor, entry, fileops, fsio, lock, manifest as records, render
from wfsetup.errors import SetupError
from wfsetup.manifest import Manifest, Roots

HAND = b'\n# my own override, set by hand\n[process]\ndocs_dir = "documentation"\n'
START, END = b"<!-- workflow-setup:start -->\n", b"<!-- workflow-setup:end -->\n"


def flat(text: str) -> str:
    return " ".join(text.split())


# --- S1: the settings file -------------------------------------------------------

class SettingsFileTests(UninstallCase):
    """No value the user set in a settings file is removed by ``uninstall``."""

    def rewritten(self, file: Path, *where: str) -> bytes:
        """``init``; the user adds keys by hand; ``init`` with another
        answer, which rewrites the file from its values. Returns what the
        file holds then."""
        self.done("init", "--yes", *where)
        file.write_bytes(file.read_bytes() + HAND)
        code, out, err = self.cli("init", "--yes", "--max-parallel-coders", "2", *where)
        self.assertEqual(code, 2, out)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertIn("Give --rewrite-settings with --yes", err)
        # What the message says of `uninstall` is what `uninstall` does.
        self.assertIn("leaves in place, as yours, one that `init` rewrote after you edited it", err)
        self.assertNotIn("and `uninstall` puts it back", err)
        self.done("init", "--yes", "--rewrite-settings", "--max-parallel-coders", "2", *where)
        wrote = file.read_bytes()
        self.assertIn(b'docs_dir = "documentation"', wrote)      # the user's key, kept by the rewrite
        self.assertIn(b"max_parallel_coders = 2", wrote)
        self.assertNotIn(b"my own override", wrote)               # its comments are not
        return wrote

    def test_a_file_init_created_and_nobody_edited_is_removed(self) -> None:
        self.done("init", "--user", "--yes", *self.at_home)
        out = self.done("uninstall", "--dry-run", *self.at_home)
        (line,) = [line for line in out.splitlines() if line.strip().startswith("remove file home:.agents/workflow.toml")]
        self.assertIn("--keep-settings leaves it as it is, as yours", line)
        report = self.uninstall()
        self.assertEqual((report["kept"], report["left"]), ([], []))
        self.assertNothingAt(self.home / ".agents")
        self.assertNoState()

    def test_a_file_rewritten_from_a_hand_edited_one_is_left_with_the_users_keys(self) -> None:
        wrote = self.rewritten(self.user_file, "--user", *self.at_home)
        known = fileops.read_record(self.roots()).entries["home:.agents/workflow.toml"]
        self.assertIs(known[fileops.REWRITTEN], True)
        self.assertEqual(known["sha256"], fsio.sha256(wrote))    # the hash alone would say "as setup left it"
        dry = self.uninstall("--dry-run")
        self.assertEqual([item["key"] for item in dry["left"]], ["home:.agents/workflow.toml"])
        self.assertEqual(dry["removed"], [])
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        self.assertEqual([item["key"] for item in report["left"]], ["home:.agents/workflow.toml"])
        self.assertIn("holds values you set", report["left"][0]["why"])
        self.assertIn("is yours", report["left"][0]["why"])
        self.assertEqual(self.user_file.read_bytes(), wrote)
        self.assertNoState()                                     # left, and the uninstall is finished

    def test_the_same_for_a_projects_settings_file(self) -> None:
        wrote = self.rewritten(self.project_file, *self.at_home, *self.in_project)
        record = fileops.read_record(Roots(self.home, self.project, self.clone))
        self.assertIs(record.entries["project:.agents/workflow.toml"][fileops.REWRITTEN], True)
        report = self.uninstall(project=True)
        self.assertEqual(report["kept"], [])
        self.assertEqual([item["key"] for item in report["left"]], ["project:.agents/workflow.toml"])
        self.assertEqual(self.project_file.read_bytes(), wrote)
        self.assertNothingAt(self.project_state)

    def test_the_mark_stays_through_a_later_init(self) -> None:
        self.rewritten(self.user_file, "--user", *self.at_home)
        # Nobody edited it since, so --yes alone writes it again.
        self.done("init", "--user", "--yes", "--max-parallel-coders", "4", *self.at_home)
        wrote = self.user_file.read_bytes()
        self.assertIs(fileops.read_record(self.roots()).entries["home:.agents/workflow.toml"][fileops.REWRITTEN], True)
        report = self.uninstall()
        self.assertEqual([item["key"] for item in report["left"]], ["home:.agents/workflow.toml"])
        self.assertEqual(self.user_file.read_bytes(), wrote)
        self.assertIn(b'docs_dir = "documentation"', wrote)

    def test_a_file_that_was_there_before_the_first_init_comes_back_and_the_dry_run_names_the_option(self) -> None:
        self.data(self.user_file, USER_SETTINGS)
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home)
        self.assertNotIn(fileops.REWRITTEN, fileops.read_record(self.roots()).entries["home:.agents/workflow.toml"])
        out = self.done("uninstall", "--dry-run", *self.at_home)
        (line,) = [line for line in out.splitlines() if line.strip().startswith("restore file home:.agents/workflow.toml")]
        self.assertIn("--keep-settings", line)
        report = self.uninstall()
        self.assertEqual((report["kept"], report["left"]), ([], []))
        self.assertEqual(self.user_file.read_bytes(), USER_SETTINGS.encode("utf-8"))

    def test_but_not_once_init_rewrote_what_the_user_edited_after_that(self) -> None:
        self.data(self.user_file, USER_SETTINGS)
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home)
        self.user_file.write_bytes(self.user_file.read_bytes() + b'\n[memory]\ndir = "mine"\n')
        self.done("init", "--user", "--yes", "--rewrite-settings", "--max-parallel-coders", "2", *self.at_home)
        wrote = self.user_file.read_bytes()
        report = self.uninstall()
        self.assertEqual([item["key"] for item in report["left"]], ["home:.agents/workflow.toml"])
        # Neither removed nor replaced by the older file: it holds every value the user set.
        self.assertEqual(self.user_file.read_bytes(), wrote)
        for value in (b'dir = "mine"', b'docs_dir = "notes"', b"max_parallel_coders = 2"):
            self.assertIn(value, wrote)

    def test_a_record_with_a_mark_that_is_not_one_is_refused(self) -> None:
        self.done("init", "--user", "--yes", *self.at_home)
        file = self.state / "manifest.json"
        data = json.loads(file.read_bytes())
        data["entries"]["home:.agents/workflow.toml"]["rewritten"] = "yes"
        file.write_bytes(json.dumps(data).encode())
        with self.assertRaises(SetupError) as caught:
            fileops.read_record(self.roots())
        self.assertIn("its rewritten mark is not true or false", caught.exception.lines[0])

    def test_the_rule_is_in_both_help_texts(self) -> None:
        said = flat(support.run("uninstall", "--help")[1])
        for words in (
            "No value you set in a settings file is removed by `uninstall`",
            "removed, when `init` created it and it holds exactly what `init` wrote from its own answers",
            "replaced, byte for byte, by the file that was there before the first `init`, when nothing but `init` has "
            "written it since",
            "left as it is, and yours from then on, in every other case",
            "names --keep-settings on the line that would remove or replace the file",
        ):
            self.assertIn(words, said)
        said = flat(support.run("init", "--help")[1])
        self.assertIn("No value you set is removed. `uninstall` removes the file only when `init` created it", said)
        self.assertIn("`uninstall` then leaves it as it is, and it is yours", said)


# --- S2: what --overwrite-edited replaced ---------------------------------------

class OverwrittenTextTests(OpsCase):
    """Text of the user's that setup replaced because it was asked to is
    put back where it was, or its backup is kept."""

    def setUp(self) -> None:
        super().setUp()
        self.file = self.home / ".claude" / "CLAUDE.md"
        self.key = "home:.claude/CLAUDE.md"
        self.json = self.project / ".claude" / "settings.json"
        self.json_key = "project:.claude/settings.json"

    def edit(self, text: str = "ours\n", **how) -> fileops.Result:
        plan = self.plan()
        plan.edit_block(self.file, text, **how)
        return plan.apply()

    def set(self, value: str = "manager") -> fileops.Result:
        plan = self.plan()
        plan.edit_json(self.json, set={"agent": value})
        return plan.apply()

    def overwritten(self, before: bytes | None = b"# Mine\n") -> tuple[bytes, Path]:
        """Setup's block, edited by the user, written again on request.
        Returns the file as the user had it, and the backup that holds it."""
        if before is not None:
            self.put(self.file, before)
        self.edit()
        mine = self.file.read_bytes().replace(START, START + b"MY OWN IMPORTANT NOTE\n")
        self.file.write_bytes(mine)
        with self.assertRaises(fileops.PlanError):
            self.edit("ours, in a newer version\n")                       # not without being asked
        self.edit("ours, in a newer version\n", replace=fileops.EDITED)
        self.assertNotIn(b"MY OWN IMPORTANT NOTE", self.file.read_bytes())
        replaced = self.record().get(self.key)["blocks"][""]["replaced"]
        self.assertEqual(replaced["text"].encode(), START + b"MY OWN IMPORTANT NOTE\nours\n" + END)
        backup = self.record().path(replaced["backup"])
        self.assertEqual(backup.read_bytes(), mine)
        return mine, backup

    def test_a_recorded_block_gets_the_users_text_back_in_its_place(self) -> None:
        mine, backup = self.overwritten()
        back = self.reversal().apply()
        self.assertEqual((back.kept, back.left, back.unlisted), ([], [], []))
        self.assertIn("    block (unnamed): put back what it replaced", back.lines)
        self.assertEqual(self.file.read_bytes(), mine)                    # the file stays, with the user's text
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertFalse(self.state.exists())                             # the text is in the file: its backup may go

    def test_a_file_setup_created_stays_with_the_users_text(self) -> None:
        mine, _ = self.overwritten(before=None)
        back = self.reversal().apply()
        # The file stays, and so the directory setup made for it is the user's now.
        self.assertEqual([key for key, _ in back.kept], ["home:.claude"])
        self.assertEqual([key for key, _ in back.left], ["home:.claude"])
        self.assertEqual(back.unlisted, [])
        self.assertEqual(self.file.read_bytes(), mine)
        self.assertIn(b"MY OWN IMPORTANT NOTE", mine)
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertFalse(self.state.exists())

    def test_a_second_run_of_the_same_plan_writes_nothing(self) -> None:
        self.overwritten()
        before = self.snap()
        self.assertEqual(self.edit("ours, in a newer version\n", replace=fileops.EDITED).lines, [fileops.UP_TO_DATE])
        self.assertEqual(self.snap(), before)

    def test_a_block_that_is_gone_keeps_the_backup_and_names_it(self) -> None:
        mine, backup = self.overwritten()
        self.file.write_bytes(b"# Mine\n")                                # the user took the block out
        dry = self.reversal().describe()
        self.assertEqual(dry.unlisted, [backup])
        back = self.reversal().apply()
        self.assertEqual(back.kept, [])
        self.assertEqual(back.unlisted, [backup])
        (note,) = [note for note in back.notes if str(backup) in note]
        self.assertIn("could not be put back where it was", note)
        self.assertIn("--overwrite-edited", note)
        self.assertEqual(self.file.read_bytes(), b"# Mine\n")
        # The record lets go of it, so that nothing removes it with the record.
        self.assertEqual(fileops.unlisted_backups(self.roots), [backup])
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(backup.read_bytes(), mine)                       # the only copy of the user's text
        self.assertFalse(self.manifest_file.exists())
        self.assertEqual(fileops.discard_backups(self.roots), [backup])   # and goes when the user says so
        fileops.remove_state(self.roots)
        self.assertFalse(self.state.exists())

    def test_text_replaced_twice_at_one_place_keeps_the_first_in_its_backup(self) -> None:
        foreign = b"# Mine\n\n" + START + b"text of mine between setup's markers\n" + END
        self.put(self.file, foreign)
        self.edit(replace=fileops.ANY)
        first = self.record().path(self.record().get(self.key)["blocks"][""]["replaced"]["backup"])
        self.assertEqual(first.read_bytes(), foreign)
        edited = self.file.read_bytes().replace(b"ours\n", b"ours, and a line of mine\n")
        self.file.write_bytes(edited)
        result = self.edit(replace=fileops.EDITED)
        # One place holds one text: the later one goes back, the earlier one stays in its backup.
        self.assertEqual(result.unlisted, [first])
        self.assertTrue(any(str(first) in note for note in result.notes))
        replaced = self.record().get(self.key)["blocks"][""]["replaced"]
        self.assertIn("ours, and a line of mine", replaced["text"])
        self.assertEqual(self.reversal().apply().unlisted, [])
        self.assertEqual(self.file.read_bytes(), edited)
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(first.read_bytes(), foreign)
        self.assertEqual(fileops.unlisted_backups(self.roots), [first])

    def test_the_backup_a_record_names_is_the_one_that_holds_the_text(self) -> None:
        foreign = b"# Mine\n\n" + START + b"text of mine between setup's markers\n" + END
        self.put(self.file, foreign)
        self.edit(replace=fileops.ANY)
        first = self.record().get(self.key)["blocks"][""]["replaced"]["backup"]
        # A run that takes the block out and writes it again over the same
        # text, and changes the file besides: it makes a backup of its own,
        # which holds setup's block and not the user's text.
        plan = self.plan()
        plan.remove_block(self.file)
        plan.edit_block(self.file, "ours\n", replace=fileops.ANY)
        plan.edit_block(self.file, "more\n", name="n1")
        result = plan.apply()
        self.assertEqual(result.unlisted, [])
        replaced = self.record().get(self.key)["blocks"][""]["replaced"]
        self.assertEqual(replaced["backup"], first)
        self.assertEqual(self.record().path(first).read_bytes(), foreign)

    def test_a_key_changed_by_hand_and_set_again_gets_the_users_value_back(self) -> None:
        self.put(self.json, b'{\n  "theme": "dark"\n}\n')
        self.set()
        mine = self.json.read_bytes().replace(b'"manager"', b'"mine"')
        self.json.write_bytes(mine)
        self.set()                                                       # as render --overwrite-edited does
        known = self.record().get(self.json_key)["keys"]["agent"]
        self.assertEqual((known["had"], known["previous"]), (True, "mine"))
        self.assertEqual(self.record().path(known["replaced"]["backup"]).read_bytes(), mine)
        back = self.reversal(project=True).apply()
        self.assertEqual((back.kept, back.left, back.unlisted), ([], [], []))
        self.assertEqual(self.json.read_bytes(), mine)
        self.assertTrue(fileops.remove_state(self.roots, project=True))
        self.assertFalse(self.project_state.exists())

    def test_a_plan_that_gives_a_key_up_and_sets_it_again_names_the_same_backup_each_time(self) -> None:
        self.put(self.json, b'{\n  "agent": "mine"\n}\n')

        def both() -> fileops.Result:
            plan = self.plan()
            plan.edit_json(self.json, remove=["agent"])
            plan.edit_json(self.json, set={"agent": "manager"})
            return plan.apply()

        both()
        known = self.record().get(self.json_key)["keys"]["agent"]
        after = self.snap()
        # The second run writes no file, so it makes no backup: it must not name one.
        self.assertEqual(both().lines, [fileops.UP_TO_DATE])
        self.assertEqual(self.record().get(self.json_key)["keys"]["agent"], known)
        self.assertEqual(self.snap(), after)
        self.assertTrue(self.record().path(known["replaced"]["backup"]).is_file())

    def test_a_key_changed_again_is_left_and_the_replaced_value_stays_in_its_backup(self) -> None:
        self.put(self.json, b'{\n  "agent": "mine"\n}\n')
        original = self.json.read_bytes()
        self.set()
        backup = self.record().path(self.record().get(self.json_key)["keys"]["agent"]["replaced"]["backup"])
        self.json.write_bytes(original.replace(b'"mine"', b'"another"'))
        back = self.reversal(project=True).apply()
        self.assertEqual([key for key, _ in back.left], [self.json_key])
        self.assertEqual(back.unlisted, [backup])
        self.assertIn(b'"another"', self.json.read_bytes())
        self.assertTrue(fileops.remove_state(self.roots, project=True))
        self.assertEqual(backup.read_bytes(), original)

    def test_the_file_put_back_by_hand_as_it_was_before_setup_needs_nothing(self) -> None:
        # The branch "what was there before setup is there again" of the way
        # back: nothing is left to undo, nothing is the user's "from now on",
        # and no backup has to stay.
        self.put(self.json, b'{\n  "agent": "mine"\n}\n')
        original = self.json.read_bytes()
        self.set()
        self.json.write_bytes(original)
        back = self.reversal(project=True).apply()
        self.assertEqual((back.kept, back.left, back.unlisted), ([], [], []))
        self.assertEqual(self.json.read_bytes(), original)
        self.assertTrue(fileops.remove_state(self.roots, project=True))
        self.assertFalse(self.project_state.exists())

    def test_the_record_takes_a_backup_off_its_list_and_checks_what_it_is_told(self) -> None:
        backup = records.backup_key("s1", self.key)
        listed = {"path": self.key, "kind": "file", "backup": backup, "sha256": "0" * 64, "mode": None, "stamp": "s1"}
        one = Manifest(self.manifest_file, records.HOME)
        one.backups = [dict(listed)]
        one.commit({"path": self.key, "set": True, "entry": None, "backup": None, "unlist": [backup]})
        self.assertEqual(one.backups, [])
        one.backups = [dict(listed)]
        for bad in (["home:.ssh/id_ed25519"], [records.backup_key("s1", "home:other.md")], "text", [3]):
            one.pending = [{"path": self.key, "after": None, "set": True, "entry": None, "backup": None, "unlist": bad}]
            self.assertIn("the backups it takes out of the record are not backups of this path", one.fault() or "")
        entry_ = {"kind": "text", "sha256": None, "blocks": {"": {"sha256": "0" * 64, "replaced": {
            "text": "x", "backup": "home:.ssh/id_ed25519"}}}}
        self.assertIn("does not hold what it replaced", records.entry_fault(self.key, entry_) or "")
        keyed = {"kind": "json", "sha256": None, "keys": {"agent": {"value": 1, "replaced": {"backup": "home:x"}}}}
        self.assertIn("does not say what it replaced", records.entry_fault("project:.claude/settings.json", keyed) or "")


class OverwriteEditedCommandTests(UninstallCase):
    """The same through the commands: ``render --overwrite-edited``, then
    ``uninstall``."""

    def edited_and_overwritten(self) -> bytes:
        self.done("render", "--no-roles", "--migrate-v1", *self.at_home)
        wrote = self.agents_md.read_bytes()
        mine = wrote.replace(b"Sprint and epic", b"MY OWN IMPORTANT NOTE\nSprint and epic", 1)
        self.assertNotEqual(mine, wrote)
        self.agents_md.write_bytes(mine)
        self.done("render", "--no-roles", "--migrate-v1", *self.at_home, code=3)
        self.assertEqual(self.agents_md.read_bytes(), mine)
        self.done("render", "--no-roles", "--migrate-v1", "--overwrite-edited", *self.at_home)
        self.assertEqual(self.agents_md.read_bytes(), wrote)
        return mine

    def test_uninstall_puts_the_users_line_back_and_keeps_the_file(self) -> None:
        mine = self.edited_and_overwritten()
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        self.assertEqual(self.agents_md.read_bytes(), mine)
        self.assertTrue(any("put back what it replaced" in line for line in report["restored"]))
        self.assertNoState()

    def test_where_it_cannot_be_put_back_the_backup_stays_is_named_and_the_code_is_3(self) -> None:
        mine = self.edited_and_overwritten()
        self.agents_md.write_bytes(b"")                 # the user removed setup's block, markers and all
        dry = self.uninstall("--dry-run", code=3)
        self.assertEqual(len(dry["state"]["unlisted_backups"]), 1)
        report = self.uninstall(code=3)
        (backup,) = [Path(path) for path in report["state"]["unlisted_backups"]]
        self.assertEqual(backup.read_bytes(), mine)
        self.assertEqual(report["kept"], [])
        self.assertTrue(any(str(backup) in note and "--overwrite-edited" in note for note in report["notes"]))
        self.assertIn("--discard-backups", report["state"]["why"])
        self.assertTrue(report["summary"].startswith("not finished: "))
        self.assertFalse((self.state / "manifest.json").exists())
        # A second uninstall says the same, and removes nothing.
        again = self.uninstall(code=3)
        self.assertEqual(again["state"]["unlisted_backups"], [str(backup)])
        self.assertEqual(backup.read_bytes(), mine)
        self.discard("--yes")
        self.assertNoState()

    def test_a_block_edited_again_is_kept_and_the_backup_of_the_first_text_is_named(self) -> None:
        mine = self.edited_and_overwritten()
        again = self.agents_md.read_bytes().replace(b"Sprint and epic", b"A SECOND NOTE\nSprint and epic", 1)
        self.agents_md.write_bytes(again)
        report = self.uninstall(code=3)
        item = self.kept(report, self.agents_md)
        self.assertIn("was edited since setup wrote it", item["why"])
        self.assertEqual(Path(item["backup"]).read_bytes(), mine)
        self.assertEqual(self.agents_md.read_bytes(), again)
        self.assertTrue((self.state / "manifest.json").is_file())

    def test_the_help_says_it(self) -> None:
        said = flat(support.run("uninstall", "--help")[1])
        self.assertIn("is put back where it was when setup's block or key goes", said)
        self.assertIn("Where that cannot be done exactly, the backup that holds your text is never removed, its path is "
                      "printed, and the exit code is 3", said)
        self.assertIn("the backup is taken out of the record and stays in the state directory", said)
        said = flat(support.run("render", "--help")[1])
        self.assertIn("What --overwrite-edited replaces in a key or a block is yours, and is not lost", said)


# --- S3: what the mutation pass showed missing ----------------------------------

class MutationGapTests(OpsCase):
    def second_path(self, directory: Path) -> str:
        """Another text for ``directory`` that the system takes to the same
        directory: through ``/proc/self/root`` on Linux, a junction on
        Windows, a link elsewhere."""
        if os.name == "nt":
            junction = self.root / "second-path"
            fsio.make_junction(str(directory), junction)
            return str(junction)
        through = "/proc/self/root" + str(directory)
        if os.path.isdir(through):
            return through
        if not SYMLINKS:
            self.skipTest("no second path to a directory on this system")
        link = self.root / "second-path"
        os.symlink(directory, link, target_is_directory=True)
        return str(link)

    def test_admit_decides_by_the_directory_and_not_by_its_text(self) -> None:
        work = self.home / "work"
        (work / "deep").mkdir(parents=True)
        second = self.second_path(work)
        found = os.stat(second)
        self.assertTrue(os.path.samestat(found, os.stat(work)))
        self.assertNotEqual(os.path.normcase(second), os.path.normcase(str(work)))
        # The directory as a run knows it by its other path: the text of
        # that path holds no place below ``work``, the directory does.
        other = fsio._Mark(str(work), second, found)
        home = fsio._mark(self.home)
        levels = fsio._BOUNDS.levels
        levels.append(fsio.Bounds(roots=(home,), barred=(other,)))
        try:
            for path in (work / "x", work / "deep" / "x", work / "new" / "deeper" / "x"):
                self.assertIn("never writes to", fsio.admits(path) or "", path)
            self.assertIsNone(fsio.admits(self.home / "x"))
        finally:
            levels.pop()
        levels.append(fsio.Bounds(roots=(other,), barred=()))
        try:
            self.assertIsNone(fsio.admits(work / "x"))
            self.assertIsNone(fsio.admits(work / "deep" / "x"))
            self.assertIn("outside the directories", fsio.admits(self.home / "x") or "")
        finally:
            levels.pop()

    def test_a_barred_directory_that_is_not_there_yet_bars_what_would_be_in_it(self) -> None:
        later = self.home / "later"
        with fsio.confined([self.home], [later]):
            for path in (later / "x", later / "a" / "b"):
                self.assertIn("never writes to", fsio.admits(path) or "", path)
            self.assertIsNone(fsio.admits(self.home / "x"))

    def test_only_a_temporary_of_setups_is_discarded(self) -> None:
        notes = self.put(self.home / "notes.txt", b"mine")
        almost = self.put(self.home / ".wfsetup-zz.tmp", b"mine")
        folder = self.home / "folder"
        folder.mkdir()
        with fsio.confined([self.home]):
            for path in (notes, almost):
                fsio._discard(str(path))
                self.assertFalse(fsio.discard_temporary(path))
            self.assertFalse(fsio.discard_temporary(folder))
            self.assertEqual(sorted(os.listdir(self.home)), [".wfsetup-zz.tmp", "folder", "notes.txt"])
            temporary = self.put(self.home / ".wfsetup-abcdabcd.tmp", b"x")
            self.assertTrue(fsio.discard_temporary(temporary))
            empty = self.home / ".wfsetup-abcd.tmp"
            empty.mkdir()
            self.assertTrue(fsio.discard_temporary(empty))
        self.assertEqual(sorted(os.listdir(self.home)), [".wfsetup-zz.tmp", "folder", "notes.txt"])

    def test_the_place_a_file_is_moved_to_is_asked_as_well(self) -> None:
        inside = self.put(self.home / "inside", b"1")
        with fsio.confined([self.home]):
            for change in (fsio._replace_entry, fsio._rename_entry, fsio._hard_link):
                with self.assertRaises(fsio.Refused):
                    change(inside, self.project / "outside")
        self.assertEqual(os.listdir(self.project), [])
        self.assertEqual(inside.read_bytes(), b"1")

    def test_a_record_lists_nothing_inside_a_state_directory(self) -> None:
        state = "home:.agents/workflow-setup"
        for key in (f"{state}/backups", f"{state}/backups/s1/home/x.md", f"{state}/lock"):
            self.put(self.manifest_file, json.dumps({"schema_version": 1, "entries": {key: {"kind": "directory"}}}))
            with self.assertRaises(SetupError) as caught:
                self.record()
            self.assertIn("setup's own state, which no record lists", caught.exception.lines[0], key)
        backup = {"path": f"{state}/manifest.json", "kind": "file", "sha256": "0" * 64, "mode": None, "stamp": "s1",
                  "backup": f"{state}/backups/s1/home/.agents/workflow-setup/manifest.json"}
        self.put(self.manifest_file, json.dumps({"schema_version": 1, "entries": {}, "backups": [backup]}))
        with self.assertRaises(SetupError) as caught:
            self.record()
        self.assertIn("setup's own state", caught.exception.lines[0])
        # The state directory itself is listed, as a directory setup created.
        self.put(self.manifest_file, json.dumps({"schema_version": 1, "entries": {state: {"kind": "directory"}}}))
        self.assertEqual(list(self.record().entries), [state])

    def test_a_lock_that_is_no_longer_this_runs_is_not_removed(self) -> None:
        with lock.held(self.roots) as mine:
            said = json.loads(mine.file.read_bytes())
            theirs = (json.dumps({**said, "pid": os.getppid(), "token": "f" * 16}) + "\n").encode()
            mine.file.write_bytes(theirs)             # another run's lock, in the place of this run's
            claim = mine.state / (lock.CLAIM_PREFIX + "0" * 16)
            claim.write_bytes(b"{}\n")                # and what that run has in the state directory
            file = mine.file
        self.assertEqual(file.read_bytes(), theirs)
        self.assertTrue(claim.is_file())

    def test_giving_back_a_second_time_does_not_remove_the_lock_another_run_took_since(self) -> None:
        # An interrupt between the removal of this run's lock and the end
        # of giving it back: the rest is done again, and by then another
        # run may hold the lock.
        self.put(self.manifest_file, json.dumps({"schema_version": 1, "entries": {}}))
        one = lock.Lock(self.roots)
        one.take()
        one._give_back()
        self.assertFalse(one.file.exists())
        theirs = b'{"pid": 1, "token": "ffffffffffffffff"}\n'
        one.file.write_bytes(theirs)
        one._give_back()
        self.assertEqual(one.file.read_bytes(), theirs)

    def test_a_claim_that_a_dead_clearer_left_goes_with_the_next_lock(self) -> None:
        self.state.mkdir(parents=True)
        claim = self.state / (lock.CLAIM_PREFIX + "0123456789abcdef")
        claim.write_bytes(b'{"pid": 1}\n')
        self.assertEqual(lock.leftovers(self.roots), [claim])
        with lock.held(self.roots):
            self.assertFalse(claim.exists())

    def test_a_stale_lock_without_a_token_is_never_cleared_and_says_what_to_do(self) -> None:
        self.state.mkdir(parents=True)
        said = {"schema_version": 1, "pid": gone_pid(), "start": "0", "identity": lock.identity(), "command": "x",
                "time": "2026-01-01 00:00:00 UTC"}
        raw = (json.dumps(said) + "\n").encode()
        (self.state / "lock").write_bytes(raw)
        with self.assertRaises(lock.LockHeld) as caught:
            with lock.held(self.roots):
                self.fail("a lock without a token was cleared")
        line = caught.exception.lines[0]
        self.assertIn("holds no token", line)
        self.assertIn("remove that file and run again", line)
        self.assertEqual((self.state / "lock").read_bytes(), raw)

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_the_real_place_of_the_lock_is_asked_before_anything_else(self) -> None:
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.home / ".agents").mkdir()
        os.symlink(elsewhere, self.home / ".agents" / "workflow-setup", target_is_directory=True)
        one = lock.Lock(self.roots, follow=True)      # the link itself is allowed; where it leads is not
        with one.confined():
            with self.assertRaises(SetupError) as caught:
                one.check_place()
        self.assertIn("outside the directories this run may write to", caught.exception.lines[0])
        self.assertEqual(os.listdir(elsewhere), [])

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_record_reached_through_a_link_is_not_removed_without_the_option(self) -> None:
        real = self.root / "real-home"
        real.mkdir()
        link = self.root / "home-link"
        os.symlink(real, link, target_is_directory=True)
        roots = Roots(link, None, self.clone)
        plan = fileops.Plan(roots, stamp=self.stamp(), follow_config_symlinks=True)
        plan.write_file(link / "generated.md", "x\n")
        plan.apply()
        fileops.plan_reversal(roots, stamp=self.stamp(), follow_config_symlinks=True).apply()
        record = real / ".agents" / "workflow-setup" / "manifest.json"
        self.assertTrue(record.is_file())
        with self.assertRaises(fileops.SymlinkedConfigPath):
            fileops.remove_state(roots)
        self.assertTrue(record.is_file())
        self.assertTrue(fileops.remove_state(roots, follow_config_symlinks=True))
        self.assertFalse((real / ".agents").exists())


# --- M1 to M4: fsio ---------------------------------------------------------------

class TemporaryNameTests(OpsCase):
    """M1: only the call that made a temporary removes it."""

    TOKEN = "abcd1234"

    def test_what_is_under_the_runs_own_temporary_name_is_not_removed(self) -> None:
        file_name, directory_name = fsio.temporary_names(self.TOKEN)
        precious = self.home / directory_name
        self.put(precious / "precious.txt", b"the user's\n")
        with fsio.confined([self.home]), fsio.named_temporaries(self.TOKEN):
            for make in (
                lambda: fsio.publish_directory(self.home / "new", lambda directory: None),
                lambda: fsio.make_directory(self.home / "new", 0o750) if POSIX else fsio.publish_directory(
                    self.home / "new", lambda directory: None),
            ):
                with self.assertRaises(SetupError) as caught:
                    make()
                self.assertEqual(len(caught.exception.lines), 1)
                self.assertIn("under the temporary name of this run, and setup did not make it", caught.exception.lines[0])
        self.assertEqual((precious / "precious.txt").read_bytes(), b"the user's\n")
        self.assertFalse((self.home / "new").exists())
        foreign = self.put(self.home / file_name, b"the user's file\n")
        with fsio.confined([self.home]), fsio.named_temporaries(self.TOKEN):
            for write in (
                lambda: fsio.atomic_write(self.home / "written", b"x"),
                lambda: fsio.write_new(self.home / "written", b"x"),
            ):
                with self.assertRaises(SetupError) as caught:
                    write()
                self.assertEqual(len(caught.exception.lines), 1)
                self.assertIn("setup did not make it", caught.exception.lines[0])
        self.assertEqual(foreign.read_bytes(), b"the user's file\n")
        self.assertFalse((self.home / "written").exists())

    def test_without_fixed_names_another_name_is_taken(self) -> None:
        taken = self.put(self.home / ".wfsetup-00000000.tmp", b"mine")
        free = self.home / ".wfsetup-11111111.tmp"
        with mock.patch.object(fsio, "_temporary_name", side_effect=[str(taken), str(free)]):
            with fsio.confined([self.home]):
                fsio.atomic_write(self.home / "written", b"data")
        self.assertEqual(taken.read_bytes(), b"mine")
        self.assertEqual((self.home / "written").read_bytes(), b"data")
        self.assertFalse(free.exists())
        held = self.home / ".wfsetup-0000.tmp"
        self.put(held / "x", b"mine")
        with mock.patch.object(fsio, "_temporary_name", side_effect=[str(held), str(self.home / ".wfsetup-1111.tmp")]):
            with fsio.confined([self.home]):
                fsio.publish_directory(self.home / "made", lambda directory: None)
        self.assertEqual((held / "x").read_bytes(), b"mine")
        self.assertTrue((self.home / "made").is_dir())
        self.assertEqual(fsio.temporaries(self.home), sorted([taken, held]))

    def test_a_call_still_removes_the_temporary_it_made(self) -> None:
        (self.home / "there").mkdir()
        with fsio.confined([self.home]):
            with self.assertRaises(fsio.AlreadyThere):
                fsio.publish_directory(self.home / "there", lambda directory: None)

            def fails(directory: Path) -> None:
                raise SetupError("the filling failed")

            with self.assertRaises(SetupError):
                fsio.publish_directory(self.home / "other", fails)
        self.assertEqual(sorted(os.listdir(self.home)), ["there"])


class PermissionBitsTests(OpsCase):
    """M2: permission bits are never set through a link."""

    @unittest.skipUnless(POSIX and SYMLINKS, "needs permission bits and a symlink")
    def test_a_link_is_refused_and_what_it_leads_to_keeps_its_bits(self) -> None:
        victim = self.put(self.root / "elsewhere" / "victim", b"v", 0o644)
        folder = self.root / "elsewhere" / "folder"
        folder.mkdir(mode=0o755)
        os.symlink(victim, self.home / "to-file")
        os.symlink(folder, self.home / "to-folder", target_is_directory=True)
        with fsio.confined([self.home]):
            for link in (self.home / "to-file", self.home / "to-folder"):
                with self.assertRaises(OSError):
                    fsio._chmod(link, 0o600)
            fsio.make_private(self.home / "to-folder")
        self.assertEqual(stat.S_IMODE(os.stat(victim).st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o755)

    @unittest.skipUnless(POSIX, "needs permission bits")
    def test_a_written_file_has_the_bits_asked_for_and_they_are_set_on_the_open_file(self) -> None:
        seen: list[tuple] = []
        real = os.fchmod

        def watched(handle: int, mode: int) -> None:
            seen.append((stat.S_ISREG(os.fstat(handle).st_mode), mode))
            real(handle, mode)

        with mock.patch.object(os, "fchmod", watched), mock.patch.object(os, "chmod", side_effect=AssertionError("by name")):
            with fsio.confined([self.home]):
                fsio.atomic_write(self.home / "f", b"x", 0o640)
        self.assertEqual(seen, [(True, 0o640)])
        self.assertEqual(stat.S_IMODE(os.stat(self.home / "f").st_mode), 0o640)
        self.assertEqual(os.listdir(self.home), ["f"])


class SecondLookTests(OpsCase):
    """M3: the limit is stated, and the one cheap check is made."""

    def test_a_directory_that_changed_under_a_write_fails_it_and_leaves_no_temporary(self) -> None:
        target = self.put(self.home / "f", b"as it was")
        another = os.stat(self.project)
        with mock.patch.object(fsio, "_directory_now", return_value=another), fsio.confined([self.home]):
            with self.assertRaises(SetupError) as caught:
                fsio.atomic_write(target, b"new")
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn("the directory changed while setup was writing into it", caught.exception.lines[0])
        self.assertEqual(os.listdir(self.home), ["f"])
        self.assertEqual(target.read_bytes(), b"as it was")

    @unittest.skipUnless(POSIX, "a file that is open is renamed")
    def test_a_name_that_no_longer_leads_to_the_file_just_made_fails_it_and_removes_nothing(self) -> None:
        real = fsio._create
        made: list[str] = []

        def swapped(path, mode):
            handle = real(path, mode)
            made.append(str(path))
            os.rename(path, str(path) + ".moved")           # another program moved it away, and put its own there
            Path(path).write_bytes(b"another program's")
            return handle

        with mock.patch.object(fsio, "_create", swapped), fsio.confined([self.home]):
            with self.assertRaises(SetupError) as caught:
                fsio.atomic_write(self.home / "f", b"new")
        self.assertIn("the directory changed while setup was writing into it", caught.exception.lines[0])
        self.assertFalse((self.home / "f").exists())
        # What is at the name now is not the file this call made: it is not removed.
        self.assertEqual(Path(made[0]).read_bytes(), b"another program's")

    def test_the_limit_is_written_down(self) -> None:
        text = flat(fsio.__doc__ or "")
        self.assertIn("the guards hold against the disk as the run finds it, and not against another program that "
                      "changes the same directories during the run", text)
        for command in ("render", "uninstall"):
            said = flat(support.run(command, "--help")[1])
            self.assertIn("hold against the disk as the run finds it, not against another program that changes the same "
                          "directories while the run is under way", said, command)

    def test_no_help_promises_to_handle_an_interrupt_before_the_script_starts(self) -> None:
        from wfsetup import cli

        self.assertIn("is Python's to report", flat(cli.__doc__ or ""))
        script = flat(support.SCRIPT.read_text(encoding="utf-8"))
        self.assertIn("Before the first statement of this file Python is still starting and none of this is in force", script)


class BoundsTests(OpsCase):
    """M4: the bounds are a thread's own, and an inner block only narrows."""

    def test_an_inner_block_never_reaches_what_the_outer_one_does_not(self) -> None:
        (self.home / "sub").mkdir()
        with fsio.confined([self.home]):
            with fsio.confined([self.root]):                         # wider
                self.assertIn("outside the directories", fsio.admits(self.project / "x") or "")
                self.assertIsNone(fsio.admits(self.home / "x"))
                with self.assertRaises(SetupError):
                    fsio.atomic_write(self.project / "x", b"1")
            with fsio.confined([self.project]):                      # elsewhere
                self.assertIsNotNone(fsio.admits(self.project / "x"))
                self.assertIsNotNone(fsio.admits(self.home / "x"))
            with fsio.confined([self.home / "sub"]):                 # narrower
                self.assertIsNone(fsio.admits(self.home / "sub" / "x"))
                self.assertIsNotNone(fsio.admits(self.home / "x"))
            self.assertIsNone(fsio.admits(self.home / "x"))
        with fsio.confined([self.root], [self.project]):
            with fsio.confined([self.root]):                         # what the outer bars stays barred
                self.assertIn("never writes to", fsio.admits(self.project / "x") or "")
        self.assertEqual(os.listdir(self.project), [])
        self.assertEqual(len(fsio._BOUNDS), 0)

    def test_a_thread_without_a_block_changes_nothing_under_anothers(self) -> None:
        saved, fsio._BASE = fsio._BASE, None                         # as in the tool: no base
        try:
            said: list[str | None] = []

            def other() -> None:
                said.append(fsio.admits(self.home / "x"))
                try:
                    fsio.atomic_write(self.home / "from-thread", b"x")
                    said.append("written")
                except SetupError as exc:
                    said.append(exc.lines[0])

            with fsio.confined([self.home]):
                thread = threading.Thread(target=other)
                thread.start()
                thread.join()
                self.assertIsNone(fsio.admits(self.home / "x"))
            self.assertEqual(len(said), 2)
            for line in said:
                self.assertIn("no place to write", line or "")
            self.assertEqual(os.listdir(self.home), [])
            # And a block another thread has open is not this thread's.
            inside, done = threading.Event(), threading.Event()

            def holder() -> None:
                with fsio.confined([self.project]):
                    inside.set()
                    done.wait(10)

            thread = threading.Thread(target=holder)
            thread.start()
            try:
                self.assertTrue(inside.wait(10))
                self.assertIn("no place to write", fsio.admits(self.project / "x") or "")
            finally:
                done.set()
                thread.join()
        finally:
            fsio._BASE = saved


# --- M5 to M7 ----------------------------------------------------------------------

class BackupsLinkTests(OpsCase):
    """M5: nothing is written through a backups directory that is a link."""

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_backups_directory_that_is_a_link_refuses_the_run(self) -> None:
        docs = self.home / "docs"
        docs.mkdir()
        file = self.put(self.home / ".claude" / "CLAUDE.md", b"# Mine\n")
        plan = self.plan()
        plan.edit_block(file, "ours\n")
        plan.apply()
        backups = self.state / "backups"
        shutil.rmtree(backups)
        os.symlink(docs, backups, target_is_directory=True)
        wrote = file.read_bytes()
        for follow in (False, True):
            plan = self.plan(follow_config_symlinks=follow)
            plan.edit_block(file, "other\n")
            before = self.snap()
            with self.assertRaises(fileops.PlanError) as caught:
                plan.apply()
            self.assertEqual(len(caught.exception.lines), 1)
            self.assertIn(f"{backups}: is a link", caught.exception.lines[0])
            self.assertIn("writes, reads and removes none through a link", caught.exception.lines[0])
            self.assertEqual(self.snap(), before)
        self.assertEqual(os.listdir(docs), [])
        self.assertEqual(file.read_bytes(), wrote)

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_no_backup_is_read_or_removed_through_a_link_below_the_backups_directory(self) -> None:
        file = self.put(self.home / ".claude" / "CLAUDE.md", b"# Mine\n")
        plan = self.plan()
        plan.write_file(self.home / "gen.md", "x\n")
        plan.remove_file(file)
        plan.apply()
        entry_ = self.record().get("home:.claude/CLAUDE.md")
        backup = self.record().path(entry_["original"]["backup"])
        stamp = backup.parents[2]                                    # backups/<stamp>
        moved = self.home / "docs"
        os.rename(stamp, moved)
        os.symlink(moved, stamp, target_is_directory=True)
        self.assertIsNotNone(fileops._backup_link(self.roots, False, backup))
        back = self.reversal().apply()
        self.assertEqual([key for key, _ in back.kept], ["home:.claude/CLAUDE.md"])     # not read through the link
        self.assertFalse(file.exists())
        fileops._remove_backups_of(self.roots, self.record().home)
        self.assertEqual((moved / "home" / ".claude" / "CLAUDE.md").read_bytes(), b"# Mine\n")   # nor removed through it


class MovedCloneTests(OpsCase):
    """M6: a link of the user's into the clone, removed by setup, is put
    back with the text it had."""

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_it_is_put_back_under_where_the_clone_was_or_kept_with_the_option_named(self) -> None:
        skill = self.put(self.clone / "s1" / "SKILL.md", "s\n").parent
        users = self.home / ".codex" / "skills" / "s1"
        users.parent.mkdir(parents=True)
        os.symlink(skill, users, target_is_directory=True)
        plan = self.plan()
        plan.remove_link(users)
        plan.create_link(self.home / ".claude" / "skills" / "s1", skill)
        plan.apply()
        self.assertEqual(self.record().get("home:.codex/skills/s1")["target"], "clone:s1")
        moved = self.root / "moved-clone"
        shutil.copytree(self.clone, moved)
        roots = Roots(self.home, self.project, moved)
        # From the moved clone, without the option: the text the link had cannot be known.
        result = fileops.plan_reversal(roots, stamp=self.stamp()).apply()
        kept = dict(result.kept)
        self.assertIn("--clone-was DIR", kept["home:.codex/skills/s1"])
        self.assertIn(str(self.clone), kept["home:.codex/skills/s1"])
        self.assertFalse(os.path.lexists(users))
        # With it: the link is the one the user had.
        roots = dataclasses.replace(roots, clone_was=self.clone)
        result = fileops.plan_reversal(roots, stamp=self.stamp()).apply()
        self.assertEqual(result.kept, [])
        self.assertEqual(fsio.read_link(users), str(skill))    # without the prefix Windows puts before a long path
        self.assertFalse(os.path.lexists(self.home / ".claude" / "skills" / "s1"))

    @unittest.skipUnless(SYMLINKS, "needs a symlink")
    def test_a_clone_that_did_not_move_needs_no_option(self) -> None:
        skill = self.put(self.clone / "s1" / "SKILL.md", "s\n").parent
        users = self.home / ".codex" / "skills" / "s1"
        users.parent.mkdir(parents=True)
        os.symlink(skill, users, target_is_directory=True)
        start = self.snap()
        plan = self.plan()
        plan.remove_link(users)
        plan.create_link(self.home / ".claude" / "skills" / "s1", skill)
        plan.apply()
        self.assertEqual(self.reversal().apply().kept, [])
        fileops.remove_state(self.roots)
        self.assertEqual(self.snap(), start)

    def test_the_help_says_it(self) -> None:
        said = flat(support.run("uninstall", "--help")[1])
        self.assertIn("a link of yours into the clone that the v1 migration removed is put back with the text it had, "
                      "into DIR", said)
        self.assertIn("Without the option such a link of yours is kept, not put back", said)


class ForeignStateTests(UninstallCase):
    """M7: a state directory that stays for something setup did not put
    there is not a finished uninstall."""

    def test_it_is_named_and_the_code_is_3_until_it_is_gone(self) -> None:
        self.done("init", "--user", "--yes", *self.at_home)
        note = self.data(self.state / "notes.txt", "mine\n")
        dry = self.uninstall("--dry-run", code=3)
        self.assertFalse(dry["state"]["would_remove"])
        self.assertIn("notes.txt", dry["state"]["why"])
        report = self.uninstall(code=3)
        self.assertFalse(report["state"]["removed"])
        self.assertIn("holds something setup did not put there (notes.txt)", report["state"]["why"])
        self.assertTrue(report["summary"].startswith("not finished: "))
        self.assertNothingAt(self.user_file)                 # everything else was undone
        # Again: no record now, and still not finished.
        again = self.uninstall(code=3)
        self.assertFalse(again["recorded"])
        self.assertIn("notes.txt", again["state"]["why"])
        self.assertTrue(again["summary"].startswith("not finished: "))
        out = self.done("uninstall", *self.at_home, code=3)
        self.assertIn("notes.txt", out)
        self.assertEqual(note.read_bytes(), b"mine\n")
        note.unlink()
        report = self.uninstall()
        self.assertNoState()
        self.assertNothingAt(self.home / ".agents")

    def test_the_help_names_the_code(self) -> None:
        said = flat(support.run("uninstall", "--help")[1])
        self.assertIn("or for something else in it that setup did not put there (the output names it)", said)


# --- M8: wording --------------------------------------------------------------------

class WordingTests(unittest.TestCase):
    COUNTS = (
        "create", "up_to_date", "remove", "forget", "kept", "file_write", "file_up_to_date", "file_remove", "edited",
        "default_write", "default_remove", "codex_settings_write", "codex_settings_remove", "skipped", "needs_flag",
        "conflict", "error",
    )

    def report(self, dry_run: bool) -> dict:
        return {
            "counts": {**dict.fromkeys(self.COUNTS, 0), "create": 3, "skipped": 2},
            "errors": [], "changed": True, "dry_run": dry_run,
            "plan": ["replace link home:a -> clone:a", "create link home:b -> clone:b", "    a detail",
                     "replace link home:c -> clone:c"],
        }

    def test_a_link_made_in_place_of_another_is_said_and_what_was_skipped_is_pointed_at(self) -> None:
        self.assertEqual(
            render._summary(self.report(True)),
            "dry run: would create 3 links (2 of them in place of a link that is there) and remove 0; nothing was "
            "written; 2 skipped (each is listed as skipped, with the reason)",
        )
        self.assertEqual(
            render._summary(self.report(False)),
            "done: 3 links created (2 of them in place of a link that was there), 0 removed; 2 skipped (each is listed "
            "as skipped, with the reason)",
        )
        plain = self.report(False)
        plain["plan"] = ["create link home:b -> clone:b"]
        plain["counts"]["skipped"] = 0
        self.assertEqual(render._summary(plain), "done: 3 links created, 0 removed")

    def test_a_block_whose_line_endings_were_converted_with_its_file_is_setups(self) -> None:
        block = blocks.render(blocks.MARKDOWN, "", "ours\nmore\n")
        wrote = fsio.sha256(block)
        lf = b"# Mine\n\n" + block
        crlf = lf.replace(b"\n", b"\r\n")
        self.assertTrue(blocks.as_written(lf, block, wrote))
        self.assertTrue(blocks.as_written(crlf, blocks.get(crlf, blocks.MARKDOWN), wrote))
        back = fsio.sha256(block.replace(b"\n", b"\r\n"))                     # written with CRLF, converted to LF
        self.assertTrue(blocks.as_written(lf, block, back))
        # Only the block's endings changed, or only one line's: someone edited it.
        mixed = b"# Mine\n\nText.\nMore.\nAnd more.\nAnd more.\nAnd more.\n" + block.replace(b"\n", b"\r\n")
        self.assertFalse(blocks.as_written(mixed, blocks.get(mixed, blocks.MARKDOWN), wrote))
        one = crlf.replace(b"ours\r\n", b"ours\n")
        self.assertFalse(blocks.as_written(one, blocks.get(one, blocks.MARKDOWN), wrote))
        other = crlf.replace(b"ours", b"theirs")
        self.assertFalse(blocks.as_written(other, blocks.get(other, blocks.MARKDOWN), wrote))
        self.assertFalse(blocks.as_written(lf, None, wrote))


class ConvertedFileTests(OpsCase):
    def test_the_way_back_and_the_next_run_agree_that_the_block_is_setups(self) -> None:
        file = self.put(self.home / ".claude" / "CLAUDE.md", b"# Mine\n\nText.\n")
        plan = self.plan()
        plan.edit_block(file, "ours\nmore\n")
        plan.apply()
        file.write_bytes(file.read_bytes().replace(b"\n", b"\r\n"))        # the whole file, by an editor or by git
        converted = file.read_bytes()
        # The next run takes the block for its own: nothing to write, and no conflict.
        plan = self.plan()
        plan.edit_block(file, "ours\nmore\n")
        self.assertEqual(plan.describe().edited, [])
        self.assertEqual(file.read_bytes(), converted)
        # And so does the way back, which called it edited before.
        back = self.reversal().apply()
        self.assertEqual(back.kept, [])
        self.assertEqual(file.read_bytes(), b"# Mine\r\n\r\nText.\r\n")
        self.assertTrue(fileops.remove_state(self.roots))

    def test_a_block_that_was_really_edited_is_still_kept(self) -> None:
        file = self.put(self.home / ".claude" / "CLAUDE.md", b"# Mine\n\nText.\n")
        plan = self.plan()
        plan.edit_block(file, "ours\nmore\n")
        plan.apply()
        file.write_bytes(file.read_bytes().replace(b"\n", b"\r\n").replace(b"ours", b"mine"))
        self.assertEqual([key for key, _ in self.reversal().apply().kept], ["home:.claude/CLAUDE.md"])


@unittest.skipUnless(SYMLINKS, "needs a symlink")
class LinkWordingTests(MigrateCase):
    def test_a_link_to_another_homes_entry_is_not_called_a_link_into_the_clone(self) -> None:
        theirs = self.root / "other-home" / ".claude" / "skills" / "self-reflection"
        theirs.parent.mkdir(parents=True)
        os.symlink(self.clone / "self-reflection", theirs, target_is_directory=True)
        self.claude_skills.mkdir(parents=True)
        mine = self.claude_skills / "self-reflection"
        os.symlink(theirs, mine, target_is_directory=True)
        direct = self.claude_skills / "json-tools"
        os.symlink(self.clone / "json-tools", direct, target_is_directory=True)
        code, report, err = self.migrated("--dry-run")
        self.assertEqual(err, "")
        said = self.said(report, mine)["says"]
        self.assertIn("as a link to another place that itself leads into the clone setup runs from", said)
        self.assertNotIn("as a link into the clone setup runs from", said)
        self.assertIn("as a link into the clone setup runs from, which setup did not make", self.said(report, direct)["says"])

    def test_what_an_interrupted_run_left_is_not_said_to_be_a_removal(self) -> None:
        # ``test_review_p5.ResumeTests`` holds the sentence as a command
        # prints it; here, that it no longer says which of the two it was.
        import inspect

        from wfsetup import migrate

        text = flat(inspect.getsource(migrate._skill_directory))
        self.assertIn("which it was removing or putting back", text)
        self.assertNotIn("that an interrupted run of setup was removing", text)


class LoadedSizeAfterNoRolesTests(DoctorCase):
    def test_a_home_rendered_without_roles_has_nothing_to_measure(self) -> None:
        code, out, err = support.run("render", "--no-roles", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        limit_loaded_skills(self, "claude-code", 100)
        code, findings = self.only("loaded-skill-size")
        self.assertEqual(code, 0)
        self.assertEqual(self.details(findings, doctor.WARNING), [])
        (detail,) = self.details(findings, doctor.INFO)
        self.assertIn("rendered with --no-roles", detail)

    def test_a_home_rendered_with_roles_is_still_warned(self) -> None:
        code, out, err = support.run("render", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)
        limit_loaded_skills(self, "claude-code", 100)
        code, findings = self.only("loaded-skill-size")
        # Two loaded roles, on Claude Code: Codex has no limit.
        self.assertEqual(len(self.details(findings, doctor.WARNING)), 2)


if __name__ == "__main__":
    unittest.main()
