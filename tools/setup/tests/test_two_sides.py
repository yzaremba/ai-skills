"""Tests that need both sides of one machine at once: what WSL reads of a
junction Windows made, and what the Windows Python meets where WSL made a
link.

They run under Linux, in a WSL that can start Windows programs, and are
skipped anywhere else with the reason (see ``interop_support``). Every
scratch tree is in the Windows temporary directory, on a Windows drive: a
junction leads nowhere else, and that is where both sides read one file.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

import interop_support
from test_validate import TreeCase
from wfsetup import fsio, homes
from wfsetup.locations import Locations

WSL_NOTE = "a link made in WSL, which Windows cannot follow"


@unittest.skipUnless(os.name == "posix", "the mount table and its paths are a Linux matter")
class DriveTableCase(unittest.TestCase):
    def test_the_drives_of_a_mount_table(self) -> None:
        table = (
            "none /usr/lib/wsl/drivers 9p ro,aname=drivers;fmask=222,cache=5 0 0\n"
            "/dev/sdc / ext4 rw,relatime 0 0\n"
            "Q:\\134 /mnt/q 9p rw,noatime,aname=drvfs;path=Q:\\134;uid=1000,cache=5 0 0\n"
            "R: /win\\040drives/r drvfs rw,noatime 0 0\n"
            "drvfs /mnt/s drvfs rw,noatime 0 0\n"
            "drvfs /mnt/share drvfs rw,noatime 0 0\n"
        )
        self.assertEqual(interop_support.drive_table(table), {"q": "/mnt/q", "r": "/win drives/r", "s": "/mnt/s"})
        there = interop_support.Windows({"q": "/mnt/q", "r": "/win drives/r"}, Path("/"), Path("/"), "", None)
        self.assertEqual(there.here("Q:\\Users\\Someone\\x y"), Path("/mnt/q/Users/Someone/x y"))
        self.assertEqual(there.here("r:/a"), Path("/win drives/r/a"))
        self.assertEqual(there.there("/mnt/q/Users/Someone/x y"), "Q:\\Users\\Someone\\x y")
        self.assertEqual(there.there(Path("/win drives/r")), "R:\\")
        for text in ("Z:\\x", "\\\\server\\share"):
            with self.assertRaises(ValueError):
                there.here(text)
        with self.assertRaises(ValueError):
            there.there("/home/someone")


class JunctionSeenFromWslCase(unittest.TestCase):
    """A junction made by Windows reads, from WSL, as a link to the matching
    path under the drive's mount point (P5.13)."""

    def setUp(self) -> None:
        self.far = interop_support.need(self)
        self.root = self.far.scratch(self)
        self.home = self.root / "home"
        self.skills = self.home / ".claude" / "skills"
        self.skills.mkdir(parents=True)
        self.clone = self.root / "clone"
        self.host = homes.Host.current()

    def directory(self, path: Path) -> Path:
        path.mkdir(parents=True)
        (path / "SKILL.md").write_bytes(b"the sentinel\n")
        return path

    def junction(self, link: Path, target: Path) -> None:
        done = self.far.shell("mklink", "/J", self.far.there(link), self.far.there(target))
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr).decode("utf-8", "replace"))

    def remove_as_windows_does(self, link: Path) -> None:
        done = self.far.shell("rmdir", self.far.there(link))
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr).decode("utf-8", "replace"))

    def sorter(self, home: Path | None = None) -> homes.Classifier:
        where = Locations(home=home or self.home, clone=self.clone, real_home=True)
        return homes.Classifier(homes.resolve(where, self.host))

    def test_it_reads_as_a_link_to_the_path_under_the_mount_point(self) -> None:
        target = self.directory(self.clone / "json-tools")
        link = self.skills / "json-tools"
        self.junction(link, target)

        seen = fsio.look(link)
        self.assertEqual((seen.kind, seen.directory), (fsio.LINK, True))
        self.assertEqual(seen.target, str(target))            # /mnt/<drive>/..., not the drive path
        mount = self.far.drives[self.far.temp[0].lower()]
        self.assertTrue(seen.target.startswith(mount.rstrip("/") + "/"), seen.target)
        self.assertNotIn("\\", seen.target)
        self.assertFalse(seen.junction)                       # to Linux it is a symlink
        self.assertFalse(fsio.is_junction(link))
        self.assertEqual(os.path.realpath(link), os.path.realpath(target))
        self.assertEqual((link / "SKILL.md").read_bytes(), b"the sentinel\n")

        # The classifier: the Windows home is the other side's, the link is
        # a link into the clone, and the clone on the drive is shared.
        self.assertEqual(self.host.side, homes.WSL)
        self.assertEqual(self.host.other_side(link), homes.WINDOWS)
        sorter = self.sorter()
        entry = sorter.entry(link)
        self.assertEqual((entry.kind, entry.target, entry.real), (homes.LINK_TO_CLONE, str(target), target))
        standing = sorter.standing(link)
        self.assertEqual((standing.kind, standing.side, standing.writes), (homes.OTHER_SIDE, homes.WINDOWS, False))
        self.assertIs(homes.clone_standing(sorter.homes).shared, True)

        # Removed by Windows as a link: what it led to is whole.
        self.remove_as_windows_does(link)
        self.assertEqual(fsio.look(link).kind, fsio.ABSENT)
        self.assertEqual(os.listdir(target), ["SKILL.md"])
        self.assertEqual((target / "SKILL.md").read_bytes(), b"the sentinel\n")

    def test_a_junction_to_elsewhere_on_the_drive_and_one_that_leads_nowhere(self) -> None:
        elsewhere = self.directory(self.root / "another home" / "skills" / "solo ö 日本")
        gone = self.directory(self.root / "gone")
        self.junction(self.skills / "solo", elsewhere)
        self.junction(self.skills / "broken", gone)
        shutil.rmtree(gone)
        sorter = self.sorter()
        solo = sorter.entry(self.skills / "solo")
        self.assertEqual((solo.kind, solo.side, solo.target), (homes.LINK_OTHER_SIDE, homes.WINDOWS, str(elsewhere)))
        # A link that leads nowhere is still told by where its text leads.
        broken = fsio.look(self.skills / "broken")
        self.assertEqual((broken.kind, broken.target, broken.directory), (fsio.LINK, str(gone), False))
        self.assertEqual(sorter.entry(self.skills / "broken").kind, homes.LINK_OTHER_SIDE)
        for name in ("solo", "broken"):
            self.remove_as_windows_does(self.skills / name)
        self.assertEqual(os.listdir(self.skills), [])
        self.assertEqual((elsewhere / "SKILL.md").read_bytes(), b"the sentinel\n")

    def test_a_wsl_home_that_links_to_the_windows_homes_junction(self) -> None:
        # As on a machine where WSL's skills directory entry is a link to
        # the Windows home's: two links deep, and still a link into the clone.
        target = self.directory(self.clone / "json-tools")
        self.junction(self.skills / "json-tools", target)
        import tempfile

        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        wsl_home = Path(scratch.name).resolve() / "home"
        mine = wsl_home / ".claude" / "skills"
        mine.mkdir(parents=True)
        os.symlink(str(self.skills / "json-tools"), mine / "json-tools")
        os.symlink(str(self.home / ".claude" / "rules"), wsl_home / ".claude" / "rules")
        sorter = self.sorter(wsl_home)
        self.assertEqual(sorter.entry(mine / "json-tools").kind, homes.LINK_TO_CLONE)
        self.assertEqual(sorter.standing(mine).kind, homes.THIS_SIDE)
        rules = sorter.standing(wsl_home / ".claude" / "rules" / "sample")
        self.assertEqual((rules.kind, rules.side), (homes.OTHER_SIDE, homes.WINDOWS))
        self.remove_as_windows_does(self.skills / "json-tools")
        self.assertEqual(sorter.entry(mine / "json-tools").kind, homes.LINK_OTHER_SIDE)   # now it leads nowhere
        self.assertEqual((target / "SKILL.md").read_bytes(), b"the sentinel\n")


class WslLinkSeenFromWindowsCase(TreeCase):
    """The other way round. A link made in WSL on a Windows drive, to an
    absolute path, is to the Windows Python a file it cannot open and no
    link it can read. Every command says so in one line and none ends in a
    traceback; nothing is written over one."""

    def setUp(self) -> None:
        self.far = interop_support.need(self, python=True)
        with self.far.as_temp():
            super().setUp()
        self.script = self.install_tool()
        self.claude, self.codex = self.home / ".claude", self.home / ".codex"
        self.claude.mkdir()
        self.codex.mkdir()

    def run_there(self, *argv: str) -> tuple[int, str, str]:
        done = self.far.run(
            self.far.python, "-B", self.far.there(self.script), *argv, "--home", self.far.there(self.home))
        out, err = done.stdout.decode("utf-8"), done.stderr.decode("utf-8")
        self.assertNotIn("Traceback", out + err, argv)
        self.assertNotIn("\r", out + err, argv)
        for line in err.splitlines():
            self.assertTrue(line.startswith("error: "), (argv, err))
        return done.returncode, out, err

    def wsl_link(self, path: Path, target: str = "/home/nobody/there") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, path)
        return path

    def test_the_junctions_render_makes_on_windows_read_from_wsl_as_links_into_the_clone(self) -> None:
        # Setup's own way of making one (inside the Windows Python, not
        # ``mklink``), through the real commands on the Windows side.
        code, out, err = self.run_there("render", "--no-roles")
        self.assertEqual((code, err), (0, ""), out)
        where = Locations(home=self.home, clone=self.clone, real_home=True)
        sorter = homes.Classifier(homes.resolve(where, homes.Host.current()))
        links = [self.claude / "skills" / "alpha", self.claude / "skills" / "solo",
                 self.home / ".agents" / "skills" / "beta", self.claude / "rules" / "sample"]
        for link in links:
            target = self.clone / ("rules/sample" if link.name == "sample" else link.name)
            seen = fsio.look(link)
            self.assertEqual((seen.kind, seen.target, seen.directory), (fsio.LINK, str(target), True), link)
            self.assertEqual(sorter.entry(link).kind, homes.LINK_TO_CLONE, link)
            self.assertEqual(sorter.standing(link).kind, homes.OTHER_SIDE, link)
        self.assertTrue((links[0] / "SKILL.md").read_bytes().startswith(b"---\n"))
        source = sorted(os.listdir(self.clone / "alpha"))
        code, out, err = self.run_there("uninstall")
        self.assertEqual((code, err), (0, ""), out)
        for link in links:
            self.assertEqual(fsio.look(link).kind, fsio.ABSENT, link)
        self.assertEqual(sorted(os.listdir(self.clone / "alpha")), source)

    def test_where_a_skill_is_to_be_linked(self) -> None:
        link = self.wsl_link(self.claude / "skills" / "alpha", str(self.clone / "alpha"))
        code, out, err = self.run_there("homes")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("    - alpha: a file of its own, not a link", out.splitlines())
        for argv in (("render", "--no-roles", "--dry-run"), ("render", "--no-roles")):
            code, out, err = self.run_there(*argv)
            self.assertEqual(code, 2, out)
            self.assertEqual(len([line for line in err.splitlines() if "alpha" in line]), 1, err)
            self.assertIn(f"{self.far.there(link)}: a file of its own, not a link, and setup did not make it", err)
            self.assertIn("nothing was written", out.splitlines()[-1])
        self.assertEqual(os.readlink(link), str(self.clone / "alpha"))   # as WSL made it
        self.assertEqual(sorted(os.listdir(self.claude / "skills")), ["alpha"])
        code, out, _ = self.run_there("doctor", "--only", "links", "--only", "v1")
        self.assertIn(code, (0, 1, 2))

    def test_where_setups_own_link_was(self) -> None:
        self.assertEqual(self.run_there("render", "--no-roles")[0], 0)
        link = self.claude / "skills" / "alpha"
        self.assertEqual(self.far.shell("rmdir", self.far.there(link)).returncode, 0)
        self.wsl_link(link, str(self.clone / "alpha"))
        code, out, err = self.run_there("render", "--no-roles")
        self.assertEqual(code, 2)
        self.assertEqual(len(err.splitlines()), 2, err)            # the conflict, and the hint
        code, out, err = self.run_there("doctor", "--only", "links")
        self.assertNotEqual(code, 0)
        self.assertIn("home:.claude/skills/alpha: no longer a link: a file is there", out)
        for _ in range(2):
            code, out, err = self.run_there("uninstall")
            self.assertEqual(code, 2)
            self.assertEqual(err.splitlines(), [
                f"error: {self.far.there(link)}: cannot be read: Invalid argument (it is {WSL_NOTE})"])
            self.assertIn("nothing was changed", out.splitlines()[-1])
        self.assertEqual(os.readlink(link), str(self.clone / "alpha"))
        os.unlink(link)
        code, _, err = self.run_there("uninstall")
        self.assertEqual(err, "")
        self.assertIn(code, (0, 3))

    def test_where_the_files_setup_edits_are(self) -> None:
        self.wsl_link(self.claude / "CLAUDE.md")
        self.wsl_link(self.claude / "rules")
        config = self.wsl_link(self.codex / "config.toml")
        self.wsl_link(self.claude / "agents" / "sprint-coder.md")
        code, out, err = self.run_there("homes")
        self.assertEqual((code, err), (0, ""))
        code, out, err = self.run_there("render", "--no-roles", "--apply-codex-settings")
        self.assertEqual(code, 2, out)
        rules = self.far.there(self.claude / "rules")
        self.assertEqual(sorted(err.splitlines()), sorted([
            f"error: {rules}\\sample: cannot be told ({rules}\\sample: cannot be read: The file cannot be "
            f"accessed by the system ({rules} is {WSL_NOTE}))",
            f"error: {self.far.there(config)}: cannot be read: Invalid argument (it is {WSL_NOTE})",
        ]))
        self.assertIn("nothing was written", out.splitlines()[-1])
        self.assertFalse((self.home / ".agents").exists())
        code, out, err = self.run_there("doctor", "--only", "links", "--only", "codex-settings", "--only", "v1")
        self.assertEqual(err, "")
        self.assertIn(WSL_NOTE, out)
        code, out, err = self.run_there("uninstall")
        self.assertEqual((code, err), (0, ""))
        for path in (self.claude / "CLAUDE.md", self.claude / "rules", config):
            self.assertEqual(os.readlink(path), "/home/nobody/there")

    def test_where_setups_own_state_and_settings_are(self) -> None:
        state = self.wsl_link(self.home / ".agents" / "workflow-setup")
        record = self.far.there(state) + "\\manifest.json"
        for argv in (("render", "--no-roles"), ("uninstall",), ("doctor", "--only", "links")):
            code, out, err = self.run_there(*argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn(f"{self.far.there(state)} is {WSL_NOTE}", out + err, argv)
            self.assertLessEqual(len([line for line in (out + err).splitlines() if record in line]), 2, argv)
        os.unlink(state)
        settings = self.wsl_link(self.home / ".agents" / "workflow.toml")
        for argv in (("show",), ("init", "--user", "--yes", "--rewrite-settings")):
            code, out, err = self.run_there(*argv)
            self.assertEqual(code, 2, argv)
            self.assertEqual(err.splitlines()[0],
                             f"error: {self.far.there(settings)}: cannot be read: Invalid argument (it is {WSL_NOTE})")
        self.assertEqual(os.readlink(settings), "/home/nobody/there")

    def test_in_the_clone(self) -> None:
        self.wsl_link(self.clone / "beta" / "linked", str(self.clone / "alpha"))
        self.wsl_link(self.clone / "beta" / "references.md")
        code, out, err = self.run_there("validate")
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(out.splitlines(), [
            "beta/linked: [symlink] is a link; no link is committed, and Codex skips a linked file inside a skill",
            "beta/references.md: [symlink] is a link; no link is committed, and Codex skips a linked file inside a skill",
            "2 problems",
        ])
        code, out, err = self.run_there("render", "--no-roles")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(len(err.splitlines()), 2)
        self.assertFalse((self.home / ".agents").exists())


if __name__ == "__main__":
    unittest.main()
