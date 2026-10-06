"""Tests for the v1 migration: ``render --migrate-v1``, ``--remove-stale``,
``doctor``'s check ``v1``, the hash file and its build script, and what
``fileops`` gained for it.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

No test touches a real home. The four homes of the machine the step was
written for ("This machine (L1)" in the sprint's PLAN) are rebuilt in
scratch directories by ``windows_home`` and ``wsl_home``: the Windows
homes under a directory that stands for the Windows drive, the WSL homes
as links into it. A run "on the Windows side" is a run with that
directory as its home; a run "in WSL" has a host that says the directory
is a Windows drive.

The known hashes are a table made here from small fixture texts
(``V1``), so the suite needs no git history. The committed hash file is
checked by ``HashFileCase``, whose comparison with the history is skipped
where there is none.
"""
from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest import mock

import support
from fileops_support import POSIX, SYMLINKS, OpsCase
from test_doctor import DoctorCase
from test_render import LINKS, SIDE, RenderCase, tree
from test_validate import SKILL
from wfsetup import doctor, fileops, fsio, homes, migrate, render
from wfsetup.locations import Locations


def _builder():
    spec = importlib.util.spec_from_file_location("build_v1_hashes", support.SETUP / "build_v1_hashes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _builder()

# The committed versions of the fixture's v1 files, oldest first.
V1: dict[str, tuple[str, ...]] = {
    "prd-implementation.md": ("# Sprints, first version\n\nGates.\n", "# Sprints, last version\n\nGates.\n"),
    "epic-implementation.md": ("# Epics\n\nRoadmap.\n",),
    migrate.BASH_RULE: ("# Bash shapes, at the root\n",),
    migrate.BASH_RULE_NOW: ("# Bash shapes, in the rule's directory\n",),
    migrate.V1_AGENT_SOURCE: ("---\nname: sprint-coder\n---\n\nShip the step.\n",),
    "self-reflection/SKILL.md": ("---\nname: self-reflection\n---\n\nFirst.\n", "---\nname: self-reflection\n---\n\nLast.\n"),
    "usage-cost/SKILL.md": ("---\nname: usage-cost\n---\n\nCost.\n",),
    "usage-cost/scripts/usage_cost.py": ("print('cost')\n",),
    "json-tools/SKILL.md": ("---\nname: json-tools\n---\n\nJSON.\n",),
    "json-tools/scripts/common.py": ("def load():\n    return {}\n",),
    "csv-tools/SKILL.md": ("---\nname: csv-tools\n---\n\nCSV.\n",),
}
TABLE = migrate.Known({
    path: frozenset(digest for text in versions for digest in BUILDER.forms(text.encode("utf-8")))
    for path, versions in V1.items()
})

IMPORTS = "@rules/prd-implementation.md\n@rules/epic-implementation.md\n"
CLAUDE_MD = "# My instructions\n\nBe direct.\n\n" + IMPORTS + "\n## Tone\n\n- Short answers.\n"
OTHER_BLOCK = "<!-- multiagent-collab:start -->\nUse the baton.\n<!-- multiagent-collab:end -->\n"
EDITED = "---\nname: self-reflection\n---\n\nEdited by hand in this home.\n"
HAND_KEPT = "---\nname: prd-implementation\n---\n\nA hand-kept, skill-shaped copy of the v1 rule.\n"
BLOCK_START = "<!-- workflow-setup:start process -->"
BLOCK_END = "<!-- workflow-setup:end process -->"


def v1(path: str, version: int = -1) -> bytes:
    return V1[path][version].encode("utf-8")


class MigrateCase(RenderCase):
    """The fixture clone with the v1 skills' names in it, as the real one
    has, and the fixture table as the known hashes."""

    def setUp(self) -> None:
        super().setUp()
        for name in ("self-reflection", "json-tools", "csv-tools", "prd-implementation", "epic-implementation"):
            self.put(f"{name}/SKILL.md", SKILL.format(name=name))
        self.put("usage-cost/SKILL.md", SKILL.format(name="usage-cost").replace(
            "claude-code, codex", "claude-code (reads its own session logs)"))
        self.put(migrate.BASH_RULE_NOW, "Reshape the command.\n")
        self.put("tools/setup/workflow_setup.py", "# the tool\n")   # what makes a directory look like a clone
        # Kept, so that a test of the committed table can take it away.
        self.known_patch = mock.patch.object(migrate, "known", lambda: TABLE)
        self.known_patch.start()
        self.addCleanup(self.known_patch.stop)
        self.agents = self.claude / "agents"
        self.old_skills = self.codex / "skills"
        self.claude_md = self.claude / "CLAUDE.md"
        self.agents_md = self.codex / "AGENTS.md"

    # --- Running -------------------------------------------------------------

    def migrate(self, *argv: str, home: Path | None = None, host: homes.Host | None = None) -> tuple[int, str, str]:
        host = host or self.host
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: host)):
            return support.run("render", "--no-roles", "--migrate-v1", *argv, "--home", str(home or self.home))

    def migrated(self, *argv: str, **how) -> tuple[int, dict, str]:
        code, out, err = self.migrate("--json", *argv, **how)
        return code, json.loads(out), err

    def v1_check(self, home: Path | None = None, host: homes.Host | None = None) -> tuple[int, list[dict]]:
        host = host or self.host
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: host)):
            code, out, err = support.run("doctor", "--only", "v1", "--json", "--home", str(home or self.home))
        self.assertEqual(err, "", out)
        return code, json.loads(out)["checks"][0]["findings"]

    def said(self, report: dict, path: Path) -> dict:
        for item in report["migration"]["items"]:
            if item["path"] == str(path):
                return item
        self.fail(f"nothing said of {path} in {json.dumps(report['migration'], indent=1)}")

    def roots_of(self, home: Path, host: homes.Host | None = None):
        return homes.resolve(Locations(home=home, clone=self.clone), host or self.host).roots()

    def undo(self, home: Path | None = None, host: homes.Host | None = None) -> fileops.Result:
        """What ``uninstall`` is made of: the way back, then the state."""
        roots = self.roots_of(home or self.home, host)
        result = fileops.plan_reversal(roots).run(dry_run=False)
        self.assertTrue(fileops.remove_state(roots), fileops.read_record(roots).entries)
        return result

    def backups(self, home: Path | None = None) -> dict[str, bytes]:
        root = (home or self.home) / ".agents" / "workflow-setup" / "backups"
        return {
            Path(directory, name).relative_to(root).as_posix().split("/", 1)[1]: Path(directory, name).read_bytes()
            for directory, _, names in os.walk(root) for name in names
        }

    # --- Building ------------------------------------------------------------

    def data(self, path: Path, data: bytes | str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def copy(self, directory: Path, skill: str, version: int = -1) -> Path:
        """A copy of a v1 skill, every file a committed version."""
        for path in V1:
            if path.startswith(skill + "/"):
                self.data(directory / path[len(skill) + 1:], v1(path, version if path.endswith("SKILL.md") else -1))
        return directory

    def rule_copies(self, rules: Path) -> None:
        self.data(rules / "prd-implementation.md", v1("prd-implementation.md", 0))   # an older version
        self.data(rules / "epic-implementation.md", v1("epic-implementation.md"))
        self.data(rules / migrate.BASH_RULE, v1(migrate.BASH_RULE_NOW))

    def windows_home(self, home: Path) -> Path:
        """The Windows side of L1: both homes below ``home``."""
        claude, codex = home / ".claude", home / ".codex"
        self.data(claude / "CLAUDE.md", CLAUDE_MD)
        self.data(claude / "commands" / "note.md", "A command of the user's.\n")
        self.rule_copies(claude / "rules")
        if SYMLINKS:
            (claude / "agents").mkdir()
            os.symlink(str(self.clone / "agents" / "sprint-coder.md"), claude / "agents" / "sprint-coder.md")
        self.copy(claude / "skills" / "self-reflection", "self-reflection", 0)
        self.copy(claude / "skills" / "usage-cost", "usage-cost")
        old = claude / "skills" / "ai-skills"
        self.data(old / ".git" / "HEAD", "ref: refs/heads/main\n")
        self.copy(old / "json-tools", "json-tools")
        self.copy(old / "csv-tools", "csv-tools")
        self.data(codex / "AGENTS.md", "")
        self.data(codex / "skills" / ".system" / "note", "Codex's own.\n")
        self.data(codex / "skills" / "prd-implementation" / "SKILL.md", HAND_KEPT)
        self.data(codex / "skills" / "prd-implementation" / "references" / "rule.md", "The rule, reworded.\n")
        self.data(codex / "skills" / "self-reflection" / "SKILL.md", EDITED)
        self.data(codex / "skills" / "self-reflection" / "agents" / "openai.yaml", "policy: {}\n")
        return home

    def wsl_home(self, home: Path, windows: Path) -> Path:
        """The WSL side of L1: its homes, with the links into the Windows
        home at ``windows``."""
        claude, codex, theirs = home / ".claude", home / ".codex", windows / ".claude"
        for name in ("CLAUDE.md", "rules", "commands"):
            os.symlink(str(theirs / name), claude / name)
        (claude / "skills").mkdir()
        for name in ("self-reflection", "usage-cost"):
            os.symlink(str(theirs / "skills" / name), claude / "skills" / name)
        os.symlink(str(self.clone / "multiagent-collab"), claude / "skills" / "multiagent-collab")
        self.data(codex / "AGENTS.md", OTHER_BLOCK)
        self.data(codex / "skills" / "self-reflection" / "SKILL.md", EDITED)
        self.data(codex / "skills" / "self-reflection" / "agents" / "openai.yaml", "policy: {}\n")
        (home / ".agents" / "skills").mkdir(parents=True)
        os.symlink(str(self.clone / "multiagent-collab"), home / ".agents" / "skills" / "multiagent-collab")
        return home


# --- The instructions files -------------------------------------------------------

class InstructionsCase(MigrateCase):
    def test_the_import_lines_go_and_the_pointer_is_added(self) -> None:
        self.data(self.claude_md, CLAUDE_MD)
        code, report, err = self.migrated()
        self.assertEqual((code, err), (0, ""))
        text = self.claude_md.read_text(encoding="utf-8")
        block = f"{BLOCK_START}\n{migrate.POINTER}{BLOCK_END}\n"
        # Every other byte is as it was: the file without the two lines, then the block.
        self.assertEqual(text, CLAUDE_MD.replace(IMPORTS, "") + "\n" + block)
        self.assertIn("`prd-implementation`", migrate.POINTER)
        self.assertIn("`epic-implementation`", migrate.POINTER)
        self.assertIn("invoked by their names", migrate.POINTER)
        self.assertLessEqual(migrate.POINTER.count("\n"), 5)
        item = self.said(report, self.claude_md)
        self.assertEqual(item["status"], migrate.EDIT)
        self.assertIn("remove the lines @rules/prd-implementation.md and @rules/epic-implementation.md", item["says"])
        self.assertIn("    line 5: remove: @rules/prd-implementation.md", report["plan"])
        # The record holds each line with its place, and the file's backup.
        entry = fileops.read_record(self.roots()).entries["home:.claude/CLAUDE.md"]
        self.assertEqual([(one["index"], one["text"]) for one in entry["removed_lines"][0]],
                         [(4, "@rules/prd-implementation.md"), (5, "@rules/epic-implementation.md")])
        self.assertEqual(self.backups()["home/.claude/CLAUDE.md"], CLAUDE_MD.encode("utf-8"))

    def test_crlf_is_kept(self) -> None:
        before = CLAUDE_MD.replace("\n", "\r\n").encode("utf-8")
        self.data(self.claude_md, before)
        self.assertEqual(self.migrate()[0], 0)
        after = self.claude_md.read_bytes()
        self.assertNotIn(b"@rules/", after)
        self.assertEqual(after.count(b"\n"), after.count(b"\r\n"))
        self.assertIn(BLOCK_START.encode() + b"\r\n", after)
        self.assertTrue(after.startswith(CLAUDE_MD.replace(IMPORTS, "").replace("\n", "\r\n").encode("utf-8")))
        self.undo()
        self.assertEqual(self.claude_md.read_bytes(), before)

    def test_only_exactly_those_lines_are_removed(self) -> None:
        text = (
            "@rules/prd-implementation.md\n  @rules/epic-implementation.md\n@rules/other.md\n"
            "See @rules/prd-implementation.md for sprints.\n@rules/prd-implementation.mdx\n"
        )
        self.data(self.claude_md, text)
        self.assertEqual(self.migrate()[0], 0)
        after = self.claude_md.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(text.split("\n", 1)[1]))
        # What is left of v1 and is not the exact line is the user's to remove: doctor names each.
        code, findings = self.v1_check()
        self.assertEqual(code, 1)
        errors = [found["detail"] for found in findings if found["severity"] == doctor.ERROR]
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(all("remove it yourself" in detail for detail in errors))
        self.assertIn("line 1 still imports a v1 rule (@rules/epic-implementation.md)", errors[0])
        self.assertIn("line 3 ", errors[1])

    def test_neither_line_present_only_the_block_is_added(self) -> None:
        self.data(self.claude_md, "# Mine\n")
        code, report, _ = self.migrated()
        self.assertEqual(code, 0)
        self.assertEqual(self.claude_md.read_text(encoding="utf-8"),
                         f"# Mine\n\n{BLOCK_START}\n{migrate.POINTER}{BLOCK_END}\n")
        self.assertEqual(report["notes"], [])   # no "line not found": the lines were not asked for
        self.assertNotIn("removed_lines\": [\n", self.manifest_file.read_text(encoding="utf-8"))

    def test_a_file_that_is_absent_is_created_with_the_block_alone(self) -> None:
        code, report, _ = self.migrated()
        self.assertEqual(code, 0)
        wanted = f"{BLOCK_START}\n{migrate.POINTER}{BLOCK_END}\n"
        self.assertEqual(self.claude_md.read_text(encoding="utf-8"), wanted)
        self.assertEqual(self.agents_md.read_text(encoding="utf-8"), wanted)
        self.assertIn("in a new file", self.said(report, self.agents_md)["says"])
        self.undo()
        self.assertNothingAt(self.claude_md)
        self.assertNothingAt(self.agents_md)

    def test_agents_md_keeps_another_tools_block(self) -> None:
        self.data(self.agents_md, OTHER_BLOCK)
        self.assertEqual(self.migrate()[0], 0)
        text = self.agents_md.read_text(encoding="utf-8")
        self.assertEqual(text, f"{OTHER_BLOCK}\n{BLOCK_START}\n{migrate.POINTER}{BLOCK_END}\n")
        self.undo()
        self.assertEqual(self.agents_md.read_text(encoding="utf-8"), OTHER_BLOCK)

    def test_an_empty_agents_md_gets_the_block_and_is_empty_again_on_the_way_back(self) -> None:
        self.data(self.agents_md, "")
        self.assertEqual(self.migrate()[0], 0)
        self.assertIn(BLOCK_START, self.agents_md.read_text(encoding="utf-8"))
        self.undo()
        self.assertEqual(self.agents_md.read_bytes(), b"")

    def test_a_pointer_edited_by_hand_is_kept(self) -> None:
        self.assertEqual(self.migrate()[0], 0)
        text = self.claude_md.read_text(encoding="utf-8").replace("Sprint and epic work", "All work")
        self.data(self.claude_md, text)
        code, report, _ = self.migrated()
        self.assertEqual(code, render.EXIT_NEEDS_FLAG)   # kept, and the code says that something was
        self.assertEqual(self.claude_md.read_text(encoding="utf-8"), text)
        self.assertEqual(self.said(report, self.claude_md)["status"], migrate.KEPT)
        self.assertIn("edited by hand", self.said(report, self.claude_md)["says"])
        self.assertEqual(self.migrate("--overwrite-edited")[0], 0)
        self.assertIn("Sprint and epic work", self.claude_md.read_text(encoding="utf-8"))

    def test_nothing_without_the_option(self) -> None:
        self.data(self.claude_md, CLAUDE_MD)
        self.rule_copies(self.rules)
        code, out, _ = self.render()
        self.assertEqual(code, 0)
        self.assertEqual(self.claude_md.read_text(encoding="utf-8"), CLAUDE_MD)
        self.assertEqual((self.rules / "prd-implementation.md").read_bytes(), v1("prd-implementation.md", 0))
        self.assertNotIn("v1 migration:", out)
        self.assertNothingAt(self.agents_md)


# --- Copies ------------------------------------------------------------------------

class CopiesCase(MigrateCase):
    def test_a_known_copy_is_removed_and_backed_up(self) -> None:
        self.rule_copies(self.rules)
        self.data(self.agents / "sprint-coder.md", v1(migrate.V1_AGENT_SOURCE).replace(b"\n", b"\r\n"))   # a CRLF checkout
        self.copy(self.old_skills / "json-tools", "json-tools")
        self.data(self.old_skills / "json-tools" / "scripts" / "__pycache__" / "common.cpython-312.pyc", b"\0compiled")
        mine = self.keep(self.rules / "my-own-rule.md")
        code, report, err = self.migrated()
        self.assertEqual((code, err), (0, ""))
        for path in (self.rules / "prd-implementation.md", self.rules / "epic-implementation.md",
                     self.rules / migrate.BASH_RULE, self.agents / "sprint-coder.md", self.old_skills / "json-tools"):
            self.assertNothingAt(path)
            self.assertEqual(self.said(report, path)["status"], migrate.REMOVE)
        self.assertTrue(mine.is_file())
        self.assertEqual(sorted(os.listdir(self.rules)), ["avoid-bash-injection-heuristics", "my-own-rule.md", "sample"])
        saved = self.backups()
        self.assertEqual(saved["home/.claude/rules/prd-implementation.md"], v1("prd-implementation.md", 0))
        self.assertEqual(saved["home/.codex/skills/json-tools/scripts/common.py"], v1("json-tools/scripts/common.py"))
        self.assertEqual(saved["home/.codex/skills/json-tools/scripts/__pycache__/common.cpython-312.pyc"], b"\0compiled")
        self.assertIn("remove file home:.claude/rules/epic-implementation.md (backup)", report["plan"])
        self.assertIn("remove directory home:.codex/skills/json-tools", report["plan"])
        entries = fileops.read_record(self.roots()).entries
        self.assertEqual(entries["home:.claude/agents/sprint-coder.md"]["kind"], "removed-file")
        self.assertEqual(entries["home:.codex/skills/json-tools"], {"kind": "removed-directory"})
        self.assertIn("v1: 5 removed, 2 edited", report["summary"])

    def test_the_dry_run_warns_that_project_links_will_dangle(self) -> None:
        self.rule_copies(self.rules)
        code, out, _ = self.migrate("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn(f"warning: {migrate.DANGLING}", out.splitlines())
        self.assertIn("project-level links to the removed rule copies will dangle", migrate.DANGLING)
        # Not where no rule copy is to be removed.
        for name in os.listdir(self.rules):
            os.remove(self.rules / name)
        self.copy(self.old_skills / "csv-tools", "csv-tools")
        code, report, _ = self.migrated("--dry-run")
        self.assertEqual(report["migration"]["warnings"], [])

    def test_a_hand_edited_copy_is_kept_and_reported_with_the_flag(self) -> None:
        copy = self.old_skills / "self-reflection"
        self.data(copy / "SKILL.md", EDITED)
        self.data(copy / "agents" / "openai.yaml", "policy: {}\n")
        edited = self.data(self.rules / "prd-implementation.md", "# Sprints, as I changed them\n")
        before = {root: tree(root) for root in (self.claude, self.codex)}
        code, report, err = self.migrated("--dry-run")
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        item = self.said(report, copy)
        self.assertEqual(item["status"], migrate.KEPT)
        self.assertIn("2 entries match no committed version (SKILL.md, agents/openai.yaml (not a file of the skill))", item["says"])
        self.assertEqual(item["flag"], f"--remove-stale {migrate.quoted(copy)}")
        self.assertIn(f"render --migrate-v1 --remove-stale {migrate.quoted(copy)}", item["says"])
        self.assertIn(f"--remove-stale {migrate.quoted(edited)}", self.said(report, edited)["says"])

        code, out, _ = self.migrate()
        self.assertEqual(code, render.EXIT_NEEDS_FLAG)
        # Everything that was there is there, byte for byte. (Review
        # finding S14: this compared a union with itself, and so passed on
        # changed bytes.)
        for root, was in before.items():
            now = tree(root)
            self.assertEqual({name: now.get(name) for name in was}, was)
        self.assertEqual((copy / "SKILL.md").read_text(encoding="utf-8"), EDITED)
        self.assertEqual(edited.read_text(encoding="utf-8"), "# Sprints, as I changed them\n")
        self.assertIn("v1: 2 edited, 2 kept", out.splitlines()[-1])

    def test_remove_stale_removes_a_named_copy_after_a_backup(self) -> None:
        copy = self.old_skills / "self-reflection"
        self.data(copy / "SKILL.md", EDITED)
        self.data(copy / "agents" / "openai.yaml", "policy: {}\n")
        other = self.data(self.old_skills / "prd-implementation" / "SKILL.md", HAND_KEPT)
        code, report, err = self.migrated("--remove-stale", str(copy))
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))   # the other one is still kept
        self.assertNothingAt(copy)
        self.assertEqual(other.read_text(encoding="utf-8"), HAND_KEPT)
        self.assertIn("because --remove-stale names it", self.said(report, copy)["says"])
        saved = self.backups()
        self.assertEqual(saved["home/.codex/skills/self-reflection/SKILL.md"], EDITED.encode("utf-8"))
        self.assertEqual(saved["home/.codex/skills/self-reflection/agents/openai.yaml"], b"policy: {}\n")
        code, _, _ = self.migrated("--remove-stale", str(copy), "--remove-stale", str(other.parent))
        self.assertEqual(code, 0)
        self.assertNothingAt(other.parent)
        self.undo()
        self.assertEqual((copy / "SKILL.md").read_text(encoding="utf-8"), EDITED)
        self.assertEqual(other.read_text(encoding="utf-8"), HAND_KEPT)

    def test_remove_stale_refuses_a_path_that_is_not_a_v1_location(self) -> None:
        mine = self.keep(self.claude / "notes" / "keep.md")
        own_skill = self.keep(self.old_skills / "my-skill" / "SKILL.md")
        system = self.keep(self.old_skills / ".system" / "note")
        before = tree(self.root)
        for path in (mine, mine.parent, own_skill.parent, system.parent, self.claude, self.home, self.root / "nowhere",
                     self.claude_skills / "multiagent-collab", self.claude / "settings.json"):
            code, out, err = self.migrate("--remove-stale", str(path))
            self.assertEqual(code, 2, path)
            self.assertIn(f"--remove-stale {path}: not a place a v1 install used", err)
            self.assertIn("it removes nothing else", err)
            self.assertEqual(tree(self.root), before)

    def test_remove_stale_refuses_what_is_not_a_v1_copy_at_a_v1_location(self) -> None:
        odd = self.rules / "prd-implementation.md"
        self.keep(odd / "inner.md")   # a directory where the rule file was
        before = tree(self.root)
        code, _, err = self.migrate("--remove-stale", str(odd))
        self.assertEqual(code, 2)
        self.assertIn("not a copy or a link a v1 install left", err)
        self.assertEqual(tree(self.root), before)

    def test_remove_stale_needs_the_migration(self) -> None:
        code, _, err = self.render("--remove-stale", str(self.old_skills / "self-reflection"))
        self.assertEqual(code, 2)
        self.assertIn("give --migrate-v1 with it", err)

    def test_a_skill_directory_with_one_unknown_file_is_kept(self) -> None:
        copy = self.copy(self.old_skills / "json-tools", "json-tools")
        extra = self.data(copy / "scripts" / "mine.py", "print('mine')\n")
        swap = self.data(copy / ".SKILL.md.swp", b"\0editor")
        code, report, _ = self.migrated()
        self.assertEqual(code, render.EXIT_NEEDS_FLAG)
        self.assertTrue(extra.is_file() and swap.is_file() and (copy / "SKILL.md").is_file())
        says = self.said(report, copy)["says"]
        self.assertIn("scripts/mine.py (not a file of the skill)", says)
        self.assertIn(".SKILL.md.swp (not a file of the skill)", says)

    def test_a_link_or_an_empty_directory_inside_a_copy_keeps_it(self) -> None:
        one = self.copy(self.old_skills / "csv-tools", "csv-tools")
        (one / "references").mkdir()
        code, report, _ = self.migrated()
        self.assertEqual(code, render.EXIT_NEEDS_FLAG)
        self.assertIn("references/ (an empty directory)", self.said(report, one)["says"])
        self.assertTrue((one / "SKILL.md").is_file())

    @unittest.skipUnless(SYMLINKS, "needs a link to a file")
    def test_a_link_inside_a_copy_goes_as_a_link_with_remove_stale(self) -> None:
        # The Windows Claude Code copy of usage-cost on the real machine: SKILL.md and a link to the script.
        script = self.keep(self.root / "elsewhere" / "usage_cost.py")
        copy = self.old_skills / "usage-cost"
        self.data(copy / "SKILL.md", v1("usage-cost/SKILL.md"))
        os.symlink(str(script), copy / "usage_cost.py")
        code, report, _ = self.migrated()
        self.assertEqual(code, render.EXIT_NEEDS_FLAG)
        self.assertIn("usage_cost.py (a link)", self.said(report, copy)["says"])
        self.assertEqual(self.migrate("--remove-stale", str(copy))[0], 0)
        self.assertNothingAt(copy)
        self.assertTrue(script.is_file())
        self.undo()
        self.assertLinked(copy / "usage_cost.py", script)

    def test_a_credentials_file_in_a_copy_is_never_touched(self) -> None:
        copy = self.copy(self.old_skills / "csv-tools", "csv-tools")
        secret = self.data(copy / "auth.json", '{"token": "s3cr3t-value"}')
        before = tree(copy)
        code, report, _ = self.migrated()
        self.assertEqual(code, 0)
        self.assertEqual(self.said(report, copy)["status"], migrate.KEPT)
        self.assertNotIn("s3cr3t-value", json.dumps(report))
        code, _, err = self.migrate("--remove-stale", str(copy))
        self.assertEqual(code, 2)
        self.assertIn("setup cannot remove it", err)
        self.assertEqual(secret.read_text(encoding="utf-8"), '{"token": "s3cr3t-value"}')
        self.assertEqual(tree(copy), before)
        self.assertNotIn("auth.json", self.manifest_file.read_text(encoding="utf-8"))

    def test_the_clone_is_never_removed(self) -> None:
        old = self.claude_skills / "ai-skills"
        self.data(old / ".git" / "HEAD", "ref: refs/heads/main\n")
        self.copy(old / "json-tools", "json-tools")
        named = self.copy(self.old_skills / "csv-tools", "csv-tools")   # a v1 name, and a working tree of its own
        self.data(named / ".git" / "HEAD", "ref: refs/heads/main\n")
        before = tree(old) | tree(named)
        code, report, err = self.migrated()
        self.assertEqual((code, err), (0, ""))
        for path in (old, named):
            item = self.said(report, path)
            self.assertEqual(item["status"], migrate.NEVER)
            self.assertIn("setup never removes a clone, it is yours to move away", item["says"])
            code, _, err = self.migrate("--remove-stale", str(path))
            self.assertEqual(code, 2)
            self.assertIn("setup never removes a clone", err)
        self.assertEqual(tree(old) | tree(named), before)
        code, findings = self.v1_check()
        self.assertEqual(code, 1)
        details = [found["detail"] for found in findings if found["severity"] == doctor.ERROR]
        self.assertEqual(len(details), 2)
        self.assertTrue(all("remove it yourself" in detail for detail in details))

    def test_a_skills_directory_that_is_itself_a_clone_is_left_whole(self) -> None:
        # ``git clone <url> ~/.claude/skills``, as the v1 README said.
        self.data(self.old_skills / ".git" / "HEAD", "ref: refs/heads/main\n")
        self.copy(self.old_skills / "json-tools", "json-tools")
        before = tree(self.old_skills)
        code, report, _ = self.migrated()
        self.assertEqual(code, 0)
        self.assertEqual(self.said(report, self.old_skills)["status"], migrate.NEVER)
        self.assertEqual(tree(self.old_skills), before)


# --- Links -------------------------------------------------------------------------

@unittest.skipUnless(SYMLINKS, "needs links to files")
class LinksCase(MigrateCase):
    def test_a_v1_link_is_removed_as_a_link_and_its_target_stays(self) -> None:
        source = self.root / "another-clone"
        self.data(source / ".git" / "HEAD", "ref: refs/heads/main\n")
        rule = self.data(source / "prd-implementation.md", v1("prd-implementation.md"))
        agent = self.data(source / "agents" / "sprint-coder.md", v1(migrate.V1_AGENT_SOURCE))
        self.rules.mkdir()
        self.agents.mkdir()
        os.symlink(str(rule), self.rules / "prd-implementation.md")
        os.symlink(str(agent), self.agents / "sprint-coder.md")
        before = tree(source)
        code, report, err = self.migrated()
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.rules / "prd-implementation.md")
        self.assertNothingAt(self.agents / "sprint-coder.md")
        self.assertEqual(tree(source), before)   # the sentinel: what the links led to
        self.assertIn("removed as a link, its target untouched", self.said(report, self.agents / "sprint-coder.md")["says"])
        self.assertIn("remove link home:.claude/agents/sprint-coder.md", report["plan"])
        entry = fileops.read_record(self.roots()).entries["home:.claude/agents/sprint-coder.md"]
        self.assertEqual((entry["kind"], entry["target"]), ("removed-link", f"raw:{agent}"))
        self.assertEqual(self.backups(), {})   # a link is recorded; nothing is copied
        self.undo()
        self.assertLinked(self.agents / "sprint-coder.md", agent)
        self.assertLinked(self.rules / "prd-implementation.md", rule)

    def test_a_link_into_a_clone_that_moved_on_to_v2_is_a_v1_link(self) -> None:
        # The real ``agents/sprint-coder.md``: its target left the clone with v2, so it leads nowhere.
        self.agents.mkdir()
        os.symlink(str(self.clone / "agents" / "sprint-coder.md"), self.agents / "sprint-coder.md")
        before = tree(self.clone)
        code, report, _ = self.migrated()
        self.assertEqual(code, 0)
        self.assertNothingAt(self.agents / "sprint-coder.md")
        item = self.said(report, self.agents / "sprint-coder.md")
        self.assertEqual(item["status"], migrate.REMOVE)
        self.assertIn("a link into the clone setup runs from, which no longer has it", item["says"])
        self.assertEqual(tree(self.clone), before)

    def test_a_link_that_leads_nowhere_outside_the_clone_is_kept_until_it_is_named(self) -> None:
        # It may have led into another clone, or to a file of the user's: setup cannot tell.
        self.rules.mkdir()
        link = self.rules / "prd-implementation.md"
        text = str(self.root / "gone" / "prd-implementation.md")
        os.symlink(text, link)
        for more in (("--dry-run",), ()):
            code, report, err = self.migrated(*more)
            self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
            item = self.said(report, link)
            self.assertEqual((item["status"], item["flag"]), (migrate.KEPT, f"--remove-stale {migrate.quoted(link)}"))
            self.assertIn("which leads nowhere, outside the clone setup runs from", item["says"])
            self.assertEqual(fsio.read_link(link), text)
        code, report, err = self.migrated("--remove-stale", str(link))
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(link)
        self.undo()
        self.assertEqual(fsio.read_link(link), text)

    def test_a_link_whose_text_is_the_other_systems_path_is_recorded_as_it_is(self) -> None:
        # The real Windows ``agents/sprint-coder.md`` was made from WSL: its text is a WSL path.
        # Put together here, so that this file holds no path of a machine.
        text = "/".join(["", "mnt", "q", "workspace", "ai-skills", "agents", "sprint-coder.md"])
        self.agents.mkdir()
        os.symlink(text, self.agents / "sprint-coder.md")
        # Here it leads nowhere, and not into the clone this run uses: kept until it is named.
        code, report, err = self.migrated()
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        self.assertEqual(self.said(report, self.agents / "sprint-coder.md")["status"], migrate.KEPT)
        self.assertEqual(fsio.look(self.agents / "sprint-coder.md").target.replace("\\", "/"), text)
        code, report, err = self.migrated("--remove-stale", str(self.agents / "sprint-coder.md"))
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.agents / "sprint-coder.md")
        entry = fileops.read_record(self.roots()).entries["home:.claude/agents/sprint-coder.md"]
        self.assertEqual((entry["kind"], entry["target"]), ("removed-link", f"raw:{text}"))
        self.undo()
        self.assertEqual(fsio.look(self.agents / "sprint-coder.md").target.replace("\\", "/"), text)

    def test_an_unrecognised_link_is_kept(self) -> None:
        mine = self.keep(self.root / "my-notes" / "prd-implementation.md", "# My own rule of that name\n")
        other = self.keep(self.root / "my-notes" / "sprint-coder.md")
        skill = self.keep(self.root / "my-skills" / "self-reflection" / "SKILL.md").parent
        self.rules.mkdir()
        self.agents.mkdir()
        os.symlink(str(mine), self.rules / "prd-implementation.md")
        os.symlink(str(other), self.agents / "sprint-coder.md")
        os.symlink(str(self.root / "my-notes" / "missing.md"), self.rules / "epic-implementation.md")
        self.old_skills.mkdir()
        os.symlink(str(skill), self.old_skills / "self-reflection")
        links = (self.rules / "prd-implementation.md", self.agents / "sprint-coder.md",
                 self.rules / "epic-implementation.md", self.old_skills / "self-reflection")
        before = {link: os.readlink(link) for link in links}
        code, report, _ = self.migrated()
        self.assertEqual(code, render.EXIT_NEEDS_FLAG)
        for link in links:
            self.assertEqual(os.readlink(link), before[link])
            item = self.said(report, link)
            self.assertEqual(item["status"], migrate.KEPT)
            self.assertIn(f"--remove-stale {migrate.quoted(link)}", item["says"])
        code, findings = self.v1_check()
        self.assertEqual((code, len([one for one in findings if one["severity"] == doctor.ERROR])), (1, 4))
        # Named, the link goes, and never what it leads to.
        self.assertEqual(self.migrate(*[part for link in links for part in ("--remove-stale", str(link))])[0], 0)
        for link in links:
            self.assertNothingAt(link)
        self.assertEqual(mine.read_text(encoding="utf-8"), "# My own rule of that name\n")
        self.assertTrue((skill / "SKILL.md").is_file())


@unittest.skipUnless(LINKS, "needs links to directories")
class SamePathCase(MigrateCase):
    """Migration removes at a path, and the skills part links there, in
    one plan."""

    def test_a_copy_is_replaced_by_setups_link_and_comes_back(self) -> None:
        copy = self.copy(self.claude_skills / "self-reflection", "self-reflection")
        self.data(copy / "references" / "deep" / "note.md", v1("self-reflection/SKILL.md"))   # not the skill's: kept
        code, report, _ = self.migrated()
        self.assertEqual(code, 2)   # in the way of the link, and not a known copy
        self.assertIn(f"`render --migrate-v1 --remove-stale {migrate.quoted(copy)}` removes it after a backup",
                      report["errors"][0])
        os.remove(copy / "references" / "deep" / "note.md")
        os.rmdir(copy / "references" / "deep")
        os.rmdir(copy / "references")
        before = tree(self.claude_skills)
        code, report, err = self.migrated()
        self.assertEqual((code, err), (0, ""))
        self.assertLinked(copy, self.clone / "self-reflection")
        self.assertEqual(self.items(report, "claude-code", "skills")["self-reflection"], render.CREATE)
        self.assertIn("create link home:.claude/skills/self-reflection -> clone:self-reflection, in place of the "
                      "directory there", report["plan"])
        entry = fileops.read_record(self.roots()).entries["home:.claude/skills/self-reflection"]
        self.assertEqual(entry, {"kind": "link", "target": "clone:self-reflection",
                                 "replaced": {"kind": "removed-directory"}})
        self.assertEqual((self.clone / "self-reflection" / "SKILL.md").read_bytes(),
                         SKILL.format(name="self-reflection").encode("utf-8"))
        # A second run: nothing.
        code, again, _ = self.migrated()
        self.assertEqual((code, again["plan"], again["changed"]), (0, [], False))
        self.undo()
        self.assertEqual({name: what for name, what in tree(self.claude_skills).items()
                          if name.startswith("self-reflection")}, before)

    def test_a_known_copy_in_the_way_is_named_without_the_option(self) -> None:
        self.copy(self.claude_skills / "self-reflection", "self-reflection")
        code, out, err = self.render()
        self.assertEqual(code, 2)
        self.assertIn(f"{self.claude_skills / 'self-reflection'}: a copy of the v1 skill self-reflection, every file a "
                      "known committed version, which an earlier (v1) install left and setup did not make; "
                      "`render --migrate-v1` removes it and links here", err)
        self.assertIn("render --migrate-v1 --dry-run", err.splitlines()[-1])

    def test_a_link_setup_did_not_make_into_this_clone_becomes_setups(self) -> None:
        self.claude_skills.mkdir()
        fsio.make_link(str(self.clone / "json-tools"), self.claude_skills / "json-tools", True)
        self.assertEqual(self.render()[0], 2)
        before = tree(self.claude_skills)
        code, report, _ = self.migrated()
        self.assertEqual(code, 0)
        self.assertLinked(self.claude_skills / "json-tools", self.clone / "json-tools")
        self.undo()
        self.assertEqual(tree(self.claude_skills), before)   # the user's link is there again


@unittest.skipUnless(SYMLINKS and POSIX, "the view from WSL is rebuilt from symlinks on a POSIX file system")
class MachineCase(MigrateCase):
    """The four homes of L1."""

    def setUp(self) -> None:
        super().setUp()
        self.drive = self.root / "drive"
        self.win = self.windows_home(self.drive / "Users" / "someone")
        self.wsl_home(self.home, self.win)
        self.wsl = homes.Host(homes.WSL, {"PATH": ""}, (str(self.drive),))
        self.win_codex_copies = (self.win / ".codex" / "skills" / "prd-implementation",
                                 self.win / ".codex" / "skills" / "self-reflection")

    def test_the_dry_run_on_each_side_changes_nothing_and_names_the_flags(self) -> None:
        before = tree(self.root)
        code, report, err = self.migrated("--dry-run", home=self.win)
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        self.assertEqual(tree(self.root), before)
        for copy in self.win_codex_copies:
            self.assertEqual(self.said(report, copy)["flag"], f"--remove-stale {migrate.quoted(copy)}")
        self.assertEqual(self.said(report, self.win / ".claude" / "skills" / "ai-skills")["status"], migrate.NEVER)
        self.assertEqual(report["migration"]["warnings"], [migrate.DANGLING])

        code, out, err = self.migrate("--dry-run", host=self.wsl)
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        self.assertEqual(tree(self.root), before)
        self.assertNothingAt(self.home / ".agents" / "workflow-setup")
        lines = out.splitlines()
        copy = self.home / ".codex" / "skills" / "self-reflection"
        self.assertTrue(any(line.startswith(f"  {copy}: kept: ") and
                            line.endswith(f"render --migrate-v1 --remove-stale {migrate.quoted(copy)}") for line in lines))
        self.assertIn(f"  {self.claude_md}: skipped: other side (windows): a link to {self.win / '.claude' / 'CLAUDE.md'}; "
                      "skipped here, the windows side owns it", lines)

    def test_the_other_sides_paths_are_skipped(self) -> None:
        drive_before = tree(self.drive)
        code, report, err = self.migrated("--remove-stale", str(self.home / ".codex" / "skills" / "self-reflection"),
                                          host=self.wsl)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.drive), drive_before)   # nothing of the Windows side changed
        for name in ("prd-implementation.md", "epic-implementation.md", migrate.BASH_RULE):
            item = self.said(report, self.rules / name)
            self.assertEqual(item["status"], migrate.SKIPPED)
            self.assertIn("other side (windows)", item["says"])
        self.assertEqual(self.said(report, self.claude_md)["status"], migrate.SKIPPED)
        self.assertEqual(report["migration"]["warnings"], [])   # no rule copy is removed from here
        # A path of the other side cannot be named for removal either.
        code, _, err = self.migrate("--remove-stale", str(self.rules / "prd-implementation.md"), host=self.wsl)
        self.assertEqual(code, 2)
        self.assertIn("run the migration on that side", err)
        self.assertEqual(tree(self.drive), drive_before)

    def test_the_wsl_links_to_the_windows_copies_become_setups_links(self) -> None:
        drive_before = tree(self.drive)
        code, report, _ = self.migrated(host=self.wsl)
        self.assertEqual(code, render.EXIT_NEEDS_FLAG)   # the Codex copy is kept
        for name in ("self-reflection", "usage-cost"):
            self.assertLinked(self.claude_skills / name, self.clone / name)
            item = self.said(report, self.claude_skills / name)
            self.assertEqual(item["status"], migrate.REMOVE)
            self.assertIn("as a link to a copy whose every file is a known committed version", item["says"])
        self.assertEqual(os.readlink(self.claude_skills / "multiagent-collab"), str(self.clone / "multiagent-collab"))
        self.assertEqual(tree(self.drive), drive_before)   # the copies the links led to are intact
        entry = fileops.read_record(self.roots_of(self.home, self.wsl)).entries["home:.claude/skills/usage-cost"]
        self.assertEqual(entry["replaced"]["target"], f"raw:{self.win / '.claude' / 'skills' / 'usage-cost'}")
        self.assertEqual(self.agents_md.read_text(encoding="utf-8"),
                         f"{OTHER_BLOCK}\n{BLOCK_START}\n{migrate.POINTER}{BLOCK_END}\n")

    def test_windows_first_then_wsl_then_a_second_run_and_the_way_back(self) -> None:
        start = tree(self.root)
        # Windows, which owns the shared rules and CLAUDE.md.
        stale = [part for copy in self.win_codex_copies for part in ("--remove-stale", str(copy))]
        code, report, err = self.migrated(*stale, home=self.win)
        self.assertEqual((code, err), (0, ""))
        claude = self.win / ".claude"
        self.assertEqual(sorted(os.listdir(claude / "rules")), ["avoid-bash-injection-heuristics", "sample"])
        self.assertEqual(os.listdir(claude / "agents"), [])
        self.assertNotIn("@rules/", (claude / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertEqual(sorted(os.listdir(self.win / ".codex" / "skills")), [".system"])
        self.assertTrue((claude / "skills" / "ai-skills" / ".git" / "HEAD").is_file())   # the old clone stays
        for name in ("self-reflection", "usage-cost"):
            self.assertLinked(claude / "skills" / name, self.clone / name)
        self.assertEqual((claude / "commands" / "note.md").read_text(encoding="utf-8"), "A command of the user's.\n")
        # doctor on the Windows side: the clone is all that is left.
        code, findings = self.v1_check(home=self.win)
        errors = [found["detail"] for found in findings if found["severity"] == doctor.ERROR]
        self.assertEqual((code, len(errors)), (1, 1))
        self.assertIn(str(claude / "skills" / "ai-skills"), errors[0])

        # WSL.
        mine = self.home / ".codex" / "skills" / "self-reflection"
        code, report, err = self.migrated("--remove-stale", str(mine), host=self.wsl)
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(mine)
        for name in ("self-reflection", "usage-cost"):
            self.assertLinked(self.claude_skills / name, self.clone / name)
        code, findings = self.v1_check(host=self.wsl)
        self.assertEqual(code, 0)
        self.assertEqual([found for found in findings if found["severity"] in (doctor.ERROR, doctor.WARNING)], [])

        # A second run on each side plans nothing and writes nothing.
        after = tree(self.root)
        for how in ({"home": self.win}, {"host": self.wsl}):
            options = stale if "home" in how else ["--remove-stale", str(mine)]
            code, again, err = self.migrated(*options, **how)
            self.assertEqual((code, err, again["plan"], again["changed"]), (0, "", [], False))
            self.assertEqual(tree(self.root), after)

        # The way back, WSL then Windows: every path, link target and byte as at the start.
        self.undo(host=self.wsl)
        self.undo(home=self.win)
        self.assertEqual(tree(self.root), start)

    def test_doctor_before_after_and_with_a_kept_copy(self) -> None:
        # Before: everything this side can change is an error with its command.
        code, findings = self.v1_check(home=self.win)
        self.assertEqual(code, 1)
        errors = {found["subject"]: found["detail"] for found in findings if found["severity"] == doctor.ERROR}
        claude, codex = self.win / ".claude", self.win / ".codex"
        self.assertEqual(sorted(errors), sorted(str(path) for path in (
            claude / "CLAUDE.md", claude / "rules" / "prd-implementation.md", claude / "rules" / "epic-implementation.md",
            claude / "rules" / migrate.BASH_RULE, claude / "agents" / "sprint-coder.md",
            claude / "skills" / "self-reflection", claude / "skills" / "usage-cost", claude / "skills" / "ai-skills",
            codex / "skills" / "prd-implementation", codex / "skills" / "self-reflection",
        )))
        self.assertIn("`render --migrate-v1` removes it after a backup", errors[str(claude / "rules" / "prd-implementation.md")])
        self.assertIn(f"`render --migrate-v1 --remove-stale {migrate.quoted(codex / 'skills' / 'self-reflection')}`",
                      errors[str(codex / "skills" / "self-reflection")])
        self.assertIn("remove it yourself", errors[str(claude / "skills" / "ai-skills")])
        both = [found["detail"] for found in findings if found["subject"] == str(claude / "CLAUDE.md")]
        self.assertEqual(len(both), 2)
        self.assertIn("removes the line and adds a pointer", both[0])

        # From WSL: its own are errors, the Windows side's are read and are info.
        code, findings = self.v1_check(host=self.wsl)
        self.assertEqual(code, 1)
        errors = sorted(found["subject"] for found in findings if found["severity"] == doctor.ERROR)
        self.assertEqual(errors, sorted(str(path) for path in (
            self.claude_skills / "self-reflection", self.claude_skills / "usage-cost",
            self.home / ".codex" / "skills" / "self-reflection",
        )))
        infos = [found["detail"] for found in findings if found["severity"] == doctor.INFO]
        self.assertEqual(len(infos), 5)   # two import lines and three rule copies
        self.assertTrue(all("the windows side's to migrate: run `render --migrate-v1` there" in detail
                            or "the windows side's to migrate" in detail for detail in infos))

        # After a migration that keeps the edited copies: an error naming the flag, and nothing else but the clone.
        self.assertEqual(self.migrate(home=self.win)[0], render.EXIT_NEEDS_FLAG)
        code, findings = self.v1_check(home=self.win)
        errors = {found["subject"]: found["detail"] for found in findings if found["severity"] == doctor.ERROR}
        self.assertEqual((code, len(errors)), (1, 3))
        for copy in self.win_codex_copies:
            self.assertIn(f"--remove-stale {migrate.quoted(copy)}", errors[str(copy)])

        # After the user decided, and removed the clone: clean.
        stale = [part for copy in self.win_codex_copies for part in ("--remove-stale", str(copy))]
        self.assertEqual(self.migrate(*stale, home=self.win)[0], 0)
        import shutil
        shutil.rmtree(claude / "skills" / "ai-skills")
        code, findings = self.v1_check(home=self.win)
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))


class SecondRunCase(MigrateCase):
    def test_a_second_run_changes_nothing(self) -> None:
        self.data(self.claude_md, CLAUDE_MD)
        self.data(self.agents_md, OTHER_BLOCK)
        self.rule_copies(self.rules)
        self.data(self.agents / "sprint-coder.md", v1(migrate.V1_AGENT_SOURCE))
        self.copy(self.old_skills / "json-tools", "json-tools")
        kept = self.data(self.old_skills / "self-reflection" / "SKILL.md", EDITED).parent
        self.assertEqual(self.migrate()[0], render.EXIT_NEEDS_FLAG)
        before = tree(self.root)
        for argv in ((), ("--dry-run",)):
            code, report, err = self.migrated(*argv)
            self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
            self.assertEqual((report["plan"], report["changed"], report["notes"]), ([], False, []))
            self.assertEqual(tree(self.root), before)
            self.assertEqual(self.said(report, kept)["status"], migrate.KEPT)
            self.assertEqual(self.said(report, self.claude_md)["status"], migrate.UP_TO_DATE)
        code, out, _ = self.migrate()
        self.assertTrue(out.splitlines()[-1].startswith(f"{fileops.UP_TO_DATE}; nothing was written"))
        # And a plain render after it leaves what migration did alone.
        self.assertEqual(self.render()[0], 0)
        self.assertEqual(tree(self.root), before)

    def test_the_dry_run_changes_nothing(self) -> None:
        self.data(self.claude_md, CLAUDE_MD)
        self.rule_copies(self.rules)
        self.copy(self.claude_skills / "self-reflection", "self-reflection")
        before = tree(self.root)
        code, report, err = self.migrated("--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.root), before)
        self.assertTrue(report["dry_run"] and report["changed"] and not report["applied"])
        self.assertNothingAt(self.home / ".agents")

    def test_the_round_trip_restores_every_path_link_and_byte(self) -> None:
        self.data(self.claude_md, CLAUDE_MD.replace("\n", "\r\n"))
        self.data(self.agents_md, OTHER_BLOCK)
        self.rule_copies(self.rules)
        self.data(self.agents / "sprint-coder.md", v1(migrate.V1_AGENT_SOURCE))
        self.copy(self.claude_skills / "self-reflection", "self-reflection")
        self.copy(self.claude_skills / "usage-cost", "usage-cost")
        self.copy(self.old_skills / "json-tools", "json-tools")
        edited = self.data(self.old_skills / "self-reflection" / "SKILL.md", EDITED).parent
        self.data(edited / "agents" / "openai.yaml", "policy: {}\n")
        if POSIX:
            os.chmod(self.rules / "prd-implementation.md", 0o640)
        before = tree(self.root)
        modes = {path: fsio.look(path).mode for path in (self.rules / "prd-implementation.md", self.claude_md)}
        self.assertEqual(self.migrate("--remove-stale", str(edited))[0], 0)
        self.assertNotEqual(tree(self.root), before)
        result = self.undo()
        self.assertEqual(result.kept, [])
        self.assertEqual(tree(self.root), before)
        self.assertEqual({path: fsio.look(path).mode for path in modes}, modes)


# --- doctor: one thing reported once ------------------------------------------------

class DoctorOnceCase(DoctorCase):
    def setUp(self) -> None:
        super().setUp()
        patch = mock.patch.object(migrate, "known", lambda: TABLE)
        patch.start()
        self.addCleanup(patch.stop)
        self.put("self-reflection/SKILL.md", SKILL.format(name="self-reflection"))

    def test_a_v1_leftover_in_the_way_is_the_v1_checks_and_not_the_missing_checks(self) -> None:
        copy = self.claude_skills / "self-reflection"
        for path, versions in V1.items():
            if path.startswith("self-reflection/"):
                self.write(copy / path.split("/", 1)[1], versions[-1])
        self.keep(self.claude_skills / "alpha" / "SKILL.md")   # in the way, and nothing of v1
        code, report = self.doctor("--only", "missing", "--only", "v1")
        self.assertEqual(code, 1)
        found = {check["name"]: check["findings"] for check in report["checks"]}
        missing = [one["detail"] for one in found["missing"] if one["severity"] == doctor.ERROR]
        self.assertEqual(len(missing), 1)
        self.assertIn(str(self.claude_skills / "alpha"), missing[0])
        self.assertFalse(any(str(copy) in one["detail"] for one in found["missing"]))
        v1_errors = [one["detail"] for one in found["v1"] if one["severity"] == doctor.ERROR]
        self.assertEqual(len(v1_errors), 1)
        self.assertIn(f"{copy}: a copy of the v1 skill self-reflection", v1_errors[0])
        self.assertIn("`render --migrate-v1` removes it after a backup", v1_errors[0])

    def test_a_clean_home_has_no_v1_item(self) -> None:
        self.rendered()
        code, findings = self.only("v1")
        self.assertEqual((code, [found["severity"] for found in findings]), (0, [doctor.OK]))


# --- The hash file -------------------------------------------------------------------

class HashFileCase(unittest.TestCase):
    def setUp(self) -> None:
        self.held = json.loads(migrate.KNOWN_FILE.read_bytes().decode("utf-8"))

    def test_the_file_is_what_setup_reads(self) -> None:
        table = migrate.load_known(migrate.KNOWN_FILE)
        self.assertEqual(self.held["schema_version"], migrate.KNOWN_SCHEMA)
        for source in (*migrate.PROCESS_RULES, migrate.BASH_RULE, migrate.BASH_RULE_NOW, migrate.V1_AGENT_SOURCE,
                       *[f"{skill}/SKILL.md" for skill in migrate.V1_SKILLS]):
            self.assertTrue(table.has(source), source)
            self.assertGreaterEqual(len(table.files[source]), 2)   # LF and CRLF
        for path, hashes in self.held["files"].items():
            self.assertFalse(os.path.isabs(path) or path.startswith(("/", "~")) or ":" in path, path)
            self.assertEqual(hashes, sorted(set(hashes)))
            self.assertTrue(all(len(one) == 64 and set(one) <= set("0123456789abcdef") for one in hashes))
        for name in ("v1", "built_from"):
            self.assertRegex(self.held[name], r"^[0-9a-f]{40}$")
        raw = migrate.KNOWN_FILE.read_bytes()
        self.assertNotIn(b"\r", raw)
        for word in (b"/home/", b"/mnt/", b"Users", b":\\"):
            self.assertNotIn(word, raw)

    def test_lf_and_crlf_are_both_known(self) -> None:
        text = b"one\ntwo\n"
        both = BUILDER.forms(text)
        self.assertEqual(both, BUILDER.forms(text.replace(b"\n", b"\r\n")))
        self.assertEqual(len(both), 2)
        self.assertEqual(len(BUILDER.forms(b"\0binary\n")), 1)

    def test_the_file_is_what_the_script_builds_from_the_history(self) -> None:
        if not BUILDER.has_history(support.REPOSITORY, self.held["v1"], self.held["built_from"]):
            self.skipTest("this working copy has no git history that reaches the commits the file names")
        again = BUILDER.build(support.REPOSITORY, self.held["v1"], self.held["built_from"])
        self.assertEqual(BUILDER.to_bytes(again), migrate.KNOWN_FILE.read_bytes())
        # A file as git has it at the tag is a known version, in both forms.
        blob = BUILDER.git(support.REPOSITORY, "cat-file", "blob", f"{self.held['v1']}:prd-implementation.md")
        table = migrate.load_known(migrate.KNOWN_FILE)
        for data in (blob, blob.replace(b"\n", b"\r\n")):
            self.assertTrue(table.matches(migrate.V1_RULES["prd-implementation.md"], fsio.sha256(data)))

    @unittest.skipUnless(POSIX, "the path form of a Windows drive in WSL")
    def test_the_script_refuses_a_clone_on_a_windows_drive(self) -> None:
        # Put together here, so that this file holds no path of a machine.
        mount = "/".join(["", "mnt"])
        for path in (f"{mount}/c/workspace/some-clone", f"{mount}/d"):
            with self.assertRaises(BUILDER.BuildError):
                BUILDER.refuse_windows_drive(Path(path))
            self.assertFalse(BUILDER.has_history(Path(path), "HEAD"))
            with self.assertRaises(BUILDER.BuildError):
                BUILDER.build(Path(path), "HEAD", "HEAD")


# --- fileops: setup's link where something of the user's was --------------------------

@unittest.skipUnless(LINKS, "needs links to directories")
class ReplacedCase(OpsCase):
    def setUp(self) -> None:
        super().setUp()
        self.target = self.clone / "skill"
        self.put(self.target / "SKILL.md", "the clone's\n")
        self.path = self.home / ".claude" / "skills" / "skill"
        self.key = "home:.claude/skills/skill"

    def users_link(self) -> Path:
        theirs = self.root / "theirs" / "skill"
        self.put(theirs / "SKILL.md", "theirs\n")
        self.path.parent.mkdir(parents=True)
        fsio.make_link(str(theirs), self.path, True)
        return theirs

    def users_directory(self) -> None:
        self.put(self.path / "SKILL.md", "a copy\n")
        self.put(self.path / "scripts" / "deep" / "tool.py", "print()\n", 0o750 if POSIX else None)

    def remove_copy(self, plan: fileops.Plan) -> None:
        plan.remove_file(self.path / "SKILL.md")
        plan.remove_file(self.path / "scripts" / "deep" / "tool.py")
        for directory in (self.path / "scripts" / "deep", self.path / "scripts", self.path):
            plan.remove_directory(directory, users=True)

    def test_a_users_link_then_setups_link_in_one_plan_and_back(self) -> None:
        theirs = self.users_link()
        before = self.snap()
        plan = self.plan()
        plan.remove_link(self.path)
        plan.create_link(self.path, self.target)
        result = plan.apply()
        self.assertEqual(result.lines[-1], f"replace link {self.key} -> clone:skill")
        self.assertTrue(fsio.same_target(fsio.look(self.path).target, str(self.target)))
        entry = self.record().entries[self.key]
        self.assertEqual((entry["kind"], entry["target"]), ("link", "clone:skill"))
        self.assertEqual((entry["replaced"]["kind"], entry["replaced"]["target"]), ("removed-link", f"raw:{theirs}"))
        self.assertEqual((theirs / "SKILL.md").read_text(encoding="utf-8"), "theirs\n")
        # Asked again, the link is up to date and still carries what it took the place of.
        again = self.plan()
        again.create_link(self.path, self.target)
        self.assertFalse(again.apply().changed)
        self.assertEqual(self.record().entries[self.key], entry)
        back = self.reversal().apply()
        self.assertEqual(back.lines[0], f"restore link {self.key} -> raw:{theirs}")
        self.assertEqual(back.kept, [])
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(self.snap(), before)

    def test_without_the_removal_the_users_link_is_still_a_conflict(self) -> None:
        self.users_link()
        plan = self.plan()
        plan.create_link(self.path, self.target)
        self.assertEqual(self.refused(plan).codes(), {fileops.CONFLICT})

    def test_a_users_directory_then_setups_link_in_one_plan_and_back(self) -> None:
        self.users_directory()
        before = self.snap()
        plan = self.plan()
        self.remove_copy(plan)
        plan.create_link(self.path, self.target)
        result = plan.apply()
        self.assertEqual(result.lines[-1], f"create link {self.key} -> clone:skill, in place of the directory there")
        self.assertEqual((self.path / "SKILL.md").read_text(encoding="utf-8"), "the clone's\n")
        entries = self.record().entries
        self.assertEqual(entries[self.key]["replaced"], {"kind": "removed-directory"})
        self.assertEqual(entries[self.key + "/scripts"], {"kind": "removed-directory"})
        self.assertEqual(entries[self.key + "/SKILL.md"]["kind"], "removed-file")
        back = self.reversal().apply()
        self.assertEqual(back.kept, [])
        self.assertIn(f"restore directory {self.key}, in place of the link there", back.lines)
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(self.snap(), before)
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), "the clone's\n")   # never followed

    def test_setups_link_removed_later_leaves_the_users_entry_for_the_way_back(self) -> None:
        self.users_directory()
        before = self.snap()
        plan = self.plan()
        self.remove_copy(plan)
        plan.create_link(self.path, self.target)
        plan.apply()
        later = self.plan()   # the skill left the clone: the stale sweep
        later.remove_link(self.path, expect_target=self.target)
        later.apply()
        self.assertEqual(self.record().entries[self.key], {"kind": "removed-directory"})
        self.assertEqual(fsio.look(self.path).kind, fsio.ABSENT)
        # And it can be linked again, by a later run.
        again = self.plan()
        again.create_link(self.path, self.target)
        again.apply()
        self.assertEqual(self.record().entries[self.key]["replaced"], {"kind": "removed-directory"})
        self.reversal().apply()
        self.assertTrue(fileops.remove_state(self.roots))
        self.assertEqual(self.snap(), before)

    def test_a_directory_that_still_holds_something_is_not_removed(self) -> None:
        self.users_directory()
        plan = self.plan()
        plan.remove_file(self.path / "SKILL.md")
        plan.remove_directory(self.path, users=True)
        error = self.refused(plan)
        self.assertEqual(error.codes(), {fileops.CONFLICT})
        self.assertIn("still holds something the plan does not remove", error.lines[0])

    def test_a_link_changed_since_is_kept_and_nothing_is_put_back_through_it(self) -> None:
        self.users_directory()
        plan = self.plan()
        self.remove_copy(plan)
        plan.create_link(self.path, self.target)
        plan.apply()
        elsewhere = self.root / "elsewhere"
        self.put(elsewhere / "keep.md", "the user's\n")
        fsio.remove_link(self.path)
        fsio.make_link(str(elsewhere), self.path, True)
        before = self.snap()
        back = self.reversal().apply()
        kept = dict(back.kept)
        self.assertIn(self.key, kept)
        self.assertIn(self.key + "/SKILL.md", kept)
        self.assertEqual(sorted(os.listdir(elsewhere)), ["keep.md"])   # nothing was written through the link
        self.assertFalse(fileops.remove_state(self.roots))
        self.assertEqual({name: what for name, what in self.snap().items() if "workflow-setup" not in name},
                         {name: what for name, what in before.items() if "workflow-setup" not in name})


if __name__ == "__main__":
    unittest.main()
