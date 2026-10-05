"""Tests for session_profile.py.

Every record under ``fixtures/handwritten`` was written by hand from the
field names seen in provider records. These tests therefore prove only the
reader's own logic: where it looks, what it skips, what it prints. They do
not prove that either provider writes records of this shape. A fixture cut
from a real record is what does that. Those are under ``fixtures/real``,
each reduced to the fields read (see the README there).

Run from the repository root:
    python -m unittest discover -s tools/session-profile/tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SCRIPT = TESTS.parent / "session_profile.py"
FIXTURES = TESTS / "fixtures" / "handwritten"
CODEX_HOME = FIXTURES / "codex-home"
CLAUDE_HOME = FIXTURES / "claude-home"

# Every piece of message, prompt or instruction text in the fixtures holds
# this marker, so its absence from the output can be checked.
MARKER = "FIXTURE-TRANSCRIPT-TEXT"

CX_ROOT = "00000000-0000-7000-8000-000000000001"
CX_CODER = "00000000-0000-7000-8000-000000000002"
CX_PM = "00000000-0000-7000-8000-000000000003"
CX_HARD = "00000000-0000-7000-8000-000000000004"
CX_UNRELATED = "00000000-0000-7000-8000-000000000009"
CC_SESSION = "00000000-0000-4000-8000-0000000000aa"
CC_OTHER = "00000000-0000-4000-8000-0000000000bb"

_spec = importlib.util.spec_from_file_location("session_profile", SCRIPT)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)


def run(*argv: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Run main() with only the given provider variables set."""
    clean = {k: v for k, v in os.environ.items() if k not in ("CODEX_HOME", "CLAUDE_CONFIG_DIR")}
    clean.update(env or {})
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, clean, clear=True):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sp.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def codex(*argv: str) -> dict:
    code, out, _ = run("--json", "codex", *argv, env={"CODEX_HOME": str(CODEX_HOME)})
    assert code == 0, code
    return json.loads(out)


def claude(*argv: str) -> dict:
    code, out, _ = run("--json", "claude-code", *argv, env={"CLAUDE_CONFIG_DIR": str(CLAUDE_HOME)})
    assert code == 0, code
    return json.loads(out)


def by_id(report: dict) -> dict[str, dict]:
    return {agent["id"]: agent for agent in report["agents"]}


def pairs(agent: dict) -> list[tuple]:
    return [(p["model"], p["effort"], p["count"]) for p in agent["profiles"]]


class CodexTests(unittest.TestCase):
    def test_parent_is_listed_with_its_children_at_any_depth(self):
        report = codex(CX_ROOT)
        self.assertEqual(report["provider"], "codex")
        self.assertEqual(report["session"], CX_ROOT)
        self.assertEqual([a["id"] for a in report["agents"]], [CX_ROOT, CX_CODER, CX_HARD, CX_PM])
        self.assertEqual([a["depth"] for a in report["agents"]], [0, 1, 2, 1])
        self.assertNotIn(CX_UNRELATED, by_id(report))

    def test_roles_models_and_efforts(self):
        agents = by_id(codex(CX_ROOT))
        root, coder, hard = agents[CX_ROOT], agents[CX_CODER], agents[CX_HARD]
        self.assertIsNone(root["role"])
        self.assertEqual(root["kind"], "user")
        self.assertEqual(pairs(root), [("fixture-model-a", "low", 2), ("fixture-model-b", "xhigh", 1)])
        self.assertEqual(coder["role"], "coder")
        self.assertEqual(coder["role_source"], "session_meta.agent_role")
        self.assertEqual(coder["name"], "/root/coder (Ada)")
        self.assertEqual(coder["parent_id"], CX_ROOT)
        self.assertEqual(coder["kind"], "subagent")
        self.assertEqual(pairs(coder)[0], ("fixture-model-b", "medium", 2))
        self.assertEqual(hard["role"], "coder_hard")
        self.assertEqual(hard["parent_id"], CX_CODER)

    def test_fallback_locations(self):
        agents = by_id(codex(CX_ROOT))
        pm, hard = agents[CX_PM], agents[CX_HARD]
        self.assertEqual(pm["role"], "product_manager")
        self.assertEqual(pm["role_source"], "session_meta.source.subagent.thread_spawn.agent_role")
        self.assertEqual(pm["parent_id"], CX_ROOT)
        self.assertEqual(pairs(hard), [("fixture-model-d", "high", 1)])
        self.assertEqual(hard["effort_sources"], ["turn_context.collaboration_mode.settings.reasoning_effort"])

    def test_missing_values_are_null_and_not_a_crash(self):
        pm = by_id(codex(CX_ROOT))[CX_PM]
        self.assertEqual(pm["provider_versions"], [])
        self.assertEqual(
            pairs(pm),
            [("fixture-model-c", None, 1), (None, "high", 1), (None, None, 1)],
        )

    def test_malformed_lines_are_skipped_and_counted(self):
        coder = by_id(codex(CX_ROOT))[CX_CODER]
        self.assertEqual(coder["malformed_lines"], 3)
        self.assertEqual(pairs(coder), [("fixture-model-b", "medium", 2), (None, None, 1)])

    def test_unknown_fields_and_record_types_are_ignored(self):
        report = codex(CX_ROOT)
        self.assertNotIn("must-not-be-read", json.dumps(report))
        self.assertNotIn("a_field_added_later", json.dumps(report))

    def test_provider_version(self):
        report = codex(CX_ROOT)
        self.assertEqual(report["provider_versions"], ["0.160.0"])
        self.assertEqual(report["written_against"], "0.160.0")

    def test_a_child_id_lists_that_child_and_its_own_children(self):
        report = codex(CX_CODER)
        self.assertEqual([a["id"] for a in report["agents"]], [CX_CODER, CX_HARD])
        self.assertEqual(report["agents"][0]["parent_id"], CX_ROOT)

    def test_path_argument_finds_children_without_codex_home(self):
        path = next(CODEX_HOME.rglob(f"*{CX_ROOT}.jsonl"))
        code, out, _ = run("--json", "codex", str(path), env={"CODEX_HOME": str(TESTS / "no-such-home")})
        self.assertEqual(code, 0)
        self.assertEqual([a["id"] for a in json.loads(out)["agents"]], [CX_ROOT, CX_CODER, CX_HARD, CX_PM])

    def test_a_file_with_no_record_in_it(self):
        path = next(CODEX_HOME.rglob("*00000000000a.jsonl"))
        report = codex(str(path))
        (agent,) = report["agents"]
        self.assertEqual(agent["id"], "00000000-0000-7000-8000-00000000000a")
        self.assertEqual(agent["profiles"], [])
        self.assertEqual(agent["malformed_lines"], 2)
        self.assertIsNone(agent["role"])

    def test_unknown_session_exits_1(self):
        code, out, err = run("codex", "00000000-0000-7000-8000-0000000000ee", env={"CODEX_HOME": str(CODEX_HOME)})
        self.assertEqual((code, out), (1, ""))
        self.assertIn("no rollout", err)

    def test_parent_cycle_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            sessions.mkdir()
            for me, parent in (("c1", "c2"), ("c2", "c1")):
                meta = {"type": "session_meta", "payload": {"id": me, "parent_thread_id": parent}}
                (sessions / f"rollout-{me}.jsonl").write_text(json.dumps(meta) + "\n", encoding="utf-8", newline="\n")
            code, out, _ = run("--json", "codex", "c1", env={"CODEX_HOME": tmp})
        self.assertEqual(code, 0)
        self.assertEqual(sorted(a["id"] for a in json.loads(out)["agents"]), ["c1", "c2"])


class ClaudeCodeTests(unittest.TestCase):
    def test_main_agent_is_listed_with_its_subagents(self):
        report = claude(CC_SESSION)
        self.assertEqual(report["provider"], "claude-code")
        self.assertEqual([a["id"] for a in report["agents"]], [CC_SESSION, "a01", "a02", "a03", "a04"])
        self.assertEqual([a["depth"] for a in report["agents"]], [0, 1, 2, 1, 1])
        self.assertEqual([a["kind"] for a in report["agents"]], ["main"] + ["subagent"] * 4)

    def test_main_agent(self):
        main = by_id(claude(CC_SESSION))[CC_SESSION]
        self.assertIsNone(main["role"])
        self.assertIsNone(main["parent_id"])
        # Two entries share one message id and count once; the synthetic entry is left out.
        self.assertEqual(pairs(main), [("fixture-claude-a", "high", 1), ("fixture-claude-a", "max", 1)])
        self.assertEqual(main["malformed_lines"], 1)

    def test_subagent_role_comes_from_the_meta_file(self):
        agents = by_id(claude(CC_SESSION))
        self.assertEqual(agents["a01"]["role"], "coder")
        self.assertEqual(agents["a01"]["role_source"], "meta.json:agentType")
        self.assertEqual(agents["a01"]["parent_id"], CC_SESSION)
        self.assertEqual(pairs(agents["a01"]), [("fixture-claude-b", "medium", 2)])
        self.assertEqual(agents["a01"]["effort_sources"], ["assistant entry:effort"])
        self.assertEqual(agents["a02"]["role"], "coder-hard")
        self.assertEqual(agents["a02"]["parent_id"], "a01")

    def test_fallback_locations(self):
        agents = by_id(claude(CC_SESSION))
        self.assertEqual(pairs(agents["a02"]), [("fixture-claude-c", "high", 1)])
        self.assertEqual(agents["a02"]["effort_sources"], ["assistant entry:perTurnEffort"])
        # a04's meta file is cut off, so the role falls back to the entry field.
        self.assertEqual(agents["a04"]["role"], "product-manager")
        self.assertEqual(agents["a04"]["role_source"], "assistant entry:attributionAgent")

    def test_missing_values_are_null_and_not_a_crash(self):
        a03 = by_id(claude(CC_SESSION))["a03"]
        self.assertIsNone(a03["role"])
        self.assertIsNone(a03["role_source"])
        self.assertEqual(a03["provider_versions"], [])
        self.assertEqual(pairs(a03), [("fixture-claude-d", None, 1), (None, None, 4)])

    def test_unknown_fields_and_entry_types_are_ignored(self):
        text = json.dumps(claude(CC_SESSION))
        self.assertNotIn("must-not-be-read", text)
        self.assertNotIn("a_key_added_later", text)
        self.assertNotIn("<synthetic>", text)

    def test_provider_version(self):
        report = claude(CC_SESSION)
        self.assertEqual(report["provider_versions"], ["2.1.289", "2.1.288"])
        self.assertEqual(report["written_against"], "2.1.289")
        self.assertEqual(by_id(report)["a02"]["provider_versions"], ["2.1.288"])

    def test_other_sessions_are_not_mixed_in(self):
        self.assertNotIn("fixture-claude-unrelated", json.dumps(claude(CC_SESSION)))
        self.assertEqual([a["id"] for a in claude(CC_OTHER)["agents"]], [CC_OTHER])

    def test_path_arguments(self):
        project = CLAUDE_HOME / "projects" / "-fixture-project"
        code, out, _ = run("--json", "claude-code", str(project / f"{CC_SESSION}.jsonl"))
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["agents"]), 5)
        sub = project / CC_SESSION / "subagents" / "agent-a02.jsonl"
        code, out, _ = run("--json", "claude-code", str(sub))
        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(report["session"], CC_SESSION)
        self.assertEqual([(a["id"], a["role"], a["parent_id"]) for a in report["agents"]], [("a02", "coder-hard", "a01")])

    def test_subagents_without_a_main_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(CLAUDE_HOME, Path(tmp) / "home")
            (Path(tmp) / "home" / "projects" / "-fixture-project" / f"{CC_SESSION}.jsonl").unlink()
            code, out, _ = run("--json", "claude-code", CC_SESSION, env={"CLAUDE_CONFIG_DIR": str(Path(tmp) / "home")})
        self.assertEqual(code, 0)
        self.assertEqual([a["id"] for a in json.loads(out)["agents"]], ["a01", "a02", "a03", "a04"])

    def test_session_in_two_projects_asks_for_a_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(CLAUDE_HOME, Path(tmp) / "home")
            projects = Path(tmp) / "home" / "projects"
            shutil.copy(projects / "-fixture-project" / f"{CC_SESSION}.jsonl", projects / "-other-project")
            code, out, err = run("claude-code", CC_SESSION, env={"CLAUDE_CONFIG_DIR": str(Path(tmp) / "home")})
        self.assertEqual((code, out), (1, ""))
        self.assertIn("more than one project", err)

    def test_unknown_session_exits_1(self):
        code, out, err = run("claude-code", "no-such-session", env={"CLAUDE_CONFIG_DIR": str(CLAUDE_HOME)})
        self.assertEqual((code, out), (1, ""))
        self.assertIn("no transcript", err)


def write_claude_session(home: Path, main: list[dict], sub: list[dict] | None = None, meta: dict | None = None) -> None:
    """Write a main transcript and, if ``sub`` is given, one subagent ``a01``."""
    project = home / "projects" / "-p"
    project.mkdir(parents=True)
    (project / f"{CC_SESSION}.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in main), encoding="utf-8", newline="\n"
    )
    if sub is not None:
        subagents = project / CC_SESSION / "subagents"
        subagents.mkdir(parents=True)
        (subagents / "agent-a01.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in sub), encoding="utf-8", newline="\n"
        )
        if meta is not None:
            (subagents / "agent-a01.meta.json").write_text(json.dumps(meta), encoding="utf-8")


class ClaudeMainRoleTests(unittest.TestCase):
    """Where a session started with ``--agent`` records the main agent's role."""

    RESPONSE = {"type": "assistant", "version": "2.1.289", "effort": "high",
                "message": {"id": "m1", "model": "fixture-claude-a"}}

    @staticmethod
    def setting(name) -> dict:
        return {"type": "agent-setting", "agentSetting": name, "sessionId": CC_SESSION}

    def read(self, main: list[dict], sub: list[dict] | None = None, meta: dict | None = None) -> tuple[list[dict], str]:
        with tempfile.TemporaryDirectory() as tmp:
            write_claude_session(Path(tmp), main, sub, meta)
            env = {"CLAUDE_CONFIG_DIR": tmp}
            code, out, err = run("--json", "claude-code", CC_SESSION, env=env)
            self.assertEqual((code, err), (0, ""))
            text = run("claude-code", CC_SESSION, env=env)[1]
        return json.loads(out)["agents"], text

    def test_agent_setting_entry_is_the_main_agents_role(self):
        agents, text = self.read([self.setting("manager"), self.RESPONSE, self.setting("manager"), self.RESPONSE])
        (main,) = agents
        self.assertEqual((main["role"], main["role_source"]), ("manager", "agent-setting entry:agentSetting"))
        self.assertEqual((main["kind"], main["notes"]), ("main", []))
        self.assertEqual(pairs(main), [("fixture-claude-a", "high", 1)])
        self.assertIn("role:    manager\n", text)

    def test_a_session_started_without_an_agent_records_no_role(self):
        agents, text = self.read([{"type": "mode", "mode": "normal"}, self.RESPONSE])
        (main,) = agents
        self.assertEqual((main["role"], main["role_source"]), (None, None))
        self.assertIn("role:    not recorded\n", text)

    def test_the_key_is_read_only_on_an_agent_setting_entry(self):
        agents, _ = self.read([dict(self.RESPONSE, agentSetting="manager"), {"type": "user", "agentSetting": "manager"}])
        self.assertEqual((agents[0]["role"], agents[0]["role_source"]), (None, None))

    def test_a_setting_that_is_not_a_name_is_not_recorded(self):
        for value in (MARKER + " a sentence where a name belongs", "", None, 7, ["manager"], {"name": "manager"}):
            agents, text = self.read([self.setting(value), self.RESPONSE])
            self.assertEqual((agents[0]["role"], agents[0]["role_source"]), (None, None), repr(value))
            self.assertNotIn(MARKER, text)
            self.assertNotIn(MARKER, json.dumps(agents))

    def test_order_of_preference(self):
        attributed = dict(self.RESPONSE, attributionAgent="attributed")
        # The setting wins over the attribution, wherever it stands in the file.
        for main in ([self.setting("manager"), attributed], [attributed, self.setting("manager")]):
            agents, _ = self.read(main, sub=[self.setting("other"), attributed], meta={"agentType": "coder"})
            self.assertEqual(
                [(a["role"], a["role_source"]) for a in agents],
                [("manager", "agent-setting entry:agentSetting"), ("coder", "meta.json:agentType")],
            )

    def test_a_setting_that_changes_is_noted(self):
        agents, text = self.read([self.setting("manager"), self.RESPONSE, self.setting("coder"), self.setting("manager")])
        self.assertEqual(agents[0]["role"], "manager")
        self.assertEqual(len(agents[0]["notes"]), 1)
        self.assertIn("manager, coder", agents[0]["notes"][0])
        self.assertIn("note:    the agent setting changed", text)


REAL = TESTS / "fixtures" / "real"
REAL_CLAUDE_HOME = REAL / "claude-code-2.1.289"
REAL_CC_SESSION = "45ec0763-013a-4e48-9026-cff114de0ddb"


class RealClaudeCodeFixtureTests(unittest.TestCase):
    """A record Claude Code 2.1.289 wrote, reduced by ``reduce_claude_code.py``."""

    def report(self) -> dict:
        code, out, err = run("--json", "claude-code", REAL_CC_SESSION, env={"CLAUDE_CONFIG_DIR": str(REAL_CLAUDE_HOME)})
        self.assertEqual((code, err), (0, ""))
        return json.loads(out)

    def test_four_agents_with_their_roles_models_and_efforts(self):
        report = self.report()
        self.assertEqual(report["provider_versions"], ["2.1.289"])
        self.assertEqual(report["written_against"], "2.1.289")
        self.assertEqual(len(report["agents"]), 4)
        self.assertEqual([a["kind"] for a in report["agents"]], ["main", "subagent", "subagent", "subagent"])
        self.assertEqual([a["depth"] for a in report["agents"]], [0, 1, 1, 1])
        main = report["agents"][0]
        self.assertEqual(main["id"], REAL_CC_SESSION)
        self.assertEqual((main["role"], main["role_source"]), ("manager", "agent-setting entry:agentSetting"))
        self.assertEqual(pairs(main), [("claude-sonnet-5-5", "high", 3)])
        found = {a["role"]: a for a in report["agents"][1:]}
        self.assertEqual(sorted(found), ["coder", "coder-hard", "product-manager"])
        self.assertEqual(pairs(found["product-manager"]), [("claude-opus-5-5", "high", 3)])
        self.assertEqual(pairs(found["coder"]), [("claude-sonnet-5-5", "medium", 3)])
        self.assertEqual(pairs(found["coder-hard"]), [("claude-opus-5-5", "high", 3)])
        for agent in report["agents"][1:]:
            self.assertEqual(agent["role_source"], "meta.json:agentType")
            self.assertEqual(agent["parent_id"], REAL_CC_SESSION)
        for agent in report["agents"]:
            self.assertEqual(agent["provider_versions"], ["2.1.289"])
            self.assertEqual(agent["effort_sources"], ["assistant entry:effort"])
            self.assertEqual((agent["malformed_lines"], agent["notes"]), (0, []))

    def test_text_output(self):
        code, out, _ = run("claude-code", REAL_CC_SESSION, env={"CLAUDE_CONFIG_DIR": str(REAL_CLAUDE_HOME)})
        self.assertEqual(code, 0)
        self.assertIn("provider version recorded: 2.1.289 (reader written against 2.1.289)", out)
        self.assertIn("agents: 4", out)
        self.assertIn("role:    manager\n", out)
        self.assertNotIn(sp.NOT_RECORDED, out)

    def test_the_fixture_holds_only_the_fields_read(self):
        allowed = {"type", "version", "effort", "perTurnEffort", "attributionAgent", "agentSetting", "message"}
        files = sorted(p for p in REAL_CLAUDE_HOME.rglob("*") if p.is_file())
        self.assertEqual(len(files), 7)
        for path in files:
            if path.name.endswith(".meta.json"):
                self.assertEqual(set(json.loads(path.read_text(encoding="utf-8"))), {"agentType"}, path.name)
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                self.assertLessEqual(set(entry), allowed, path.name)
                self.assertLessEqual(set(entry.get("message", {})), {"id", "model"}, path.name)
                for value in list(entry.values()) + list(entry.get("message", {}).values()):
                    if not isinstance(value, dict):
                        self.assertIsNotNone(sp._name(value), path.name)

    def test_the_fixture_names_no_machine_path_or_user(self):
        user = Path.home().name
        files = sorted(p for p in REAL.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        # Every real fixture is under REAL, so this covers them all, with their reducers.
        for home, count in ((REAL_CLAUDE_HOME, 7), (REAL_CODEX_HOME, 5)):
            self.assertEqual(sum(1 for p in files if home in p.parents), count, home.name)
        for path in files:
            data = path.read_bytes()
            self.assertNotIn(b"\r", data, path.name)
            text = data.decode("utf-8")
            for pattern in ("/" + "home/", "/" + "mnt/", "/" + "Users/", r"\b[A-Za-z]:" + r"\\"):
                self.assertIsNone(re.search(pattern, text), f"{path.name} matches {pattern!r}")
            if len(user) > 3:
                self.assertNotIn(user, text, path.name)
                self.assertNotIn(user, path.relative_to(REAL).as_posix())


REAL_CODEX_HOME = REAL / "codex-0.160.0"
REAL_CX_MAIN = "01a10c90-d1fb-7703-89d6-1e13f807a41b"
REAL_CX_SPAWN_KEYS = {"parent_thread_id", "agent_role", "agent_path", "agent_nickname"}


class RealCodexFixtureTests(unittest.TestCase):
    """Rollouts Codex 0.160.0 wrote, reduced by ``reduce_codex.py``.

    The session had six agents. One of the two ``guardian_review`` threads was
    left out of the fixture, so five are read.
    """

    def report(self) -> dict:
        code, out, err = run("--json", "codex", REAL_CX_MAIN, env={"CODEX_HOME": str(REAL_CODEX_HOME)})
        self.assertEqual((code, err), (0, ""))
        return json.loads(out)

    def test_five_agents_with_their_roles_models_and_efforts(self):
        report = self.report()
        self.assertEqual(report["provider_versions"], ["0.160.0"])
        self.assertEqual(report["written_against"], "0.160.0")
        self.assertEqual((report["session"], report["notes"]), (REAL_CX_MAIN, []))
        agents = report["agents"]
        self.assertEqual(len(agents), 6 - 1)
        self.assertEqual([a["kind"] for a in agents], ["user", "subagent", "subagent", "guardian_review", "subagent"])
        self.assertEqual([a["depth"] for a in agents], [0, 1, 1, 2, 1])
        self.assertEqual([a["role"] for a in agents], [None, "product_manager", "coder", None, "coder_hard"])
        main, manager_child, coder, guardian, hard = agents
        # The main thread's record names no role: its instructions come from the project's configuration.
        self.assertEqual((main["id"], main["role"], main["role_source"], main["name"]), (REAL_CX_MAIN, None, None, None))
        self.assertIsNone(main["parent_id"])
        self.assertEqual(pairs(main), [("gpt-6.1-sol", "medium", 17)])
        self.assertEqual(pairs(manager_child), [("gpt-6.1-sol", "high", 1)])
        self.assertEqual(pairs(coder), [("gpt-6.1-sol", "medium", 2)])
        self.assertEqual(pairs(hard), [("gpt-6.1-sol", "high", 1)])
        self.assertNotEqual(pairs(hard)[0][1], pairs(main)[0][1])
        self.assertEqual(
            [a["name"] for a in (manager_child, coder, hard)],
            ["/root/prd_header_edit (Tesla)", "/root/coder_r1 (Mencius)", "/root/coder_r2 (Darwin)"],
        )
        for agent in (manager_child, coder, hard):
            # The role is at the top of the session_meta payload, which is where the reader looks first.
            self.assertEqual(agent["role_source"], "session_meta.agent_role")
            self.assertEqual(agent["parent_id"], REAL_CX_MAIN)
        # A guardian review is a child of the thread whose command it reviewed, and has no role.
        self.assertEqual((guardian["parent_id"], guardian["role_source"], guardian["name"]), (coder["id"], None, None))
        self.assertEqual(pairs(guardian), [("codex-auto-review", "low", 1)])
        for agent in agents:
            self.assertEqual(agent["provider_versions"], ["0.160.0"])
            self.assertEqual(agent["effort_sources"], ["turn_context.effort"])
            self.assertEqual((agent["malformed_lines"], agent["notes"], agent["readable"]), (0, [], True))

    def test_a_spawned_thread_records_its_role_in_two_places(self):
        """The payload's own keys and ``source.subagent.thread_spawn`` agree in the real record."""
        spawned = 0
        for path in sorted(REAL_CODEX_HOME.rglob("*.jsonl")):
            meta = json.loads(path.read_text(encoding="utf-8").splitlines()[0])["payload"]
            spawn = sp._dig(meta, ("source", "subagent", "thread_spawn"))
            if spawn is None:
                self.assertNotIn("agent_role", meta, path.name)
                continue
            spawned += 1
            self.assertEqual(set(spawn), REAL_CX_SPAWN_KEYS, path.name)
            for key in REAL_CX_SPAWN_KEYS:
                self.assertEqual(meta[key], spawn[key], f"{path.name} {key}")
            self.assertEqual(meta["parent_thread_id"], REAL_CX_MAIN)
        self.assertEqual(spawned, 3)

    def test_text_output(self):
        code, out, _ = run("codex", REAL_CX_MAIN, env={"CODEX_HOME": str(REAL_CODEX_HOME)})
        self.assertEqual(code, 0)
        self.assertIn("provider version recorded: 0.160.0 (reader written against 0.160.0)", out)
        self.assertIn("agents: 5", out)
        self.assertIn("role:    coder_hard\n", out)
        self.assertIn("model:   gpt-6.1-sol  (17 turns)\n", out)
        self.assertEqual(out.count("role:    " + sp.NOT_RECORDED), 2)
        self.assertNotIn("model:   " + sp.NOT_RECORDED, out)
        self.assertNotIn("effort:  " + sp.NOT_RECORDED, out)

    def test_the_fixture_holds_only_the_fields_read(self):
        meta_keys = {"id", "cli_version", "thread_source", "source"} | REAL_CX_SPAWN_KEYS
        files = sorted(p for p in REAL_CODEX_HOME.rglob("*") if p.is_file())
        self.assertEqual(len(files), 5)
        for path in files:
            self.assertEqual(path.parent, REAL_CODEX_HOME / "sessions" / "2026" / "10" / "05")
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["type"] for e in entries[:1]], ["session_meta"], path.name)
            self.assertTrue(path.name.endswith(entries[0]["payload"]["id"] + ".jsonl"))
            leaves: list = []
            for entry in entries:
                self.assertEqual(set(entry), {"type", "payload"}, path.name)
                payload = entry["payload"]
                if entry["type"] == "session_meta":
                    self.assertLessEqual(set(payload), meta_keys, path.name)
                    spawn = {}
                    if "source" in payload:
                        self.assertEqual(set(payload["source"]), {"subagent"}, path.name)
                        self.assertEqual(set(payload["source"]["subagent"]), {"thread_spawn"}, path.name)
                        spawn = payload["source"]["subagent"]["thread_spawn"]
                        self.assertLessEqual(set(spawn), REAL_CX_SPAWN_KEYS, path.name)
                    for holder in (payload, spawn):
                        leaves.extend(v for k, v in holder.items() if k not in ("source", "agent_path"))
                        if "agent_path" in holder:
                            self.assertIsNotNone(sp._agent_path(holder["agent_path"]), path.name)
                else:
                    self.assertEqual(entry["type"], "turn_context", path.name)
                    self.assertEqual(set(payload), {"model", "effort", "collaboration_mode"}, path.name)
                    self.assertEqual(set(payload["collaboration_mode"]), {"settings"}, path.name)
                    settings = payload["collaboration_mode"]["settings"]
                    self.assertEqual(set(settings), {"model", "reasoning_effort"}, path.name)
                    leaves.extend([payload["model"], payload["effort"], *settings.values()])
            for value in leaves:
                self.assertIsNotNone(sp._name(value), f"{path.name} {value!r}")

    def test_reducing_the_fixture_again_changes_nothing(self):
        """The fixture is what ``reduce_codex.py`` writes: reduced once more, it is the same bytes."""
        spec = importlib.util.spec_from_file_location("reduce_codex", REAL / "reduce_codex.py")
        reducer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reducer)
        sources = sorted(REAL_CODEX_HOME.rglob("*.jsonl"))
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(reducer.main([*map(str, sources), tmp]), 0)
            for source in sources:
                again = Path(tmp) / source.relative_to(REAL_CODEX_HOME)
                self.assertEqual(again.read_bytes(), source.read_bytes(), source.name)

    def test_the_reducer_drops_text_and_unread_fields(self):
        spec = importlib.util.spec_from_file_location("reduce_codex", REAL / "reduce_codex.py")
        reducer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reducer)
        sources = sorted(p for p in CODEX_HOME.rglob("*.jsonl") if sp._UUID_AT_END.search(p.stem))
        self.assertTrue(any(MARKER in p.read_text(encoding="utf-8") for p in sources))
        with tempfile.TemporaryDirectory() as tmp:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(reducer.main([*map(str, sources), tmp]), 0)
                self.assertEqual(reducer.main([str(Path(tmp) / "notes.jsonl"), tmp]), 2)
            written = sorted(Path(tmp).rglob("*.jsonl"))
            self.assertEqual([p.name for p in written], [p.name for p in sources])
            for path in written:
                text = path.read_text(encoding="utf-8")
                for unwanted in (MARKER, "must-not-be-read", "a_field_added_later", "cwd", "instructions"):
                    self.assertNotIn(unwanted, text, path.name)
            self.assertNotIn(str(CODEX_HOME), out.getvalue() + err.getvalue())
            code, reduced, _ = run("--json", "codex", CX_ROOT, env={"CODEX_HOME": tmp})
        self.assertEqual(code, 0)
        self.assertEqual(
            [(a["id"], a["role"], a["parent_id"]) for a in json.loads(reduced)["agents"]],
            [(a["id"], a["role"], a["parent_id"]) for a in codex(CX_ROOT)["agents"]],
        )


class EnvironmentTests(unittest.TestCase):
    def test_codex_home_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run("codex", CX_ROOT, env={"CODEX_HOME": tmp})[0], 1)
        self.assertEqual(run("codex", CX_ROOT, env={"CODEX_HOME": str(CODEX_HOME)})[0], 0)

    def test_claude_config_dir_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run("claude-code", CC_SESSION, env={"CLAUDE_CONFIG_DIR": tmp})[0], 1)
        self.assertEqual(run("claude-code", CC_SESSION, env={"CLAUDE_CONFIG_DIR": str(CLAUDE_HOME)})[0], 0)

    def test_defaults_are_under_the_user_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            shutil.copytree(CODEX_HOME, home / ".codex")
            shutil.copytree(CLAUDE_HOME, home / ".claude")
            with mock.patch.object(Path, "home", return_value=home):
                self.assertEqual(run("codex", CX_ROOT)[0], 0)
                self.assertEqual(run("claude-code", CC_SESSION)[0], 0)
                self.assertEqual(run("codex", CX_ROOT, env={"CODEX_HOME": ""})[0], 0)


class OutputTests(unittest.TestCase):
    def outputs(self) -> list[str]:
        found = []
        for json_flag in ([], ["--json"]):
            found.append(run(*json_flag, "codex", CX_ROOT, env={"CODEX_HOME": str(CODEX_HOME)})[1])
            found.append(run(*json_flag, "claude-code", CC_SESSION, env={"CLAUDE_CONFIG_DIR": str(CLAUDE_HOME)})[1])
            for path in sorted(FIXTURES.rglob("*.jsonl")):
                provider = "codex" if CODEX_HOME in path.parents else "claude-code"
                code, out, err = run(*json_flag, provider, str(path))
                self.assertEqual(code, 0, path.name)
                self.assertEqual(err, "", path.name)
                found.append(out)
        return found

    def test_no_fixture_text_reaches_the_output(self):
        holders = [p for p in FIXTURES.rglob("*") if p.is_file() and MARKER in p.read_text(encoding="utf-8")]
        self.assertGreaterEqual(len(holders), 8, "the fixtures must hold text for this test to mean anything")
        for output in self.outputs():
            self.assertTrue(output)
            self.assertNotIn(MARKER, output)

    def test_text_output(self):
        code, out, _ = run("codex", CX_ROOT, env={"CODEX_HOME": str(CODEX_HOME)})
        self.assertEqual(code, 0)
        self.assertIn("provider version recorded: 0.160.0 (reader written against 0.160.0)", out)
        self.assertIn("agents: 4", out)
        self.assertIn("role:    coder\n", out)
        self.assertIn("role:    not recorded\n", out)
        self.assertIn("model:   fixture-model-a  (2 turns)\n", out)
        self.assertIn("model:   fixture-model-b  (1 turn)\n", out)
        self.assertIn("effort:  not recorded\n", out)
        self.assertIn("skipped: 3 malformed lines\n", out)
        self.assertNotIn(str(CODEX_HOME), out)

    def test_text_output_claude_code(self):
        code, out, _ = run("claude-code", CC_SESSION, env={"CLAUDE_CONFIG_DIR": str(CLAUDE_HOME)})
        self.assertEqual(code, 0)
        self.assertIn("provider version recorded: 2.1.289, 2.1.288 (reader written against 2.1.289)", out)
        self.assertIn("role:    coder-hard\n", out)
        self.assertIn("model:   fixture-claude-b  (2 responses)\n", out)
        self.assertIn("version: not recorded\n", out)

    def test_help_documents_the_session_argument(self):
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, encoding="utf-8", check=False
        )
        self.assertEqual(done.returncode, 0)
        for word in (
            "CLAUDE_CONFIG_DIR", "CODEX_HOME", "session id", "--json", "not recorded",
            "--full-paths", "own directory only", "file name",
        ):
            self.assertIn(word, done.stdout)

    def test_bad_provider_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as raised:
            run("gemini", "x")
        self.assertEqual(raised.exception.code, 2)


def thread(number: int) -> str:
    return f"00000000-0000-7000-8000-{number:012x}"


def write_rollout(directory: Path, thread_id: str, payload: dict | None = None, stamp: str = "10-00-00",
                  before: list[dict] | None = None) -> Path:
    """Write a rollout named for ``thread_id`` whose session_meta holds ``payload``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-2026-10-03T{stamp}-{thread_id}.jsonl"
    meta = {"id": thread_id, "cli_version": "0.160.0"}
    meta.update(payload or {})
    records = list(before or []) + [
        {"type": "session_meta", "payload": meta},
        {"type": "turn_context", "payload": {"model": "fixture-model-a", "effort": "low"}},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8", newline="\n")
    return path


class IdentifierOnlyTests(unittest.TestCase):
    """A sentence in a field that should hold a name is not printed."""

    SENTENCE = MARKER + " a sentence where a name belongs"

    def both(self, provider: str, session: str, env: dict[str, str]) -> list[str]:
        found = []
        for flags in ([], ["--json"], ["--json", "--full-paths"]):
            code, out, err = run(*flags, provider, session, env=env)
            self.assertEqual((code, err), (0, ""))
            found.append(out)
        return found

    def test_codex_role_path_and_nickname(self):
        spawn = {"agent_role": self.SENTENCE, "agent_path": "/root/" + self.SENTENCE, "agent_nickname": self.SENTENCE}
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            write_rollout(sessions, thread(1), dict(spawn, source={"subagent": {"thread_spawn": dict(spawn)}}))
            outputs = self.both("codex", thread(1), {"CODEX_HOME": tmp})
        for output in outputs:
            self.assertNotIn(MARKER, output)
            self.assertNotIn("sentence", output)
        (agent,) = json.loads(outputs[1])["agents"]
        self.assertEqual((agent["role"], agent["role_source"], agent["name"]), (None, None, None))
        self.assertIn("role:    not recorded\n", outputs[0])

    def test_claude_agent_type_and_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-p"
            subagents = project / CC_SESSION / "subagents"
            subagents.mkdir(parents=True)
            entry = {"type": "assistant", "attributionAgent": self.SENTENCE, "message": {"id": "m1", "model": "fixture-claude-a"}}
            line = json.dumps(entry) + "\n"
            (project / f"{CC_SESSION}.jsonl").write_text(line, encoding="utf-8", newline="\n")
            (subagents / "agent-a01.jsonl").write_text(line, encoding="utf-8", newline="\n")
            (subagents / "agent-a01.meta.json").write_text(json.dumps({"agentType": self.SENTENCE}), encoding="utf-8")
            outputs = self.both("claude-code", CC_SESSION, {"CLAUDE_CONFIG_DIR": tmp})
        for output in outputs:
            self.assertNotIn(MARKER, output)
            self.assertNotIn("sentence", output)
        agents = json.loads(outputs[1])["agents"]
        self.assertEqual([(a["role"], a["role_source"]) for a in agents], [(None, None)] * 2)
        self.assertEqual([pairs(a) for a in agents], [[("fixture-claude-a", None, 1)]] * 2)

    def test_shapes_seen_in_real_records_are_kept(self):
        for name in ("general-purpose", "sprint-coder", "Explore", "fork", "collab_probe_role", "plugin:code-reviewer", "Ada"):
            self.assertEqual(sp._name(name), name)
        for path in ("/root/coder", "/root/live_depth_a/live_depth_b/live_depth_c", "root/a.b-c"):
            self.assertEqual(sp._agent_path(path), path)

    def test_shapes_that_are_not_names(self):
        for value in ("two words", "", "x" * 65, "tab\there", "line\nbreak", "a/b", None, 7, ["coder"]):
            self.assertIsNone(sp._name(value), repr(value))
        for value in ("/root/two words", "", "/", "//", "/root//x", "/root/", "/" + "x" * 120, None, 7):
            self.assertIsNone(sp._agent_path(value), repr(value))


class CodexThreadIdTests(unittest.TestCase):
    def test_file_name_id_wins_over_a_session_meta_that_disagrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            write_rollout(sessions, thread(1))
            # Named for thread 2, but its session_meta says it is thread 1.
            write_rollout(sessions, thread(2), {"id": thread(1), "agent_role": "impostor"}, stamp="09-00-00")
            env = {"CODEX_HOME": tmp}
            code, out, err = run("--json", "codex", thread(1), env=env)
            self.assertEqual((code, err), (0, ""))
            (agent,) = json.loads(out)["agents"]
            self.assertEqual((agent["id"], agent["role"], agent["notes"]), (thread(1), None, []))
            self.assertTrue(agent["record"].endswith(thread(1) + ".jsonl"))

            code, out, _ = run("--json", "codex", thread(2), env=env)
            self.assertEqual(code, 0)
            (agent,) = json.loads(out)["agents"]
            self.assertEqual(agent["id"], thread(2))
            self.assertEqual(len(agent["notes"]), 1)
            self.assertIn("file name", agent["notes"][0])
            code, out, _ = run("codex", thread(2), env=env)
            self.assertIn("note:    session_meta names another thread", out)

    def test_two_rollouts_with_one_id_are_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            first = write_rollout(sessions / "a", thread(1))
            second = write_rollout(sessions / "b", thread(1), stamp="11-00-00")
            write_rollout(sessions, thread(5))
            env = {"CODEX_HOME": tmp}
            for flags in ([], ["--json"]):
                code, out, err = run(*flags, "codex", thread(1), env=env)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("has 2 rollouts", err)
                self.assertIn(first.name, err)
                self.assertIn(second.name, err)
                self.assertNotIn(tmp, err)
            # A duplicate elsewhere does not get in the way of another session.
            self.assertEqual(run("codex", thread(5), env=env)[0], 0)
            # Naming one of the two by path settles it, and says so.
            code, out, err = run("--json", "codex", str(second), env=env)
            self.assertEqual((code, err), (0, ""))
            report = json.loads(out)
            self.assertEqual(report["agents"][0]["record"], f"sessions/b/{second.name}")
            self.assertEqual(len(report["notes"]), 1)
            self.assertIn(first.name, report["notes"][0])

    def test_a_duplicated_child_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            write_rollout(sessions, thread(1))
            write_rollout(sessions / "a", thread(2), {"parent_thread_id": thread(1)})
            write_rollout(sessions / "b", thread(2), {"parent_thread_id": thread(1)})
            code, out, err = run("codex", thread(1), env={"CODEX_HOME": tmp})
        self.assertEqual((code, out), (1, ""))
        self.assertIn(f"thread {thread(2)} has 2 rollouts", err)

    def test_session_meta_far_into_the_file_is_found(self):
        filler = [{"type": "event_msg", "payload": {"n": n}} for n in range(400)]
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            write_rollout(sessions, thread(1))
            write_rollout(sessions, thread(2), {"parent_thread_id": thread(1), "agent_role": "coder"}, before=filler)
            code, out, _ = run("--json", "codex", thread(1), env={"CODEX_HOME": tmp})
        self.assertEqual(code, 0)
        self.assertEqual([(a["id"], a["role"]) for a in json.loads(out)["agents"]], [(thread(1), None), (thread(2), "coder")])

    def test_only_the_first_session_meta_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            path = write_rollout(sessions, thread(1), {"agent_role": "coder"})
            later = {"type": "session_meta", "payload": {"id": thread(9), "agent_role": "other"}}
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(later) + "\n")
            code, out, _ = run("--json", "codex", thread(1), env={"CODEX_HOME": tmp})
        (agent,) = json.loads(out)["agents"]
        self.assertEqual((code, agent["role"], agent["notes"]), (0, "coder", []))


class CodexSearchScopeTests(unittest.TestCase):
    def test_a_file_under_no_sessions_directory_searches_its_own_directory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            root = write_rollout(work, thread(1))
            write_rollout(work, thread(2), {"parent_thread_id": thread(1)})
            write_rollout(work / "below", thread(3), {"parent_thread_id": thread(1)})
            write_rollout(Path(tmp), thread(4), {"parent_thread_id": thread(1)})
            code, out, err = run("--json", "codex", str(root), env={"CODEX_HOME": str(Path(tmp) / "no-home")})
            self.assertEqual((code, err), (0, ""))
            report = json.loads(out)
            self.assertEqual([a["id"] for a in report["agents"]], [thread(1), thread(2)])
            self.assertEqual(len(report["notes"]), 1)
            self.assertIn("own directory only", report["notes"][0])
            self.assertEqual(report["agents"][0]["record"], root.name)
            code, out, _ = run("codex", str(root), env={"CODEX_HOME": str(Path(tmp) / "no-home")})
            self.assertIn("\nnote: the record is under no sessions directory", out)

    def test_a_file_under_a_sessions_directory_gets_no_note(self):
        path = next(CODEX_HOME.rglob(f"*{CX_ROOT}.jsonl"))
        code, out, _ = run("--json", "codex", str(path), env={"CODEX_HOME": str(TESTS / "no-such-home")})
        self.assertEqual((code, json.loads(out)["notes"]), (0, []))


class RobustnessTests(unittest.TestCase):
    DEPTH = 1200

    def test_order_tree_does_not_recurse(self):
        count = sys.getrecursionlimit() * 3
        agents = [{"id": str(n), "parent_id": str(n - 1) if n else None, "depth": 0} for n in range(count)]
        ordered = sp._order_tree(list(reversed(agents)))
        self.assertEqual([a["id"] for a in ordered], [str(n) for n in range(count)])
        self.assertEqual(ordered[-1]["depth"], count - 1)

    def test_order_tree_keeps_sibling_order_and_ends_on_a_cycle(self):
        def agent(me, parent):
            return {"id": me, "parent_id": parent, "depth": 0}

        tree = [agent("r", None), agent("a", "r"), agent("b", "r"), agent("a1", "a"), agent("x", "y"), agent("y", "x")]
        ordered = sp._order_tree(tree)
        self.assertEqual([(a["id"], a["depth"]) for a in ordered], [("r", 0), ("a", 1), ("a1", 2), ("b", 1), ("x", 0), ("y", 1)])

    def test_a_deep_codex_parent_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions"
            for n in range(1, self.DEPTH + 1):
                write_rollout(sessions, thread(n), {"parent_thread_id": thread(n - 1)} if n > 1 else None)
            for flags in ([], ["--json"]):
                code, out, err = run(*flags, "codex", thread(1), env={"CODEX_HOME": tmp})
                self.assertEqual((code, err), (0, ""))
        agents = json.loads(out)["agents"]
        self.assertEqual(len(agents), self.DEPTH)
        self.assertEqual((agents[-1]["id"], agents[-1]["depth"]), (thread(self.DEPTH), self.DEPTH - 1))

    def test_a_deep_claude_parent_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            subagents = Path(tmp) / "projects" / "-p" / CC_SESSION / "subagents"
            subagents.mkdir(parents=True)
            for n in range(1, self.DEPTH + 1):
                (subagents / f"agent-a{n:05d}.jsonl").write_text("{}\n", encoding="utf-8", newline="\n")
                meta = {"agentType": "coder", "parentAgentId": f"a{n - 1:05d}"} if n > 1 else {"agentType": "coder"}
                (subagents / f"agent-a{n:05d}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
            code, out, err = run("--json", "claude-code", CC_SESSION, env={"CLAUDE_CONFIG_DIR": tmp})
        self.assertEqual((code, err), (0, ""))
        agents = json.loads(out)["agents"]
        self.assertEqual((len(agents), agents[-1]["depth"]), (self.DEPTH, self.DEPTH - 1))

    def test_a_very_long_session_argument_is_not_found(self):
        for provider, env in (("codex", {"CODEX_HOME": str(CODEX_HOME)}), ("claude-code", {"CLAUDE_CONFIG_DIR": str(CLAUDE_HOME)})):
            for argument in ("a" * 5000, "a/" * 2500, "a b" * 1700, "nul\x00byte"):
                code, out, err = run(provider, argument, env=env)
                self.assertEqual((code, out), (1, ""), provider)
                self.assertIn("session not found", err)
                self.assertNotIn("Traceback", err)
                self.assertLess(len(err), 300)


class RecordPathTests(unittest.TestCase):
    def test_json_record_is_relative_to_the_provider_home(self):
        report = codex(CX_ROOT)
        self.assertEqual(
            report["agents"][0]["record"], f"sessions/2026/10/01/rollout-2026-10-01T10-00-00-{CX_ROOT}.jsonl"
        )
        report = claude(CC_SESSION)
        self.assertEqual(report["agents"][0]["record"], f"projects/-fixture-project/{CC_SESSION}.jsonl")
        self.assertEqual(
            report["agents"][1]["record"], f"projects/-fixture-project/{CC_SESSION}/subagents/agent-a01.jsonl"
        )

    def test_json_record_outside_the_provider_home_is_the_file_name(self):
        path = next(CODEX_HOME.rglob(f"*{CX_ROOT}.jsonl"))
        code, out, _ = run("--json", "codex", str(path), env={"CODEX_HOME": str(TESTS / "no-such-home")})
        self.assertEqual(code, 0)
        for agent in json.loads(out)["agents"]:
            self.assertNotIn("/", agent["record"])
            self.assertNotIn("\\", agent["record"])

    def test_no_machine_path_in_any_default_output(self):
        root = str(TESTS.parent)
        for flags in ([], ["--json"]):
            for argv, env in (
                (("codex", CX_ROOT), {"CODEX_HOME": str(CODEX_HOME)}),
                (("claude-code", CC_SESSION), {"CLAUDE_CONFIG_DIR": str(CLAUDE_HOME)}),
                (("codex", str(next(CODEX_HOME.rglob(f"*{CX_ROOT}.jsonl")))), {}),
                (("claude-code", str(CLAUDE_HOME / "projects" / "-fixture-project" / f"{CC_SESSION}.jsonl")), {}),
            ):
                code, out, _ = run(*flags, *argv, env=env)
                self.assertEqual(code, 0)
                self.assertNotIn(root, out)
                self.assertNotIn(json.dumps(root)[1:-1], out)

    def test_full_paths(self):
        path = next(CODEX_HOME.rglob(f"*{CX_ROOT}.jsonl")).resolve()
        code, out, _ = run("--json", "--full-paths", "codex", CX_ROOT, env={"CODEX_HOME": str(CODEX_HOME)})
        self.assertEqual((code, json.loads(out)["agents"][0]["record"]), (0, str(path)))
        code, out, _ = run("--full-paths", "codex", CX_ROOT, env={"CODEX_HOME": str(CODEX_HOME)})
        self.assertIn(f"record:  {path}\n", out)


class FixtureHygieneTests(unittest.TestCase):
    def test_sources_are_lf_utf8_without_machine_paths(self):
        files = [SCRIPT, Path(__file__)] + [p for p in FIXTURES.rglob("*") if p.is_file()]
        for path in files:
            data = path.read_bytes()
            self.assertNotIn(b"\r", data, path.name)
            text = data.decode("utf-8")
            # Home directories, WSL drive mounts and drive letters. The patterns are
            # assembled so that this file does not hold what it looks for.
            for pattern in ("/" + "home/", "/" + "mnt/", "/" + "Users/", r"\b[A-Za-z]:" + r"\\"):
                self.assertIsNone(re.search(pattern, text), f"{path.name} matches {pattern!r}")


if __name__ == "__main__":
    unittest.main()
