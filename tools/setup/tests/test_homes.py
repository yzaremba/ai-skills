"""Tests for the homes of a run: where they are, whose each path is, the
shared clone, and links.

Every home here is a scratch directory. The layout of a machine with two
sides is rebuilt from links: a directory of the scratch tree stands in for
a Windows drive, and a hand-made ``Host`` says it is one.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

import support
from fileops_support import POSIX, SYMLINKS, OpsCase, snapshot
from wfsetup import fileops, fsio, homes
from wfsetup.errors import SetupError
from wfsetup.locations import Locations

WINDOWS = os.name == "nt"
SECRET = "SECRET-CONTENT-NOT-TO-BE-PRINTED"


def stub_program(directory: Path, name: str) -> Path:
    """An executable called ``name`` that does nothing."""
    directory.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        file = directory / f"{name}.cmd"
        file.write_bytes(b"@exit /b 0\r\n")
    else:
        file = directory / name
        file.write_bytes(b"#!/bin/sh\nexit 0\n")
        os.chmod(file, 0o755)
    return file


class HomesCase(OpsCase):
    """A scratch home taken for the real one, on a host made by hand."""

    def host(self, side: str = homes.LINUX, **environ: str) -> homes.Host:
        return homes.Host(side, dict(environ), ())

    def found(self, host: homes.Host | None = None, real_home: bool = True, project: bool = False) -> homes.Homes:
        where = Locations(
            home=self.home, project=self.project if project else None, clone=self.clone, real_home=real_home
        )
        return homes.resolve(where, host or self.host())


class SideCase(unittest.TestCase):
    def test_wsl_is_told_by_the_kernel_release_or_the_interop_entry(self) -> None:
        self.assertTrue(homes.is_wsl("6.6.87.2-microsoft-standard-WSL2\n", False))
        self.assertTrue(homes.is_wsl("4.4.0-19041-Microsoft", False))
        self.assertTrue(homes.is_wsl("6.1.0-custom", True))
        self.assertFalse(homes.is_wsl("6.8.0-45-generic", False))
        self.assertFalse(homes.is_wsl("", False))

    def test_this_process_is_on_one_of_the_three_sides(self) -> None:
        side = homes.detect_side()
        self.assertEqual(side == homes.WINDOWS, WINDOWS)
        self.assertIn(side, (homes.LINUX, homes.WSL, homes.WINDOWS))
        self.assertEqual(homes.Host.current().side, side)

    def test_drive_mounts_are_read_from_the_mount_table(self) -> None:
        table = (
            "none /usr/lib/wsl/drivers 9p ro,aname=drivers;fmask=222,cache=5 0 0\n"
            "/dev/sdc / ext4 rw,relatime 0 0\n"
            "drive /mnt/q 9p rw,noatime,aname=drvfs;path=drive;uid=1000,cache=5 0 0\n"
            "drive /win\\040drives/r drvfs rw,noatime 0 0\n"
            "short line\n"
        )
        self.assertEqual(homes.drive_mounts(table), ("/mnt/q", "/win drives/r"))
        self.assertEqual(homes.drive_mounts(""), ())

    def test_the_other_side_seen_from_wsl(self) -> None:
        host = homes.Host(homes.WSL, {}, ("/drives/q",))
        self.assertEqual(host.other, homes.WINDOWS)
        for text in ("/mnt/c", "/mnt/c/Users/someone/.claude", "/mnt/Z/x", "/drives/q", "/drives/q/x"):
            self.assertTrue(host.foreign(text), text)
        for text in ("/mnt/cache/x", "/mnt/wslg/x", "/mnt", "/home/someone/mnt/c/x", "/drives/quota", "/"):
            self.assertFalse(host.foreign(text), text)

    def test_the_other_side_seen_from_windows(self) -> None:
        host = homes.Host(homes.WINDOWS, {}, ())
        self.assertEqual(host.other, homes.WSL)
        for text in (
            "\\\\wsl.localhost\\Distro\\home\\someone",
            "\\\\WSL.LOCALHOST\\Distro\\home",
            "\\\\wsl$\\Distro\\home",
            "\\\\?\\UNC\\wsl.localhost\\Distro\\home",
            "//wsl.localhost/Distro/home",
        ):
            self.assertTrue(host.foreign(text), text)
        for text in ("Q:\\somewhere\\clone", "\\\\server\\share\\x", "\\\\wsl.example\\x", "Q:\\wsl$\\x"):
            self.assertFalse(host.foreign(text), text)

    def test_a_plain_linux_has_no_other_side(self) -> None:
        host = homes.Host(homes.LINUX, {}, ())
        self.assertIsNone(host.other)
        self.assertFalse(host.foreign("/mnt/c/x"))
        self.assertIsNone(host.other_side("/mnt/c/x"))

    def test_a_local_drive_path(self) -> None:
        for text in ("Q:\\x", "q:/x", "\\\\?\\Q:\\x"):
            self.assertTrue(fsio.local_drive_path(text), text)
        for text in ("\\\\server\\share", "\\\\wsl$\\Distro", "\\\\?\\UNC\\server\\share", "Q:x", "/mnt/q/x", "x", ""):
            self.assertFalse(fsio.local_drive_path(text), text)


class ResolutionCase(HomesCase):
    def test_the_default_homes(self) -> None:
        found = self.found()
        claude, codex = found.provider(homes.CLAUDE_CODE), found.provider(homes.CODEX)
        self.assertEqual(claude.home, self.home / ".claude")
        self.assertEqual(claude.home_from, homes.FROM_DEFAULT)
        self.assertEqual(
            {place.name: place.path for place in claude.places},
            {
                "skills": self.home / ".claude" / "skills",
                "agents": self.home / ".claude" / "agents",
                "rules": self.home / ".claude" / "rules",
                "instructions": self.home / ".claude" / "CLAUDE.md",
            },
        )
        self.assertEqual(codex.home, self.home / ".codex")
        self.assertEqual(
            {place.name: place.path for place in codex.places},
            {
                "skills": self.home / ".agents" / "skills",
                "agents": self.home / ".codex" / "agents",
                "instructions": self.home / ".codex" / "AGENTS.md",
                "config": self.home / ".codex" / "config.toml",
                "old-skills": self.home / ".codex" / "skills",
                "profiles": self.home / ".codex",
            },
        )
        self.assertIsNone(claude.anchor)
        self.assertIsNone(codex.anchor)
        self.assertFalse(found.scratch)
        self.assertEqual(found.extra, {})
        self.assertTrue(claude.place("skills").directory)
        self.assertFalse(codex.place("config").directory)
        with self.assertRaises(SetupError):
            codex.place("rules")
        with self.assertRaises(SetupError):
            found.provider("acme")

    def test_the_environment_variables_name_the_homes(self) -> None:
        inside = self.home / "config" / "claude"
        outside = self.root / "elsewhere" / "codex-home"
        found = self.found(self.host(CLAUDE_CONFIG_DIR=str(inside), CODEX_HOME=str(outside)))
        claude, codex = found.provider(homes.CLAUDE_CODE), found.provider(homes.CODEX)
        self.assertEqual((claude.home, claude.home_from), (inside, "CLAUDE_CONFIG_DIR"))
        self.assertEqual(claude.place("rules").path, inside / "rules")
        self.assertIsNone(claude.anchor)  # inside the user's home: the home anchor holds it
        self.assertEqual((codex.home, codex.home_from), (outside, "CODEX_HOME"))
        self.assertEqual(codex.place("agents").path, outside / "agents")
        self.assertEqual(codex.place("config").path, outside / "config.toml")
        # Codex's user skills stay in the user's own home.
        self.assertEqual(codex.place("skills").path, self.home / ".agents" / "skills")
        self.assertEqual(codex.anchor, "codex-home")
        roots = found.roots()
        self.assertEqual(roots.key(outside / "agents" / "coder.toml"), "codex-home:agents/coder.toml")
        self.assertEqual(roots.key(inside / "agents" / "coder.md"), "home:config/claude/agents/coder.md")
        self.assertEqual(roots.path("codex-home:agents/coder.toml"), outside / "agents" / "coder.toml")

    def test_a_claude_home_outside_the_users_home_has_its_own_anchor(self) -> None:
        outside = self.root / "elsewhere" / "claude-home"
        found = self.found(self.host(CLAUDE_CONFIG_DIR=str(outside)))
        self.assertEqual(found.provider(homes.CLAUDE_CODE).anchor, "claude-code-home")
        self.assertEqual(found.extra, {"claude-code-home": outside})
        self.assertEqual(found.roots().key(outside / "skills" / "json-tools"), "claude-code-home:skills/json-tools")

    def test_a_scratch_home_ignores_the_environment_variables(self) -> None:
        host = self.host(CLAUDE_CONFIG_DIR=str(self.root / "a"), CODEX_HOME=str(self.root / "b"))
        found = self.found(host, real_home=False)
        self.assertTrue(found.scratch)
        self.assertEqual(found.provider(homes.CLAUDE_CODE).home, self.home / ".claude")
        self.assertEqual(found.provider(homes.CLAUDE_CODE).home_from, homes.FROM_OPTION)
        self.assertEqual(found.provider(homes.CODEX).home, self.home / ".codex")
        self.assertEqual(found.provider(homes.CODEX).place("skills").path, self.home / ".agents" / "skills")
        self.assertEqual(found.extra, {})

    def test_a_locations_value_built_by_hand_is_a_scratch_home(self) -> None:
        self.assertFalse(Locations(home=self.home).real_home)
        self.assertTrue(homes.resolve(self.locations(), self.host()).scratch)

    def test_the_command_line_ignores_the_variables_with_home(self) -> None:
        elsewhere = self.root / "elsewhere"
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(elsewhere), "CODEX_HOME": str(elsewhere)}):
            code, out, err = support.run("homes", "--json", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""))
        found = json.loads(out)
        self.assertTrue(found["scratch"])
        self.assertEqual(
            [provider["home"] for provider in found["providers"]],
            [str(self.home / ".claude"), str(self.home / ".codex")],
        )
        self.assertNotIn("elsewhere", out)

    def test_help_says_that_home_ignores_the_variables(self) -> None:
        code, out, _ = support.run("homes", "--help")
        flat = " ".join(out.split())
        self.assertEqual(code, 0)
        self.assertIn("CLAUDE_CONFIG_DIR and CODEX_HOME are ignored", flat)
        self.assertIn("DIR/.claude and DIR/.codex", flat)

    def test_a_variable_set_to_nothing_is_not_set(self) -> None:
        found = self.found(self.host(CLAUDE_CONFIG_DIR="", CODEX_HOME="   "))
        self.assertEqual(found.provider(homes.CLAUDE_CODE).home, self.home / ".claude")
        self.assertEqual(found.provider(homes.CODEX).home_from, homes.FROM_DEFAULT)

    def test_a_relative_variable_is_refused(self) -> None:
        with self.assertRaises(SetupError) as caught:
            self.found(self.host(CODEX_HOME="some/where"))
        self.assertIn("CODEX_HOME: some/where: not an absolute path", str(caught.exception))

    def test_installed_is_the_program_on_path_or_the_home(self) -> None:
        bin_dir = self.root / "bin"
        stub_program(bin_dir, "claude")
        found = self.found(self.host(PATH=str(bin_dir)))
        claude, codex = found.provider(homes.CLAUDE_CODE), found.provider(homes.CODEX)
        self.assertTrue(claude.installed)
        self.assertEqual(Path(claude.program_file).parent, bin_dir)
        self.assertFalse(claude.home_exists)
        self.assertFalse(codex.installed)
        self.assertIsNone(codex.program_file)
        self.assertEqual([provider.name for provider in found.installed()], [homes.CLAUDE_CODE])

        (self.home / ".codex").mkdir()
        found = self.found(self.host(PATH=str(self.root / "empty")))
        self.assertEqual([provider.name for provider in found.installed()], [homes.CODEX])
        self.assertTrue(found.provider(homes.CODEX).home_exists)
        self.assertIsNone(found.provider(homes.CODEX).program_file)

        self.assertEqual(self.found(self.host()).provider(homes.CLAUDE_CODE).installed, False)

    def test_the_shared_option(self) -> None:
        import argparse
        parser = argparse.ArgumentParser()
        homes.add_arguments(parser)
        self.assertFalse(parser.parse_args([]).allow_unshared_clone)
        self.assertTrue(parser.parse_args(["--allow-unshared-clone"]).allow_unshared_clone)


@unittest.skipUnless(SYMLINKS and POSIX, "the view from WSL is rebuilt from symlinks on a POSIX file system")
class TwoSidesCase(HomesCase):
    """The layout of "This machine (L1)", seen from WSL: ``drive`` stands in
    for the Windows drive, ``dev`` for the development clone."""

    def setUp(self) -> None:
        super().setUp()
        self.drive = self.root / "drive"
        self.win = self.drive / "Users" / "someone"
        self.dev = self.root / "dev"
        self.put(self.win / ".claude" / "CLAUDE.md", SECRET)
        self.put(self.win / ".claude" / "rules" / "a-rule.md", SECRET)
        self.put(self.win / ".claude" / "commands" / "c.md", SECRET)
        self.put(self.win / ".claude" / "skills" / "self-reflection" / "SKILL.md", SECRET)
        self.put(self.win / ".claude" / "skills" / "usage-cost" / "SKILL.md", SECRET)
        self.put(self.dev / "multiagent-collab" / "SKILL.md", SECRET)
        self.put(self.clone / "json-tools" / "SKILL.md", "a skill\n")

        claude = self.home / ".claude"
        (claude / "skills").mkdir(parents=True)
        for name in ("CLAUDE.md", "rules", "commands"):
            os.symlink(str(self.win / ".claude" / name), claude / name)
        for name in ("self-reflection", "usage-cost"):
            os.symlink(str(self.win / ".claude" / "skills" / name), claude / "skills" / name)
        os.symlink(str(self.dev / "multiagent-collab"), claude / "skills" / "multiagent-collab")
        self.put(claude / "skills" / "auth.json", SECRET)
        self.put(claude / "settings.json", SECRET)

        codex = self.home / ".codex"
        self.put(codex / "AGENTS.md", SECRET)
        self.put(codex / "config.toml", SECRET)
        self.put(codex / "auth.json", SECRET)
        self.put(codex / "skills" / "self-reflection" / "SKILL.md", SECRET)
        (self.home / ".agents" / "skills").mkdir(parents=True)
        os.symlink(str(self.dev / "multiagent-collab"), self.home / ".agents" / "skills" / "multiagent-collab")

        self.wsl = homes.Host(homes.WSL, {}, (str(self.drive),))
        self.claude, self.codex = claude, codex

    def sorter(self, host: homes.Host | None = None) -> homes.Classifier:
        return homes.Classifier(self.found(host or self.wsl))

    def test_rules_and_the_instruction_file_are_the_other_sides(self) -> None:
        sorter = self.sorter()
        for name in ("rules", "CLAUDE.md"):
            found = sorter.standing(self.claude / name)
            self.assertEqual((found.kind, found.side), (homes.OTHER_SIDE, homes.WINDOWS), name)
            self.assertFalse(found.writes)
            self.assertEqual(found.link, self.claude / name)
            self.assertEqual(found.target, str(self.win / ".claude" / name))
            self.assertEqual(found.real, self.win / ".claude" / name)
            self.assertIn("the windows side owns it", found.describe())

    def test_a_path_under_the_linked_rules_is_the_other_sides_too(self) -> None:
        found = self.sorter().standing(self.claude / "rules" / "avoid-bash" / "rule.md")
        self.assertEqual((found.kind, found.side), (homes.OTHER_SIDE, homes.WINDOWS))
        self.assertEqual(found.link, self.claude / "rules")
        self.assertIn(f"under the link {self.claude / 'rules'}", found.describe())

    def test_the_places_of_this_side(self) -> None:
        sorter = self.sorter()
        for path in (
            self.claude / "skills", self.claude / "agents", self.claude / "skills" / "json-tools",
            self.codex / "agents", self.codex / "AGENTS.md", self.codex / "config.toml",
            self.home / ".agents" / "skills",
        ):
            found = sorter.standing(path)
            self.assertEqual(found.kind, homes.THIS_SIDE, path)
            self.assertTrue(found.writes)
            self.assertFalse(found.through_link)
            self.assertEqual(found.describe(), "this side")

    def test_the_skill_links_to_the_other_homes_copies(self) -> None:
        sorter = self.sorter()
        for name in ("self-reflection", "usage-cost"):
            path = self.claude / "skills" / name
            found = sorter.entry(path)
            self.assertEqual((found.kind, found.side), (homes.LINK_OTHER_SIDE, homes.WINDOWS), name)
            self.assertEqual(found.target, str(self.win / ".claude" / "skills" / name))
            # The link is an entry of this side's directory: the path
            # itself is this run's, and what it leads to is not.
            self.assertEqual(sorter.standing(path).kind, homes.OTHER_SIDE)
            self.assertEqual(sorter.standing(path.parent).kind, homes.THIS_SIDE)

    def test_a_link_to_the_other_side_is_a_conflict_for_a_new_link(self) -> None:
        found = self.found(self.wsl)
        plan = fileops.Plan(found.roots(), stamp=self.stamp())
        plan.create_link(self.claude / "skills" / "self-reflection", self.clone / "json-tools")
        before = snapshot(self.root)
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertEqual(caught.exception.codes(), {fileops.CONFLICT})
        self.assertIn(str(self.win / ".claude" / "skills" / "self-reflection"), str(caught.exception))
        self.assertEqual(snapshot(self.root), before)

    def test_removing_such_a_link_leaves_the_other_sides_copy(self) -> None:
        found = self.found(self.wsl)
        link = self.claude / "skills" / "usage-cost"
        plan = fileops.Plan(found.roots(), stamp=self.stamp())
        plan.remove_link(link, expect_target=self.win / ".claude" / "skills" / "usage-cost")
        plan.apply()
        self.assertEqual(fsio.look(link).kind, fsio.ABSENT)
        self.assertEqual((self.win / ".claude" / "skills" / "usage-cost" / "SKILL.md").read_text(), SECRET)
        entry = fileops.read_record(found.roots()).get("home:.claude/skills/usage-cost")
        self.assertEqual(entry["kind"], "removed-link")
        self.assertTrue(entry["target"].startswith("raw:"))  # the user's link, kept as the user wrote it

    def test_the_collaboration_skill_is_left_to_its_own_setup(self) -> None:
        sorter = self.sorter()
        for path in (
            self.claude / "skills" / "multiagent-collab",
            self.home / ".agents" / "skills" / "multiagent-collab",
            self.codex / "skills" / "multiagent-collab",  # not there: still not setup's to create
        ):
            found = sorter.entry(path)
            self.assertEqual(found.kind, homes.OWN_SETUP, path)
            self.assertIn("managed by its own setup", found.describe())
        # The name means that only in a skills directory.
        self.assertEqual(sorter.entry(self.claude / "agents" / "multiagent-collab").kind, homes.ABSENT)

    def test_a_copy_and_the_other_entries(self) -> None:
        sorter = self.sorter()
        self.assertEqual(sorter.entry(self.codex / "skills" / "self-reflection").kind, homes.PLAIN)
        self.assertEqual(sorter.entry(self.codex / "skills" / "self-reflection").found, fsio.DIRECTORY)
        self.assertEqual(sorter.entry(self.claude / "skills" / "json-tools").kind, homes.ABSENT)
        os.symlink(str(self.clone / "json-tools"), self.claude / "skills" / "json-tools")
        self.assertEqual(sorter.entry(self.claude / "skills" / "json-tools").kind, homes.LINK_TO_CLONE)
        os.symlink(str(self.root / "gone"), self.claude / "skills" / "broken")
        self.assertEqual(sorter.entry(self.claude / "skills" / "broken").kind, homes.LINK_BROKEN)
        os.symlink(str(self.dev / "multiagent-collab"), self.claude / "skills" / "elsewhere")
        self.assertEqual(sorter.entry(self.claude / "skills" / "elsewhere").kind, homes.LINK_THIS_SIDE)

    def test_a_link_into_the_shared_clone_on_the_drive_is_a_link_into_the_clone(self) -> None:
        shared = self.drive / "work" / "clone"
        self.put(shared / "json-tools" / "SKILL.md", "a skill\n")
        found = homes.resolve(Locations(home=self.home, clone=shared, real_home=True), self.wsl)
        self.assertIs(homes.require_shared_clone(found).shared, True)
        link = self.claude / "skills" / "json-tools"
        plan = fileops.Plan(found.roots(), stamp=self.stamp())
        plan.create_link(link, shared / "json-tools")
        plan.apply()
        # The text is this side's way to the clone; the record names no machine.
        self.assertEqual(os.readlink(link), str(shared / "json-tools"))
        self.assertEqual(
            fileops.read_record(found.roots()).get("home:.claude/skills/json-tools"),
            {"kind": "link", "target": "clone:json-tools"},
        )
        sorter = homes.Classifier(found)
        self.assertEqual(sorter.entry(link).kind, homes.LINK_TO_CLONE)
        self.assertEqual(sorter.entry(self.claude / "skills" / "usage-cost").kind, homes.LINK_OTHER_SIDE)

    def test_a_link_to_an_unmounted_drive_is_still_the_other_sides(self) -> None:
        host = homes.Host(homes.WSL, {}, ())
        os.symlink("/mnt/q/Users/someone/.codex/agents", self.codex / "agents")
        found = homes.Classifier(self.found(host)).standing(self.codex / "agents")
        self.assertEqual((found.kind, found.side), (homes.OTHER_SIDE, homes.WINDOWS))

    def test_a_home_named_on_the_other_side_is_the_other_sides(self) -> None:
        host = homes.Host(homes.WSL, {"CODEX_HOME": str(self.win / ".codex")}, (str(self.drive),))
        found = self.found(host)
        sorter = homes.Classifier(found)
        codex = found.provider(homes.CODEX)
        self.assertEqual(codex.anchor, "codex-home")
        for name in ("agents", "instructions", "config"):
            standing = sorter.standing(codex.place(name).path)
            self.assertEqual((standing.kind, standing.link), (homes.OTHER_SIDE, None), name)
        self.assertEqual(sorter.standing(codex.place("skills").path).kind, homes.THIS_SIDE)

    def test_on_a_plain_linux_the_same_links_are_shared_on_this_side(self) -> None:
        sorter = self.sorter(self.host(homes.LINUX))
        found = sorter.standing(self.claude / "rules")
        self.assertEqual(found.kind, homes.SHARED)
        self.assertTrue(found.writes and found.through_link)
        self.assertIn("written once, where the link leads", found.describe())
        # Written through a link only when the user says so.
        roots = self.found(self.host(homes.LINUX)).roots()
        plan = fileops.Plan(roots, stamp=self.stamp())
        plan.write_file(self.claude / "rules" / "x.md", "x\n")
        with self.assertRaises(fileops.SymlinkedConfigPath):
            plan.describe()

    def test_two_names_for_one_directory_are_handled_once(self) -> None:
        (self.claude / "agents").mkdir()
        os.symlink(str(self.claude / "agents"), self.codex / "agents")
        sorter = self.sorter()
        first = sorter.standing(self.claude / "agents")
        second = sorter.standing(self.codex / "agents")
        self.assertEqual(first.kind, homes.THIS_SIDE)
        self.assertEqual((second.kind, second.first), (homes.HANDLED, self.claude / "agents"))
        self.assertFalse(second.writes)
        self.assertIn("already handled", second.describe())
        # Asked again, each answer is the same.
        self.assertEqual(sorter.standing(self.claude / "agents").kind, homes.THIS_SIDE)
        self.assertEqual(sorter.standing(self.codex / "agents").kind, homes.HANDLED)
        # A file below is told apart by its own name.
        self.assertEqual(sorter.standing(self.claude / "agents" / "coder.md").kind, homes.THIS_SIDE)
        self.assertEqual(sorter.standing(self.codex / "agents" / "coder.toml").kind, homes.SHARED)
        self.assertEqual(sorter.standing(self.codex / "agents" / "coder.md").kind, homes.HANDLED)

    def test_what_cannot_be_looked_at_is_unknown(self) -> None:
        sorter = self.sorter()
        with mock.patch.object(fsio, "look", side_effect=SetupError("x: cannot be read: refused")):
            standing = sorter.standing(self.claude / "agents")
            entry = sorter.entry(self.claude / "skills" / "json-tools")
        self.assertEqual((standing.kind, standing.writes), (homes.UNKNOWN, False))
        self.assertIn("nothing is written", standing.describe())
        self.assertEqual(entry.kind, homes.UNKNOWN)

    def test_the_report_matches_the_layout(self) -> None:
        found = homes.report(self.found(self.wsl))
        self.assertEqual((found["side"], found["other_side"], found["scratch"]), ("wsl", "windows", False))
        claude, codex = found["providers"]
        places = {place["name"]: place for place in claude["places"]}
        self.assertEqual(
            {name: place["standing"] for name, place in places.items()},
            {"skills": "this-side", "agents": "this-side", "rules": "other-side", "instructions": "other-side"},
        )
        self.assertFalse(places["agents"]["present"])
        self.assertEqual(places["rules"]["entries"], [])  # the other side's directory is not listed
        self.assertEqual(
            {entry["name"]: entry["kind"] for entry in places["skills"]["entries"]},
            {
                "multiagent-collab": "own-setup",
                "self-reflection": "link-other-side",
                "usage-cost": "link-other-side",
            },
        )
        places = {place["name"]: place for place in codex["places"]}
        self.assertEqual({place["standing"] for place in places.values()}, {"this-side"})
        self.assertEqual(
            {entry["name"]: entry["kind"] for entry in places["skills"]["entries"]},
            {"multiagent-collab": "own-setup"},
        )
        self.assertEqual(
            {entry["name"]: entry["kind"] for entry in places["old-skills"]["entries"]},
            {"self-reflection": "plain"},
        )
        self.assertTrue(claude["installed"] and codex["installed"])

    def test_the_report_reads_no_file_and_changes_nothing(self) -> None:
        before = snapshot(self.root)
        opened: list[str] = []
        real_open = open

        def watching(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", watching), mock.patch.object(Path, "read_bytes", side_effect=AssertionError):
            found = homes.report(self.found(self.wsl))
        text = json.dumps(found) + "\n".join(homes.report_lines(found))
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual([name for name in opened if str(self.root) in name], [])
        self.assertNotIn(SECRET, text)
        self.assertNotIn("auth.json", text)

    def test_the_text_of_the_report(self) -> None:
        lines = homes.report_lines(homes.report(self.found(self.wsl)))
        self.assertEqual(lines[0], "side: wsl (the other side is windows)")
        self.assertIn(f"  rules: {self.claude / 'rules'}", lines)
        self.assertIn(
            f"    other side (windows): a link to {self.win / '.claude' / 'rules'}; skipped here, "
            "the windows side owns it",
            lines,
        )
        self.assertIn(f"  agents: {self.claude / 'agents'} [absent]", lines)
        self.assertIn(
            f"    - multiagent-collab: managed by its own setup (a link to {self.dev / 'multiagent-collab'}); left alone",
            lines,
        )
        self.assertIn("claude-code: installed", lines)


class CloneCase(HomesCase):
    def wsl(self) -> homes.Host:
        return homes.Host(homes.WSL, {}, (str(self.root / "drive"),))

    def at(self, clone: Path, host: homes.Host, real_home: bool = True) -> homes.Homes:
        return homes.resolve(Locations(home=self.home, clone=clone, real_home=real_home), host)

    def test_a_clone_inside_wsl_is_refused(self) -> None:
        found = self.at(self.clone, self.wsl())
        self.assertIs(homes.clone_standing(found).shared, False)
        with self.assertRaises(SetupError) as caught:
            homes.require_shared_clone(found)
        text = str(caught.exception)
        self.assertIn(str(self.clone), text)
        self.assertIn("clone the repository to a directory on a Windows drive", text)
        self.assertIn("/mnt/<drive>/", text)
        self.assertIn("run setup from that clone", text)
        self.assertIn("--allow-unshared-clone", text)

    def test_the_flag_allows_it(self) -> None:
        found = self.at(self.clone, self.wsl())
        self.assertIs(homes.require_shared_clone(found, allow_unshared=True).shared, False)

    @unittest.skipUnless(POSIX, "the view from WSL: a POSIX path under a mount point")
    def test_a_clone_on_a_windows_drive_is_shared(self) -> None:
        clone = self.root / "drive" / "work" / "clone"
        clone.mkdir(parents=True)
        self.assertIs(homes.require_shared_clone(self.at(clone, self.wsl())).shared, True)

    @unittest.skipUnless(SYMLINKS and POSIX, "the view from WSL is rebuilt from symlinks on a POSIX file system")
    def test_the_real_path_of_the_clone_is_what_counts(self) -> None:
        clone = self.root / "drive" / "work" / "clone"
        clone.mkdir(parents=True)
        os.symlink(str(clone), self.root / "near")
        self.assertIs(homes.clone_standing(self.at(self.root / "near", self.wsl())).shared, True)
        os.symlink(str(self.clone), self.root / "drive" / "looks-shared")
        found = self.at(self.root / "drive" / "looks-shared", self.wsl())
        self.assertIs(homes.clone_standing(found).shared, False)

    def test_a_scratch_home_is_not_asked(self) -> None:
        found = self.at(self.clone, self.wsl(), real_home=False)
        standing = homes.require_shared_clone(found)
        self.assertIsNone(standing.shared)
        self.assertIn("scratch home", standing.why)

    def test_a_plain_linux_is_not_asked(self) -> None:
        found = self.at(self.clone, self.host(homes.LINUX))
        standing = homes.require_shared_clone(found)
        self.assertIsNone(standing.shared)
        self.assertIn("no Windows side", standing.why)

    @unittest.skipIf(WINDOWS, "on Windows a scratch clone is on a local drive")
    def test_seen_as_windows_a_path_that_is_no_drive_path_is_refused(self) -> None:
        found = self.at(self.clone, self.host(homes.WINDOWS))
        self.assertIs(homes.clone_standing(found).shared, False)
        with self.assertRaises(SetupError):
            homes.require_shared_clone(found)

    @unittest.skipUnless(WINDOWS, "needs Windows")
    def test_on_windows_a_clone_on_a_local_drive_is_shared(self) -> None:
        found = self.at(self.clone, homes.Host.current())
        self.assertEqual(found.host.side, homes.WINDOWS)
        self.assertIs(homes.require_shared_clone(found).shared, True)

    def test_the_command_reports_and_does_not_refuse(self) -> None:
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.wsl())):
            code, out, err = support.run("homes", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("  shared by both sides: not asked (a scratch home (--home))", out.splitlines())


class LinkCase(HomesCase):
    """Links through a plan: a symlink on Linux, a junction on Windows."""

    def setUp(self) -> None:
        super().setUp()
        self.target = self.clone / "json-tools"
        self.sentinel = self.put(self.target / "SKILL.md", "the skill\n")
        self.put(self.target / "scripts" / "tool.py", "pass\n")
        self.found_homes = self.found()
        self.link_roots = self.found_homes.roots()
        self.link = self.home / ".claude" / "skills" / "json-tools"

    def new_plan(self, **options) -> fileops.Plan:
        return fileops.Plan(self.link_roots, stamp=self.stamp(), **options)

    def linkable(self) -> None:
        if not (SYMLINKS or WINDOWS):
            self.skipTest("this system makes neither a symlink nor a junction")

    def clone_tree(self) -> dict:
        return snapshot(self.clone)

    def test_create_read_back_and_remove(self) -> None:
        self.linkable()
        clone_before = self.clone_tree()
        plan = self.new_plan()
        plan.create_link(self.link, self.target)
        self.assertTrue(plan.apply().changed)

        seen = fsio.look(self.link)
        self.assertEqual((seen.kind, seen.directory), (fsio.LINK, True))
        # The text is the clone's path as this side writes it.
        self.assertTrue(fsio.same_target(seen.target, str(self.target)))
        self.assertEqual(fsio.is_junction(self.link), WINDOWS)
        self.assertEqual((self.link / "SKILL.md").read_text(encoding="utf-8"), "the skill\n")
        sorter = homes.Classifier(self.found_homes)
        self.assertEqual(sorter.entry(self.link).kind, homes.LINK_TO_CLONE)

        # A second run changes nothing.
        again = self.new_plan()
        again.create_link(self.link, self.target)
        self.assertFalse(again.apply().changed)

        gone = self.new_plan()
        gone.remove_link(self.link)
        gone.apply()
        self.assertEqual(fsio.look(self.link).kind, fsio.ABSENT)
        self.assertEqual(self.clone_tree(), clone_before)
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "the skill\n")

    def test_the_record_holds_anchors_and_no_machine_path(self) -> None:
        self.linkable()
        plan = self.new_plan()
        plan.create_link(self.link, self.target)
        plan.apply()
        raw = self.manifest_file.read_bytes().decode("utf-8")
        record = json.loads(raw)
        self.assertEqual(
            record["entries"]["home:.claude/skills/json-tools"], {"kind": "link", "target": "clone:json-tools"}
        )
        for machine in (str(self.root), self.root.as_posix(), str(self.root).replace("\\", "\\\\"), self.root.name):
            self.assertNotIn(machine, raw)

    def test_a_home_outside_the_users_home_is_recorded_by_its_anchor(self) -> None:
        self.linkable()
        outside = self.root / "elsewhere" / "claude-home"
        outside.mkdir(parents=True)
        found = self.found(self.host(CLAUDE_CONFIG_DIR=str(outside)))
        link = found.provider(homes.CLAUDE_CODE).place("skills").path / "json-tools"
        plan = fileops.Plan(found.roots(), stamp=self.stamp())
        plan.create_link(link, self.target)
        plan.apply()
        self.assertEqual(fsio.look(link).kind, fsio.LINK)
        raw = self.manifest_file.read_bytes().decode("utf-8")
        self.assertEqual(
            json.loads(raw)["entries"]["claude-code-home:skills/json-tools"],
            {"kind": "link", "target": "clone:json-tools"},
        )
        self.assertNotIn(self.root.name, raw)
        fileops.plan_reversal(found.roots(), stamp=self.stamp()).apply()
        self.assertEqual(fsio.look(link).kind, fsio.ABSENT)
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "the skill\n")

    def test_the_reversal_removes_the_link_and_nothing_of_the_clone(self) -> None:
        self.linkable()
        clone_before = self.clone_tree()
        plan = self.new_plan()
        plan.create_link(self.link, self.target)
        plan.apply()
        fileops.plan_reversal(self.link_roots, stamp=self.stamp()).apply()
        self.assertEqual(fsio.look(self.link).kind, fsio.ABSENT)
        self.assertEqual(self.clone_tree(), clone_before)

    def test_an_unmanaged_directory_in_the_way_is_a_conflict(self) -> None:
        mine = self.put(self.link / "SKILL.md", "the user's own copy\n")
        other = self.home / ".claude" / "skills" / "csv-tools"
        self.put(self.clone / "csv-tools" / "SKILL.md", "another\n")
        plan = self.new_plan()
        plan.create_link(other, self.clone / "csv-tools")   # would be fine alone
        plan.create_link(self.link, self.target)
        before = snapshot(self.root)
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertEqual(caught.exception.codes(), {fileops.CONFLICT})
        self.assertIn(f"{self.link}: a directory is there and setup did not make it", str(caught.exception))
        # Stopped before any write: not the other link, not the record.
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(mine.read_text(encoding="utf-8"), "the user's own copy\n")

    def test_an_unmanaged_file_in_the_way_is_a_conflict(self) -> None:
        self.put(self.link, "a file\n")
        plan = self.new_plan()
        plan.create_link(self.link, self.target)
        with self.assertRaises(fileops.PlanError) as caught:
            plan.describe()
        self.assertIn("a file is there and setup did not make it", str(caught.exception))

    def test_an_unmanaged_link_in_the_way_is_a_conflict_that_names_its_target(self) -> None:
        self.linkable()
        elsewhere = self.root / "elsewhere-skill"
        self.put(elsewhere / "SKILL.md", "theirs\n")
        self.link.parent.mkdir(parents=True)
        fsio.make_link(str(elsewhere), self.link, True)
        plan = self.new_plan()
        plan.create_link(self.link, self.target)
        before = snapshot(self.root)
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertEqual(caught.exception.codes(), {fileops.CONFLICT})
        self.assertIn("a link to ", str(caught.exception))
        self.assertIn("elsewhere-skill is there and setup did not make it", str(caught.exception))
        self.assertEqual(snapshot(self.root), before)
        fsio.remove_link(self.link)
        self.assertEqual((elsewhere / "SKILL.md").read_text(encoding="utf-8"), "theirs\n")

    def test_no_link_is_made_inside_the_clone(self) -> None:
        self.put(self.clone / "csv-tools" / "SKILL.md", "another\n")
        plan = self.new_plan()
        plan.create_link(self.clone / "linked", self.clone / "csv-tools")
        with self.assertRaises(fileops.PlanError) as caught:
            plan.apply()
        self.assertEqual(caught.exception.codes(), {fileops.OUTSIDE})
        self.assertEqual(fsio.look(self.clone / "linked").kind, fsio.ABSENT)

    def test_remove_link_refuses_what_is_not_a_link(self) -> None:
        with self.assertRaises(SetupError) as caught:
            fsio.remove_link(self.target)
        self.assertIn("it is not a link", str(caught.exception))
        empty = self.root / "empty-directory"
        empty.mkdir()
        with self.assertRaises(SetupError):
            fsio.remove_link(empty)
        self.assertTrue(empty.is_dir())
        with self.assertRaises(SetupError):
            fsio.remove_link(self.sentinel)
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "the skill\n")

    def test_fsio_link_round_trip(self) -> None:
        self.linkable()
        link = self.root / "a-link"
        fsio.make_link(str(self.target), link, True)
        self.assertTrue(fsio.same_target(fsio.read_link(link), str(self.target)))
        self.assertEqual(sorted(os.listdir(link)), ["SKILL.md", "scripts"])
        fsio.remove_link(link)
        self.assertFalse(os.path.lexists(link))
        self.assertEqual(sorted(os.listdir(self.target)), ["SKILL.md", "scripts"])

    @unittest.skipIf(WINDOWS, "the refusal on a system without junctions")
    def test_a_junction_is_made_on_windows_only(self) -> None:
        with self.assertRaises(SetupError) as caught:
            fsio.make_junction(str(self.target), self.root / "j")
        self.assertIn("on Windows only", str(caught.exception))
        self.assertFalse(fsio.is_junction(self.target))
        self.assertFalse(fsio.is_junction(self.root / "not-there"))


@unittest.skipUnless(WINDOWS, "junctions are made on Windows")
class JunctionCase(HomesCase):
    """Run under Windows Python. The scratch tree is in the Windows
    temporary directory, on a local drive, where a junction can lead."""

    def setUp(self) -> None:
        super().setUp()
        self.target = self.clone / "json-tools"
        self.sentinel = self.put(self.target / "SKILL.md", "the skill\n")
        self.junction = self.root / "a-junction"

    def assert_target_whole(self) -> None:
        self.assertEqual(os.listdir(self.target), ["SKILL.md"])
        self.assertEqual(self.sentinel.read_bytes(), b"the skill\n")

    def check_round_trip(self, **how) -> None:
        fsio.make_junction(str(self.target), self.junction, **how)
        self.assertTrue(fsio.is_junction(self.junction))
        self.assertFalse(os.path.islink(self.junction))
        seen = fsio.look(self.junction)
        self.assertEqual((seen.kind, seen.directory), (fsio.LINK, True))
        self.assertTrue(fsio.same_target(seen.target, str(self.target)))
        self.assertFalse(seen.target.startswith("\\\\?\\"))
        self.assertEqual((self.junction / "SKILL.md").read_bytes(), b"the skill\n")
        fsio.remove_link(self.junction)
        self.assertFalse(os.path.lexists(self.junction))
        self.assert_target_whole()

    def test_create_read_back_remove(self) -> None:
        self.check_round_trip()

    def test_create_through_mklink(self) -> None:
        self.check_round_trip(use_mklink=True)

    def test_make_link_makes_a_junction_for_a_directory(self) -> None:
        fsio.make_link(str(self.target), self.junction, True)
        self.assertTrue(fsio.is_junction(self.junction))
        fsio.remove_link(self.junction)
        self.assert_target_whole()

    def test_the_reparse_tag_tells_a_junction_without_isjunction(self) -> None:
        fsio.make_junction(str(self.target), self.junction)
        with mock.patch.object(os.path, "isjunction", None, create=True):
            self.assertTrue(fsio.is_junction(self.junction))
            self.assertFalse(fsio.is_junction(self.target))
            self.assertFalse(fsio.is_junction(self.root / "not-there"))
        fsio.remove_link(self.junction)

    def test_a_junction_is_not_followed_on_removal(self) -> None:
        self.put(self.target / "deep" / "inner.txt", "inner\n")
        fsio.make_junction(str(self.target), self.junction)
        fsio.remove_link(self.junction)
        self.assertFalse(os.path.lexists(self.junction))
        self.assertEqual((self.target / "deep" / "inner.txt").read_bytes(), b"inner\n")
        self.assertEqual(self.sentinel.read_bytes(), b"the skill\n")

    def test_a_junction_to_a_network_name_or_a_file_is_refused(self) -> None:
        for target in ("\\\\wsl.localhost\\Distro\\home", "\\\\server\\share\\x", "relative\\path", str(self.sentinel)):
            with self.assertRaises(SetupError, msg=target):
                fsio.make_junction(target, self.junction)
            self.assertFalse(os.path.lexists(self.junction), target)

    def test_nothing_is_made_where_something_is(self) -> None:
        self.put(self.junction / "kept.txt", "kept\n")
        with self.assertRaises(SetupError):
            fsio.make_junction(str(self.target), self.junction)
        self.assertEqual((self.junction / "kept.txt").read_bytes(), b"kept\n")

    def test_mklink_refuses_a_path_cmd_would_read_as_syntax(self) -> None:
        odd = self.root / "a&b"
        with self.assertRaises(SetupError) as caught:
            fsio.make_junction(str(self.target), odd, use_mklink=True)
        self.assertIn("cmd.exe", str(caught.exception))
        self.assertFalse(os.path.lexists(odd))
        # The same name is no trouble without cmd.exe.
        fsio.make_junction(str(self.target), odd)
        self.assertTrue(fsio.is_junction(odd))
        fsio.remove_link(odd)
        self.assert_target_whole()

    def test_a_junction_in_a_home_is_a_link_into_the_clone(self) -> None:
        found = self.found(homes.Host.current())
        link = self.home / ".claude" / "skills" / "json-tools"
        plan = fileops.Plan(found.roots(), stamp=self.stamp())
        plan.create_link(link, self.target)
        plan.apply()
        self.assertTrue(fsio.is_junction(link))
        sorter = homes.Classifier(found)
        self.assertEqual(sorter.entry(link).kind, homes.LINK_TO_CLONE)
        # Below a junction a path is a linked config path, as below a symlink.
        self.assertEqual(sorter.standing(link / "SKILL.md").kind, homes.SHARED)
        problem = fileops.symlink_in_the_way(found.roots(), link / "SKILL.md")
        self.assertEqual(problem.link, link)
        fileops.plan_reversal(found.roots(), stamp=self.stamp()).apply()
        self.assertFalse(os.path.lexists(link))
        self.assert_target_whole()

    def test_a_users_junction_that_was_removed_is_put_back_as_a_junction(self) -> None:
        elsewhere = self.root / "elsewhere-skill"
        self.put(elsewhere / "SKILL.md", "theirs\n")
        link = self.home / ".claude" / "skills" / "old-skill"
        link.parent.mkdir(parents=True)
        fsio.make_junction(str(elsewhere), link)
        found = self.found(homes.Host.current())
        plan = fileops.Plan(found.roots(), stamp=self.stamp())
        plan.remove_link(link)
        plan.apply()
        self.assertFalse(os.path.lexists(link))
        self.assertEqual((elsewhere / "SKILL.md").read_bytes(), b"theirs\n")
        entry = fileops.read_record(found.roots()).get("home:.claude/skills/old-skill")
        self.assertEqual((entry["kind"], entry["junction"]), ("removed-link", True))
        fileops.plan_reversal(found.roots(), stamp=self.stamp()).apply()
        self.assertTrue(fsio.is_junction(link))
        self.assertTrue(fsio.same_target(fsio.read_link(link), str(elsewhere)))
        fsio.remove_link(link)
        self.assertEqual((elsewhere / "SKILL.md").read_bytes(), b"theirs\n")

    def test_the_windows_homes(self) -> None:
        with mock.patch.dict(os.environ, {"USERPROFILE": str(self.home)}):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            os.environ.pop("CODEX_HOME", None)
            import argparse
            from wfsetup import locations
            where = locations.from_args(argparse.Namespace(home=None, project=None))
            found = homes.resolve(where)
        self.assertTrue(where.real_home)
        self.assertEqual(found.home, self.home)
        self.assertEqual(found.provider(homes.CODEX).home, self.home / ".codex")
        self.assertEqual(found.provider(homes.CODEX).place("skills").path, self.home / ".agents" / "skills")
        self.assertEqual(found.provider(homes.CLAUDE_CODE).home, self.home / ".claude")
        self.assertEqual(found.host.side, homes.WINDOWS)


if __name__ == "__main__":
    unittest.main()
