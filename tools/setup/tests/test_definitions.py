"""Tests for the role definitions ``render`` generates for each provider.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

Every home is a scratch directory. The clone is the fixture clone of
``test_render.RenderCase`` with roles of its own: a role that starts a
session and dispatches (lead), one with a hard profile (worker), one that
may neither edit, run commands nor dispatch (reviewer), one that may not
run commands (runner), one on a model with no effort setting (quick) and
one with no entry point at all (silent). ``RepositoryCase`` renders the
repository's own roles and holds whatever they say.

These tests are about the definitions: they run ``render`` with the parts up
to ``roles`` (``DefinitionsCase.PARTS``). What the ``entry`` part adds, a
loaded role's skill, a starting role's profile and the project level, is in
``test_entry``.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import support
from fileops_support import POSIX, SYMLINKS
from test_render import LINKS, RenderCase, tree
from wfsetup import definitions, dictionary, fileops, fsio, homes, locations, render, roles, validate
from wfsetup.errors import SetupError
from wfsetup.locations import Locations

CLAUDE = "claude-code"
CODEX = "codex"

# A description that YAML cannot take plain: a colon and a space, quotes of
# both kinds, a backslash, a hash after a space, a leading bracket.
ODD = '[Lead]: routes "each" request \\ and # more, it\'s all: yes'

ROLE = """name = "{name}"
title = "{title}"
description = {description}
includes = {includes}

[profile]
tier = "{tier}"
effort = "{effort}"
{hard}
[limits]
edits = {edits}
commands = {commands}
dispatches = {dispatches}

[entry]
dispatch = {dispatch}
load = {load}
start = {start}
"""

HARD = """
[profile.hard]
tier = "deep"
effort = "high"
"""

BINDINGS = """schema_version = 1

[[binding]]
role = "worker"
skill = "alpha"
stage = "stage-1.md"
part = "owns"

[[binding]]
role = "lead"
skill = "alpha"
stage = "stage-1.md"
part = "checks"
note = "Reads the stage and writes nothing."
"""

ALL_FILES = {
    ".claude/agents/lead.md", ".claude/agents/quick.md", ".claude/agents/reviewer.md", ".claude/agents/runner.md",
    ".claude/agents/worker.md", ".claude/agents/worker-hard.md",
    ".codex/agents/quick.toml", ".codex/agents/reviewer.toml", ".codex/agents/runner.toml",
    ".codex/agents/worker.toml", ".codex/agents/worker-hard.toml",
}

_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r"}
_PLAIN = re.compile(r"[A-Za-z][A-Za-z0-9._-]*(?:, [A-Za-z][A-Za-z0-9]*)*")
_WORDS = ("true", "false", "yes", "no", "on", "off", "null", "y", "n")


def yaml_value(raw: str) -> str:
    """One scalar as a strict reader takes it: double-quoted with the
    escapes YAML defines, or plain where plain can be nothing but a string."""
    if not raw.startswith('"'):
        if not _PLAIN.fullmatch(raw) or raw.lower() in _WORDS:
            raise ValueError(f"not a plain string: {raw!r}")
        return raw
    if len(raw) < 2 or not raw.endswith('"'):
        raise ValueError(f"an open quote: {raw!r}")
    out, at, end = [], 1, len(raw) - 1
    while at < end:
        char = raw[at]
        if char == '"':
            raise ValueError(f"a quote inside the string: {raw!r}")
        if char != "\\":
            if ord(char) < 0x20:
                raise ValueError("a control character")
            out.append(char)
            at += 1
            continue
        if at + 1 >= end:
            raise ValueError("an escape with nothing after it")
        code = raw[at + 1]
        if code in _ESCAPES:
            out.append(_ESCAPES[code])
            at += 2
        elif code in "xu":
            width = 2 if code == "x" else 4
            digits = raw[at + 2:at + 2 + width]
            if len(digits) != width or at + 2 + width > end:
                raise ValueError("a short escape")
            out.append(chr(int(digits, 16)))
            at += 2 + width
        else:
            raise ValueError(f"an unknown escape: \\{code}")
    return "".join(out)


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    """The fields of a Claude Code definition, in order, and its body."""
    if not text.startswith("---\n"):
        raise ValueError("no frontmatter")
    head, found, body = text[4:].partition("\n---\n")
    if not found:
        raise ValueError("the frontmatter is not closed")
    fields: dict[str, str] = {}
    lines = head.split("\n")
    # The one nested map a definition may end with, in exactly the form the
    # provider documents: ``experimental:`` and, two spaces in, ``cacheTtl``
    # with a lifetime. It is read as the field ``experimental.cacheTtl``.
    if len(lines) >= 2 and lines[-2] == "experimental:":
        matched = re.fullmatch(r"  cacheTtl: ([0-9]+[mh])", lines[-1])
        if not matched:
            raise ValueError(f"not the cache line of the map: {lines[-1]!r}")
        fields["experimental.cacheTtl"] = matched.group(1)
        lines = lines[:-2]
    nested = dict(fields)
    fields = {}
    for line in lines:
        matched = re.fullmatch(r"([A-Za-z]+): (\S.*)", line)
        if not matched or matched.group(1) in fields:
            raise ValueError(f"not a `key: value` line: {line!r}")
        fields[matched.group(1)] = yaml_value(matched.group(2))
    fields.update(nested)
    return fields, body


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DefinitionsCase(RenderCase):
    ROLES = ()
    # How many of ``render.PARTS`` a run has; None for all of them.
    PARTS: int | None = 3

    def setUp(self) -> None:
        super().setUp()
        if self.PARTS is not None:
            patch = mock.patch.object(render, "PARTS", render.PARTS[:self.PARTS])
            patch.start()
            self.addCleanup(patch.stop)
        for name in ("worker", "lead"):
            shutil.rmtree(self.clone / "roles" / name)
        self.fill(self.clone)
        self.claude_agents = self.claude / "agents"
        self.codex_agents = self.codex / "agents"

    def fill(self, clone: Path) -> None:
        def put(name: str, text: str) -> None:
            file = clone / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(text.encode("utf-8"))

        for provider, text in support.FIXTURE_DICTIONARIES.items():
            put(f"providers/{provider}/dictionary.toml", text)
            put(f"providers/{provider}/actions.md", f"## How actions are done on {provider}\n\n- Dispatch a role.\n")
        put("roles/_shared/brief.md", "## The brief\n\nWork from the brief.\n")
        put("roles/_shared/gates.md", "## Gates\n\nHold the gate.\n")
        put("roles/bindings.toml", BINDINGS)
        self.source(clone, "lead", description=json.dumps(ODD), includes='["gates.md"]', edits="false",
                  dispatches='["worker", "worker-hard"]', dispatch="false", load="true", start="true")
        self.source(clone, "worker", hard=HARD, includes='["brief.md"]')
        self.source(clone, "reviewer", includes='["brief.md", "gates.md"]', edits="false", commands="false")
        self.source(clone, "runner", commands="false", dispatches='["worker"]')
        self.source(clone, "quick", tier="fast")
        self.source(clone, "silent", dispatch="false")

    def source(self, clone: Path, name: str, **changes: str) -> None:
        values = {
            "name": name, "title": name.title(), "description": f'"Does {name} work."', "includes": "[]",
            "tier": "standard", "effort": "medium", "hard": "", "edits": "true", "commands": "true",
            "dispatches": "[]", "dispatch": "true", "load": "false", "start": "false",
        }
        values.update(changes)
        directory = clone / "roles" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "role.toml").write_bytes(ROLE.format(**values).encode("utf-8"))
        (directory / "ROLE.md").write_bytes(f"# {name.title()}\n\nYou are the {name}. Do the work.\n".encode("utf-8"))

    def where(self, project: bool = False) -> Locations:
        return Locations(home=self.home, project=self.project if project else None, clone=self.clone)

    def generated(self, home: Path | None = None) -> dict[str, bytes]:
        """Every file in the two agents directories, by its path in the home."""
        home = home or self.home
        found: dict[str, bytes] = {}
        for directory in (home / ".claude" / "agents", home / ".codex" / "agents"):
            if directory.is_dir():
                for file in sorted(directory.iterdir()):
                    found[file.relative_to(home).as_posix()] = file.read_bytes()
        return found

    def changed_by(self, change) -> set[str]:
        """Render, make ``change``, render again: the files whose bytes differ."""
        self.assertEqual(self.render()[0], 0)
        before = self.generated()
        self.assertEqual(set(before), ALL_FILES)
        change()
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""), out)
        after = self.generated()
        self.assertEqual(set(after), set(before))
        return {name for name in after if after[name] != before[name]}

    def claude_file(self, name: str) -> tuple[dict[str, str], str]:
        return frontmatter((self.claude_agents / f"{name}.md").read_bytes().decode("utf-8"))

    def codex_file(self, name: str) -> dict:
        return tomllib.loads((self.codex_agents / f"{name}.toml").read_bytes().decode("utf-8"))

    def entries(self) -> dict:
        return json.loads(self.manifest_file.read_text(encoding="utf-8"))["entries"]


class FilesCase(DefinitionsCase):
    def test_each_provider_gets_the_definitions_its_entry_flags_ask_for(self) -> None:
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(set(self.generated()), ALL_FILES)
        # A role that only starts a session is an agent file on Claude Code alone.
        self.assertNothingAt(self.codex_agents / "lead.toml")
        # A role with no entry point gives nothing.
        self.assertNothingAt(self.claude_agents / "silent.md")
        self.assertNothingAt(self.codex_agents / "silent.toml")
        self.assertIn("11 files written, 0 removed", out.splitlines()[-1])
        for file in (*self.claude_agents.iterdir(), *self.codex_agents.iterdir()):
            self.assertFalse(os.path.islink(file))
            data = file.read_bytes()
            self.assertNotIn(b"\r", data)
            self.assertTrue(data.endswith(b"\n"))

    def test_the_frontmatter_of_a_claude_code_definition(self) -> None:
        self.render()
        fields, _ = self.claude_file("worker")
        self.assertEqual(list(fields.items()), [
            ("name", "worker"), ("description", "Does worker work."), ("model", "sonnet"), ("effort", "medium"),
            ("disallowedTools", "Agent, Workflow"),
        ])
        hard, _ = self.claude_file("worker-hard")
        self.assertEqual(list(hard.items()), [
            ("name", "worker-hard"), ("description", "The Worker for steps marked hard. Does worker work."),
            ("model", "opus"), ("effort", "high"), ("disallowedTools", "Agent, Workflow"),
        ])
        text = (self.claude_agents / "worker.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith('---\nname: worker\ndescription: "Does worker work."\nmodel: sonnet\n'))
        for name in ("lead", "worker", "worker-hard", "reviewer", "runner", "quick"):
            self.assertNotIn("tools", [key for key in self.claude_file(name)[0] if key != "disallowedTools"])

    def test_the_keys_of_a_codex_definition(self) -> None:
        self.render()
        data = self.codex_file("worker-hard")
        self.assertEqual(list(data), ["name", "description", "model", "model_reasoning_effort", "developer_instructions"])
        self.assertEqual(data["name"], "worker_hard")
        self.assertEqual(data["description"], "The Worker for steps marked hard. Does worker work.")
        self.assertEqual((data["model"], data["model_reasoning_effort"]), ("gpt-6.1-sol", "high"))
        self.assertEqual(self.codex_file("worker")["name"], "worker")
        self.assertEqual(self.codex_file("worker")["model_reasoning_effort"], "medium")

    def test_a_description_that_needs_quoting_reads_back_the_same(self) -> None:
        self.render()
        fields, _ = self.claude_file("lead")
        self.assertEqual(fields["description"], ODD)
        raw = (self.claude_agents / "lead.md").read_text(encoding="utf-8").split("\n")[2]
        self.assertEqual(raw, 'description: "[Lead]: routes \\"each\\" request \\\\ and # more, it\'s all: yes"')
        # The same text through the Codex format.
        self.source(self.clone, "worker", hard=HARD, includes='["brief.md"]', description=json.dumps(ODD))
        self.assertEqual(self.render()[0], 0)
        self.assertEqual(self.codex_file("worker")["description"], ODD)
        self.assertEqual(self.codex_file("worker-hard")["description"], f"The Worker for steps marked hard. {ODD}")

    def test_any_description_text_survives_both_formats(self) -> None:
        for text in ("plain", "- a dash first", "yes", "a: b", "tab\there", "line\nbreak", "é ü   ﻿ \x85 \x7f",
                     "'single'", '"', "\\", "trailing \\", "# hash", "{a: 1}", "100%", "null", "> folded", "|"):
            with self.subTest(text):
                self.assertEqual(yaml_value(definitions.yaml_quoted(text)), text)
                self.assertEqual(yaml_value(definitions.yaml_scalar(text)), text)
                fields = {"name": "x", "role": "x", "description": text, "model": "m", "effort": None}
                made = definitions.claude_code_text(fields, ["A notice."], ["Body."])
                self.assertEqual(frontmatter(made)[0]["description"], text)
                self.assertEqual(tomllib.loads(definitions.codex_text(fields, ["A notice."], ["Body."]))["description"], text)
        for model in ("opus", "gpt-6.1-sol", "claude-opus-5-5"):
            self.assertEqual(definitions.yaml_scalar(model), model)
        for model in ("opus[1m]", "1", "true", "a b"):
            self.assertTrue(definitions.yaml_scalar(model).startswith('"'), model)
            self.assertEqual(yaml_value(definitions.yaml_scalar(model)), model)

    def test_the_strict_reader_refuses_what_is_not_a_string(self) -> None:
        for raw in ("yes", "a: b", "# x", "[a]", '"open', '"a"b"', '"\\q"', "1", "- a", "a #b"):
            with self.subTest(raw):
                with self.assertRaises(ValueError):
                    yaml_value(raw)

    def test_the_limits_of_each_combination(self) -> None:
        self.render()
        denied = {name: self.claude_file(name)[0].get("disallowedTools") for name in ("lead", "reviewer", "runner", "worker")}
        self.assertEqual(denied, {
            "lead": "Edit, Write, NotebookEdit",                                   # edits = false, dispatches some
            "reviewer": "Edit, Write, NotebookEdit, Bash, PowerShell, Monitor, Agent, Workflow",  # nothing allowed
            "runner": "Bash, PowerShell, Monitor",                                 # commands = false, dispatches some
            "worker": "Agent, Workflow",                                           # dispatches = []
        })
        # An empty ``dispatches`` denies every tool that starts an agent:
        # the one that spawns one, and the one that runs a script spawning many.
        self.assertEqual(definitions.DISPATCH_TOOLS, ("Agent", "Workflow"))
        self.assertEqual(definitions.denied_tools({"dispatches": []}), ("Agent", "Workflow"))
        self.assertEqual(definitions.denied_tools({"dispatches": ["worker"]}), ())
        self.assertEqual(self.codex_file("reviewer")["sandbox_mode"], "read-only")
        self.assertEqual(list(self.codex_file("reviewer")), [
            "name", "description", "model", "model_reasoning_effort", "sandbox_mode", "developer_instructions",
        ])
        for name in ("runner", "worker", "worker-hard", "quick"):
            self.assertNotIn("sandbox_mode", self.codex_file(name))

    def test_a_role_with_no_limit_denies_nothing(self) -> None:
        self.assertEqual(definitions.denied_tools({"edits": True, "commands": True, "dispatches": ["worker"]}), ())
        self.assertEqual(definitions.denied_tools({}), ())
        self.source(self.clone, "runner", dispatches='["worker"]')
        self.render()
        self.assertEqual(list(self.claude_file("runner")[0]), ["name", "description", "model", "effort"])

    def test_no_effort_is_written_for_a_model_that_takes_none(self) -> None:
        self.render()
        fields, _ = self.claude_file("quick")
        self.assertEqual(list(fields.items()), [
            ("name", "quick"), ("description", "Does quick work."), ("model", "haiku"),
            ("disallowedTools", "Agent, Workflow"),
        ])
        # The Codex model of the same tier takes one.
        self.assertEqual(self.codex_file("quick")["model_reasoning_effort"], "medium")
        self.write(self.user_file, '[providers.codex.tiers]\nfast = "gpt-unlisted"\n')
        self.assertEqual(self.render()[0], 0)
        self.assertEqual(self.codex_file("quick")["model_reasoning_effort"], "medium")  # unlisted: unchecked, kept

    def test_the_body_is_the_notice_the_role_its_includes_its_bindings_and_the_actions(self) -> None:
        self.render()
        _, body = self.claude_file("reviewer")
        self.assertEqual(body, "\n" + roles.join_text([
            "<!--\n" + "\n".join(definitions.notice_lines(CLAUDE, "reviewer", "reviewer")) + "\n-->",
            "# Reviewer\n\nYou are the reviewer. Do the work.",
            "## The brief\n\nWork from the brief.",
            "## Gates\n\nHold the gate.",
            definitions.bindings_section([], "~/anywhere"),
            "## How actions are done on claude-code\n\n- Dispatch a role.",
        ]))
        instructions = self.codex_file("reviewer")["developer_instructions"]
        self.assertEqual(instructions, roles.join_text([
            definitions.notice_inline("reviewer"),
            "# Reviewer\n\nYou are the reviewer. Do the work.",
            "## The brief\n\nWork from the brief.",
            "## Gates\n\nHold the gate.",
            definitions.bindings_section([], "~/anywhere"),
            "## How actions are done on codex\n\n- Dispatch a role.",
        ]))
        # What validation measured is in the file as measured.
        measured = roles.join_text([
            "# Reviewer\n\nYou are the reviewer. Do the work.\n", "## The brief\n\nWork from the brief.\n",
            "## Gates\n\nHold the gate.\n",
        ])
        sizes = validate.check(self.where()).role_sizes
        self.assertEqual(sizes["reviewer"], len(measured.encode("utf-8")))
        self.assertIn(measured.rstrip("\n") + "\n\n## Your bindings", body)
        self.assertIn(measured.rstrip("\n") + "\n\n## Your bindings", instructions)

    def test_the_notice_names_the_source_and_breaks_neither_format(self) -> None:
        self.render()
        text = (self.claude_agents / "worker-hard.md").read_text(encoding="utf-8")
        _, body = frontmatter(text)
        self.assertTrue(body.startswith("\n<!--\nGenerated by workflow setup for the definition worker-hard of the role worker. Do not edit"))
        comment = body[body.index("<!--") + 4:body.index("-->")]
        self.assertNotIn("--", comment)
        self.assertIn("roles/worker/ (ROLE.md, role.toml)", comment)
        self.assertIn("providers/claude-code/actions.md", comment)
        self.assertIn("run `python tools/setup/workflow_setup.py render`", comment)
        self.assertEqual(body.count("<!--"), 1)

        raw = (self.codex_agents / "worker-hard.toml").read_text(encoding="utf-8")
        head = raw.split("\n\n", 1)[0].split("\n")
        self.assertEqual(head, [f"# {line}" for line in definitions.notice_lines(CODEX, "worker", "worker-hard")])
        self.assertIn("providers/codex/actions.md", head[1])
        instructions = self.codex_file("worker-hard")["developer_instructions"]
        self.assertTrue(instructions.startswith(
            "[This text is generated by workflow setup from roles/worker/ of the skills repository."
        ))
        self.assertIn('developer_instructions = """\n[This text is generated', raw)

    def test_the_binding_rows_reach_the_right_roles_and_the_hard_definition(self) -> None:
        self.render()
        owns = "In `~/.claude/skills/alpha/references/`:\n\n- `stage-1.md`, part `owns`.\n"
        codex_owns = "In `~/.agents/skills/alpha/references/`:\n\n- `stage-1.md`, part `owns`.\n"
        said = "The part `owns` is everything the stage file asks of whoever runs the stage."
        checks = "In `~/.claude/skills/alpha/references/`:\n\n- `stage-1.md`, part `checks`: Reads the stage and writes nothing."
        for name in ("worker", "worker-hard"):
            body = self.claude_file(name)[1]
            self.assertIn("## Your bindings\n\nEach row binds you to one stage file", body)
            self.assertIn(owns, body)
            # What `owns` means is said once, in the paragraph above the rows.
            self.assertEqual(body.count(said), 1)
            self.assertNotIn(checks, body)
            self.assertIn(codex_owns, self.codex_file(name)["developer_instructions"])
        self.assertIn(checks, self.claude_file("lead")[1])
        self.assertNotIn(owns, self.claude_file("lead")[1])
        self.assertNotIn(said, self.claude_file("lead")[1])
        for name in ("reviewer", "runner", "quick"):
            self.assertIn("## Your bindings\n\nNone: no stage file of the process skills is bound to you.", self.claude_file(name)[1])
            self.assertNotIn("stage-1.md", self.codex_file(name)["developer_instructions"])

    def test_a_role_is_told_where_the_skills_are_installed(self) -> None:
        self.render()
        for name in ("worker", "worker-hard", "lead"):
            self.assertIn("\n\nIn `~/.claude/skills/alpha/references/`:\n\n- `stage-1.md`, part `", self.claude_file(name)[1])
        self.assertIn(
            "\n\nIn `~/.agents/skills/alpha/references/`:\n\n- `stage-1.md`, part `owns`.",
            self.codex_file("worker")["developer_instructions"],
        )
        # A role with no row is told of no directory: it reads no stage file.
        self.assertNotIn("/skills/", self.claude_file("reviewer")[1])
        where = self.where()
        self.assertEqual(definitions.skills_place(where, CLAUDE), "~/.claude/skills")
        self.assertEqual(definitions.skills_place(where, CODEX), "~/.agents/skills")

    def moved_run(self, **variables: Path) -> tuple[homes.Homes, render.Outcome]:
        """A run of render as the command makes it for the user's own home,
        with the providers' variables set: ``render.execute`` on the homes
        resolved for a host that has them. ``Host.current`` is not replaced:
        what a file says of the home must come from the run's own homes."""
        host = homes.Host(self.host.side, {"PATH": "", **{name: str(path) for name, path in variables.items()}}, ())
        where = dataclasses.replace(self.where(), real_home=True)
        found = homes.resolve(where, host)
        self.assertFalse(found.scratch)
        sources = validate.require(where)
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.fail("the host was read again"))):
            outcome = render.execute(found, sources)
        self.assertEqual((outcome.code, outcome.errors), (0, []))
        return found, outcome

    def test_a_home_that_a_variable_moved_is_named_in_full(self) -> None:
        moved = self.root / "moved" / "claude-home"
        moved.mkdir(parents=True)
        found, _ = self.moved_run(CLAUDE_CONFIG_DIR=moved)
        self.assertEqual(found.provider(CLAUDE).home, moved)
        # The skills are linked into the moved home, and that is the directory a role is told.
        self.assertTrue(fsio.is_file(moved / "skills" / "alpha" / "SKILL.md"))
        text = (moved / "agents" / "worker.md").read_bytes().decode("utf-8")
        self.assertIn(f"\n\nIn `{(moved / 'skills').as_posix()}/alpha/references/`:\n\n- `stage-1.md`, part `owns`.", text)
        self.assertNotIn("~/.claude/skills", text)
        # Nothing went to the home's default place.
        self.assertEqual(os.listdir(self.claude), [])
        # Codex reads the user's skills beside its home, wherever that home is.
        self.assertIn("\n\nIn `~/.agents/skills/alpha/references/`:\n\n- `stage-1.md`, part `owns`.",
                      self.codex_file("worker")["developer_instructions"])
        self.assertEqual(definitions.skills_place(self.where(), CLAUDE, found), (moved / "skills").as_posix())
        self.assertEqual(definitions.skills_place(self.where(), CODEX, found), "~/.agents/skills")
        # A scratch home reads no variable.
        self.assertEqual(definitions.skills_place(self.where(), CLAUDE), "~/.claude/skills")

    def test_a_codex_home_that_a_variable_moved_keeps_the_skills_beside_the_users_home(self) -> None:
        moved = self.root / "moved" / "codex-home"
        moved.mkdir(parents=True)
        found, _ = self.moved_run(CODEX_HOME=moved)
        self.assertEqual(found.provider(CODEX).home, moved)
        text = tomllib.loads((moved / "agents" / "worker.toml").read_bytes().decode("utf-8"))["developer_instructions"]
        self.assertIn("\n\nIn `~/.agents/skills/alpha/references/`:\n\n- `stage-1.md`, part `owns`.", text)
        self.assertTrue(fsio.is_file(self.codex_skills / "alpha" / "SKILL.md"))
        self.assertNotIn(str(moved), text)
        self.assertNotIn(moved.as_posix(), text)

    def test_a_home_moved_inside_the_users_home_is_named_from_the_tilde(self) -> None:
        moved = self.home / "config" / "claude"
        moved.mkdir(parents=True)
        self.moved_run(CLAUDE_CONFIG_DIR=moved)
        text = (moved / "agents" / "worker.md").read_bytes().decode("utf-8")
        self.assertIn("\n\nIn `~/config/claude/skills/alpha/references/`:\n\n", text)
        self.assertNotIn(self.home.as_posix(), text)

    def test_the_skills_directory_is_in_the_digest_of_a_role_with_rows(self) -> None:
        moved = self.root / "moved" / "claude-home"
        moved.mkdir(parents=True)
        found, _ = self.moved_run(CLAUDE_CONFIG_DIR=moved)
        there = definitions.digests(self.where(), homes_found=found)
        here = definitions.digests(self.where())
        # worker and lead have a row, and with it the directory in their text.
        self.assertEqual({key for key in here if here[key] != there[key]},
                         {(CLAUDE, "worker"), (CLAUDE, "worker-hard"), (CLAUDE, "lead")})
        record = fileops.read_record(found.roots())
        recorded = {entry["inputs"] for entry in record.entries.values() if entry.get("kind") == "file"}
        self.assertEqual(recorded, set(there.values()))

    def test_a_part_without_a_note_points_at_the_stage_file(self) -> None:
        section = definitions.bindings_section([
            definitions.Binding("r", "alpha", "s.md", "implementer"),
            definitions.Binding("r", "alpha", "t.md", "owns", "And the index."),
        ], "~/some/skills")
        self.assertIn("\n\nIn `~/some/skills/alpha/references/`:\n\n- `s.md`, part `implementer`: ", section)
        self.assertIn("one stage file of an installed process skill and names your part in it.", section)
        # Every role with a row is told here to read its stage file first.
        self.assertIn("Read the file before you act on it, and take no part in a stage with no row here.", section)
        self.assertIn("A skill's scripts are in `scripts/`, beside `references/`.", section)
        self.assertIn("part `implementer`: the part the stage file defines under that name.", section)
        self.assertIn("part `owns`: And the index.", section)
        self.assertEqual(section.count("The part `owns` is everything the stage file asks of whoever runs the stage."), 1)

    def test_a_skills_directory_is_named_once_above_its_rows(self) -> None:
        section = definitions.bindings_section([
            definitions.Binding("r", "alpha", "s.md", "implementer"),
            definitions.Binding("r", "beta", "u.md", "owns"),
            definitions.Binding("r", "alpha", "t.md", "owns", "And the index."),
        ], "~/some/skills")
        # The skills in the order of their first row, each skill's rows in the table's order.
        self.assertTrue(section.endswith(
            "\n\nIn `~/some/skills/alpha/references/`:\n\n"
            "- `s.md`, part `implementer`: the part the stage file defines under that name.\n"
            "- `t.md`, part `owns`: And the index.\n\n"
            "In `~/some/skills/beta/references/`:\n\n"
            "- `u.md`, part `owns`."
        ), section)
        self.assertEqual(section.count("~/some/skills"), 2)

    def test_the_report_gives_each_definition_its_size_model_and_effort(self) -> None:
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        listed = {(found["provider"], found["file"]): found for found in report["definitions"]}
        self.assertEqual(len(listed), 11)
        for (provider, name), found in listed.items():
            file = (self.claude_agents if provider == CLAUDE else self.codex_agents) / name
            self.assertEqual(found["bytes"], len(file.read_bytes()))
            self.assertEqual(found["status"], render.CREATE)
        self.assertEqual(
            (listed[(CLAUDE, "quick.md")]["model"], listed[(CLAUDE, "quick.md")]["effort"]), ("haiku", None)
        )
        self.assertEqual(listed[(CODEX, "worker-hard.toml")]["definition"], "worker-hard")
        self.assertEqual(listed[(CODEX, "worker-hard.toml")]["role"], "worker")
        self.assertEqual(self.items(report, CLAUDE, "agents")["lead.md"], render.CREATE)
        self.assertEqual(report["counts"]["file_write"], 11)
        self.assertEqual(report["counts"]["create"], 6)  # the links are counted apart

        code, out, _ = self.render()
        size = len((self.claude_agents / "quick.md").read_bytes())
        self.assertIn(f"    quick.md: up to date: as generated ({size:,} bytes; model haiku, no effort setting)", out.splitlines())
        size = len((self.codex_agents / "worker.toml").read_bytes())
        self.assertIn(f"    worker.toml: up to date: as generated ({size:,} bytes; model gpt-6.1-sol, effort medium)", out.splitlines())

    def test_help_states_the_options_and_the_rule(self) -> None:
        code, out, _ = support.run("render", "--help")
        flat = " ".join(out.split())
        self.assertEqual(code, 0)
        for text in ("--no-roles", "--overwrite-edited", "installs the process alone", "<role>-hard",
                     "Edit, Write, NotebookEdit; Bash, PowerShell, Monitor; Agent", "read-only sandbox",
                     "one generated file, key or block was kept that --overwrite-edited would replace"):
            self.assertIn(text, flat)


class StableCase(DefinitionsCase):
    def test_a_second_run_writes_nothing(self) -> None:
        self.assertEqual(self.render()[0], 0)
        before = tree(self.root)
        code, report, err = self.report()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.root), before)
        self.assertEqual((report["plan"], report["changed"]), ([], False))
        self.assertEqual(report["counts"]["file_up_to_date"], 11)
        self.assertEqual(report["counts"]["file_write"], 0)
        self.assertEqual({found["status"] for found in report["definitions"]}, {render.UP_TO_DATE})
        code, out, _ = self.render()
        self.assertTrue(out.splitlines()[-1].startswith(f"{fileops.UP_TO_DATE}; nothing was written"))
        self.assertEqual(tree(self.root), before)

    def test_a_dry_run_writes_nothing_and_says_what_it_would(self) -> None:
        before = tree(self.root)
        code, out, err = self.render("--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.root), before)
        self.assertIn("  create file home:.codex/agents/worker-hard.toml", out.splitlines())
        self.assertEqual(
            out.splitlines()[-1],
            "dry run: would create 6 links and remove 0, write 11 files and remove 0; nothing was written; 2 skipped "
            "(each is listed as skipped, with the reason)",
        )

    def test_two_clone_paths_give_the_same_bytes(self) -> None:
        self.assertEqual(self.render()[0], 0)
        other_clone = self.root / "elsewhere" / "a longer name" / "clone-two"
        shutil.copytree(self.clone, other_clone)
        other_home = self.root / "second-home"
        (other_home / ".claude").mkdir(parents=True)
        (other_home / ".codex").mkdir()
        with mock.patch.object(locations, "CLONE", other_clone), \
                mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            code, _, err = support.run("render", "--home", str(other_home))
        self.assertEqual((code, err), (0, ""))
        first, second = self.generated(), self.generated(other_home)
        self.assertEqual(set(first), ALL_FILES)
        self.assertEqual(first, second)
        for name, data in first.items():
            for machine in (str(self.root), self.root.as_posix(), self.root.name, "clone-two", "fake-clone"):
                self.assertNotIn(machine.encode("utf-8"), data, name)
        # The record's digests are the same too, and hold no path.
        mine = self.entries()
        theirs = json.loads((other_home / ".agents/workflow-setup/manifest.json").read_text(encoding="utf-8"))["entries"]
        for key in (f"home:{name}" for name in ALL_FILES):
            self.assertEqual(mine[key], theirs[key])

    def test_a_crlf_checkout_gives_the_same_bytes_and_the_same_digest(self) -> None:
        self.assertEqual(self.render()[0], 0)
        before, digests = self.generated(), definitions.digests(self.where())
        for file in (self.clone / "roles/worker/ROLE.md", self.clone / "roles/_shared/brief.md",
                     self.clone / "providers/codex/actions.md", self.clone / "roles/worker/role.toml"):
            file.write_bytes(b"\xef\xbb\xbf" + file.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(definitions.digests(self.where()), digests)
        code, report, _ = self.report()
        self.assertEqual((code, report["plan"]), (0, []))
        self.assertEqual(self.generated(), before)

    def test_the_reversal_restores_the_home_byte_for_byte(self) -> None:
        self.keep(self.claude / "CLAUDE.md")
        self.keep(self.claude_agents / "mine.md")
        self.keep(self.codex / "config.toml", 'model = "x"\n')
        self.write(self.user_file, '[roles.worker]\ntier = "deep"\n')
        home_before, clone_before = tree(self.home), tree(self.clone)
        self.assertEqual(self.render()[0], 0)
        self.assertNotEqual(tree(self.home), home_before)
        roots = self.roots()
        result = fileops.plan_reversal(roots).apply()
        self.assertEqual(result.kept, [])
        self.assertTrue(fileops.remove_state(roots))
        self.assertEqual(tree(self.home), home_before)
        self.assertEqual(tree(self.clone), clone_before)


class DependsCase(DefinitionsCase):
    """A change reaches exactly the definitions made from what changed."""

    def test_a_roles_text(self) -> None:
        file = self.clone / "roles/worker/ROLE.md"
        changed = self.changed_by(lambda: file.write_bytes(file.read_bytes() + b"\nOne more line.\n"))
        self.assertEqual(changed, {
            ".claude/agents/worker.md", ".claude/agents/worker-hard.md",
            ".codex/agents/worker.toml", ".codex/agents/worker-hard.toml",
        })

    def test_an_include(self) -> None:
        file = self.clone / "roles/_shared/gates.md"
        changed = self.changed_by(lambda: file.write_bytes(b"## Gates\n\nHold every gate.\n"))
        self.assertEqual(changed, {".claude/agents/lead.md", ".claude/agents/reviewer.md", ".codex/agents/reviewer.toml"})

    def test_a_binding_row(self) -> None:
        file = self.clone / "roles/bindings.toml"
        changed = self.changed_by(lambda: file.write_bytes(file.read_bytes().replace(b"writes nothing", b"writes a note")))
        self.assertEqual(changed, {".claude/agents/lead.md"})

    def test_a_new_binding_row_for_a_role_with_a_hard_definition(self) -> None:
        file = self.clone / "roles/bindings.toml"
        row = b'\n[[binding]]\nrole = "worker"\nskill = "beta"\nstage = "stage-2.md"\npart = "owns"\n'

        def add() -> None:
            # Together: a stage file with no row is a fault of the sources.
            (self.clone / "beta/references").mkdir()
            (self.clone / "beta/references/stage-2.md").write_bytes(b"# Stage 2\n")
            file.write_bytes(file.read_bytes() + row)

        changed = self.changed_by(add)
        self.assertEqual(changed, {
            ".claude/agents/worker.md", ".claude/agents/worker-hard.md",
            ".codex/agents/worker.toml", ".codex/agents/worker-hard.toml",
        })

    def test_a_providers_action_notes(self) -> None:
        file = self.clone / "providers/codex/actions.md"
        changed = self.changed_by(lambda: file.write_bytes(file.read_bytes() + b"- Follow up.\n"))
        self.assertEqual(changed, {name for name in ALL_FILES if name.startswith(".codex/")})

    def test_a_limit_in_role_toml(self) -> None:
        changed = self.changed_by(lambda: self.source(self.clone, "runner", commands="false", edits="false", dispatches='["worker"]'))
        self.assertEqual(changed, {".claude/agents/runner.md", ".codex/agents/runner.toml"})

    def test_a_user_level_override_of_one_roles_tier_changes_that_roles_files_only(self) -> None:
        """R8.3, at the user level."""
        self.assertEqual(self.render()[0], 0)
        hashes = {key: entry.get("sha256") for key, entry in self.entries().items()}
        changed = self.changed_by(lambda: self.write(self.user_file, '[roles.worker]\ntier = "frontier"\n'))
        self.assertEqual(changed, {".claude/agents/worker.md", ".codex/agents/worker.toml"})
        self.assertEqual(self.claude_file("worker")[0]["model"], "fable")
        self.assertEqual(self.codex_file("worker")["model"], "gpt-6-astra")
        self.assertEqual(self.claude_file("worker-hard")[0]["model"], "opus")  # the hard definition is its own
        after = {key: entry.get("sha256") for key, entry in self.entries().items()}
        self.assertEqual(
            {key for key in after if after[key] != hashes[key]},
            {"home:.claude/agents/worker.md", "home:.codex/agents/worker.toml"},
        )
        for key in changed:
            self.assertEqual(after[f"home:{key}"], digest((self.home / key).read_bytes()))

    def test_a_model_named_for_one_definition_on_one_provider(self) -> None:
        text = '[providers.codex.role_models]\nworker-hard = "gpt-6-astra"\n'
        self.assertEqual(self.changed_by(lambda: self.write(self.user_file, text)), {".codex/agents/worker-hard.toml"})

    def test_an_effort_override(self) -> None:
        changed = self.changed_by(lambda: self.write(self.user_file, '[roles.quick]\neffort = "high"\n'))
        # The Claude Code model of that tier takes no effort: its file is the same.
        self.assertEqual(changed, {".codex/agents/quick.toml"})

    def test_a_project_override_changes_that_roles_definitions_only(self) -> None:
        """R8.3, at the project level: the home's files do not move, and the
        definitions built for the project differ in that role alone."""
        self.assertEqual(self.render()[0], 0)
        before, record = self.generated(), self.manifest_file.read_bytes()
        self.write(self.project_file, '[roles.worker]\ntier = "frontier"\n')
        code, report, err = self.report("--project", str(self.project))
        self.assertEqual((code, err, report["plan"]), (0, "", []))
        self.assertEqual(self.generated(), before)
        self.assertEqual(self.manifest_file.read_bytes(), record)

        user = {(found.provider, found.definition): found for found in definitions.build(self.where())}
        project = {(found.provider, found.definition): found for found in definitions.build(self.where(project=True))}
        self.assertEqual(set(user), set(project))
        self.assertEqual({key for key in user if user[key].text != project[key].text}, {(CLAUDE, "worker"), (CODEX, "worker")})
        self.assertEqual({key for key in user if user[key].inputs != project[key].inputs}, {(CLAUDE, "worker"), (CODEX, "worker")})
        for key, found in user.items():
            if key[1] != "worker":
                self.assertEqual(found.sha256, project[key].sha256)
        self.assertEqual(project[(CLAUDE, "worker")].model, "fable")
        # The text built for the home is what is in the home.
        for (provider, _), found in user.items():
            directory = ".claude/agents" if provider == CLAUDE else ".codex/agents"
            self.assertEqual(found.text.encode("utf-8"), before[f"{directory}/{found.name}"])
        self.assertEqual(definitions.user_level(self.where(project=True)), self.where())

    def test_an_unrelated_change_changes_nothing(self) -> None:
        def change() -> None:
            (self.clone / "roles/README.md").write_bytes(b"# Roles\n\nMore.\n")
            (self.clone / "roles/silent/ROLE.md").write_bytes(b"# Silent\n\nOther text.\n")
            (self.clone / "providers/acme/actions.md").write_bytes(b"## Other\n\n- Other.\n")
            self.write(self.user_file, '[roles.silent]\ntier = "deep"\n[process]\ndocs_dir = "documents"\n')

        self.assertEqual(self.changed_by(change), set())


class DigestCase(DefinitionsCase):
    def test_the_recorded_inputs_are_recomputed_without_writing(self) -> None:
        self.write(self.user_file, '[roles.worker]\ntier = "deep"\n')
        self.assertEqual(self.render()[0], 0)
        entries = self.entries()
        before = tree(self.root)
        found = definitions.digests(self.where())
        self.assertEqual(tree(self.root), before)
        self.assertEqual(len(found), 11)
        for (provider, definition), inputs in found.items():
            directory = ".claude/agents" if provider == CLAUDE else ".codex/agents"
            entry = entries[f"home:{directory}/{definitions.file_name(provider, definition)}"]
            self.assertEqual(entry["inputs"], inputs)
            self.assertEqual(entry["kind"], "file")
            self.assertEqual(entry["sha256"], digest((self.home / directory / definitions.file_name(provider, definition)).read_bytes()))
            self.assertTrue(inputs.startswith(definitions.INPUTS_SCHEME + ":"))
            self.assertRegex(inputs, rf"^render:role-definition:{definitions.FORMAT}:[0-9a-f]{{64}}$")
        # The text for the same inputs changed with the tools denied for an
        # empty ``dispatches``, so the format number did.
        # 4: the section "Your bindings" says where the skills are installed.
        # 5: it names each skill's directory once, above that skill's rows.
        # 6: the skills directory is that of the run's homes, and is in the digest.
        self.assertEqual(definitions.FORMAT, 6)
        self.assertTrue(definitions.INPUTS_SCHEME.startswith(render.GENERATED_PREFIX))
        self.assertEqual(len(set(found.values())), 11)

    def test_a_changed_source_shows_as_drift_in_the_digests_of_its_dependents(self) -> None:
        self.assertEqual(self.render()[0], 0)
        recorded = definitions.digests(self.where())
        (self.clone / "roles/_shared/brief.md").write_bytes(b"## The brief\n\nWork from the brief alone.\n")
        before = tree(self.root)
        now = definitions.digests(self.where())
        self.assertEqual(tree(self.root), before)
        self.assertEqual(
            {key for key in now if now[key] != recorded[key]},
            {(CLAUDE, "worker"), (CLAUDE, "worker-hard"), (CLAUDE, "reviewer"),
             (CODEX, "worker"), (CODEX, "worker-hard"), (CODEX, "reviewer")},
        )
        self.write(self.user_file, '[providers.claude-code.tiers]\nfast = "sonnet"\n')
        later = definitions.digests(self.where())
        self.assertEqual({key for key in later if later[key] != now[key]}, {(CLAUDE, "quick")})

    def test_a_comment_in_role_toml_is_an_input_and_changes_no_byte(self) -> None:
        self.assertEqual(self.render()[0], 0)
        before = self.generated()
        hashes = {key: entry["inputs"] for key, entry in self.entries().items() if entry["kind"] == "file"}
        file = self.clone / "roles/runner/role.toml"
        file.write_bytes(b"# A comment.\n" + file.read_bytes())
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(report["plan"], ["update record home:.claude/agents/runner.md", "update record home:.codex/agents/runner.toml"])
        self.assertEqual(self.generated(), before)
        after = {key: entry["inputs"] for key, entry in self.entries().items() if entry["kind"] == "file"}
        self.assertEqual({key for key in after if after[key] != hashes[key]},
                         {"home:.claude/agents/runner.md", "home:.codex/agents/runner.toml"})
        self.assertEqual(self.report()[1]["plan"], [])

    def test_build_for_one_provider_gives_that_providers_definitions(self) -> None:
        built = definitions.build(self.where(), [CODEX])
        self.assertEqual([found.name for found in built],
                         ["quick.toml", "reviewer.toml", "runner.toml", "worker.toml", "worker-hard.toml"])
        self.assertEqual({found.provider for found in built}, {CODEX})
        worker = built[3]
        self.assertEqual(worker.sources, ("roles/worker/ROLE.md", "roles/worker/role.toml", "roles/_shared/brief.md",
                                          "providers/codex/actions.md"))
        self.assertEqual(worker.size, len(worker.text.encode("utf-8")))
        with self.assertRaises(SetupError):
            definitions.build(self.where(), ["acme"])


CACHE = 'cache = "long"\n'
CACHE_TABLE = '\n[cache]\nlong = "1h"\n'
CACHE_LINES = "experimental:\n  cacheTtl: 1h\n"


class CacheCase(DefinitionsCase):
    """``[profile]`` ``cache``: a Claude Code definition of a dispatched role
    says how long its context stays cached, and nothing else changes."""

    def setUp(self) -> None:
        super().setUp()
        self.dictionary = self.clone / "providers" / CLAUDE / "dictionary.toml"
        self.map(CACHE_TABLE)

    def map(self, table: str) -> None:
        self.dictionary.write_bytes((support.FIXTURE_DICTIONARIES[CLAUDE] + table).encode("utf-8"))

    def name(self, role: str, **changes: str) -> None:
        """Give the fixture role the key; ``hard`` of ``ROLE`` is the place
        straight after the profile's effort."""
        self.source(self.clone, role, hard=CACHE + changes.pop("hard", ""), **changes)

    def test_the_key_ends_the_frontmatter_of_that_roles_claude_code_definition_only(self) -> None:
        self.assertEqual(self.render()[0], 0)
        before = (self.claude_agents / "runner.md").read_text(encoding="utf-8")
        records = {key: entry["inputs"] for key, entry in self.entries().items() if entry["kind"] == "file"}
        changed = self.changed_by(lambda: self.name("runner", commands="false", dispatches='["worker"]'))
        self.assertEqual(changed, {".claude/agents/runner.md"})
        text = (self.claude_agents / "runner.md").read_text(encoding="utf-8")
        # The file it was, with the map as the last lines of the frontmatter.
        self.assertEqual(text, before.replace("\n---\n", "\n" + CACHE_LINES + "---\n", 1))
        self.assertTrue(text.startswith(
            '---\nname: runner\ndescription: "Does runner work."\nmodel: sonnet\neffort: medium\n'
            "disallowedTools: Bash, PowerShell, Monitor\nexperimental:\n  cacheTtl: 1h\n---\n\n<!--\n"
        ), text[:300])
        self.assertEqual(list(self.claude_file("runner")[0]), [
            "name", "description", "model", "effort", "disallowedTools", "experimental.cacheTtl",
        ])
        # Codex has no such key: the same bytes, and only the record of what
        # the file was made from moves, since ``role.toml`` is an input.
        self.assertNotIn("cache", (self.codex_agents / "runner.toml").read_text(encoding="utf-8").lower())
        after = {key: entry["inputs"] for key, entry in self.entries().items() if entry["kind"] == "file"}
        self.assertEqual({key for key in after if after[key] != records[key]},
                         {"home:.claude/agents/runner.md", "home:.codex/agents/runner.toml"})
        self.assertEqual(self.report()[1]["plan"], [])

    def test_the_hard_definition_does_not_take_it(self) -> None:
        changed = self.changed_by(lambda: self.name("worker", hard=HARD, includes='["brief.md"]'))
        self.assertEqual(changed, {".claude/agents/worker.md"})
        self.assertEqual(self.claude_file("worker")[0]["experimental.cacheTtl"], "1h")
        self.assertNotIn("experimental.cacheTtl", self.claude_file("worker-hard")[0])

    def test_a_role_that_only_starts_a_session_gets_none(self) -> None:
        # Its definition is the main thread's, which the provider does not read the key from.
        def change() -> None:
            self.name("lead", description=json.dumps(ODD), includes='["gates.md"]', edits="false",
                      dispatches='["worker", "worker-hard"]', dispatch="false", load="true", start="true")

        self.assertEqual(self.changed_by(change), set())
        self.assertNotIn("experimental", (self.claude_agents / "lead.md").read_text(encoding="utf-8"))

    def test_a_provider_that_maps_no_cache_writes_nothing_and_says_nothing(self) -> None:
        self.map("")
        self.assertEqual(self.render()[0], 0)
        before = self.generated()
        self.name("runner", commands="false", dispatches='["worker"]')
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.generated(), before)
        self.assertNotIn("cache", out.lower())
        code, out, err = support_validate(self)
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("cache", out.lower())

    def test_a_lifetime_claude_code_does_not_take_is_one_fault_of_the_dictionary(self) -> None:
        """Claude Code ignores such a value without a word, so every command
        that reads the dictionary says it, once, and nothing is written."""
        self.name("runner", commands="false", dispatches='["worker"]')
        for value in ("2h", "1H", "1h ", "60m"):
            with self.subTest(value):
                self.map(f'\n[cache]\nlong = "{value}"\n')
                fault = f'cache.long: a claude-code definition does not take "{value}"; accepted values: 5m, 1h'
                before = tree(self.root)
                with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
                    runs = {
                        "validate": support.run("validate", "--home", str(self.home)),
                        "show": support.run("show", "roles", "--home", str(self.home)),
                        "doctor": support.run("doctor", "--home", str(self.home)),
                        "render": support.run("render", "--home", str(self.home)),
                    }
                for command, (code, out, err) in runs.items():
                    with self.subTest(command=command):
                        self.assertNotEqual(code, 0)
                        said = [line for line in (out + err).splitlines() if "cache.long" in line]
                        self.assertTrue(said and all(line.endswith(fault) for line in said), out + err)
                        # ``doctor`` says a fault of a dictionary under its check
                        # of the sources and again under each check it stops,
                        # as it does for any other fault of that file.
                        if command != "doctor":
                            self.assertEqual(len(said), 1, out + err)
                            self.assertIn("dictionary.toml: ", said[0])
                self.assertEqual(tree(self.root), before)
        # The same entry in the dictionary of a provider with no such key is not looked at.
        other = self.clone / "providers" / CODEX / "dictionary.toml"
        problems: list[str] = []
        self.map(CACHE_TABLE)
        other.write_bytes(other.read_bytes() + b'\n[cache]\nlong = "2h"\n')
        self.assertIsNotNone(dictionary.check_file(other, CODEX, problems))
        self.assertEqual(problems, [])

    def test_build_refuses_a_lifetime_the_dictionary_let_through(self) -> None:
        self.map('\n[cache]\nlong = "2h"\n')
        self.name("runner", commands="false", dispatches='["worker"]')
        with mock.patch.object(dictionary, "CACHE_VALUES", {}):
            with self.assertRaises(SetupError) as caught:
                definitions.build(self.where())
        self.assertEqual(caught.exception.lines, [
            f'{self.dictionary}: cache.long: "2h" is not a prompt cache lifetime a Claude Code definition takes '
            "(needed for the role runner); it takes: 5m, 1h",
        ])

    def test_codex_writes_nothing_though_its_dictionary_maps_a_cache(self) -> None:
        other = self.clone / "providers" / CODEX / "dictionary.toml"
        plain = other.read_bytes()
        self.name("runner", commands="false", dispatches='["worker"]')
        self.assertEqual(self.render()[0], 0)
        before, digests = self.generated(), definitions.digests(self.where())
        other.write_bytes(plain + b'\n[cache]\nlong = "1h"\n')
        self.assertEqual({item.cache for item in definitions.materials(self.where(), [CODEX])
                          if item.definition == "runner"}, {"1h"})
        self.assertEqual({found.cache for found in definitions.build(self.where(), [CODEX])}, {None})
        self.assertEqual(definitions.digests(self.where()), digests)
        code, report, err = self.report()
        self.assertEqual((code, err, report["plan"]), (0, "", []))
        self.assertEqual(self.generated(), before)
        for file in self.codex_agents.iterdir():
            self.assertNotIn(b"cache", file.read_bytes().lower(), file.name)

    def test_the_definitions_line_of_the_output_names_the_cache_where_there_is_one(self) -> None:
        self.name("runner", commands="false", dispatches='["worker"]')
        self.assertEqual(self.render()[0], 0)
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        size = (self.claude_agents / "runner.md").stat().st_size
        self.assertIn(f"    runner.md: up to date: as generated ({size:,} bytes; model sonnet, effort medium, cache 1h)", lines)
        self.assertEqual([line for line in lines if "cache" in line.lower()], [
            f"    runner.md: up to date: as generated ({size:,} bytes; model sonnet, effort medium, cache 1h)",
        ])
        size = (self.codex_agents / "runner.toml").stat().st_size
        self.assertIn(f"    runner.toml: up to date: as generated ({size:,} bytes; model gpt-6.1-sol, effort medium)", lines)
        report = self.report()[1]
        listed = {(found["provider"], found["file"]): found for found in report["definitions"]}
        self.assertEqual(listed[(CLAUDE, "runner.md")]["cache"], "1h")
        self.assertEqual([key for key, found in listed.items() if "cache" in found], [(CLAUDE, "runner.md")])

    def test_the_digest_holds_the_value_where_one_is_written_and_is_what_it_was_elsewhere(self) -> None:
        # A definition without the key keeps the digest it had before the
        # key existed: the form below is that one, built by hand, and has no
        # ``cache`` in it. Were it there, every recorded definition would
        # show as drift after an upgrade.
        files = {"roles/x/ROLE.md": "# X\r\n\r\nText.\n\n", "roles/x/role.toml": 'name = "x"\n'}
        form = {
            "scheme": definitions.INPUTS_SCHEME, "provider": CLAUDE, "definition": "x", "role": "x",
            "files": {name: digest(roles.join_text([text]).encode("utf-8")) for name, text in files.items()},
            "bindings": [], "skills": None, "model": "opus", "effort": "high",
        }

        def hashed(form: dict) -> str:
            raw = json.dumps(form, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            return f"{definitions.INPUTS_SCHEME}:{digest(raw)}"

        self.assertEqual(definitions.inputs_digest(CLAUDE, "x", "x", files, (), "opus", "high"), hashed(form))
        self.assertEqual(definitions.inputs_digest(CLAUDE, "x", "x", files, (), "opus", "high", cache=None), hashed(form))
        self.assertEqual(definitions.inputs_digest(CLAUDE, "x", "x", files, (), "opus", "high", cache="1h"),
                         hashed({**form, "cache": "1h"}))
        self.assertEqual(
            definitions.inputs_digest(CLAUDE, "x", "x", files, (), "opus", "high"),
            # What the code gave before the key existed (commit ccbd2a9).
            "render:role-definition:6:5a188bc0f2084527f427e3ce235cff4b252ee4cb89fcdddd38ad57b14f4f0faa",
        )

        self.map("")
        without = definitions.digests(self.where())
        self.map(CACHE_TABLE)
        # A table nobody names changes no digest: no format number is raised for the key.
        self.assertEqual(definitions.digests(self.where()), without)
        self.name("runner", commands="false", dispatches='["worker"]')
        named = definitions.digests(self.where())
        self.assertEqual({key for key in named if named[key] != without[key]}, {(CLAUDE, "runner"), (CODEX, "runner")})
        self.map('\n[cache]\nlong = "5m"\n')
        short = definitions.digests(self.where())
        self.assertEqual({key for key in short if short[key] != named[key]}, {(CLAUDE, "runner")})
        self.assertEqual(self.render()[0], 0)
        self.assertEqual(self.claude_file("runner")[0]["experimental.cacheTtl"], "5m")

    def test_the_two_formats(self) -> None:
        fields = {"name": "x", "role": "x", "description": "Does x.", "model": "opus", "effort": "high",
                  "denied": ("Agent", "Workflow"), "cache": "1h"}
        made = definitions.claude_code_text(fields, ["A notice."], ["Body."])
        self.assertEqual(
            made.split("\n\n")[0],
            '---\nname: x\ndescription: "Does x."\nmodel: opus\neffort: high\ndisallowedTools: Agent, Workflow\n'
            "experimental:\n  cacheTtl: 1h\n---",
        )
        self.assertEqual(made, definitions.claude_code_text({**fields, "cache": None}, ["A notice."], ["Body."])
                         .replace("\n---\n", "\n" + CACHE_LINES + "---\n", 1))
        # The Codex format has no place for it.
        self.assertEqual(definitions.codex_text(fields, ["A notice."], ["Body."]),
                         definitions.codex_text({**fields, "cache": None}, ["A notice."], ["Body."]))


def support_validate(case: DefinitionsCase) -> tuple[int, str, str]:
    """``validate`` on the case's clone."""
    with mock.patch.object(homes.Host, "current", classmethod(lambda cls: case.host)):
        return support.run("validate", "--home", str(case.home))


class NoRolesCase(DefinitionsCase):
    def test_no_roles_generates_nothing(self) -> None:
        code, out, err = self.render("--no-roles")
        self.assertEqual((code, err), (0, ""))
        self.assertNothingAt(self.claude_agents)
        self.assertNothingAt(self.codex_agents)
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertIn("done: 6 links created, 0 removed", out.splitlines()[-1])
        self.assertNotIn("files", out.splitlines()[-1])

    def test_no_roles_removes_the_definitions_of_an_earlier_run(self) -> None:
        self.assertEqual(self.render()[0], 0)
        code, report, err = self.report("--no-roles")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.generated(), {})
        self.assertLinked(self.claude_skills / "alpha", self.clone / "alpha")
        self.assertLinked(self.rules / "sample", self.clone / "rules" / "sample")
        self.assertEqual(sorted(item["key"] for item in report["stale"]), sorted(f"home:{name}" for name in ALL_FILES))
        self.assertEqual({item["status"] for item in report["stale"]}, {render.REMOVE})
        self.assertEqual(report["counts"]["file_remove"], 11)
        self.assertEqual(report["definitions"], [])
        self.assertIn("0 files written, 11 removed", report["summary"])
        self.assertEqual([key for key, entry in self.entries().items() if entry["kind"] == "file"], [])
        before = tree(self.root)
        code, report, _ = self.report("--no-roles")
        self.assertEqual((code, report["plan"], report["stale"]), (0, [], []))
        self.assertEqual(tree(self.root), before)
        # Without the option they are generated again.
        self.assertEqual(self.render()[0], 0)
        self.assertEqual(set(self.generated()), ALL_FILES)

    def test_no_roles_keeps_a_definition_that_was_edited(self) -> None:
        self.assertEqual(self.render()[0], 0)
        mine = self.claude_agents / "lead.md"
        mine.write_bytes(mine.read_bytes() + b"\nMy own line.\n")
        edited = mine.read_bytes()
        code, report, err = self.report("--no-roles")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.generated(), {".claude/agents/lead.md": edited})
        kept = [item for item in report["stale"] if item["status"] == render.KEPT]
        self.assertEqual([item["key"] for item in kept], ["home:.claude/agents/lead.md"])
        self.assertIn("it was edited since setup wrote it; kept, it is yours", kept[0]["says"])
        self.assertIn("1 kept", report["summary"])

    def test_a_settings_file_init_wrote_is_not_a_stale_generated_file(self) -> None:
        self.assertEqual(self.render()[0], 0)
        plan = fileops.Plan(self.roots())
        plan.write_file(self.user_file, '[roles.worker]\ntier = "deep"\n', replace=fileops.ANY)
        plan.apply()
        code, report, _ = self.report("--no-roles")
        self.assertEqual(code, 0)
        self.assertEqual(self.user_file.read_text(encoding="utf-8"), '[roles.worker]\ntier = "deep"\n')
        self.assertNotIn("home:.agents/workflow.toml", [item["key"] for item in report["stale"]])


class StaleCase(DefinitionsCase):
    def test_a_role_that_left_the_clone_loses_its_definitions(self) -> None:
        self.assertEqual(self.render()[0], 0)
        shutil.rmtree(self.clone / "roles" / "quick")
        code, out, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(set(self.generated()), ALL_FILES - {".claude/agents/quick.md", ".codex/agents/quick.toml"})
        self.assertIn("  remove file home:.claude/agents/quick.md (backup)", out.splitlines())
        self.assertIn("  home:.codex/agents/quick.toml: remove: no longer generated; it still holds what setup wrote, so it is removed", out.splitlines())

    def test_a_role_that_is_no_longer_dispatched_loses_its_codex_definition(self) -> None:
        self.assertEqual(self.render()[0], 0)
        self.source(self.clone, "runner", commands="false", dispatches='["worker"]', dispatch="false", start="true")
        self.assertEqual(self.render()[0], 0)
        self.assertNothingAt(self.codex_agents / "runner.toml")
        self.assertEqual(self.claude_file("runner")[0]["name"], "runner")

    def test_a_stale_definition_that_is_gone_is_forgotten(self) -> None:
        self.assertEqual(self.render()[0], 0)
        shutil.rmtree(self.clone / "roles" / "quick")
        (self.codex_agents / "quick.toml").unlink()
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual({item["key"]: item["status"] for item in report["stale"]},
                         {"home:.claude/agents/quick.md": render.REMOVE, "home:.codex/agents/quick.toml": render.FORGET})
        self.assertNotIn("home:.codex/agents/quick.toml", self.entries())


class EditedCase(DefinitionsCase):
    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.render()[0], 0)
        self.mine = self.codex_agents / "worker.toml"
        self.original = self.mine.read_bytes()
        self.edited = self.original.replace(b'model = "gpt-6.1-sol"', b'model = "my-own"')
        self.assertNotEqual(self.edited, self.original)
        self.mine.write_bytes(self.edited)

    def test_a_hand_edited_definition_is_kept_and_reported(self) -> None:
        before = tree(self.root)
        for argv in (("--dry-run",), ()):
            code, out, err = self.render(*argv)
            self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
            self.assertEqual(code, 3)
            self.assertEqual(tree(self.root), before)
            flat = " ".join(out.split())
            self.assertIn("worker.toml: kept: edited by hand since setup wrote it, and kept; --overwrite-edited backs "
                          "it up and replaces it, or remove the file and run render again", flat)
            self.assertIn("1 edited by hand and kept, which --overwrite-edited would replace", out.splitlines()[-1])
        code, report, _ = self.report()
        self.assertEqual((code, report["exit_code"], report["counts"]["edited"], report["errors"]), (3, 3, 1, []))
        self.assertEqual(self.items(report, CODEX, "agents")["worker.toml"], render.EDITED)

    def test_the_rest_of_the_run_is_done_beside_a_kept_file(self) -> None:
        file = self.clone / "roles/worker/ROLE.md"
        file.write_bytes(file.read_bytes() + b"\nOne more line.\n")
        code, _, err = self.render()
        self.assertEqual((code, err), (3, ""))
        self.assertEqual(self.mine.read_bytes(), self.edited)
        self.assertIn(b"One more line.", (self.claude_agents / "worker.md").read_bytes())
        self.assertIn(b"One more line.", (self.codex_agents / "worker-hard.toml").read_bytes())

    def test_the_overwrite_flag_backs_it_up_and_replaces_it(self) -> None:
        code, out, err = self.render("--overwrite-edited", "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.mine.read_bytes(), self.edited)
        self.assertIn("  replace file home:.codex/agents/worker.toml (backup)", out.splitlines())

        code, out, err = self.render("--overwrite-edited")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.mine.read_bytes(), self.original)
        self.assertIn("worker.toml: replace: edited by hand since setup wrote it; backed up and replaced", " ".join(out.split()))
        record = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        backups = [backup for backup in record["backups"] if backup["path"] == "home:.codex/agents/worker.toml"]
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]["sha256"], digest(self.edited))
        saved = [
            Path(directory) / name
            for directory, _, names in os.walk(self.home / ".agents" / "workflow-setup" / "backups")
            for name in names
        ]
        self.assertEqual([file.read_bytes() for file in saved], [self.edited])
        self.assertEqual(self.render()[0], 0)

    def test_removing_the_file_has_it_written_again(self) -> None:
        self.mine.unlink()
        code, _, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.mine.read_bytes(), self.original)

    def test_an_edit_that_says_what_would_be_written_is_no_edit(self) -> None:
        self.write(self.user_file, '[providers.codex.role_models]\nworker = "my-own"\n')
        code, report, err = self.report()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.mine.read_bytes(), self.edited)
        self.assertEqual(self.items(report, CODEX, "agents")["worker.toml"], render.UP_TO_DATE)
        self.assertEqual(self.report()[1]["plan"], [])

    def test_a_users_own_file_in_the_way_is_a_conflict(self) -> None:
        self.assertEqual(self.render("--no-roles")[0], 0)  # the edited one is kept; the others go
        self.mine.unlink()
        self.assertEqual(self.render("--no-roles")[0], 0)
        self.keep(self.claude_agents / "lead.md")
        before = tree(self.root)
        code, out, err = self.render()
        self.assertEqual(code, 2)
        self.assertIn(f"{self.claude_agents / 'lead.md'}: a file is there, and setup did not write it", err)
        self.assertEqual(tree(self.root), before)
        self.assertIn("nothing was written", out.splitlines()[-1])


class GateCase(DefinitionsCase):
    def refused(self, *expected: str) -> str:
        before = tree(self.root)
        for argv in ((), ("--dry-run",)):
            code, out, err = self.render(*argv)
            self.assertEqual(code, 2, out)
            self.assertEqual(tree(self.root), before)
            for text in expected:
                self.assertIn(text, err)
            self.assertIn("stopped: ", out.splitlines()[-1])
            self.assertIn("nothing was written", out.splitlines()[-1])
        return err

    def test_a_profile_that_does_not_resolve_stops_before_any_write(self) -> None:
        self.write(self.user_file, '[roles.worker]\neffort = "max"\n[providers.codex.tiers]\nstandard = "gpt-5.5"\n')
        err = self.refused('role worker, provider codex: the model "gpt-5.5" does not accept the effort "max"')
        self.assertIn("it accepts: low, medium, high, xhigh", err)
        self.assertNothingAt(self.claude_skills)
        self.assertNothingAt(self.manifest_file)

    def test_an_installed_provider_with_no_dictionary_stops_before_any_write(self) -> None:
        shutil.rmtree(self.clone / "providers" / "codex")
        err = self.refused("codex: no such provider among those with a dictionary (acme, claude-code)")
        self.assertIn("providers/codex/dictionary.toml is missing", err)
        self.assertIn("quick, reviewer, runner, worker, worker-hard", err)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertNothingAt(self.claude_agents)
        # With the process alone there is nothing to resolve.
        self.assertEqual(self.render("--no-roles")[0], 0)

    def test_a_provider_that_is_not_installed_needs_no_dictionary(self) -> None:
        shutil.rmtree(self.clone / "providers" / "codex")
        self.codex.rmdir()
        code, _, err = self.render()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(set(self.generated()), {name for name in ALL_FILES if name.startswith(".claude/")})
        self.assertNothingAt(self.codex)

    def test_a_source_fault_stops_before_the_definitions(self) -> None:
        (self.clone / "roles/worker/ROLE.md").unlink()
        before = tree(self.root)
        code, out, err = self.render()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("[role-text]", err)
        self.assertEqual(tree(self.root), before)

    def test_a_directory_where_a_definition_goes_is_a_conflict(self) -> None:
        self.keep(self.codex_agents / "worker.toml" / "inside.txt")
        self.refused(f"{self.codex_agents / 'worker.toml'}: a directory is there, where setup would write a file")


@unittest.skipUnless(LINKS, "needs links to directories")
class PlacesCase(DefinitionsCase):
    @unittest.skipUnless(SYMLINKS and POSIX, "the view from WSL is rebuilt from symlinks on a POSIX file system")
    def test_an_agents_place_of_the_other_side_is_skipped(self) -> None:
        drive = self.root / "drive"
        theirs = drive / "Users" / "someone" / ".claude" / "agents"
        self.keep(theirs / "theirs.md")
        os.symlink(str(theirs), self.claude_agents)
        wsl = homes.Host(homes.WSL, {"PATH": ""}, (str(drive),))
        before = tree(drive)
        code, out, err = self.render(host=wsl)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(drive), before)
        self.assertIn("    not written here: lead.md, quick.md, reviewer.md, runner.md, worker.md, worker-hard.md", out.splitlines())
        self.assertEqual(set(self.generated()) - {".claude/agents/theirs.md"}, {name for name in ALL_FILES if name.startswith(".codex/")})
        self.assertNotIn("home:.claude/agents/lead.md", self.entries())

    def test_an_agents_place_that_leads_out_of_the_home_is_skipped_with_and_without_the_flag(self) -> None:
        elsewhere = self.root / "another-home" / "agents"
        self.keep(elsewhere / "theirs.md")
        fsio.make_link(str(elsewhere), self.codex_agents, True)   # a symlink, or on Windows a junction
        before = tree(self.root / "another-home")
        for argv in ((), ("--dry-run",), ("--follow-config-symlinks", "--dry-run"), ("--follow-config-symlinks",),
                     ("--follow-config-symlinks", "--overwrite-edited")):
            with self.subTest(argv=argv):
                code, out, err = self.render(*argv)
                # No option makes a run write there, so the code asks for none.
                self.assertEqual((code, err), (0, ""), out)
                self.assertEqual(tree(self.root / "another-home"), before)
                self.assertIn("    not written here: quick.toml, reviewer.toml, runner.toml, worker.toml, worker-hard.toml",
                              out.splitlines())
                self.assertIn(f"skipped: a link to {elsewhere}, which leads out of the directories this run may write "
                              "to: skipped, whatever the options", out)
                self.assertNotIn("needs --follow-config-symlinks", out)
        self.assertEqual(fsio.look(self.codex_agents).kind, fsio.LINK)
        self.assertFalse(any(key.startswith("home:.codex/agents") for key in self.entries()))
        # The other provider's definitions are written as always.
        self.assertTrue((self.claude_agents / "lead.md").is_file())

    def test_an_agents_place_shared_on_this_side_needs_the_flag(self) -> None:
        elsewhere = self.home / "dotfiles" / "agents"   # in the home, where a run may write
        self.keep(elsewhere / "theirs.md")
        fsio.make_link(str(elsewhere), self.codex_agents, True)   # a symlink, or on Windows a junction
        code, out, err = self.render()
        self.assertEqual((code, err), (3, ""))
        self.assertEqual(os.listdir(elsewhere), ["theirs.md"])
        self.assertIn("    not written here: quick.toml, reviewer.toml, runner.toml, worker.toml, worker-hard.toml", out.splitlines())
        code, _, err = self.render("--follow-config-symlinks")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(sorted(os.listdir(elsewhere)),
                         ["quick.toml", "reviewer.toml", "runner.toml", "theirs.md", "worker-hard.toml", "worker.toml"])


class RepositoryCase(RenderCase):
    """The repository's own roles, whatever they say: subsets only, so a
    role added later breaks nothing here."""

    ROLES = ()

    def test_the_repositorys_roles_render_for_both_providers(self) -> None:
        # The roles part alone: where the repository is a clone the other
        # side sees through a network name, no link to it can be made, and
        # the links are not what this test is about.
        where = Locations(home=self.home, clone=support.REPOSITORY)
        found, sources, parts = homes.resolve(where, self.host), validate.require(where), render.PARTS[2:3]
        outcome = render.execute(found, sources, parts=parts)
        self.assertEqual((outcome.code, outcome.errors), (0, []))
        report = outcome.report
        before = tree(self.home)
        again = render.execute(found, sources, parts=parts)
        self.assertEqual((again.code, again.report["plan"]), (0, []))
        self.assertEqual(tree(self.home), before)
        claude = {file.name for file in (self.claude / "agents").iterdir()}
        codex = {file.name for file in (self.codex / "agents").iterdir()}
        dispatched = {"product-manager", "coder", "coder-hard", "architect", "implementation-manager",
                      "investigator", "idea-reviewer", "plan-reviewer", "code-reviewer"}
        self.assertLessEqual({"manager.md"} | {f"{name}.md" for name in dispatched}, claude)
        self.assertLessEqual({f"{name}.toml" for name in dispatched}, codex)
        # The Manager starts a session and is not dispatched: no Codex agent file.
        self.assertNotIn("manager.toml", codex)

        where = Locations(home=self.home, clone=support.REPOSITORY)
        loaded = roles.load_all(where)
        for file in (self.claude / "agents").iterdir():
            fields, body = frontmatter(file.read_bytes().decode("utf-8"))
            self.assertEqual(fields["name"], file.stem)
            self.assertLessEqual({"name", "description", "model"}, set(fields))
            self.assertNotIn("tools", fields)
            self.assertIn("## Your bindings", body)
            role = loaded[fields["name"].removesuffix("-hard") if fields["name"] not in loaded else fields["name"]]
            self.assertIn(role.description, fields["description"])
            self.assertEqual(fields.get("disallowedTools", ""), ", ".join(definitions.denied_tools(role.data["limits"])))
        for file in (self.codex / "agents").iterdir():
            data = tomllib.loads(file.read_bytes().decode("utf-8"))
            self.assertEqual(data["name"], file.stem.replace("-", "_"))
            self.assertLessEqual({"name", "description", "model", "developer_instructions"}, set(data))
            self.assertIn("## Your bindings", data["developer_instructions"])
        coder, _ = frontmatter((self.claude / "agents" / "coder.md").read_bytes().decode("utf-8"))
        hard, _ = frontmatter((self.claude / "agents" / "coder-hard.md").read_bytes().decode("utf-8"))
        self.assertEqual(hard["description"], f"The Coder for steps marked hard. {coder['description']}")
        self.assertIn("stage-3-implementation.md", (self.codex / "agents" / "coder-hard.toml").read_text(encoding="utf-8"))
        self.assertEqual({found["file"] for found in report["definitions"]}, claude | codex)
        for found in report["definitions"]:
            self.assertGreater(found["bytes"], 1000)
        for data in (file.read_bytes() for directory in (self.claude / "agents", self.codex / "agents") for file in directory.iterdir()):
            self.assertNotIn(str(support.REPOSITORY).encode("utf-8"), data)
            self.assertNotIn(str(self.root).encode("utf-8"), data)

    # The roles that wait between their turns, on the user or on Coders, and
    # the two reviewers, whose long thinking outlasts five minutes.
    CACHED = ("architect", "idea-reviewer", "implementation-manager", "plan-reviewer", "product-manager")

    def test_the_roles_that_wait_keep_their_context_cached_on_claude_code(self) -> None:
        where = Locations(home=self.home, clone=support.REPOSITORY)
        loaded = roles.load_all(where)
        named = {name for name, role in loaded.items() if role.definitions[0].cache is not None}
        self.assertLessEqual(set(self.CACHED), named)
        self.assertNotIn("manager", named)   # the main session: on the long cache already
        built = {(found.provider, found.definition): found for found in definitions.build(where)}
        for (provider, name), found in built.items():
            with self.subTest(provider=provider, definition=name):
                if provider == CLAUDE and name in named:
                    fields, _ = frontmatter(found.text)
                    self.assertEqual(list(fields)[-1], "experimental.cacheTtl")
                    self.assertEqual(fields["experimental.cacheTtl"], "1h")
                    self.assertIn("\nexperimental:\n  cacheTtl: 1h\n---\n\n<!--\n", found.text)
                    self.assertEqual(found.text.count("cacheTtl"), 1)
                else:
                    self.assertNotIn("cacheTtl", found.text)
                    self.assertNotIn("experimental:", found.text)

    def test_an_installed_home_gets_the_cache_key_in_those_files_and_no_other_change(self) -> None:
        """The upgrade: a home rendered from the sources as they were before
        any role named a cache, then rendered from today's. The roles and
        entry parts, so the loaded roles' skills and the Codex profile are
        in the home too."""
        # Only what the sources are: every directory that holds a skill, the
        # roles, the rules, the providers and the shipped defaults. Nothing
        # else of the checkout is copied, so what a tool or an editor left
        # in it (a dot-directory, a cache, a link that leads nowhere) is
        # never walked.
        clone = self.root / "sources"
        ignore = shutil.ignore_patterns(".*", "__pycache__", "tests")
        wanted = ["roles", "rules", "providers", *sorted(
            entry.name for entry in support.REPOSITORY.iterdir()
            if not entry.name.startswith(".") and (entry / "SKILL.md").is_file()
        )]
        for name in wanted:
            shutil.copytree(support.REPOSITORY / name, clone / name, ignore=ignore)
        (clone / "tools" / "setup").mkdir(parents=True)
        shutil.copy(support.DEFAULTS, clone / "tools" / "setup" / "defaults.toml")
        files = {name: clone / "roles" / name / "role.toml" for name in self.CACHED}
        today = {name: file.read_bytes() for name, file in files.items()}
        for name, file in files.items():
            self.assertEqual(today[name].count(CACHE.encode()), 1, name)
            file.write_bytes(today[name].replace(CACHE.encode(), b""))
        where, parts = Locations(home=self.home, clone=clone), render.PARTS[2:4]

        def run() -> render.Outcome:
            outcome = render.execute(homes.resolve(where, self.host), validate.require(where), parts=parts)
            self.assertEqual((outcome.code, outcome.errors), (0, []))
            return outcome

        def files_of() -> dict[str, bytes]:
            return {name: found[1] for name, found in tree(self.home).items()
                    if found[0] == "file" and not name.startswith(".agents/workflow-setup/")}

        run()
        before = files_of()
        self.assertLessEqual(
            {".claude/agents/manager.md", ".claude/skills/product-manager/SKILL.md",
             ".agents/skills/architect/SKILL.md", ".codex/agents/implementation-manager.toml"}, set(before))
        self.assertFalse([name for name, data in before.items() if b"cacheTtl" in data])
        for name, file in files.items():
            file.write_bytes(today[name])
        report = run().report
        after = files_of()
        self.assertEqual(set(after), set(before))
        changed = {name for name in after if after[name] != before[name]}
        self.assertEqual(changed, {f".claude/agents/{name}.md" for name in self.CACHED})
        self.assertEqual(report["counts"]["file_write"], len(self.CACHED))
        for name in changed:
            old, new = before[name].decode("utf-8"), after[name].decode("utf-8")
            self.assertEqual(new, old.replace("\n---\n", "\n" + CACHE_LINES + "---\n", 1))
        self.assertEqual(run().report["plan"], [])
        self.assertEqual(files_of(), after)

    # Who dispatches whom, and what each of the nine may do: the framework
    # document's table, as the sources state it. A role added later is not
    # looked at.
    DISPATCHES = {
        "manager": ("product-manager", "architect", "implementation-manager", "idea-reviewer", "plan-reviewer"),
        "product-manager": ("investigator",),
        "architect": ("investigator",),
        "implementation-manager": ("coder", "coder-hard", "code-reviewer"),
        "coder": (), "investigator": (), "idea-reviewer": (), "plan-reviewer": (), "code-reviewer": (),
    }

    def test_the_nine_roles_and_who_dispatches_whom(self) -> None:
        where = Locations(home=self.home, clone=support.REPOSITORY)
        loaded = roles.load_all(where)
        self.assertLessEqual(set(self.DISPATCHES), set(loaded))
        for name, wanted in self.DISPATCHES.items():
            with self.subTest(role=name):
                limits, entry = loaded[name].data["limits"], loaded[name].data["entry"]
                self.assertEqual(tuple(limits["dispatches"]), wanted)
                # Only the Manager starts a session, and it is never dispatched.
                self.assertEqual((entry["start"], entry["dispatch"]), (name == "manager", name != "manager"))
                self.assertEqual(entry["load"], name in ("manager", "product-manager", "architect"))
        # The Manager and the reviewers change no file; two reviewers run no command.
        writes = {name for name in self.DISPATCHES if loaded[name].data["limits"]["edits"]}
        self.assertEqual(writes, {"product-manager", "architect", "implementation-manager", "coder"})
        shell = {name for name in self.DISPATCHES if not loaded[name].data["limits"]["commands"]}
        self.assertEqual(shell, {"idea-reviewer", "plan-reviewer"})
        for name in shell:
            self.assertEqual(loaded[name].data["actions"], ["read"])
        self.assertEqual([definition.id for definition in loaded["coder"].definitions], ["coder", "coder-hard"])

    def test_every_role_that_follows_a_stage_file_has_its_rows(self) -> None:
        where = Locations(home=self.home, clone=support.REPOSITORY)
        rows = definitions.bindings(where)
        found = {role: {(row.skill, row.stage, row.part) for row in mine} for role, mine in rows.items()}
        sprint, epic = "prd-implementation", "epic-implementation"
        for role, wanted in {
            "manager": {(sprint, "deferred.md", "checks"), (sprint, "stage-3-implementation.md", "choices"),
                        (sprint, "completion.md", "close-commands"), (sprint, "abandon.md", "close-commands")},
            "product-manager": {(sprint, "stage-0-backlog.md", "owns"), (sprint, "backlog-conversion.md", "owns"),
                                (sprint, "deferred-conversion.md", "owns"), (sprint, "stage-1-thoughts.md", "owns"), (sprint, "stage-2-prd.md", "owns"),
                                (epic, "stage-e0-backlog.md", "owns"), (epic, "stage-e1-thoughts.md", "owns"),
                                (epic, "stage-e2-charter.md", "owns"), (epic, "stage-e3-roadmap.md", "seam"),
                                (epic, "completion.md", "owns")},
            "idea-reviewer": {(sprint, "stage-2-prd.md", "critical-pass"), (epic, "stage-e2-charter.md", "critical-pass")},
            "architect": {(sprint, "stage-3-plan-tasks.md", "owns"), (epic, "stage-e3-roadmap.md", "decomposes")},
            "plan-reviewer": {(sprint, "stage-3-plan-tasks.md", "reviews")},
            "implementation-manager": {(sprint, "stage-3-implementation.md", "build-lead"),
                                       (sprint, "state.md", "build-lead"),
                                       (sprint, "completion.md", "close-writer"),
                                       (sprint, "abandon.md", "close-writer")},
            "coder": {(sprint, "stage-3-implementation.md", "implementer")},
        }.items():
            with self.subTest(role=role):
                self.assertLessEqual(wanted, found.get(role, set()))
        # The Manager writes nothing, so what the close and a deferred item
        # write has a role that does.
        self.assertIn((sprint, "deferred.md", "writes"), found["implementation-manager"])        # The Investigator and the Code Reviewer follow no stage file.
        self.assertEqual(set(found) & {"investigator", "code-reviewer"}, set())

    def test_every_stage_file_of_both_process_skills_has_a_row(self) -> None:
        """The table is complete, and a role that may not write owns no
        stage that writes."""
        where = Locations(home=self.home, clone=support.REPOSITORY)
        rows = [row for mine in definitions.bindings(where).values() for row in mine]
        stages = {
            skill: {file.name for file in (support.REPOSITORY / skill / "references").glob("*.md")}
            - {"conventions.md", "claude-code.md", "codex.md"}
            for skill in ("prd-implementation", "epic-implementation")
        }
        self.assertEqual(len(stages["prd-implementation"]), 11)
        self.assertEqual(len(stages["epic-implementation"]), 5)
        self.assertEqual({skill: {row.stage for row in rows if row.skill == skill} for skill in stages}, stages)
        self.assertEqual(validate.check(where).lines(), [])
        loaded = roles.load_all(where)
        for row in rows:
            if row.part == definitions.OWNS:
                self.assertTrue(loaded[row.role].data["limits"]["edits"], row)

    def test_a_loaded_role_of_the_repository_is_told_where_its_stage_files_are(self) -> None:
        where = Locations(home=self.home, clone=support.REPOSITORY)
        places = {CLAUDE: "~/.claude/skills", CODEX: "~/.agents/skills"}
        seen = set()
        for found in definitions.materials(where, select=lambda role: definitions.PROVIDERS, hard=False):
            section = found.body[-2]
            self.assertTrue(section.startswith("## Your bindings\n"), found.role.name)
            for row in found.rows:
                self.assertIn(f"\n\nIn `{places[found.provider]}/{row.skill}/references/`:\n\n", section)
                self.assertIn(f"\n- `{row.stage}`, part `{row.part}`", section)
                self.assertTrue((support.REPOSITORY / row.skill / "references" / row.stage).is_file(), row)
                seen.add(found.role.name)
        self.assertLessEqual({"manager", "product-manager", "architect", "implementation-manager", "coder"}, seen)
        # The command the Manager runs at a session's start is one the skill has.
        self.assertTrue((support.REPOSITORY / "prd-implementation" / "scripts" / "check.py").is_file())
        manager = [row for row in definitions.bindings(where)["manager"] if row.part == "checks"]
        self.assertIn("`python scripts/check.py --project <project root>`", manager[0].note)
        # ... and the section says where a skill's scripts are.
        self.assertIn("A skill's scripts are in `scripts/`, beside `references/`.", definitions.bindings_section(manager, "~"))

    def test_a_question_asked_in_a_dialogue_reaches_the_user_in_the_main_thread(self) -> None:
        """An agent's thread may close before the user reads it, so the
        question is in the hand-back as well, the Manager prints it, and an
        answer given to the Manager goes back by a follow-up."""
        where = Locations(home=self.home, clone=support.REPOSITORY)
        texts = {(found.role.name, found.provider): "\n".join(found.body)
                 for found in definitions.materials(where, select=lambda role: definitions.PROVIDERS, hard=False)}
        for provider in (CLAUDE, CODEX):
            # The writer: the two roles that hold a dialogue carry the question.
            for role in ("product-manager", "architect"):
                with self.subTest(role=role, provider=provider):
                    text = texts[role, provider]
                    self.assertIn("<one line>\nQuestion:\n<what you asked the user>\nQuotes:\n", text)
                    self.assertIn("**The user reads your thread first, and it may close before they do.**", text)
                    self.assertIn("goes there first, in full, as ordinary text", text)
                    self.assertIn("A question is then repeated under `Question:`, word for word with its options and any "
                                  "recommendation, for the Manager to print; so is your reply, when the "
                                  "Manager's follow-up started the turn", text)
                    self.assertIn("**One line while in dialogue**, besides the question.", text)
                    # What the rule replaced is gone.
                    self.assertNotIn("never the hand-back", text)
                    self.assertNotIn("has not been asked", text)
                    self.assertNotIn("the Manager does nothing", text)
                    self.assertNotIn("## Reading hand-backs", text)
            # The reader: the Manager prints it, and relays the answer.
            with self.subTest(role="manager", provider=provider):
                text = texts["manager", provider]
                self.assertIn("- **`in dialogue, no action`.** Do nothing: no dispatch, lookup, question of your own, summary, "
                              "acknowledgement or comment on the quotes.", text)
                self.assertIn("A `Question:` you print to the user word for word under that role's name, adding only that "
                              "they may answer here.", text)
                self.assertIn("- **The user answers it here.** Follow up with that agent, quoting question and answer "
                              "word for word. It passes no gate.", text)
                # A quote that passes nothing leaves the user to be asked, not waiting.
                self.assertIn("If none does, ask for the word here.", text)
                # The rules the reader no longer repeats are the gates section's.
                self.assertIn("passes nothing and triggers nothing", text)
                self.assertIn("only on the user's word", text)
                # The gate rule the relay leans on: a follow-up ends the quote's standing.
                self.assertIn("has sent the agent nothing since, not even a follow-up", text)
                self.assertNotIn("## Writing hand-backs", text)
        # How it is done where the user can type to a dispatched agent.
        self.assertIn("Tell the user how, and that its questions also appear here, to answer in either place:",
                      texts["manager", CLAUDE])
        self.assertIn("After that only your follow-up resumes it.", texts["manager", CLAUDE])
        for role in ("product-manager", "architect"):
            self.assertIn("The user answers in your thread or through the Manager's follow-up; either resumes you.",
                          texts[role, CLAUDE])
            # On Codex no role is dispatched for a dialogue.
            self.assertIn("you cannot ask the user anything", texts[role, CODEX])
        self.assertIn("no role is dispatched for dialogue", texts["manager", CODEX])


if __name__ == "__main__":
    unittest.main()
