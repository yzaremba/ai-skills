"""Tests for source validation: each rule on a scratch clone, and the
repository itself.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

Every test but ``RepositoryTests`` builds its own clone from the fixtures
below and reads nothing of the repository. A path of one machine is never
written out in this file: where a test needs one, it is put together from
pieces, so the file itself holds none.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

import support
from wfsetup import definitions, entry, locations, roles, validate
from wfsetup.errors import SetupError

# Put together at run time, so this file holds no machine path.
SLASH = "/"
HOME_PATH = SLASH + "home" + SLASH + "alice" + SLASH + "notes.md"
MAC_PATH = SLASH + "Users" + SLASH + "alice" + SLASH + "notes.md"
MOUNT_PATH = SLASH + "mnt" + SLASH + "c" + SLASH + "clone"
DRIVE_PATH = "C" + ":" + "\\" + "work" + "\\" + "clone"
DRIVE_PATH_ESCAPED = "C" + ":" + "\\\\" + "work"
DRIVE_PATH_SLASH = "D" + ":" + "/" + "work"
WSL_PATH = "\\\\" + "wsl.localhost" + "\\" + "Distro" + "\\" + "x"

SKILL = """---
name: {name}
description: Does {name} work. Use when asked for it.
compatibility: claude-code, codex
---

# {name}

Run `scripts/` in this skill's directory.
"""

LAUNCHER = '''"""Print the settings a skill reads."""
import json
import sys

BUILT_IN = {
    "process.docs_dir": "docs",
    "process.questions": "one-at-a-time",
    "process.recommend": True,
    "memory.dir": "docs/memory",
    "roles.enabled": True,
    "roles.manager_default": False,
    "roles.high_stakes": False,
    "roles.max_parallel_coders": 3,
}
'''

CHECK = '''"""Check the docs."""
import argparse

BUILT_IN = {
    "process.docs_dir": "docs",
    "process.questions": "one-at-a-time",
    "process.recommend": True,
}
'''

ROLE = """name = "{name}"
title = "{title}"
description = "Does {name} work."
includes = ["brief.md"]

[profile]
tier = "standard"
effort = "medium"
{hard}
[limits]
edits = true
commands = true
dispatches = {dispatches}

[entry]
dispatch = true
load = false
start = false
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

OPENAI = """interface:
  display_name: "Alpha"

policy:
  allow_implicit_invocation: false
"""


class TreeCase(support.CloneCase):
    """A clone with nothing wrong in it: two shared skills, a skill for one
    provider, a skill with its own setup, a rule, two roles, the binding
    table, a provider and the shipped defaults."""

    def setUp(self) -> None:
        super().setUp()
        for name in ("alpha", "beta"):
            self.put(f"{name}/SKILL.md", SKILL.format(name=name))
            self.put(f"{name}/scripts/settings.py", LAUNCHER)
        self.put("alpha/scripts/common.py", "import json\n\n\ndef load(text):\n    return json.loads(text)\n")
        self.put("alpha/scripts/tool.py", "from __future__ import annotations\n\nimport os.path\n\nimport common\n")
        self.put("alpha/tests/test_tool.py", "import unittest\n\nimport tool\nfrom . import helper\n")
        self.put("alpha/scripts-node/common.mjs", 'import fs from "node:fs";\n')
        self.put(
            "alpha/scripts-node/tool.mjs",
            'import { parseArgs } from "node:util";\nimport {\n  load,\n  save,\n} from "./common.mjs";\n'
            'import path from "path";\nimport { readFile } from "fs/promises";\n',
        )
        self.put("alpha/references/stage-1.md", "# Stage 1\n\nDispatch the role your binding names.\n")
        self.put("alpha/references/claude-code.md", "Ask with `AskUserQuestion`; use ${CLAUDE_SKILL_DIR}.\n")
        self.put("alpha/references/codex.md", "Call `spawn_agent` with `fork_turns`.\n")
        self.put("beta/scripts/check.py", CHECK)
        self.put(
            "solo/SKILL.md",
            SKILL.format(name="solo").replace("claude-code, codex", "claude-code (reads its own session logs)")
            + "\nCalls `SendMessage` and reads ~/.claude/projects/.\n",
        )
        # Not this tool's to judge beyond its frontmatter.
        self.put("multiagent-collab/SKILL.md", SKILL.format(name="multiagent-collab"))
        self.put("multiagent-collab/scripts/run.py", f"import requests\nWHERE = {HOME_PATH!r}\nspawn_agent = 1\n")
        self.put("rules/sample/sample.md", "Anchor the rule: `Read(//home/<user>/**/.env)`.\n")
        self.put("roles/README.md", "# Roles\n")
        self.put("roles/_shared/brief.md", "## The brief\n\nWork from the brief.\n")
        self.role("worker", hard=HARD)
        self.role("lead", dispatches='["worker", "worker-hard"]')
        self.put("roles/bindings.toml", BINDINGS)
        self.put("providers/acme/actions.md", "## How actions are done\n\n- Call `spawn_agent`.\n")
        self.put("providers/acme/dictionary.toml", support.VALID_DICTIONARY)

    def put(self, name: str, text: str | bytes) -> Path:
        file = self.clone / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return file

    def role(self, name: str, hard: str = "", dispatches: str = "[]", text: str = "# Role\n\nDo the work.\n") -> None:
        self.put(f"roles/{name}/role.toml", ROLE.format(name=name, title=name.title(), hard=hard, dispatches=dispatches))
        self.put(f"roles/{name}/ROLE.md", text)

    def skill(self, skill: str = "alpha", **changes: str) -> Path:
        """The fixture ``SKILL.md`` with frontmatter lines replaced: a key
        maps to its whole new line, or to "" to drop the line."""
        lines = SKILL.format(name=skill).split("\n")
        for key, line in changes.items():
            key = key.replace("_", "-")
            at = next(index for index, found in enumerate(lines) if found.startswith(key + ":"))
            lines[at:at + 1] = [line] if line else []
        return self.put(f"{skill}/SKILL.md", "\n".join(lines))

    def check(self) -> validate.Report:
        report = validate.check(self.locations(project=False))
        for problem in report.problems:
            self.assertIn(problem.rule, validate.RULES)
            self.assertNotIn(str(self.clone), problem.text())
            self.assertNotIn("\n", problem.text())
        return report

    def found(self) -> list[tuple[str, str]]:
        """Each problem as (file, rule), in the order reported."""
        return [(problem.file, problem.rule) for problem in self.check().problems]

    def rules(self) -> list[str]:
        return sorted({problem.rule for problem in self.check().problems})

    def messages(self, rule: str) -> list[str]:
        return [problem.text() for problem in self.check().problems if problem.rule == rule]

    def assertClean(self) -> None:
        self.assertEqual(self.check().lines(), [])

    def symlink(self, target: str | Path, link: Path, directory: bool = False) -> None:
        try:
            os.symlink(target, link, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"no symlink can be made here: {exc}")


class GoodTreeTests(TreeCase):
    def test_the_fixture_clone_is_clean(self) -> None:
        self.assertClean()

    def test_the_report_names_the_skills_and_the_role_sizes(self) -> None:
        report = self.check()
        self.assertTrue(report.ok)
        self.assertEqual(list(report.skills), ["alpha", "beta", "multiagent-collab", "solo"])
        self.assertEqual(report.skills["alpha"].providers, ("claude-code", "codex"))
        self.assertEqual(report.skills["solo"].providers, ("claude-code",))
        self.assertTrue(report.skills["multiagent-collab"].own_setup)
        self.assertFalse(report.skills["alpha"].invoke_only)
        joined = "# Role\n\nDo the work.\n\n## The brief\n\nWork from the brief.\n"
        self.assertEqual(report.role_sizes, {"lead": len(joined), "worker": len(joined)})

    def test_require_returns_the_report_or_raises_every_line(self) -> None:
        self.assertTrue(validate.require(self.locations(project=False)).ok)
        self.skill(name="name: other", description="")
        with self.assertRaises(SetupError) as caught:
            validate.require(self.locations(project=False))
        self.assertEqual(len(caught.exception.lines), 2)
        self.assertTrue(all(line.startswith("alpha/SKILL.md") for line in caught.exception.lines))

    def test_a_clone_that_is_not_there_is_the_validators_own_error(self) -> None:
        with self.assertRaises(SetupError):
            validate.check(locations.Locations(home=self.home, clone=self.root / "nowhere"))

    def test_a_directory_without_skill_md_is_not_a_skill(self) -> None:
        self.put("docs/notes.md", f"See {HOME_PATH}; call spawn_agent.\n")
        self.put("tools/other/run.py", "import requests\n")
        self.assertClean()


class FrontmatterTests(TreeCase):
    def test_name_must_be_the_directory(self) -> None:
        self.skill(name="name: other")
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-name")])
        self.skill(name="")
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-name")])

    def test_description_must_be_there_and_not_empty(self) -> None:
        for line in ("", "description:", "description:   ", 'description: ""', "description: ''"):
            with self.subTest(line):
                self.skill(description=line)
                self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-description")])

    def test_compatibility_follows_the_grammar_on_the_raw_line(self) -> None:
        bad = (
            "",
            "compatibility:",
            "compatibility: claude",
            "compatibility: codex, claude-code",
            "compatibility: claude-code,codex",
            'compatibility: "claude-code, codex"',
            "compatibility: claude-code, codex # both",
            "compatibility: claude-code, codex ",
            "compatibility:  codex",
            "compatibility: codex (a note: with a colon)",
            "compatibility: codex (a (nested) note)",
            "compatibility: codex ()",
            "compatibility: codex(note)",
            "compatibility: [claude-code, codex]",
        )
        for line in bad:
            with self.subTest(line):
                self.skill(compatibility=line)
                self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-compatibility")])
        good = (
            "compatibility: claude-code",
            "compatibility: codex",
            "compatibility: claude-code, codex",
            "compatibility: claude-code, codex (reads Claude Code's own session logs)",
        )
        for line in good:
            with self.subTest(line):
                self.skill(compatibility=line)
                self.assertClean()

    def test_a_faulty_compatibility_line_is_reported_with_its_line(self) -> None:
        self.skill(compatibility="compatibility: both")
        problem = self.check().problems[0]
        self.assertEqual((problem.file, problem.line, problem.rule), ("alpha/SKILL.md", 4, "skill-compatibility"))
        self.assertEqual(self.check().skills["alpha"].providers, ())

    def test_values_that_are_read(self) -> None:
        good = {
            "description: Use it for C# and for a:b pairs; 50% of the time.": "Use it for C# and for a:b pairs; 50% of the time.",
            'description: "Use when: the user asks # really"': "Use when: the user asks # really",
            'description: "A \\"quoted\\" word and a back\\\\slash"': 'A "quoted" word and a back\\slash',
            "description: 'It''s here: yes'": "It's here: yes",
            'description: Say "hello" and it\'s done': 'Say "hello" and it\'s done',
            "description: trailing space   ": "trailing space",
        }
        for line, value in good.items():
            with self.subTest(line):
                self.skill(description=line)
                self.assertClean()
                fields, faults = validate.parse_frontmatter(SKILL.format(name="a").replace(
                    "description: Does a work. Use when asked for it.", line))
                self.assertEqual(faults, [])
                self.assertEqual(fields["description"].value, value)

    def test_values_that_are_reported_and_not_guessed(self) -> None:
        bad = (
            "description: Use when: the user asks",
            "description: ends with a colon:",
            "description: a value # with a comment",
            "description: >",
            "description: |",
            "description: >-",
            "description: [a, b]",
            "description: {a: b}",
            'description: "no closing quote',
            'description: "closed" and more',
            'description: "a \\n escape"',
            "description: 'no closing quote",
            "description: *alias",
            "description: &anchor text",
            "description: !tag text",
            "description: - item",
            "description:\tafter a tab",
            "description:no space",
        )
        for line in bad:
            with self.subTest(line):
                self.skill(description=line)
                self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-frontmatter")])

    def test_lines_that_are_not_key_value_lines(self) -> None:
        for extra in ("  continued on a second line", "# a comment", "- item", "just words", "name: alpha",
                      "metadata:\n  version: 1"):
            with self.subTest(extra):
                self.skill(description="description: Does work.\n" + extra)
                found = self.found()
                self.assertTrue(found)
                self.assertEqual(set(found), {("alpha/SKILL.md", "skill-frontmatter")})

    def test_a_key_given_twice_names_both_lines(self) -> None:
        self.skill(description="description: One.\ndescription: Two.")
        self.assertEqual(
            self.messages("skill-frontmatter"),
            ["alpha/SKILL.md:4: [skill-frontmatter] the key description is given twice (first on line 3)"],
        )

    def test_an_empty_line_in_the_frontmatter_is_read_over(self) -> None:
        self.skill(description="description: Does work.\n")
        self.assertClean()

    def test_crlf_line_endings_are_read_as_lf(self) -> None:
        self.put("alpha/SKILL.md", SKILL.format(name="alpha").replace("\n", "\r\n"))
        self.assertClean()

    def test_a_byte_order_mark_is_a_problem_and_the_rest_is_still_read(self) -> None:
        self.put("alpha/SKILL.md", "﻿" + SKILL.format(name="alpha").replace("name: alpha", "name: other"))
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-frontmatter"), ("alpha/SKILL.md", "skill-name")])

    def test_no_closing_marker_is_one_problem(self) -> None:
        self.put("alpha/SKILL.md", "---\nname: alpha\ndescription: Does work.\n\n# Alpha\n")
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-frontmatter")])
        self.assertNotIn("alpha", self.check().skills)

    def test_no_opening_marker_is_one_problem(self) -> None:
        for text in ("# Alpha\n", "", "\n---\nname: alpha\n---\n", "--- \nname: alpha\n---\n"):
            with self.subTest(text):
                self.put("alpha/SKILL.md", text)
                self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-frontmatter")])

    def test_other_keys_are_allowed(self) -> None:
        self.skill(description="description: Does work.\nlicense: Apache-2.0\nallowed-tools: Read")
        self.assertClean()

    def test_the_skill_with_its_own_setup_is_checked_for_its_frontmatter(self) -> None:
        self.skill("multiagent-collab", compatibility="compatibility: everything", description="")
        self.assertEqual(
            self.found(),
            [("multiagent-collab/SKILL.md", "skill-description"), ("multiagent-collab/SKILL.md", "skill-compatibility")],
        )


class InvokeOnlyTests(TreeCase):
    INVOKE = "compatibility: claude-code, codex\ndisable-model-invocation: true"

    def test_both_declarations_or_neither(self) -> None:
        self.assertClean()
        self.skill(compatibility=self.INVOKE)
        self.put("alpha/agents/openai.yaml", OPENAI)
        self.assertClean()
        self.assertTrue(self.check().skills["alpha"].invoke_only)

    def test_the_frontmatter_alone_is_a_problem(self) -> None:
        self.skill(compatibility=self.INVOKE)
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-invoke-only")])
        self.put("alpha/agents/openai.yaml", OPENAI.replace("false", "true"))
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-invoke-only")])
        self.put("alpha/agents/openai.yaml", 'interface:\n  display_name: "Alpha"\n')
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-invoke-only")])

    def test_the_yaml_alone_is_a_problem(self) -> None:
        self.put("alpha/agents/openai.yaml", OPENAI)
        self.assertEqual(self.found(), [("alpha/agents/openai.yaml", "skill-invoke-only")])
        self.skill(compatibility="compatibility: claude-code, codex\ndisable-model-invocation: false")
        self.assertEqual(self.found(), [("alpha/agents/openai.yaml", "skill-invoke-only")])

    def test_declared_as_not_invoke_only_on_both_is_clean(self) -> None:
        self.skill(compatibility="compatibility: claude-code, codex\ndisable-model-invocation: false")
        self.put("alpha/agents/openai.yaml", OPENAI.replace("false", "true"))
        self.assertClean()
        self.assertFalse(self.check().skills["alpha"].invoke_only)

    def test_a_value_that_is_not_true_or_false(self) -> None:
        self.skill(compatibility="compatibility: claude-code, codex\ndisable-model-invocation: yes")
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-invoke-only")])

    def test_a_skill_for_one_provider_needs_that_providers_declaration_only(self) -> None:
        self.skill(compatibility="compatibility: claude-code\ndisable-model-invocation: true")
        self.assertClean()
        self.assertTrue(self.check().skills["alpha"].invoke_only)
        self.skill(compatibility="compatibility: codex")
        self.put("alpha/agents/openai.yaml", OPENAI)
        self.assertClean()
        self.assertTrue(self.check().skills["alpha"].invoke_only)

    def test_what_the_yaml_reader_cannot_read_safely_is_reported(self) -> None:
        unsafe = {
            "flow": "policy: {allow_implicit_invocation: false}\n",
            "tab": "policy:\n\tallow_implicit_invocation: false\n",
            "nested deeper": "policy:\n  inner:\n    allow_implicit_invocation: false\n",
            "under another key": "interface:\n  allow_implicit_invocation: false\n",
            "at the top": "allow_implicit_invocation: false\n",
            "not a boolean": "policy:\n  allow_implicit_invocation: no\n",
            "with a comment": "policy:\n  allow_implicit_invocation: false # never\n",
            "quoted": 'policy:\n  allow_implicit_invocation: "false"\n',
            "twice": "policy:\n  allow_implicit_invocation: false\n  allow_implicit_invocation: true\n",
            "two blocks": "policy:\n  allow_implicit_invocation: false\npolicy:\n  other: 1\n",
        }
        self.skill(compatibility=self.INVOKE)
        for name, text in unsafe.items():
            with self.subTest(name):
                self.put("alpha/agents/openai.yaml", text)
                found = self.found()
                self.assertIn(("alpha/agents/openai.yaml", "skill-invoke-only"), found)
                self.assertEqual({rule for _, rule in found}, {"skill-invoke-only"})

    def test_the_yaml_reader(self) -> None:
        read = validate.read_implicit_invocation
        self.assertEqual(read(OPENAI), (False, []))
        self.assertEqual(read(OPENAI.replace("\n", "\r\n")), (False, []))
        self.assertEqual(read("# only a comment\n"), (None, []))
        self.assertEqual(read("policy:\n    # why\n    allow_implicit_invocation: true\n    other: 1\n"), (True, []))
        self.assertEqual(read("policy:\ninterface:\n  name: x\n"), (None, []))

    def test_a_yaml_that_is_not_text(self) -> None:
        self.put("alpha/agents/openai.yaml", b"\xff\xfe\x00policy")
        self.assertEqual(self.found(), [("alpha/agents/openai.yaml", "skill-invoke-only")])


class ScriptTests(TreeCase):
    def test_python_imports_outside_the_standard_library(self) -> None:
        cases = {
            "import requests\n": 1,
            "import json\nimport yaml.loader\n": 2,
            "from requests import get\n": 1,
            "def f():\n    import numpy as np\n": 2,
            "try:\n    import tomli\nexcept ImportError:\n    tomli = None\n": 2,
            "import json, requests\n": 1,
            "from wfsetup import cli\n": 1,
        }
        for text, line in cases.items():
            with self.subTest(text):
                self.put("alpha/scripts/tool.py", text)
                problems = self.check().problems
                self.assertEqual([(p.file, p.line, p.rule) for p in problems], [("alpha/scripts/tool.py", line, "script-import")])

    def test_python_imports_that_are_allowed(self) -> None:
        self.put(
            "alpha/scripts/tool.py",
            "from __future__ import annotations\nimport os, sys\nimport xml.etree.ElementTree\nimport tomllib\n"
            "import common\nfrom common import load\nfrom . import common as again\nfrom .common import load\n"
            "import scripts.common\n",
        )
        self.assertClean()

    def test_a_module_of_another_skill_is_not_local(self) -> None:
        self.put("beta/scripts/tool.py", "import common\n")
        self.assertEqual(self.found(), [("beta/scripts/tool.py", "script-import")])

    def test_a_python_script_that_does_not_parse(self) -> None:
        for text in ("def broken(:\n", "import json\n\x00", "x = " + "(" * 500 + ")" * 500 + "\n"):
            with self.subTest(text[:20]):
                self.put("alpha/scripts/tool.py", text)
                self.assertIn(self.found(), ([("alpha/scripts/tool.py", "script-syntax")], []))
        self.put("alpha/scripts/tool.py", "def broken(:\n")
        self.assertEqual(self.found(), [("alpha/scripts/tool.py", "script-syntax")])
        self.put("alpha/scripts/tool.py", b"\xff\xfe not text")
        self.assertEqual(self.found(), [("alpha/scripts/tool.py", "script-syntax")])

    def test_node_imports_outside_the_built_ins(self) -> None:
        cases = (
            'import _ from "lodash";\n',
            "import x from 'left-pad'\n",
            'import {\n  a,\n  b,\n} from "@scope/pkg";\n',
            'import "side-effect";\n',
            'export { a } from "other-package";\n',
            'const x = require("express");\n',
            'const x = await import("chalk");\n',
            'import fs from "fs-extra";\n',
        )
        for name in ("tool.mjs", "tool.js", "tool.cjs"):
            for text in cases:
                with self.subTest(name=name, text=text):
                    file = self.put(f"alpha/scripts-node/{name}", text)
                    self.assertEqual(self.found(), [(f"alpha/scripts-node/{name}", "script-import")])
                    file.unlink()

    def test_node_imports_that_are_allowed(self) -> None:
        self.put(
            "alpha/scripts-node/tool.mjs",
            'import fs from "node:fs";\nimport path from "path";\nimport { readFile } from "fs/promises";\n'
            'import { a } from "./common.mjs";\nimport { b } from "../scripts-node/common.mjs";\n'
            'const os = require("os");\nconst later = await import("node:zlib");\n'
            'const text = "imported from the file";\n',
        )
        self.assertClean()

    def test_a_node_import_is_reported_at_its_line(self) -> None:
        self.put("alpha/scripts-node/tool.mjs", 'import fs from "node:fs";\nimport {\n  a,\n} from "lodash";\n')
        problem = self.check().problems[0]
        self.assertEqual((problem.line, problem.rule), (4, "script-import"))

    def test_a_literal_path_that_leaves_the_skill(self) -> None:
        self.put("alpha/scripts/tool.py", 'from pathlib import Path\nOTHER = Path(__file__).parent / "../../beta/scripts"\n')
        self.assertEqual(self.found(), [("alpha/scripts/tool.py", "script-path")])
        self.put("alpha/scripts/tool.py", 'import os\nOTHER = os.path.join("..", "..\\\\..", "x")\n')
        self.assertEqual(self.found(), [("alpha/scripts/tool.py", "script-path")])
        self.put("alpha/scripts/tool.py", "X = 1\n")
        self.put("alpha/scripts-node/tool.mjs", 'import { a } from "../../beta/x.mjs";\n')
        self.assertEqual(self.found(), [("alpha/scripts-node/tool.mjs", "script-path")])

    def test_a_literal_path_that_stays_in_the_skill(self) -> None:
        self.put(
            "alpha/scripts/tool.py",
            'A = "../references/stage-1.md"\nB = "./x/../../SKILL.md"\nC = "see ../../other for more"\nD = ".."\n'
            'E = "a..b/c"\nF = "..."\n',
        )
        self.put("alpha/scripts-node/tool.mjs", 'const a = "../references/stage-1.md";\n')
        self.assertClean()

    def test_no_script_is_run_or_imported(self) -> None:
        marker = self.root / "ran"
        body = f"open({str(marker)!r}, 'w').close()\nraise SystemExit(3)\n"
        self.put("alpha/scripts/settings.py", LAUNCHER + body)
        self.put("beta/scripts/settings.py", LAUNCHER + body)
        self.put("beta/scripts/check.py", CHECK + body)
        self.put("alpha/scripts/tool.py", "import json\n" + body)
        self.check()
        self.assertFalse(marker.exists())


class MachinePathTests(TreeCase):
    PLACES = (
        "alpha/SKILL.md",
        "alpha/references/stage-1.md",
        "alpha/references/codex.md",
        "alpha/scripts/tool.py",
        "solo/SKILL.md",
        "rules/sample/sample.md",
        "roles/worker/ROLE.md",
        "roles/_shared/brief.md",
        "roles/README.md",
        "providers/acme/actions.md",
        "tools/setup/defaults.toml",
    )

    def append(self, name: str, text: str) -> None:
        file = self.clone / name
        file.write_bytes(file.read_bytes() + text.encode("utf-8"))

    def test_each_form_is_found(self) -> None:
        for path in (HOME_PATH, MAC_PATH, MOUNT_PATH, DRIVE_PATH, DRIVE_PATH_ESCAPED, DRIVE_PATH_SLASH, WSL_PATH,
                     SLASH + HOME_PATH, "file://" + HOME_PATH):
            with self.subTest(path):
                self.put("rules/sample/sample.md", f"line one\nIt lives at `{path}` here.\n")
                problems = self.check().problems
                self.assertEqual([(p.file, p.line, p.rule) for p in problems], [("rules/sample/sample.md", 2, "machine-path")])

    def test_every_installed_text_is_looked_at(self) -> None:
        for name in self.PLACES:
            with self.subTest(name):
                file = self.clone / name
                before = file.read_bytes()
                self.append(name, f"\n# see {HOME_PATH}\n")
                self.assertEqual(self.found(), [(name, "machine-path")])
                file.write_bytes(before)

    def test_placeholders_and_path_forms_pass(self) -> None:
        home, mount = SLASH + "home" + SLASH, SLASH + "mnt" + SLASH
        forms = (
            f"{home}<user>/project", f"/{home}<user>/**/.env", f"{home}$USER/x", f"{home}{{user}}/x", f"{home}*/x",
            f"{home}\\w", f"{mount}<drive>/clone", f"{mount}\\w", f"{mount}data/x", "C:" + "\\<dir>", "<drive>:" + "\\Users",
            "~/.agents/workflow.toml", "%USERPROFILE%\\.codex", "$HOME/.claude", f"docs{home}index.md",
            f"https://example.com{home}page", f"https://example.com{SLASH}Users{SLASH}list", "see: /opt and /srv",
            "ratio 3:/4", "http://localhost:8080/x", "\\\\wsl.localhost\\<distro>\\home", "key:\\n",
        )
        for form in forms:
            with self.subTest(form):
                self.put("rules/sample/sample.md", f"A form: `{form}`.\n")
                self.assertClean()

    def test_what_is_not_installed_is_not_looked_at(self) -> None:
        self.put("alpha/scripts/__pycache__/tool.cpython-313.pyc", f"compiled at {HOME_PATH}".encode())
        self.put("README.md", f"The clone is at {MOUNT_PATH}.\n")
        self.assertClean()

    def test_an_installed_file_that_is_not_text_is_reported_and_not_skipped(self) -> None:
        # Review finding S12: such a file was skipped without a word, and
        # is installed through the skill's link all the same.
        cases = {
            "a NUL byte": b"\x00\x01" + HOME_PATH.encode() + b"\xff",
            "Latin-1": b"caf\xe9 " + HOME_PATH.encode(),
            "UTF-16": ("see " + HOME_PATH).encode("utf-16"),
        }
        for name, data in cases.items():
            with self.subTest(name):
                file = self.put("alpha/examples/data.txt", data)
                self.assertEqual(self.found(), [("alpha/examples/data.txt", "not-text")])
                file.unlink()
        self.put("alpha/examples/data.txt", b"\x00\x01")
        self.put("rules/sample/picture.dat", b"\xff\xfe\x00")
        self.assertEqual(self.rules(), ["not-text"])
        self.assertEqual(len(self.found()), 2)

    def test_a_type_gitattributes_declares_binary_is_not_reported(self) -> None:
        self.put("alpha/examples/picture.png", b"\x89PNG\x00\x01")
        self.put("alpha/examples/table.dat", b"\x00\x01")
        self.put(".gitattributes", "* text=auto eol=lf\n# a comment binary\n*.png binary\nalpha/examples/table.dat binary\n")
        self.assertClean()
        # ``-text`` keeps a text file's bytes; it does not make a file binary.
        self.put(".gitattributes", "*.png -text\nalpha/examples/table.dat binary\n")
        self.assertEqual(self.found(), [("alpha/examples/picture.png", "not-text")])

    def test_a_file_reported_by_its_own_rule_is_not_reported_twice(self) -> None:
        self.put("alpha/SKILL.md", b"\xff\xfe\x00")
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-file")])

    def test_more_forms_of_a_machine_path(self) -> None:
        # Review finding S12: each of these passed.
        back = "\\"
        forms = {
            "the root user's home directory": SLASH + "root" + SLASH + "work" + SLASH + "x",
            "a WSL share": SLASH + SLASH + "wsl.localhost" + SLASH + "Ubuntu" + SLASH + "x",
            "a drive, in the form of a Unix shell on Windows": SLASH + "c" + SLASH + "Users" + SLASH + "someone",
            "a network share": back + back + "fileserver" + back + "share" + back + "x",
            "a home directory": SLASH + "home" + SLASH + "\u00e9milie" + SLASH + "x",
        }
        forms_too = {
            "a drive, in the form of a Unix shell on Windows": SLASH + "cygdrive" + SLASH + "d" + SLASH + "work",
            "a network share": back * 4 + "fileserver" + back * 2 + "share",
            "a WSL share": SLASH + SLASH + "wsl$" + SLASH + "Ubuntu",
        }
        for kind, form in [*forms.items(), *forms_too.items()]:
            with self.subTest(form):
                self.put("rules/sample/sample.md", f"See `{form}` for it.\n")
                found = self.messages("machine-path")
                self.assertEqual(len(found), 1, found)
                self.assertIn(f"holds {kind}, ", found[0])

    def test_what_only_looks_like_one_of_the_new_forms(self) -> None:
        back = "\\"
        forms = (
            SLASH + "root" + SLASH + "coder_r2",                     # a Codex task path: one name
            "https:" + SLASH + SLASH + "wsl.localhost" + SLASH + "x",
            SLASH + "c" + SLASH + "work",                            # too short to tell
            "docs" + SLASH + "cygdrive" + SLASH + "c",
            back + back + "n" + back + "t",                          # an escape in a script
            back + back + "d+" + back + "s",
            back + back + "<server>" + back + "<share>",
            back * 3 + "host" + back + "share",
        )
        for form in forms:
            with self.subTest(form):
                self.put("rules/sample/sample.md", f"A form: `{form}`.\n")
                self.assertClean()


class NameTests(TreeCase):
    """Review findings S10 and S11, and the minor on device names: what
    ``render`` would refuse, or a home could not hold, is reported here."""

    def test_an_id_longer_than_a_file_name_made_from_it_may_be(self) -> None:
        # A role id leaves room for ``-hard``: the hard definition is a file too.
        limit = validate.ID_LIMIT - len(roles.HARD_SUFFIX)
        self.role("a" * limit, hard=HARD)
        self.assertClean()
        long = "a" * (limit + 1)
        self.role(long)
        self.assertEqual(self.found(), [(f"roles/{long}/role.toml", "id-length")])
        self.assertIn(f"at most {limit}", self.messages("id-length")[0])

    def test_a_252_character_id_does_not_pass(self) -> None:
        # The review's case: it passed validation and failed at the write.
        try:
            self.role("a" * 252)
        except OSError as exc:
            self.skipTest(f"no such name can be made here: {exc}")
        self.assertIn("id-length", self.rules())

    def test_a_long_skill_or_rule_name(self) -> None:
        long = "b" * (validate.ID_LIMIT + 1)
        self.put(f"{long}/SKILL.md", SKILL.format(name=long))
        self.put(f"rules/{long}/rule.md", "A rule.\n")
        self.assertEqual(self.found(), [(f"{long}/SKILL.md", "id-length"), (f"rules/{long}", "id-length")])

    def test_a_skill_or_rule_name_that_is_not_an_id(self) -> None:
        for name in ("a b", "x_y", "-x", "x--y", *(["x."] if os.name != "nt" else [])):
            with self.subTest(name):
                skill = self.put(f"{name}/SKILL.md", SKILL.format(name=f'"{name}"'))
                self.assertIn((f"{name}/SKILL.md", "id-characters"), self.found())
                skill.unlink()
                skill.parent.rmdir()
        self.put("rules/a b/rule.md", "A rule.\n")
        self.assertEqual(self.found(), [("rules/a b", "id-characters")])

    def test_a_device_name_of_windows(self) -> None:
        if os.name == "nt":
            self.skipTest("Windows cannot hold a directory of such a name, which is the rule's reason")
        for name in ("con", "nul", "aux", "prn", "com1", "lpt9"):
            with self.subTest(name):
                self.role(name)
                self.assertEqual(self.found(), [(f"roles/{name}/role.toml", "id-device-name")])
                for file in (self.clone / "roles" / name).iterdir():
                    file.unlink()
                (self.clone / "roles" / name).rmdir()
        self.role("console")
        self.role("com10")
        self.assertClean()
        self.put("aux/SKILL.md", SKILL.format(name="aux"))
        self.put("rules/nul/rule.md", "A rule.\n")
        self.assertEqual(self.found(), [("aux/SKILL.md", "id-device-name"), ("rules/nul", "id-device-name")])

    def test_two_names_that_differ_only_in_letter_case(self) -> None:
        if not locations.paths.CASE_SENSITIVE:
            self.skipTest("this file system cannot hold the two")
        try:
            self.put("rules/Sample/rule.md", "A rule.\n")
        except OSError:
            self.skipTest("this file system cannot hold the two")
        if len(os.listdir(self.clone / "rules")) < 2:
            self.skipTest("this file system cannot hold the two")
        found = self.found()
        self.assertIn(("rules/sample", "id-case"), found)
        self.assertIn("differs from 'Sample' only in letter case", self.messages("id-case")[0])

    def test_a_loaded_role_named_as_a_skill(self) -> None:
        # ``render`` stops on it; before, validation passed it.
        self.role("alpha")
        self.assertClean()   # not loaded: no skill is made of it
        file = self.clone / "roles" / "alpha" / "role.toml"
        file.write_text(file.read_text(encoding="utf-8").replace("load = false", "load = true"), encoding="utf-8")
        self.assertEqual(self.found(), [("roles/alpha/role.toml", "role-skill-name")])
        self.assertIn("the clone has a skill of that name (alpha/SKILL.md)", self.messages("role-skill-name")[0])
        self.role(validate.OWN_SETUP[0])
        file = self.clone / "roles" / validate.OWN_SETUP[0] / "role.toml"
        file.write_text(file.read_text(encoding="utf-8").replace("load = false", "load = true"), encoding="utf-8")
        self.assertIn("has a setup of its own", "".join(self.messages("role-skill-name")))


class EmbeddedTextTests(TreeCase):
    """Review finding S11: what ``render`` embeds, and would refuse or be
    broken by."""

    def set_key(self, file: str, key: str, value: str) -> None:
        path = self.clone / file
        lines = path.read_text(encoding="utf-8").split("\n")
        at = next(index for index, line in enumerate(lines) if line.startswith(f"{key} = "))
        lines[at] = f"{key} = {value}"
        path.write_bytes("\n".join(lines).encode("utf-8"))

    def test_a_control_character_in_a_single_line_field(self) -> None:
        self.role("planner")
        cases = {
            "a lone CR": '"Plan\\rner"', "a NUL": '"Plan\\u0000ner"', "a line feed": '"Plan\\nner"',
            "a tab": '"Plan\\tner"', "a line separator": '"Plan\\u2028ner"', "NEL": '"Plan\\u0085ner"',
            "a direction override": '"Plan\\u202Ener"', "an escape": '"Plan\\u001Bner"',
        }
        for key in ("title", "description"):
            for name, value in cases.items():
                with self.subTest(key=key, case=name):
                    self.role("planner")
                    self.set_key("roles/planner/role.toml", key, value)
                    self.assertEqual(self.found(), [("roles/planner/role.toml", "field-control")])
                    problem = self.check().problems[0]
                    self.assertEqual(problem.key, key)
                    self.assertTrue(problem.text().isprintable(), problem.text())
                    self.assertIn("U+", problem.message)

    def test_a_field_longer_than_its_limit(self) -> None:
        self.role("planner")
        self.set_key("roles/planner/role.toml", "title", '"' + "T" * validate.TITLE_LIMIT + '"')
        self.set_key("roles/planner/role.toml", "description", '"' + "D" * validate.DESCRIPTION_LIMIT + '"')
        self.assertClean()
        self.set_key("roles/planner/role.toml", "title", '"' + "T" * 1_000_000 + '"')
        self.set_key("roles/planner/role.toml", "description", '"' + "D" * (validate.DESCRIPTION_LIMIT + 1) + '"')
        self.assertEqual(self.found(), [("roles/planner/role.toml", "field-length")] * 2)
        self.assertEqual(sorted(problem.key for problem in self.check().problems), ["description", "title"])

    def test_a_marker_line_in_a_text_render_embeds(self) -> None:
        markers = ("# workflow-setup:end starting-role", "<!-- workflow-setup:start process -->",
                   "  #workflow-setup:start", "<!--workflow-setup:end-->")
        places = ("roles/worker/ROLE.md", "roles/_shared/brief.md", "providers/acme/actions.md")
        for place in places:
            original = (self.clone / place).read_bytes()
            for marker in markers:
                with self.subTest(place=place, marker=marker):
                    self.put(place, original + f"\nA line.\n{marker}\nAnother.\n".encode())
                    self.assertEqual(self.found(), [(place, "text-marker")])
            # A sentence that mentions the words is not a marker.
            self.put(place, original + b"\nSetup writes `# workflow-setup:start` before its block.\n")
            self.assertClean()
            self.put(place, original)

    def test_a_marker_in_a_single_line_field(self) -> None:
        self.role("planner")
        self.set_key("roles/planner/role.toml", "description", '"# workflow-setup:end starting-role"')
        self.assertEqual(self.found(), [("roles/planner/role.toml", "text-marker")])

    def test_a_carriage_return_of_its_own_in_a_text_render_embeds(self) -> None:
        for place in ("roles/worker/ROLE.md", "roles/_shared/brief.md", "providers/acme/actions.md"):
            with self.subTest(place=place):
                original = (self.clone / place).read_bytes()
                self.put(place, original.replace(b"\n", b"\r\n"))   # a Windows checkout
                self.assertClean()
                self.put(place, original + b"one\rtwo\n")
                self.assertEqual(self.found(), [(place, "text-carriage-return")])
                self.assertEqual(self.check().problems[0].line, original.count(b"\n") + 1)
                self.put(place, original)

    def test_the_size_of_the_action_notes(self) -> None:
        original = (self.clone / "providers/acme/actions.md").read_bytes()
        self.put("providers/acme/actions.md", original + b"x" * (validate.ACTIONS_LIMIT - len(original)))
        self.assertClean()
        self.put("providers/acme/actions.md", original + b"x" * validate.ACTIONS_LIMIT)
        self.assertEqual(self.found(), [("providers/acme/actions.md", "provider-actions-size")])

    def test_a_control_character_in_a_binding_or_a_dictionary(self) -> None:
        table = (self.clone / "roles/bindings.toml").read_text(encoding="utf-8")
        self.put("roles/bindings.toml", table.replace("Reads the stage", "Reads\\u202E the stage"))
        self.assertEqual(self.found(), [("roles/bindings.toml", "field-control")])
        self.assertEqual(self.check().problems[0].key, "binding[2].note")
        self.put("roles/bindings.toml", table)
        text = (self.clone / "providers/acme/dictionary.toml").read_text(encoding="utf-8")
        self.put("providers/acme/dictionary.toml", text.replace('note = "May change."', 'note = "May\\rchange."'))
        self.assertIn(("providers/acme/dictionary.toml", "field-control"), self.found())

    def test_every_new_rule_has_its_meaning(self) -> None:
        for rule in ("not-text", "id-characters", "id-length", "id-device-name", "id-case", "role-skill-name",
                     "field-control", "field-length", "text-carriage-return", "text-marker", "provider-actions-size"):
            self.assertIn(rule, validate.RULES)


class ProviderNameTests(TreeCase):
    def test_a_tool_name_in_shared_text(self) -> None:
        for term in ("AskUserQuestion", "SendMessage", "subagent_type", "spawn_agent", "wait_agent", "followup_task",
                     "fork_turns", "${CLAUDE_SKILL_DIR}", "$CLAUDE_PROJECT_DIR", "$ARGUMENTS", "$CODEX_HOME",
                     "the `Agent` tool", "the Bash tool", "the `Write` tool"):
            with self.subTest(term):
                self.put("alpha/references/stage-1.md", f"# Stage\n\nThen use {term} for it.\n")
                problems = self.check().problems
                self.assertEqual(
                    [(p.file, p.line, p.rule) for p in problems], [("alpha/references/stage-1.md", 3, "provider-name")]
                )

    def test_every_listed_term_is_found(self) -> None:
        for provider, terms in validate.PROVIDER_TERMS.items():
            for term in terms:
                with self.subTest(provider=provider, term=term):
                    self.put("alpha/SKILL.md", SKILL.format(name="alpha") + f"\nCall `{term}`.\n")
                    self.assertEqual(self.found(), [("alpha/SKILL.md", "provider-name")])

    def test_every_shared_file_of_a_skill_is_looked_at(self) -> None:
        for name in ("alpha/SKILL.md", "alpha/references/stage-1.md", "alpha/scripts/tool.py", "alpha/references/notes/x.md"):
            with self.subTest(name):
                file = self.clone / name
                before = file.read_bytes() if file.exists() else None
                self.put(name, (before or b"").decode() + "\n# call spawn_agent\n")
                self.assertEqual(self.found(), [(name, "provider-name")])
                file.write_bytes(before) if before is not None else file.unlink()

    def test_a_providers_own_files_may_name_its_tools(self) -> None:
        self.put("alpha/references/claude-code.md", "Call `SendMessage`, `spawn_agent` and the `Agent` tool.\n")
        self.put("alpha/references/codex.md", "Call `spawn_agent` with $CODEX_HOME.\n")
        self.put("alpha/agents/openai.yaml", 'interface:\n  default_prompt: "Use spawn_agent."\n')
        self.put("providers/acme/actions.md", "Call `spawn_agent` and `SendMessage`.\n")
        self.put("rules/sample/sample.md", "Use the Write tool.\n")
        self.assertClean()

    def test_a_skill_for_one_provider_may_name_what_it_reads(self) -> None:
        self.put("solo/references/notes.md", "Call `SendMessage` and read ${CLAUDE_SKILL_DIR}.\n")
        self.assertClean()
        self.put("solo/SKILL.md", SKILL.format(name="solo") + "\nCall `SendMessage`.\n")
        self.assertEqual(
            [(p.file, p.line, p.rule) for p in self.check().problems],
            [("solo/SKILL.md", 11, "provider-name"), ("solo/references/notes.md", 1, "provider-name"),
             ("solo/references/notes.md", 1, "provider-name")],
        )

    def test_prose_is_not_flagged(self) -> None:
        self.put(
            "alpha/references/stage-1.md",
            "Dispatch the Agent. Write the file, then Read it and Edit it. Bash is a shell; Task one is done.\n"
            "The setup tool, a file-editing tool and your shell tool. Run $skill and ${name}; my_spawn_agent_x.\n"
            "Send a message, ask the user a question, follow up with the agent. Arguments: $1 and $ARGUMENTSX.\n",
        )
        self.assertClean()

    def test_role_text_names_no_provider_tool(self) -> None:
        for name in ("roles/worker/ROLE.md", "roles/_shared/brief.md", "roles/worker/role.toml"):
            with self.subTest(name):
                file = self.clone / name
                before = file.read_bytes()
                file.write_bytes(before + b"\n# then call SendMessage\n")
                self.assertEqual(self.found(), [(name, "provider-name")])
                file.write_bytes(before)


class SymlinkTests(TreeCase):
    def test_a_linked_file_in_a_skill(self) -> None:
        self.symlink(self.clone / "alpha" / "scripts" / "common.py", self.clone / "alpha" / "scripts" / "linked.py")
        self.assertEqual(self.found(), [("alpha/scripts/linked.py", "symlink")])

    def test_a_linked_directory_is_reported_and_not_entered(self) -> None:
        self.put("outside/run.py", "import requests\n")
        self.symlink(self.clone / "outside", self.clone / "alpha" / "vendored", directory=True)
        self.assertEqual(self.found(), [("alpha/vendored", "symlink")])

    def test_a_loop_of_links_ends(self) -> None:
        self.symlink(self.clone / "alpha", self.clone / "alpha" / "again", directory=True)
        self.symlink("self.md", self.clone / "alpha" / "references" / "self.md")
        self.assertEqual(self.found(), [("alpha/again", "symlink"), ("alpha/references/self.md", "symlink")])

    def test_a_skill_md_that_is_a_link_to_itself(self) -> None:
        (self.clone / "alpha" / "SKILL.md").unlink()
        self.symlink("SKILL.md", self.clone / "alpha" / "SKILL.md")
        self.assertEqual(self.found(), [("alpha/SKILL.md", "source-unreadable"), ("alpha/SKILL.md", "symlink")])

    def test_a_linked_skill_directory(self) -> None:
        self.symlink(self.clone / "alpha", self.clone / "delta", directory=True)
        self.assertEqual(self.found(), [("delta", "symlink")])

    def test_a_link_in_a_role_or_a_rule(self) -> None:
        self.symlink(self.clone / "roles" / "_shared" / "brief.md", self.clone / "roles" / "_shared" / "other.md")
        self.symlink(self.clone / "rules" / "sample" / "sample.md", self.clone / "rules" / "sample" / "other.md")
        self.assertEqual(self.found(), [("roles/_shared/other.md", "symlink"), ("rules/sample/other.md", "symlink")])

    @unittest.skipUnless(os.name == "nt", "a junction is a Windows link")
    def test_a_junction_is_a_link(self) -> None:
        import _winapi

        self.put("outside/run.py", "import requests\n")
        _winapi.CreateJunction(str(self.clone / "outside"), str(self.clone / "alpha" / "vendored"))
        self.assertEqual(self.found(), [("alpha/vendored", "symlink")])

    def test_a_link_that_leads_nowhere(self) -> None:
        self.symlink("gone.md", self.clone / "alpha" / "references" / "dangling.md")
        self.assertEqual(self.found(), [("alpha/references/dangling.md", "symlink")])


class HostileInputTests(TreeCase):
    def test_a_binary_skill_md(self) -> None:
        for data in (b"\xff\xfe\x00\x01binary", b"---\nname: alpha\x00\n---\n", bytes(range(256)) * 4):
            with self.subTest(data[:8]):
                self.put("alpha/SKILL.md", data)
                self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-file")])

    def test_a_directory_named_skill_md(self) -> None:
        (self.clone / "alpha" / "SKILL.md").unlink()
        self.put("alpha/SKILL.md/inner.md", "text\n")
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-file")])

    def test_an_empty_skill_md(self) -> None:
        self.put("alpha/SKILL.md", b"")
        self.assertEqual(self.found(), [("alpha/SKILL.md", "skill-frontmatter")])

    def test_a_huge_file_is_reported_and_not_read(self) -> None:
        with mock.patch.object(validate, "MAX_FILE_BYTES", 4096):
            self.assertClean()
            self.put("alpha/SKILL.md", SKILL.format(name="alpha") + "x" * 5000)
            self.put("beta/references/big.md", "y" * 4097)
            self.put("beta/references/fits.md", "y" * 4096)
            self.assertEqual(self.found(), [("alpha/SKILL.md", "file-too-large"), ("beta/references/big.md", "file-too-large")])

    @unittest.skipUnless(support.can_lock_directories(), "permissions do not keep this process out")
    def test_an_unreadable_file(self) -> None:
        for name in ("alpha/SKILL.md", "alpha/scripts/tool.py", "roles/worker/ROLE.md", "providers/acme/actions.md"):
            with self.subTest(name):
                file = self.clone / name
                file.chmod(0)
                try:
                    found = self.found()
                finally:
                    file.chmod(0o644)
                self.assertEqual(found, [(name, "source-unreadable")])

    @unittest.skipUnless(support.can_lock_directories(), "permissions do not keep this process out")
    def test_an_unreadable_directory(self) -> None:
        directory = self.clone / "alpha" / "references"
        directory.chmod(0)
        try:
            found = self.found()
        finally:
            directory.chmod(0o755)
        self.assertIn(("alpha/references", "source-unreadable"), found)
        self.assertIn(("roles/bindings.toml", "bindings"), found)  # its stage file cannot be seen

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no FIFO here")
    def test_a_fifo_is_reported_and_never_opened(self) -> None:
        os.mkfifo(self.clone / "alpha" / "references" / "pipe.md")
        self.assertEqual(self.found(), [("alpha/references/pipe.md", "source-unreadable")])

    def test_a_deep_tree_of_directories(self) -> None:
        self.put("alpha/" + "d/" * 60 + "note.md", "text\n")
        self.assertClean()

    def test_faulty_toml_and_binary_role_files(self) -> None:
        self.put("roles/worker/role.toml", b"\xff\xfe")
        self.put("roles/lead/ROLE.md", b"\xff\xfe")
        self.put("roles/bindings.toml", "schema_version = [[[\n")
        self.put("providers/acme/dictionary.toml", b"\x00\x00")
        self.put("tools/setup/defaults.toml", "not toml at all\n")
        found = self.found()
        for expected in (("roles/worker/role.toml", "role-toml"), ("roles/lead/ROLE.md", "role-text"),
                         ("roles/bindings.toml", "bindings"), ("providers/acme/dictionary.toml", "dictionary"),
                         ("tools/setup/defaults.toml", "defaults")):
            self.assertIn(expected, found)

    def test_missing_trees_are_not_a_crash(self) -> None:
        import shutil

        for name in ("roles", "providers", "rules"):
            shutil.rmtree(self.clone / name)
        self.assertEqual(self.found(), [])


class RoleTests(TreeCase):
    def edit(self, old: str, new: str, role: str = "worker") -> None:
        file = self.clone / "roles" / role / "role.toml"
        text = file.read_text(encoding="utf-8")
        self.assertIn(old, text)
        file.write_text(text.replace(old, new), encoding="utf-8", newline="\n")

    def test_every_key_of_the_format_is_required(self) -> None:
        for old, key in (
            ('includes = ["brief.md"]\n', "includes"),
            ("edits = true\n", "limits.edits"),
            ("commands = true\n", "limits.commands"),
            ("dispatches = []\n", "limits.dispatches"),
            ("dispatch = true\n", "entry.dispatch"),
            ("load = false\n", "entry.load"),
            ("start = false\n", "entry.start"),
            ('title = "Worker"\n', "title"),
            ('tier = "standard"\n', "profile.tier"),
        ):
            with self.subTest(key):
                self.role("worker", hard=HARD)
                self.edit(old, "")
                problems = [p for p in self.check().problems if p.rule == "role-toml"]
                self.assertEqual([(p.file, p.key) for p in problems], [("roles/worker/role.toml", key)])
                self.assertIn("missing", problems[0].message)

    def test_a_missing_table_is_one_problem(self) -> None:
        self.put("roles/worker/role.toml", ROLE.format(name="worker", title="W", hard="", dispatches="[]").split("[limits]")[0])
        self.assertEqual(
            [(p.key, p.rule) for p in self.check().problems if p.file == "roles/worker/role.toml"],
            [("entry", "role-toml"), ("limits", "role-toml")],
        )

    def test_types_are_checked(self) -> None:
        for old, new, key in (
            ("edits = true", 'edits = "yes"', "limits.edits"),
            ("commands = true", "commands = 1", "limits.commands"),
            ("dispatches = []", 'dispatches = "lead"', "limits.dispatches"),
            ("dispatches = []", "dispatches = [1]", "limits.dispatches"),
            ("load = false", "load = 0", "entry.load"),
            ('includes = ["brief.md"]', 'includes = "brief.md"', "includes"),
            ('includes = ["brief.md"]', 'includes = ["brief.md", "brief.md"]', "includes"),
            ('effort = "medium"', 'effort = "extreme"', "profile.effort"),
            ('title = "Worker"', "title = 3", "title"),
        ):
            with self.subTest(new):
                self.role("worker", hard=HARD)
                self.edit(old, new)
                problems = [p for p in self.check().problems if p.rule == "role-toml"]
                self.assertEqual([(p.file, p.key) for p in problems], [("roles/worker/role.toml", key)])

    def test_unknown_keys_are_problems(self) -> None:
        for old, new, key in (
            ('title = "Worker"', 'title = "Worker"\nmodel = "opus"', "model"),
            ("edits = true", "edits = true\nnetwork = false", "limits.network"),
            ("load = false", "load = false\nresume = true", "entry.resume"),
            ('effort = "medium"', 'effort = "medium"\nmodel = "x"', "profile.model"),
        ):
            with self.subTest(key):
                self.role("worker", hard=HARD)
                self.edit(old, new)
                problems = self.check().problems
                self.assertEqual([(p.file, p.key, p.rule) for p in problems], [("roles/worker/role.toml", key, "role-toml")])
                self.assertIn("unknown key", problems[0].message)

    def test_a_cache_is_one_the_format_has(self) -> None:
        # Accepted, and nothing is said where no provider maps it.
        self.edit('effort = "medium"', 'effort = "medium"\ncache = "long"')
        self.assertClean()
        self.edit('cache = "long"', 'cache = "forever"')
        problems = self.check().problems
        self.assertEqual([(p.file, p.key, p.rule) for p in problems], [("roles/worker/role.toml", "profile.cache", "role-toml")])
        self.assertIn('"forever" is not allowed; allowed values: long', problems[0].message)
        self.role("worker", hard=HARD)
        self.edit('effort = "high"', 'effort = "high"\ncache = "long"')
        problems = self.check().problems
        self.assertEqual([(p.file, p.key, p.rule) for p in problems], [("roles/worker/role.toml", "profile.hard.cache", "role-toml")])
        self.assertIn("unknown key", problems[0].message)

    def test_the_name_is_the_directory(self) -> None:
        self.edit('name = "worker"', 'name = "other"')
        self.assertEqual([(p.key, p.rule) for p in self.check().problems], [("name", "role-toml")])

    def test_a_role_directory_without_role_toml_or_role_md(self) -> None:
        (self.clone / "roles" / "lead" / "role.toml").unlink()
        (self.clone / "roles" / "worker" / "ROLE.md").unlink()
        found = self.found()
        self.assertIn(("roles/lead/role.toml", "role-toml"), found)
        self.assertIn(("roles/worker/ROLE.md", "role-text"), found)
        self.assertNotIn("worker", self.check().role_sizes)

    def test_includes_exist_in_shared(self) -> None:
        for item in ("gone.md", "../worker/ROLE.md", "sub/brief.md", "..", "BRIEF.MD.txt"):
            with self.subTest(item):
                self.role("worker", hard=HARD)
                self.edit('includes = ["brief.md"]', f'includes = ["brief.md", "{item}"]')
                problems = self.check().problems
                self.assertEqual([(p.file, p.key, p.rule) for p in problems], [("roles/worker/role.toml", "includes", "role-include")])
                self.assertNotIn("worker", self.check().role_sizes)
        self.put("roles/_shared/sub/brief.md", "## Sub\n")
        self.role("worker", hard=HARD)
        self.edit('includes = ["brief.md"]', 'includes = ["sub"]')
        self.assertEqual(self.rules(), ["role-include"])

    def test_no_includes_is_allowed(self) -> None:
        self.edit('includes = ["brief.md"]', "includes = []")
        self.assertClean()
        self.assertEqual(self.check().role_sizes["worker"], len("# Role\n\nDo the work.\n"))

    def test_the_size_limit_counts_role_md_and_its_includes_as_joined(self) -> None:
        brief = "## The brief\n\nWork from the brief.\n"
        room = roles.TEXT_LIMIT - len(brief) - len("\n")  # the empty line between the two
        self.role("worker", hard=HARD, text="x" * (room - 2) + "\n")
        report = self.check()
        self.assertEqual(report.role_sizes["worker"], roles.TEXT_LIMIT - 1)
        self.assertTrue(report.ok)
        self.role("worker", hard=HARD, text="x" * (room - 1) + "\n")
        report = self.check()
        self.assertEqual(report.role_sizes["worker"], roles.TEXT_LIMIT)
        self.assertEqual(
            report.lines(),
            ["roles/worker/ROLE.md: [role-size] with its includes the role's text is 12,000 bytes; it must stay under 12,000"],
        )

    def test_the_size_is_in_bytes_and_the_same_for_crlf_sources(self) -> None:
        self.role("worker", hard=HARD, text="# Rôle\n\nDo the work.\n\n\n")
        lf = self.check().role_sizes["worker"]
        self.assertEqual(lf, len("# Rôle\n\nDo the work.\n\n## The brief\n\nWork from the brief.\n".encode("utf-8")))
        self.role("worker", hard=HARD, text="﻿# Rôle\r\n\r\nDo the work.\r\n")
        self.put("roles/_shared/brief.md", "## The brief\r\n\r\nWork from the brief.\r\n")
        self.assertEqual(self.check().role_sizes["worker"], lf)

    def test_join_text(self) -> None:
        self.assertEqual(roles.join_text(["a\n", "b\n\n", "c"]), "a\n\nb\n\nc\n")
        self.assertEqual(roles.join_text(["only\r\n"]), "only\n")

    # --- `actions`: the sections of the action notes a role is given ---

    NOTES = "## How it is done\n\nThe head.\n\n### Dispatch\n\n- Spawn.\n\n### In dialogue\n\n- Ask in the thread.\n"

    def test_actions_is_optional_and_names_sections_of_every_providers_notes(self) -> None:
        self.put("providers/acme/actions.md", self.NOTES)
        self.assertClean()  # no `actions`: the whole file, as before
        for value in ("[]", '["dispatch"]', '["in-dialogue", "dispatch"]'):
            with self.subTest(value):
                self.role("worker", hard=HARD)
                self.edit('includes = ["brief.md"]', f'includes = ["brief.md"]\nactions = {value}')
                self.assertClean()

    def test_an_action_that_is_no_section_is_a_problem(self) -> None:
        self.put("providers/acme/actions.md", self.NOTES)
        self.put("providers/other/actions.md", "## Other\n\n### Dispatch\n\n- Spawn.\n")
        self.put("providers/other/dictionary.toml", support.VALID_DICTIONARY)
        for item, missing in (
            ("commit", "providers/acme/actions.md, providers/other/actions.md"),
            ("in-dialogue", "providers/other/actions.md"),
            ("In dialogue", "providers/acme/actions.md, providers/other/actions.md"),
        ):
            with self.subTest(item):
                self.role("worker", hard=HARD)
                self.edit('includes = ["brief.md"]', f'includes = ["brief.md"]\nactions = ["dispatch", "{item}"]')
                self.assertEqual(self.check().lines(), [
                    f"roles/worker/role.toml: [role-actions] actions: {item!r} is not a section of {missing}; a section is "
                    "named by its level-three heading, in lower case with hyphens"
                ])

    def test_the_type_of_actions_is_checked(self) -> None:
        self.put("providers/acme/actions.md", self.NOTES)
        for value in ('"dispatch"', "[1]", '["dispatch", "dispatch"]', '[""]'):
            with self.subTest(value):
                self.role("worker", hard=HARD)
                self.edit('includes = ["brief.md"]', f'includes = ["brief.md"]\nactions = {value}')
                problems = self.check().problems
                self.assertEqual([(p.file, p.key, p.rule) for p in problems], [("roles/worker/role.toml", "actions", "role-toml")])

    def test_the_sections_of_the_action_notes(self) -> None:
        head, sections = definitions.action_sections(self.NOTES.replace("\n", "\r\n"))
        self.assertEqual(head, "## How it is done\n\nThe head.\n\n")
        self.assertEqual(sections, [
            ("dispatch", "### Dispatch\n\n- Spawn.\n\n"), ("in-dialogue", "### In dialogue\n\n- Ask in the thread.\n"),
        ])
        self.assertEqual(definitions.action_sections("## No sections\n\n- One.\n"), ("## No sections\n\n- One.\n", []))
        self.assertEqual(definitions.action_id("Commands and files"), "commands-and-files")
        # No list: the whole file, byte for byte. A list: the head and the
        # sections named, in the file's order whatever the list's.
        self.assertEqual(definitions.select_actions(self.NOTES, None), self.NOTES)
        self.assertEqual(definitions.select_actions(self.NOTES, []), "## How it is done\n\nThe head.\n")
        self.assertEqual(
            definitions.select_actions(self.NOTES, ["in-dialogue", "dispatch", "nothing"]), self.NOTES,
        )
        self.assertEqual(
            definitions.select_actions(self.NOTES, ["in-dialogue"]),
            "## How it is done\n\nThe head.\n\n### In dialogue\n\n- Ask in the thread.\n",
        )


class LoadedSkillSizeTests(TreeCase):
    """A role that can be loaded gives a skill of at most
    ``validate.LOADED_SKILL_TOKENS`` on every provider."""

    def setUp(self) -> None:
        super().setUp()
        import shutil

        shutil.rmtree(self.clone / "providers" / "acme")
        for provider, text in support.FIXTURE_DICTIONARIES.items():
            self.put(f"providers/{provider}/dictionary.toml", text)
            self.put(f"providers/{provider}/actions.md", f"## How actions are done on {provider}\n\n- Dispatch a role.\n")
        self.load("lead")

    def load(self, role: str) -> None:
        file = self.clone / "roles" / role / "role.toml"
        file.write_text(file.read_text(encoding="utf-8").replace("load = false", "load = true"), encoding="utf-8", newline="\n")

    def skills(self) -> dict[tuple[str, str], entry.Made]:
        where = locations.Locations(home=self.home, clone=self.clone)
        return {(one.role, one.provider): one for one in entry.skills(where) if one.name.endswith(entry.SKILL_FILE)}

    def fill(self, provider: str, tokens: int) -> None:
        """Make the skill of lead on ``provider`` exactly ``tokens`` by setup's
        estimate: that provider's notes are long, the other's short, and the
        role's own text takes up the rest. Each stays under its own limit."""
        for name in ("claude-code", "codex"):
            filler = "x" * 6_000 if name == provider else ""
            self.put(f"providers/{name}/actions.md", f"## How actions are done on {name}\n\n- Dispatch a role.{filler}\n")

        def write(count: int) -> None:
            self.role("lead", dispatches='["worker", "worker-hard"]', text="# Role\n\n" + "y" * count + "\n")
            self.load("lead")

        write(1)
        write(1 + tokens * entry.BYTES_PER_TOKEN - self.skills()[("lead", provider)].size)
        self.assertEqual(self.skills()[("lead", provider)].tokens, tokens)

    def test_the_report_gives_each_loaded_roles_skill_on_each_provider(self) -> None:
        report = self.check()
        self.assertTrue(report.ok, report.lines())
        made = self.skills()
        self.assertEqual(set(made), {("lead", "claude-code"), ("lead", "codex")})
        self.assertEqual(report.loaded_sizes, {"lead": {
            provider: {"bytes": made[("lead", provider)].size, "tokens": made[("lead", provider)].tokens}
            for provider in ("claude-code", "codex")
        }})
        self.assertEqual(report.as_json()["loaded"], {"limit_tokens": 5000, "roles": report.loaded_sizes})
        self.assertEqual(validate.LOADED_SKILL_TOKENS, entry.COMPACTION_TOKENS)

    def test_a_role_that_is_not_loaded_is_not_measured(self) -> None:
        self.put("providers/codex/actions.md", "## Notes\n\n" + "x" * 11_000 + "\n")
        self.put("providers/claude-code/actions.md", "## Notes\n\n" + "x" * 11_000 + "\n")
        self.role("worker", hard=HARD, text="# Role\n\n" + "x" * 11_000 + "\n")
        report = self.check()
        self.assertTrue(report.ok, report.lines())
        self.assertNotIn("worker", report.loaded_sizes)

    def test_the_limit_is_the_last_size_allowed_on_either_provider(self) -> None:
        for provider in ("claude-code", "codex"):
            with self.subTest(provider):
                self.fill(provider, validate.LOADED_SKILL_TOKENS)
                self.assertClean()
                self.fill(provider, validate.LOADED_SKILL_TOKENS + 1)
                size = self.skills()[("lead", provider)].size
                self.assertEqual(self.check().lines(), [
                    f"roles/lead/ROLE.md: [loaded-skill-size] loaded as a skill on {provider} the role is about 5,001 "
                    f"tokens ({size:,} bytes, at 3 bytes a token); at most 5,000, which is what Claude Code keeps of an "
                    "invoked skill after a compaction. Cut the role's text, its includes or its actions"
                ])
                self.fill(provider, validate.LOADED_SKILL_TOKENS)

    def test_what_the_role_is_given_counts_and_what_it_is_not_given_does_not(self) -> None:
        # The role's own text, an include and the provider's notes all count.
        self.role("lead", dispatches='["worker", "worker-hard"]', text="# Role\n\n" + "x" * 9_000 + "\n")
        self.load("lead")
        self.assertClean()
        self.put("roles/_shared/brief.md", "## The brief\n\n" + "y" * 2_900 + "\n")
        self.assertClean()
        notes = "## Notes\n\n### Dispatch\n\n- Spawn.\n\n### Commit\n\n" + "z" * 4_000 + "\n"
        for provider in ("claude-code", "codex"):
            self.put(f"providers/{provider}/actions.md", notes)
        self.assertEqual(self.found(), [("roles/lead/ROLE.md", "loaded-skill-size")] * 2)
        # A section the role does not name is not in its skill.
        file = self.clone / "roles" / "lead" / "role.toml"
        file.write_text(file.read_text(encoding="utf-8").replace(
            'includes = ["brief.md"]', 'includes = ["brief.md"]\nactions = ["dispatch"]'), encoding="utf-8", newline="\n")
        self.assertClean()
        self.assertNotIn("zzzz", self.skills()[("lead", "codex")].text)

    def test_the_users_settings_do_not_decide_it(self) -> None:
        """The skill is measured with the shipped settings: a source is valid
        or not whatever home the command is run for."""
        before = self.check().loaded_sizes
        shipped = {key: one.text for key, one in self.skills().items()}
        self.write(self.user_file, '[roles.lead]\ntier = "frontier"\neffort = "max"\n')
        for key, one in self.skills().items():
            self.assertNotEqual(one.text, shipped[key], key)  # the user's profile is in the installed skill
        self.assertEqual(self.check().loaded_sizes, before)
        self.write(self.user_file, "this is not TOML =\n")
        self.assertEqual(self.check().loaded_sizes, before)
        self.assertClean()

    def test_the_rule_does_not_move_with_the_figure_render_flags_by(self) -> None:
        with mock.patch.object(entry, "COMPACTION_TOKENS", 10):
            self.assertClean()

    def test_sources_no_skill_can_be_made_from_are_another_rules_to_report(self) -> None:
        (self.clone / "providers" / "codex" / "dictionary.toml").write_bytes(b"schema_version = 1\n")
        found = self.found()
        self.assertTrue(found)
        self.assertNotIn("loaded-skill-size", [rule for _, rule in found])

    def test_a_reason_no_other_rule_gave_is_reported(self) -> None:
        with mock.patch.object(entry, "skills", side_effect=SetupError("the role lead: no profile")):
            self.assertEqual(self.check().lines(), [
                "roles: [loaded-skill-size] a loaded role's skill cannot be made, so its size is not known: "
                "the role lead: no profile"
            ])

    def test_dispatches_name_real_definitions(self) -> None:
        self.role("lead", dispatches='["worker", "worker-hard", "lead"]')
        self.assertClean()
        for item in ("nobody", "lead-hard", "worker_hard", "_shared", "Worker"):
            with self.subTest(item):
                self.role("lead", dispatches=f'["worker", "{item}"]')
                problems = self.check().problems
                self.assertEqual(
                    [(p.file, p.key, p.rule) for p in problems], [("roles/lead/role.toml", "limits.dispatches", "role-dispatch")]
                )
                self.assertIn("lead, worker, worker-hard", problems[0].message)

    def test_no_definition_id_is_a_key_of_the_codex_agents_table(self) -> None:
        for name in ("enabled", "max-threads", "max-depth", "interrupt-message", "default-subagent-model"):
            with self.subTest(name):
                self.role(name)
                self.assertEqual(self.found(), [(f"roles/{name}/role.toml", "role-reserved")])
                import shutil

                shutil.rmtree(self.clone / "roles" / name)
        self.role("max")
        self.role("threads", hard=HARD)
        self.assertClean()

    def test_the_hard_definition_id_is_checked_too(self) -> None:
        with mock.patch.object(validate, "RESERVED_IDS", frozenset({"worker_hard"})):
            self.assertEqual(self.found(), [("roles/worker/role.toml", "role-reserved")])
        self.assertEqual(
            set(validate.CODEX_AGENTS_KEYS) | set(validate.CODEX_AGENTS_KEYS_UNVERIFIED), validate.RESERVED_IDS
        )
        self.assertIn("max_concurrent_threads_per_session", validate.RESERVED_IDS)

    def test_a_hard_definition_that_is_also_a_role(self) -> None:
        self.role("worker-hard")
        self.assertEqual([(p.file, p.key, p.rule) for p in self.check().problems],
                         [("roles/worker/role.toml", "profile.hard", "role-toml")])

    def test_the_reader_of_profiles_is_not_made_strict(self) -> None:
        self.put("roles/plain/role.toml", 'name = "plain"\ntitle = "Plain"\ndescription = "x"\n\n[profile]\ntier = "fast"\neffort = "low"\n')
        self.assertIn("plain", roles.load_all(self.locations(project=False)))
        self.assertEqual({p.key for p in self.check().problems if p.rule == "role-toml"}, {"includes", "limits", "entry"})


class BindingsTests(TreeCase):
    ROW = '\n[[binding]]\nrole = "{role}"\nskill = "{skill}"\nstage = "{stage}"\npart = "{part}"\n'

    def row(self, role: str = "worker", skill: str = "beta", stage: str = "s.md", part: str = "owns", more: str = "") -> None:
        self.put("beta/references/s.md", "# S\n")
        self.put("roles/bindings.toml", BINDINGS + self.ROW.format(role=role, skill=skill, stage=stage, part=part) + more)

    def keys(self) -> list[str | None]:
        problems = self.check().problems
        self.assertEqual({(p.file, p.rule) for p in problems}, {("roles/bindings.toml", "bindings")})
        return [p.key for p in problems]

    def test_a_good_row(self) -> None:
        self.row(more='note = "What the part covers."\n')
        self.assertClean()

    def test_the_file_must_be_there_and_parse(self) -> None:
        (self.clone / "roles" / "bindings.toml").unlink()
        self.assertEqual(self.found(), [("roles/bindings.toml", "bindings")])
        self.put("roles/bindings.toml", "[[binding]\n")
        self.assertEqual(self.found(), [("roles/bindings.toml", "bindings")])
        # A table with no row is in the format, and good where no skill has a stage file.
        self.put("roles/bindings.toml", "schema_version = 1\n")
        self.assertEqual(self.found(), [("alpha/references/stage-1.md", "stage-unbound")])
        (self.clone / "alpha" / "references" / "stage-1.md").unlink()
        self.assertClean()

    def test_the_documented_keys(self) -> None:
        self.put("roles/bindings.toml", BINDINGS.replace("schema_version = 1\n", ""))
        self.assertEqual(self.keys(), ["schema_version"])
        self.put("roles/bindings.toml", BINDINGS.replace("schema_version = 1", "schema_version = 2"))
        self.assertEqual(self.keys(), ["schema_version"])
        self.put("roles/bindings.toml", BINDINGS.replace("schema_version = 1", 'schema_version = "1"\nextra = true'))
        self.assertEqual(self.keys(), ["extra", "schema_version"])
        self.put("roles/bindings.toml", 'schema_version = 1\nbinding = "x"\n')
        self.assertEqual(self.keys(), ["binding"])
        self.row(more="owner = true\n")
        self.assertEqual(self.keys(), ["binding[3].owner"])

    def test_a_row_has_its_four_keys_as_strings(self) -> None:
        self.put("roles/bindings.toml", BINDINGS + '\n[[binding]]\nrole = "worker"\nstage = 3\npart = ""\n')
        self.assertEqual(self.keys(), ["binding[3].part", "binding[3].skill", "binding[3].stage"])

    def test_names_are_real(self) -> None:
        for change, key in (
            ({"role": "nobody"}, "binding[3].role"),
            ({"role": "_shared"}, "binding[3].role"),
            ({"role": "worker-hard"}, "binding[3].role"),
            ({"skill": "gamma"}, "binding[3].skill"),
            ({"skill": "roles"}, "binding[3].skill"),
            ({"skill": "./beta"}, "binding[3].skill"),
            ({"stage": "gone.md"}, "binding[3].stage"),
            ({"stage": "references/s.md"}, "binding[3].stage"),
            ({"stage": "../SKILL.md"}, "binding[3].stage"),
            ({"stage": ".."}, "binding[3].stage"),
            ({"part": "Owns"}, "binding[3].part"),
            ({"part": "two words"}, "binding[3].part"),
            ({"part": "part_1"}, "binding[3].part"),
        ):
            with self.subTest(change):
                self.row(**change)
                self.assertEqual(self.keys(), [key])

    def test_a_stage_that_is_a_directory_is_not_a_stage_file(self) -> None:
        self.put("beta/references/dir.md/x.md", "# X\n")
        self.row(stage="dir.md")
        self.assertEqual(self.keys(), ["binding[3].stage"])

    def test_a_note_is_one_short_line(self) -> None:
        self.row(more=f'note = "{"n" * 200}"\n')
        self.assertClean()
        self.row(more=f'note = "{"n" * 201}"\n')
        self.assertEqual(self.keys(), ["binding[3].note"])
        self.row(more='note = "two\\nlines"\n')
        self.assertEqual(self.keys(), ["binding[3].note"])

    def test_rows_are_unique_by_role_skill_and_stage(self) -> None:
        self.row(skill="alpha", stage="stage-1.md", part="plucks")
        problems = self.check().problems
        self.assertEqual([(p.key, p.rule) for p in problems], [("binding[3]", "bindings")])
        self.assertIn("row 1", problems[0].message)


class BindingProvidersTests(TreeCase):
    """A row's skill is installed for every provider the row's role is
    made for: the role is told to read its stage file in that provider's
    skills directory."""

    ROW = '\n[[binding]]\nrole = "{role}"\nskill = "solo"\nstage = "stage-1.md"\npart = "owns"\n'

    def setUp(self) -> None:
        super().setUp()
        for provider, text in support.FIXTURE_DICTIONARIES.items():
            self.put(f"providers/{provider}/dictionary.toml", text)
            self.put(f"providers/{provider}/actions.md", f"## How actions are done on {provider}\n\n- Dispatch.\n")
        # solo is for Claude Code alone (the fixture).
        self.put("solo/references/stage-1.md", "# Stage 1\n\nDo it.\n")

    def entry(self, name: str, **flags: str) -> None:
        file = self.clone / "roles" / name / "role.toml"
        text = file.read_text(encoding="utf-8")
        for key, value in flags.items():
            before = text
            text = text.replace(f"{key} = {'false' if value == 'true' else 'true'}", f"{key} = {value}")
            self.assertTrue(text != before or f"{key} = {value}" in text, (key, text))
        file.write_text(text, encoding="utf-8", newline="\n")

    def bind(self, role: str) -> None:
        self.put("roles/bindings.toml", BINDINGS + self.ROW.format(role=role))

    def test_the_fixture_roles_are_made_for_both_providers(self) -> None:
        self.bind("worker")
        self.assertEqual(self.check().lines(), [
            "roles/bindings.toml: [bindings] binding[3].skill: the role worker is made for codex, where the skill "
            "'solo' is not installed: its compatibility line names claude-code. The role would be told to read its "
            "stage file in a skills directory that does not hold the skill. Name codex in solo/SKILL.md, or bind a "
            "role that is not made for codex"
        ])

    def test_a_role_no_provider_but_the_skills_gets_is_bound_freely(self) -> None:
        # Started only: a definition on Claude Code, and on Codex a profile.
        self.entry("worker", dispatch="false", start="true")
        self.bind("worker")
        self.assertEqual([(p.key, p.rule) for p in self.check().problems], [("binding[3].skill", "bindings")])
        # With no entry point at all the role is made for nobody.
        self.entry("worker", start="false")
        self.assertClean()
        # Loaded: a skill on both.
        self.entry("worker", load="true")
        problems = self.check().problems
        self.assertEqual([(p.key, p.rule) for p in problems], [("binding[3].skill", "bindings")])
        self.assertIn("is made for codex", problems[0].message)

    def test_a_provider_without_a_dictionary_gets_no_file_and_is_not_counted(self) -> None:
        (self.clone / "providers" / "codex" / "dictionary.toml").unlink()
        self.bind("worker")
        self.assertNotIn("bindings", [rule for _, rule in self.found()])

    def test_a_skill_for_both_providers_is_bound_to_any_role(self) -> None:
        (self.clone / "solo" / "references" / "stage-1.md").unlink()
        self.put("roles/bindings.toml", BINDINGS + self.ROW.format(role="worker").replace('"solo"', '"alpha"')
                 .replace('"worker"', '"plain-reader"'))
        self.role("plain-reader")
        self.assertClean()


class StageRowsTests(TreeCase):
    """Every stage file of a process skill has a row in the binding table
    (``stage-unbound``). A process skill holds ``references/stage-*.md``; its
    stage files are the ``.md`` files directly in ``references/`` but for
    ``conventions.md`` and the two provider files."""

    ROW = '\n[[binding]]\nrole = "{role}"\nskill = "{skill}"\nstage = "{stage}"\npart = "owns"\n'

    def bind(self, *rows: tuple[str, str, str]) -> None:
        self.put("roles/bindings.toml", BINDINGS + "".join(
            self.ROW.format(role=role, skill=skill, stage=stage) for role, skill, stage in rows))

    def test_what_counts_as_a_stage_file(self) -> None:
        self.assertEqual(validate.NOT_A_STAGE, {"conventions.md", "claude-code.md", "codex.md"})
        # The fixture: alpha is a process skill, with one stage file and the two provider files.
        self.assertClean()
        for name in ("conventions.md", "claude-code.md", "codex.md"):
            self.put(f"alpha/references/{name}", "# Notes\n\nRead this first.\n")
        self.put("alpha/references/notes/x.md", "# Below the directory\n")
        self.put("alpha/references/table.csv", "a,b\n")
        self.put("alpha/references/stage-1.txt", "not a stage file\n")
        self.put("alpha/stage-9.md", "# Not in references\n")
        self.assertClean()

    def test_a_new_stage_file_without_a_row_fails(self) -> None:
        self.put("alpha/references/stage-2.md", "# Stage 2\n")
        self.assertEqual(self.check().lines(), [
            "alpha/references/stage-2.md: [stage-unbound] no row of roles/bindings.toml names this stage file; "
            "every stage file of a process skill has a row with the role that follows it"
        ])
        self.bind(("worker", "alpha", "stage-2.md"))
        self.assertClean()

    def test_a_stage_file_under_any_name_needs_a_row(self) -> None:
        """A process skill's stage file is not always named ``stage-*``."""
        for name in ("completion.md", "abandon.md", "Stage-3.md"):
            with self.subTest(name):
                file = self.put(f"alpha/references/{name}", "# A stage\n")
                self.assertEqual(self.found(), [(f"alpha/references/{name}", "stage-unbound")])
                self.bind(("lead", "alpha", name))
                self.assertClean()
                file.unlink()
                self.put("roles/bindings.toml", BINDINGS)

    def test_letter_case_does_not_hide_a_stage_file(self) -> None:
        """A file system that folds case opens ``Stage-A.md`` for
        ``stage-a.md``: the name makes a process skill, and a stage file,
        in any case."""
        self.put("beta/references/Stage-A.md", "# Stage A\n")
        self.assertEqual(self.found(), [("beta/references/Stage-A.md", "stage-unbound")])
        self.put("beta/references/Notes.MD", "# Notes\n")
        self.put("beta/references/Conventions.MD", "# Conventions\n")
        self.put("beta/references/CODEX.md", "# How it is done on one provider\n")
        self.assertEqual(self.found(), [
            ("beta/references/Notes.MD", "stage-unbound"), ("beta/references/Stage-A.md", "stage-unbound")
        ])
        # A row names the file as it is written.
        self.bind(("worker", "beta", "Stage-A.md"), ("worker", "beta", "Notes.MD"))
        self.assertClean()
        (self.clone / "beta" / "references" / "Stage-A.md").unlink()
        self.put("beta/references/STAGE-B.MD", "# Stage B\n")
        self.bind(("worker", "beta", "STAGE-B.MD"), ("worker", "beta", "Notes.MD"))
        self.assertClean()

    def test_a_skill_with_no_stage_file_is_no_process_skill(self) -> None:
        self.put("beta/references/notes.md", "# Notes\n")
        self.put("beta/references/conventions.md", "# Conventions\n")
        self.assertClean()
        # Its first stage file makes it one, and then every file there counts.
        self.put("beta/references/stage-a.md", "# Stage A\n")
        self.assertEqual(self.found(), [
            ("beta/references/notes.md", "stage-unbound"), ("beta/references/stage-a.md", "stage-unbound")
        ])
        self.bind(("worker", "beta", "stage-a.md"), ("worker", "beta", "notes.md"))
        self.assertClean()

    def test_a_row_of_another_skill_or_another_role_does_not_count_for_it(self) -> None:
        self.put("beta/references/stage-1.md", "# Stage 1 of beta\n")
        # alpha's stage-1.md has its rows; beta's file of the same name has none.
        self.assertEqual(self.found(), [("beta/references/stage-1.md", "stage-unbound")])
        # One row is enough, whichever role it names.
        self.bind(("lead", "beta", "stage-1.md"))
        self.assertClean()

    def test_a_skill_with_its_own_setup_is_not_judged(self) -> None:
        self.put("multiagent-collab/references/stage-1.md", "# Its own\n")
        self.assertClean()

    def test_a_faulty_table_reports_its_faults_and_the_stages_it_leaves_unbound(self) -> None:
        self.put("roles/bindings.toml", 'schema_version = 1\n\n[[binding]]\nrole = "worker"\nskill = 3\nstage = ["x"]\npart = "owns"\n')
        self.assertEqual(self.found(), [
            ("alpha/references/stage-1.md", "stage-unbound"),
            ("roles/bindings.toml", "bindings"), ("roles/bindings.toml", "bindings"),
        ])
        # A table that cannot be read at all is the one fault.
        self.put("roles/bindings.toml", 'schema_version = 1\nbinding = "x"\n')
        self.assertEqual(self.found(), [("roles/bindings.toml", "bindings")])

    def test_the_repository_binds_every_stage_file(self) -> None:
        where = locations.Locations(home=self.home, clone=support.REPOSITORY)
        run = validate._Run(where)
        validate._find_skills(run)
        found = {name: sorted(file.name for file in validate.stage_files(run, source.directory))
                 for name, source in run.skills.items()}
        self.assertEqual({name: files for name, files in found.items() if files}, {
            "prd-implementation": [
                "abandon.md", "backlog-conversion.md", "completion.md", "deferred-conversion.md", "deferred.md",
                "stage-0-backlog.md",
                "stage-1-thoughts.md", "stage-2-prd.md", "stage-3-implementation.md", "stage-3-plan-tasks.md", "state.md",
            ],
            "epic-implementation": [
                "completion.md", "stage-e0-backlog.md", "stage-e1-thoughts.md", "stage-e2-charter.md", "stage-e3-roadmap.md",
            ],
        })
        self.assertEqual([p.text() for p in validate.check(where).problems if p.rule == "stage-unbound"], [])


class SettingsTests(TreeCase):
    def test_a_provider_has_its_action_notes_and_its_dictionary(self) -> None:
        (self.clone / "providers" / "acme" / "actions.md").unlink()
        self.assertEqual(self.found(), [("providers/acme/actions.md", "provider-actions")])
        self.put("providers/acme/actions.md", "  \n")
        self.assertEqual(self.found(), [("providers/acme/actions.md", "provider-actions")])
        self.put("providers/other/actions.md", "## Actions\n")
        self.put("providers/acme/actions.md", "## Actions\n")
        self.assertEqual(self.found(), [("providers/other/dictionary.toml", "dictionary")])

    def test_a_dictionary_fault_is_surfaced_with_its_key(self) -> None:
        self.put("providers/acme/dictionary.toml", support.VALID_DICTIONARY.replace('fast = "a-small"', 'fast = "nothing"')
                 .replace('checked_on_date = "2026-10-05"', 'checked_on_date = "soon"'))
        problems = self.check().problems
        self.assertEqual(
            [(p.file, p.key, p.rule) for p in problems], [("providers/acme/dictionary.toml", "checked_on_date", "dictionary")]
        )
        self.put("providers/acme/dictionary.toml", support.VALID_DICTIONARY.replace('fast = "a-small"', 'fast = "nothing"'))
        problems = self.check().problems
        self.assertEqual([(p.key, p.rule) for p in problems], [("tiers.fast", "dictionary")])

    def test_the_defaults_follow_the_settings_schema(self) -> None:
        self.put("tools/setup/defaults.toml", support.FIXTURE_DEFAULTS.replace("recommend = true", 'recommend = "yes"\nextra = 1'))
        problems = self.check().problems
        self.assertEqual(
            [(p.file, p.key, p.rule) for p in problems],
            [("tools/setup/defaults.toml", "process.extra", "defaults"), ("tools/setup/defaults.toml", "process.recommend", "defaults")],
        )
        (self.clone / "tools" / "setup" / "defaults.toml").unlink()
        self.assertEqual(self.found(), [("tools/setup/defaults.toml", "defaults")])


class LauncherTests(TreeCase):
    def test_the_launchers_are_byte_identical(self) -> None:
        self.put("beta/scripts/settings.py", LAUNCHER + "\n")
        self.assertEqual(self.found(), [("beta/scripts/settings.py", "launcher-identical")])
        self.put("beta/scripts/settings.py", LAUNCHER.replace("\n", "\r\n"))
        self.assertEqual(self.found(), [("beta/scripts/settings.py", "launcher-identical")])
        self.put("gamma/SKILL.md", SKILL.format(name="gamma"))
        self.put("gamma/scripts/settings.py", LAUNCHER + "# third\n")
        self.assertEqual(
            self.found(), [("beta/scripts/settings.py", "launcher-identical"), ("gamma/scripts/settings.py", "launcher-identical")]
        )

    def test_one_launcher_alone_has_nothing_to_differ_from(self) -> None:
        (self.clone / "beta" / "scripts" / "settings.py").unlink()
        self.assertClean()

    def test_built_in_defaults_equal_the_shipped_ones(self) -> None:
        for old, new, said in (
            ('"process.docs_dir": "docs"', '"process.docs_dir": "documents"', "process.docs_dir is 'documents' here and 'docs' there"),
            ('"process.recommend": True', '"process.recommend": 1', "process.recommend is 1 here and True there"),
            ('    "memory.dir": "docs/memory",\n', "", "memory.dir is missing"),
            ('"memory.dir": "docs/memory"', '"memory.dir": "docs/memory", "providers.x": False', "providers.x is not in"),
            ('    "roles.max_parallel_coders": 3,\n', "", "roles.max_parallel_coders is missing"),
            ('"roles.max_parallel_coders": 3', '"roles.max_parallel_coders": 4', "roles.max_parallel_coders is 4 here and 3 there"),
        ):
            with self.subTest(new):
                for name in ("alpha", "beta"):
                    self.put(f"{name}/scripts/settings.py", LAUNCHER.replace(old, new))
                problems = self.check().problems
                self.assertEqual(
                    [(p.file, p.rule) for p in problems],
                    [("alpha/scripts/settings.py", "launcher-defaults"), ("beta/scripts/settings.py", "launcher-defaults")],
                )
                self.assertIn(said, problems[0].message)

    def test_the_check_script_holds_the_process_group(self) -> None:
        self.put("beta/scripts/check.py", CHECK.replace('"one-at-a-time"', '"all-together"'))
        self.assertEqual(self.found(), [("beta/scripts/check.py", "launcher-defaults")])
        self.put("beta/scripts/check.py", CHECK.replace("}", '    "memory.dir": "docs/memory",\n}'))
        self.assertEqual(self.found(), [("beta/scripts/check.py", "launcher-defaults")])

    def test_a_change_of_the_shipped_defaults_is_seen(self) -> None:
        self.put("tools/setup/defaults.toml", support.FIXTURE_DEFAULTS.replace('docs_dir = "docs"', 'docs_dir = "planning"'))
        self.assertEqual(
            self.found(),
            [("alpha/scripts/settings.py", "launcher-defaults"), ("beta/scripts/check.py", "launcher-defaults"),
             ("beta/scripts/settings.py", "launcher-defaults")],
        )

    def test_a_built_in_that_is_not_a_literal(self) -> None:
        for text in ("BUILT_IN = dict(a=1)\n", "import json\n", "BUILT_IN = {1: 2}\n", "BUILT_IN = [1]\n",
                     "BUILT_IN = {'process.docs_dir': open('x')}\n"):
            with self.subTest(text):
                self.put("beta/scripts/check.py", text)
                self.assertEqual(self.found(), [("beta/scripts/check.py", "launcher-defaults")])

    def test_read_built_in(self) -> None:
        self.assertEqual(validate.read_built_in("X = 1\nBUILT_IN: dict = {'a': True}\n"), {"a": True})
        self.assertIsNone(validate.read_built_in("def f():\n    BUILT_IN = {'a': 1}\n"))
        self.assertIsNone(validate.read_built_in("BUILT_IN = {"))


class AllAtOnceTests(TreeCase):
    def break_things(self) -> None:
        self.skill(name="name: other", compatibility="compatibility: all")
        self.put("alpha/scripts/tool.py", "import requests\n")
        self.put("beta/references/x.md", f"At {HOME_PATH}, call spawn_agent.\n")
        self.put("beta/scripts/settings.py", LAUNCHER + "\n")
        self.role("lead", dispatches='["nobody"]')
        self.put("roles/bindings.toml", BINDINGS.replace('skill = "alpha"', 'skill = "gamma"', 1))
        self.put("providers/acme/dictionary.toml", support.VALID_DICTIONARY.replace('fast = "a-small"', 'fast = "nothing"'))
        self.put("tools/setup/defaults.toml", support.FIXTURE_DEFAULTS + "\n[other]\nx = 1\n")

    EXPECTED = [
        ("alpha/SKILL.md", "skill-name"),
        ("alpha/SKILL.md", "skill-compatibility"),
        ("alpha/scripts/tool.py", "script-import"),
        ("beta/references/x.md", "machine-path"),
        ("beta/references/x.md", "provider-name"),
        ("beta/scripts/settings.py", "launcher-identical"),
        ("providers/acme/dictionary.toml", "dictionary"),
        ("roles/bindings.toml", "bindings"),
        ("roles/lead/role.toml", "role-dispatch"),
        ("tools/setup/defaults.toml", "defaults"),
    ]

    def test_every_problem_is_returned_in_one_run_in_a_stable_order(self) -> None:
        self.break_things()
        first = self.check()
        self.assertEqual([(p.file, p.rule) for p in first.problems], self.EXPECTED)
        self.assertEqual(self.check(), first)
        ordered = sorted(first.problems, key=lambda p: (p.file, p.line or 0, p.rule, p.key or "", p.message))
        self.assertEqual(list(first.problems), ordered)

    def test_the_command_prints_them_and_exits_1(self) -> None:
        self.break_things()
        code, out, err = support.run("validate", "--home", str(self.home))
        self.assertEqual((code, err), (1, ""))
        lines = out.splitlines()
        self.assertEqual(lines[-1], "10 problems")
        self.assertEqual(lines[:-1], validate.check(self.locations(project=False)).lines())
        self.assertEqual(lines[0], "alpha/SKILL.md:2: [skill-name] 'other' is not the directory's name, 'alpha'")
        self.assertNotIn(str(self.clone), out)

    def test_the_command_as_json(self) -> None:
        self.break_things()
        code, out, err = support.run("validate", "--json", "--home", str(self.home))
        self.assertEqual((code, err), (1, ""))
        report = json.loads(out)
        self.assertEqual(report["schema_version"], 1)
        self.assertFalse(report["ok"])
        self.assertEqual([(p["file"], p["rule"]) for p in report["problems"]], self.EXPECTED)
        self.assertEqual(set(report["problems"][0]), {"file", "line", "key", "rule", "message"})
        self.assertEqual(report["problems"][0]["line"], 2)
        self.assertIsNone(report["problems"][0]["key"])
        self.assertEqual(report["roles"]["worker"], {"bytes": 57, "limit": 12000})
        self.assertEqual(report["skills"]["solo"], {"providers": ["claude-code"], "invoke_only": False, "own_setup": False})


class CommandTests(TreeCase):
    def test_a_clean_clone_exits_0(self) -> None:
        self.assertEqual(support.run("validate", "--home", str(self.home)), (0, "no problems: 4 skills, 2 roles\n", ""))
        code, out, err = support.run("validate", "--json", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(json.loads(out)["ok"])
        self.assertEqual(json.loads(out)["problems"], [])

    def test_one_problem_is_counted_in_the_singular(self) -> None:
        self.skill(name="name: other")
        code, out, _ = support.run("validate", "--home", str(self.home))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[-1], "1 problem")

    def test_its_own_error_exits_2(self) -> None:
        with mock.patch.object(locations, "CLONE", self.root / "nowhere"):
            code, out, err = support.run("validate", "--home", str(self.home))
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("error: "), err)
        self.assertEqual(err.count("\n"), 1)
        code, out, err = support.run("validate", "--home", "")
        self.assertEqual((code, out), (2, ""))
        code, _, err = support.run("validate", "--jso")
        self.assertEqual(code, 2)

    def test_the_rules_are_listed(self) -> None:
        code, out, err = support.run("validate", "--rules")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([line.split(": ", 1)[0] for line in out.splitlines()], list(validate.RULES))
        self.assertEqual(json.loads(support.run("validate", "--rules", "--json")[1]), validate.RULES)

    def test_the_command_is_listed(self) -> None:
        self.assertIn("validate", support.run("--help")[1])

    def test_the_command_writes_nothing(self) -> None:
        def snapshot() -> dict[str, tuple[int, int]]:
            return {
                str(path): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in sorted(self.root.rglob("*")) if path.is_file()
            }

        before = snapshot()
        support.run("validate", "--home", str(self.home))
        support.run("validate", "--json", "--home", str(self.home))
        self.assertEqual(snapshot(), before)


class RepositoryTests(support.ScratchCase):
    """The repository's own sources, whatever they say today."""

    def test_the_repository_is_clean(self) -> None:
        report = validate.check(self.repository(project=False))
        self.assertEqual(report.lines(), [])

    def test_the_repository_was_really_looked_at(self) -> None:
        report = validate.check(self.repository(project=False))
        self.assertIn("multiagent-collab", report.skills)
        self.assertGreaterEqual(len(report.skills), 2)
        self.assertTrue(report.role_sizes)
        for size in report.role_sizes.values():
            self.assertLess(size, roles.TEXT_LIMIT)

    def test_the_command_on_the_repository(self) -> None:
        with mock.patch.object(locations, "CLONE", support.REPOSITORY):
            code, out, err = support.run("validate", "--home", str(self.home))
        self.assertEqual((code, err), (0, ""), out)

    def test_the_validators_own_files_hold_no_machine_path(self) -> None:
        package = support.SETUP / "wfsetup"
        for file in (package / "validate.py", package / "commands" / "validate.py", Path(__file__)):
            text = file.read_text(encoding="utf-8")
            for kind, pattern in validate.MACHINE_PATHS:
                self.assertIsNone(pattern.search(text), (file.name, kind))

    def test_the_compatibility_grammar_is_the_one_agents_md_states(self) -> None:
        text = (support.REPOSITORY / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(f"`{validate.COMPATIBILITY.pattern}`", " ".join(text.split()).replace("` `", "``"))


if __name__ == "__main__":
    unittest.main()
