"""Tests for what native Windows changes: how paths are compared, junctions
through the real commands, the other side seen from Windows, and the bytes
setup writes and prints.

Most of these run on both systems and hold the opposite on each: letter
case counts in a path on POSIX and does not on Windows. The junction tests
run under a Windows Python only; every scratch tree is in the temporary
directory, which on Windows is on a local drive, where a junction can lead.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import support
from fileops_support import SYMLINKS, OpsCase
from test_doctor import DoctorCase
from test_homes import HomesCase
from test_render import LINKS, RenderCase, tree
from test_uninstall import UninstallCase, picture
from test_validate import SKILL
from wfsetup import doctor, fileops, fsio, homes, locations, manifest, paths, render
from wfsetup.errors import SetupError
from wfsetup.locations import Locations

WINDOWS = os.name == "nt"
WSL_SHARE = "\\\\wsl.localhost\\NoSuchDistro\\home\\someone"   # no distribution of that name: nothing is asked of WSL
PACKAGE = support.SETUP / "wfsetup"


def other_case(path: Path | str) -> str:
    """The same path in other letters: every letter's case swapped, the
    drive letter with it."""
    text = os.fspath(path)
    swapped = text.swapcase()
    assert swapped != text, text
    return swapped


def short_form(path: Path | str) -> str:
    """The 8.3 short form of a path that exists (Windows only); the path
    itself where the volume keeps no short names."""
    import ctypes

    ask = ctypes.windll.kernel32.GetShortPathNameW
    ask.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    ask.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(1024)
    return buffer.value if 0 < ask(os.fspath(path), buffer, 1024) < 1024 else os.fspath(path)


def uninstall(case: RenderCase, *argv: str, home: Path | str | None = None) -> tuple[int, dict, str]:
    with mock.patch.object(homes.Host, "current", classmethod(lambda cls: case.host)):
        code, out, err = support.run("uninstall", "--json", *argv, "--home", str(home or case.home))
    return code, json.loads(out) if out.startswith("{") else {}, err


# --- One rule for comparing paths ---------------------------------------------

class FoldCase(unittest.TestCase):
    ONE, OTHER = ("Q:\\Users\\Someone\\Clone", "q:\\users\\SOMEONE\\clone") if WINDOWS else (
        "/home/Someone/Clone", "/home/someone/clone")

    def test_letter_case_counts_on_posix_and_not_on_windows(self) -> None:
        self.assertEqual(paths.CASE_SENSITIVE, not WINDOWS)
        self.assertEqual(paths.same(self.ONE, self.OTHER), WINDOWS)
        self.assertEqual(paths.fold(self.ONE) == paths.fold(self.OTHER), WINDOWS)
        self.assertEqual(paths.inside(self.OTHER + os.sep + "json-tools", self.ONE), WINDOWS)
        self.assertEqual(fsio.same_target(self.ONE, self.OTHER), WINDOWS)
        self.assertEqual(paths.fold_key("home:.Claude/Skills") == paths.fold_key("home:.claude/skills"), WINDOWS)
        self.assertEqual(Path(self.ONE) == Path(self.OTHER), WINDOWS)   # what ``pathlib`` itself says

    def test_the_same_text_is_the_same_on_both(self) -> None:
        self.assertTrue(paths.same(self.ONE, Path(self.ONE)))
        self.assertTrue(paths.inside(self.ONE, self.ONE))
        self.assertTrue(paths.inside(Path(self.ONE) / "a" / "b", self.ONE))
        self.assertTrue(paths.inside(Path(self.ONE) / "a", self.ONE + os.sep))
        self.assertFalse(paths.inside(self.ONE + "-2", self.ONE))    # a name that only starts the same
        self.assertFalse(paths.inside(Path(self.ONE).parent, self.ONE))
        self.assertEqual(paths.fold_key("home:.claude/skills"), "home:.claude/skills")

    @unittest.skipUnless(WINDOWS, "the two separators of Windows")
    def test_on_windows_either_separator_is_the_same_path(self) -> None:
        self.assertTrue(paths.same("Q:/Users/Someone", "q:\\users\\someone"))
        self.assertTrue(fsio.same_target("\\\\?\\Q:\\Users\\Someone\\", "q:/users/someone"))
        self.assertTrue(paths.inside("q:/users/someone/x", "Q:\\Users\\Someone"))

    def test_no_module_folds_a_path_on_its_own(self) -> None:
        # One shared helper: ``paths`` is the only module that asks the
        # system how it compares paths, or lowers one for the sake of Windows.
        alone = re.compile(r"normcase\(|\.lower\(\) if os\.name|os\.name == \"nt\" and [^\n]*\.lower\(\)")
        found = [
            f"{file.relative_to(PACKAGE).as_posix()}:{number}"
            for file in sorted(PACKAGE.rglob("*.py")) if file.name != "paths.py"
            for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1) if alone.search(line)
        ]
        self.assertEqual(found, [])

    def test_a_long_form_is_the_text_itself_where_nothing_is_short(self) -> None:
        for text in (self.ONE, "relative/part", "with~tilde/that/is/not/there", ""):
            self.assertEqual(paths.long_form(text), text)
        self.assertEqual(paths.absolute(self.ONE), Path(os.path.abspath(self.ONE)))


class RecordCaseCase(OpsCase):
    """A record written with one letter case, asked with another."""

    def test_the_key_of_a_path_in_another_case(self) -> None:
        made = self.home / ".claude" / "agents" / "Made.md"
        plan = self.plan()
        plan.write_file(made, "made\n")
        plan.apply()
        self.assertEqual(self.roots.key(made), "home:.claude/agents/Made.md")
        # The whole path in other letters, the drive letter with them.
        asked = self.roots.key(other_case(made))
        entry = None if asked is None else self.record().get(asked)
        if WINDOWS:
            self.assertEqual(asked, "home:" + other_case(".claude/agents/Made.md"))
            self.assertEqual(entry["kind"], "file")
            self.assertEqual(self.roots.path(asked), made)   # the same file to Windows
            self.assertTrue(self.roots.is_state(other_case(self.manifest_file)))
        else:
            self.assertIsNone(asked)                         # another directory altogether
            self.assertFalse(self.roots.is_state(other_case(self.manifest_file)))
        # The same root, the name in other letters.
        again = self.roots.key(self.home / ".CLAUDE" / "Agents" / "made.MD")
        self.assertEqual(again, "home:.CLAUDE/Agents/made.MD")
        self.assertEqual(self.record().get(again) is not None, WINDOWS)

    def test_a_second_plan_in_another_case_meets_the_first_ones_file(self) -> None:
        made = self.home / ".claude" / "agents" / "Made.md"
        first = self.plan()
        first.write_file(made, "made\n")
        first.apply()
        other = self.home / ".CLAUDE" / "AGENTS" / "MADE.MD"
        second = self.plan()
        second.write_file(other, "made\n")
        changed = second.apply().changed
        entries = [key for key in self.record().entries if key.lower() == "home:.claude/agents/made.md"]
        if WINDOWS:
            self.assertFalse(changed)                        # setup's own file, as it left it
            self.assertEqual(entries, ["home:.claude/agents/Made.md"])
            self.assertEqual(sorted(os.listdir(made.parent)), ["Made.md"])
        else:
            self.assertTrue(changed)                         # a second file, in a second directory
            self.assertEqual(len(entries), 2)
            self.assertTrue(other.is_file() and made.is_file())
        self.reversal().apply()
        self.assertFalse(made.exists() or other.exists())

    def test_two_planned_paths_that_differ_in_case_only(self) -> None:
        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "one.md", "a\n")
        plan.write_file(self.home / ".claude" / "AGENTS" / "ONE.md", "b\n")
        if WINDOWS:
            self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})   # one file, planned twice
        else:
            self.assertTrue(plan.apply().changed)

    def test_the_lookup_in_a_record_file(self) -> None:
        record = manifest.Manifest(self.manifest_file)
        record.entries["home:.claude/skills/Alpha"] = {"kind": "link", "target": "clone:alpha"}
        self.assertEqual(record.find("home:.claude/skills/Alpha"), "home:.claude/skills/Alpha")
        self.assertEqual(record.find("home:.CLAUDE/skills/alpha"), "home:.claude/skills/Alpha" if WINDOWS else None)
        record.commit({"set": True, "path": "home:.Claude/Skills/ALPHA", "entry": None})
        self.assertEqual(list(record.entries), [] if WINDOWS else ["home:.claude/skills/Alpha"])


@unittest.skipUnless(LINKS, "needs links to directories")
class LinkCaseCase(RenderCase):
    """Setup's link, the record and the command line, each in its own
    letter case."""

    def test_setups_link_with_its_target_in_other_letters(self) -> None:
        self.assertEqual(self.render()[0], 0)
        link = self.claude_skills / "alpha"
        fsio.remove_link(link)
        retyped = other_case(self.clone / "alpha")
        if WINDOWS:
            fsio.make_link(retyped, link, True)
            self.assertEqual(fsio.read_link(link), retyped)   # the text is kept as it was typed
        else:
            os.symlink(retyped, link)
        code, report, err = self.report()
        if WINDOWS:
            self.assertEqual((code, err, report["plan"]), (0, "", []))
            self.assertEqual(self.items(report, "claude-code", "skills")["alpha"], render.UP_TO_DATE)
            code, _, err = uninstall(self)
            self.assertEqual((code, err), (0, ""))
            self.assertNothingAt(link)
        else:
            self.assertEqual(code, 2)
            self.assertIn("it was changed since", err)

    def test_the_home_named_in_other_letters(self) -> None:
        self.assertEqual(self.render()[0], 0)
        before = tree(self.root)
        retyped = other_case(self.home)
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, out, err = support.run("render", "--json", "--no-roles", "--home", retyped)
        if not WINDOWS:
            self.assertEqual((code, out), (2, ""))
            self.assertIn("--home: ", err)
            self.assertIn("not a directory", err)
            return
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((json.loads(out)["plan"], tree(self.root)), ([], before))
        code, report, err = uninstall(self, home=retyped)
        self.assertEqual((code, err, report["kept"]), (0, "", []))
        self.assertNothingAt(self.claude_skills / "alpha")
        self.assertNothingAt(self.manifest_file)
        self.assertTrue((self.clone / "alpha" / "SKILL.md").is_file())

    def test_the_clone_named_in_other_letters(self) -> None:
        self.assertEqual(self.render()[0], 0)
        before = tree(self.root)
        with mock.patch.object(locations, "CLONE", Path(other_case(self.clone))):
            code, out, err = self.render("--json")
        if WINDOWS:
            # The links the first run made are this run's too.
            self.assertEqual((code, err, json.loads(out)["plan"]), (0, "", []))
            self.assertEqual(tree(self.root), before)
        else:
            self.assertEqual(code, 2)                        # no such clone
            self.assertEqual(tree(self.root), before)

    def test_where_the_clone_was_named_in_other_letters(self) -> None:
        self.assertEqual(self.render()[0], 0)
        was, moved = self.clone, self.root / "moved-clone"
        os.rename(was, moved)
        with mock.patch.object(locations, "CLONE", moved):
            code, report, _ = uninstall(self)
            self.assertEqual(code, 3)
            self.assertTrue(report["kept"])
            self.assertTrue(any(f"--clone-was {was}" in item["finish"] for item in report["kept"]), report["kept"])
            code, report, err = uninstall(self, "--clone-was", other_case(was))
        if WINDOWS:
            self.assertEqual((code, err, report["kept"]), (0, "", []))
            self.assertNothingAt(self.claude_skills / "alpha")
        else:
            self.assertEqual(code, 3)                        # not the directory the links name
            self.assertEqual(fsio.look(self.claude_skills / "alpha").kind, fsio.LINK)
            with mock.patch.object(locations, "CLONE", moved):
                self.assertEqual(uninstall(self, "--clone-was", str(was))[0], 0)
        self.assertTrue((moved / "alpha" / "SKILL.md").is_file())

    def test_a_record_whose_keys_are_in_other_letters(self) -> None:
        # The stale sweep and the conflict check both ask the record by key.
        self.assertEqual(self.render()[0], 0)
        record = json.loads(self.manifest_file.read_bytes())
        record["entries"] = {
            (key.replace("skills/alpha", "SKILLS/Alpha") if key.endswith("skills/alpha") else key): entry
            for key, entry in record["entries"].items()
        }
        self.manifest_file.write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))
        before = tree(self.claude_skills)
        code, report, err = self.report()
        if WINDOWS:
            self.assertEqual((code, err, report["plan"]), (0, "", []))
            self.assertEqual(tree(self.claude_skills), before)
        else:
            # Another path to POSIX: the link at ``skills/alpha`` is one
            # setup has no record of, and the run stops.
            self.assertEqual(code, 2)
            self.assertIn("setup did not make it", err)

    def test_the_collaboration_skill_by_its_name_in_other_letters(self) -> None:
        mine = self.keep(self.claude_skills / "Multiagent-Collab" / "SKILL.md")
        entry = homes.Classifier(homes.resolve(Locations(home=self.home, clone=self.clone), self.host)).entry(mine.parent)
        self.assertEqual(entry.kind, homes.OWN_SETUP if WINDOWS else homes.PLAIN)
        code, _, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(mine.read_text(encoding="utf-8"), "the user's own text\n")


class StaleCaseCase(UninstallCase):
    def test_a_stale_location_named_in_other_letters(self) -> None:
        if not LINKS:
            self.skipTest("needs links to directories")
        before = self.start()
        retyped = [part for path in self.edited_copies for part in ("--remove-stale", other_case(path))]
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home)
        code, out, err = self.cli("render", "--migrate-v1", *retyped, *self.at_home)
        if not WINDOWS:
            self.assertEqual(code, 2, out)
            self.assertIn("--remove-stale", err)
            return
        self.assertEqual((code, err), (0, ""), out[-800:])
        for path in self.edited_copies:
            self.assertNotEqual(fsio.look(path).kind, fsio.DIRECTORY, path)   # removed, after a backup
        self.take_back(project=False)
        self.assertAsAtTheStart(before)


class CloneCheckCase(HomesCase):
    """The clone check as Windows makes it (R6.9)."""

    def at(self, clone: Path | str, real: str | None = None) -> homes.CloneStanding:
        found = homes.resolve(Locations(home=self.home, clone=Path(clone), real_home=True), self.host(homes.WINDOWS))
        if real is None:
            return homes.clone_standing(found)
        with mock.patch.object(os.path, "realpath", return_value=real):
            return homes.clone_standing(found)

    def test_a_drive_letter_in_either_case_is_a_local_drive(self) -> None:
        for real in ("Q:\\work\\clone", "q:\\work\\clone", "\\\\?\\Q:\\work\\clone"):
            found = self.at(self.clone, real)
            self.assertIs(found.shared, True, real)
            self.assertIn("on a local drive", found.why)

    def test_a_network_name_is_refused(self) -> None:
        # ``realpath`` turns a mapped network drive into its UNC name.
        for real, why in (
            ("\\\\server\\share\\clone", "not on a local drive"),
            ("\\\\?\\UNC\\server\\share\\clone", "not on a local drive"),
            (WSL_SHARE + "\\clone", "inside WSL"),
            ("\\\\WSL$\\Distro\\home\\clone", "inside WSL"),
        ):
            found = self.at(self.clone, real)
            self.assertIs(found.shared, False, real)
            self.assertIn(why, found.why)

    @unittest.skipUnless(WINDOWS, "a Windows path is made absolute by Windows rules")
    def test_on_windows_the_scratch_clone_is_on_a_local_drive_whatever_the_case(self) -> None:
        self.assertIs(self.at(self.clone).shared, True)
        self.assertIs(self.at(other_case(self.clone)).shared, True)

    @unittest.skipUnless(WINDOWS, "a Windows path is made absolute by Windows rules")
    def test_on_windows_a_clone_inside_wsl_is_refused_and_the_flag_allows_it(self) -> None:
        found = homes.resolve(
            Locations(home=self.home, clone=Path(WSL_SHARE, "clone"), real_home=True), homes.Host.current())
        self.assertIs(homes.clone_standing(found).shared, False)
        with self.assertRaises(SetupError) as caught:
            homes.require_shared_clone(found)
        text = str(caught.exception)
        self.assertIn("inside WSL, reached over the network name; a junction cannot lead there", text)
        self.assertIn("--allow-unshared-clone", text)
        self.assertIs(homes.require_shared_clone(found, allow_unshared=True).shared, False)

    def test_doctor_gives_the_same_verdict(self) -> None:
        def verdict(real: str, allow: bool = False) -> doctor.Finding:
            where = Locations(home=self.home, clone=self.clone, real_home=True)
            host = homes.Host(homes.WINDOWS, {"PATH": ""}, ())
            context = doctor.Context(where, argparse.Namespace(allow_unshared_clone=allow), host)
            with mock.patch.object(os.path, "realpath", return_value=real):
                (found,) = doctor.check_clone(context)
            return found

        self.assertEqual(verdict("q:\\work\\clone").severity, doctor.OK)
        found = verdict(WSL_SHARE + "\\clone")
        self.assertEqual(found.severity, doctor.ERROR)
        self.assertIn("inside WSL", found.detail)
        self.assertEqual(verdict("\\\\server\\share\\clone", allow=True).severity, doctor.WARNING)


# --- The other side, seen from Windows ----------------------------------------

@unittest.skipUnless(WINDOWS, "a path under \\\\wsl.localhost\\ is a path only to Windows")
class WslSeenFromWindowsCase(RenderCase):
    """The counterpart of ``test_homes.TwoSidesCase``: what is inside WSL
    is the other side's, and this run writes none of it."""

    def found(self, **environ: str) -> homes.Homes:
        host = homes.Host(homes.WINDOWS, {"PATH": "", **environ}, ())
        return homes.resolve(Locations(home=self.home, clone=self.clone, real_home=True), host)

    def test_a_home_named_inside_wsl_is_the_other_sides(self) -> None:
        for share in (WSL_SHARE, "\\\\wsl$\\NoSuchDistro\\home\\someone"):
            found = self.found(CODEX_HOME=share + "\\.codex")
            sorter = homes.Classifier(found)
            codex = found.provider(homes.CODEX)
            self.assertEqual(codex.anchor, "codex-home")
            for name in ("agents", "instructions", "config"):
                standing = sorter.standing(codex.place(name).path)
                self.assertEqual((standing.kind, standing.side, standing.writes), (homes.OTHER_SIDE, homes.WSL, False), name)
                self.assertIn("the wsl side owns it", standing.describe())
            # Codex's user skills stay in the user's own home, on this side.
            self.assertEqual(sorter.standing(codex.place("skills").path).kind, homes.THIS_SIDE)
            self.assertEqual(sorter.standing(found.provider(homes.CLAUDE_CODE).place("skills").path).kind, homes.THIS_SIDE)

    @unittest.skipUnless(SYMLINKS, "a link into WSL is a symlink, and this user may make none")
    def test_a_link_into_wsl_is_the_other_sides_and_render_writes_nothing_there(self) -> None:
        theirs = WSL_SHARE + "\\.claude"
        os.symlink(theirs + "\\rules", self.rules, target_is_directory=True)
        self.claude_skills.mkdir()
        os.symlink(theirs + "\\skills\\solo", self.claude_skills / "solo", target_is_directory=True)
        sorter = homes.Classifier(self.found())
        standing = sorter.standing(self.rules / "sample")
        self.assertEqual((standing.kind, standing.side, standing.link), (homes.OTHER_SIDE, homes.WSL, self.rules))
        entry = sorter.entry(self.claude_skills / "solo")
        self.assertEqual((entry.kind, entry.side), (homes.LINK_OTHER_SIDE, homes.WSL))

        code, out, err = self.render()
        self.assertEqual(code, 2, out)   # the link at ``solo`` is in the way, and is the user's
        self.assertIn("a link to the other side (wsl)", err)
        self.assertIn("    skipped: other side (wsl): a link to ", out)
        os.rmdir(self.claude_skills / "solo")
        for more in ((), ("--follow-config-symlinks",)):
            code, out, err = self.render(*more)
            self.assertEqual(err, "")
            self.assertIn("    skipped: other side (wsl): a link to ", out)
            self.assertIn("the wsl side owns it", out)
        self.assertTrue(os.path.islink(self.rules))
        self.assertEqual(fsio.read_link(self.rules), theirs + "\\rules")
        self.assertFalse(any(key.startswith("home:.claude/rules") for key in fileops.read_record(self.roots()).entries))
        self.assertTrue(fsio.is_junction(self.claude_skills / "alpha"))   # this side's part was done

    @unittest.skipUnless(SYMLINKS, "a link into WSL is a symlink, and this user may make none")
    def test_uninstall_writes_nothing_where_a_recorded_path_now_leads_into_wsl(self) -> None:
        self.assertEqual(self.render()[0], 0)
        fsio.remove_link(self.rules / "sample")
        self.rules.rmdir()
        os.symlink(WSL_SHARE + "\\.claude\\rules", self.rules, target_is_directory=True)
        code, report, _ = uninstall(self)
        self.assertEqual(code, 3, report)
        whys = [item["why"] for item in report["kept"] if "rules" in item["key"]]
        self.assertTrue(whys)
        for why in whys:
            self.assertIn("is on the other side (wsl); this side writes nothing there", why)
        self.assertEqual(fsio.read_link(self.rules), WSL_SHARE + "\\.claude\\rules")
        self.assertNothingAt(self.claude_skills / "alpha")   # the rest was taken back

    def test_a_junction_that_leads_out_of_the_home_is_skipped_with_and_without_the_flag(self) -> None:
        elsewhere = self.root / "another-home" / "rules"
        elsewhere.mkdir(parents=True)
        (elsewhere / "theirs.md").write_bytes(b"theirs\n")
        fsio.make_junction(str(elsewhere), self.rules)
        before = tree(self.root / "another-home")
        for more in ((), ("--dry-run",), ("--follow-config-symlinks", "--dry-run"), ("--follow-config-symlinks",)):
            code, out, err = self.render(*more)
            # No option makes a run write there, so the code asks for none.
            self.assertEqual((code, err), (0, ""), out)
            self.assertEqual(tree(self.root / "another-home"), before)
            self.assertIn("which leads out of the directories this run may write to: skipped, whatever the options", out)
            self.assertNotIn("needs --follow-config-symlinks", out)
            self.assertTrue(fsio.is_junction(self.rules))
        self.assertFalse(any(key.startswith("home:.claude/rules") for key in fileops.read_record(self.roots()).entries))
        self.assertTrue(fsio.is_junction(self.claude_skills / "alpha"))   # the rest of the run was done

    def test_a_config_path_under_a_junction_is_refused_without_the_flag(self) -> None:
        elsewhere = self.home / "dotfiles" / "rules"   # in the home, where a run may write
        elsewhere.mkdir(parents=True)
        fsio.make_junction(str(elsewhere), self.rules)
        found = self.found()
        standing = homes.Classifier(found).standing(self.rules / "mine.md")
        self.assertEqual((standing.kind, standing.through_link), (homes.SHARED, True))
        plan = fileops.Plan(found.roots(), stamp="20260101T000001000000Z")
        plan.write_file(self.rules / "mine.md", "x\n")
        with self.assertRaises(fileops.SymlinkedConfigPath) as caught:
            plan.apply()
        self.assertIn("--follow-config-symlinks", str(caught.exception))
        self.assertEqual(os.listdir(elsewhere), [])
        code, out, err = self.render()
        self.assertEqual((code, err), (3, ""), out)
        self.assertEqual(os.listdir(elsewhere), [])
        code, _, err = self.render("--follow-config-symlinks")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(fsio.is_junction(elsewhere / "sample"))   # written once, where the junction leads
        self.assertTrue(fsio.is_junction(self.rules))


@unittest.skipUnless(WINDOWS, "junctions are made on Windows")
class EntriesOnWindowsCase(HomesCase):
    """The counterpart of ``TwoSidesCase``'s entries, made of junctions."""

    def setUp(self) -> None:
        super().setUp()
        self.skills = self.home / ".claude" / "skills"
        self.skills.mkdir(parents=True)
        self.put(self.clone / "json-tools" / "SKILL.md", "a skill\n")
        self.elsewhere = self.root / "dev" / "multiagent-collab"
        self.put(self.elsewhere / "SKILL.md", "theirs\n")

    def sorter(self) -> homes.Classifier:
        return homes.Classifier(self.found(homes.Host(homes.WINDOWS, {}, ())))

    def test_each_kind_of_entry(self) -> None:
        sorter = self.sorter()
        self.assertEqual(sorter.entry(self.skills / "json-tools").kind, homes.ABSENT)
        fsio.make_junction(str(self.clone / "json-tools"), self.skills / "json-tools")
        fsio.make_junction(other_case(self.clone / "json-tools"), self.skills / "retyped")
        fsio.make_junction(str(self.elsewhere), self.skills / "elsewhere")
        fsio.make_junction(str(self.elsewhere), self.skills / "multiagent-collab")
        gone = self.root / "gone"
        gone.mkdir()
        fsio.make_junction(str(gone), self.skills / "broken")
        gone.rmdir()
        self.put(self.skills / "copy" / "SKILL.md", "a copy\n")
        kinds = {name: sorter.entry(self.skills / name).kind for name in sorted(os.listdir(self.skills))}
        self.assertEqual(kinds, {
            "broken": homes.LINK_BROKEN, "copy": homes.PLAIN, "elsewhere": homes.LINK_THIS_SIDE,
            "json-tools": homes.LINK_TO_CLONE, "multiagent-collab": homes.OWN_SETUP, "retyped": homes.LINK_TO_CLONE,
        })
        broken = fsio.look(self.skills / "broken")
        self.assertEqual((broken.kind, broken.directory, broken.junction), (fsio.LINK, False, True))
        self.assertTrue(fsio.same_target(broken.target, str(gone)))

    def test_two_names_for_one_directory_are_handled_once(self) -> None:
        claude, codex = self.home / ".claude" / "agents", self.home / ".codex" / "agents"
        claude.mkdir()
        codex.parent.mkdir()
        fsio.make_junction(other_case(claude), codex)
        sorter = self.sorter()
        self.assertEqual(sorter.standing(claude).kind, homes.THIS_SIDE)
        second = sorter.standing(codex)
        self.assertEqual((second.kind, second.first, second.writes), (homes.HANDLED, claude, False))
        self.assertEqual(sorter.standing(Path(other_case(claude))).kind, homes.THIS_SIDE)   # the first name, retyped
        self.assertEqual(sorter.standing(codex / "coder.toml").kind, homes.SHARED)


# --- Short names ---------------------------------------------------------------

@unittest.skipUnless(WINDOWS, "8.3 short names are a Windows matter")
class ShortNameCase(RenderCase):
    """``%TEMP%`` often arrives as ``C:\\Users\\SOMEON~1\\...``: a home given
    in the short form and a link's target read back in the long one are the
    same place."""

    def setUp(self) -> None:
        super().setUp()
        self.long_home = self.root / "a home with a long name"
        (self.long_home / ".claude").mkdir(parents=True)
        (self.long_home / ".codex").mkdir()
        self.short_home = short_form(self.long_home)
        self.short_clone = short_form(self.clone)
        if "~" not in self.short_home or "~" not in self.short_clone:
            self.skipTest("this volume keeps no 8.3 short names")
        self.home = self.long_home
        self.claude_skills = self.long_home / ".claude" / "skills"

    def test_the_long_form_of_a_short_path(self) -> None:
        self.assertNotEqual(self.short_home, str(self.long_home))
        self.assertEqual(paths.long_form(self.short_home), str(self.long_home))
        self.assertEqual(paths.long_form(self.short_home + "\\not\\there~1"), str(self.long_home / "not" / "there~1"))
        self.assertEqual(paths.absolute(self.short_home + "\\.claude\\..\\.codex"), self.long_home / ".codex")
        self.assertEqual(paths.long_form(str(self.long_home)), str(self.long_home))
        self.assertTrue(fsio.same_target(self.short_clone + "\\alpha", other_case(self.clone / "alpha")))
        self.assertFalse(fsio.same_target(self.short_clone + "\\alpha", str(self.clone / "beta")))
        # No link is followed for it: a junction keeps its own name.
        fsio.make_junction(str(self.clone), self.root / "a junction to the clone")
        self.assertEqual(
            paths.long_form(short_form(self.root / "a junction to the clone") + "\\alpha"),
            str(self.root / "a junction to the clone" / "alpha"),
        )

    def test_a_home_given_short_and_then_long_is_one_home(self) -> None:
        start = tree(self.long_home)
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, out, err = support.run("render", "--json", "--no-roles", "--home", self.short_home)
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(report["counts"]["create"], 6)
        self.assertNotIn("~", out)                       # the home is named in full
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertEqual(fsio.read_link(self.claude_skills / "alpha"), str(self.clone / "alpha"))
        before = tree(self.root)
        for home in (self.long_home, self.short_home, other_case(self.short_home)):
            with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
                code, out, err = support.run("render", "--json", "--no-roles", "--home", str(home))
            self.assertEqual((code, err, json.loads(out)["plan"]), (0, "", []), home)
            self.assertEqual(tree(self.root), before)
        code, report, err = uninstall(self, home=self.long_home)
        self.assertEqual((code, err, report["kept"]), (0, "", []))
        self.assertEqual(tree(self.long_home), start)

    def test_a_clone_found_by_its_short_name_gives_links_in_the_long_form(self) -> None:
        with mock.patch.object(locations, "CLONE", Path(self.short_clone)):
            code, report, err = self.report()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(fsio.read_link(self.claude_skills / "alpha"), str(self.clone / "alpha"))
        code, report, err = self.report()                # and the clone by its long name finds them its own
        self.assertEqual((code, err, report["plan"]), (0, "", []))

    def test_a_link_whose_text_is_the_short_form_is_setups_link_all_the_same(self) -> None:
        self.assertEqual(self.render()[0], 0)
        link = self.claude_skills / "alpha"
        fsio.remove_link(link)
        fsio.make_junction(self.short_clone + "\\alpha", link)
        self.assertIn("~", fsio.read_link(link))
        sorter = homes.Classifier(homes.resolve(Locations(home=self.home, clone=self.clone), self.host))
        self.assertEqual(sorter.entry(link).kind, homes.LINK_TO_CLONE)
        code, report, err = self.report()
        self.assertEqual((code, err, report["plan"]), (0, "", []))
        code, report, err = uninstall(self, "--clone-was", self.short_clone)
        self.assertEqual((code, err, report["kept"]), (0, "", []))
        self.assertNothingAt(link)
        self.assertTrue((self.clone / "alpha" / "SKILL.md").is_file())


# --- Junctions through the commands -------------------------------------------

@unittest.skipUnless(WINDOWS, "junctions are made on Windows")
class JunctionInstallCase(UninstallCase):
    """``init``, ``render`` with the migration, and ``uninstall``, as the
    user runs them: every link is a junction, and none is ever entered."""

    def links(self) -> list[Path]:
        record = fileops.read_record(self.roots())
        return [record.path(key) for key, entry in record.entries.items() if entry["kind"] == "link"]

    def test_every_link_is_a_junction_and_the_clone_is_as_it_was(self) -> None:
        before = self.start()
        self.install()
        links = self.links()
        self.assertGreaterEqual(len(links), 8)
        for link in links:
            self.assertTrue(fsio.is_junction(link), link)
            self.assertFalse(os.path.islink(link), link)
            seen = fsio.look(link)
            self.assertEqual((seen.kind, seen.directory, seen.junction), (fsio.LINK, True, True), link)
        # The migration put setup's junction where a v1 copy was.
        self.assertIn(self.claude_skills / "self-reflection", links)
        self.assertTrue(fsio.is_junction(self.claude_skills / "csv-tools"))   # in place of the user's junction
        self.assertEqual(picture(self.clone), before["clone"])

        # A stale sweep: the skill is no longer one for Codex.
        skill = self.clone / "beta" / "SKILL.md"
        was = skill.read_bytes()
        skill.write_bytes(was.replace(b"claude-code, codex", b"claude-code (no longer for both)"))
        out = self.done("render", "--apply-codex-settings", *self.at_home)
        self.assertIn("remove link home:.agents/skills/beta", out)
        self.assertNothingAt(self.codex_skills / "beta")
        self.assertTrue(fsio.is_junction(self.claude_skills / "beta"))
        self.assertEqual(sorted(os.listdir(self.clone / "beta")), ["SKILL.md", "scripts"])   # the sentinel
        skill.write_bytes(was)
        self.done("render", "--apply-codex-settings", *self.at_home)
        self.assertEqual(picture(self.clone), before["clone"])

        self.take_back()
        self.assertAsAtTheStart(before)

    def test_the_python_311_way_of_telling_and_removing_a_junction(self) -> None:
        # 3.11 has no ``os.path.isjunction``, and an older Windows Python
        # refuses to ``unlink`` a junction: both other branches, on purpose.
        before = self.start()
        real_unlink = os.unlink

        def unlink(path, *args, **kwargs):
            found = os.lstat(path)
            if getattr(found, "st_reparse_tag", 0) == 0xA0000003:
                raise PermissionError(13, "Access is denied", os.fspath(path))
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(os.path, "isjunction", None, create=True), mock.patch.object(os, "unlink", unlink):
            self.install()
            links = self.links()
            self.assertTrue(links)
            for link in links:
                self.assertTrue(fsio.is_junction(link), link)
                self.assertTrue(fsio.look(link).junction, link)
            self.take_back()
            self.assertAsAtTheStart(before)


@unittest.skipUnless(WINDOWS, "junctions are made on Windows")
class JunctionRenderCase(RenderCase):
    def junctions(self) -> list[Path]:
        return [self.claude_skills / "alpha", self.claude_skills / "beta", self.claude_skills / "solo",
                self.codex_skills / "alpha", self.codex_skills / "beta", self.rules / "sample"]

    def assertInstalled(self) -> None:
        for link in self.junctions():
            self.assertTrue(fsio.is_junction(link), link)
            self.assertLinked(link, self.clone / ("rules/sample" if link.name == "sample" else link.name))

    def test_a_junction_whose_target_is_gone_is_swept_as_a_link(self) -> None:
        self.assertEqual(self.render()[0], 0)
        moved = self.root / "moved away"
        shutil.move(str(self.clone / "solo"), str(moved))
        link = self.claude_skills / "solo"
        seen = fsio.look(link)
        self.assertEqual((seen.kind, seen.directory, seen.junction), (fsio.LINK, False, True))
        self.assertTrue(fsio.is_junction(link))
        self.assertFalse(os.path.exists(link))
        sorter = homes.Classifier(homes.resolve(Locations(home=self.home, clone=self.clone), self.host))
        self.assertEqual(sorter.entry(link).kind, homes.LINK_BROKEN)
        code, report, err = self.report()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(report["plan"], ["remove link home:.claude/skills/solo"])
        self.assertNothingAt(link)
        self.assertEqual(sorted(os.listdir(moved)), ["SKILL.md"])

    def test_uninstall_removes_a_junction_whose_target_is_gone(self) -> None:
        self.assertEqual(self.render()[0], 0)
        moved = self.root / "moved away"
        shutil.move(str(self.clone / "alpha"), str(moved))
        kept = tree(moved)
        code, report, err = uninstall(self)
        self.assertEqual((code, err, report["kept"]), (0, "", []))
        for link in self.junctions():
            self.assertNothingAt(link)
        self.assertEqual(tree(moved), kept)
        self.assertTrue((self.clone / "beta" / "SKILL.md").is_file())

    def test_fsio_removes_a_dangling_junction(self) -> None:
        target, link = self.root / "target", self.root / "dangling"
        target.mkdir()
        fsio.make_junction(str(target), link)
        target.rmdir()
        self.assertTrue(fsio.is_junction(link))
        fsio.remove_link(link)
        self.assertFalse(os.path.lexists(link))

    def test_a_home_and_a_clone_with_spaces_and_letters_beyond_ascii(self) -> None:
        clone = self.root / "clöne with spaces 日本語"
        os.rename(self.clone, clone)
        home = self.root / "hôme of Zoë & co"
        shutil.move(str(self.home), str(home))
        self.clone, self.home = clone, home
        self.claude_skills, self.codex_skills = home / ".claude" / "skills", home / ".agents" / "skills"
        self.rules = home / ".claude" / "rules"
        start, source = tree(home), tree(clone)
        with mock.patch.object(locations, "CLONE", clone):
            code, out, err = self.render()
            self.assertEqual((code, err), (0, ""), out)
            self.assertInstalled()
            self.assertEqual(fsio.read_link(self.claude_skills / "alpha"), str(clone / "alpha"))
            self.assertTrue((self.claude_skills / "alpha" / "SKILL.md").read_bytes().startswith(b"---\n"))
            raw = (home / ".agents" / "workflow-setup" / "manifest.json").read_bytes()
            self.assertNotIn(b"\r", raw)
            self.assertNotIn("clöne".encode("utf-8"), raw)   # the record names no machine's path
            code, report, err = uninstall(self)
            self.assertEqual((code, err, report["kept"]), (0, "", []))
        self.assertEqual((tree(home), tree(clone)), (start, source))
        # The other way to make one: ``cmd.exe`` is given no name it would read as syntax.
        with self.assertRaises(SetupError) as caught:
            fsio.make_junction(str(clone / "alpha"), home / "by mklink", use_mklink=True)
        self.assertIn("cmd.exe", str(caught.exception))
        plain = self.root / "hôme of Zoë"
        plain.mkdir()
        fsio.make_junction(str(clone / "alpha"), plain / "by mklink", use_mklink=True)
        self.assertTrue(fsio.same_target(fsio.read_link(plain / "by mklink"), str(clone / "alpha")))
        fsio.remove_link(plain / "by mklink")
        self.assertEqual(tree(clone), source)


@unittest.skipUnless(WINDOWS, "the 260-character limit is a Windows matter")
class LongPathCase(RenderCase):
    """Windows refuses a path of 260 characters or more unless long paths
    are switched on for the machine. Setup asks for nothing special: below
    the limit it works, beyond it the run fails in one line, or works where
    the machine allows long paths. Nothing is half made either way."""

    LONGEST_TAIL = len("\\.agents\\workflow-setup\\.wfsetup-12345678.tmp")   # the longest name a plain render makes

    def deep_home(self, length: int) -> Path:
        """A home whose own path has ``length`` characters, made with the
        prefix that lifts the limit, and removed with it."""
        text = str(self.root / "deep")
        self.addCleanup(shutil.rmtree, "\\\\?\\" + text, True)
        while len(text) < length - 1:
            text += "\\" + "d" * min(60, length - len(text) - 1)
        self.assertEqual(len(text), length)
        os.makedirs("\\\\?\\" + text + "\\.claude")
        os.mkdir("\\\\?\\" + text + "\\.codex")
        return Path(text)

    def run_at(self, command: str, home: Path, *argv: str) -> tuple[int, str, str]:
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            return support.run(command, *argv, "--home", str(home))

    def test_just_below_the_limit_everything_works(self) -> None:
        home = self.deep_home(259 - self.LONGEST_TAIL - 2)
        start = tree(home)
        code, out, err = self.run_at("render", home, "--no-roles")
        self.assertEqual((code, err), (0, ""), out)
        link = home / ".claude" / "skills" / "alpha"
        self.assertGreater(len(str(link)), 230)
        self.assertTrue(fsio.is_junction(link))
        self.assertTrue((link / "SKILL.md").is_file())
        code, out, err = self.run_at("uninstall", home)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(tree(home), start)

    def test_beyond_the_limit_the_run_fails_in_one_line_or_works(self) -> None:
        for length in (250, 300):
            home = self.deep_home(length) if length == 250 else Path(str(self.root / "deep") + "\\x" * 150)
            if length != 250:
                os.makedirs("\\\\?\\" + str(home) + "\\.claude")
            before = tree(Path("\\\\?\\" + str(self.root / "deep")))
            for command, argv in (("render", ("--no-roles",)), ("doctor", ("--only", "links")), ("uninstall", ())):
                code, out, err = self.run_at(command, home, *argv)
                self.assertNotIn("Traceback", out + err)
                if code == 0 and not err:
                    continue                                 # long paths are on, or nothing was to be done
                lines = err.splitlines()
                self.assertTrue(lines and all(line.startswith("error: ") for line in lines), (command, out, err))
                self.assertLessEqual(len([line for line in lines if "deep" in line]), 2, err)
                if command == "render":
                    self.assertEqual(tree(Path("\\\\?\\" + str(self.root / "deep"))), before)   # nothing half made
            shutil.rmtree("\\\\?\\" + str(self.root / "deep"), True)

    def test_a_target_near_the_limit(self) -> None:
        target = Path(str(self.root / "deep-target") + "\\" + "t" * 60 + "\\" + "u" * 60)
        target = Path(str(target) + "\\" + "v" * (245 - len(str(target))))
        target.mkdir(parents=True)
        self.assertEqual(len(str(target)), 246)
        (target / "SKILL.md").write_bytes(b"deep\n")
        link = self.root / "j"
        fsio.make_junction(str(target), link)
        self.assertEqual(fsio.read_link(link), str(target))
        self.assertEqual((link / "SKILL.md").read_bytes(), b"deep\n")
        fsio.remove_link(link)
        self.assertEqual((target / "SKILL.md").read_bytes(), b"deep\n")


# --- What another program does to a file ---------------------------------------

class ReplaceCase(OpsCase):
    """A rename over a file that a scanner or an editor holds open is
    refused by Windows for a moment. It is tried again for under a second."""

    def test_the_waits_are_short_and_windows_only(self) -> None:
        self.assertEqual(bool(fsio.REPLACE_WAITS), WINDOWS)
        self.assertLess(sum(fsio.REPLACE_WAITS), 1.0)

    def refusing(self, times: int):
        real, calls = os.replace, []

        def replace(source, target):
            calls.append(target)
            if len(calls) <= times:
                raise PermissionError(13, "The process cannot access the file because it is being used by another process")
            return real(source, target)

        return calls, mock.patch.object(os, "replace", replace)

    def test_a_rename_refused_for_a_moment_is_tried_again(self) -> None:
        target = self.put(self.home / "x.md", "old\n")
        calls, patch = self.refusing(2)
        with patch, mock.patch.object(fsio, "REPLACE_WAITS", (0.0, 0.0, 0.0)):
            fsio.atomic_write(target, b"new\n")
        self.assertEqual((target.read_bytes(), len(calls)), (b"new\n", 3))
        self.assertEqual(self.temporaries(), [])

    def test_a_rename_refused_for_good_is_one_line_and_leaves_the_old_file(self) -> None:
        target = self.put(self.home / "x.md", "old\n")
        calls, patch = self.refusing(99)
        with patch, mock.patch.object(fsio, "REPLACE_WAITS", (0.0, 0.0)):
            with self.assertRaises(SetupError) as caught:
                fsio.atomic_write(target, b"new\n")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(caught.exception.lines), 1)
        self.assertIn("read-only, or open in another program?", caught.exception.lines[0])
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(self.temporaries(), [])

    def test_without_waits_nothing_is_tried_twice(self) -> None:
        target = self.put(self.home / "x.md", "old\n")
        calls, patch = self.refusing(1)
        with patch, mock.patch.object(fsio, "REPLACE_WAITS", ()):
            with self.assertRaises(SetupError):
                fsio.atomic_write(target, b"new\n")
        self.assertEqual(len(calls), 1)

    @unittest.skipUnless(WINDOWS, "Windows refuses to rename over a file another handle holds")
    def test_a_file_held_open_is_reported_and_the_plan_changes_nothing(self) -> None:
        target = self.put(self.home / ".claude" / "agents" / "held.md", "the user's\n")
        other = self.home / ".claude" / "agents" / "new.md"
        with open(target, "rb"):
            plan = self.plan()
            plan.write_file(other, "new\n")
            plan.write_file(target, "setup's\n", replace=fileops.ANY)
            with self.assertRaises(SetupError) as caught:
                plan.apply()
        self.assertIn(str(target), caught.exception.lines[0])
        self.assertIn("open in another program?", caught.exception.lines[0])
        self.assertEqual(target.read_bytes(), b"the user's\n")
        self.assertEqual(self.temporaries(), [])
        self.reversal().apply()
        self.assertFalse(other.exists())

    @unittest.skipUnless(WINDOWS, "the read-only attribute of Windows")
    def test_a_read_only_file_is_refused_before_anything_is_written(self) -> None:
        import stat as stat_module

        target = self.put(self.home / ".claude" / "agents" / "locked.md", "the user's\n")
        os.chmod(target, stat_module.S_IREAD)
        self.addCleanup(os.chmod, target, stat_module.S_IWRITE | stat_module.S_IREAD)
        plan = self.plan()
        plan.write_file(self.home / ".claude" / "agents" / "new.md", "new\n")
        plan.write_file(target, "setup's\n", replace=fileops.ANY)
        error = self.refused(plan)
        self.assertEqual(error.codes(), {fileops.NOT_WRITABLE})
        self.assertIn(f"{target}: is read-only", str(error))


# --- The bytes setup writes and prints -----------------------------------------

class LineEndingCase(UninstallCase):
    """Run as a process of its own, as the user runs it: what it prints is
    UTF-8 with LF whatever the console is, and what it writes is LF, except
    into a file of the user's that has CRLF already."""

    def child(self, script: Path, *argv: str, home: Path | None = None) -> subprocess.CompletedProcess:
        empty = self.root / "no-programs"
        empty.mkdir(exist_ok=True)
        environment = {**support.child_environment(), "PATH": str(empty)}
        return subprocess.run(
            [sys.executable, "-B", str(script), *argv, "--home", str(home or self.home)], env=environment,
            cwd=str(self.root), stdin=subprocess.DEVNULL, capture_output=True, timeout=180, check=False,
        )

    def tool(self) -> Path:
        """The tool in the fixture clone, with the list of keys it reads."""
        script = self.install_tool()
        shutil.copyfile(support.SETUP / "manifest-keys.json", script.parent / "manifest-keys.json")
        return script

    def files(self) -> dict[str, bytes]:
        found = {}
        for name, root in (("home", self.home), ("project", self.project)):
            for path, what in picture(root).items():
                if what[0] == "file":
                    found[f"{name}/{path}"] = what[1]
        return found

    def test_every_byte_printed_and_written_is_lf(self) -> None:
        if not LINKS:
            self.skipTest("needs links to directories")
        self.start(v1_copies=False)
        script = self.tool()
        before = self.files()
        project = ("--project", str(self.project))
        runs = [
            (("init", "--user", "--yes", "--rewrite-settings"), 0), (("init", "--yes", "--rewrite-settings", *project), 0),
            (("render", "--apply-codex-settings"), 0), (("render", *project), 0),
            (("render", "--json", "--dry-run", *project), 0),
            (("homes",), 0), (("homes", "--json"), 0), (("show",), 0), (("show", "--json", *project), 0),
            (("validate",), 0), (("doctor", "--no-collab", "--no-model-list", "--no-versions"), None),
            (("doctor", "--json", "--no-collab", "--no-model-list", "--no-versions", *project), None),
            (("uninstall", "--dry-run"), 0), (("uninstall", "--dry-run", "--json", *project), 0),
            (("render", "--help"), 0), (("render", "--no-such-option"), 2), (("show", "no.such.key"), 2),
        ]
        printed = 0
        for argv, expected in runs:
            done = self.child(script, *argv)
            said = done.stdout + done.stderr
            if expected is not None:
                self.assertEqual(done.returncode, expected, (argv, said.decode("utf-8", "replace")[-600:]))
            self.assertNotIn(b"Traceback", said, argv)
            self.assertNotIn(b"\r", said, argv)
            said.decode("utf-8")
            printed += len(said)
        self.assertGreater(printed, 5000)

        after = self.files()
        written = {name for name, data in after.items() if before.get(name) != data}
        self.assertGreaterEqual(len(written), 12, sorted(written))
        kept_crlf = 0
        for name in sorted(written):
            data, was = after[name], before.get(name, b"")
            if "/workflow-setup/backups/" in name:
                continue                                     # a backup: what was there, byte for byte
            elif b"\r\n" in was:
                # The user's file, with the user's line endings: setup's lines take them.
                self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), name)
                kept_crlf += 1
            else:
                self.assertNotIn(b"\r", data, name)
        self.assertGreaterEqual(kept_crlf, 2)                # the project's settings.json and config.toml

        for argv in (("uninstall", *project), ("uninstall",)):
            done = self.child(script, *argv)
            self.assertEqual((done.returncode, done.stderr), (0, b""), done.stdout.decode("utf-8", "replace")[-600:])
            self.assertNotIn(b"\r", done.stdout)
        self.assertEqual(self.files(), before)               # CRLF where it was, LF where it was

    def test_a_path_beyond_ascii_is_printed_as_utf8(self) -> None:
        script = self.tool()
        home = self.root / "hôme Zoë 日本語"
        (home / ".claude").mkdir(parents=True)
        for argv in (("homes",), ("render", "--no-roles", "--dry-run"), ("homes", "--json")):
            done = self.child(script, *argv, home=home)
            self.assertEqual((done.returncode, done.stderr), (0, b""), done.stdout.decode("utf-8", "replace")[-400:])
            self.assertIn("hôme Zoë 日本語", done.stdout.decode("utf-8"))
            self.assertNotIn(b"\r", done.stdout)
        done = self.child(script, "show", home=home / "nöt thére")
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertIn("nöt thére", done.stderr.decode("utf-8"))
        self.assertNotIn(b"\r", done.stderr)


class DoctorOnWindowsCase(DoctorCase):
    @unittest.skipUnless(WINDOWS, "junctions are made on Windows")
    def test_doctor_reads_junctions_and_reports_a_dangling_one_in_one_line(self) -> None:
        self.rendered()
        code, findings = self.only("links")
        self.assertEqual(code, 0, findings)
        shutil.move(str(self.clone / "alpha"), str(self.root / "moved away"))
        code, findings = self.only("links")
        missing = [found for found in findings if "the link's target does not exist" in found["detail"]]
        self.assertEqual(len(missing), 2, findings)          # one for each provider's link
        for found in missing:
            self.assertNotIn("\n", found["detail"])


if __name__ == "__main__":
    unittest.main()
