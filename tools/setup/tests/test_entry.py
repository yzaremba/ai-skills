"""Tests for the entry points ``render`` generates, and for the project level.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

Every home and every project is a scratch directory. The clone is the
fixture clone of ``test_definitions.DefinitionsCase``, where ``lead`` is the
role a session starts as and can be loaded, with one more loaded role:
``quick``, on a Claude Code model that takes no effort setting. ``worker``
can only be dispatched. ``RepositoryCase`` renders the repository's own
roles into a scratch home and a scratch project and holds whatever they say.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import support
from test_definitions import ALL_FILES, CLAUDE, CODEX, DefinitionsCase
from test_render import RenderCase, tree
from wfsetup import blocks, definitions, entry, fileops, fsio, homes, locations, render, roles, validate
from wfsetup.locations import Locations

SKILLS = {
    ".claude/skills/lead/SKILL.md", ".claude/skills/lead/agents/openai.yaml",
    ".claude/skills/quick/SKILL.md", ".claude/skills/quick/agents/openai.yaml",
    ".agents/skills/lead/SKILL.md", ".agents/skills/lead/agents/openai.yaml",
    ".agents/skills/quick/SKILL.md", ".agents/skills/quick/agents/openai.yaml",
}
PROFILE = ".codex/lead.config.toml"
ENTRY_FILES = SKILLS | {PROFILE}
HOME_FILES = ALL_FILES | ENTRY_FILES

# What the project's ignore block always holds, as the block lists it.
ALWAYS = sorted(fileops.IGNORE_ALWAYS)

DEFAULT_ON = "[roles]\nmanager_default = true\n"
OVERRIDE = '[roles.worker]\ntier = "frontier"\n'
SETTINGS = ".claude/settings.json"
CONFIG = ".codex/config.toml"
USER_JSON = b'{\r\n\t"permissions": {"allow": ["Bash(ls *)"]},\r\n\t"model": "opus"\r\n}'
USER_TOML = b'# Mine.\r\napproval_policy = "on-request"\r\n\r\n[features]\r\nfast = true\r\n'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def skill_parts(text: str) -> tuple[dict[str, str], str]:
    """The frontmatter of a generated ``SKILL.md``, read as source
    validation reads a skill's, and what follows it."""
    fields, faults = validate.parse_frontmatter(text)
    if fields is None or faults:
        raise ValueError(f"the frontmatter is not read: {faults}")
    return {key: field.value for key, field in fields.items()}, text.split("\n---\n", 1)[1]


class EntryCase(DefinitionsCase):
    PARTS = None  # every part

    def fill(self, clone: Path) -> None:
        super().fill(clone)
        self.source(clone, "quick", tier="fast", load="true")

    def setUp(self) -> None:
        super().setUp()
        self.project_arg = ("--project", str(self.project))

    def files(self, root: Path, *tops: str) -> dict[str, bytes]:
        """Every file below the directories ``tops`` of ``root``. A link
        is not entered, a junction neither: what it leads to is the clone's."""
        found: dict[str, bytes] = {}
        for top in tops:
            for directory, inner, names in os.walk(root / top):
                inner[:] = [name for name in inner if fsio.look(Path(directory) / name).kind != fsio.LINK]
                for name in names:
                    file = Path(directory) / name
                    found[file.relative_to(root).as_posix()] = file.read_bytes()
        return found

    def home_files(self, home: Path | None = None) -> dict[str, bytes]:
        home = home or self.home
        found = self.files(home, ".claude/skills", ".agents/skills", ".claude/agents", ".codex/agents")
        found.update({
            file.relative_to(home).as_posix(): file.read_bytes()
            for file in (home / ".codex").glob("*.config.toml")
        })
        return found

    def project_files(self, project: Path | None = None) -> dict[str, bytes]:
        project = project or self.project
        return {
            name: data for name, data in self.files(project, ".claude", ".codex").items()
        }

    def text(self, name: str, root: Path | None = None) -> str:
        return ((root or self.home) / name).read_bytes().decode("utf-8")

    PROJECT_STATE = ".agents/workflow-setup"
    PROJECT_RECORD = PROJECT_STATE + "/manifest.json"

    def project_entries(self) -> dict:
        return json.loads((self.project / self.PROJECT_RECORD).read_text(encoding="utf-8"))["entries"]

    def assertOnlyStateAndIgnoreFileAdded(self, before: dict, after: dict) -> None:
        """A project got the ignore file and setup's state directory, with
        the record in it, and nothing else."""
        added = set(after) - set(before)
        inside = self.PROJECT_STATE + "/"
        self.assertEqual({name for name in added if not name.startswith(inside)}, {".gitignore", self.PROJECT_STATE})
        self.assertIn(self.PROJECT_RECORD, added)
        self.assertTrue(all(name == self.PROJECT_RECORD or name.startswith(inside + "backups")
                            for name in added if name.startswith(inside)), sorted(added))

    def all_roots(self):
        where = Locations(home=self.home, project=self.project, clone=self.clone)
        return homes.resolve(where, self.host).roots()

    def ok(self, *argv: str) -> str:
        code, out, err = self.render(*argv)
        self.assertEqual((code, err), (0, ""), out)
        return out

    def with_project(self, *argv: str) -> str:
        return self.ok(*self.project_arg, *argv)

    def refused_by_validation(self, *argv: str) -> str:
        before = tree(self.root)
        for more in ((), ("--dry-run",)):
            code, out, err = self.render(*argv, *more)
            self.assertEqual((code, out), (2, ""))
            self.assertEqual(tree(self.root), before)
        return err

    def refused(self, *argv: str) -> str:
        before = tree(self.root)
        for more in ((), ("--dry-run",)):
            code, out, err = self.render(*argv, *more)
            self.assertEqual(code, 2, out)
            self.assertEqual(tree(self.root), before)
            self.assertIn("nothing was written", out.splitlines()[-1])
        return err


class LoadedRoleCase(EntryCase):
    def test_each_provider_gets_a_skill_for_each_loaded_role_and_no_other(self) -> None:
        out = self.ok()
        self.assertEqual(set(self.home_files()), HOME_FILES)
        self.assertIn("6 links created, 0 removed; 20 files written, 0 removed", out.splitlines()[-1])
        for place in (self.claude_skills, self.codex_skills):
            # A role that is only dispatched, or has no entry point, is no skill.
            self.assertEqual([name for name in sorted(os.listdir(place)) if name not in ("alpha", "beta", "solo")],
                             ["lead", "quick"])
            for name in ("worker", "reviewer", "runner", "silent", "worker-hard"):
                self.assertNothingAt(place / name)
            for role in ("lead", "quick"):
                # A directory of regular files, never a link.
                self.assertFalse(os.path.islink(place / role))
                self.assertTrue(os.path.isdir(place / role))
                self.assertEqual(sorted(os.listdir(place / role)), ["SKILL.md", "agents"])
                self.assertEqual(os.listdir(place / role / "agents"), ["openai.yaml"])
        for name, data in self.home_files().items():
            self.assertNotIn(b"\r", data, name)
            self.assertTrue(data.endswith(b"\n"), name)

    def test_the_frontmatter_makes_it_invoke_only_for_its_provider(self) -> None:
        self.ok()
        for directory, provider in ((".claude/skills", CLAUDE), (".agents/skills", CODEX)):
            raw = self.text(f"{directory}/lead/SKILL.md")
            fields, _ = skill_parts(raw)
            self.assertEqual(list(fields), ["name", "description", "compatibility", "disable-model-invocation"])
            self.assertEqual(fields["name"], "lead")
            self.assertEqual(fields["compatibility"], provider)
            self.assertEqual(fields["disable-model-invocation"], "true")
            self.assertTrue(fields["description"].startswith("Load the Lead role into this session. "))
            line = raw.split("\n")[3]
            self.assertRegex(line.removeprefix("compatibility: "), validate.COMPATIBILITY)
            # No model key: on Claude Code it would hold for one turn only.
            self.assertNotIn("model", fields)
            self.assertNotIn("effort", fields)
            yaml = self.text(f"{directory}/lead/agents/openai.yaml")
            self.assertEqual(validate.read_implicit_invocation(yaml), (False, []))
            self.assertIn("policy:\n  allow_implicit_invocation: false\n", yaml)
            self.assertTrue(yaml.startswith("# Generated by workflow setup for the loaded role lead. Do not edit"))

    def test_a_generated_skill_passes_the_rules_for_a_skill_of_the_clone(self) -> None:
        """What source validation asks of a skill holds for a generated one."""
        self.ok()
        scratch = self.root / "as-a-clone"
        shutil.copytree(self.clone, scratch, ignore=shutil.ignore_patterns("alpha", "beta", "solo", "multiagent-collab"))
        for role in ("lead", "quick"):
            shutil.copytree(self.codex_skills / role, scratch / role)
        report = validate.check(Locations(home=self.home, clone=scratch))
        mine = [problem.text() for problem in report.problems if problem.file.startswith(("lead/", "quick/"))
                and problem.rule.startswith("skill-")]
        self.assertEqual(mine, [])
        self.assertTrue(report.skills["lead"].invoke_only)
        self.assertEqual(report.skills["lead"].providers, (CODEX,))

    def test_the_body_is_the_notice_the_loaded_section_and_the_definitions_text(self) -> None:
        self.ok()
        role = ["# Lead\n\nYou are the lead. Do the work.", "## Gates\n\nHold the gate."]
        rows = definitions.bindings(self.where())["lead"]
        for directory, provider, model, way in (
            (".claude/skills", CLAUDE, "sonnet", "`/model sonnet` and `/effort medium` switch the session to it"),
            (".agents/skills", CODEX, "gpt-6.1-sol",
             "`/model`, choosing that model and that reasoning effort, switches the session to it"),
        ):
            _, body = skill_parts(self.text(f"{directory}/lead/SKILL.md"))
            notice = definitions.notice_lines(provider, "lead", "lead")
            notice[0] = ("Generated by workflow setup: the role lead as a skill the user loads into a session. "
                         "Do not edit this file.")
            loaded = body.split("-->\n\n", 1)[1].split("\n\n# Lead\n", 1)[0]
            self.assertEqual(body, "\n" + roles.join_text([
                "<!--\n" + "\n".join(notice) + "\n-->", loaded, *role, definitions.bindings_section(rows),
                f"## How actions are done on {provider}\n\n- Dispatch a role.",
            ]))
            comment = body[body.index("<!--") + 4:body.index("-->")]
            self.assertNotIn("--", comment)
            self.assertIn(f"providers/{provider}/actions.md", comment)
            # The loaded section: the role, the one-active-role rule, the profile.
            paragraphs = loaded.split("\n\n")
            self.assertEqual(len(paragraphs), 3)
            self.assertTrue(paragraphs[0].startswith("**Loaded role.** The user loaded the Lead role into this session."))
            self.assertEqual(paragraphs[1], entry.ONE_ROLE)
            self.assertTrue(paragraphs[2].startswith(
                f"**Profile.** This role is meant to run on the model `{model}` with the effort `medium`. "
                "Loading it did not switch the session"
            ))
            self.assertIn(way, paragraphs[2])
        # The role's text is the definition's, byte for byte.
        definition = self.text(".claude/agents/lead.md").split("-->\n\n", 1)[1]
        skill = self.text(".claude/skills/lead/SKILL.md")
        self.assertTrue(skill.endswith(definition))
        self.assertIn("Reads the stage and writes nothing.", skill)

    def test_the_one_active_role_rule_is_not_said_twice(self) -> None:
        said = "# Lead\n\nYou are the lead.\n\nLoading this role suspends any other role loaded in this session. One role is active at a time.\n"
        (self.clone / "roles/lead/ROLE.md").write_bytes(said.encode("utf-8"))
        self.ok()
        for directory in (".claude/skills", ".agents/skills"):
            text = self.text(f"{directory}/lead/SKILL.md")
            self.assertEqual(text.count("suspends any other role"), 1)
            self.assertEqual(text.count("**Profile.**"), 1)
            # The role without the sentence gets it.
            self.assertEqual(self.text(f"{directory}/quick/SKILL.md").count(entry.ONE_ROLE), 1)

    def test_the_profile_of_a_model_with_no_effort_setting(self) -> None:
        self.ok()
        text = self.text(".claude/skills/quick/SKILL.md")
        self.assertIn("meant to run on the model `haiku` with no effort setting.", text)
        self.assertIn("tell the user that `/model haiku` switches the session to it.", text)
        self.assertNotIn("/effort", text)
        # The Codex model of the same tier takes one.
        self.assertIn("the model `gpt-6-luna` with the effort `medium`", self.text(".agents/skills/quick/SKILL.md"))

    def test_the_profile_is_the_user_levels_also_with_a_project(self) -> None:
        self.write(self.user_file, '[roles.lead]\ntier = "deep"\neffort = "high"\n')
        self.write(self.project_file, '[roles.lead]\ntier = "frontier"\n')
        self.with_project()
        self.assertIn("the model `opus` with the effort `high`", self.text(".claude/skills/lead/SKILL.md"))
        self.assertEqual(tomllib.loads(self.text(PROFILE))["model"], "gpt-6.1-sol")

    def test_a_role_named_like_a_skill_of_the_clone_is_refused(self) -> None:
        self.source(self.clone, "alpha", load="true")
        # Source validation says it first (review finding S11): render does
        # not get as far as a plan, so it prints no report.
        err = self.refused_by_validation()
        self.assertIn(
            "roles/alpha/role.toml: [role-skill-name] entry.load: the role alpha is loaded as the skill alpha, and "
            "the clone has a skill of that name (alpha/SKILL.md); rename one of the two, or set load = false", err,
        )
        self.assertNothingAt(self.manifest_file)
        self.assertNothingAt(self.claude_skills)
        # Not loaded, it is a role like any other.
        self.source(self.clone, "alpha", load="false")
        self.ok()
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")

    def test_a_role_named_like_the_collaboration_skill_is_refused(self) -> None:
        shutil.rmtree(self.clone / "multiagent-collab")
        self.source(self.clone, "multiagent-collab", load="true", dispatch="false")
        err = self.refused_by_validation()
        self.assertIn("the skill multiagent-collab, and a skill of that name has a setup of its own", err)

    def test_the_part_itself_still_refuses_such_a_role(self) -> None:
        # What validation reports first is still refused where the plan is
        # made: ``execute`` is also called with sources checked elsewhere.
        self.source(self.clone, "alpha", load="true")
        where = Locations(home=self.home, project=None, clone=self.clone)
        with mock.patch.object(validate, "_check_ids", lambda run: None):
            sources = validate.require(where)
        outcome = render.execute(homes.resolve(where, self.host), sources, None)
        self.assertEqual(outcome.code, 2)
        self.assertIn("the role would be installed as the skill alpha", outcome.errors[0])
        self.assertNothingAt(self.manifest_file)

    def test_the_report_lists_the_entry_points_with_their_sizes(self) -> None:
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        points = {(point["provider"], point["kind"], point["role"]): point for point in report["entry_points"]}
        self.assertEqual(set(points), {
            (CLAUDE, "load", "lead"), (CLAUDE, "load", "quick"), (CLAUDE, "start", "lead"),
            (CODEX, "load", "lead"), (CODEX, "load", "quick"), (CODEX, "start", "lead"),
        })
        self.assertEqual(points[(CLAUDE, "load", "lead")]["how"], "/lead")
        self.assertEqual(points[(CODEX, "load", "quick")]["how"], "$quick")
        self.assertEqual(points[(CLAUDE, "start", "lead")]["how"], "claude --agent lead")
        self.assertEqual(points[(CLAUDE, "start", "lead")]["file"], "lead.md")
        self.assertEqual(points[(CODEX, "start", "lead")]["how"], "codex --profile lead")
        size = len((self.claude_skills / "lead" / "SKILL.md").read_bytes())
        loaded = points[(CLAUDE, "load", "lead")]
        self.assertEqual((loaded["bytes"], loaded["tokens"], loaded["over_limit"]), (size, -(-size // 3), False))
        self.assertEqual((loaded["model"], loaded["effort"]), ("sonnet", "medium"))
        self.assertEqual(points[(CLAUDE, "load", "quick")]["effort"], None)
        self.assertIsNone(report["project"])
        self.assertEqual(len(report["definitions"]), 11)
        self.assertEqual(self.items(report, CODEX, "profiles"), {"lead.config.toml": render.CREATE})
        self.assertEqual(self.items(report, CLAUDE, "skills")["lead/SKILL.md"], render.CREATE)

        out = self.ok()
        lines = out.splitlines()
        self.assertIn("entry points:", lines)
        self.assertIn(
            f"  claude-code: load lead into a session: /lead (lead/SKILL.md; {size:,} bytes; about "
            f"{-(-size // 3):,} tokens; model sonnet, effort medium)", lines,
        )
        self.assertIn("  claude-code: start a session as lead: claude --agent lead (lead.md)", lines)
        size = len((self.home / PROFILE).read_bytes())
        self.assertIn(
            f"  codex: start a session as lead: codex --profile lead (lead.config.toml; {size:,} bytes; "
            "model gpt-6.1-sol, effort medium)", lines,
        )
        self.assertIn(f"    lead.config.toml: up to date: as generated ({size:,} bytes; model gpt-6.1-sol, effort medium)", lines)

    def test_a_loaded_role_likely_over_the_compaction_limit_is_flagged_and_written(self) -> None:
        long = "# Lead\n\n" + "\n".join(f"- Rule {number}: do the work as the brief says." for number in range(400)) + "\n"
        (self.clone / "roles/lead/ROLE.md").write_bytes(long.encode("utf-8"))
        with mock.patch.object(roles, "TEXT_LIMIT", 100_000):
            code, report, err = self.report()
            self.assertEqual((code, err), (0, ""))
            out = self.ok()
        points = {(point["provider"], point["kind"], point["role"]): point for point in report["entry_points"]}
        self.assertGreater(points[(CLAUDE, "load", "lead")]["tokens"], entry.COMPACTION_TOKENS)
        self.assertTrue(points[(CLAUDE, "load", "lead")]["over_limit"])
        self.assertFalse(points[(CLAUDE, "load", "quick")]["over_limit"])
        # The figure is Claude Code's; no such limit is known for Codex.
        self.assertFalse(points[(CODEX, "load", "lead")]["over_limit"])
        flagged = [line for line in out.splitlines() if "LONG" in line]
        self.assertEqual(len(flagged), 1)
        self.assertIn("claude-code: load lead into a session", flagged[0])
        self.assertIn("keeps the first 5,000 tokens of an invoked skill", flagged[0])
        self.assertIn(b"Rule 399", (self.claude_skills / "lead" / "SKILL.md").read_bytes())

    def test_help_states_the_entry_points_the_project_and_the_limit(self) -> None:
        code, out, _ = support.run("render", "--help")
        flat = " ".join(out.split())
        self.assertEqual(code, 0)
        for text in (
            "claude --agent <role>", "codex --profile <role>", "<role>.config.toml",
            "disable-model-invocation: true", "policy.allow_implicit_invocation: false",
            '"keeping the first 5,000 tokens of each"', "combined budget of 25,000 tokens", "marked LONG",
            "Without it nothing is written in any project",
            "the homes are installed and refreshed exactly as without it",
            "no other generated file, in the home or the project, changes",
            "Codex reads a project's config only when the project is trusted, and there it wins over a profile",
            "the user's value stays in effect", "Agent and Workflow",
        ):
            self.assertIn(text, flat)


class ProfileCase(EntryCase):
    def test_the_codex_profile_holds_the_three_keys_and_the_notice(self) -> None:
        self.ok()
        raw = self.text(PROFILE)
        data = tomllib.loads(raw)
        self.assertEqual(list(data), ["model", "model_reasoning_effort", "developer_instructions"])
        self.assertEqual((data["model"], data["model_reasoning_effort"]), ("gpt-6.1-sol", "medium"))
        self.assertEqual(data["developer_instructions"], roles.join_text([
            definitions.notice_inline("lead"),
            "# Lead\n\nYou are the lead. Do the work.", "## Gates\n\nHold the gate.",
            definitions.bindings_section(definitions.bindings(self.where())["lead"]),
            "## How actions are done on codex\n\n- Dispatch a role.",
        ]))
        head = raw.split("\n\n", 1)[0].split("\n")
        self.assertTrue(all(line.startswith("# ") for line in head))
        self.assertEqual(head[0], "# Generated by workflow setup: the profile that starts a Codex session as the "
                                  "role lead. Do not edit this file.")
        self.assertIn("Start with `codex --profile lead`.", head[1])
        self.assertIn("read only in a trusted project: a key set there wins over the same key here", head[1])
        self.assertIn("providers/codex/actions.md", head[2])
        # A regular file in the Codex home, and the user's configuration is not made.
        self.assertFalse(os.path.islink(self.home / PROFILE))
        self.assertNothingAt(self.codex / "config.toml")
        # Claude Code starts as the role through its agent file: nothing more.
        self.assertEqual(sorted(os.listdir(self.claude)), ["agents", "rules", "skills"])
        self.assertTrue((self.claude / "agents" / "lead.md").is_file())

    def test_the_users_codex_configuration_is_not_touched(self) -> None:
        mine = self.keep(self.codex / "config.toml", 'model = "mine"\n\n[profiles.lead]\nmodel = "old"\n')
        self.ok()
        self.assertEqual(mine.read_text(encoding="utf-8"), 'model = "mine"\n\n[profiles.lead]\nmodel = "old"\n')
        self.assertNotIn("home:.codex/config.toml", self.entries())

    def test_no_effort_is_written_for_a_model_that_takes_none(self) -> None:
        file = self.clone / "providers/codex/dictionary.toml"
        file.write_bytes(file.read_bytes() + b'\n[models.gpt-plain]\nefforts = []\nvisibility = "list"\n')
        self.write(self.user_file, '[providers.codex.role_models]\nlead = "gpt-plain"\n')
        self.ok()
        self.assertEqual(list(tomllib.loads(self.text(PROFILE))), ["model", "developer_instructions"])
        self.assertEqual(tomllib.loads(self.text(PROFILE))["model"], "gpt-plain")
        self.assertIn("the model `gpt-plain` with no effort setting", self.text(".agents/skills/lead/SKILL.md"))
        self.assertNotIn("reasoning effort", self.text(".agents/skills/lead/SKILL.md"))

    def test_each_starting_role_gets_a_profile_when_no_project_default_is_asked(self) -> None:
        self.source(self.clone, "runner", commands="false", dispatches='["worker"]', start="true")
        self.ok()
        self.assertEqual(sorted(file.name for file in self.codex.glob("*.config.toml")),
                         ["lead.config.toml", "runner.config.toml"])

    def test_a_provider_that_is_not_installed_gets_no_entry_point(self) -> None:
        shutil.rmtree(self.clone / "providers" / "codex")
        self.codex.rmdir()
        self.ok()
        self.assertEqual(set(self.home_files()), {name for name in HOME_FILES if name.startswith(".claude/")})
        self.assertNothingAt(self.codex)
        self.assertNothingAt(self.codex_skills)


class StableCase(EntryCase):
    def test_a_second_run_writes_nothing(self) -> None:
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        self.with_project()
        before = tree(self.root)
        code, report, err = self.report(*self.project_arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.root), before)
        self.assertEqual((report["plan"], report["changed"]), ([], False))
        self.assertEqual(report["counts"]["file_up_to_date"], 22)
        self.assertEqual({item["status"] for item in report["project"]["items"]}, {render.UP_TO_DATE})
        out = self.with_project()
        self.assertTrue(out.splitlines()[-1].startswith(f"{fileops.UP_TO_DATE}; nothing was written"))
        self.assertEqual(tree(self.root), before)

    def test_a_dry_run_writes_nothing_and_says_what_it_would(self) -> None:
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        before = tree(self.root)
        out = self.with_project("--dry-run")
        self.assertEqual(tree(self.root), before)
        lines = out.splitlines()
        self.assertIn("  create file home:.claude/skills/lead/SKILL.md", lines)
        self.assertIn("  create file home:.codex/lead.config.toml", lines)
        self.assertIn("  create file project:.claude/agents/worker.md", lines)
        self.assertIn("      key agent: set", lines)
        self.assertIn("      block starting-role: add", lines)
        self.assertEqual(
            lines[-1],
            "dry run: would create 6 links and remove 0, write 22 files and remove 0, set 2 project defaults and "
            "remove 0; nothing was written; 2 skipped (each is listed as skipped, with the reason)",
        )

    def test_two_clone_paths_give_the_same_bytes(self) -> None:
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        self.with_project()
        other_clone = self.root / "elsewhere" / "a longer name" / "clone-two"
        shutil.copytree(self.clone, other_clone)
        other_home, other_project = self.root / "second-home", self.root / "second-project"
        (other_home / ".claude").mkdir(parents=True)
        (other_home / ".codex").mkdir()
        self.write(other_project / ".agents" / "workflow.toml", DEFAULT_ON + OVERRIDE)
        with mock.patch.object(locations, "CLONE", other_clone), \
                mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, _, err = support.run("render", "--home", str(other_home), "--project", str(other_project))
        self.assertEqual((code, err), (0, ""))
        first, second = self.home_files(), self.home_files(other_home)
        self.assertEqual(set(first), HOME_FILES)
        self.assertEqual(first, second)
        mine, theirs = self.project_files(), self.project_files(other_project)
        self.assertEqual(set(mine), {SETTINGS, CONFIG, ".claude/agents/worker.md", ".codex/agents/worker.toml"})
        self.assertEqual(mine, theirs)
        machine = (str(self.root), self.root.as_posix(), self.root.name, "clone-two", "fake-clone", "second-project")
        for name, data in {**first, **mine}.items():
            for text in machine:
                self.assertNotIn(text.encode("utf-8"), data, name)
        # The records' digests are the same too.
        theirs_home = json.loads((other_home / ".agents/workflow-setup/manifest.json").read_text(encoding="utf-8"))
        for name in ENTRY_FILES:
            self.assertEqual(self.entries()[f"home:{name}"], theirs_home["entries"][f"home:{name}"])
        theirs_project = json.loads((other_project / self.PROJECT_RECORD).read_text(encoding="utf-8"))
        self.assertEqual(self.project_entries(), theirs_project["entries"])

    def test_a_crlf_checkout_gives_the_same_bytes(self) -> None:
        self.ok()
        before, digests = self.home_files(), entry.digests(self.where())
        for file in (self.clone / "roles/lead/ROLE.md", self.clone / "roles/_shared/gates.md",
                     self.clone / "providers/codex/actions.md", self.clone / "roles/lead/role.toml"):
            file.write_bytes(b"\xef\xbb\xbf" + file.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(entry.digests(self.where()), digests)
        code, report, _ = self.report()
        self.assertEqual((code, report["plan"]), (0, []))
        self.assertEqual(self.home_files(), before)

    def test_reversing_the_project_and_then_the_home_restores_both_trees(self) -> None:
        self.keep(self.claude / "CLAUDE.md")
        self.keep(self.codex / "config.toml", 'model = "x"\n')
        self.keep(self.claude_skills / "mine" / "SKILL.md")
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        (self.project / ".claude").mkdir()
        (self.project / SETTINGS).write_bytes(USER_JSON)
        (self.project / ".codex").mkdir()
        (self.project / CONFIG).write_bytes(USER_TOML)
        (self.project / ".gitignore").write_bytes(b"node_modules/\n")
        home_before, project_before, clone_before = tree(self.home), tree(self.project), tree(self.clone)
        self.with_project()
        self.assertNotEqual(tree(self.home), home_before)
        self.assertNotEqual(tree(self.project), project_before)
        roots = self.all_roots()
        result = fileops.plan_reversal(roots, project=True).apply()
        self.assertEqual(result.kept, [])
        self.assertTrue(fileops.remove_state(roots, project=True))
        self.assertEqual(tree(self.project), project_before)
        result = fileops.plan_reversal(roots).apply()
        self.assertEqual(result.kept, [])
        self.assertTrue(fileops.remove_state(roots))
        self.assertEqual(tree(self.home), home_before)
        self.assertEqual(tree(self.clone), clone_before)


class DigestCase(EntryCase):
    def test_the_recorded_inputs_are_recomputed_without_writing(self) -> None:
        self.write(self.user_file, '[roles.lead]\ntier = "deep"\n')
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        self.with_project()
        home, project = self.entries(), self.project_entries()
        before = tree(self.root)
        where = self.where(project=True)
        found = entry.digests(definitions.user_level(where))
        changed = entry.project_digests(where)
        self.assertEqual(tree(self.root), before)
        places = {(CLAUDE, entry.LOADED): ".claude/skills", (CODEX, entry.LOADED): ".agents/skills",
                  (CODEX, entry.PROFILE): ".codex"}
        self.assertEqual({f"{places[(provider, kind)]}/{name}" for provider, kind, name in found}, ENTRY_FILES)
        for (provider, kind, name), inputs in found.items():
            record = home[f"home:{places[(provider, kind)]}/{name}"]
            self.assertEqual((record["kind"], record["inputs"]), ("file", inputs))
            self.assertEqual(record["sha256"], digest((self.home / places[(provider, kind)] / name).read_bytes()))
            scheme = entry.PROFILE_SCHEME if kind == entry.PROFILE else entry.LOADED_SCHEME
            self.assertRegex(inputs, rf"^{scheme}:[0-9a-f]{{64}}$")
            self.assertTrue(inputs.startswith(render.GENERATED_PREFIX))
        self.assertEqual((entry.LOADED_SCHEME, entry.PROFILE_SCHEME), ("render:loaded-role:2", "render:codex-profile:1"))
        self.assertEqual(len(set(found.values())), len(found))
        self.assertEqual(set(changed), {(CLAUDE, "worker.md"), (CODEX, "worker.toml")})
        for (provider, name), inputs in changed.items():
            record = project[f"project:{entry.PROJECT_AGENTS[provider]}/{name}"]
            self.assertEqual((record["kind"], record["inputs"]), ("file", inputs))
            self.assertTrue(inputs.startswith(definitions.INPUTS_SCHEME + ":"))
        # What the block and the key should be is recomputed the same way.
        role, content = entry.project_block(where)
        self.assertEqual(role, "lead")
        block = blocks.render(blocks.TOML, entry.BLOCK_NAME, content)
        self.assertEqual(project[f"project:{CONFIG}"]["blocks"][entry.BLOCK_NAME]["sha256"], digest(block))
        self.assertEqual(project[f"project:{SETTINGS}"]["keys"][entry.AGENT_KEY]["value"], entry.starting_role(where))
        self.assertTrue(entry.manager_default(where))
        self.assertFalse(entry.manager_default(definitions.user_level(where)))

    def test_a_changed_source_shows_as_drift_in_its_dependents_only(self) -> None:
        self.ok()
        recorded = entry.digests(self.where())
        (self.clone / "roles/lead/ROLE.md").write_bytes(b"# Lead\n\nYou are the lead. Do other work.\n")
        now = entry.digests(self.where())
        self.assertEqual({key for key in now if now[key] != recorded[key]}, {
            (CLAUDE, entry.LOADED, "lead/SKILL.md"), (CODEX, entry.LOADED, "lead/SKILL.md"),
            (CODEX, entry.PROFILE, "lead.config.toml"),
        })
        self.write(self.user_file, '[roles.quick]\neffort = "high"\n')
        later = entry.digests(self.where())
        # The Claude Code model of that tier takes no effort: its skill is the same.
        self.assertEqual({key for key in later if later[key] != now[key]}, {(CODEX, entry.LOADED, "quick/SKILL.md")})

    def test_a_changed_role_text_rewrites_the_skill_and_leaves_its_yaml(self) -> None:
        self.ok()
        before = self.home_files()
        file = self.clone / "roles/quick/ROLE.md"
        file.write_bytes(file.read_bytes() + b"\nOne more line.\n")
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        after = self.home_files()
        self.assertEqual({name for name in after if after[name] != before[name]}, {
            ".claude/skills/quick/SKILL.md", ".agents/skills/quick/SKILL.md",
            ".claude/agents/quick.md", ".codex/agents/quick.toml",
        })
        self.assertEqual(len(report["plan"]), 4)


class NoRolesCase(EntryCase):
    def test_no_roles_generates_no_entry_point(self) -> None:
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        project_before = tree(self.project)
        out = self.with_project("--no-roles")
        self.assertEqual(self.home_files(), {})
        self.assertEqual(tree(self.project), project_before)
        self.assertNothingAt(self.codex / "lead.config.toml")
        self.assertNothingAt(self.claude_skills / "lead")
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertNotIn("entry points:", out.splitlines())
        self.assertIn("done: 6 links created, 0 removed", out.splitlines()[-1])
        self.assertNotIn("files", out.splitlines()[-1])

    def test_no_roles_removes_what_an_earlier_run_generated(self) -> None:
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        project_before = tree(self.project)
        self.with_project()
        code, report, err = self.report(*self.project_arg, "--no-roles")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.home_files(), {})
        # The skill directories went with their files; the links stay.
        self.assertEqual(sorted(os.listdir(self.claude_skills)), ["alpha", "beta", "solo"])
        self.assertEqual(sorted(os.listdir(self.codex_skills)), ["alpha", "beta"])
        self.assertLinked(self.rules / "sample", self.clone / "rules" / "sample")
        self.assertEqual(report["counts"]["file_remove"], 22)
        self.assertEqual(report["counts"]["default_remove"], 2)
        self.assertIn("0 files written, 22 removed; 0 project defaults set, 2 removed", report["summary"])
        self.assertEqual({item["status"] for item in report["stale"]}, {render.REMOVE})
        # The project holds its settings, the record and the ignore block, and nothing else.
        after = tree(self.project)
        self.assertOnlyStateAndIgnoreFileAdded(project_before, after)
        self.assertEqual((self.project / ".gitignore").read_bytes(),
                         ("# workflow-setup:start\n" + "".join(f"{entry}\n" for entry in ALWAYS)
                          + "# workflow-setup:end\n").encode("utf-8"))
        before = tree(self.root)
        code, report, _ = self.report(*self.project_arg, "--no-roles")
        self.assertEqual((code, report["plan"], report["stale"]), (0, [], []))
        self.assertEqual(tree(self.root), before)
        # Without the option everything is generated again.
        self.with_project()
        self.assertEqual(set(self.home_files()), HOME_FILES)
        self.assertEqual(json.loads(self.text(SETTINGS, self.project)), {"agent": "lead"})

    def test_no_roles_keeps_what_was_edited(self) -> None:
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        self.with_project()
        edited = {}
        for root, name in ((self.home, ".claude/skills/lead/SKILL.md"), (self.home, PROFILE),
                           (self.home, ".agents/skills/quick/agents/openai.yaml"),
                           (self.project, ".codex/agents/worker.toml"), (self.project, CONFIG)):
            file = root / name
            file.write_bytes(file.read_bytes().replace(b"Generated by workflow setup", b"Changed by me"))
            edited[file] = file.read_bytes()
        (self.project / SETTINGS).write_bytes(b'{\n  "agent": "other"\n}\n')
        code, report, err = self.report(*self.project_arg, "--no-roles")
        self.assertEqual((code, err), (0, ""))
        for file, data in edited.items():
            self.assertEqual(file.read_bytes(), data, file)
        self.assertEqual((self.project / SETTINGS).read_bytes(), b'{\n  "agent": "other"\n}\n')
        kept = sorted(item["key"] for item in report["stale"] if item["status"] == render.KEPT)
        self.assertEqual(kept, sorted([
            "home:.claude/skills/lead/SKILL.md", "home:.codex/lead.config.toml",
            "home:.agents/skills/quick/agents/openai.yaml", "project:.codex/agents/worker.toml",
            f"project:{CONFIG}", f"project:{SETTINGS}",
        ]))
        # A directory that still holds a kept file stays; the others went.
        self.assertTrue((self.claude_skills / "lead").is_dir())
        self.assertNothingAt(self.claude_skills / "lead" / "agents")
        self.assertNothingAt(self.claude_skills / "quick")
        self.assertIn("6 kept", report["summary"])


class EditedCase(EntryCase):
    def setUp(self) -> None:
        super().setUp()
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        self.with_project()

    def edit(self, file: Path, old: bytes, new: bytes) -> tuple[bytes, bytes]:
        original = file.read_bytes()
        self.assertIn(old, original)
        file.write_bytes(original.replace(old, new, 1))
        return original, file.read_bytes()

    def kept(self, file: Path, original: bytes, edited: bytes, name: str, says: str) -> None:
        """Kept and reported with exit code 3; replaced on request."""
        before = tree(self.root)
        for argv in (("--dry-run",), ()):
            code, out, err = self.render(*self.project_arg, *argv)
            self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""), out)
            self.assertEqual(tree(self.root), before)
            self.assertIn(f"{name}: kept: {says}", " ".join(out.split()))
            self.assertIn("1 edited by hand and kept, which --overwrite-edited would replace", out.splitlines()[-1])
        code, report, _ = self.report(*self.project_arg)
        self.assertEqual((code, report["counts"]["edited"], report["errors"]), (3, 1, []))
        code, _, err = self.render(*self.project_arg, "--overwrite-edited")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(file.read_bytes(), original)
        record = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        self.assertIn(digest(edited), [backup.get("sha256") for backup in record["backups"]]
                      + [backup.get("sha256") for backup in json.loads(
                          (self.project / self.PROJECT_RECORD).read_text(encoding="utf-8"))["backups"]])
        self.assertEqual(self.render(*self.project_arg)[0], 0)

    FILE_SAYS = "edited by hand since setup wrote it, and kept; --overwrite-edited backs it up and replaces it"

    def test_a_loaded_roles_skill(self) -> None:
        file = self.claude_skills / "lead" / "SKILL.md"
        self.kept(file, *self.edit(file, b"You are the lead.", b"You are mine."), "lead/SKILL.md", self.FILE_SAYS)

    def test_a_loaded_roles_yaml(self) -> None:
        file = self.codex_skills / "quick" / "agents" / "openai.yaml"
        self.kept(file, *self.edit(file, b"allow_implicit_invocation: false", b"allow_implicit_invocation: true"),
                  "quick/agents/openai.yaml", self.FILE_SAYS)

    def test_the_codex_profile(self) -> None:
        file = self.home / PROFILE
        self.kept(file, *self.edit(file, b'model = "gpt-6.1-sol"', b'model = "my-own"'), "lead.config.toml", self.FILE_SAYS)

    def test_a_projects_definition(self) -> None:
        file = self.project / ".claude/agents/worker.md"
        self.kept(file, *self.edit(file, b"model: fable", b"model: opus"), ".claude/agents/worker.md", self.FILE_SAYS)

    def test_the_projects_block(self) -> None:
        file = self.project / CONFIG
        self.kept(file, *self.edit(file, b'model = "gpt-6.1-sol"', b'model = "my-own"'),
                  f"{CONFIG}: block starting-role",
                  "edited by hand since setup wrote it, and kept; --overwrite-edited backs the file up and writes "
                  "the block again")

    def test_the_projects_key(self) -> None:
        file = self.project / SETTINGS
        self.kept(file, *self.edit(file, b'"lead"', b'"other"'), f"{SETTINGS}: key agent",
                  'changed by hand since setup set it (it is "other", setup set "lead"), and kept; '
                  "--overwrite-edited sets it again")

    def test_the_rest_of_the_run_is_done_beside_a_kept_file(self) -> None:
        mine = self.home / PROFILE
        _, edited = self.edit(mine, b'model = "gpt-6.1-sol"', b'model = "my-own"')
        file = self.clone / "roles/lead/ROLE.md"
        file.write_bytes(file.read_bytes() + b"\nOne more line.\n")
        code, _, err = self.render(*self.project_arg)
        self.assertEqual((code, err), (3, ""))
        self.assertEqual(mine.read_bytes(), edited)
        self.assertIn(b"One more line.", (self.claude_skills / "lead" / "SKILL.md").read_bytes())
        self.assertIn(b"One more line.", (self.project / CONFIG).read_bytes())

    def test_a_removed_file_key_and_block_are_written_again(self) -> None:
        skill = (self.codex_skills / "lead" / "SKILL.md").read_bytes()
        shutil.rmtree(self.codex_skills / "lead")
        (self.project / SETTINGS).write_bytes(b"{}\n")
        (self.project / CONFIG).write_bytes(b"")
        self.with_project()
        self.assertEqual((self.codex_skills / "lead" / "SKILL.md").read_bytes(), skill)
        self.assertEqual(json.loads(self.text(SETTINGS, self.project)), {"agent": "lead"})
        self.assertEqual(tomllib.loads(self.text(CONFIG, self.project))["model"], "gpt-6.1-sol")

    def test_a_users_own_skill_of_a_roles_name_is_a_conflict(self) -> None:
        self.ok("--no-roles")
        self.keep(self.claude_skills / "lead" / "SKILL.md")
        before = tree(self.root)
        code, out, err = self.render()
        self.assertEqual(code, 2)
        self.assertIn(f"{self.claude_skills / 'lead' / 'SKILL.md'}: a file is there, and setup did not write it", err)
        self.assertEqual(tree(self.root), before)


class ProjectDefinitionsCase(EntryCase):
    def same_home(self, before: dict, record: dict) -> None:
        """Nothing in the home changed, setup's own state included: the
        backups of the project's files that a run replaced are in the project."""
        now = tree(self.home)
        moved = {name for name in {*now, *before} if now.get(name) != before.get(name)}
        self.assertEqual(moved, set())
        self.assertEqual(self.entries(), record)

    def test_a_run_without_a_project_writes_nothing_in_the_project(self) -> None:
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        before = tree(self.project)
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(tree(self.project), before)
        self.assertIsNone(report["project"])
        self.assertEqual(self.text(".claude/agents/worker.md").split("\n")[3], "model: sonnet")

    def test_a_project_that_changes_nothing_gets_nothing(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "documents"\n')
        before = tree(self.project)
        code, report, err = self.report(*self.project_arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.project), before)
        self.assertEqual(set(self.home_files()), HOME_FILES)
        self.assertEqual(report["project"], {
            "path": str(self.project), "manager_default": False, "starting_role": None, "items": [],
            "loaded_roles": [],
        })
        out = self.with_project()
        self.assertIn(f"project: {self.project}", out.splitlines())
        self.assertIn("  roles.manager_default: false; no starting role is set for the project", out.splitlines())
        self.assertIn("  nothing is generated for it: its settings change no role definition", out.splitlines())

    def test_a_project_override_of_one_roles_tier_changes_that_roles_project_files_only(self) -> None:
        """R8.3: every other generated file, home and project, keeps its hash."""
        self.write(self.project_file, DEFAULT_ON)
        self.with_project()
        home_tree, home_record = tree(self.home), self.entries()
        project_record = self.project_entries()
        project_files = self.project_files()
        self.assertEqual(set(project_files), {SETTINGS, CONFIG})

        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        code, report, err = self.report(*self.project_arg)
        self.assertEqual((code, err), (0, ""))
        # The home: not a byte, setup's own state included (the backup of the
        # project's ignore file is in the project); and no entry of the record.
        self.same_home(home_tree, home_record)
        self.assertEqual({key: entry_["sha256"] for key, entry_ in self.entries().items() if "sha256" in entry_},
                         {key: entry_["sha256"] for key, entry_ in home_record.items() if "sha256" in entry_})
        # The project: that role's two files, and nothing else generated.
        after = self.project_files()
        self.assertEqual(set(after) - set(project_files), {".claude/agents/worker.md", ".codex/agents/worker.toml"})
        for name in project_files:
            self.assertEqual(after[name], project_files[name], name)
        record = self.project_entries()
        new = {key for key in record if key not in project_record}
        self.assertEqual(new, {
            "project:.claude/agents", "project:.claude/agents/worker.md",
            "project:.codex/agents", "project:.codex/agents/worker.toml",
        })
        changed = {key for key in project_record if record[key] != project_record[key]}
        self.assertEqual(changed, {"project:.gitignore"})  # the ignore block lists the two files
        for key in (f"project:{SETTINGS}", f"project:{CONFIG}"):
            self.assertEqual(record[key]["sha256"], project_record[key]["sha256"])
        self.assertEqual(report["plan"][:2], ["create directory project:.claude/agents", "create directory project:.codex/agents"])
        self.assertEqual(sorted(line for line in report["plan"] if line.startswith("create file")),
                         ["create file project:.claude/agents/worker.md", "create file project:.codex/agents/worker.toml"])
        # The files are the role's definition with the project's tier, and the home keeps the user's.
        self.assertEqual(self.text(".claude/agents/worker.md", self.project).split("\n")[3], "model: fable")
        self.assertEqual(self.text(".claude/agents/worker.md").split("\n")[3], "model: sonnet")
        self.assertEqual(tomllib.loads(self.text(".codex/agents/worker.toml", self.project))["model"], "gpt-6-astra")
        built = {(found.provider, found.name): found for found in definitions.build(self.where(project=True))}
        self.assertEqual(after[".claude/agents/worker.md"], built[(CLAUDE, "worker.md")].text.encode("utf-8"))
        listed = {(found["provider"], found["file"], found["level"]) for found in report["definitions"]}
        self.assertIn((CLAUDE, "worker.md", "project"), listed)
        self.assertIn((CLAUDE, "worker.md", "home"), listed)
        self.assertEqual(sum(1 for found in listed if found[2] == "project"), 2)

        # Another tier for the same role: those two files again, and nothing else anywhere.
        hashes = {key: entry_.get("sha256") for key, entry_ in {**self.entries(), **self.project_entries()}.items()}
        self.write(self.project_file, DEFAULT_ON + '[roles.worker]\ntier = "fast"\n')
        self.with_project()
        now = {key: entry_.get("sha256") for key, entry_ in {**self.entries(), **self.project_entries()}.items()}
        self.assertEqual(set(now), set(hashes))
        self.assertEqual({key for key in now if now[key] != hashes[key]},
                         {"project:.claude/agents/worker.md", "project:.codex/agents/worker.toml"})
        self.same_home(home_tree, home_record)

    def test_an_override_of_a_hard_definition_and_of_one_providers_model(self) -> None:
        self.write(self.project_file, '[roles.worker-hard]\neffort = "max"\n[providers.codex.role_models]\nquick = "gpt-6-astra"\n')
        self.with_project()
        self.assertEqual(set(self.project_files()), {
            ".claude/agents/worker-hard.md", ".codex/agents/worker-hard.toml", ".codex/agents/quick.toml",
        })

    def test_the_ignore_block_lists_what_is_generated(self) -> None:
        (self.project / ".gitignore").write_bytes(b"node_modules/\n")
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        self.with_project()
        held = blocks.content_of((self.project / ".gitignore").read_bytes(), blocks.GITIGNORE)
        # The key and the block are setup's part of files the project owns: not listed.
        self.assertEqual(held, sorted([*ALWAYS, ".claude/agents/worker.md", ".codex/agents/worker.toml"]))
        self.assertTrue((self.project / ".gitignore").read_bytes().startswith(b"node_modules/\n"))
        # An override that goes takes its files and their entries with it.
        self.write(self.project_file, DEFAULT_ON)
        out = self.with_project()
        self.assertIn("  remove file project:.claude/agents/worker.md (backup)", out.splitlines())
        self.assertIn("  remove directory project:.codex/agents", out.splitlines())
        held = blocks.content_of((self.project / ".gitignore").read_bytes(), blocks.GITIGNORE)
        self.assertEqual(held, ALWAYS)
        self.assertEqual(set(self.project_files()), {SETTINGS, CONFIG})
        self.assertNothingAt(self.project / ".claude" / "agents")

    def test_a_default_alone_still_gets_the_ignore_block(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        self.with_project()
        self.assertEqual(blocks.content_of((self.project / ".gitignore").read_bytes(), blocks.GITIGNORE),
                         ALWAYS)

    def test_a_users_own_file_where_a_projects_definition_goes_is_a_conflict(self) -> None:
        self.keep(self.project / ".claude/agents/worker.md")
        self.write(self.project_file, OVERRIDE)
        err = self.refused(*self.project_arg)
        self.assertIn(f"{self.project / '.claude/agents/worker.md'}: a file is there, and setup did not write it", err)

    @unittest.skipUnless(os.name == "posix", "the view from WSL is rebuilt on a POSIX file system")
    def test_a_project_on_the_other_sides_drive_is_written(self) -> None:
        """A project is one directory for both sides: nothing in it is the
        other side's to write."""
        self.write(self.project_file, DEFAULT_ON + OVERRIDE)
        wsl = homes.Host(homes.WSL, {"PATH": ""}, (str(self.project),))
        code, out, err = self.render(*self.project_arg, host=wsl)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(set(self.project_files()), {SETTINGS, CONFIG, ".claude/agents/worker.md", ".codex/agents/worker.toml"})


class ProjectDefaultCase(EntryCase):
    def test_a_fresh_project_gets_the_key_and_the_block(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        code, report, err = self.report(*self.project_arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((self.project / SETTINGS).read_bytes(), b'{\n  "agent": "lead"\n}\n')
        raw = (self.project / CONFIG).read_bytes()
        self.assertTrue(raw.startswith(b"# workflow-setup:start starting-role\n# Generated by workflow setup: a Codex "
                                       b"session in this project starts as the role lead, because "
                                       b"roles.manager_default is set for the project."))
        self.assertTrue(raw.endswith(b'"""\n# workflow-setup:end starting-role\n'))
        self.assertIn(b"# Codex reads this file only in a trusted project. A key set here wins over the same key of a "
                      b"profile (codex --profile)", raw)
        data = tomllib.loads(raw.decode("utf-8"))
        self.assertEqual(list(data), list(entry.BLOCK_KEYS))
        # The same three values as the profile of the home.
        self.assertEqual(data, tomllib.loads(self.text(PROFILE)))
        self.assertEqual(report["project"]["manager_default"], True)
        self.assertEqual(report["project"]["starting_role"], "lead")
        self.assertEqual({item["name"]: item["status"] for item in report["project"]["items"]}, {
            f"{SETTINGS}: key agent": render.CREATE, f"{CONFIG}: block starting-role": render.CREATE,
        })
        self.assertEqual(report["counts"]["default_write"], 2)
        points = [point for point in report["entry_points"] if point["kind"] == "project-default"]
        self.assertEqual([(point["provider"], point["role"]) for point in points], [(CLAUDE, "lead"), (CODEX, "lead")])
        self.assertIn("read in a trusted project only; it wins over a profile", points[1]["how"])
        self.assertIn("2 project defaults set, 0 removed", report["summary"])
        out = self.with_project()
        self.assertIn("  roles.manager_default: true; a session in the project starts as lead", out.splitlines())
        self.assertIn(f'  {SETTINGS}: key agent: up to date: is "lead"', out.splitlines())

    def test_the_default_uses_the_projects_profile(self) -> None:
        self.write(self.project_file, DEFAULT_ON + '[roles.lead]\ntier = "frontier"\neffort = "high"\n')
        self.with_project()
        data = tomllib.loads(self.text(CONFIG, self.project))
        self.assertEqual((data["model"], data["model_reasoning_effort"]), ("gpt-6-astra", "high"))
        self.assertEqual(tomllib.loads(self.text(PROFILE))["model"], "gpt-6.1-sol")
        # On Claude Code the project's definition of the starting role carries it.
        self.assertEqual(self.text(".claude/agents/lead.md", self.project).split("\n")[3], "model: fable")
        self.assertNothingAt(self.project / ".codex" / "agents")

    def test_other_keys_of_the_settings_file_are_kept_as_they_are(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".claude").mkdir()
        (self.project / SETTINGS).write_bytes(USER_JSON)
        self.with_project()
        after = (self.project / SETTINGS).read_bytes()
        self.assertEqual(after, USER_JSON[:-3] + b',\r\n\t"agent": "lead"\r\n}')
        self.assertEqual(list(json.loads(after)), ["permissions", "model", "agent"])
        # Turned off, the file has its earlier bytes.
        self.write(self.project_file, "[roles]\nmanager_default = false\n")
        self.with_project()
        self.assertEqual((self.project / SETTINGS).read_bytes(), USER_JSON)

    def test_a_value_setup_did_not_set_is_kept_and_reported(self) -> None:
        # Review finding S15: it was replaced without being asked.
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".claude").mkdir()
        original = b'{"agent": "reviewer", "x": 1}\n'
        (self.project / SETTINGS).write_bytes(original)
        for more in (("--dry-run",), (), ()):
            code, out, err = self.render(*self.project_arg, *more)
            self.assertEqual((code, err), (3, ""), out)
            self.assertEqual((self.project / SETTINGS).read_bytes(), original)
            said = " ".join(out.split())
            self.assertIn('key agent: kept: is "reviewer", which setup did not set, and kept', said)
            self.assertIn('it is not set to "lead". --overwrite-edited sets it', said)
            self.assertIn("1 edited by hand and kept, which --overwrite-edited would replace", out.splitlines()[-1])
        self.assertNotIn(f"project:{SETTINGS}", self.project_entries())
        # The rest of the run was done all the same.
        self.assertTrue((self.project / CONFIG).is_file())
        code, report, _ = self.report(*self.project_arg)
        self.assertEqual(code, 3)
        item = next(item for item in report["project"]["items"] if item["kind"] == "key")
        self.assertEqual((item["status"], item["value"]), ("edited", "lead"))

    def test_the_users_value_is_replaced_on_request_and_put_back(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".claude").mkdir()
        (self.project / SETTINGS).write_bytes(b'{"agent": "reviewer", "x": 1}\n')
        code, out, err = self.render(*self.project_arg, "--overwrite-edited")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn('key agent: replace: was "reviewer", which setup did not set; set to "lead", as '
                      '--overwrite-edited asks. "reviewer" is put back when setup takes its key out',
                      " ".join(out.split()))
        self.assertEqual((self.project / SETTINGS).read_bytes(), b'{"agent": "lead", "x": 1}\n')
        # Setup's from now on: a second run, without the option, changes nothing.
        code, out, err = self.render(*self.project_arg)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("nothing to do", out.splitlines()[-1])
        self.write(self.project_file, "")
        out = self.with_project()
        self.assertIn('the value it had before, "reviewer", is put back', " ".join(out.split()))
        self.assertEqual((self.project / SETTINGS).read_bytes(), b'{"agent": "reviewer", "x": 1}\n')

    def test_a_key_the_user_already_set_to_the_role_stays_the_users(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".claude").mkdir()
        (self.project / SETTINGS).write_bytes(b'{"agent": "lead"}\n')
        self.with_project()
        self.assertNotIn(f"project:{SETTINGS}", self.project_entries())
        self.write(self.project_file, "")
        self.with_project()
        self.assertEqual((self.project / SETTINGS).read_bytes(), b'{"agent": "lead"}\n')

    def test_the_block_goes_to_the_head_and_the_users_bytes_are_kept(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".codex").mkdir()
        (self.project / CONFIG).write_bytes(USER_TOML)
        self.with_project()
        after = (self.project / CONFIG).read_bytes()
        self.assertTrue(after.startswith(b"# workflow-setup:start starting-role\r\n"))
        self.assertTrue(after.endswith(b"# workflow-setup:end starting-role\r\n\r\n" + USER_TOML))
        data = tomllib.loads(after.decode("utf-8"))
        self.assertEqual(list(data), [*entry.BLOCK_KEYS, "approval_policy", "features"])
        self.assertEqual((data["model"], data["approval_policy"], data["features"]), ("gpt-6.1-sol", "on-request", {"fast": True}))
        before = tree(self.root)
        self.assertEqual(self.report(*self.project_arg)[1]["plan"], [])
        self.assertEqual(tree(self.root), before)
        # Turned off, the file has its earlier bytes.
        self.write(self.project_file, "")
        self.with_project()
        self.assertEqual((self.project / CONFIG).read_bytes(), USER_TOML)

    def test_a_key_set_outside_the_block_is_reported_and_nothing_is_written(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".codex").mkdir()
        (self.project / CONFIG).write_bytes(b'model = "mine"\ndeveloper_instructions = "Mine."\n\n[features]\nfast = true\n')
        err = self.refused(*self.project_arg)
        file = self.project / CONFIG
        for key in ("model", "developer_instructions"):
            self.assertIn(
                f"{file}: {key} is already set outside setup's block. roles.manager_default asks setup to set "
                f"{key} for the starting role lead, and a key cannot be set twice in one TOML file, so setup "
                "writes nothing: your value stays in effect, and a Codex session in this project does not start "
                "as lead. Remove the key from the file, or set roles.manager_default = false for this project, "
                "and run render again", err,
            )
        self.assertNotIn("model_reasoning_effort is already set", err)
        self.assertNothingAt(self.manifest_file)
        self.assertNothingAt(self.project / ".claude")
        # A table of that name deeper in the file is not the top-level key.
        (self.project / CONFIG).write_bytes(b'[profiles.x]\nmodel = "mine"\n')
        self.with_project()
        self.assertEqual(tomllib.loads(self.text(CONFIG, self.project))["profiles"], {"x": {"model": "mine"}})

    def test_once_written_a_key_added_outside_the_block_is_reported_too(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        self.with_project()
        file = self.project / CONFIG
        file.write_bytes(file.read_bytes() + b'model = "mine"\n')
        err = self.refused(*self.project_arg)
        self.assertIn(f"{file}: model is already set outside setup's block.", err)

    def test_a_project_configuration_that_is_not_toml_is_refused(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        (self.project / ".codex").mkdir()
        (self.project / CONFIG).write_bytes(b"model = \n")
        err = self.refused(*self.project_arg)
        self.assertIn(f"{self.project / CONFIG}: is not valid TOML", err)

    def test_turned_off_both_go_and_what_setup_created_goes_with_them(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        before = tree(self.project)
        self.with_project()
        self.write(self.project_file, "[roles]\nmanager_default = false\n")
        code, report, err = self.report(*self.project_arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual({item["key"]: item["status"] for item in report["stale"]},
                         {f"project:{SETTINGS}": render.REMOVE, f"project:{CONFIG}": render.REMOVE})
        self.assertNothingAt(self.project / ".claude")
        self.assertNothingAt(self.project / ".codex")
        after = tree(self.project)
        self.assertOnlyStateAndIgnoreFileAdded(before, after)
        self.assertEqual(report["counts"]["default_remove"], 2)
        self.assertIn("0 project defaults set, 2 removed", report["summary"])
        self.assertEqual(report["project"]["manager_default"], False)
        self.assertEqual(self.report(*self.project_arg)[1]["plan"], [])

    def test_turned_off_an_edited_block_and_a_changed_key_are_kept(self) -> None:
        self.write(self.project_file, DEFAULT_ON)
        self.with_project()
        config = self.project / CONFIG
        config.write_bytes(config.read_bytes().replace(b'model = "gpt-6.1-sol"', b'model = "my-own"'))
        edited = config.read_bytes()
        (self.project / SETTINGS).write_bytes(b'{\n  "agent": "other"\n}\n')
        self.write(self.project_file, "")
        code, report, err = self.report(*self.project_arg)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(config.read_bytes(), edited)
        self.assertEqual((self.project / SETTINGS).read_bytes(), b'{\n  "agent": "other"\n}\n')
        self.assertEqual({item["key"]: item["status"] for item in report["stale"]},
                         {f"project:{SETTINGS}": render.KEPT, f"project:{CONFIG}": render.KEPT})
        # The key is the user's from now on; the block stays in the record until it is removed.
        self.assertNotIn(f"project:{SETTINGS}", self.project_entries())
        self.assertIn(entry.BLOCK_NAME, self.project_entries()[f"project:{CONFIG}"]["blocks"])

    def test_no_starting_role_is_an_error_only_when_the_default_is_asked(self) -> None:
        self.source(self.clone, "lead", includes='["gates.md"]', edits="false", dispatches='["worker", "worker-hard"]',
                    load="true", start="false")
        self.write(self.project_file, "")
        self.with_project()
        self.assertNothingAt(self.home / PROFILE)
        self.write(self.project_file, DEFAULT_ON)
        err = self.refused(*self.project_arg)
        self.assertIn("roles.manager_default is set, and no role has `start = true` under [entry] in its role.toml", err)

    def test_two_starting_roles_are_an_error_only_when_the_default_is_asked(self) -> None:
        self.source(self.clone, "runner", commands="false", dispatches='["worker"]', start="true")
        self.write(self.project_file, DEFAULT_ON)
        err = self.refused(*self.project_arg)
        self.assertIn("roles.manager_default is set, and 2 roles have `start = true` under [entry] in their "
                      "role.toml (lead, runner)", err)
        self.assertNothingAt(self.manifest_file)
        self.write(self.project_file, "")
        self.with_project()
        self.assertTrue((self.codex / "runner.config.toml").is_file())

    def test_a_default_set_at_the_user_level_reaches_a_project_only_with_the_option(self) -> None:
        self.write(self.user_file, DEFAULT_ON)
        before = tree(self.project)
        self.ok()
        self.assertEqual(tree(self.project), before)
        self.with_project()
        self.assertEqual(json.loads(self.text(SETTINGS, self.project)), {"agent": "lead"})
        # The project's own layer turns it off again.
        self.write(self.project_file, "[roles]\nmanager_default = false\n")
        self.with_project()
        self.assertNothingAt(self.project / ".claude")

    def test_only_an_installed_provider_gets_its_default(self) -> None:
        shutil.rmtree(self.clone / "providers" / "codex")
        self.codex.rmdir()
        self.write(self.project_file, DEFAULT_ON)
        self.with_project()
        self.assertEqual(set(self.project_files()), {SETTINGS})
        self.assertNothingAt(self.project / ".codex")

    def test_a_key_that_is_not_listed_cannot_be_set(self) -> None:
        self.assertEqual(
            fileops.jsonkeys.load_key_list()[f"project:{entry.CLAUDE_SETTINGS}"], (entry.AGENT_KEY,)
        )


class RepositoryCase(RenderCase):
    """The repository's own roles, whatever they say: subsets only, so a
    role added later breaks nothing here."""

    ROLES = ()

    def test_the_repositorys_roles_give_entry_points_and_a_project_level(self) -> None:
        # The roles and entry parts alone: where the repository is a clone
        # the other side sees through a network name, no link to it can be
        # made, and the links are not what this test is about.
        self.write(self.project_file, DEFAULT_ON + '[roles.coder]\ntier = "frontier"\n')
        where = Locations(home=self.home, project=self.project, clone=support.REPOSITORY)
        found, sources, parts = homes.resolve(where, self.host), validate.require(where), render.PARTS[2:4]
        self.assertEqual([part.name for part in parts], ["roles", "entry"])
        outcome = render.execute(found, sources, parts=parts)
        self.assertEqual((outcome.code, outcome.errors), (0, []))
        report = outcome.report
        before = tree(self.root)
        again = render.execute(found, sources, parts=parts)
        self.assertEqual((again.code, again.report["plan"]), (0, []))
        self.assertEqual(tree(self.root), before)

        loaded = roles.load_all(where)
        generated: list[bytes] = []
        for place, provider in ((self.claude_skills, CLAUDE), (self.codex_skills, CODEX)):
            self.assertLessEqual({"manager", "product-manager"}, set(os.listdir(place)))
            self.assertNotIn("coder", os.listdir(place))  # dispatched only
            for name in os.listdir(place):
                text = (place / name / "SKILL.md").read_bytes().decode("utf-8")
                fields, body = skill_parts(text)
                self.assertEqual((fields["name"], fields["compatibility"]), (name, provider))
                self.assertEqual(fields["disable-model-invocation"], "true")
                self.assertIn(loaded[name].description, fields["description"])
                self.assertEqual(body.count("suspends any other role"), 1)
                self.assertEqual(body.count("**Profile.**"), 1)
                self.assertIn("## Your bindings", body)
                yaml = (place / name / "agents" / "openai.yaml").read_bytes().decode("utf-8")
                self.assertEqual(validate.read_implicit_invocation(yaml), (False, []))
                generated += [text.encode("utf-8"), yaml.encode("utf-8")]
        # The definition's text is the skill's, on Claude Code where the Manager has both.
        definition = (self.claude / "agents" / "manager.md").read_bytes().decode("utf-8").split("-->\n\n", 1)[1]
        self.assertTrue((self.claude_skills / "manager" / "SKILL.md").read_bytes().decode("utf-8").endswith(definition))

        profile = tomllib.loads((self.codex / "manager.config.toml").read_bytes().decode("utf-8"))
        self.assertLessEqual({"model", "developer_instructions"}, set(profile))
        self.assertIn("# Manager", profile["developer_instructions"])
        self.assertNothingAt(self.codex / "config.toml")

        self.assertEqual(json.loads((self.project / SETTINGS).read_bytes()), {"agent": "manager"})
        config = tomllib.loads((self.project / CONFIG).read_bytes().decode("utf-8"))
        self.assertEqual(config, profile)
        project = {file.relative_to(self.project).as_posix() for directory in (".claude/agents", ".codex/agents")
                   for file in (self.project / directory).iterdir()}
        self.assertEqual(project, {".claude/agents/coder.md", ".codex/agents/coder.toml"})
        self.assertEqual(report["project"]["starting_role"], "manager")
        points = {(point["provider"], point["kind"], point["role"]) for point in report["entry_points"]}
        self.assertLessEqual({
            (CLAUDE, "load", "manager"), (CODEX, "load", "product-manager"), (CLAUDE, "start", "manager"),
            (CODEX, "start", "manager"), (CLAUDE, "project-default", "manager"), (CODEX, "project-default", "manager"),
        }, points)
        for point in report["entry_points"]:
            if point["kind"] == "load":
                self.assertGreater(point["bytes"], 1000)
                self.assertEqual(point["tokens"], -(-point["bytes"] // 3))
        generated += [(self.codex / "manager.config.toml").read_bytes(), (self.project / CONFIG).read_bytes(),
                      (self.project / ".claude/agents/coder.md").read_bytes()]
        for data in generated:
            self.assertNotIn(str(support.REPOSITORY).encode("utf-8"), data)
            self.assertNotIn(str(self.root).encode("utf-8"), data)
            self.assertNotIn(b"\r", data)
        # What doctor recomputes is what the records hold.
        home = json.loads(self.manifest_file.read_text(encoding="utf-8"))["entries"]
        places = {(CLAUDE, entry.LOADED): ".claude/skills", (CODEX, entry.LOADED): ".agents/skills",
                  (CODEX, entry.PROFILE): ".codex"}
        for (provider, kind, name), inputs in entry.digests(definitions.user_level(where)).items():
            self.assertEqual(home[f"home:{places[(provider, kind)]}/{name}"]["inputs"], inputs)


if __name__ == "__main__":
    unittest.main()
