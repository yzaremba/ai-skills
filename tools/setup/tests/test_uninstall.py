"""Tests for ``uninstall``, and the round trip of a whole install (R8.1).

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

Every home, project and clone is a scratch directory; no test touches a real
home. The clone is the fixture clone of ``test_entry`` (roles, dictionaries,
entry points) with the v1 names of ``test_migrate`` in it, and the known v1
hashes are that module's table.

The round trip: a home, a project and a clone are built and photographed
(``picture``: every path, its kind, a link's own text and form, a file's
bytes, and on POSIX the permission bits of files and directories). Then the
commands that write are run through the command line, then ``uninstall``,
and the photograph must be the same.
"""
from __future__ import annotations

import io
import json
import os
import random
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import support
from fileops_support import POSIX, SYMLINKS
from test_entry import DEFAULT_ON, OVERRIDE, USER_JSON, USER_TOML, EntryCase
from test_migrate import CLAUDE_MD, EDITED, IMPORTS, OTHER_BLOCK, MigrateCase, v1
from wfsetup import fileops, fsio, homes, migrate, uninstall
from wfsetup.locations import Locations
from wfsetup.manifest import Manifest

CONFIG_PLAIN = (
    b'# My Codex settings.\nmodel = "gpt-mine"   # the one I like\napproval_policy = "on-request"\n\n'
    b'[features]\nfast = true\n\n[mcp_servers.docs]\ncommand = "docs-server"\n'
)
CONFIG_SANDBOX = b'sandbox_mode = "workspace-write"\n' + CONFIG_PLAIN
CONFIG_AGENTS = CONFIG_PLAIN + b'\n[agents]\njob_max_runtime_seconds = 600\n'
PROJECT_SETTINGS = "# This project's own settings.\n" + DEFAULT_ON + OVERRIDE
USER_SETTINGS = '# Mine, with a comment.\nschema_version = 1\n\n[process]\ndocs_dir = "notes"   # where I keep them\n'


def picture(root: Path) -> dict[str, tuple]:
    """Every path below ``root``. A link is not followed: its own text as
    the system gives it, whether it leads to a directory, and whether it is
    a junction. A file with its bytes; on POSIX a file and a directory with
    their permission bits."""
    found: dict[str, tuple] = {}
    for directory, names, files in os.walk(root):
        for name in [*names, *files]:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            seen = fsio.look(path)
            status = os.lstat(path)
            mode = stat.S_IMODE(status.st_mode) if POSIX else None
            if seen.kind == fsio.LINK:
                found[relative] = ("link", os.readlink(path), seen.directory, seen.junction)
            elif seen.kind == fsio.DIRECTORY:
                found[relative] = ("directory", mode)
            else:
                found[relative] = ("file", path.read_bytes(), mode)
        # A link to a directory is listed, and not entered.
        names[:] = [name for name in names if fsio.look(Path(directory) / name).kind != fsio.LINK]
    return found


class Crash(BaseException):
    """The process is gone."""


class UninstallCase(MigrateCase, EntryCase):
    """Both providers in a scratch home, a project, and the fixture clone
    with roles, entry points and the v1 names."""

    def setUp(self) -> None:
        super().setUp()
        self.elsewhere = self.root / "elsewhere"
        self.state = self.home / ".agents" / "workflow-setup"
        self.project_state = self.project / ".agents" / "workflow-setup"
        self.project_record = self.project_state / "manifest.json"
        self.edited_copies: list[Path] = []

    # --- Running -------------------------------------------------------------

    def cli(self, *argv: str, host: homes.Host | None = None) -> tuple[int, str, str]:
        host = host or self.host
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: host)):
            return support.run(*argv)

    def done(self, *argv: str, code: int = 0, **how) -> str:
        got, out, err = self.cli(*argv, **how)
        self.assertEqual((got, err), (code, ""), "\n".join([str(argv), *out.splitlines()[-12:]]))
        return out

    @property
    def at_home(self) -> tuple[str, str]:
        return ("--home", str(self.home))

    @property
    def in_project(self) -> tuple[str, str]:
        return ("--project", str(self.project))

    def uninstall(self, *argv: str, code: int = 0, project: bool = False, **how) -> dict:
        places = [*self.at_home, *(self.in_project if project else ())]
        got, out, err = self.cli("uninstall", "--json", *places, *argv, **how)
        self.assertEqual(got, code, out + err)
        if code != 2:
            self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["exit_code"], code)
        return report

    def kept(self, report: dict, path: Path) -> dict:
        for item in report["kept"]:
            if item["path"] == str(path):
                return item
        self.fail(f"{path} is not kept in {json.dumps(report['kept'], indent=1)}")

    def pictures(self) -> dict[str, dict]:
        return {
            "home": picture(self.home), "project": picture(self.project), "clone": picture(self.clone),
            "elsewhere": picture(self.elsewhere) if self.elsewhere.exists() else {},
        }

    def assertAsAtTheStart(self, before: dict[str, dict]) -> None:
        after = self.pictures()
        for name in before:
            self.assertEqual(set(after[name]), set(before[name]), name)
            for path in before[name]:
                self.assertEqual(after[name][path], before[name][path], f"{name}: {path}")
        self.assertNoState()

    def assertNoState(self) -> None:
        self.assertNothingAt(self.state)
        self.assertNothingAt(self.project_state)
        # Nor what a run leaves while it makes a state directory.
        for root in (self.home, self.project):
            self.assertEqual([name for name in os.listdir(root) if name.startswith(".wfsetup-")], [], root)

    def home_without_state(self) -> dict[str, tuple]:
        return {name: what for name, what in picture(self.home).items() if "workflow-setup" not in name}

    def backups(self, state: Path) -> list[str]:
        """The files under the backups directory of a state, by path."""
        return sorted(name for name, what in picture(state).items() if name.startswith("backups/") and what[0] == "file")

    def unlisted(self, state: Path, anchor: str, name: str = "mine.md", data: bytes = b"the only copy\n") -> Path:
        """A file under a backups directory that no record lists."""
        return self.data(state / "backups" / "20260101T000000.000000Z" / anchor / ".claude" / name, data)

    def discard(self, *argv: str, code: int = 0, answer: str | None = None, project: bool = False) -> tuple[str, str]:
        """``uninstall --discard-backups``. Standard input is no terminal,
        unless ``answer`` is what is typed at one."""
        places = [*self.at_home, *(self.in_project if project else ())]
        stdin = io.StringIO()
        stdin.isatty = lambda: answer is not None  # type: ignore[method-assign]
        asked: list[str] = []

        def typed(prompt: str = "") -> str:
            asked.append(prompt)
            return answer or ""

        with mock.patch.object(sys, "stdin", stdin), mock.patch("builtins.input", typed):
            got, out, err = self.cli("uninstall", "--discard-backups", *argv, *places)
        self.assertEqual(got, code, out + err)
        self.assertEqual(len(asked), 0 if answer is None else 1, out + err)
        return out, err

    # --- Building ------------------------------------------------------------

    def chmod(self, path: Path, mode: int) -> None:
        if POSIX:
            os.chmod(path, mode)

    def claude_home(self, crlf: bool = False, v1_copies: bool = True) -> None:
        claude = self.claude
        text = CLAUDE_MD if v1_copies else CLAUDE_MD.replace(IMPORTS, "")
        self.data(claude / "CLAUDE.md", text.replace("\n", "\r\n") if crlf else text)
        self.chmod(claude / "CLAUDE.md", 0o640)
        self.data(claude / "settings.json", USER_JSON)
        self.data(claude / "commands" / "note.md", "A command of the user's.\n")
        self.data(self.rules / "my-own-rule.md", "Mine.\n")
        self.data(self.agents / "mine.md", "---\nname: mine\n---\n\nAn agent of the user's.\n")
        self.data(self.claude_skills / "mine" / "SKILL.md", "---\nname: mine\n---\n\nA skill of the user's.\n")
        # The collaboration skill's link, made by its own setup.
        fsio.make_link(str(self.clone / "multiagent-collab"), self.claude_skills / "multiagent-collab", True)
        if not v1_copies:
            return
        self.rule_copies(self.rules)
        agent = v1(migrate.V1_AGENT_SOURCE)
        self.data(self.agents / "sprint-coder.md", agent.replace(b"\n", b"\r\n") if crlf else agent)
        # A v1 copy, every file a committed version: removed, and linked.
        copy = self.copy(self.claude_skills / "self-reflection", "self-reflection", 0)
        self.chmod(copy, 0o750)
        self.chmod(copy / "SKILL.md", 0o600)
        self.copy(self.claude_skills / "usage-cost", "usage-cost")
        self.chmod(self.claude_skills / "usage-cost" / "scripts", 0o700)
        # A copy edited by hand: kept, until --remove-stale names it.
        edited = self.copy(self.claude_skills / "json-tools", "json-tools")
        self.data(edited / "SKILL.md", EDITED)
        self.data(edited / "notes" / "mine.md", "What I changed.\n")
        self.edited_copies.append(edited)
        # A link to another home's copy of a v1 skill.
        theirs = self.copy(self.elsewhere / ".claude" / "skills" / "csv-tools", "csv-tools")
        fsio.make_link(str(theirs), self.claude_skills / "csv-tools", True)

    def codex_home(self, config: bytes | None = CONFIG_PLAIN, v1_copies: bool = True) -> None:
        codex = self.codex
        self.data(self.agents_md, "# Mine\n\nBe brief.\n\n" + OTHER_BLOCK)
        if config is not None:
            self.data(codex / "config.toml", config)
            self.chmod(codex / "config.toml", 0o600)
        self.data(self.old_skills / ".system" / "note", "Codex's own.\n")
        self.codex_skills.mkdir(parents=True)
        fsio.make_link(str(self.clone / "multiagent-collab"), self.codex_skills / "multiagent-collab", True)
        if not v1_copies:
            return
        edited = self.old_skills / "self-reflection"
        self.data(edited / "SKILL.md", EDITED)
        self.data(edited / "agents" / "openai.yaml", "policy: {}\n")
        self.edited_copies.append(edited)

    def a_project(self) -> None:
        project = self.project
        self.data(project / ".gitignore", "node_modules/\n*.log\n")
        self.data(project / ".claude" / "settings.json", USER_JSON)
        self.data(project / ".codex" / "config.toml", USER_TOML)
        self.data(project / ".agents" / "workflow.toml", PROJECT_SETTINGS)
        self.data(project / "src" / "main.py", "print('the project')\n")

    def start(self, **how) -> dict[str, dict]:
        """The whole starting state, and its photograph."""
        config = how.pop("config", CONFIG_PLAIN)
        self.claude_home(**how)
        self.codex_home(config=config, v1_copies=how.get("v1_copies", True))
        self.a_project()
        return self.pictures()

    def stale(self) -> list[str]:
        return [part for path in self.edited_copies for part in ("--remove-stale", str(path))]

    def install(self, *render: str, migrate_v1: bool = True, project: bool = True, codex: tuple[str, ...] = ()) -> None:
        """Every command that writes, as the user would run them. ``render``
        goes to every run of it, ``codex`` with --apply-codex-settings."""
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home)
        if project:
            self.done("init", "--yes", "--rewrite-settings", *self.at_home, *self.in_project)
        first = ["--migrate-v1", *self.stale()] if migrate_v1 else []
        self.done("render", *first, "--apply-codex-settings", *codex, *render, *self.at_home)
        if project:
            self.done("render", *render, *self.at_home, *self.in_project)
            # A second run writes nothing.
            before = self.pictures()
            out = self.done("render", "--json", *render, *self.at_home, *self.in_project)
            self.assertEqual(json.loads(out)["plan"], [])
            self.assertEqual(self.pictures(), before)

    def take_back(self, project: bool = True) -> None:
        if project:
            report = self.uninstall(project=True)
            self.assertEqual(report["kept"], [])
        report = self.uninstall()
        self.assertEqual(report["kept"], [])


# --- The round trip (R8.1) -----------------------------------------------------

class RoundTripCase(UninstallCase):
    def test_init_render_and_uninstall_leave_every_path_link_and_byte_as_at_the_start(self) -> None:
        before = self.start()
        self.install()
        # Something of everything was installed.
        self.assertLinked(self.claude_skills / "self-reflection", self.clone / "self-reflection")
        self.assertLinked(self.claude_skills / "json-tools", self.clone / "json-tools")
        self.assertLinked(self.claude_skills / "csv-tools", self.clone / "csv-tools")
        self.assertNothingAt(self.rules / "prd-implementation.md")
        self.assertNothingAt(self.old_skills / "self-reflection")
        self.assertNotIn("@rules/", self.claude_md.read_text(encoding="utf-8"))
        self.assertTrue((self.claude_agents / "lead.md").is_file())
        self.assertTrue((self.codex / "lead.config.toml").is_file())
        self.assertIn(b"workflow-setup:start", (self.codex / "config.toml").read_bytes())
        self.assertIn(b'"agent"', (self.project / ".claude" / "settings.json").read_bytes())
        self.assertIn(b"workflow-setup:start", (self.project / ".codex" / "config.toml").read_bytes())
        self.assertTrue((self.project / ".claude" / "agents" / "worker.md").is_file())
        self.assertTrue(self.user_file.is_file())
        self.assertNotEqual(self.pictures(), before)
        self.take_back()
        self.assertAsAtTheStart(before)

    def test_crlf_files_come_back_with_their_line_endings(self) -> None:
        before = self.start(crlf=True)
        self.assertIn(b"@rules/prd-implementation.md\r\n", self.claude_md.read_bytes())
        self.install()
        self.take_back()
        self.assertAsAtTheStart(before)

    def test_a_codex_config_that_sets_sandbox_mode(self) -> None:
        before = self.start(config=CONFIG_SANDBOX)
        self.install()
        self.take_back()
        self.assertAsAtTheStart(before)

    def test_a_codex_config_with_an_agents_table(self) -> None:
        before = self.start(config=CONFIG_AGENTS)
        self.install(codex=("--default-codex-permissions",))
        self.take_back()
        self.assertAsAtTheStart(before)

    def test_no_codex_config_at_all(self) -> None:
        before = self.start(config=None)
        self.install(codex=("--default-codex-permissions",))
        self.assertTrue((self.codex / "config.toml").is_file())
        self.take_back()
        self.assertAsAtTheStart(before)

    def test_without_migration(self) -> None:
        before = self.start(v1_copies=False)
        self.install(migrate_v1=False)
        self.take_back()
        self.assertAsAtTheStart(before)

    def test_with_no_roles(self) -> None:
        before = self.start()
        self.install("--no-roles")
        self.assertNothingAt(self.claude_agents / "lead.md")
        self.take_back()
        self.assertAsAtTheStart(before)

    def test_homes_that_held_nothing(self) -> None:
        before = self.pictures()
        self.install()
        self.assertTrue((self.home / ".agents" / "skills" / "alpha").exists())
        self.take_back()
        self.assertAsAtTheStart(before)
        self.assertEqual(sorted(os.listdir(self.home)), [".claude", ".codex"])
        self.assertEqual(os.listdir(self.project), [])

    def test_a_user_level_settings_file_that_was_there_before_init_comes_back_exactly(self) -> None:
        self.data(self.user_file, USER_SETTINGS)
        self.chmod(self.user_file, 0o600)
        before = self.start()
        self.install()
        self.assertNotEqual(self.user_file.read_bytes(), USER_SETTINGS.encode("utf-8"))
        self.assertIn(b"[providers.codex.tiers]", self.user_file.read_bytes())
        self.take_back()
        self.assertAsAtTheStart(before)
        self.assertEqual(self.user_file.read_bytes(), USER_SETTINGS.encode("utf-8"))

    def test_a_project_alone(self) -> None:
        before = self.start()
        self.done("init", "--yes", "--rewrite-settings", "--high-stakes", *self.at_home, *self.in_project)
        # The record and the backups of the project's files are in the
        # project, and the run left nothing of setup's in the home.
        self.assertTrue(self.project_record.is_file())
        self.assertTrue(self.backups(self.project_state))
        self.assertEqual(picture(self.home), before["home"])
        report = self.uninstall(project=True)
        self.assertEqual(report["state"]["path"], str(self.project_state))
        self.assertTrue(report["state"]["removed"])
        self.assertNotIn("user_state", report)
        self.assertAsAtTheStart(before)

    def test_only_the_project_is_taken_out_and_the_home_stays_installed(self) -> None:
        before = self.start()
        self.install()
        home = picture(self.home)
        # Each state holds the backups of its own files and no other's.
        self.assertTrue(any(name.startswith("backups/") and "/project/" in name for name in self.backups(self.project_state)))
        self.assertTrue(all("/project/" in name for name in self.backups(self.project_state)))
        self.assertTrue(any(name.endswith("/home/.claude/CLAUDE.md") for name in self.backups(self.state)))
        self.assertTrue(all("/home/" in name for name in self.backups(self.state)))
        report = self.uninstall(project=True)
        self.assertEqual((report["scope"], report["kept"]), ("project", []))
        self.assertTrue(report["state"]["removed"])
        self.assertNotIn("user_state", report)
        self.assertEqual(picture(self.project), before["project"])
        self.assertNothingAt(self.project_state)
        # The home is as it was, its state with the record and every backup included.
        self.assertEqual(picture(self.home), home)
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        code, out, _ = self.cli("render", "--json", *self.at_home)
        self.assertEqual((code, json.loads(out)["plan"]), (0, []))

    def test_a_v1_copy_that_the_migration_kept_is_not_in_the_record_and_is_never_touched(self) -> None:
        before = self.start()
        kept = self.edited_copies.pop()   # the edited copy in Codex's old skills directory is not named
        self.assertEqual(kept, self.old_skills / "self-reflection")
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home)
        self.done("render", "--migrate-v1", *self.stale(), *self.at_home, code=3)
        self.assertEqual((kept / "SKILL.md").read_text(encoding="utf-8"), EDITED)
        self.assertNotIn(".codex/skills/self-reflection", (self.state / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("multiagent-collab", (self.state / "manifest.json").read_text(encoding="utf-8"))
        report = self.uninstall()
        self.assertEqual((report["kept"], report["left"]), ([], []))
        self.assertAsAtTheStart(before)

    def test_a_render_that_is_refused_leaves_only_init_to_take_back(self) -> None:
        before = self.start()
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home)
        code, _, err = self.cli("render", *self.at_home)   # v1 copies are in the way, and no migration is asked
        self.assertEqual(code, 2)
        self.assertIn("--migrate-v1", err)
        self.take_back(project=False)
        self.assertAsAtTheStart(before)

    @unittest.skipUnless(POSIX and SYMLINKS, "a link text with a trailing separator and a ..")
    def test_a_link_of_the_users_comes_back_with_its_own_text_letter_for_letter(self) -> None:
        self.start()
        # A v1 link into the clone, in Codex's old skills directory, where
        # setup links nothing: the migration removes it. An anchor of the
        # record could name its target, and would give the path back
        # without the detour and without the last separator.
        link = self.old_skills / "csv-tools"
        text = f"{self.clone}/rules/../csv-tools/"
        os.symlink(text, link)
        before = self.pictures()
        self.install(project=False)
        self.assertNothingAt(link)
        entry = fileops.read_record(self.roots()).entries["home:.codex/skills/csv-tools"]
        self.assertEqual((entry["kind"], entry["target"]), ("removed-link", f"raw:{text}"))
        self.take_back(project=False)
        self.assertEqual(os.readlink(link), text)
        self.assertAsAtTheStart(before)


# --- The order, and the state ----------------------------------------------------

class OrderCase(UninstallCase):
    def test_the_home_first_and_the_project_after_each_finish_by_themselves(self) -> None:
        before = self.start()
        self.install()
        project = picture(self.project)
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        state = report["state"]
        self.assertEqual((state["path"], state["removed"], state["unlisted_backups"]), (str(self.state), True, []))
        self.assertNotIn("project_backups", state)
        self.assertTrue(report["summary"].startswith("done: "), report["summary"])
        # The home is as at the start, with nothing of setup's left in it,
        # and nothing of the project was touched: its record and its backups are its own.
        self.assertEqual(picture(self.home), before["home"])
        self.assertEqual(picture(self.project), project)
        self.assertTrue(self.backups(self.project_state))
        # Asked again, there is nothing to do.
        again = self.uninstall()
        self.assertEqual((again["recorded"], again["changed"], again["removed"]), (False, False, []))
        self.assertEqual(picture(self.home), before["home"])
        self.assertEqual(picture(self.project), project)
        # The project comes back exactly, and its uninstall makes no state in the home.
        report = self.uninstall(project=True)
        self.assertEqual(report["kept"], [])
        self.assertEqual((report["state"]["path"], report["state"]["removed"]), (str(self.project_state), True))
        self.assertAsAtTheStart(before)

    def test_the_project_first_and_the_home_after_each_finish_by_themselves(self) -> None:
        before = self.start()
        self.install()
        home = picture(self.home)
        report = self.uninstall(project=True)
        self.assertEqual((report["kept"], report["state"]["removed"]), ([], True))
        self.assertTrue(report["summary"].startswith("done: "), report["summary"])
        self.assertEqual(picture(self.project), before["project"])
        self.assertEqual(picture(self.home), home)
        report = self.uninstall()
        self.assertEqual((report["kept"], report["state"]["removed"]), ([], True))
        self.assertTrue(report["summary"].startswith("done: "), report["summary"])
        self.assertEqual(picture(self.project), before["project"])
        self.assertAsAtTheStart(before)

    def test_the_text_when_the_home_goes_first_says_it_is_done_and_asks_nothing_of_a_project(self) -> None:
        self.start()
        self.install()
        out = self.done("uninstall", *self.at_home)
        lines = out.splitlines()
        self.assertIn(f"state directory: {self.state}: removed", lines)
        self.assertRegex(lines[-1], r"^done: \d+ removed, \d+ restored; nothing kept; the state directory was removed$")
        self.assertNotIn("to finish", out)
        self.assertNotIn("--project", out)
        self.assertNotIn(str(self.project), out)
        out = self.done("uninstall", *self.at_home, *self.in_project)
        lines = out.splitlines()
        self.assertEqual(lines[0], f"project: {self.project}")
        self.assertIn(f"state directory: {self.project_state}: removed", lines)
        self.assertRegex(
            lines[-1], r"^done: \d+ removed, \d+ restored; nothing kept; the project's state directory was removed$")

    def test_a_project_that_is_gone_does_not_keep_the_home(self) -> None:
        before = self.start()
        self.install()
        shutil.rmtree(self.project)
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        self.assertTrue(report["state"]["removed"])
        self.assertNothingAt(self.state)
        self.assertEqual(picture(self.home), before["home"])
        self.assertNothingAt(self.project)

    def test_a_project_whose_backups_were_removed_by_hand_is_still_undone_piece_by_piece(self) -> None:
        before = self.start()
        self.install()
        shutil.rmtree(self.project_state / "backups")
        report = self.uninstall(project=True)
        self.assertEqual(report["kept"], [])
        # Setup's blocks, keys and files are taken out; with no backup to
        # copy from, that is done in the files as they are.
        self.assertEqual(picture(self.project), before["project"])
        self.take_back(project=False)
        self.assertAsAtTheStart(before)

    def test_the_old_option_for_a_projects_backups_is_gone(self) -> None:
        self.start()
        self.install()
        before = self.pictures()
        code, _, err = self.cli("uninstall", "--discard-project-backups", *self.at_home)
        self.assertEqual(code, 2)
        self.assertIn("--discard-project-backups", err)
        self.assertEqual(self.pictures(), before)

    @unittest.skipUnless(POSIX and SYMLINKS, "the path form of a Windows drive in WSL")
    def test_a_project_on_the_other_sides_drive_is_the_projects_all_the_same(self) -> None:
        drive = self.root / "drive"
        self.project.rmdir()
        self.project = drive / "work" / "project"
        self.project.mkdir(parents=True)
        self.project_state = self.project / ".agents" / "workflow-setup"
        self.project_record = self.project_state / "manifest.json"
        self.project_arg = ("--project", str(self.project))
        wsl = homes.Host(homes.WSL, {"PATH": ""}, (str(drive),))
        before = self.start(v1_copies=False)
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home, host=wsl)
        self.done("render", *self.at_home, *self.in_project, host=wsl)
        self.assertTrue(self.project_record.is_file())
        self.assertEqual(self.uninstall(project=True, host=wsl)["kept"], [])
        self.assertEqual(self.uninstall(host=wsl)["kept"], [])
        self.assertAsAtTheStart(before)

    def test_two_projects_and_the_home_between_them(self) -> None:
        before = self.start()
        other = self.root / "second-project"
        self.data(other / ".gitignore", "dist/\n")
        self.data(other / ".agents" / "workflow.toml", DEFAULT_ON)
        self.data(other / ".claude" / "settings.json", USER_JSON)
        other_before = picture(other)
        self.install()
        self.done("render", *self.at_home, "--project", str(other))
        other_state = other / ".agents" / "workflow-setup"
        self.assertTrue((other_state / "manifest.json").is_file())
        other_installed = picture(other)
        self.uninstall(project=True)
        self.assertEqual(picture(self.project), before["project"])
        self.assertTrue(self.state.is_dir())
        self.assertEqual(picture(other), other_installed)
        # The home does not wait for the second project: its backups are in that project.
        report = self.uninstall()
        self.assertTrue(report["state"]["removed"])
        self.assertNotIn("project_backups", report["state"])
        self.assertNothingAt(self.state)
        self.assertEqual(picture(other), other_installed)
        got, out, err = self.cli("uninstall", "--json", *self.at_home, "--project", str(other))
        self.assertEqual((got, err), (0, ""), out)
        report = json.loads(out)
        self.assertEqual((report["state"]["path"], report["state"]["removed"]), (str(other_state), True))
        self.assertEqual(picture(other), other_before)
        self.assertAsAtTheStart(before)

    def test_a_second_uninstall_has_nothing_to_do(self) -> None:
        before = self.start()
        self.install()
        self.take_back()
        for project in (True, False):
            report = self.uninstall(project=project)
            self.assertFalse(report["recorded"])
            self.assertTrue(report["summary"].startswith("nothing to do: "))
        out = self.done("uninstall", *self.at_home)
        self.assertEqual(out.splitlines()[-1], "nothing to do: setup has no record for this home; nothing was changed")
        self.assertAsAtTheStart(before)

    def test_a_dry_run_changes_nothing_and_says_what_would_be_done(self) -> None:
        self.start()
        self.install()
        before = self.pictures()
        report = self.uninstall("--dry-run", project=True)
        self.assertEqual((report["dry_run"], report["applied"], report["kept"]), (True, False, []))
        self.assertTrue(report["state"]["would_remove"])
        self.assertTrue(any(".claude/settings.json" in line for line in report["restored"]))
        self.assertTrue(any(".claude/agents/worker.md" in line for line in report["removed"]))
        self.assertEqual(report["state"]["path"], str(self.project_state))
        self.assertNotIn("user_state", report)
        # The home alone waits for no project.
        report = self.uninstall("--dry-run")
        self.assertTrue(report["state"]["would_remove"])
        self.assertEqual(report["state"]["path"], str(self.state))
        self.assertIn("remove link home:.claude/skills/alpha", report["removed"])
        self.assertTrue(any(line.startswith("restore file home:.claude/CLAUDE.md") for line in report["restored"]))
        self.assertTrue(any(line.startswith("restore directory home:.claude/skills/self-reflection") for line in report["restored"]))
        self.assertEqual(self.pictures(), before)
        out = self.done("uninstall", "--dry-run", *self.at_home, *self.in_project)
        lines = out.splitlines()
        self.assertEqual(lines[0], "dry run: nothing is changed")
        self.assertEqual(lines[1], f"project: {self.project}")
        self.assertIn("would remove:", lines)
        self.assertIn("would restore:", lines)
        self.assertTrue(lines[2].startswith(f"record: {self.project_record} ("), lines[2])
        self.assertIn(f"state directory: {self.project_state}: would be removed", lines)
        self.assertTrue(lines[-1].startswith("dry run: would remove "), lines[-1])
        self.assertTrue(lines[-1].endswith("; nothing was changed"), lines[-1])
        self.assertEqual(self.pictures(), before)

    def test_the_text_of_a_finished_uninstall(self) -> None:
        self.start()
        self.install(project=False)
        out = self.done("uninstall", *self.at_home)
        lines = out.splitlines()
        self.assertEqual(lines[0], f"home: {self.home}")
        self.assertTrue(lines[1].startswith(f"record: {self.state / 'manifest.json'} ("))
        self.assertIn("removed:", lines)
        self.assertIn("  remove link home:.claude/skills/alpha", lines)
        self.assertIn("restored:", lines)
        self.assertIn("  restore link home:.claude/skills/csv-tools -> raw:" + str(
            self.elsewhere / ".claude" / "skills" / "csv-tools"), lines)
        self.assertIn(f"state directory: {self.state}: removed", lines)
        self.assertRegex(lines[-1], r"^done: \d+ removed, \d+ restored; nothing kept; the state directory was removed$")

    def test_an_interrupted_render_is_completed_in_the_record_and_then_undone(self) -> None:
        before = self.start()
        self.install(project=False)
        real = Manifest.save
        saved: set[Path] = set()

        def save(manifest: Manifest) -> None:
            if manifest.file in saved:
                raise Crash()
            saved.add(manifest.file)
            real(manifest)

        plan = fileops.Plan(self.roots())
        made, undone = self.claude_agents / "made.md", self.claude_agents / "undone.md"
        plan.write_file(made, "one\n", inputs="render:test")
        plan.write_file(undone, "two\n", inputs="render:test")
        with mock.patch.object(Manifest, "save", autospec=True, side_effect=save):
            with self.assertRaises(Crash):
                plan.apply()
        os.remove(undone)   # as if the run had stopped before it
        self.assertIn(b'"pending"', (self.state / "manifest.json").read_bytes())
        dry = self.uninstall("--dry-run")
        self.assertIn(b'"pending"', (self.state / "manifest.json").read_bytes())
        self.assertIn("remove file home:.claude/agents/made.md", dry["removed"])
        report = self.uninstall()
        self.assertTrue(any(note.startswith("complete the record of an interrupted run: 1 changes were made") for note in report["notes"]))
        self.assertAsAtTheStart(before)

    def test_through_the_script_as_a_process_of_its_own(self) -> None:
        before = self.start(v1_copies=False)
        script = self.install_tool()
        clone = picture(self.clone)
        empty = self.root / "no-programs"
        empty.mkdir()
        environment = {**support.child_environment(), "PATH": str(empty)}

        def child(*argv: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, "-B", str(script), *argv, *self.at_home], env=environment, cwd=str(self.root),
                stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=False,
            )

        for argv in (("init", "--user", "--yes", "--rewrite-settings"), ("render",)):
            done = child(*argv)
            self.assertEqual((done.returncode, done.stderr), (0, b""), done.stdout.decode("utf-8", "replace")[-800:])
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        file = self.claude_agents / "lead.md"
        wrote = file.read_bytes()
        file.write_bytes(wrote + b"mine\n")
        done = child("uninstall")
        self.assertEqual((done.returncode, done.stderr), (3, b""))
        self.assertNotIn(b"\r\n", done.stdout)
        self.assertIn(b"not finished: ", done.stdout.splitlines()[-1])
        file.write_bytes(wrote)
        done = child("uninstall")
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertTrue(done.stdout.splitlines()[-1].startswith(b"done: "))
        done = child("uninstall")
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertTrue(done.stdout.splitlines()[-1].startswith(b"nothing to do: "))
        before["clone"] = clone
        self.assertAsAtTheStart(before)

    def test_help_states_the_scope_the_state_and_the_exit_codes(self) -> None:
        code, out, _ = support.run("uninstall", "--help")
        flat = " ".join(out.split())
        self.assertEqual(code, 0)
        for option in ("--project", "--home", "--dry-run", "--json", "--follow-config-symlinks", "--keep-settings",
                       "--clone-was", "--discard-backups", "--yes"):
            self.assertIn(option, flat)
        self.assertNotIn("--discard-project-backups", flat)
        self.assertIn("With --project DIR: what setup did in that project, and nothing else", flat)
        self.assertIn("in ~/.agents/workflow-setup for the user level, and in DIR/.agents/workflow-setup for a project", flat)
        self.assertIn("undoing a project touches nothing of the home, and undoing the home nothing of a project", flat)
        self.assertIn("When every entry was removed or restored, the state goes too", flat)
        self.assertIn("is never removed by a run: it may be the only copy of a file of yours", flat)
        self.assertIn("`uninstall` then leaves the state directory, names the files, and ends with 3", flat)
        self.assertIn("removes them after you confirm (or with --yes; --dry-run only lists)", flat)
        self.assertIn("Exit code 0 when everything was undone, or there was nothing to do; 3 when", flat)
        self.assertIn("uninstall", support.run("--help")[1])


# --- What the user changed since ---------------------------------------------------

class KeptCase(UninstallCase):
    def setUp(self) -> None:
        super().setUp()
        self.before = self.start()
        self.install(project=False)

    def unfinished(self, path: Path, *words: str, **how) -> dict:
        """The entry at ``path`` is kept and reported, the rest is undone,
        and the state stays."""
        report = self.uninstall(code=3, **how)
        item = self.kept(report, path)
        for word in words:
            self.assertIn(word, f"{item['what']}: {item['why']} | {item['finish']}")
        self.assertFalse(report["state"]["removed"])
        self.assertIn("the record of what was kept", report["state"]["why"])
        self.assertTrue((self.state / "manifest.json").is_file())
        self.assertTrue(report["summary"].startswith("not finished: "))
        return report

    def assertTheRestIsUndone(self, *but: str) -> None:
        """The home is as at the start, but for setup's state and ``but``."""
        after = self.home_without_state()
        for name in sorted(set(after) | set(self.before["home"])):
            if not any(name == one or name.startswith(one + "/") for one in but):
                self.assertEqual(after.get(name), self.before["home"].get(name), name)

    def finished(self) -> None:
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        self.assertAsAtTheStart(self.before)

    def test_a_generated_file_that_was_edited_then_removed(self) -> None:
        file = self.claude_agents / "lead.md"
        edited = file.read_bytes() + b"\nMy own line.\n"
        file.write_bytes(edited)
        self.unfinished(file, "a file setup wrote", "changed since setup wrote it", "remove the file")
        self.assertEqual(file.read_bytes(), edited)
        self.assertTheRestIsUndone(".claude/agents/lead.md")
        self.assertNothingAt(self.claude_agents / "worker.md")
        # Asked again, it is still kept, and nothing else is left to do.
        again = self.unfinished(file)
        self.assertEqual((again["removed"], again["restored"], len(again["kept"])), ([], [], 1))
        file.unlink()
        self.finished()

    def test_a_generated_file_that_was_edited_then_put_back(self) -> None:
        file = self.codex / "lead.config.toml"
        wrote = file.read_bytes()
        file.write_bytes(wrote.replace(b"model = ", b"model  =  "))
        self.unfinished(file, "changed since setup wrote it")
        file.write_bytes(wrote)
        self.finished()

    def test_a_block_that_was_edited_then_put_back(self) -> None:
        file = self.codex / "config.toml"
        wrote = file.read_bytes()
        self.assertIn(b"max_concurrent_threads_per_session = 8", wrote)
        edited = wrote.replace(b"max_concurrent_threads_per_session = 8", b"max_concurrent_threads_per_session = 3")
        file.write_bytes(edited)
        self.unfinished(file, "a text file of yours", "setup's block codex-settings was edited since setup wrote it",
                        "remove the block with its markers")
        self.assertEqual(file.read_bytes(), edited)   # the user's text between the markers is not lost
        self.assertTheRestIsUndone(".codex/config.toml")
        file.write_bytes(wrote)
        self.finished()

    def test_a_block_that_was_edited_then_removed_with_its_markers(self) -> None:
        wrote = self.claude_md.read_bytes()
        start = wrote.index(b"\n<!-- workflow-setup:start process -->")
        self.claude_md.write_bytes(wrote.replace(b"Sprint and epic work", b"All work"))
        self.unfinished(self.claude_md, "setup's block process was edited")
        self.assertIn(b"All work", self.claude_md.read_bytes())
        self.assertNotIn(b"@rules/", self.claude_md.read_bytes())   # nothing of it was undone
        self.claude_md.write_bytes(wrote[:start])
        # The lines the migration removed are put back where they were.
        self.finished()

    def test_a_file_of_the_users_that_was_changed_elsewhere_keeps_the_change(self) -> None:
        self.claude_md.write_bytes(self.claude_md.read_bytes() + b"\nA line added after the install.\n")
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        text = self.claude_md.read_text(encoding="utf-8")
        self.assertEqual(text, CLAUDE_MD + "\nA line added after the install.\n")
        self.assertTrue(any("setup's part was taken out and the rest left" in note for note in report["notes"]))
        self.assertNoState()

    def test_a_file_of_the_users_put_back_by_hand_needs_nothing_and_gets_no_line_twice(self) -> None:
        self.claude_md.write_bytes(CLAUDE_MD.encode("utf-8"))
        self.chmod(self.claude_md, 0o640)
        self.finished()
        self.assertEqual(self.claude_md.read_text(encoding="utf-8").count("@rules/prd-implementation.md"), 1)

    def test_a_link_that_was_pointed_elsewhere_then_removed(self) -> None:
        link = self.claude_skills / "alpha"
        mine = self.data(self.elsewhere / "my-alpha" / "SKILL.md", "mine\n").parent
        fsio.remove_link(link)
        fsio.make_link(str(mine), link, True)
        self.before["elsewhere"] = picture(self.elsewhere)
        self.unfinished(link, "a link setup made", "no longer the link setup made", "remove what is there")
        self.assertLinked(link, mine)
        self.assertTheRestIsUndone(".claude/skills/alpha")
        fsio.remove_link(link)
        self.finished()

    def test_a_link_in_place_of_the_users_directory_then_removed(self) -> None:
        link = self.claude_skills / "self-reflection"
        mine = self.data(self.elsewhere / "my-reflection" / "SKILL.md", "mine\n").parent
        fsio.remove_link(link)
        fsio.make_link(str(mine), link, True)
        self.before["elsewhere"] = picture(self.elsewhere)
        report = self.unfinished(link, "what it took the place of was not put back")
        below = self.kept(report, link / "SKILL.md")
        self.assertIn("a file of yours that setup removed", below["what"])
        self.assertEqual(Path(below["backup"]).read_bytes(), v1("self-reflection/SKILL.md", 0))
        self.assertEqual(sorted(os.listdir(mine)), ["SKILL.md"])   # nothing was written through the link
        fsio.remove_link(link)
        self.finished()

    def test_something_where_setup_removed_a_file_is_kept_and_the_backup_is_named(self) -> None:
        rule = self.rules / "prd-implementation.md"
        self.assertNothingAt(rule)
        rule.write_bytes(b"A rule the user wrote since.\n")
        report = self.unfinished(rule, "a file of yours that setup removed", "something is there again",
                                 "remove what is there and the backup is put back")
        item = self.kept(report, rule)
        self.assertEqual(Path(item["backup"]).read_bytes(), v1("prd-implementation.md", 0))
        self.assertTrue(str(item["backup"]).startswith(str(self.state / "backups")))
        self.assertEqual(rule.read_bytes(), b"A rule the user wrote since.\n")
        self.assertTheRestIsUndone(".claude/rules/prd-implementation.md")
        out = self.done("uninstall", *self.at_home, code=3)
        self.assertIn(f"    backup: {item['backup']}", out)
        self.assertIn(f"    path: {rule}", out)
        self.assertIn("to finish: do what is said for each kept entry, then run `workflow_setup.py uninstall` again", out)
        rule.unlink()
        self.finished()

    def test_the_same_bytes_where_setup_removed_a_file_need_nothing(self) -> None:
        rule = self.rules / "prd-implementation.md"
        rule.write_bytes(v1("prd-implementation.md", 0))
        self.finished()

    def test_a_directory_setup_created_that_holds_something_of_the_users_is_left(self) -> None:
        mine = self.data(self.codex / "agents" / "mine.toml", 'name = "mine"\n')
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        self.assertEqual([(item["key"], item["path"]) for item in report["left"]],
                         [("home:.codex/agents", str(self.codex / "agents"))])
        self.assertIn("it is the user's now", report["left"][0]["why"])
        self.assertEqual(os.listdir(self.codex / "agents"), ["mine.toml"])
        self.assertNoState()
        mine.unlink()
        (self.codex / "agents").rmdir()
        self.assertAsAtTheStart(self.before)

    def test_the_settings_file_edited_is_left_as_the_users(self) -> None:
        # It holds what the user put there: left, without --keep-settings,
        # and the uninstall finishes (S1 of the third review; before, it was
        # kept, with exit code 3, until --keep-settings was given).
        self.user_file.write_bytes(self.user_file.read_bytes() + b"\n[memory]\ndir = \"mine\"\n")
        edited = self.user_file.read_bytes()
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        self.assertEqual([item["key"] for item in report["left"]], ["home:.agents/workflow.toml"])
        self.assertIn("it was edited since `init` wrote it", report["left"][0]["why"])
        self.assertIn("is yours", report["left"][0]["why"])
        self.assertEqual(self.user_file.read_bytes(), edited)
        self.assertNoState()
        self.assertTheRestIsUndone(".agents/workflow.toml")

    def test_keep_settings_leaves_the_file_init_wrote(self) -> None:
        wrote = self.user_file.read_bytes()
        out = self.done("uninstall", "--keep-settings", *self.at_home)
        self.assertIn("left, and yours from now on:", out)
        self.assertIn("  home:.agents/workflow.toml: the settings file stays as it is, and is yours, as --keep-settings says", out)
        self.assertEqual(self.user_file.read_bytes(), wrote)
        self.assertNoState()
        self.assertTheRestIsUndone(".agents/workflow.toml")
        # It is the user's now: a later init and uninstall bring it back to this.
        self.done("init", "--user", "--yes", "--rewrite-settings", "--docs-dir", "sprints", *self.at_home)
        self.assertNotEqual(self.user_file.read_bytes(), wrote)
        self.uninstall()
        self.assertEqual(self.user_file.read_bytes(), wrote)

    def test_a_removed_settings_file_that_replaced_the_users_is_kept_until_the_backup_is_copied_back(self) -> None:
        self.uninstall()
        self.data(self.user_file, USER_SETTINGS)
        start = self.pictures()
        self.install(project=False, migrate_v1=True)
        self.user_file.unlink()
        report = self.unfinished(self.user_file, "removed since setup wrote it", "copy the backup back")
        backup = Path(self.kept(report, self.user_file)["backup"])
        shutil.copyfile(backup, self.user_file)
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        self.assertAsAtTheStart(start)


class ProjectKeptCase(UninstallCase):
    def setUp(self) -> None:
        super().setUp()
        self.before = self.start()
        self.install()
        self.settings = self.project / ".claude" / "settings.json"
        self.config = self.project / ".codex" / "config.toml"

    def test_a_key_the_user_changed_is_theirs_and_is_left(self) -> None:
        data = self.settings.read_bytes()
        self.assertIn(b'"agent": "lead"', data)
        self.settings.write_bytes(data.replace(b'"agent": "lead"', b'"agent": "my-own"'))
        report = self.uninstall(project=True)
        self.assertEqual(report["kept"], [])
        self.assertEqual([item["key"] for item in report["left"]], ["project:.claude/settings.json"])
        self.assertIn("the key agent was changed since setup set it; it is the user's now", report["left"][0]["why"])
        # The file keeps the user's value, and every other byte is as at the start.
        self.assertEqual(json.loads(self.settings.read_bytes())["agent"], "my-own")
        self.assertNothingAt(self.project_record)
        after = picture(self.project)
        after.pop(".claude/settings.json")
        start = dict(self.before["project"])
        start.pop(".claude/settings.json")
        self.assertEqual(after, start)
        out_of_the_way = self.uninstall()
        self.assertEqual(out_of_the_way["kept"], [])
        self.assertNoState()

    def test_a_key_the_user_removed_needs_nothing(self) -> None:
        self.settings.write_bytes(USER_JSON)
        self.take_back()
        self.assertAsAtTheStart(self.before)

    def test_a_project_block_that_was_edited_then_put_back(self) -> None:
        wrote = self.config.read_bytes()
        edited = wrote.replace(b'model = "', b'model = "my-')
        self.assertNotEqual(edited, wrote)
        self.config.write_bytes(edited)
        report = self.uninstall(code=3, project=True)
        item = self.kept(report, self.config)
        self.assertIn("was edited since setup wrote it", item["why"])
        self.assertEqual(self.config.read_bytes(), edited)
        self.assertTrue(self.project_record.is_file())
        self.assertIn("the record of what was kept", report["state"]["why"])
        # The rest of the project is undone.
        self.assertEqual(self.settings.read_bytes(), USER_JSON)
        self.assertNothingAt(self.project / ".claude" / "agents")
        self.assertEqual(report["state"]["path"], str(self.project_state))
        # The home may go first now, and is finished: it waits for no project.
        self.assertTrue(self.uninstall()["state"]["removed"])
        self.assertNothingAt(self.state)
        self.assertEqual(self.config.read_bytes(), edited)
        self.assertTrue(self.project_record.is_file())
        self.config.write_bytes(wrote)
        report = self.uninstall(project=True)
        self.assertTrue(report["state"]["removed"])
        self.assertAsAtTheStart(self.before)

    def test_a_generated_file_of_the_project_edited_then_removed(self) -> None:
        file = self.project / ".claude" / "agents" / "worker.md"
        file.write_bytes(file.read_bytes() + b"\nmine\n")
        report = self.uninstall(code=3, project=True)
        self.assertIn("changed since setup wrote it", self.kept(report, file)["why"])
        # The ignore block went with the rest; the kept file is the user's to deal with.
        self.assertEqual((self.project / ".gitignore").read_bytes(), b"node_modules/\n*.log\n")
        file.unlink()
        self.take_back()
        self.assertAsAtTheStart(self.before)


# --- A clone that moved, links in the way, the other side ---------------------------

class PlacesCase(UninstallCase):
    def test_after_the_clone_moved_the_links_are_kept_until_the_old_place_is_named(self) -> None:
        from wfsetup import locations
        before = self.start()
        self.install(project=False)
        moved = self.root / "moved" / "the-clone"
        moved.parent.mkdir()
        os.rename(self.clone, moved)
        with mock.patch.object(locations, "CLONE", moved):
            got, out, err = self.cli("uninstall", "--json", *self.at_home)
            self.assertEqual((got, err), (3, ""), out)
            report = json.loads(out)
            link = self.kept(report, self.claude_skills / "alpha")
            self.assertIn("no longer the link setup made", link["why"])
            self.assertIn(f"--clone-was {self.clone}", link["finish"])
            self.assertTrue(fsio.look(self.claude_skills / "alpha").kind == fsio.LINK)
            # What is not a link into the clone is undone all the same.
            self.assertNothingAt(self.claude_agents / "lead.md")
            self.assertIn("@rules/prd-implementation.md", self.claude_md.read_text(encoding="utf-8"))
            got, out, err = self.cli("uninstall", "--json", "--clone-was", str(self.clone), *self.at_home)
            self.assertEqual((got, err), (0, ""), out)
            self.assertEqual(json.loads(out)["kept"], [])
        os.rename(moved, self.clone)
        self.assertAsAtTheStart(before)

    def test_clone_was_must_be_an_absolute_path(self) -> None:
        for value, word in (("", "an empty value"), ("some/where", "not an absolute path")):
            code, _, err = self.cli("uninstall", "--clone-was", value, *self.at_home)
            self.assertEqual(code, 2)
            self.assertIn(word, err)

    def linked_agents(self, target: Path) -> Path:
        """The agents directory of the Claude Code home, moved away and
        linked from where it was, as a user would share it."""
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.claude_agents), str(target))
        fsio.make_link(str(target), self.claude_agents, True)
        return target

    def test_a_path_under_a_link_is_kept_until_the_option_is_given(self) -> None:
        self.start()
        self.install(project=False)
        shared = self.linked_agents(self.elsewhere / "shared-agents")
        held = picture(shared)
        report = self.uninstall(code=3)
        item = self.kept(report, self.claude_agents / "lead.md")
        # The link leads out of the home: the option would not help, and
        # neither the reason nor the advice says it would.
        self.assertIn("is outside the directories this run may write to", item["why"])
        self.assertNotIn("--follow-config-symlinks", item["why"] + item["finish"])
        self.assertIn("take away the link that leads there", item["finish"])
        self.assertEqual(picture(shared), held)   # nothing was written through the link
        # The rest is undone.
        self.assertNothingAt(self.claude_skills / "alpha")
        self.assertNothingAt(self.codex / "lead.config.toml")
        self.assertIn("@rules/prd-implementation.md", self.claude_md.read_text(encoding="utf-8"))
        # The link leads out of the home: the option does not make this
        # run write there, so the entries are kept with it as well.
        home = picture(self.home)
        for option in (("--follow-config-symlinks",), ("--follow-config-symlinks", "--dry-run")):
            report = self.uninstall(*option, code=3)
            item = self.kept(report, self.claude_agents / "lead.md")
            self.assertIn(f"its real place, {shared / 'lead.md'}, is outside the directories this run may write to", item["why"])
            self.assertNotIn("give --follow-config-symlinks", item["finish"])
            self.assertEqual((report["removed"], report["restored"]), ([], []))
            self.assertFalse(report["state"]["removed"])
            self.assertEqual(picture(shared), held)
            self.assertEqual(picture(self.home), home)
        # Once the directory is the home's own again, the rest is undone.
        fsio.remove_link(self.claude_agents)
        shutil.move(str(shared), str(self.claude_agents))
        report = self.uninstall()
        self.assertEqual(report["kept"], [])
        self.assertNoState()
        self.assertEqual(sorted(os.listdir(self.claude_agents)), ["mine.md", "sprint-coder.md"])
        self.assertEqual((self.claude_agents / "sprint-coder.md").read_bytes(), v1(migrate.V1_AGENT_SOURCE))

    def test_a_path_under_a_link_that_stays_in_the_home_is_undone_with_the_option(self) -> None:
        self.start()
        self.install(project=False)
        shared = self.linked_agents(self.home / "dotfiles" / "claude-agents")
        held = picture(shared)
        report = self.uninstall(code=3)
        item = self.kept(report, self.claude_agents / "lead.md")
        self.assertIn(f"lies under the link {self.claude_agents}", item["why"])
        self.assertIn("give --follow-config-symlinks", item["finish"])
        self.assertEqual(picture(shared), held)   # nothing was written through the link
        report = self.uninstall("--follow-config-symlinks")
        self.assertEqual(report["kept"], [])
        self.assertNoState()
        # The link is still the user's link, and what setup wrote where it leads is gone.
        self.assertLinked(self.claude_agents, shared)
        self.assertEqual(sorted(os.listdir(shared)), ["mine.md", "sprint-coder.md"])
        self.assertEqual((shared / "sprint-coder.md").read_bytes(), v1(migrate.V1_AGENT_SOURCE))
        self.assertEqual((shared / "mine.md").read_bytes(), held["mine.md"][1])

    def test_a_state_directory_under_a_link_stops_the_run_before_anything_changes(self) -> None:
        self.start()
        self.install(project=False)
        agents = self.home / ".agents"
        shutil.move(str(agents), str(self.elsewhere / "agents-home"))
        fsio.make_link(str(self.elsewhere / "agents-home"), agents, True)
        before = self.pictures()
        code, out, err = self.cli("uninstall", *self.at_home)
        self.assertEqual(code, 2, out)
        self.assertIn("--follow-config-symlinks", err)
        self.assertIn("nothing was changed", out.splitlines()[-1])
        self.assertEqual(self.pictures(), before)

    @unittest.skipUnless(POSIX and SYMLINKS, "the path form of a Windows drive in WSL")
    def test_a_path_on_the_other_side_is_never_written(self) -> None:
        self.start()
        self.install(project=False)
        drive = self.root / "drive"
        shared = self.linked_agents(drive / "Users" / "someone" / ".claude" / "agents")
        wsl = homes.Host(homes.WSL, {"PATH": ""}, (str(drive),))
        held = picture(drive)
        for option in ((), ("--follow-config-symlinks",)):
            report = self.uninstall(*option, code=3, host=wsl)
            item = self.kept(report, self.claude_agents / "lead.md")
            self.assertIn("is on the other side (windows); this side writes nothing there", item["why"])
            self.assertIn(str(shared), item["why"])
            self.assertEqual(picture(drive), held)
        self.assertNothingAt(self.claude_skills / "alpha")

    @unittest.skipUnless(POSIX and SYMLINKS, "the path form of a Windows drive in WSL")
    def test_what_the_other_side_owns_was_never_written_and_is_as_it_was(self) -> None:
        drive = self.root / "drive"
        theirs = drive / "Users" / "someone" / ".claude"
        self.data(theirs / "CLAUDE.md", CLAUDE_MD)
        self.rule_copies(theirs / "rules")
        os.symlink(str(theirs / "CLAUDE.md"), self.claude / "CLAUDE.md")
        os.symlink(str(theirs / "rules"), self.claude / "rules")
        self.codex_home()
        wsl = homes.Host(homes.WSL, {"PATH": ""}, (str(drive),))
        before, drive_before = self.pictures(), picture(drive)
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home, host=wsl)
        self.done("render", "--migrate-v1", *self.stale(), *self.at_home, host=wsl)
        self.assertEqual(picture(drive), drive_before)
        report = self.uninstall(host=wsl)
        self.assertEqual(report["kept"], [])
        self.assertEqual(picture(drive), drive_before)
        self.assertAsAtTheStart(before)


# --- Backups that no record lists ----------------------------------------------------

class UnlistedBackupsCase(UninstallCase):
    """A file under a backups directory that no record lists: no run
    removes it, ``uninstall`` leaves the state directory for it, and
    ``uninstall --discard-backups`` removes it when asked."""

    def test_they_keep_the_state_directory_are_named_and_the_code_is_3(self) -> None:
        before = self.start()
        self.install(project=False)
        mine = self.unlisted(self.state, "home")
        report = self.uninstall(code=3)
        self.assertEqual(report["kept"], [])
        state = report["state"]
        self.assertEqual((state["path"], state["removed"], state["unlisted_backups"]), (str(self.state), False, [str(mine)]))
        self.assertIn("1 backup that no record lists", state["why"])
        self.assertIn("uninstall --discard-backups", state["why"])
        self.assertTrue(report["summary"].startswith("not finished: "), report["summary"])
        # Everything was undone, the record and the backups it listed are gone, and the file is as it was.
        self.assertEqual(self.home_without_state(), before["home"])
        self.assertEqual(
            {name: what for name, what in picture(self.state).items() if what[0] == "file"},
            {mine.relative_to(self.state).as_posix(): ("file", b"the only copy\n", stat.S_IMODE(os.lstat(mine).st_mode) if POSIX else None)},
        )
        # Asked again: no record, the file is still named, and the code is still 3.
        held = picture(self.home)
        again = self.uninstall(code=3)
        self.assertEqual((again["recorded"], again["changed"], again["state"]["unlisted_backups"]), (False, False, [str(mine)]))
        self.assertEqual(picture(self.home), held)
        out = self.done("uninstall", *self.at_home, code=3)
        self.assertIn(f"    {mine}", out.splitlines())
        self.assertIn(f"state directory: {self.state}: stays: ", out)
        self.assertEqual(picture(self.home), held)
        # A dry run says the same, and no other command removes the file either.
        self.assertEqual(self.uninstall("--dry-run", code=3)["state"]["unlisted_backups"], [str(mine)])
        self.done("init", "--user", "--yes", "--rewrite-settings", *self.at_home)
        self.done("render", "--migrate-v1", *self.stale(), *self.at_home)
        self.assertEqual(mine.read_bytes(), b"the only copy\n")
        self.assertEqual(self.uninstall(code=3)["state"]["unlisted_backups"], [str(mine)])
        self.assertEqual(mine.read_bytes(), b"the only copy\n")
        self.discard("--yes")
        self.assertAsAtTheStart(before)

    def test_without_a_terminal_discarding_needs_yes_and_removes_nothing_without_it(self) -> None:
        self.start()
        self.install(project=False)
        mine = self.unlisted(self.state, "home")
        before = self.pictures()
        out, err = self.discard(code=2)
        self.assertIn(str(mine), out)
        self.assertIn("--discard-backups: needs a confirmation: nothing was removed", err)
        self.assertIn("--yes", err)
        self.assertEqual(self.pictures(), before)

    def test_a_dry_run_only_lists(self) -> None:
        self.start()
        self.install(project=False)
        mine = self.unlisted(self.state, "home")
        other = self.unlisted(self.state, "home", "other.md", b"another\n")
        before = self.pictures()
        for option in (("--dry-run",), ("--dry-run", "--yes")):
            out, err = self.discard(*option)
            self.assertEqual(err, "")
            lines = out.splitlines()
            self.assertEqual(lines[0], f"backups of {self.home} that no record of setup's lists:")
            self.assertEqual(sorted(lines[1:-1]), sorted([f"  {mine}", f"  {other}"]))
            self.assertEqual(lines[-1], "dry run: nothing was removed")
            self.assertEqual(self.pictures(), before)

    def test_what_is_typed_at_a_terminal_decides(self) -> None:
        self.start()
        self.install(project=False)
        mine = self.unlisted(self.state, "home")
        before = self.pictures()
        for answer in ("n", "no", "maybe", " "):
            out, err = self.discard(answer=answer)
            self.assertEqual((out.splitlines()[-1], err), ("nothing was removed", ""))
            self.assertEqual(self.pictures(), before)
        out, err = self.discard(answer="y")
        self.assertEqual((out.splitlines()[-1], err), ("removed: 1 backup", ""))
        self.assertNothingAt(mine)

    def test_yes_removes_the_unlisted_ones_and_never_a_listed_one(self) -> None:
        before = self.start()
        self.install(project=False)
        listed = {name: what for name, what in picture(self.state).items() if what[0] == "file"}
        self.assertTrue(any(name.startswith("backups/") for name in listed))
        mine = self.unlisted(self.state, "home")
        # One beside a listed backup, in the directory of a run of setup's.
        beside = self.state / Path(next(name for name in sorted(listed) if name.endswith("/home/.claude/CLAUDE.md"))).parent / "beside.md"
        self.data(beside, "not listed\n")
        home = self.home_without_state()
        out, err = self.discard("--yes")
        self.assertEqual(err, "")
        self.assertIn(f"  {mine}", out.splitlines())
        self.assertIn(f"  {beside}", out.splitlines())
        self.assertEqual(out.splitlines()[-1], "removed: 2 backups")
        self.assertNothingAt(mine)
        self.assertNothingAt(mine.parents[2])   # the directories that held only it went with it
        self.assertNothingAt(beside)
        # Every file the record lists is there, byte for byte, with the record; nothing was undone.
        self.assertEqual({name: what for name, what in picture(self.state).items() if what[0] == "file"}, listed)
        self.assertEqual(self.home_without_state(), home)
        # Asked again, there is nothing to discard, and the install is taken back exactly.
        held = self.pictures()
        out, err = self.discard("--yes")
        self.assertEqual(err, "")
        self.assertTrue(out.startswith("nothing to do: no backup under "), out)
        self.assertEqual(self.pictures(), held)
        self.take_back(project=False)
        self.assertAsAtTheStart(before)

    def test_after_an_uninstall_the_empty_state_goes_with_them(self) -> None:
        before = self.start()
        self.install(project=False)
        self.unlisted(self.state, "home")
        self.uninstall(code=3)
        self.assertTrue(self.state.is_dir())
        out, _ = self.discard("--yes")
        self.assertEqual(out.splitlines()[-1], "removed: 1 backup")
        self.assertAsAtTheStart(before)
        report = self.uninstall()
        self.assertTrue(report["summary"].startswith("nothing to do: "))

    def test_a_projects_are_in_the_project_and_are_discarded_with_project(self) -> None:
        before = self.start()
        self.install()
        mine = self.unlisted(self.project_state, "project")
        home = picture(self.home)
        # The home has none: nothing of the project's is listed for it, or removed with it.
        out, err = self.discard("--yes")
        self.assertEqual(err, "")
        self.assertTrue(out.startswith(f"nothing to do: no backup under {self.state} is unlisted"), out)
        self.assertEqual(mine.read_bytes(), b"the only copy\n")
        report = self.uninstall(code=3, project=True)
        self.assertEqual(report["kept"], [])
        self.assertEqual(report["state"]["unlisted_backups"], [str(mine)])
        self.assertFalse(report["state"]["removed"])
        self.assertNothingAt(self.project_record)
        project = {name: what for name, what in picture(self.project).items() if "workflow-setup" not in name}
        self.assertEqual(project, before["project"])
        out, err = self.discard(project=True, code=2)
        self.assertIn(str(mine), out)
        self.assertEqual(mine.read_bytes(), b"the only copy\n")
        out, err = self.discard("--yes", project=True)
        self.assertEqual(out.splitlines()[0], f"backups of {self.project} that no record of setup's lists:")
        self.assertEqual(out.splitlines()[-1], "removed: 1 backup")
        self.assertEqual(picture(self.project), before["project"])
        self.assertEqual(picture(self.home), home)
        self.take_back(project=False)
        self.assertAsAtTheStart(before)

    def test_it_is_a_command_of_its_own(self) -> None:
        self.start()
        self.install(project=False)
        self.unlisted(self.state, "home")
        before = self.pictures()
        for option in (("--json",), ("--keep-settings",), ("--clone-was", str(self.root / "was"))):
            _, err = self.discard("--yes", *option, code=2)
            self.assertIn(f"--discard-backups: is a command of its own; give it without {option[0]}", err)
            self.assertEqual(self.pictures(), before)
        # And --yes confirms nothing else.
        code, _, err = self.cli("uninstall", "--yes", *self.at_home)
        self.assertEqual(code, 2)
        self.assertIn("--yes: only confirms --discard-backups", err)
        self.assertEqual(self.pictures(), before)

    def test_with_nothing_installed_there_is_nothing_to_do_and_nothing_is_made(self) -> None:
        before = self.start()
        for project in (False, True):
            out, err = self.discard("--yes", project=project)
            self.assertEqual(err, "")
            self.assertTrue(out.startswith("nothing to do: "), out)
        self.assertAsAtTheStart(before)


# --- Random installs ---------------------------------------------------------------

class RandomCase(UninstallCase):
    SEEDS = range(8)

    def commands(self, rng: random.Random) -> list[list[str]]:
        home, project = list(self.at_home), list(self.in_project)
        choices = [
            ["init", "--user", "--yes", "--rewrite-settings", *home],
            ["init", "--user", "--yes", "--rewrite-settings", "--docs-dir", "sprints", "--high-stakes", *home],
            ["init", "--yes", "--rewrite-settings", *home, *project],
            ["init", "--yes", "--rewrite-settings", "--max-parallel-coders", "5", *home, *project],
            ["render", *home],
            ["render", "--no-roles", *home],
            ["render", "--migrate-v1", *home],
            ["render", "--migrate-v1", *self.stale(), *home],
            ["render", "--migrate-v1", *self.stale(), "--apply-codex-settings", *home],
            ["render", "--apply-codex-settings", "--default-codex-permissions", *home],
            ["render", "--remove-codex-settings", *home],
            ["render", *home, *project],
            ["render", "--migrate-v1", *self.stale(), *home, *project],
            ["render", "--no-roles", *home, *project],
        ]
        return [rng.choice(choices) for _ in range(rng.randint(2, 7))]

    def test_any_commands_in_any_order_are_taken_back(self) -> None:
        for seed in self.SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                for directory in (self.home, self.project, self.elsewhere):
                    shutil.rmtree(directory, ignore_errors=True)
                self.home.mkdir()
                self.project.mkdir()
                self.claude.mkdir()
                self.codex.mkdir()
                self.edited_copies.clear()
                before = self.start(
                    crlf=rng.random() < 0.5, v1_copies=rng.random() < 0.7,
                    config=rng.choice([CONFIG_PLAIN, CONFIG_SANDBOX, CONFIG_AGENTS, None]),
                )
                if rng.random() < 0.3:
                    self.data(self.user_file, USER_SETTINGS)
                    before = self.pictures()
                ran = []
                for argv in self.commands(rng):
                    code, out, err = self.cli(*argv)
                    # A run that is refused (a v1 copy in the way) writes nothing.
                    self.assertIn(code, (0, 2, 3), f"{argv}\n{out}\n{err}")
                    ran.append((code, argv[:2] + [word for word in argv[2:] if word.startswith("--")]))
                first = self.uninstall("--dry-run", project=True)
                self.assertEqual(first["kept"], [], ran)
                self.assertEqual(self.uninstall(project=True)["kept"], [], ran)
                self.assertEqual(self.uninstall()["kept"], [], ran)
                try:
                    self.assertAsAtTheStart(before)
                except AssertionError as exc:
                    raise AssertionError(f"{exc}\nafter: {ran}") from None


if __name__ == "__main__":
    unittest.main()
