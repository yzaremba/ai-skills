"""Tests for the check ``discovery``: the readers, on output captured from
Codex CLI 0.160.0 and on shapes written here; and the check, with stub
providers, in every state of every kind of item.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

No real provider is started (R6.8) and no session with a model: ``codex``
and ``claude`` are ``discovery_stub.DiscoveryStub``, found on a PATH that
holds nothing else.
"""
from __future__ import annotations

import json
import os
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import support
from discovery_stub import APP_SERVER, EXEC, PRINT, PROFILE, PROMPT_INPUT, SESSION_MODES, DiscoveryStub
from provider_stub import VERSION
from test_doctor import DoctorCase
from test_validate import OPENAI
from wfsetup import definitions, discovery, doctor, homes

MARKER = "MODEL-OUTPUT-MARKER-7c1f"
INVOKE = "compatibility: claude-code, codex\ndisable-model-invocation: true"

CODEX_SKILLS = ("alpha", "beta")
CODEX_LOADED = ("lead", "quick")
CODEX_AGENTS = ("quick", "reviewer", "runner", "worker", "worker_hard")
CLAUDE_SKILLS = ("alpha", "beta", "solo")
CLAUDE_AGENTS = ("lead", "quick", "reviewer", "runner", "worker", "worker-hard")


def fixture(name: str) -> str:
    return (support.FIXTURES / name).read_text(encoding="utf-8")


def prompt_input(skills=(), instructions: str | None = None) -> str:
    """What ``codex debug prompt-input`` prints, with these skills in its
    model-visible list and these instructions before it."""
    lines = ["<skills_instructions>", "## Skills", "### Skill roots", "- `r0` = `/home/user/.agents/skills`",
             "### Available skills"]
    lines += [f"- {name}: Does {name} work: all of it. (file: r0/{name}/SKILL.md)" for name in skills]
    lines += ["</skills_instructions>"]
    content = [{"type": "input_text", "text": "\n".join(lines)}]
    if instructions is not None:
        content.insert(0, {"type": "input_text", "text": instructions})
    return json.dumps([
        {"type": "message", "role": "developer", "content": content},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": MARKER}]},
    ], indent=2)


def skills_list(skills=(), disabled=()) -> str:
    """The app server's answer to ``skills/list``."""
    listed = [
        {"name": name, "description": MARKER, "enabled": name not in disabled, "scope": "user",
         "path": f"/home/user/.agents/skills/{name}/SKILL.md", "pluginId": None}
        for name in skills
    ]
    answer = {"id": discovery.LIST_REQUEST_ID, "result": {"data": [{"cwd": "/home/user", "errors": [], "skills": listed}]}}
    return json.dumps({"method": "remoteControl/status/changed", "params": {}}) + "\n" + json.dumps(answer) + "\n"


def init_event(**lists) -> str:
    """The first lines of ``claude -p --output-format stream-json``: the
    ``system/init`` event with these lists, after a hook event."""
    event = {"type": "system", "subtype": "init", "session_id": "0000", "cwd": f"/home/{MARKER}", "model": "sonnet",
             "tools": ["Read", "Bash"], "mcp_servers": [{"name": "files", "status": "connected"}],
             "apiKeySource": MARKER, **lists}
    return json.dumps({"type": "system", "subtype": "hook_started", "hook_name": MARKER}) + "\n" + json.dumps(event) + "\n"


def named(names, described: bool = True) -> list:
    return [{"name": name, "description": MARKER, "source": "user"} if described else name for name in names]


REFUSED = json.dumps({"id": discovery.LIST_REQUEST_ID, "error": {"code": -32601, "message": "Method not found"}}) + "\n"
ASSISTANT = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": MARKER}]}}) + "\n"


def events(spawn: str | None = None, extra: dict | None = None) -> str:
    """What ``codex exec --json`` prints: the documented events, and with
    ``spawn`` a definition of the spawn tool whose text is ``spawn``."""
    lines: list[dict] = [{"type": "thread.started", "thread_id": "0000"}, {"type": "turn.started"}]
    if spawn is not None:
        lines.append({"type": "session.configured", "tools": [
            {"type": "function", "name": "exec_command", "description": "Runs a command."},
            {"type": "function", "name": discovery.SPAWN_TOOL, "description": spawn,
             "parameters": {"properties": {"agent_type": {"type": "string", "description": "One of the roles."}}}},
        ]})
    if extra is not None:
        lines.append(extra)
    lines += [
        {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": MARKER}},
        {"type": "turn.completed", "usage": {"input_tokens": 1}},
    ]
    return "".join(json.dumps(line) + "\n" for line in lines)


# --- The readers -------------------------------------------------------------------

class CapturedCase(unittest.TestCase):
    """The readers on what Codex CLI 0.160.0 printed (``fixtures/README.md``)."""

    def test_the_model_visible_list_holds_the_skills_a_model_may_load_and_no_invoke_only_one(self) -> None:
        found = discovery.parse_prompt_input(fixture("codex-prompt-input-0.160.0.json"))
        self.assertEqual(sorted(found.skills), [
            "csv-tools", "epic-implementation", "imagegen", "json-tools", "openai-docs", "prd-implementation",
            "skill-creator", "skill-installer",
        ])
        # Invoke-only, and so not there: no warning says so (PLAN P2.2).
        for name in ("self-reflection", "manager", "product-manager"):
            self.assertNotIn(name, found.skills)
        self.assertEqual(found.skills["csv-tools"], ("r0", "csv-tools/SKILL.md"))
        self.assertEqual(found.roots, {"r0": "/home/user/.agents/skills", "r1": "/home/user/.codex/skills/.system"})
        self.assertEqual(found.unread, 0)
        self.assertEqual(found.roles, ("developer", "developer", "developer", "user", "user"))
        self.assertIn("skills_instructions", found.tags)

    def test_the_prompt_input_holds_no_agent_name_and_no_tool_text(self) -> None:
        text = fixture("codex-prompt-input-0.160.0.json")
        for name in ("coder", "coder_hard", "product_manager", "agent_type"):
            self.assertNotIn(name, text)

    def test_a_profile_shows_the_roles_instructions_and_no_profile_does_not(self) -> None:
        line = definitions.notice_inline("manager")
        with_profile = discovery.parse_prompt_input(fixture("codex-prompt-input-profile-0.160.0.json"))
        self.assertTrue(with_profile.shows(line))
        self.assertTrue(with_profile.shows("# Manager"))
        self.assertEqual(with_profile.texts[0][0], "developer")
        self.assertTrue(with_profile.texts[0][1].startswith(line))
        # A profile that does not exist prints what no profile prints, with exit code 0.
        self.assertFalse(discovery.parse_prompt_input(fixture("codex-prompt-input-0.160.0.json")).shows(line))

    def test_the_app_server_lists_the_invoke_only_skills_too(self) -> None:
        lines = fixture("codex-app-server-skills-list-0.160.0.jsonl").splitlines()
        self.assertEqual([discovery.is_list_answer(line) for line in lines], [False, False, True])
        found = discovery.parse_skills_list(lines)
        names = [one.name for one in found.skills]
        for name in ("csv-tools", "self-reflection", "manager", "product-manager"):
            self.assertIn(name, names)
        self.assertTrue(all(one.enabled for one in found.skills))
        self.assertEqual({one.scope for one in found.skills}, {"user", "system"})
        self.assertEqual(found.errors, 0)
        self.assertEqual(found.named("manager")[0].path, "/home/user/.agents/skills/manager/SKILL.md")

    def test_the_fixtures_name_no_machine(self) -> None:
        for name in ("codex-prompt-input-0.160.0.json", "codex-prompt-input-profile-0.160.0.json",
                     "codex-app-server-skills-list-0.160.0.jsonl"):
            text = fixture(name)
            self.assertNotIn(os.path.expanduser("~"), text)
            self.assertNotIn("scratch", text)


class ReadersCase(unittest.TestCase):
    def test_what_is_not_a_prompt_input_is_said_to_be_none(self) -> None:
        for text, why in (
            ("", "not JSON"), ("codex: please log in", "not JSON"), ('{"models": []}', "not a list of messages"),
            ("[1, 2]", "not a list of messages"), ("[]", "no message text"),
            ('[{"role": "developer", "content": "text"}]', "no message text"),
        ):
            with self.assertRaises(ValueError) as caught:
                discovery.parse_prompt_input(text)
            self.assertIn(why, str(caught.exception))

    def test_a_prompt_with_no_skills_section_has_no_list_and_an_empty_section_an_empty_one(self) -> None:
        none = discovery.parse_prompt_input(json.dumps([{"role": "developer", "content": [{"text": "# Rules"}]}]))
        self.assertIsNone(none.skills)
        self.assertEqual(discovery.parse_prompt_input(prompt_input()).skills, {})

    def test_an_entry_is_read_by_its_name_whatever_its_description_holds(self) -> None:
        body = "\n".join([
            "### Available skills",
            "- alpha: Note: use it (carefully): always. (file: r0/alpha/SKILL.md)",
            "- pack:tool: From a plugin. (file: r1/pack/tool/SKILL.md)",
            "- broken entry with no file",
            "### Something else",
            "- gamma: After the section. (file: r0/gamma/SKILL.md)",
        ])
        found = discovery.parse_prompt_input(json.dumps([{"role": "developer", "content": [{"text": body}]}]))
        self.assertEqual(sorted(found.skills), ["alpha", "pack:tool"])
        self.assertEqual(found.unread, 1)

    def test_lines_that_say_something_was_skipped_are_found(self) -> None:
        self.assertEqual(
            discovery.skipped_lines("ok\nSkipped loading 1 skill(s)\n", "warning: ignoring invalid agent file\n"),
            ["Skipped loading 1 skill(s)", "warning: ignoring invalid agent file"],
        )

    def test_a_skills_list_that_is_none_is_said_to_be_none(self) -> None:
        for lines, why in (
            ([], "no answer"), (["not json", '{"id": 0, "result": {}}'], "no answer"),
            (['{"id": 1, "error": {"code": -32600, "message": "Not initialized"}}'], "refused skills/list: Not initialized"),
            (['{"id": 1, "result": {}}'], "no list"), (['{"id": 1, "result": {"data": [{"cwd": "/x"}]}}'], "no `skills` list"),
            (['{"id": 1, "result": {"data": [{"skills": [{"enabled": true}]}]}}'], "no name"),
        ):
            with self.assertRaises(ValueError) as caught:
                discovery.parse_skills_list(lines)
            self.assertIn(why, str(caught.exception))

    def test_the_init_event_is_found_and_its_lists_are_read_as_names(self) -> None:
        lines = init_event(agents=named(["worker"]), skills=["alpha"], slash_commands=["/beta", "clear"],
                           notes=["a sentence, not a name"], plugins=[]).splitlines()
        self.assertIsNone(discovery.claude_init(lines[0]))
        self.assertIsNone(discovery.claude_init("not json"))
        self.assertIsNone(discovery.claude_init('["system", "init"]'))
        event = discovery.claude_init(lines[1])
        found = discovery.listing_of(event)
        self.assertEqual(found.lists["agents"], ("worker",))
        self.assertEqual(found.lists["tools"], ("Read", "Bash"))
        self.assertEqual(found.lists["mcp_servers"], ("files",))
        self.assertEqual(found.lists["plugins"], ())
        self.assertNotIn("notes", found.lists)
        self.assertNotIn("cwd", found.lists)
        self.assertEqual(found.names(discovery.SKILL_KEYS), {"alpha", "beta", "clear"})
        self.assertEqual(found.names(discovery.AGENT_KEYS), {"worker"})
        self.assertIsNone(discovery.listing_of({"type": "system", "tools": ["Read"]}).names(discovery.AGENT_KEYS))
        self.assertEqual(found.keys, tuple(sorted(event)))

    def test_agent_names_are_read_from_the_spawn_tools_definition_as_whole_names(self) -> None:
        found = discovery.parse_events(events("Roles: worker_hard (hard steps), reviewer.").splitlines())
        self.assertEqual(found.tools, ("exec_command", discovery.SPAWN_TOOL))
        self.assertEqual(found.names(["worker", "worker_hard", "reviewer", "runner"]), {"worker_hard", "reviewer"})
        self.assertIn("description", found.spawn_paths)
        self.assertEqual(found.types[:2], ("thread.started", "turn.started"))
        self.assertIn("item.completed/agent_message", found.types)

    def test_a_call_of_the_spawn_tool_and_what_a_model_wrote_are_not_read(self) -> None:
        call = {"type": "item.completed", "item": {
            "type": "function_call", "name": discovery.SPAWN_TOOL, "description": "worker",
            "arguments": '{"agent_type": "worker"}', "call_id": "c1",
        }}
        found = discovery.parse_events(events(extra=call).splitlines())
        self.assertIsNone(found.spawn)
        self.assertEqual(found.tools, ())
        self.assertEqual(found.names(["worker"]), set())
        message = {"type": "item.completed", "item": {"type": "agent_message", "text": "spawn_agent can use worker"}}
        self.assertIsNone(discovery.parse_events(events(extra=message).splitlines()).spawn)
        with self.assertRaises(ValueError):
            discovery.parse_events(["please log in", ""])


# --- The check ---------------------------------------------------------------------

class DiscoveryCase(DoctorCase):
    """The fixture clone of ``test_doctor`` with ``beta`` made invoke-only,
    rendered into the scratch home. For Codex that is: the skills alpha and
    beta, the loaded roles lead and quick, five role definitions and the
    starting role lead; for Claude Code: three skills, the same loaded
    roles, six definitions and the starting role lead."""

    def setUp(self) -> None:
        super().setUp()
        self.skill("beta", compatibility=INVOKE)
        self.put("beta/agents/openai.yaml", OPENAI)
        patch = mock.patch.object(discovery, "STOP_GRACE", 5.0)
        patch.start()
        self.addCleanup(patch.stop)

    def stubbed(self, name: str) -> DiscoveryStub:
        """The stub of that program, made once for a test. Its app server
        refuses the request until a test gives it an answer, as a server
        that does not know the request would; one that says nothing at all
        is waited for to the time limit."""
        made = self.__dict__.setdefault("_stubbed", {})
        if name not in made:
            made[name] = DiscoveryStub(self.stubs / name, name)
            made[name].answer(APP_SERVER, REFUSED)
        return made[name]

    def instructions(self) -> str:
        return tomllib.loads((self.codex / "lead.config.toml").read_text(encoding="utf-8"))["developer_instructions"]

    def codex_stub(self, visible=("alpha",), listed=CODEX_SKILLS + CODEX_LOADED, disabled=(),
                   profile: bool = True) -> DiscoveryStub:
        """A Codex that lists these skills and shows the profile."""
        stub = self.stubbed("codex")
        stub.answer(PROMPT_INPUT, prompt_input(visible))
        stub.answer(PROFILE, prompt_input(visible, self.instructions() if profile else None))
        stub.answer(APP_SERVER, skills_list(listed, disabled))
        return stub

    def claude_stub(self, text: str | None = None, **how) -> DiscoveryStub:
        stub = self.stubbed("claude")
        if text is None:
            text = init_event(agents=named(CLAUDE_AGENTS), skills=named(CLAUDE_SKILLS + CODEX_LOADED),
                              slash_commands=named(["clear"], described=False))
        stub.answer(PRINT, text, **how)
        return stub

    def discovery(self, *stubs: DiscoveryStub, argv=()) -> tuple[int, list[dict]]:
        self.proving = discovery.PROVE_OPTION in argv
        return self.only("discovery", *argv, host=self.stub_host(*stubs) if stubs else None)

    def state(self, findings: list[dict], provider: str, state: str, *words: str) -> str:
        """The finding of one group of items. An unproven one is a warning
        of its own where proof was asked for (``--prove-discovery``); on a
        plain run it is a part of the one info line (review finding S16)."""
        severity = {discovery.PROVEN: doctor.OK, discovery.UNPROVEN: doctor.WARNING, discovery.MISSING: doctor.ERROR}
        if state == discovery.UNPROVEN and not getattr(self, "proving", False):
            line = self.assertFinding(findings, doctor.INFO, "not proven on this run")
            parts = line.split(f"{provider}: {state}: ")[1:]
            for part in parts:
                if all(word in part for word in words):
                    return part
            self.fail(f"no unproven part of {provider} with {words} in {line}")
        return self.assertFinding(findings, severity[state], f"{provider}: {state}: ", *words)

    def summary(self, findings: list[dict]) -> str:
        return self.assertFinding(findings, doctor.INFO, "asked of the providers")


class OfflineCase(DiscoveryCase):
    def test_codex_proves_skills_loaded_roles_and_the_starting_role_and_starts_no_session(self) -> None:
        self.rendered()
        codex, claude = self.codex_stub(), self.claude_stub()
        code, findings = self.discovery(codex, claude)
        self.assertEqual(code, 0)
        self.state(findings, "codex", discovery.PROVEN, "the skill alpha",
                   "in the model-visible skills list of `codex debug prompt-input <prompt>`")
        self.state(findings, "codex", discovery.PROVEN, "the skill beta", "`skills/list` of `codex app-server",
                   "by design (invoke-only)")
        self.state(findings, "codex", discovery.PROVEN, "2 loaded roles (lead, quick)", "by design (invoke-only)")
        self.state(findings, "codex", discovery.PROVEN, "the starting role lead",
                   "`codex --profile lead debug prompt-input <prompt>` shows the role's instructions")
        self.state(findings, "codex", discovery.UNPROVEN, f"5 role definitions ({', '.join(CODEX_AGENTS)})",
                   "no offline output of Codex lists custom agents", "--prove-discovery")
        for what in ("3 skills (alpha, beta, solo)", "2 loaded roles (lead, quick)",
                     f"6 role definitions ({', '.join(CLAUDE_AGENTS)})", "the starting role lead"):
            self.state(findings, "claude-code", discovery.UNPROVEN, what, "without a session", "--prove-discovery")
        self.assertEqual(self.details(findings, doctor.ERROR), [])
        self.assertIn("22 items asked of the providers: 5 proven, 17 unproven, 0 missing", self.summary(findings))
        self.assertIn("spends quota", self.summary(findings))
        # Review finding S16: on a plain run nothing unproven is a warning,
        # and all of it is one info line.
        self.assertQuiet(findings)
        unproven = [line for line in self.details(findings, doctor.INFO) if "unproven: " in line]
        self.assertEqual(len(unproven), 1, unproven)
        self.assertTrue(unproven[0].startswith("17 items not proven on this run, which started no session: "))
        self.assertEqual(unproven[0].count("unproven: "), 5)
        # The commands started, each with a fixed argument list; no session among them.
        self.assertEqual(codex.calls(), [
            ["debug", "prompt-input", discovery.OFFLINE_PROMPT],
            ["app-server", "--listen", "stdio://"],
            ["--profile", "lead", "debug", "prompt-input", discovery.OFFLINE_PROMPT],
        ])
        self.assertEqual(claude.calls(), [])
        self.assertFalse(set(codex.modes()) & set(SESSION_MODES))

    def test_the_app_server_gets_the_handshake_and_one_request_for_the_working_directory(self) -> None:
        self.rendered()
        codex = self.codex_stub()
        self.discovery(codex)
        sent = codex.requests()
        self.assertEqual([one.get("method") for one in sent], ["initialize", "initialized", "skills/list"])
        self.assertEqual(sent[0]["params"]["clientInfo"]["name"], discovery.CLIENT_NAME)
        self.assertEqual(sent[2]["id"], discovery.LIST_REQUEST_ID)
        self.assertEqual(sent[2]["params"], {"cwds": [str(self.home)], "forceReload": True})

    def test_a_scratch_home_is_the_home_the_provider_is_started_in(self) -> None:
        self.rendered()
        codex = self.codex_stub()
        self.discovery(codex)
        for call in codex.starts():
            self.assertEqual(os.path.normcase(os.path.realpath(call["cwd"])), os.path.normcase(str(self.home)))
            self.assertEqual(call["environ"]["HOME"], str(self.home))
            self.assertEqual(call["environ"]["CODEX_HOME"], str(self.codex))
            self.assertEqual(call["environ"]["CLAUDE_CONFIG_DIR"], str(self.claude))

    def test_with_a_project_the_probes_run_there(self) -> None:
        self.rendered(project=True)
        codex = self.codex_stub()
        self.discovery(codex, argv=self.project_arg)
        self.assertEqual({os.path.normcase(os.path.realpath(call["cwd"])) for call in codex.starts()},
                         {os.path.normcase(str(self.project))})
        self.assertEqual(codex.requests()[2]["params"]["cwds"], [str(self.project)])

    def test_the_real_home_gets_the_callers_environment_untouched(self) -> None:
        context = doctor.Context(self.locations(project=False), None, homes.Host(self.host.side, {"PATH": "x"}, ()))
        self.assertEqual(discovery.child_environment(context)["HOME"], str(self.home))  # a scratch home
        real = mock.Mock(environ={"PATH": "x", "CODEX_HOME": "/elsewhere"}, homes=mock.Mock(scratch=False))
        self.assertEqual(discovery.child_environment(real), {"PATH": "x", "CODEX_HOME": "/elsewhere"})

    def test_an_invoke_only_skill_the_app_server_does_not_answer_for_is_unproven_not_missing(self) -> None:
        self.rendered()
        codex = self.codex_stub()
        for answer, why in ((REFUSED, "refused skills/list: Method not found"), ("", "did not finish within 2 seconds"),
                            ("not json\n", "did not finish within 2 seconds")):
            with self.subTest(why=why), mock.patch.object(discovery, "OFFLINE_TIMEOUT", 2.0):
                codex.answer(APP_SERVER, answer)  # with "": it reads the requests and says nothing
                code, findings = self.discovery(codex)
                self.assertEqual(code, 0)
                self.state(findings, "codex", discovery.PROVEN, "the skill alpha")
                self.state(findings, "codex", discovery.UNPROVEN, "the skill beta", "not provable offline: invoke-only",
                           "by design", why)
                self.state(findings, "codex", discovery.UNPROVEN, "2 loaded roles (lead, quick)",
                           "not provable offline: invoke-only")
                self.assertEqual(self.details(findings, doctor.ERROR), [])
                self.assertIn("2 proven, 8 unproven, 0 missing", self.summary(findings))

    def test_a_skill_absent_from_a_list_that_was_read_is_missing_and_an_error(self) -> None:
        self.rendered()
        code, findings = self.discovery(self.codex_stub(visible=(), listed=("alpha", "beta", "lead"), disabled=("lead",)))
        self.assertEqual(code, 1)
        self.state(findings, "codex", discovery.MISSING, "the skill alpha", "not in the model-visible skills list",
                   "though `skills/list` of `codex app-server --listen stdio://` has it")
        self.state(findings, "codex", discovery.MISSING, "the loaded role lead", "lists it as disabled")
        self.state(findings, "codex", discovery.MISSING, "the loaded role quick", "does not list it")
        self.state(findings, "codex", discovery.PROVEN, "the skill beta")
        self.assertIn("2 proven, 5 unproven, 3 missing", self.summary(findings))

    def test_a_skill_in_neither_list_is_missing(self) -> None:
        self.rendered()
        code, findings = self.discovery(self.codex_stub(visible=("other",), listed=("other",)))
        self.assertEqual(code, 1)
        self.state(findings, "codex", discovery.MISSING, "the skill alpha", "not in the model-visible skills list", "nor in")
        self.state(findings, "codex", discovery.MISSING, "the skill beta", "does not list it")

    def test_a_profile_whose_instructions_are_not_shown_is_missing(self) -> None:
        self.rendered()
        code, findings = self.discovery(self.codex_stub(profile=False))
        self.assertEqual(code, 1)
        self.state(findings, "codex", discovery.MISSING, "the starting role lead",
                   "does not show the role's instructions", "without a word")
        # The instructions of another role are not this role's.
        codex = self.codex_stub()
        codex.answer(PROFILE, prompt_input(("alpha",), self.instructions().replace("roles/lead/", "roles/other/")))
        code, findings = self.discovery(codex)
        self.state(findings, "codex", discovery.MISSING, "the starting role lead")

    def test_output_in_another_shape_leaves_the_items_unproven_with_the_reason(self) -> None:
        self.rendered()
        for text, why in (('{"models": []}', "not a list of messages"), ("please log in\n", "not JSON"),
                          ("", "printed nothing"),
                          (json.dumps([{"role": "developer", "content": [{"text": "# Rules"}]}]), "no skills section")):
            with self.subTest(text=text):
                codex = self.stubbed("codex")
                for mode in (PROMPT_INPUT, PROFILE):
                    codex.answer(mode, text)
                codex.answer(APP_SERVER, '{"id": 1, "result": {"skills": "many"}}\n')
                code, findings = self.discovery(codex)
                self.state(findings, "codex", discovery.UNPROVEN, "the skill alpha", why, "no list in `result.data`")
                self.state(findings, "codex", discovery.UNPROVEN, "the skill beta", "not provable offline: invoke-only")
                if "skills section" in why:
                    # A prompt that was read, and the role's instructions are not in it.
                    self.state(findings, "codex", discovery.MISSING, "the starting role lead")
                    continue
                self.assertEqual(code, 0)
                self.state(findings, "codex", discovery.UNPROVEN, "the starting role lead", why)
                self.assertIn("0 proven, 10 unproven, 0 missing", self.summary(findings))
                self.assertEqual(self.details(findings, doctor.ERROR), [])

    def test_a_command_that_fails_or_does_not_finish_leaves_the_items_unproven(self) -> None:
        self.rendered()
        codex = self.stubbed("codex")
        for mode in (PROMPT_INPUT, PROFILE, APP_SERVER):
            codex.answer(mode, prompt_input(("alpha",)), code=3, stderr="error: not logged in\nmore\n")
        code, findings = self.discovery(codex)
        self.assertEqual(code, 0)
        self.state(findings, "codex", discovery.UNPROVEN, "the skill alpha", "exited with code 3: error: not logged in")
        self.state(findings, "codex", discovery.UNPROVEN, "the starting role lead", "exited with code 3")
        with mock.patch.object(discovery, "OFFLINE_TIMEOUT", 1.0):
            for mode in (PROMPT_INPUT, PROFILE, APP_SERVER):
                codex.answer(mode, prompt_input(("alpha",)), sleep=60)
            before = time.monotonic()
            code, findings = self.discovery(codex)
        self.assertLess(time.monotonic() - before, 45)
        self.assertEqual(code, 0)
        self.state(findings, "codex", discovery.UNPROVEN, "the skill alpha", "did not finish within 1 seconds")
        self.state(findings, "codex", discovery.UNPROVEN, "the starting role lead", "did not finish within 1 seconds")

    def test_what_codex_says_it_skipped_is_a_warning(self) -> None:
        self.rendered()
        codex = self.codex_stub()
        codex.answer(PROMPT_INPUT, prompt_input(("alpha",)), stderr="warning: Skipped loading 1 skill(s) due to invalid SKILL.md\n")
        _, findings = self.discovery(codex)
        self.assertFinding(findings, doctor.WARNING, "codex: `codex debug prompt-input <prompt>` says", "Skipped loading 1")

    def test_a_program_that_is_not_on_path_is_info_and_no_warning(self) -> None:
        self.rendered()
        code, findings = self.discovery()
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        for provider, program in (("codex", "codex"), ("claude-code", "claude")):
            self.assertFinding(findings, doctor.INFO, f"{provider}: the program `{program}` is not on PATH", "skill alpha")
        self.assertFalse(any("asked of the providers" in line for line in self.details(findings, doctor.INFO)))

    def test_a_home_never_rendered_has_nothing_to_prove(self) -> None:
        codex = self.codex_stub_without_home()
        code, findings = self.discovery(codex)
        self.assertEqual(code, 0)
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "nothing that setup installs is in this home")
        self.assertEqual(codex.calls(), [])

    def codex_stub_without_home(self) -> DiscoveryStub:
        stub = self.stubbed("codex")
        stub.answer(PROMPT_INPUT, prompt_input(("alpha",)))
        return stub

    def test_what_is_not_installed_is_said_and_not_asked_for(self) -> None:
        self.rendered()
        os.remove(self.codex_agents / "quick.toml")
        os.remove(self.codex / "lead.config.toml")
        codex = self.stubbed("codex")
        codex.answer(PROMPT_INPUT, prompt_input(("alpha",)))
        codex.answer(APP_SERVER, skills_list(CODEX_SKILLS + CODEX_LOADED))
        code, findings = self.discovery(codex)
        self.assertEqual(code, 0)
        self.assertFinding(findings, doctor.INFO, "not in this home", "codex role definition quick",
                           "codex starting role lead")
        self.state(findings, "codex", discovery.UNPROVEN, "4 role definitions (reviewer, runner, worker, worker_hard)")
        self.assertNotIn(PROFILE, codex.modes())

    def test_a_file_the_provider_cannot_load_is_an_error(self) -> None:
        self.rendered()
        codex, claude = self.codex_stub(), self.claude_stub()
        (self.codex_agents / "quick.toml").write_bytes(b'name = "quick"\ndescription = "x"\n')
        (self.codex_agents / "runner.toml").write_bytes(b"name = [\n")
        (self.codex_agents / "worker.toml").write_bytes(
            b'name = "other"\ndescription = "x"\ndeveloper_instructions = "y"\n')
        os.remove(self.codex_agents / "reviewer.toml")
        (self.codex_agents / "reviewer.toml").mkdir()
        (self.claude_agents / "worker.md").write_bytes(b"no frontmatter here\n")
        (self.claude_agents / "runner.md").write_bytes(b"---\nname: runner\n---\n\nBody.\n")
        os.remove(self.codex_skills / "lead" / "SKILL.md")
        (self.codex / "lead.config.toml").write_bytes(b'model = "x"\n')
        code, findings = self.discovery(codex, claude)
        self.assertEqual(code, 1)
        for words in (
            ("codex: the role definition quick cannot be loaded", "quick.toml", "has no developer_instructions"),
            ("codex: the role definition runner cannot be loaded", "is not valid TOML"),
            ("codex: the role definition worker cannot be loaded", "names the agent other"),
            ("codex: the role definition reviewer cannot be loaded", "not a regular file: a directory is there"),
            ("claude-code: the role definition worker cannot be loaded", "no frontmatter"),
            ("claude-code: the role definition runner cannot be loaded", "has no description in its frontmatter"),
            ("codex: the loaded role lead cannot be loaded", "has no SKILL.md that is a file"),
            ("codex: the starting role lead cannot be loaded", "has no developer_instructions"),
        ):
            self.assertFinding(findings, doctor.ERROR, *words)
        # What can be loaded is still asked for.
        self.state(findings, "codex", discovery.PROVEN, "the loaded role quick")
        self.state(findings, "codex", discovery.UNPROVEN, "the role definition worker_hard")

    def test_broken_sources_are_left_to_the_check_sources(self) -> None:
        self.rendered()
        self.put("alpha/SKILL.md", "no frontmatter\n")
        codex = self.codex_stub()
        code, findings = self.discovery(codex)
        self.assertEqual([found["detail"] for found in findings], [doctor.NOT_PLANNED])
        self.assertEqual(codex.calls(), [])

    def test_the_whole_doctor_runs_the_check_by_default_and_starts_no_session(self) -> None:
        self.rendered()
        codex, claude = self.codex_stub(), self.claude_stub()
        codex.answer(VERSION, "codex-cli 0.160.0\n")
        claude.answer(VERSION, "2.1.289 (Claude Code)\n")
        code, report = self.doctor("--no-model-list", "--no-collab", host=self.stub_host(codex, claude))
        self.assertIn("discovery", [check["name"] for check in report["checks"]])
        self.assertEqual([call for call in claude.calls() if call != ["--version"]], [])
        self.assertFalse(set(codex.modes()) & set(SESSION_MODES))
        self.assertFalse(set(claude.modes()) & set(SESSION_MODES))


class SessionCase(DiscoveryCase):
    PROVE = ("--prove-discovery",)

    def test_each_provider_gets_exactly_one_session_with_fixed_arguments(self) -> None:
        self.rendered()
        codex, claude = self.codex_stub(), self.claude_stub()
        codex.answer(EXEC, events("Agent types: " + ", ".join(CODEX_AGENTS) + "."))
        code, findings = self.discovery(codex, claude, argv=self.PROVE)
        self.assertEqual(code, 0, findings)
        self.assertEqual(claude.calls(), [list(discovery.CLAUDE_SESSION_ARGS)])
        self.assertEqual(claude.calls()[0], [
            "-p", "Reply with the single word ok.", "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--max-turns", "1",
        ])
        self.assertEqual([call for call in codex.calls() if "exec" in call], [list(discovery.CODEX_SESSION_ARGS)])
        self.assertEqual(codex.calls()[-1], [
            "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
            "Reply with the single word ok.",
        ])
        for call in (*claude.starts(), *codex.starts()):
            self.assertEqual(os.path.normcase(os.path.realpath(call["cwd"])), os.path.normcase(str(self.home)))
            self.assertEqual(call["environ"]["CLAUDE_CONFIG_DIR"], str(self.claude))
        init = "the `system/init` event of `claude -p <prompt> --output-format stream-json"
        self.state(findings, "claude-code", discovery.PROVEN, f"6 role definitions ({', '.join(CLAUDE_AGENTS)})",
                   "listed under `agents`", init)
        self.state(findings, "claude-code", discovery.PROVEN, "the starting role lead", "listed under `agents`")
        self.state(findings, "claude-code", discovery.PROVEN, "3 skills (alpha, beta, solo)", "listed under `skills`")
        self.state(findings, "claude-code", discovery.PROVEN, "2 loaded roles (lead, quick)")
        self.state(findings, "codex", discovery.PROVEN, f"5 role definitions ({', '.join(CODEX_AGENTS)})",
                   "named in the spawn_agent tool's text in the event stream of `codex exec --json")
        self.assertIn("22 items asked of the providers: 22 proven, 0 unproven, 0 missing", self.summary(findings))
        self.assertNotIn("spends quota", self.summary(findings))
        self.assertEqual([found["severity"] for found in findings if found["severity"] in ("warning", "error")], [])

    def test_the_claude_session_is_ended_at_its_first_event_and_what_follows_is_not_waited_for(self) -> None:
        self.rendered()
        claude = self.claude_stub(hold=120, tail=ASSISTANT)
        before = time.monotonic()
        code, findings = self.discovery(claude, argv=self.PROVE)
        self.assertLess(time.monotonic() - before, 60)
        self.assertEqual(code, 0)
        self.state(findings, "claude-code", discovery.PROVEN, "the starting role lead")
        self.assertNotIn(MARKER, json.dumps(findings))

    def test_an_event_with_none_of_the_expected_keys_leaves_the_items_unproven_with_the_keys_seen(self) -> None:
        self.rendered()
        claude = self.claude_stub(init_event(plugins=[]))
        code, findings = self.discovery(claude, argv=self.PROVE)
        self.assertEqual(code, 0)
        keys = "its keys were: apiKeySource, cwd, mcp_servers, model, plugins, session_id, subtype, tools, type"
        self.state(findings, "claude-code", discovery.UNPROVEN, "6 role definitions", "no key that lists agents (agents)", keys)
        self.state(findings, "claude-code", discovery.UNPROVEN, "3 skills (alpha, beta, solo)",
                   "no key that lists skills (skills or slash_commands)", keys)
        self.assertIn("0 proven, 12 unproven, 0 missing", self.summary(findings))
        self.assertNotIn(MARKER, json.dumps(findings))

    def test_what_a_key_lists_decides_between_proven_missing_and_unproven(self) -> None:
        self.rendered()
        claude = self.claude_stub(init_event(agents=["lead", "worker"], slash_commands=["/alpha", "/lead", "clear"]))
        code, findings = self.discovery(claude, argv=self.PROVE)
        self.assertEqual(code, 1)
        self.state(findings, "claude-code", discovery.PROVEN, "2 role definitions (lead, worker)", "listed under `agents`")
        self.state(findings, "claude-code", discovery.MISSING, "4 role definitions (quick, reviewer, runner, worker-hard)",
                   "not listed under `agents`")
        self.state(findings, "claude-code", discovery.PROVEN, "the skill alpha", "listed under `slash_commands`")
        self.state(findings, "claude-code", discovery.PROVEN, "the loaded role lead")
        self.state(findings, "claude-code", discovery.MISSING, "the skill solo", "not listed under `slash_commands`")
        # An invoke-only skill that is not listed is not known to be missing.
        self.state(findings, "claude-code", discovery.UNPROVEN, "the skill beta", "it is invoke-only")
        self.state(findings, "claude-code", discovery.UNPROVEN, "the loaded role quick", "it is invoke-only")

    def test_a_claude_session_that_gives_no_event_leaves_the_items_unproven(self) -> None:
        self.rendered()
        for how, why in (
            (dict(text=""), "printed nothing"),
            (dict(text=ASSISTANT), "printed no `system/init` event"),
            (dict(text="Invalid API key\n", code=1, stderr="error: not logged in\n"), "exited with code 1: error: not logged in"),
        ):
            with self.subTest(why=why):
                claude = self.claude_stub(how.pop("text"), **how)
                code, findings = self.discovery(claude, argv=self.PROVE)
                self.assertEqual(code, 0)
                self.state(findings, "claude-code", discovery.UNPROVEN, "3 skills (alpha, beta, solo)", why)
                self.assertNotIn(MARKER, json.dumps(findings))
        with mock.patch.object(discovery, "SESSION_TIMEOUT", 1.0):
            claude = self.claude_stub(init_event(agents=[]), sleep=60)
            code, findings = self.discovery(claude, argv=self.PROVE)
        self.assertEqual(code, 0)
        self.state(findings, "claude-code", discovery.UNPROVEN, "the starting role lead", "did not finish within 1 seconds")

    def test_a_codex_session_with_no_tool_text_leaves_the_definitions_unproven_with_its_events(self) -> None:
        self.rendered()
        codex = self.codex_stub()
        codex.answer(EXEC, events())
        code, findings = self.discovery(codex, argv=self.PROVE)
        self.assertEqual(code, 0)
        self.state(findings, "codex", discovery.UNPROVEN, "5 role definitions", "printed no definition of the spawn_agent tool",
                   "its events were: thread.started, turn.started, item.completed/agent_message, turn.completed")
        self.assertNotIn(MARKER, json.dumps(findings))

    def test_a_codex_session_names_some_definitions_and_not_others(self) -> None:
        self.rendered()
        codex = self.codex_stub()
        codex.answer(EXEC, events("Agent types: worker_hard, quick."))
        code, findings = self.discovery(codex, argv=self.PROVE)
        self.assertEqual(code, 1)
        self.state(findings, "codex", discovery.PROVEN, "2 role definitions (quick, worker_hard)")
        self.state(findings, "codex", discovery.MISSING, "3 role definitions (reviewer, runner, worker)",
                   "not named in the spawn_agent tool's text")

    def test_a_codex_session_that_fails_leaves_the_definitions_unproven(self) -> None:
        self.rendered()
        codex = self.codex_stub()
        for how, why in ((dict(stdout=""), "printed nothing"), (dict(stdout="please log in\n"), "printed no JSON event"),
                         (dict(stdout="", code=1, stderr="error: 401 Unauthorized\n"), "exited with code 1: error: 401")):
            with self.subTest(why=why):
                codex.answer(EXEC, how.pop("stdout"), **how)
                code, findings = self.discovery(codex, argv=self.PROVE)
                self.assertEqual(code, 0)
                self.state(findings, "codex", discovery.UNPROVEN, "5 role definitions", why)
        with mock.patch.object(discovery, "SESSION_TIMEOUT", 1.0):
            codex.answer(EXEC, events(), sleep=60)
            code, findings = self.discovery(codex, argv=self.PROVE)
        self.state(findings, "codex", discovery.UNPROVEN, "5 role definitions", "did not finish within 1 seconds")

    def test_without_the_switch_no_session_is_started_even_with_save_probe(self) -> None:
        self.rendered()
        codex, claude = self.codex_stub(), self.claude_stub()
        saved = self.root / "saved"
        self.discovery(codex, claude, argv=("--save-probe", str(saved)))
        self.assertEqual(claude.calls(), [])
        self.assertFalse(set(codex.modes()) & set(SESSION_MODES))
        self.assertEqual(sorted(os.listdir(saved)),
                         ["codex-profile-lead.json", "codex-prompt-input.json", "codex-skills-list.json"])


class SaveCase(DiscoveryCase):
    def saved(self, *stubs: DiscoveryStub) -> tuple[Path, dict[str, dict], list[dict]]:
        directory = self.root / "probe" / "saved"
        _, findings = self.discovery(*stubs, argv=("--prove-discovery", "--save-probe", str(directory)))
        return directory, {
            file.name: json.loads(file.read_text(encoding="utf-8")) for file in sorted(directory.iterdir())
        }, findings

    def test_only_the_reduced_form_is_saved_and_nothing_a_model_wrote(self) -> None:
        self.rendered()
        codex = self.codex_stub()
        codex.answer(EXEC, events(f"Agent types: worker, quick. {MARKER}"))
        claude = self.claude_stub(
            init_event(agents=named(CLAUDE_AGENTS), skills=named(CLAUDE_SKILLS), slash_commands=["/lead"],
                       notes=[f"a note: {MARKER}"]) + ASSISTANT,
        )
        directory, files, findings = self.saved(codex, claude)
        self.assertEqual(sorted(files), ["claude-code-init.json", "codex-exec-events.json", "codex-profile-lead.json",
                                         "codex-prompt-input.json", "codex-skills-list.json"])
        self.assertFinding(findings, doctor.INFO, "saved, reduced to names", str(directory), "claude-code-init.json")
        # The marker stood in the model's reply, in every description, in a
        # path, in the user prompt and in a list that is no list of names.
        for file in directory.iterdir():
            raw = file.read_bytes()
            self.assertNotIn(MARKER.encode(), raw, file.name)
            self.assertNotIn(b"\r", raw)
            self.assertNotIn(str(self.home).encode(), raw, file.name)
            self.assertNotIn(b"/home/user", raw, file.name)
            self.assertNotIn(discovery.SESSION_PROMPT.encode(), raw, file.name)
            self.assertNotIn(b"Does alpha work", raw, file.name)
            self.assertNotIn(b"roles/lead", raw, file.name)
        init = files["claude-code-init.json"]
        self.assertEqual(sorted(init), ["arguments", "listing", "outcome", "probe", "unread"])
        self.assertEqual(init["arguments"][:2], ["-p", "<prompt>"])
        self.assertEqual(init["listing"]["lists"]["agents"], list(CLAUDE_AGENTS))
        self.assertEqual(init["listing"]["lists"]["slash_commands"], ["/lead"])
        self.assertEqual(init["listing"]["lists"]["tools"], ["Read", "Bash"])
        self.assertNotIn("notes", init["listing"]["lists"])
        self.assertIn("notes", init["listing"]["keys"])
        self.assertEqual(sorted(init["listing"]), ["keys", "lists"])
        exec_events = files["codex-exec-events.json"]["listing"]
        self.assertEqual(exec_events["tool_definitions"], ["exec_command", "spawn_agent"])
        self.assertEqual(exec_events["agent_names_found"], ["quick", "worker"])
        self.assertTrue(exec_events["spawn_tool_found"])
        self.assertIn("description", exec_events["spawn_tool_text_at"])
        self.assertIn("item.completed/agent_message", exec_events["event_types"])
        self.assertEqual(files["codex-prompt-input.json"]["listing"]["skills"], ["alpha"])
        self.assertEqual(files["codex-prompt-input.json"]["listing"]["skill_roots"], ["r0"])
        self.assertEqual(files["codex-skills-list.json"]["listing"]["skills"][0],
                         {"name": "alpha", "enabled": True, "scope": "user"})
        self.assertTrue(files["codex-profile-lead.json"]["listing"]["instructions_shown"])
        self.assertEqual(files["codex-profile-lead.json"]["arguments"],
                         ["--profile", "lead", "debug", "prompt-input", "<prompt>"])

    def test_a_probe_that_gave_nothing_is_saved_as_that(self) -> None:
        self.rendered()
        codex = self.stubbed("codex")
        codex.answer(PROMPT_INPUT, f"please log in {MARKER}\n", code=1, stderr=f"error: {MARKER}\n")
        claude = self.claude_stub(ASSISTANT)
        directory, files, _ = self.saved(codex, claude)
        self.assertIsNone(files["codex-prompt-input.json"]["listing"])
        self.assertEqual(files["codex-prompt-input.json"]["outcome"], "exited with code 1")
        self.assertIsNone(files["claude-code-init.json"]["listing"])
        self.assertEqual(files["claude-code-init.json"]["unread"], "printed no `system/init` event")
        for file in directory.iterdir():
            self.assertNotIn(MARKER.encode(), file.read_bytes(), file.name)

    def test_a_directory_that_cannot_be_made_is_the_checks_error(self) -> None:
        self.rendered()
        blocker = self.root / "file"
        blocker.write_bytes(b"x")
        code, findings = self.discovery(self.codex_stub(), argv=("--save-probe", str(blocker / "inside")))
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, "the check discovery could not be made", "cannot be saved")


class HelpCase(DiscoveryCase):
    def test_the_help_says_which_option_starts_a_session_and_what_is_saved(self) -> None:
        code, out, _ = support.run("doctor", "--help")
        self.assertEqual(code, 0)
        text = " ".join(out.split())
        for words in ("--prove-discovery", "--save-probe DIR", "SPENDS QUOTA", "discovery", "No description, prompt"):
            self.assertIn(words, text)


if __name__ == "__main__":
    unittest.main()
