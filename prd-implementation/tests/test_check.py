"""Tests of scripts/check.py.

Run from the repository root:

    python -B -m unittest discover -s prd-implementation/tests
"""
import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
SCRIPTS = SKILL / "scripts"
REFERENCES = SKILL / "references"
CHECK_PY = SCRIPTS / "check.py"
RUNNER = TESTS / "audit_runner.py"

sys.path.insert(0, str(SCRIPTS))
import check  # noqa: E402

TODAY = "2026-10-05"
PLAN = "SPRINT01-PLAN-sample.md"
TASKS = "SPRINT01-TASKS-sample.md"
START = check.INDEX_START
END = check.INDEX_END

# One, two and four bytes in UTF-8; the last is two units in UTF-16.
FILLS = ("x", "é", "\u0301", "\U0001d4b3")


def example(reference: str, marker: str) -> str:
    """The first ```markdown block after the line holding ``marker``."""
    lines = (REFERENCES / reference).read_text(encoding="utf-8").split("\n")
    start = next(index for index, line in enumerate(lines) if marker in line)
    opened = next(index for index in range(start, len(lines)) if lines[index].startswith("```markdown"))
    closed = next(index for index in range(opened + 1, len(lines)) if lines[index].startswith("```"))
    return "\n".join(lines[opened + 1:closed]) + "\n"


def padded(start: str, length: int, fill: str = "x") -> str:
    """A line of exactly ``length`` characters that starts with ``start``."""
    line = start + fill * (length - len(start))
    assert len(line) == length, (len(line), length)
    return line


def deferred(*items: str, pointer: int = 9, title: bool = True) -> str:
    head = ("# Deferred items\n\n" if title else "") + f"Latest assigned: D{pointer}\n"
    return head + "".join("\n" + item for item in items)


def item(number: int = 1, sprint: str = "07 P3.4", review: str = "2026-12-01", status: str = "open",
         check_line: str | None = None, title: str = "Remove the legacy export path") -> str:
    lines = [f"### D{number} — {title}", "", f"Sprint: {sprint}", "Trigger: the export log: no line with `path=legacy`",
             f"Review by: {review}"]
    if check_line is not None:
        lines.append(f"Check: {check_line}")
    lines.append(f"Status: {status}")
    return "\n".join(lines) + "\n"


def tree(root: Path) -> dict:
    """Every path under ``root`` with its bytes, to show nothing changed."""
    found = {}
    for path in sorted(root.rglob("*")):
        found[str(path.relative_to(root))] = path.read_bytes() if path.is_file() else None
    return found


class Case(unittest.TestCase):
    """A scratch project, checked in process as a skill copied on its own."""

    def setUp(self):
        # Made real, so that a path is spelled the same in a child process.
        self.root = Path(tempfile.mkdtemp(prefix="check-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        # A copy with no clone around it, for runs as a child process.
        self.lone_script = self.root / "lone" / "skill" / "scripts" / "check.py"
        self.lone_script.parent.mkdir(parents=True)
        shutil.copyfile(CHECK_PY, self.lone_script)
        self.project = self.root / "project"
        self.docs = self.project / "docs"
        self.home = self.root / "home"
        self.docs.mkdir(parents=True)
        self.home.mkdir()
        lone = mock.patch.object(check, "SETUP_DIR", self.root / "no-clone" / "tools" / "setup")
        lone.start()
        self.addCleanup(lone.stop)

    def write(self, name: str, text: str, where: Path | None = None) -> Path:
        path = (where or self.docs) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def arguments(self, *extra: str, today: str = TODAY) -> list[str]:
        return ["--project", str(self.project), "--home", str(self.home), "--today", today, *extra]

    def run_check(self, *extra: str, today: str = TODAY) -> tuple[int, dict]:
        code, text = check.run(self.arguments("--json", *extra, today=today))
        return code, json.loads(text)

    def rules(self, *extra: str, today: str = TODAY) -> list[tuple]:
        _, report = self.run_check(*extra, today=today)
        return [(v["file"], v["line"], v["rule"]) for v in report["violations"]]

    def assertClean(self, *extra: str, today: str = TODAY) -> dict:
        code, report = self.run_check(*extra, today=today)
        self.assertEqual(report["violations"], [])
        self.assertEqual(code, 0 if not report["summary"]["past_date"] else 1)
        return report

    def child(self, *arguments: str, script: Path | None = None, runner: bool = False, env: dict | None = None,
              cwd: Path | None = None) -> tuple[int, str, str]:
        script = script or self.lone_script
        command = [sys.executable, "-B"] + ([str(RUNNER)] if runner else []) + [str(script), *arguments]
        done = subprocess.run(command, capture_output=True, cwd=str(cwd or self.root), env=env, check=False)
        self.assertNotIn(b"\r", done.stdout)
        return done.returncode, done.stdout.decode("utf-8"), done.stderr.decode("utf-8", "replace")


# --- R8.6: it executes nothing ------------------------------------------------

class SyntaxTree(unittest.TestCase):
    ALLOWED_IMPORTS = {
        "__future__", "argparse", "datetime", "json", "re", "stat", "sys", "tomllib", "unicodedata", "pathlib",
    }
    # Never, whole or in part, whatever the allowlist says.
    BANNED_MODULES = {"os", "subprocess", "importlib", "runpy", "ctypes", "socket", "shutil", "multiprocessing"}
    FORBIDDEN_NAMES = {
        "eval", "exec", "compile", "__import__", "open", "getattr", "setattr", "delattr", "globals", "locals",
        "vars", "breakpoint", "input", "__builtins__", "__loader__", "__spec__",
    }
    FORBIDDEN_ATTRIBUTES = {
        "system", "popen", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput",
        "startfile", "fork", "forkpty", "posix_spawn", "posix_spawnp", "modules", "meta_path", "path_hooks",
        "import_module", "load_module", "exec_module", "run_path", "run_module", "dlopen", "addaudithook",
        "settrace", "setprofile", "open", "write_text", "write_bytes", "unlink", "mkdir", "rmdir", "rename",
        "replace", "touch", "chmod", "lchmod", "symlink_to", "hardlink_to", "link_to", "kill", "remove",
        "removedirs", "makedirs", "rmtree", "truncate", "utime", "chown",
    }

    def faults(self, source: str) -> list[str]:
        """What ``source`` holds that check.py must not: the one walker, used
        on check.py and on the samples that show the walker catches them."""
        found = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom):
                    if node.level:
                        found.append(f"line {node.lineno}: a relative import")
                    names = [node.module or ""]
                else:
                    names = [alias.name for alias in node.names]
                for name in names:
                    if name not in self.ALLOWED_IMPORTS or name.split(".")[0] in self.BANNED_MODULES:
                        found.append(f"line {node.lineno}: the import of {name or 'a relative module'}")
            elif isinstance(node, ast.Name) and node.id in self.FORBIDDEN_NAMES:
                found.append(f"line {node.lineno}: the name {node.id}")
            elif isinstance(node, ast.Attribute):
                name = node.attr
                compiles_a_pattern = name == "compile" and isinstance(node.value, ast.Name) and node.value.id == "re"
                if compiles_a_pattern:
                    continue
                if (name in self.FORBIDDEN_ATTRIBUTES or name == "compile" or name.startswith(("exec", "spawn"))
                        or (name.startswith("__") and name.endswith("__"))):
                    found.append(f"line {node.lineno}: the attribute .{name}")
        return found

    def test_the_module_can_start_no_process_and_load_no_code(self):
        self.assertEqual(self.faults(CHECK_PY.read_text(encoding="utf-8")), [])

    def test_the_allowlist_holds_no_banned_module(self):
        self.assertEqual({name.split(".")[0] for name in self.ALLOWED_IMPORTS} & self.BANNED_MODULES, set())

    def test_the_walker_catches_what_it_forbids(self):
        for source in (
            "import subprocess", "import os", "import os.path", "from os import system", "from os.path import join",
            "import importlib", "import importlib.util", "import runpy", "import ctypes", "import socket",
            "import shutil", "import tempfile", "import re, subprocess", "from . import sibling",
            "from .sibling import name", "x = eval('1')", "exec('pass')", "compile('1', 'f', 'eval')",
            "__import__('os')", "getattr(sys, 'modules')", "open('f', 'w')",
            "import sys\nsys.modules['os'].system('x')", "p.write_text('x')", "p.write_bytes(b'x')",
            "p.replace(q)", "p.rename(q)", "p.unlink()", "p.mkdir()", "p.touch()", "p.symlink_to(q)", "p.open('w')",
            "f.__globals__", "x.__class__", "x.spawnv(0)", "x.execv('a', [])", "pattern.compile('x')",
            "def f():\n    import subprocess\n", "try:\n    import os\nexcept ImportError:\n    pass\n",
        ):
            with self.subTest(source):
                self.assertNotEqual(self.faults(source), [])

    def test_the_walker_passes_what_check_py_may_do(self):
        for source in (
            "from __future__ import annotations", "import re\nP = re.compile('x')", "from pathlib import Path",
            "import stat\nstat.S_ISDIR(0)", "import json, sys, tomllib, unicodedata, argparse, datetime",
            "p.read_bytes()", "p.lstat()", "p.is_dir()", "p.resolve(strict=True)", "sys.stdout.write('x')",
        ):
            with self.subTest(source):
                self.assertEqual(self.faults(source), [])


class ExecutesNothing(Case):
    def setUp(self):
        super().setUp()
        self.marker = self.root / "marker"
        make = f'"{sys.executable}" -c "open(r\'{self.marker}\', \'w\').close()"'
        self.plain = make
        self.checks = {
            1: make,
            2: f"python tools/checks/a.py; {make}",
            3: f"python tools/checks/a.py && {make}",
            4: f"`{make}`",
            5: f"$({make})",
            6: f"python tools/checks/a.py || {make} | {make} & touch marker-relative > marker-redirect",
            7: "touch marker-relative",
        }
        items = [item(number, check_line=line, sprint=f"07 P3.{number}") for number, line in self.checks.items()]
        # An embedded newline: the command continues on a line of its own.
        items.append(item(8, check_line="python tools/checks/a.py\n" + make, sprint="07 P3.8"))
        self.write("DEFERRED.md", deferred(*items))

    def no_marker(self):
        found = [str(path) for path in self.root.rglob("*") if path.name.startswith("marker")]
        found += [name for name in ("marker-relative", "marker-redirect") if (Path.cwd() / name).exists()]
        self.assertEqual(found, [])

    def test_the_fixture_would_leave_a_marker_if_it_were_run(self):
        subprocess.run(self.plain, shell=True, check=True, cwd=str(self.root))
        self.assertTrue(self.marker.exists())

    def test_in_process_no_check_is_run_and_nothing_changes(self):
        # What proves that nothing is started is the syntax tree above and
        # the audit hook of the child run below; here, that no marker appears.
        before = tree(self.root)
        code, report = self.run_check()
        check.run(self.arguments())
        self.no_marker()
        self.assertEqual(tree(self.root), before)
        self.assertEqual(code, 1)
        listed = {entry["number"]: entry["check"] for entry in report["deferred"]}
        for number, line in self.checks.items():
            self.assertEqual(listed[number], line)  # word for word
        self.assertEqual(listed[8], "python tools/checks/a.py")
        self.assertIn(("DEFERRED.md", "deferred-unknown-line"), [(v["file"], v["rule"]) for v in report["violations"]])

    def test_as_a_child_process_no_check_is_run_and_nothing_changes(self):
        before = tree(self.root)
        for extra in ([], ["--json"]):
            code, out, err = self.child(*self.arguments(*extra), runner=True, cwd=self.project)
            self.assertEqual(code, 1, err)
            self.assertIn(self.checks[3], out if not extra else json.loads(out)["deferred"][2]["check"])
        self.no_marker()
        self.assertEqual(tree(self.root), before)

    def test_the_audit_runner_catches_a_started_process(self):
        script = self.root / "check.py"
        script.write_text("import subprocess, sys\ndef main(argv):\n"
                          "    subprocess.run([sys.executable, '-c', 'pass'])\n    return 0\n", encoding="utf-8")
        code, _, err = self.child(script=script, runner=True)
        self.assertEqual(code, 97)
        self.assertIn("subprocess.Popen", err)

    def test_the_audit_runner_catches_a_written_and_a_renamed_file(self):
        script = self.root / "check.py"
        for body, event in (("Path('made').write_text('x')", "open"), ("Path('a').rename('b')", "os.rename"),
                            ("Path('a').replace('b')", "os.rename"), ("Path('made').mkdir()", "os.mkdir"),
                            ("os.system('exit 0')", "os.system")):
            with self.subTest(body):
                script.write_text("import os\nfrom pathlib import Path\ndef main(argv):\n    try:\n"
                                  f"        {body}\n    except OSError:\n        pass\n    return 0\n",
                                  encoding="utf-8")
                work = self.root / "work"
                shutil.rmtree(work, ignore_errors=True)
                work.mkdir()
                code, _, err = self.child(script=script, runner=True, cwd=work)
                self.assertEqual(code, 97, err)
                self.assertIn(f"caught: {event} ", err)


# --- R8.6: the limits, at each and one over -----------------------------------

class Boundaries(Case):
    def over(self, name: str, start: str, limit: int, rule: str, before: str = "", after: str = "",
             where: Path | None = None):
        """``start`` filled to ``limit`` is accepted, to one more is reported."""
        line_number = before.count("\n") + 1
        for fill in FILLS:
            for length, expected in ((limit, []), (limit + 1, [(name, line_number, rule)])):
                with self.subTest(fill=fill, length=length):
                    line = padded(start, length, fill)
                    self.write(name, before + line + "\n" + after, where)
                    found = [found for found in self.rules() if found[0] == name]
                    self.assertEqual(found, expected)

    def test_annotation_300(self):
        for start in ("> Landed 2026-10-05: ", "> Bug fix 2026-10-05: ", "> Audit 2026-10-05: PARTIAL: "):
            self.over(PLAN, start, 300, "annotation-too-long", before="### P1.1 — A step\n\n")

    def test_tasks_line_150(self):
        for start in ("- [ ] **P1.1** — ", "- [~] **P1.1** — ", "- [x] **P1.1** — ", "- [x] ~~**P1.1** — "):
            self.over(TASKS, start, 150, "tasks-line-too-long", before="## Phase 1\n\n")

    def test_backlog_item_300(self):
        self.over("BACKLOG.md", "- **B1** ", 300, "backlog-item-too-long", before="Latest assigned: B1\n\n")
        self.over("BACKLOG.md", "- **B1** **[HIGH]** ", 300, "backlog-item-too-long", before="Latest assigned: B1\n\n")

    def test_deferred_item_lines_300(self):
        head = "Latest assigned: D1\n\n"
        fields = "Sprint: 07 P3.4\nTrigger: a log: no line\nReview by: 2026-12-01\nStatus: open\n"
        self.over("DEFERRED.md", "### D1 — ", 300, "deferred-line-too-long", before=head, after=fields)
        self.over("DEFERRED.md", "Trigger: ", 300, "deferred-line-too-long",
                  before=head + "### D1 — A title\nSprint: 07 P3.4\n", after="Review by: 2026-12-01\nStatus: open\n")
        self.over("DEFERRED.md", "Check: ", 300, "deferred-line-too-long",
                  before=head + "### D1 — A title\nSprint: 07 P3.4\nTrigger: a log: no line\nReview by: 2026-12-01\n",
                  after="Status: open\n")

    def test_lesson_index_line_150(self):
        self.over("AGENTS.md", "- ", 150, "index-line-too-long", before=f"# Guide\n\n{START}\n", after=f"{END}\n",
                  where=self.project)

    def test_lesson_index_50_lines(self):
        for count, expected in ((50, []), (51, [("AGENTS.md", 3, "index-too-many-lines")])):
            lines = "".join(f"- lesson {number}\n" for number in range(count))
            self.write("AGENTS.md", f"# Guide\n\n{START}\n{lines}{END}\nafter\n", self.project)
            self.assertEqual(self.rules(), expected)

    def test_a_carriage_return_is_not_counted(self):
        annotation = padded("> Landed 2026-10-05: ", 300, "é")
        task = padded("- [ ] **P1.1** — ", 150, "é")
        self.write(PLAN, f"### P1.1 — A step\r\n\r\n{annotation}\r\n")
        self.write(TASKS, f"## Phase 1\r\n\r\n{task}\r\n")
        self.write("BACKLOG.md", "Latest assigned: B1\r\n\r\n" + padded("- **B1** ", 300) + "\r\n")
        self.write("DEFERRED.md", deferred(item(title=padded("", 300 - len("### D1 — ")))).replace("\n", "\r\n"))
        self.write("AGENTS.md", f"{START}\r\n" + padded("- ", 150) + f"\r\n{END}\r\n", self.project)
        self.assertEqual(self.rules(), [])
        self.write(PLAN, f"### P1.1 — A step\r\n\r\n{annotation}x\r\n")
        self.write(TASKS, f"## Phase 1\r\n\r\n{task}x\r\n")
        self.assertEqual(self.rules(), [(PLAN, 3, "annotation-too-long"), (TASKS, 3, "tasks-line-too-long")])

    def test_only_one_carriage_return_at_the_end_is_left_out(self):
        self.assertEqual(check.split_lines("a\r\nb\r\r\nc\rd\n\ne"), ["a", "b\r", "c\rd", "", "e"])
        self.assertEqual(check.split_lines("a\x0bb\x0cc\u2028d\n"), ["a\x0bb\x0cc\u2028d"])
        self.assertEqual(check.split_lines(""), [])

    def test_a_byte_order_mark_is_not_a_character_of_the_first_line(self):
        self.write("BACKLOG.md", "\ufeff# Backlog\n\nLatest assigned: B1\n\n- **B1** One\n")
        self.assertEqual(self.rules(), [])


# --- PLAN and TASKS -----------------------------------------------------------

LONG = padded("> Landed 2026-10-05: ", 301)
LONG_TASK = padded("- [ ] **P1.1** — ", 151)


class PlanAndTasks(Case):
    def plan(self, body: str) -> list[tuple]:
        self.write(PLAN, body)
        return [(line, rule) for _, line, rule in self.rules()]

    def test_fences(self):
        cases = {
            "backticks": (f"```markdown\n{LONG}\n```\n", []),
            "tildes": (f"~~~\n{LONG}\n~~~\n", []),
            "longer": (f"`````text\n{LONG}\n```\n", []),
            "three spaces": (f"   ```\n{LONG}\n   ```\n", []),
            "four spaces is no fence": (f"    ```\n{LONG}\n    ```\n", [(2, "annotation-too-long")]),
            "two backticks is no fence": (f"``\n{LONG}\n``\n", [(2, "annotation-too-long")]),
            "tildes do not close backticks": (f"```\n~~~\n{LONG}\n~~~\n{LONG}\n```\n", []),
            "never closed": (f"```\n{LONG}\n\n{LONG}\n", []),
            "checked again after the block": (f"```\n{LONG}\n```\n{LONG}\n", [(4, "annotation-too-long")]),
            "a block between two blocks": (f"```\n```\n{LONG}\n```\n```\n", [(3, "annotation-too-long")]),
            "a shorter fence does not close": (f"````\n```\n{LONG}\n```\n````\n{LONG}\n", [(6, "annotation-too-long")]),
            "shorter tildes do not close": (f"~~~~~\n~~~\n{LONG}\n~~~~\n~~~~~\n{LONG}\n", [(6, "annotation-too-long")]),
            "a longer fence closes": (f"```\n{LONG}\n`````\n{LONG}\n", [(4, "annotation-too-long")]),
            "white space after the closer": (f"```\n{LONG}\n```  \t\n{LONG}\n", [(4, "annotation-too-long")]),
            "an indented closer": (f"```\n{LONG}\n   ```\n{LONG}\n", [(4, "annotation-too-long")]),
            "text after it is no closer": (f"```\n```python\n{LONG}\n``` x\n{LONG}\n```\n{LONG}\n",
                                           [(7, "annotation-too-long")]),
            "four spaces is no closer": (f"```\n    ```\n{LONG}\n```\n", []),
        }
        for name, (body, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.plan(body), expected)
                self.write(PLAN, "")
                self.write(TASKS, body.replace(LONG, LONG_TASK))
                found = [(line, rule.replace("tasks-line", "annotation")) for _, line, rule in self.rules()]
                self.assertEqual(found, expected)
                self.write(TASKS, "")

    def test_an_example_in_a_fence_is_no_annotation_of_the_step(self):
        body = "### P1.1 — A step\n> Landed 2026-10-05: one\n\n```markdown\n> Landed 2026-10-05: example\n> more\n```\n"
        self.assertEqual(self.plan(body), [])

    def test_continuation(self):
        first = "### P1.1 — A step\n\n> Landed 2026-10-05: one\n"
        cases = {
            "> and the rest of it\n": [(4, "annotation-continued")],
            ">\n": [(4, "annotation-continued")],
            ">no space\n": [(4, "annotation-continued")],
            "> second\n> third\n> fourth\n": [(4, "annotation-continued")],
            "> Landed: no space after the kind\n": [(4, "annotation-continued")],
            "> Depends on: P1.0\n": [],
            "> Parallel: A\n": [],
            "> Tag: light\n": [],
            "> Bug fix 2026-10-06: two\n> Audit 2026-10-07: PARTIAL: three\n": [],
            "> Audit 2026-10-07: PARTIAL: three\n> and more\n": [(5, "annotation-continued")],
            "\n> a quote of its own\n": [],
            "plain text\n> a quote\n": [],
            "```\n> in a block\n```\n> after a block\n": [],
            "> Depends on: P1.0\n> a quote after a mark\n": [],
        }
        for rest, expected in cases.items():
            with self.subTest(rest):
                self.assertEqual(self.plan(first + rest), expected)
        self.assertEqual(self.plan("> a quote\n> Landed 2026-10-05: one\n"), [])

    def test_two_annotations_of_one_kind(self):
        step = "### P1.1 — A step\n\n"
        cases = {
            "two landed": (step + "> Landed 2026-10-05: one\n\ntext\n\n> Landed 2026-10-06: two\n",
                           [(7, "annotation-duplicate")]),
            "three landed": (step + "> Landed 2026-10-05: 1\n> Landed 2026-10-06: 2\n> Landed 2026-10-07: 3\n",
                             [(4, "annotation-duplicate"), (5, "annotation-duplicate")]),
            "one of each": (step + "> Landed 2026-10-05: a\n> Bug fix 2026-10-05: b\n> Audit 2026-10-05: OK: c\n", []),
            "two bug fixes": (step + "> Bug fix 2026-10-05: a\n> Bug fix 2026-10-06: b\n",
                              [(4, "annotation-duplicate")]),
            "two audits": (step + "> Audit 2026-10-05: DEFERRED: D3\n> Audit 2026-11-05: RESOLVED: D3\n",
                           [(4, "annotation-duplicate")]),
        }
        for name, (body, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.plan(body), expected)

    def test_the_extent_of_a_step(self):
        landed = "> Landed 2026-10-05: one\n"
        cases = {
            "the next step": f"### P1.1 — A\n{landed}### P1.2 — B\n{landed}",
            "a heading of another level ends it": f"### P1.1 — A\n{landed}#### Notes\n{landed}",
            "a phase heading ends it": f"### P1.1 — A\n{landed}## Phase 2\n{landed}",
            "an indented heading ends it": f"### P1.1 — A\n{landed}   # Up to three spaces\n{landed}",
            "outside any step": f"## Phase 1\n{landed}\n{landed}",
            "before any heading": f"{landed}\n{landed}",
            "a heading that is not a step's": f"### Phase P1.1 notes\n{landed}\n{landed}",
            "not a step ID": f"### P1.1x — A\n{landed}\n{landed}",
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.assertEqual(self.plan(body), [])
        within = {
            "any level of heading": f"## P2.10 — A\n{landed}\n{landed}",
            "an ID and a colon": f"### P2.3: A\n{landed}\n{landed}",
            "a hash that is no heading": f"### P1.1 — A\n{landed}#hashtag\n{landed}",
            "four spaces is no heading": f"### P1.1 — A\n{landed}    # code\n{landed}",
            "a heading in a fence": f"### P1.1 — A\n{landed}```\n## Phase\n```\n{landed}",
        }
        for name, body in within.items():
            with self.subTest(name):
                self.assertEqual([rule for _, rule in self.plan(body)], ["annotation-duplicate"])

    def test_which_files_are_plan_and_tasks_files(self):
        self.write("SPRINT01-PLAN-a.md", LONG + "\n")
        self.write("SPRINT12-TASKS-a.md", LONG_TASK + "\n")
        self.write("SPRINT01-PRD-a.md", LONG + "\n" + LONG_TASK + "\n")
        self.write("SPRINT01-THOUGHTS-a.md", LONG + "\n")
        self.write("PLAN-a.md", LONG + "\n")
        self.write("SPRINT01-PLAN-a.txt", LONG + "\n")
        self.write("DONE/SPRINT00-PLAN-a.md", LONG + "\n")
        self.write("DONE/SPRINT00-TASKS-a.md", LONG_TASK + "\n")
        self.write("DONE/DEFERRED.md", "nonsense\n")
        self.assertEqual(self.rules(), [("SPRINT01-PLAN-a.md", 1, "annotation-too-long"),
                                        ("SPRINT12-TASKS-a.md", 1, "tasks-line-too-long")])

    def test_a_tasks_line_is_one_that_starts_with_a_box(self):
        self.write(TASKS, f"  {LONG_TASK}\n* [ ] {'x' * 200}\n- {'x' * 200}\n{'x' * 200}\n")
        self.assertEqual(self.rules(), [])
        self.write(PLAN, LONG_TASK + "\n")
        self.write(TASKS, LONG + "\n")
        self.assertEqual(self.rules(), [])

    # --- The hard tag on a TASKS line ---

    TAGGED_PLAN = (
        "## Phase 1\n\n"
        "### P1.1 — Hard\n\n> Tag: hard\n\n"                       # heading 3, mark 5
        "### P1.2 — Light\n\n> Parallel: A\n> Tag: light\n\n"      # heading 7
        "### P1.3 — Plain\n\nBody.\n\n"                            # heading 12
        "### P1.4 — Hard in a group\n\n> Depends on: P1.1\n> Parallel: B\n> Tag: hard\n"  # heading 16, mark 20
    )

    def tasks(self, body: str, plan: str | None = TAGGED_PLAN) -> list[tuple]:
        if plan is not None:
            self.write(PLAN, plan)
        self.write(TASKS, body)
        return [(line, rule) for name, line, rule in self.rules() if name == TASKS]

    def test_the_example_of_the_stage_file_is_clean(self):
        self.write(PLAN, example("stage-3-plan-tasks.md", "PLAN:"))
        tasks = example("stage-3-plan-tasks.md", "TASKS:")
        self.assertIn("- [ ] **P2.4** **[hard]** — ", tasks)
        self.write(TASKS, tasks)
        self.assertEqual(self.rules(), [])
        self.write(TASKS, tasks.replace(" **[hard]**", ""))
        self.assertEqual(self.rules(), [(TASKS, 2, "tasks-tag-mismatch")])

    def test_tags_that_agree_with_the_plan(self):
        body = ("## Phase 1\n\n- [ ] **P1.1** **[hard]** — Hard\n- [~] **P1.2** — Light\n- [x] **P1.3** — Plain\n"
                "- [x] ~~**P1.4** **[hard]** — Hard in a group~~ (skipped: deferred as D1)\n")
        self.assertEqual(self.tasks(body), [])
        for box in ("[ ]", "[~]", "[x]"):
            with self.subTest(box):
                self.assertEqual(self.tasks(f"- {box} **P1.1** **[hard]** — Hard\n"), [])

    def test_a_sprint_with_no_hard_step_and_no_tag_is_clean(self):
        plan = "### P1.1 — A\n\n> Tag: light\n\n### P1.2 — B\n\n> Parallel: A\n"
        self.assertEqual(self.tasks("- [ ] **P1.1** — A\n- [ ] **P1.2** — B\n", plan), [])

    def test_a_missing_and_an_extra_tag(self):
        body = ("## Phase 1\n\n- [ ] **P1.1** — Hard\n- [ ] **P1.2** **[hard]** — Light\n"
                "- [ ] **P1.3** **[hard]** — Plain\n- [x] ~~**P1.4** — Hard in a group~~ (skipped: x)\n")
        self.assertEqual(self.tasks(body), [(3, "tasks-tag-mismatch"), (4, "tasks-tag-mismatch"),
                                            (5, "tasks-tag-mismatch"), (6, "tasks-tag-mismatch")])
        _, report = self.run_check()
        messages = [v["message"] for v in report["violations"]]
        self.assertEqual(messages[0], "P1.1 carries `> Tag: hard` in the PLAN (line 5); this line has no **[hard]**")
        self.assertEqual(messages[1], "this line has **[hard]**; P1.2 carries no `> Tag: hard` in the PLAN (line 7)")
        self.assertEqual(report["exit_code"], 1)

    def test_a_tasks_file_written_before_the_tag_is_reported_per_line(self):
        body = "- [ ] **P1.1** — Hard\n- [ ] **P1.2** — Light\n- [ ] **P1.3** — Plain\n- [ ] **P1.4** — Hard in a group\n"
        self.assertEqual(self.tasks(body), [(1, "tasks-tag-mismatch"), (4, "tasks-tag-mismatch")])

    def test_a_malformed_tag(self):
        cases = {
            "light is not shown": "- [ ] **P1.2** **[light]** — Light\n",
            "light on a hard step": "- [ ] **P1.1** **[light]** — Hard\n",
            "an unknown word": "- [ ] **P1.3** **[easy]** — Plain\n",
            "the wrong case": "- [ ] **P1.1** **[HARD]** — Hard\n",
            "capitalised": "- [ ] **P1.1** **[Hard]** — Hard\n",
            "a group letter beside it": "- [ ] **P1.4** **[hard, B]** — Hard in a group\n",
            "a second bracket": "- [ ] **P1.4** **[hard]** **[B]** — Hard in a group\n",
            "twice": "- [ ] **P1.1** **[hard]** **[hard]** — Hard\n",
            "before the ID": "- [ ] **[hard]** **P1.1** — Hard\n",
            "after the dash": "- [ ] **P1.1** — **[hard]** Hard\n",
            "at the end": "- [ ] **P1.1** — Hard **[hard]**\n",
            "two spaces before it": "- [ ] **P1.1**  **[hard]** — Hard\n",
            "no space after it": "- [ ] **P1.1** **[hard]**— Hard\n",
            "empty": "- [ ] **P1.1** **[]** — Hard\n",
            "on a line with no ID": "- [ ] **[hard]** something\n",
        }
        for name, body in cases.items():
            with self.subTest(name):
                # One report for the line: a malformed tag is not compared as well.
                self.assertEqual(self.tasks(body), [(1, "tasks-tag-form")])
                self.assertEqual(self.tasks(body, plan=""), [(1, "tasks-tag-form")])

    def test_what_is_no_tag(self):
        for body in ("- [ ] **P1.3** — See [hard] cases and **bold** text\n", "- [ ] **P1.3** — An array `a[0]`\n",
                     "Text with **[hard]** that is no TASKS line\n", "  - [ ] **P1.1** — An indented line\n"):
            with self.subTest(body):
                self.assertEqual(self.tasks(body), [])

    def test_a_tag_in_a_fence_is_ignored_in_both_files(self):
        tasks = "- [ ] **P1.1** — A\n\n```markdown\n- [ ] **P1.1** **[light]** — A\n- [ ] **P1.2** **[hard]** — B\n```\n"
        plan = "### P1.1 — A\n\n```markdown\n> Tag: hard\n### P1.2 — B\n> Tag: hard\n```\n\n### P1.2 — B\n"
        self.assertEqual(self.tasks(tasks, plan), [])

    def test_which_plan_line_makes_a_step_hard(self):
        line = "- [ ] **P1.1** — A\n"
        hard = {
            "under the heading": "### P1.1 — A\n> Tag: hard\n",
            "after other marks": "### P1.1 — A\n\n> Depends on: P1.0\n> Parallel: A\n> Tag: hard\n\nBody.\n",
            "white space after it": "### P1.1 — A\n\n> Tag: hard  \n",
            "any level of heading": "## P1.1: A\n\n> Tag: hard\n",
            "the first of two steps with one ID": "### P1.1 — A\n> Tag: hard\n### P1.1 — Again\n",
        }
        for name, plan in hard.items():
            with self.subTest(name):
                self.assertEqual(self.tasks(line, plan), [(1, "tasks-tag-mismatch")])
                self.assertEqual(self.tasks(line.replace("** —", "** **[hard]** —"), plan), [])
        other = {
            "light": "### P1.1 — A\n\n> Tag: light\n",
            "another step's": "### P1.1 — A\n\n### P1.2 — B\n\n> Tag: hard\n",
            "after the next heading": "### P1.1 — A\n\n#### Notes\n\n> Tag: hard\n",
            "outside any step": "> Tag: hard\n\n### P1.1 — A\n",
            "another word": "### P1.1 — A\n\n> Tag: harder\n",
            "not a line of its own": "### P1.1 — A\n\nSee `> Tag: hard`.\n",
        }
        for name, plan in other.items():
            with self.subTest(name):
                self.assertEqual(self.tasks(line, plan), [])
                self.assertEqual(self.tasks(line.replace("** —", "** **[hard]** —"), plan), [(1, "tasks-tag-mismatch")])

    def test_a_step_the_plan_does_not_hold_is_not_compared(self):
        self.assertEqual(self.tasks("- [ ] **P9.9** **[hard]** — Elsewhere\n- [ ] **P9.8** — Elsewhere\n"), [])
        self.assertEqual(self.tasks("- [ ] P1.1 **[hard]** — No bold ID\n"), [(1, "tasks-tag-form")])

    def test_the_plan_is_the_one_of_the_same_sprint_and_slug(self):
        hard = "### P1.1 — A\n\n> Tag: hard\n"
        line = "- [ ] **P1.1** — A\n"
        self.write("SPRINT01-PLAN-a.md", hard)
        self.write("SPRINT02-PLAN-b.md", hard)
        self.write("SPRINT02-TASKS-a.md", line)
        self.write("SPRINT01-TASKS-b.md", line)
        self.write("SPRINT03-TASKS-c.md", line.replace("** —", "** **[hard]** —"))
        self.assertEqual(self.rules(), [])
        self.write("SPRINT01-TASKS-a.md", line)
        self.assertEqual(self.rules(), [("SPRINT01-TASKS-a.md", 1, "tasks-tag-mismatch")])

    def test_a_plan_that_was_not_read_is_not_compared_with(self):
        self.write(PLAN, "### P1.1 — A\n\n> Tag: hard\rx\n")
        self.write(TASKS, "- [ ] **P1.1** — A\n- [ ] **P1.2** **[light]** — B\n")
        self.assertEqual(self.rules(), [(PLAN, None, "line-endings"), (TASKS, 2, "tasks-tag-form")])

    def test_the_archive_is_not_compared(self):
        self.write("DONE/SPRINT00-PLAN-a.md", "### P1.1 — A\n\n> Tag: hard\n")
        self.write("DONE/SPRINT00-TASKS-a.md", "- [x] **P1.1** — A\n- [x] **P1.2** **[light]** — B\n")
        self.assertEqual(self.rules(), [])

    def test_the_150_characters_include_the_tag(self):
        plan = "### P1.1 — A\n\n> Tag: hard\n"
        for start in ("- [ ] **P1.1** **[hard]** — ", "- [x] ~~**P1.1** **[hard]** — "):
            with self.subTest(start):
                self.assertEqual(self.tasks(padded(start, 150) + "\n", plan), [])
                self.assertEqual(self.tasks(padded(start, 151) + "\n", plan), [(1, "tasks-line-too-long")])
        untagged = padded("- [ ] **P1.1** — ", 150)
        self.assertEqual(self.tasks(untagged.replace("** —", "** **[hard]** —") + "\n", plan),
                         [(1, "tasks-line-too-long")])
        self.assertEqual(self.tasks(padded("- [ ] **P1.1** — ", 151) + "\n", plan),
                         [(1, "tasks-line-too-long"), (1, "tasks-tag-mismatch")])


# --- Links in a sprint's docs -------------------------------------------------

OWN = "SPRINT84-THOUGHTS-sharadar-ingest.md"


class Links(Case):
    def found(self, body: str, name: str = OWN) -> list[tuple]:
        self.write(name, body)
        return [(line, rule) for file, line, rule in self.rules() if file == name]

    def test_links_within_the_set_are_clean(self):
        body = ("Sprint: 84\nSlug: sharadar-ingest\n\n"
                "[PRD](SPRINT84-PRD-sharadar-ingest.md) · [PLAN](SPRINT84-PLAN-sharadar-ingest.md#p12) · "
                "[TASKS](<SPRINT84-TASKS-sharadar-ingest.md>) · [STATE](./SPRINT84-STATE-sharadar-ingest.md \"now\")\n"
                "[encoded](SPRINT84%2DPRD-sharadar-ingest.md)\n")
        self.assertEqual(self.found(body), [])
        self.assertClean()

    def test_only_a_bare_name_of_the_five_kinds_of_the_same_number_is_in_the_set(self):
        for target, fix in (
                ("DONE/SPRINT84-PRD-sharadar-ingest.md", "link it by its bare file name, as the set sits in one "
                                                         "folder: `SPRINT84-PRD-sharadar-ingest.md`"),
                ("../docs/SPRINT84-PLAN-sharadar-ingest.md", "link it by its bare file name, as the set sits in one "
                                                             "folder: `SPRINT84-PLAN-sharadar-ingest.md`"),
                ("SPRINT84-NOTES-sharadar-ingest.md", "name it instead: `SPRINT84-NOTES-sharadar-ingest.md`"),
                ("SPRINT84-PRD-x.txt", "write the path in backticks instead, from the project root: "
                                       "`docs/SPRINT84-PRD-x.txt`")):
            with self.subTest(target):
                self.assertEqual(self.found(f"[x]({target})\n"), [(1, "link-outside-set")])
                self.assertTrue(self.messages(f"[x]({target})\n")[0].endswith(fix))

    def test_a_link_to_a_backlog_item_document(self):
        for target in ("BACKLOG/B9-offline-journal.md", "BACKLOG-B9-offline.md"):
            with self.subTest(target):
                self.assertEqual(self.found(f"See [B9]({target}).\n"), [(1, "link-outside-set")])
        self.assertTrue(self.messages("[B9](BACKLOG/B9-offline-journal.md)\n")[0].endswith(
            "name it instead: `B9-offline-journal.md`"))

    def test_percent_escapes_are_decoded_before_the_target_is_classified(self):
        self.assertEqual(self.found("[x](SPRINT83%2DPLAN-x.md) [y](EPIC03-PRD%20a.md)\n"),
                         [(1, "link-other-sprint"), (1, "link-epic-doc")])
        self.assertTrue(self.messages("[x](DONE/SPRINT83-PLAN-caf%C3%A9.md)\n")[0].endswith(
            "name it instead: `SPRINT83-PLAN-café.md`"))

    def test_a_path_on_a_windows_drive_is_absolute_and_not_a_url(self):
        drive = "C" + ":"  # put together: no source line holds a drive
        for target, fix in ((drive + "\\work\\src\\a.py", "write the path in backticks instead, from the project root"),
                            (drive + "/work/docs/SPRINT83-PLAN-x.md", "name it instead: `SPRINT83-PLAN-x.md`")):
            with self.subTest(target):
                messages = self.messages(f"[x]({target})\n")
                self.assertEqual(len(messages), 1)
                self.assertTrue(messages[0].endswith(fix), messages[0])
        self.assertEqual(self.found(f"[x]({drive}\\work\\SPRINT83-PLAN-x.md)\n"), [(1, "link-other-sprint")])

    def test_a_readme_or_an_index_is_named_by_its_path(self):
        for target, fix in (("DONE/README.md", ": `docs/DONE/README.md`"),
                            ("../deploy/README.md#setup", ": `deploy/README.md`"),
                            ("../site/Index.md", ": `site/Index.md`"),
                            ("/srv/README.md", "")):
            with self.subTest(target):
                messages = self.messages(f"[x]({target})\n")
                self.assertEqual(len(messages), 1)
                self.assertTrue(messages[0].endswith("name it by its path from the project root" + fix), messages[0])

    def test_what_is_no_link_reference_definition(self):
        body = "\n".join((
            "[^1]: See [the docs] for more.", "[^note]: SPRINT83-PLAN-x.md", "[NOTE]: a remark on SPRINT83-PLAN-x.md",
            "[P1.2]: done", "[x]: SPRINT83-PLAN-x.md and more", "    [x]: SPRINT83-PLAN-x.md",
        )) + "\n"
        self.assertEqual(self.found(body), [])
        body = "\n".join((
            "[a]: SPRINT83-PLAN-x.md \"title\"", "[b]: <EPIC03-PRD-a.md> (title)", "[c]: ../src/a.py 'title'",
            "[d]: SPRINT83-PRD-x.md", "[e]: <README>",
        )) + "\n"
        self.assertEqual(self.found(body), [(1, "link-other-sprint"), (2, "link-epic-doc"), (3, "link-outside-set"),
                                            (4, "link-other-sprint"), (5, "link-outside-set")])

    def test_a_link_to_another_sprints_doc(self):
        for target in ("SPRINT83-PLAN-macro-rates-ingest.md", "DONE/SPRINT83-PLAN-macro-rates-ingest.md",
                       "./DONE/SPRINT83-PLAN-macro-rates-ingest.md#p3", "../docs/SPRINT83-PLAN-macro-rates-ingest.md",
                       "<DONE/SPRINT83-PLAN-macro-rates-ingest.md>", "SPRINT83-PLAN-macro-rates-ingest.md 'title'",
                       "DONE\\SPRINT83-PLAN-macro-rates-ingest.md", "SPRINT85-STATE-x.md", "SPRINT07-PRD-old.md"):
            with self.subTest(target):
                self.assertEqual(self.found(f"See [it]({target}) for the plan.\n"), [(1, "link-other-sprint")])

    def test_the_message_names_the_fix(self):
        self.write(OWN, "Sprint: 84\n\nBuilt on [S83](DONE/SPRINT83-PLAN-macro-rates-ingest.md#p3).\n")
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(report["violations"], [{
            "file": OWN, "line": 3, "rule": "link-other-sprint",
            "message": "a link to DONE/SPRINT83-PLAN-macro-rates-ingest.md#p3, a doc of sprint 83: a sprint doc links "
                       "only within its own set, and this link breaks when either sprint is archived; "
                       "name it instead: `SPRINT83-PLAN-macro-rates-ingest.md`"}])
        text = check.run(self.arguments())[1]
        self.assertIn(f"\n{OWN}:3: link-other-sprint: a link to DONE/SPRINT83-PLAN-macro-rates-ingest.md#p3, ", text)
        self.assertTrue(text.endswith("\nResult: action needed\n"))

    def test_a_link_to_an_epic_doc(self):
        for target in ("EPIC03-PRD-reference-data-layer.md", "EPIC03-ROADMAP-reference-data-layer.md#sprints",
                       "DONE/EPIC02-THOUGHTS-index-membership.md"):
            with self.subTest(target):
                self.assertEqual(self.found(f"Epic: 03\n\n[charter]({target})\n"), [(3, "link-epic-doc")])
        self.write(OWN, "[charter](EPIC03-PRD-reference-data-layer.md)\n")
        message = self.run_check()[1]["violations"][0]["message"]
        self.assertTrue(message.endswith("; name it instead: `EPIC03-PRD-reference-data-layer.md`"), message)

    def test_a_link_to_any_other_doc(self):
        for target in ("BACKLOG.md", "DEFERRED.md", "SPRINT-INDEX.md", "DONE/README.md", "EPIC-INDEX.md",
                       "WORKFLOW-secmaster-nightly.md#steps", "../deploy/RESEARCH-ROLLOUT.md", "../README.MD"):
            with self.subTest(target):
                self.assertEqual(self.found(f"- [doc]({target})\n"), [(1, "link-outside-set")])
        self.write(OWN, "[rollout](../deploy/RESEARCH-ROLLOUT.md)\n")
        message = self.run_check()[1]["violations"][0]["message"]
        self.assertEqual(message, "a link to ../deploy/RESEARCH-ROLLOUT.md, outside the sprint's set: a sprint doc "
                                  "links only within its own set, and this link breaks when the sprint is archived; "
                                  "name it instead: `RESEARCH-ROLLOUT.md`")

    def messages(self, body: str, *extra: str) -> list[str]:
        self.write(OWN, body)
        return [v["message"] for v in self.run_check(*extra)[1]["violations"] if v["file"].endswith(OWN)]

    def test_a_link_to_code_or_an_image_gives_the_path_from_the_root(self):
        cases = {
            "../secmaster/decisions/sp500-FRC.json": "secmaster/decisions/sp500-FRC.json",
            "../src/ingest/sharadar.py#L12": "src/ingest/sharadar.py",
            "img/SPRINT83-chart.png": "docs/img/SPRINT83-chart.png",
            "./DONE/": "docs/DONE",
            "..": ".",
            "..\\tools\\run.ps1": "tools/run.ps1",
        }
        for target, rooted in cases.items():
            with self.subTest(target):
                self.assertEqual(self.found(f"[x]({target})\n"), [(1, "link-outside-set")])
                self.assertEqual(self.messages(f"[x]({target})\n"), [
                    f"a link to {target}, outside the sprint's set: a sprint doc links only within its own set, and "
                    "this link breaks when the sprint is archived; write the path in backticks instead, from the "
                    f"project root: `{rooted}`"])
        above = "/".join(("..", "..", "elsewhere", "a.py"))  # put together: no source line leaves the skill
        for target in (above, "/etc/hosts"):
            with self.subTest(target):
                self.assertEqual(self.messages(f"[x]({target})\n"), [
                    f"a link to {target}, outside the sprint's set: a sprint doc links only within its own set, and "
                    "this link breaks when the sprint is archived; write the path in backticks instead, from the "
                    "project root"])

    def test_no_path_from_the_root_for_docs_outside_the_project(self):
        outside = self.root / "elsewhere" / "docs"
        self.write(OWN, "[x](../src/a.py)\n", outside)
        report = self.run_check("--docs", str(outside))[1]
        self.assertEqual([(v["file"], v["rule"]) for v in report["violations"]], [(OWN, "link-outside-set")])
        self.assertTrue(report["violations"][0]["message"].endswith("from the project root"))

    def test_what_is_not_reported(self):
        body = "\n".join((
            "[a URL](https://example.com/docs/SPRINT83-PLAN-x.md) and [mail](mailto:a@example.com)",
            "[an anchor](#non-goals) and [a URL to code](https://github.com/o/r/blob/main/src/a.py)",
            "Named, as it should be: `SPRINT83-PLAN-macro-rates-ingest.md` and `EPIC03-PRD-reference-data-layer.md`",
            "In a code span: `[x](SPRINT83-PLAN-x.md)` and ``[y](EPIC03-PRD-y.md)``",
            "```markdown",
            "[in a fence](SPRINT83-PLAN-x.md)",
            "```",
            "Brackets that are no link: [P1.2] (SPRINT83-PLAN-x.md)",
        )) + "\n"
        self.assertEqual(self.found(body), [])

    def test_an_unclosed_backtick_is_text(self):
        self.assertEqual(self.found("a ` b [x](SPRINT83-PLAN-x.md)\n"), [(1, "link-other-sprint")])

    def test_a_link_reference_definition(self):
        body = "Built on [the plan][s83].\n\n[s83]: DONE/SPRINT83-PLAN-macro-rates-ingest.md\n   [e]: <EPIC03-PRD-a.md>\n"
        self.assertEqual(self.found(body), [(3, "link-other-sprint"), (4, "link-epic-doc")])

    def test_a_target_is_reported_once_on_its_line(self):
        body = ("[a](SPRINT83-PLAN-x.md) [b](SPRINT83-PLAN-x.md) [c](SPRINT83-PRD-x.md)\n"
                "[d](SPRINT83-PLAN-x.md)\n")
        self.assertEqual(self.found(body), [(1, "link-other-sprint"), (1, "link-other-sprint"),
                                            (2, "link-other-sprint")])

    def test_every_kind_of_a_sprints_doc_is_checked(self):
        line = "[S83](SPRINT83-PLAN-macro-rates-ingest.md)\n"
        for kind in ("THOUGHTS", "PRD", "PLAN", "TASKS", "STATE"):
            self.write(f"SPRINT84-{kind}-sharadar-ingest.md", line)
        self.assertEqual(sorted(self.rules()), sorted(
            (f"SPRINT84-{kind}-sharadar-ingest.md", 1, "link-other-sprint")
            for kind in ("THOUGHTS", "PRD", "PLAN", "TASKS", "STATE")))

    def test_the_archive_and_other_docs_are_not_checked(self):
        line = "[S83](SPRINT83-PLAN-macro-rates-ingest.md) [epic](EPIC03-PRD-a.md) [w](WORKFLOW-a.md)\n"
        for name in ("DONE/SPRINT84-PRD-sharadar-ingest.md", "DONE/README.md", "EPIC03-ROADMAP-a.md",
                     "WORKFLOW-a.md", "INCIDENTS.md", "SPRINT84-NOTES-a.md"):
            self.write(name, line)
        self.assertClean()

    def test_a_doc_that_cannot_be_read_is_reported_once(self):
        (self.docs / OWN).write_bytes(b"caf\xe9 [S83](SPRINT83-PLAN-x.md)\n")
        self.assertEqual(self.rules(), [(OWN, None, "not-utf8")])

    def test_files_never_archived_with_a_sprint_are_checked_for_sprint_and_epic_links(self):
        links = ("[s](../SPRINT83-PLAN-x.md) [d](../DONE/SPRINT07-PRD-y.md) [e](../EPIC03-PRD-a.md) "
                 "[w](../WORKFLOW-a.md) [code](../../src/a.py) [item](B4-other.md) [url](https://example.com/x.md)\n")
        self.write("BACKLOG.md", "Latest assigned: B9\n\n- **B4** Other — [notes](BACKLOG/B4-other.md)\n"
                   "- **B9** Offline mode, after [S83](SPRINT83-PLAN-x.md) — [notes](BACKLOG/B9-offline.md)\n")
        self.write("BACKLOG/B4-other.md", "# Other\n")
        self.write("BACKLOG/B9-offline.md", "# Offline\n\n" + links)
        self.write("BACKLOG/notes.txt", "[s](../SPRINT83-PLAN-x.md)\n")  # not an item document: not read
        self.write("DEFERRED-context.md", "## D1 — P3.4\n\nSee [the plan](DONE/SPRINT07-PLAN-y.md).\n")
        self.assertEqual(self.rules(), [
            ("BACKLOG.md", 4, "link-other-sprint"),
            ("BACKLOG/B9-offline.md", 3, "link-other-sprint"), ("BACKLOG/B9-offline.md", 3, "link-other-sprint"),
            ("BACKLOG/B9-offline.md", 3, "link-epic-doc"),
            ("DEFERRED-context.md", 3, "link-other-sprint"),
        ])
        messages = [v["message"] for v in self.run_check()[1]["violations"]]
        self.assertEqual(messages[0], "a link to SPRINT83-PLAN-x.md, a doc of sprint 83: a file that is not archived "
                                      "with that sprint names its docs and never links them, as the link breaks when "
                                      "the sprint is archived; name it instead: `SPRINT83-PLAN-x.md`")
        self.assertEqual(messages[3], "a link to ../EPIC03-PRD-a.md, an epic doc: a file that is not archived with "
                                      "the epic names its docs and never links them, as the link breaks when the "
                                      "epic is archived; name it instead: `EPIC03-PRD-a.md`")

    def test_an_item_document_at_its_earlier_place_is_checked_too(self):
        self.write("BACKLOG-B9-offline.md", "[s](SPRINT83-PLAN-x.md)\n")
        self.assertIn(("BACKLOG-B9-offline.md", 1, "link-other-sprint"), self.rules())


# --- DEFERRED.md --------------------------------------------------------------

class Deferred(Case):
    def found(self, text: str, today: str = TODAY) -> list[tuple]:
        self.write("DEFERRED.md", text)
        return [(line, rule) for _, line, rule in self.rules(today=today)]

    def test_the_example_of_the_reference_is_clean(self):
        self.write("DEFERRED.md", example("deferred.md", "An example of a whole `DEFERRED.md`"))
        # D5 was re-dated on 2026-12-01, which a check before that day reports.
        report = self.assertClean(today="2026-12-01")
        self.assertEqual([entry["number"] for entry in report["deferred"]], [3, 5])
        self.assertEqual([entry["state"] for entry in report["deferred"]], ["open", "open"])
        third, fifth = report["deferred"]
        self.assertEqual(third["title"], "Remove the legacy export path")
        self.assertEqual(third["sprint"], "07 P3.4")
        self.assertEqual(third["trigger"], "the export log of the last 30 days: no line with `path=legacy`")
        self.assertEqual(third["review_by"], "2026-12-01")
        self.assertEqual(third["check"], "python tools/checks/legacy_export_calls.py --days 30")
        self.assertIsNone(fifth["check"])
        self.assertEqual(fifth["review_by"], "2027-03-01 (re-dated 2026-12-01: two months of reports so far, no mismatch)")
        code, text = check.run(self.arguments(today="2026-12-01"))
        self.assertEqual(code, 0)
        self.assertIn("  check: python tools/checks/legacy_export_calls.py --days 30\n", text)
        self.assertIn("  no check named\n", text)

    def test_the_lines_of_the_reference_keep_their_limits(self):
        for line in (REFERENCES / "deferred.md").read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line.startswith("> Audit "):
                self.assertLessEqual(len(line), 300)
            if line.startswith("- [x] "):
                self.assertLessEqual(len(line), 150)

    def test_minimal_files(self):
        self.assertEqual(self.found("Latest assigned: D4\n"), [])
        self.assertEqual(self.found("# Deferred items\n\nLatest assigned: D4\n"), [])
        self.assertEqual(self.found(deferred(item(4), pointer=4, title=False)), [])
        self.assertEqual(self.found(""), [])  # an empty file is clean, as an empty backlog is

    def test_the_pointer_line(self):
        one = item(1)
        self.assertEqual(self.found("# Deferred items\n\n" + one), [(None, "deferred-pointer-missing")])
        self.assertEqual(self.found(deferred(one) + "\nLatest assigned: D9\n"), [(12, "deferred-pointer-duplicate")])
        self.assertEqual(self.found("# Deferred items\n\n" + one + "\nLatest assigned: D9\n"),
                         [(10, "deferred-pointer-below-item")])
        self.assertEqual(self.found(deferred(item(10))), [(5, "deferred-number-above-pointer")])
        self.assertEqual(self.found(deferred(item(9))), [])
        for line in ("Latest assigned: D09", "Latest assigned: D0", "Latest assigned: D9 ", "Latest assigned: 9",
                     "Latest assigned: B9", "Latest assigned:D9", "Latest assigned: D9, D8"):
            with self.subTest(line):
                # A line that starts `Latest assigned:` makes the file one of the new form, never the old.
                self.assertEqual(self.found(f"{line}\n"), [(None, "deferred-pointer-missing"), (1, "deferred-unknown-line")])
                self.assertEqual(self.found(f"{line}\n\n" + item(1)),
                                 [(None, "deferred-pointer-missing"), (1, "deferred-unknown-line")])

    def test_numbers(self):
        self.assertEqual(self.found(deferred(item(2), item(2, sprint="07 P3.5"))), [(12, "deferred-number-duplicate")])
        for heading in ("### D02 — Title", "### D0 — Title", "### D2 - Title", "### D2 – Title", "### D2 —  Title",
                        "### D2 — ", "### D2 —", "###  D2 — Title", "### d2 — Title", "###D2 — Title", "### Title"):
            with self.subTest(heading):
                text = deferred(item(2).replace("### D2 — Remove the legacy export path", heading))
                self.assertEqual(self.found(text), [(5, "deferred-heading-form")])
        # An item with a broken heading is still listed, and still flagged.
        text = deferred(item(2, review="2026-01-01").replace("### D2 —", "### D2 -"))
        self.write("DEFERRED.md", text)
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual([(e["number"], e["past_date"]) for e in report["deferred"]], [(None, True)])
        self.assertIn("D? — D2 - Remove the legacy export path  [PAST ITS DATE]", check.run(self.arguments())[1])

    def test_unknown_lines(self):
        base = deferred(item(1))
        self.assertEqual(self.found("stray\n" + base), [(1, "deferred-unknown-line")])
        self.assertEqual(self.found(base.replace("Latest", "A note\n\nLatest")), [(3, "deferred-unknown-line")])
        self.assertEqual(self.found(base + "A note under the item\n"), [(11, "deferred-unknown-line")])
        self.assertEqual(self.found(base + "\n- a bullet\n"), [(12, "deferred-unknown-line")])
        self.assertEqual(self.found(base + "```\nStatus: open\n```\n"),
                         [(11, "deferred-unknown-line"), (12, "deferred-field-duplicate"), (13, "deferred-unknown-line")])
        self.assertEqual(self.found(base + "## Group\n"), [(11, "deferred-unknown-line")])
        self.assertEqual(self.found(base + "# Deferred items\n"), [(11, "deferred-unknown-line")])
        self.assertEqual(self.found("# Deferred items\n# Deferred items\nLatest assigned: D1\n"),
                         [(2, "deferred-unknown-line")])
        self.assertEqual(self.found("Latest assigned: D1\n# Deferred items\n"), [(2, "deferred-unknown-line")])
        self.assertEqual(self.found("# Deferred\nLatest assigned: D1\n"), [(1, "deferred-unknown-line")])
        self.assertEqual(self.found("Latest assigned: D1\nStatus: open\n"), [(2, "deferred-unknown-line")])
        self.assertEqual(self.found(base.replace("Sprint:", " Sprint:")),
                         [(5, "deferred-field-missing"), (7, "deferred-unknown-line")])
        self.assertEqual(self.found(base.replace("Trigger: the export log", "Trigger: the export log\n  of the month")),
                         [(9, "deferred-unknown-line")])

    def test_fields(self):
        base = deferred(item(1, check_line="python tools/checks/a.py"))
        swap = base.replace("Sprint: 07 P3.4\n", "").replace("Status: open\n", "Status: open\nSprint: 07 P3.4\n")
        self.assertEqual(self.found(swap), [(11, "deferred-field-order")])
        late = base.replace("Check: python tools/checks/a.py\nStatus: open\n", "Status: open\nCheck: python a.py\n")
        self.assertEqual(self.found(late), [(11, "deferred-field-order")])
        self.assertEqual(self.found(base + "Status: open\n"), [(12, "deferred-field-duplicate")])
        self.assertEqual(self.found(base.replace("Status: open\n", "")), [(5, "deferred-field-missing")])
        self.assertEqual(self.found(deferred("### D1 — Only a heading\n")), [(5, "deferred-field-missing")] * 4)
        spread = base.replace("\nTrigger", "\n\n\nTrigger").replace("\nStatus", "\n\nStatus")
        self.assertEqual(self.found(spread), [])
        for field in ("Trigger", "Check", "Status", "Sprint", "Review by"):
            for form in (f"{field}:", f"{field}: ", f"{field}:   ", f"{field}:value"):
                with self.subTest(form):
                    lines = base.split("\n")
                    index = next(i for i, line in enumerate(lines) if line.startswith(field + ":"))
                    lines[index] = form
                    found = self.found("\n".join(lines))
                    self.assertIn((index + 1, "deferred-field-form"), found)

    def test_field_values(self):
        for sprint in ("7 P3.4", "07", "07 P3", "07 3.4", "07  P3.4", "07 P3.4 ", "S07 P3.4", "07 P3.4, P3.5",
                       "none ", " none", "None", "NONE", "none P3.4", "07 none", "none: a hotfix", "no", "-", "n/a"):
            with self.subTest(sprint):
                self.assertEqual(self.found(deferred(item(1, sprint=sprint))), [(7, "deferred-sprint-form")])
        self.assertEqual(self.found(deferred(item(1, sprint="107 P12.34"))), [])
        for review in ("2026-13-01", "2026-02-30", "2026-1-5", "01-12-2026", "2026-12-01T00:00", "20261201", "soon",
                       "2026-12-01 ", "2026-12-01 (re-dated 2026-10-01)", "2026-12-01 (re-dated 2026-10-01: )",
                       "2026-12-01 (re-dated 2026-10-32: why)", "2026-12-01 re-dated 2026-10-01: why",
                       "2026-12-01 (re-dated 2026-10-01: why", "2026-W49-2", "２０２６-12-01"):
            with self.subTest(review):
                self.assertEqual(self.found(deferred(item(1, review=review))), [(9, "deferred-date")])
        self.assertEqual(self.found(deferred(item(1, review="2028-02-29 (re-dated 2026-10-01: a (good) reason)"))), [])
        for status in ("closed", "Open", "open ", "open: still", "resolved", "resolved 2026-10-28", "resolved 2026-10-28:",
                       "resolved 2026-10-28: ", "resolved: done", "dropped 28-10-2026: why", "done 2026-10-28: how"):
            with self.subTest(status):
                self.assertEqual(self.found(deferred(item(1, status=status))), [(10, "deferred-status-form")])
        self.assertEqual(self.found(deferred(item(1, status="dropped 2026-02-30: why"))), [(10, "deferred-date")])

    def test_closed_items_of_a_closed_sprint_leave_the_file(self):
        resolved = "resolved 2026-10-01: done in 4e19c0a"
        dropped = "dropped 2026-10-01: no longer wanted"
        self.assertEqual(self.found(deferred(item(1, status=resolved))), [(5, "deferred-closed-sprint")])
        both = deferred(item(1, status=resolved), item(2, status=dropped, sprint="07 P3.5"), item(3, sprint="08 P1.1"))
        self.assertEqual(self.found(both), [(5, "deferred-closed-sprint")])
        kept = deferred(item(1, status=resolved), item(2, sprint="07 P3.5"), item(3, sprint="08 P1.1", status=dropped))
        self.assertEqual(self.found(kept), [(19, "deferred-closed-sprint")])
        self.assertEqual(self.found(deferred(item(1, status=resolved), item(2, sprint="07 P3.5"))), [])

    def test_the_past_date_flag(self):
        self.write("DEFERRED.md", deferred(
            item(1, review="2026-12-01"),
            item(2, review="2026-12-02 (re-dated 2026-11-01: still waiting)", sprint="07 P3.5"),
            item(3, review="2026-01-01", status="resolved 2026-01-02: done", sprint="07 P3.6"),
            item(4, review="2026-01-01", status="dropped 2026-01-02: not wanted", sprint="07 P3.7"),
        ))
        for today, past, code in (("2026-11-30", [], 0), ("2026-12-01", [], 0), ("2026-12-02", [1], 1),
                                  ("2026-12-03", [1, 2], 1)):
            with self.subTest(today):
                got, report = self.run_check(today=today)
                self.assertEqual(report["violations"], [])
                self.assertEqual([e["number"] for e in report["deferred"]], [1, 2])  # closed items are not listed
                self.assertEqual([e["number"] for e in report["deferred"] if e["past_date"]], past)
                self.assertEqual(report["summary"], {"open": 2, "state_unknown": 0, "past_date": len(past),
                                                     "violations": 0, "notes": 0})
                self.assertEqual(got, code)
                self.assertEqual(check.run(self.arguments(today=today))[1].count("[PAST ITS DATE]"), len(past))

    def test_re_dating(self):
        cases = {
            "2026-12-01 (re-dated 2026-10-05: on the day of the check)": 0,
            "2026-12-01 (re-dated 2026-01-01: long ago)": 0,
            "2026-10-06 (re-dated 2026-10-05: one day later)": 0,
            "2026-12-01 (re-dated 2026-10-06: tomorrow)": 1,
            "2026-10-01 (re-dated 2026-10-01: the same day)": 1,
            "2026-09-01 (re-dated 2026-10-01: an earlier date)": 1,
            "2026-10-07 (re-dated 2026-10-06: tomorrow, and later)": 1,
            "2026-10-06 (re-dated 2026-10-07: tomorrow, and not later)": 2,
        }
        for review, count in cases.items():
            with self.subTest(review):
                self.assertEqual(self.found(deferred(item(1, review=review))), [(9, "deferred-date")] * count)
        # The day it was re-dated is compared with the day of the check.
        late = deferred(item(1, review="2026-12-01 (re-dated 2026-10-06: tomorrow)"))
        self.assertEqual(self.found(late, today="2026-10-06"), [])
        self.write("DEFERRED.md", late)
        _, report = self.run_check()
        self.assertEqual([v["message"] for v in report["violations"]],
                         ["the day it was re-dated, 2026-10-06, is after today, 2026-10-05"])
        # A date that breaks the rule still counts for the flag.
        self.write("DEFERRED.md", deferred(item(1, review="2026-09-01 (re-dated 2026-10-01: an earlier date)")))
        self.assertEqual([entry["past_date"] for entry in self.run_check()[1]["deferred"]], [True])

    def test_an_item_whose_state_cannot_be_told_is_listed_and_flagged(self):
        forms = {
            "opne": "deferred-status-form", "Open": "deferred-status-form", "resolved": "deferred-status-form",
            "": "deferred-field-form", "dropped 2026-02-30: why": "deferred-date", None: "deferred-field-missing",
        }
        for status, rule in forms.items():
            with self.subTest(status):
                first = item(1) if status is not None else item(1).replace("Status: open\n", "")
                if status is not None:
                    first = first.replace("Status: open", f"Status: {status}".rstrip() if status else "Status:")
                self.write("DEFERRED.md", deferred(first, item(2, sprint="07 P3.5"),
                                                   item(3, sprint="08 P1.1", status="resolved 2026-10-01: done"),
                                                   item(4, sprint="08 P1.2")))
                code, report = self.run_check()
                self.assertEqual(code, 1)
                self.assertEqual([(e["number"], e["state"]) for e in report["deferred"]],
                                 [(1, "unknown"), (2, "open"), (4, "open")])
                self.assertIn(rule, [v["rule"] for v in report["violations"]])  # the form is still reported
                self.assertEqual(report["summary"]["open"], 2)
                self.assertEqual(report["summary"]["state_unknown"], 1)
                text = check.run(self.arguments())[1]
                self.assertIn("Deferred items: 2 open, 1 state unknown, 0 past its date\n", text)
                self.assertIn("\nD1 — Remove the legacy export path  [STATE UNKNOWN]\n", text)
                self.assertIn("\nD2 — Remove the legacy export path\n", text)
        # Past its date as well: both flags, and both counts.
        self.write("DEFERRED.md", deferred(item(1, review="2026-01-01", status="opne")))
        code, report = self.run_check()
        self.assertEqual((code, report["deferred"][0]["state"], report["deferred"][0]["past_date"]), (1, "unknown", True))
        self.assertIn("  [STATE UNKNOWN]  [PAST ITS DATE]\n", check.run(self.arguments())[1])
        # An item of unknown state does not make its sprint a closed one.
        self.assertNotIn("deferred-closed-sprint", [v["rule"] for v in report["violations"]])

    def test_today_is_the_default(self):
        self.write("DEFERRED.md", deferred(item(1, review="2000-01-01"), item(2, review="9999-12-31", sprint="07 P1.1")))
        code, text = check.run(["--project", str(self.project), "--home", str(self.home), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual([e["past_date"] for e in json.loads(text)["deferred"]], [True, False])

    def test_an_item_outside_a_sprint(self):
        outside = item(2, sprint="none", title="Revisit the retry limit")
        self.assertEqual(self.found(deferred(outside)), [])
        # Closed, it leaves the file in the change that closes it.
        for status in ("resolved 2026-10-01: done in 4e19c0a", "dropped 2026-10-01: not wanted"):
            with self.subTest(status):
                self.assertEqual(self.found(deferred(item(2, sprint="none", status=status))),
                                 [(5, "deferred-closed-item")])
        # It neither keeps a sprint's closed items in the file nor counts as one of them.
        resolved = "resolved 2026-10-01: done in 4e19c0a"
        self.assertEqual(self.found(deferred(item(1, status=resolved), item(2, sprint="none"))),
                         [(5, "deferred-closed-sprint")])
        self.assertEqual(self.found(deferred(item(1), item(2, sprint="none", status=resolved))),
                         [(12, "deferred-closed-item")])
        # Its state unknown, it is listed and flagged, and not taken for closed.
        self.assertEqual(self.found(deferred(item(2, sprint="none", status="opne"))), [(10, "deferred-status-form")])
        # An empty value is still reported.
        self.assertIn((7, "deferred-field-form"), self.found(deferred(item(1).replace("Sprint: 07 P3.4", "Sprint:"))))
        # Listed as belonging to no sprint, in the JSON and in the text.
        self.write("DEFERRED.md", deferred(item(1), outside))
        code, report = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual([(e["number"], e["sprint"], e["outside_sprint"]) for e in report["deferred"]],
                         [(1, "07 P3.4", False), (2, "none", True)])
        self.assertEqual(set(report["deferred"][1]), {"number", "title", "state", "sprint", "outside_sprint", "trigger",
                                                      "review_by", "check", "past_date", "line", "file"})
        self.assertEqual(report["summary"], {"open": 2, "state_unknown": 0, "past_date": 0, "violations": 0, "notes": 0})
        text = check.run(self.arguments())[1]
        self.assertIn("\nD1 — Remove the legacy export path\n  sprint: 07 P3.4\n", text)
        self.assertIn("\nD2 — Revisit the retry limit\n  sprint: none (outside a sprint)\n", text)
        # A malformed value is not outside a sprint.
        self.write("DEFERRED.md", deferred(item(1, sprint="None")))
        code, report = self.run_check()
        self.assertEqual((code, report["deferred"][0]["outside_sprint"]), (1, False))
        self.assertIn("  sprint: None\n", check.run(self.arguments())[1])

    def notes(self, text: str) -> list[tuple]:
        """The notes for a ``DEFERRED.md`` of ``text``; it has no violation."""
        self.write("DEFERRED.md", text)
        code, report = self.run_check()
        self.assertEqual((code, report["violations"], report["exit_code"], report["deferred"]), (0, [], 0, []))
        self.assertEqual(report["summary"]["notes"], len(report["notes"]))
        self.assertEqual(report["summary"]["violations"], 0)
        return [(note["file"], note["line"], note["rule"]) for note in report["notes"]]

    def test_a_deferred_file_in_the_old_form_is_one_note_and_no_violation(self):
        not_converted = [("DEFERRED.md", None, "deferred-not-converted")]
        old = ("# DEFERRED decisions\n\nLong-lived decisions we postponed.\n\n---\n\n## INFRA-01 — re-evaluate sizing\n\n"
               "**Added:** 2026-04-20\n**Context:** a paragraph\nthat goes on.\n\n**Trigger:**\n`peak_memory_pct > 75`\n\n"
               "```\ncode\n```\n**Resolved:** 2026-05-01 — done\n" + "x" * 400 + "\n")
        for body in (old, "Status: open\n", "Sprint: none\nStatus: open\n", "## D1 — two hashes\nprose\n",
                     "#### D1 — four hashes\nprose\n", " ### D1 — indented\n", "### Data sources\nprose\n",
                     "### d1 — lower case\nprose\n", "- a bullet\n", " Latest assigned: D1\n", "latest assigned: D1\n",
                     "# Deferred items \nprose\n", "## Deferred items\nprose\n", "# Deferred\nprose\n"):
            with self.subTest(body):
                self.assertEqual(self.notes(body), not_converted)
        message = ("no pointer line, no title `# Deferred items` and no item heading: the file is in the old form; "
                   "its lines were not checked")
        self.write("DEFERRED.md", old)
        code, report = self.run_check()
        self.assertEqual(report["notes"], [{"file": "DEFERRED.md", "line": None, "rule": "deferred-not-converted",
                                            "message": message}])
        self.assertEqual(report["summary"], {"open": 0, "state_unknown": 0, "past_date": 0, "violations": 0, "notes": 1})
        code, text = check.run(self.arguments())
        self.assertEqual(code, 0)
        self.assertIn(f"\nViolations: 0\n\nNotes: 1\nDEFERRED.md: deferred-not-converted: {message}\n\n"
                      "Result: nothing needs action\n", text)
        # With a backlog in the old form as well: two notes, still nothing that needs action.
        self.write("BACKLOG.md", "- an idea\n")
        self.assertEqual(self.notes(old), [("DEFERRED.md", None, "deferred-not-converted"),
                                           ("BACKLOG.md", None, "backlog-not-converted")])

    def test_a_deferred_file_of_blank_lines_and_headings_is_clean(self):
        for body in ("", "\n", "\n\n  \n\t\n", "# DEFERRED decisions\n", "# DEFERRED decisions\n\n## INFRA-01 — sizing\n",
                     "#\n", "﻿## Group\r\n\r\n"):
            with self.subTest(body):
                self.assertEqual(self.notes(body), [])
        self.assertIn("\nViolations: 0\n\nNotes: 0\n\nResult: nothing needs action\n", check.run(self.arguments())[1])

    def test_an_old_form_note_does_not_change_the_exit_code_either_way(self):
        self.write("DEFERRED.md", "# DEFERRED decisions\n\nSome prose.\n")
        self.write(TASKS, LONG_TASK + "\n")
        code, report = self.run_check()
        self.assertEqual((code, report["summary"]["violations"], report["summary"]["notes"]), (1, 1, 1))
        self.assertEqual([v["rule"] for v in report["violations"]], ["tasks-line-too-long"])

    def test_a_file_of_the_new_form_is_checked_line_by_line(self):
        # A pointer line makes it one, with prose and old entries around it.
        prose = "Latest assigned: D3\n\nSome prose about the decisions.\n\n## INFRA-01 — sizing\n**Added:** 2026-04-20\n"
        self.assertEqual(self.found(prose), [(3, "deferred-unknown-line"), (5, "deferred-unknown-line"),
                                             (6, "deferred-unknown-line")])
        # So does a broken pointer line, and the title: a lost pointer is reported, not taken for the old form.
        self.assertEqual(self.found("# Deferred items\n\nLatest assigned D5\n"),
                         [(None, "deferred-pointer-missing"), (3, "deferred-unknown-line")])
        self.assertEqual(self.found("Latest assigned: D5x\n\nSome prose.\n"),
                         [(None, "deferred-pointer-missing"), (1, "deferred-unknown-line"), (3, "deferred-unknown-line")])
        self.assertEqual(self.found("# Deferred items\n"), [(None, "deferred-pointer-missing")])
        self.assertEqual(self.found("﻿# Deferred items\r\n\r\n## Group\r\n"),
                         [(None, "deferred-pointer-missing"), (3, "deferred-unknown-line")])
        self.assertEqual(self.found("# Deferred items\n\nSome prose.\n"),
                         [(None, "deferred-pointer-missing"), (3, "deferred-unknown-line")])
        # So does an item heading, well formed or not.
        self.assertEqual(self.found("### D1 — Sizing\n\nprose\n"),
                         [(None, "deferred-pointer-missing")] + [(1, "deferred-field-missing")] * 4
                         + [(3, "deferred-unknown-line")])
        self.assertEqual(self.found("### D01 — Sizing\nprose\n"),
                         [(None, "deferred-pointer-missing"), (1, "deferred-heading-form")]
                         + [(1, "deferred-field-missing")] * 4 + [(2, "deferred-unknown-line")])
        _, report = self.run_check()
        self.assertEqual(report["notes"], [])


# --- BACKLOG.md ---------------------------------------------------------------

class Backlog(Case):
    HEAD = "# Backlog\n\nLatest assigned: B20\n\n"

    def found(self, body: str, head: str | None = None) -> list[tuple]:
        self.write("BACKLOG.md", (self.HEAD if head is None else head) + body)
        return [(line, rule) for name, line, rule in self.rules() if name == "BACKLOG.md"]

    def test_the_example_of_the_reference_is_clean(self):
        self.write("BACKLOG.md", example("stage-0-backlog.md", "An example of a whole `BACKLOG.md`"))
        self.write("BACKLOG/B9-offline-journal.md", "anything at all\n- sketch\n" + "x" * 500 + "\n")
        self.assertClean()

    def test_the_example_without_its_document(self):
        self.write("BACKLOG.md", example("stage-0-backlog.md", "An example of a whole `BACKLOG.md`"))
        self.assertEqual(self.rules(), [("BACKLOG.md", 12, "backlog-document-missing")])

    def test_minimal_files(self):
        self.assertEqual(self.found("", head="Latest assigned: B3\n"), [])
        self.assertEqual(self.found("- **B1** One\n- **B20** Twenty\n"), [])
        self.assertEqual(self.found("- **B1** **[LOW]** One, with `code`, **bold** and [a link](https://example.com/a)\n"), [])

    def notes(self, body: str) -> list[tuple]:
        """The notes for a ``BACKLOG.md`` of ``body``; it has no violation."""
        self.write("BACKLOG.md", body)
        code, report = self.run_check()
        self.assertEqual((code, report["violations"], report["exit_code"]), (0, [], 0))
        self.assertEqual(report["summary"]["notes"], len(report["notes"]))
        self.assertEqual(report["summary"]["violations"], 0)
        return [(note["file"], note["line"], note["rule"]) for note in report["notes"]]

    def test_a_backlog_in_the_old_form_is_one_note_and_no_violation(self):
        not_converted = [("BACKLOG.md", None, "backlog-not-converted")]
        old = "# Backlog\n\n## Bugs\n- export drops a row\n  more about it\n\nA paragraph.\n- " + "x" * 400 + "\n```\n"
        for body in (old, "Latest assigned: 7\n- **B** not numbered\n", "- an idea\n", "# Backlog\n\nA sentence.\n",
                     " # an indented heading is no heading here\n", "Latest assigned: B\n"):
            with self.subTest(body):
                self.assertEqual(self.notes(body), not_converted)
        self.write("BACKLOG.md", old)
        code, text = check.run(self.arguments())
        self.assertEqual(code, 0)
        self.assertIn("\nViolations: 0\n\nNotes: 1\nBACKLOG.md: backlog-not-converted: no pointer line and no numbered "
                      "item: the file is in the old form; its lines were not checked\n\nResult: nothing needs action\n",
                      text)

    def test_a_backlog_of_blank_lines_and_headings_is_clean(self):
        for body in ("", "\n", "\n\n  \n\t\n", "# Backlog\n", "# Backlog\n\n## Bugs\n\n## Features\n\n",
                     "#\n", "\ufeff# Backlog\r\n\r\n## Bugs\r\n"):
            with self.subTest(body):
                self.assertEqual(self.notes(body), [])
        self.assertIn("\nViolations: 0\n\nNotes: 0\n\nResult: nothing needs action\n", check.run(self.arguments())[1])

    def test_a_note_does_not_change_the_exit_code_either_way(self):
        self.write("BACKLOG.md", "- an idea\n")
        self.write(TASKS, LONG_TASK + "\n")
        code, report = self.run_check()
        self.assertEqual((code, report["summary"]["violations"], report["summary"]["notes"]), (1, 1, 1))
        self.assertEqual([v["rule"] for v in report["violations"]], ["tasks-line-too-long"])
        # A document of a backlog that was not converted is still an orphan.
        self.write(TASKS, "")
        self.write("BACKLOG/B1-a.md", "notes\n")
        self.assertEqual(self.rules(), [("BACKLOG/B1-a.md", None, "backlog-document-orphan")])

    def test_the_pointer_line(self):
        self.assertEqual(self.found("- **B1** One\n- loose\n", head="# Backlog\n\n"),
                         [(None, "backlog-pointer-missing"), (4, "backlog-item-form")])
        self.assertEqual(self.found("Latest assigned: B21\n- **B1** One\n"), [(5, "backlog-pointer-duplicate")])
        self.assertEqual(self.found("Latest assigned: B20\n", head="- **B1** One\n"), [(2, "backlog-pointer-below-item")])
        self.assertEqual(self.found("- **B21** Above\n- **B20** At\n"), [(5, "backlog-number-above-pointer")])
        self.assertEqual(self.found("- **B1** One\n", head="Latest assigned: B07\n"),
                         [(None, "backlog-pointer-missing"), (1, "backlog-unknown-line")])

    def test_numbers(self):
        self.assertEqual(self.found("- **B1** One\n\n## Group\n\n- **B1** Again\n"), [(9, "backlog-number-duplicate")])

    def test_the_item_grammar(self):
        for line in ("- no number", "- **B07** Leading zero", "- **B0** Zero", "- **B7**", "- **B7** ", "- **B7**  Two spaces",
                     "- B7 Not bold", "- **b7** Lower case", "- **B7**No space", "- [ ] **B7** A box", "- **D7** Deferred",
                     "- **B7** **[URGENT]** Unknown tag", "- **B7** **[high]** Lower-case tag",
                     "- **B7** Tag at the end **[HIGH]**", "- **B7** **[HIGH]** **[LOW]** Two tags",
                     "- **B7** **[HIGH]**  Two spaces after the tag", "- **B7** **[HIGH]**"):
            with self.subTest(line):
                self.assertEqual(self.found(line + "\n"), [(5, "backlog-item-form")])
        for line in ("* **B7** A star", "+ **B7** A plus", "1. **B7** Ordered", "Some prose.", "**B7** No hyphen",
                     "-**B7** No space", "> a quote", "```", "| a | table |", "---"):
            with self.subTest(line):
                self.assertEqual(self.found(line + "\n"), [(5, "backlog-unknown-line")])

    def test_an_item_is_one_line(self):
        cases = {
            "- **B7** One\n  continued\n": [(6, "backlog-item-not-one-line")],
            "- **B7** One\ncontinued without indent\n": [(6, "backlog-item-not-one-line")],
            "- **B7** One\n  - a sub-bullet\n": [(6, "backlog-item-not-one-line")],
            "- **B7** One\n\n  a paragraph under it\n": [(7, "backlog-item-not-one-line")],
            "- **B7** One\n\ta tab\n  and more\nand more\n- **B8** Two\n": [(6, "backlog-item-not-one-line"),
                                                                         (7, "backlog-item-not-one-line"),
                                                                         (8, "backlog-item-not-one-line")],
            "- **B7** One\n```\ncode\n```\n": [(line, "backlog-item-not-one-line") for line in (6, 7, 8)],
            "- **B7** One\n\n```\n": [(7, "backlog-unknown-line")],
            "- **B7** One\n## Group\n- **B8** Two\n": [],
        }
        for body, expected in cases.items():
            with self.subTest(body):
                self.assertEqual(self.found(body), expected)
        self.assertEqual(self.found("- " + "x" * 299 + "\n"), [(5, "backlog-item-too-long"), (5, "backlog-item-form")])
        self.assertEqual(self.found("  " + "x" * 400 + "\n" + "x" * 400 + "\n"),
                         [(5, "backlog-item-not-one-line"), (6, "backlog-item-not-one-line")])

    def test_item_documents(self):
        self.write("BACKLOG/B9-offline-journal.md", "notes\n")
        good = "- **B9** Offline mode — [notes](BACKLOG/B9-offline-journal.md)\n"
        self.assertEqual(self.rules(), [("BACKLOG/B9-offline-journal.md", None, "backlog-document-orphan")])
        self.assertEqual(self.found(good), [])
        self.assertEqual(self.found("- **B9** [the whole text](BACKLOG/B9-offline-journal.md)\n"), [])
        for line in ("- **B9** See [notes](BACKLOG/B9-offline-journal.md) for more",
                     "- **B9** [notes](BACKLOG/B9-offline-journal.md).",
                     "- **B9** [a](BACKLOG/B9-offline-journal.md) [b](BACKLOG/B9-offline-journal.md)",
                     "- **B9** [a](BACKLOG/B9-offline-journal.md) [b](BACKLOG-B9-offline-journal.md)",
                     "- **B8** Another item — [notes](BACKLOG/B9-offline-journal.md)"):
            with self.subTest(line):
                self.assertEqual(self.found(line + "\n"), [(5, "backlog-document-link")])
        for target in ("./BACKLOG/B9-offline-journal.md", "docs/BACKLOG/B9-offline-journal.md", "BACKLOG/B9.md",
                       "BACKLOG/B9-Offline.md", "BACKLOG/B09-offline-journal.md", "BACKLOG/B9-offline_journal.md",
                       "BACKLOG/B9-offline-journal.md#part", "BACKLOG/B9-offline-journal.txt",
                       "BACKLOG/b9-offline-journal.md", "../docs/BACKLOG/B9-offline-journal.md",
                       "BACKLOG\\B9-offline-journal.md", "BACKLOG/sub/B9-offline-journal.md",
                       "BACKLOG/BACKLOG-B9-offline-journal.md", "./BACKLOG-B9-offline-journal.md",
                       "docs/BACKLOG-B9-offline-journal.md", "BACKLOG-B9.md", "BACKLOG-B9-Offline.md",
                       "backlog/B9-offline-journal.md", "Backlog\\B9-offline-journal.md",
                       "backlog-b9-offline-journal.md"):
            with self.subTest(target):
                self.write("BACKLOG.md", self.HEAD + f"- **B9** Offline mode — [notes]({target})\n")
                self.assertEqual(self.rules(), [("BACKLOG.md", 5, "backlog-document-link"),
                                                ("BACKLOG/B9-offline-journal.md", None, "backlog-document-orphan")])
        _, report = self.run_check()
        self.assertEqual(report["violations"][0]["message"], "the link's target is `BACKLOG/B<n>-<slug>.md`")
        # A URL, or a path with no folder of that name, is not a link to an item document.
        for target in ("https://example.com/BACKLOG/B9-offline-journal.md", "https://example.com/BACKLOG-B9-a.md",
                       "WORKFLOW-backlog-bugs.md", "BACKLOG.md", "notes/backlog.md"):
            with self.subTest(target):
                self.assertEqual(self.found(f"- **B9** Offline mode — [notes]({target})\n"), [])
        # A sprint's doc is no item document either; the link is reported as one to that sprint.
        self.assertEqual(self.found("- **B9** Offline mode — [notes](SPRINT07-PRD-backlog-bugs.md)\n"),
                         [(5, "link-other-sprint")])
        self.assertEqual(self.found("- **B9** Offline mode — [notes](BACKLOG/B9-other.md)\n"),
                         [(5, "backlog-document-missing")])
        _, report = self.run_check()
        self.assertEqual(report["violations"][0]["message"], "the folder BACKLOG/ has no B9-other.md")
        # The same name beside BACKLOG.md is not the document in the folder.
        (self.docs / "BACKLOG" / "B9-offline-journal.md").unlink()
        self.write("B9-offline-journal.md", "notes\n")
        self.assertEqual(self.found(good), [(5, "backlog-document-missing")])

    def test_numbers_and_documents_in_the_folder(self):
        self.write("BACKLOG/B9-a.md", "notes\n")
        self.assertEqual(self.found("- **B9** One — [notes](BACKLOG/B9-a.md)\n- **B9** Again — [notes](BACKLOG/B9-a.md)\n"),
                         [(6, "backlog-number-duplicate")])
        self.assertEqual(self.found("- **B21** Above — [notes](BACKLOG/B21-a.md)\n"),
                         [(5, "backlog-document-missing"), (5, "backlog-number-above-pointer")])

    def test_orphan_documents(self):
        self.write("BACKLOG.md", self.HEAD + "- **B9** Offline mode — [notes](BACKLOG/B9-a.md)\n- **B4** Other\n")
        for name in ("B9-a.md", "B9-b.md", "B4-c.md", "B5-d.md", "B05-e.md", "B6-.md", "notes.md",
                     "BACKLOG-B7-unrenamed.md"):
            self.write("BACKLOG/" + name, "notes\n")
        self.write("BACKLOG/sketch.png", "not a document\n")
        self.write("BACKLOG-notes.md", "not an item document\n")
        self.write("B3-beside.md", "not in the folder\n")
        self.write("DONE/BACKLOG/B1-archived.md", "the archive is not checked\n")
        self.write("DONE/BACKLOG-B2-archived.md", "the archive is not checked\n")
        orphans = [name for name, _, rule in self.rules() if rule == "backlog-document-orphan"]
        self.assertEqual(orphans, ["BACKLOG/B05-e.md", "BACKLOG/B4-c.md", "BACKLOG/B5-d.md", "BACKLOG/B6-.md",
                                   "BACKLOG/B9-b.md", "BACKLOG/BACKLOG-B7-unrenamed.md", "BACKLOG/notes.md"])
        self.assertEqual(len(self.rules()), 7)
        (self.docs / "BACKLOG.md").unlink()
        self.assertEqual(len(self.rules()), 8)  # with no backlog, every document is an orphan

    EARLIER = "backlog-documents-earlier-place"
    OLD_LINK = "- **B9** Offline mode — [notes](BACKLOG-B9-offline-journal.md)\n"
    MOVE = ": move the documents into the folder BACKLOG/ and point the links there, as backlog-conversion.md says"

    def earlier(self) -> tuple[int, list[tuple], list[str]]:
        """The exit code, the violations, and the messages of the earlier-place notes."""
        code, report = self.run_check()
        self.assertTrue(all(note["rule"] == self.EARLIER and note["file"] == "BACKLOG.md" and note["line"] is None
                            for note in report["notes"]), report["notes"])
        return (code, [(v["file"], v["line"], v["rule"]) for v in report["violations"]],
                [note["message"] for note in report["notes"]])

    def test_documents_at_their_earlier_place_are_one_note(self):
        # A project converted before the folder: documents beside BACKLOG.md, and links to them.
        self.write("BACKLOG.md", self.HEAD + self.OLD_LINK + "- **B10** Ten — [notes](BACKLOG-B10-ten.md)\n")
        for name in ("BACKLOG-B9-offline-journal.md", "BACKLOG-B10-ten.md", "backlog-b3-lower.md"):
            self.write(name, "notes\n")
        self.assertEqual(self.earlier(), (0, [], [
            "3 item documents are at the earlier place beside BACKLOG.md (first: BACKLOG-B10-ten.md) and 2 items "
            "link to that place (first: line 5)" + self.MOVE]))
        code, text = check.run(self.arguments())
        self.assertEqual(code, 0)
        self.assertIn("\nViolations: 0\n\nNotes: 1\nBACKLOG.md: backlog-documents-earlier-place: 3 item documents",
                      text)
        self.assertTrue(text.endswith("\nResult: nothing needs action\n"))
        # One of each.
        (self.docs / "BACKLOG-B10-ten.md").unlink()
        (self.docs / "backlog-b3-lower.md").unlink()
        self.write("BACKLOG.md", self.HEAD + self.OLD_LINK)
        self.assertEqual(self.earlier(), (0, [], [
            "1 item document is at the earlier place beside BACKLOG.md (first: BACKLOG-B9-offline-journal.md) and "
            "1 item links to that place (first: line 5)" + self.MOVE]))
        # A document with no BACKLOG.md is the same note.
        (self.docs / "BACKLOG.md").unlink()
        self.assertEqual(self.earlier()[:2], (0, []))
        self.assertEqual(len(self.earlier()[2]), 1)

    def test_a_link_to_the_earlier_place_is_still_checked(self):
        self.write("BACKLOG-B9-offline-journal.md", "notes\n")
        for line in ("- **B8** Another item — [notes](BACKLOG-B9-offline-journal.md)",
                     "- **B9** See [notes](BACKLOG-B9-offline-journal.md) for more"):
            with self.subTest(line):
                self.write("BACKLOG.md", self.HEAD + line + "\n")
                code, violations, notes = self.earlier()
                self.assertEqual((code, violations, len(notes)), (1, [("BACKLOG.md", 5, "backlog-document-link")], 1))
        # A link to the earlier place whose document is in neither place.
        self.write("BACKLOG.md", self.HEAD + "- **B9** Gone — [notes](BACKLOG-B9-gone.md)\n")
        _, report = self.run_check()
        self.assertEqual([(v["line"], v["rule"], v["message"]) for v in report["violations"]], [
            (5, "backlog-document-missing",
             "BACKLOG-B9-gone.md is not beside BACKLOG.md, and the folder BACKLOG/ has no B9-gone.md")])

    def test_a_move_half_done(self):
        # Moved, and the link not yet changed: the copy in the folder is the one pointed to, no orphan.
        self.write("BACKLOG.md", self.HEAD + self.OLD_LINK)
        self.write("BACKLOG/B9-offline-journal.md", "notes\n")
        self.assertEqual(self.earlier(), (0, [], ["1 item links to that place (first: line 5)" + self.MOVE]))
        # Both copies: compare them and delete the earlier one, rather than moving it onto the other.
        both = ("; 1 is also in BACKLOG/ (first: BACKLOG-B9-offline-journal.md): compare the two copies, then "
                "delete the one beside BACKLOG.md instead of moving it")
        self.write("BACKLOG-B9-offline-journal.md", "notes\n")
        self.assertEqual(self.earlier(), (0, [], [
            "1 item document is at the earlier place beside BACKLOG.md (first: BACKLOG-B9-offline-journal.md) and "
            "1 item links to that place (first: line 5)" + self.MOVE + both]))
        # The link changed, and the copy left behind.
        self.write("BACKLOG.md", self.HEAD + "- **B9** Offline mode — [notes](BACKLOG/B9-offline-journal.md)\n")
        self.assertEqual(self.earlier(), (0, [], [
            "1 item document is at the earlier place beside BACKLOG.md (first: BACKLOG-B9-offline-journal.md)"
            + self.MOVE + both]))
        # Moved and pointed to: clean, with no note.
        (self.docs / "BACKLOG-B9-offline-journal.md").unlink()
        self.assertEqual(self.earlier(), (0, [], []))

    def test_a_folder_named_in_another_case(self):
        # Every system gives the same answer: the folder is the one named exactly BACKLOG.
        self.write("backlog/B9-a.md", "notes\n")
        self.write("BACKLOG.md", self.HEAD + "- **B9** One — [notes](backlog/B9-a.md)\n")
        _, report = self.run_check()
        self.assertEqual([(v["file"], v["line"], v["rule"]) for v in report["violations"]],
                         [("backlog", None, "backlog-folder-case"), ("BACKLOG.md", 5, "backlog-document-link")])
        self.assertEqual(report["violations"][0]["message"],
                         "differs from BACKLOG only in case: the item documents are in the folder BACKLOG, in "
                         "capitals; rename this one, or move what it holds into BACKLOG")
        self.write("BACKLOG.md", self.HEAD + "- **B9** One — [notes](BACKLOG/B9-a.md)\n")
        self.assertEqual(self.rules(), [("backlog", None, "backlog-folder-case"),
                                        ("BACKLOG.md", 5, "backlog-document-missing")])

    def test_a_folder_that_cannot_be_listed(self):
        self.write("BACKLOG", "a file, not the folder\n")
        self.assertEqual(self.found("- **B9** Offline mode — [notes](BACKLOG/B9-a.md)\n"), [])
        _, report = self.run_check()
        self.assertEqual([(v["file"], v["line"], v["rule"]) for v in report["violations"]],
                         [("BACKLOG", None, "not-a-directory")])
        (self.docs / "BACKLOG").unlink()
        outside = self.root / "outside-backlog"
        self.write("B9-a.md", "notes\n", outside)
        self.write("B4-b.md", "notes\n", outside)
        try:
            (self.docs / "BACKLOG").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"no symbolic links here: {exc}")
        self.assertEqual(self.rules(), [("BACKLOG", None, "link-outside")])


# --- The lesson index ---------------------------------------------------------

class LessonIndex(Case):
    def found(self, text: str) -> list[tuple]:
        self.write("AGENTS.md", text, self.project)
        return [(line, rule) for _, line, rule in self.rules()]

    def test_nothing_to_check(self):
        self.assertEqual(self.rules(), [])  # no AGENTS.md
        self.assertEqual(self.found("# Guide\n\n" + "x" * 400 + "\n" * 80), [])  # no markers
        self.assertEqual(self.found(f"{START}\n{END}\n"), [])
        self.assertEqual(self.found(f"text\n  {START}  \n- one\n\n- two\n{END}\n" + "x" * 400 + "\n"), [])
        self.assertEqual(self.found(f"Write the index between `{START}` and `{END}`.\n" + "x" * 400 + "\n"), [])
        self.assertEqual(self.found(f"```markdown\n{START}\n" + "x" * 400 + f"\n```\n\n{START}\n- one\n{END}\n"), [])

    def test_markers(self):
        self.assertEqual(self.found(f"{START}\n- one\n"), [(1, "index-marker-unpaired")])
        self.assertEqual(self.found(f"- one\n{END}\n"), [(2, "index-marker-unpaired")])
        self.assertEqual(self.found(f"{END}\n- one\n{START}\n"), [(1, "index-marker-unpaired")])
        self.assertEqual(self.found(f"{START}\n{START}\n- one\n{END}\n"), [(2, "index-marker-duplicate")])
        self.assertEqual(self.found(f"{START}\n- one\n{END}\n{END}\n"), [(4, "index-marker-duplicate")])

    def test_every_line_between_the_markers_counts(self):
        block = "- lesson\n\n" * 25
        self.assertEqual(self.found(f"{START}\n{block}{END}\n"), [])
        self.assertEqual(self.found(f"{START}\n{block}\n{END}\n"), [(1, "index-too-many-lines")])
        long = "x" * 151
        self.assertEqual(self.found(f"a\n{START}\n- one\n{long}\n{long}\n{END}\n{long}\n"),
                         [(4, "index-line-too-long"), (5, "index-line-too-long")])

    def test_only_the_project_root_is_looked_at(self):
        self.write("AGENTS.md", f"{START}\n", self.docs)
        self.write("AGENTS.md", f"{START}\n", self.project / "sub")
        self.assertEqual(self.rules(), [])


# --- Files --------------------------------------------------------------------

class Files(Case):
    def test_nothing_there_is_nothing_to_report(self):
        code, report = self.run_check()
        self.assertEqual((code, report["deferred"], report["violations"]), (0, [], []))
        self.assertEqual(report["summary"], {"open": 0, "state_unknown": 0, "past_date": 0, "violations": 0,
                                             "notes": 0})
        self.assertEqual(report["notes"], [])

    def test_a_file_that_is_not_utf8_is_reported_and_the_rest_is_checked(self):
        for name, where in (("DEFERRED.md", self.docs), ("BACKLOG.md", self.docs), (PLAN, self.docs),
                            (TASKS, self.docs), ("AGENTS.md", self.project)):
            (where / name).write_bytes(b"# Title\n\nLatin-1: caf\xe9\n")
        self.write("SPRINT02-PLAN-other.md", LONG + "\n")
        self.write("BACKLOG/B1-a.md", "\xff\n")
        code, report = self.run_check()
        self.assertEqual(code, 1)
        found = sorted((v["file"], v["line"], v["rule"]) for v in report["violations"])
        self.assertEqual(found, sorted([
            ("DEFERRED.md", None, "not-utf8"), ("BACKLOG.md", None, "not-utf8"), (PLAN, None, "not-utf8"),
            (TASKS, None, "not-utf8"), ("AGENTS.md", None, "not-utf8"),
            ("SPRINT02-PLAN-other.md", 1, "annotation-too-long"),
        ]))
        self.assertIn("byte 21", report["violations"][0]["message"])

    def test_lone_carriage_returns_are_a_violation_of_the_file_and_it_is_not_parsed(self):
        places = (("DEFERRED.md", self.docs), ("BACKLOG.md", self.docs), (PLAN, self.docs), (TASKS, self.docs),
                  ("AGENTS.md", self.project))
        bodies = {
            "carriage returns alone": f"{LONG}\r{LONG_TASK}\r{START}\r",
            "one among line feeds": f"# Title\n{LONG}\rmore\n{LONG_TASK}\n{START}\n",
            "two before a line feed": f"# Title\r\r\n{LONG}\n{LONG_TASK}\n{START}\n",
            "one at the very end": f"# Title\r\n{LONG}\n{LONG_TASK}\n{START}\r",
        }
        for name, body in bodies.items():
            with self.subTest(name):
                for file, where in places:
                    self.write(file, body, where)
                self.write("BACKLOG/B1-a.md", "notes\n")  # an unread backlog names no orphan
                code, report = self.run_check()
                self.assertEqual(code, 1)
                self.assertEqual(sorted((v["file"], v["line"], v["rule"]) for v in report["violations"]),
                                 sorted((file, None, "line-endings") for file, _ in places))
                self.assertEqual((report["deferred"], report["notes"]), ([], []))
        self.assertIn("3 carriage returns not directly before a newline", self.message_of("a\rb\rc\r"))
        self.assertIn("1 carriage return not directly before a newline", self.message_of("a\rb\n"))

    def message_of(self, body: str) -> str:
        for name in ("DEFERRED.md", "BACKLOG.md", PLAN, "BACKLOG/B1-a.md"):
            (self.docs / name).unlink(missing_ok=True)
        (self.project / "AGENTS.md").unlink(missing_ok=True)
        self.write(TASKS, body)
        _, report = self.run_check()
        self.assertEqual([v["rule"] for v in report["violations"]], ["line-endings"])
        return report["violations"][0]["message"]

    def test_crlf_line_ends_are_not_lone_carriage_returns(self):
        self.write(TASKS, f"## Phase 1\r\n\r\n{LONG_TASK}\r\n")
        self.write("BACKLOG.md", "# Backlog\r\n\r\nLatest assigned: B1\r\n\r\n- **B1** One\r\n")
        self.assertEqual(self.rules(), [(TASKS, 3, "tasks-line-too-long")])

    def test_a_directory_in_place_of_a_file(self):
        (self.docs / "DEFERRED.md").mkdir()
        (self.docs / PLAN).mkdir()
        self.assertEqual(self.rules(), [("DEFERRED.md", None, "not-a-file"), (PLAN, None, "not-a-file")])

    def link(self, path: Path, target: Path, directory: bool = False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"no symbolic links here: {exc}")

    def test_a_link_out_of_the_docs_directory_is_not_read(self):
        outside = self.write("secret.md", "Latest assigned: D1\n\n" + item(1, review="2000-01-01"), self.root / "outside")
        long_plan = self.write("plan.md", LONG + "\n", self.root / "outside")
        self.link(self.docs / "DEFERRED.md", outside)
        self.link(self.docs / PLAN, long_plan)
        self.link(self.project / "AGENTS.md", self.write("agents.md", f"{START}\n", self.root / "outside"))
        code, report = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(report["deferred"], [])
        self.assertEqual([(v["file"], v["rule"]) for v in report["violations"]],
                         [("DEFERRED.md", "link-outside"), (PLAN, "link-outside"), ("AGENTS.md", "link-outside")])
        self.assertNotIn("legacy", json.dumps(report))

    def test_a_link_that_stays_inside_is_read(self):
        self.write("real.md", LONG + "\n")
        self.link(self.docs / PLAN, self.docs / "real.md")
        self.assertEqual(self.rules(), [(PLAN, 1, "annotation-too-long")])

    def test_a_link_with_no_target_is_reported(self):
        self.link(self.docs / "BACKLOG.md", self.docs / "gone.md")
        self.assertEqual(self.rules(), [("BACKLOG.md", None, "unreadable")])

    def test_the_docs_directory_may_itself_be_a_link(self):
        real = self.root / "elsewhere"
        self.write(PLAN, LONG + "\n", real)
        self.link(self.project / "linked", real, directory=True)
        self.assertEqual(self.rules("--docs", str(self.project / "linked")), [(PLAN, 1, "annotation-too-long")])


# --- The command: exit codes, output, settings --------------------------------

class Command(Case):
    def rich(self):
        self.write("DEFERRED.md", deferred(
            item(1, review="2026-01-01", check_line="python tools/checks/a.py --days 30 'a b' \"c\" \\d"),
            item(2, sprint="07 P3.5", title="Décider — 日本語 \x1b[31mred\u202e"),
            "A stray line\n",
        ))
        self.write("BACKLOG.md", "Latest assigned: B2\n\n- **B1** One\n  more\n- **B3** Three\n")
        self.write(PLAN, f"### P1.1 — A\n\n{LONG}\n> more\n")
        self.write(TASKS, LONG_TASK + "\n")
        self.write("AGENTS.md", f"{START}\n", self.project)

    def code(self, *extra: str, today: str = TODAY) -> int:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check.main(self.arguments(*extra, today=today))
        self.assertEqual(code, self.child(*self.arguments(*extra, today=today))[0])
        self.assertEqual(bool(err.getvalue()), code == 2)
        self.assertEqual(bool(out.getvalue()), code != 2)
        return code

    def test_exit_codes(self):
        self.assertEqual(self.code(), 0)
        self.write(TASKS, LONG_TASK + "\n")
        self.assertEqual(self.code(), 1)
        self.write(TASKS, "")
        self.write("DEFERRED.md", deferred(item(1, review="2026-01-01")))
        self.assertEqual(self.code(), 1)
        self.assertEqual(self.code(today="2026-01-01"), 0)
        self.assertEqual(self.code(today="never"), 2)
        self.assertEqual(self.code("--docs", str(self.root / "none")), 2)

    def test_errors_are_exit_code_2(self):
        project, home = str(self.project), str(self.home)
        cases = {
            "an unknown option": ["--project", project, "--run"],
            "an abbreviated option": ["--proj", project],
            "a positional argument": ["--project", project, "extra"],
            "a missing value": ["--project"],
            "a bad date": ["--project", project, "--today", "tomorrow"],
            "a date that is none": ["--project", project, "--today", "2026-02-30"],
            "a date in another form": ["--project", project, "--today", "20261005"],
            "a project that is not there": ["--project", str(self.root / "none")],
            "a project that is a file": ["--project", str(self.write("file.md", ""))],
            "an empty project": ["--project", ""],
            "docs that are not there": ["--project", project, "--docs", str(self.root / "none")],
            "docs that are a file": ["--project", project, "--docs", str(self.write("file.md", ""))],
            "empty docs": ["--project", project, "--docs", ""],
            "a home that is not there": ["--project", project, "--home", str(self.root / "none")],
            "a home that is a file": ["--project", project, "--home", str(self.write("home-file.md", ""))],
            "an empty home": ["--project", project, "--home", ""],
            "a blank home": ["--project", project, "--home", "  "],
            "a blank project": ["--project", " "],
            "an abbreviated home": ["--project", project, "--hom", home],
        }
        for name, arguments in cases.items():
            with self.subTest(name):
                if "--home" not in arguments:
                    arguments = arguments + ["--home", home]
                code, out, err = self.child(*arguments)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("error: "), err)
                self.assertEqual(len(err.splitlines()), 1)
                with self.assertRaises(check.CheckError):
                    check.run(arguments)
        shutil.rmtree(self.docs)
        code, out, err = self.child(*self.arguments())
        self.assertEqual((code, out), (2, ""))
        self.assertIn("process.docs_dir", err)

    def test_json_and_text_hold_the_same(self):
        self.rich()
        code, text = check.run(self.arguments())
        code_json, as_json = check.run(self.arguments("--json"))
        report = json.loads(as_json)
        self.assertEqual((code, code_json, report["exit_code"]), (1, 1, 1))
        self.assertEqual(check.render_text(report), text)
        self.assertEqual(report["summary"], {"open": 2, "state_unknown": 0, "past_date": 1, "violations": 7,
                                             "notes": 0})
        for violation in report["violations"]:
            place = violation["file"] if violation["line"] is None else f"{violation['file']}:{violation['line']}"
            self.assertIn(f"{place}: {violation['rule']}: ", text)
        for entry in report["deferred"]:
            self.assertIn(f"\nD{entry['number']} — ", text)
            self.assertIn(f"  at: DEFERRED.md:{entry['line']}\n", text)
        self.assertIn("  check: python tools/checks/a.py --days 30 'a b' \"c\" \\d\n", text)
        self.assertIn("Deferred items: 2 open, 0 state unknown, 1 past its date\n", text)
        self.assertIn("Violations: 7\n", text)
        self.assertIn("\nNotes: 0\n", text)
        self.assertTrue(text.endswith("\nResult: action needed\n"))
        child_code, child_text, _ = self.child(*self.arguments())
        _, child_json, _ = self.child(*self.arguments("--json"))
        self.assertEqual((child_code, child_text, child_json), (1, text, as_json))

    def test_the_report_is_stable_and_ordered(self):
        self.rich()
        first = check.run(self.arguments("--json"))[1]
        self.assertEqual(check.run(self.arguments("--json"))[1], first)
        found = [(v["file"], v["line"]) for v in json.loads(first)["violations"]]
        self.assertEqual(found, [("DEFERRED.md", 20), ("BACKLOG.md", 4), ("BACKLOG.md", 5), (PLAN, 3), (PLAN, 4),
                                 (TASKS, 1), ("AGENTS.md", 1)])
        files = [file for file, _ in found]
        self.assertEqual(files, sorted(files, key=["DEFERRED.md", "BACKLOG.md", PLAN, TASKS, "AGENTS.md"].index))
        for name in set(files):
            lines = [line or 0 for file, line in found if file == name]
            self.assertEqual(lines, sorted(lines))

    def test_a_clean_report(self):
        code, text = check.run(self.arguments())
        self.assertEqual(code, 0)
        self.assertEqual(text.split("\n")[0], f"today: {TODAY}")
        self.assertIn("\nDeferred items: 0 open, 0 state unknown, 0 past its date\n\nViolations: 0\n\nNotes: 0\n\n"
                      "Result: nothing needs action\n", text)

    def test_the_text_report_keeps_to_one_line_per_line(self):
        self.rich()
        text = check.run(self.arguments())[1]
        self.assertIn("D2 — Décider — 日本語 \\u001b[31mred\\u202e\n", text)
        self.assertNotIn("\x1b", text)
        report = json.loads(check.run(self.arguments("--json"))[1])
        self.assertEqual(report["deferred"][1]["title"], "Décider — 日本語 \x1b[31mred\u202e")

    # U+061C and the zero-width characters, DEL, and two C1 controls.
    HIDDEN = "\u061c\u200b\u200c\u200d\u2060\ufeff\x7f\x85\x9b\u2028\U000e0001"
    HIDDEN_SHOWN = ("\\u061c\\u200b\\u200c\\u200d\\u2060\\ufeff\\u007f\\u0085\\u009b\\u2028", "\\U000e0001",
                    "\\udb40\\udc01")

    def test_hidden_characters_are_escaped_in_the_text_and_in_the_json(self):
        title = f"A{self.HIDDEN}Z"
        self.write("DEFERRED.md", deferred(item(1, title=title, check_line=f"python a.py {self.HIDDEN}")))
        self.write("BACKLOG.md", f"Latest assigned: B1\n\nstray {self.HIDDEN}\n")
        text = check.run(self.arguments())[1]
        as_json = check.run(self.arguments("--json"))[1]
        for output in (text, as_json):
            for char in self.HIDDEN + "\x1b":
                self.assertNotIn(char, output, f"U+{ord(char):04X}")
            for line in output.split("\n"):
                self.assertEqual(line, "".join(c for c in line if c.isprintable()), line)
        both, in_text, in_json = self.HIDDEN_SHOWN
        self.assertIn(f"D1 — A{both}{in_text}Z\n", text)
        self.assertIn(f"  check: python a.py {both}{in_text}\n", text)
        self.assertIn(f'"title": "A{both}{in_json}Z"', as_json)
        report = json.loads(as_json)  # the escapes are JSON's own: the exact text comes back
        self.assertEqual(report["deferred"][0]["title"], title)
        self.assertEqual(report["deferred"][0]["check"], f"python a.py {self.HIDDEN}")
        self.assertEqual(check.render_text(report), text)
        child_code, child_json, _ = self.child(*self.arguments("--json"))
        self.assertEqual((child_code, child_json), (1, as_json))
        for byte in (b"\x7f", b"\xc2\x85", b"\xc2\x9b", b"\xe2\x80\x8b", b"\xd8\x9c"):
            self.assertNotIn(byte, child_json.encode("utf-8"))

    def test_text_that_is_not_hidden_is_left_as_it_is(self):
        title = "Décider — 日本語 👍🏽 ‘quotes’ naïve Ω"
        self.write("DEFERRED.md", deferred(item(1, title=title)))
        self.assertIn(f"D1 — {title}\n", check.run(self.arguments())[1])
        self.assertIn(f'"title": "{title}"', check.run(self.arguments("--json"))[1])

    def test_an_error_is_escaped_too(self):
        odd = str(self.root / f"no\x1b[31m-such\u202e\u200b\u061c\x7f-docs")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = check.main(self.arguments("--docs", odd))
        self.assertEqual(code, 2)
        message = err.getvalue()
        self.assertEqual(len(message.splitlines()), 1)
        self.assertIn("no\\u001b[31m-such\\u202e\\u200b\\u061c\\u007f-docs", message)
        for char in "\x1b\u202e\u200b\u061c\x7f":
            self.assertNotIn(char, message)
        code, out, child_err = self.child(*self.arguments("--docs", str(self.root / "no\x1b[31m-docs")))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no\\u001b[31m-docs", child_err)
        self.assertNotIn("\x1b", child_err)
        self.assertEqual(len(child_err.splitlines()), 1)

    def test_a_working_directory_that_is_gone_is_an_error_of_one_line(self):
        gone = FileNotFoundError(2, "No such file or directory")
        err = io.StringIO()
        with mock.patch.object(check.Path, "cwd", side_effect=gone), contextlib.redirect_stderr(err):
            code = check.main(["--home", str(self.home), "--today", TODAY])
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue(), "error: the working directory cannot be read: No such file or directory; "
                                         "name the project with --project DIR\n")
        # With --project the working directory is not asked for.
        with mock.patch.object(check.Path, "cwd", side_effect=gone):
            self.assertEqual(check.run(self.arguments())[0], 0)

    @unittest.skipUnless(os.name == "posix", "a working directory cannot be removed under a process here")
    def test_a_removed_working_directory_as_a_child_process(self):
        gone = self.root / "gone"
        code = ("import os, runpy, sys\n"
                f"os.mkdir({str(gone)!r}); os.chdir({str(gone)!r}); os.rmdir({str(gone)!r})\n"
                f"sys.argv = [{str(self.lone_script)!r}, '--home', {str(self.home)!r}]\n"
                f"runpy.run_path({str(self.lone_script)!r}, run_name='__main__')\n")
        done = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, cwd=str(self.root), check=False)
        err = done.stderr.decode("utf-8")
        self.assertEqual((done.returncode, done.stdout), (2, b""), err)
        self.assertTrue(err.startswith("error: the working directory cannot be read: "), err)
        self.assertEqual(len(err.splitlines()), 1)

    def test_an_error_no_part_of_the_command_handled_is_one_line(self):
        for raised, expected in ((PermissionError(13, "Permission denied", "some/file"), "error: some/file: Permission denied\n"),
                                 (OSError("odd\nfailure"), "error: odd failure\n"),
                                 (RecursionError(), "error: the input is nested too deeply to read\n")):
            err = io.StringIO()
            with mock.patch.object(check, "build_report", side_effect=raised), contextlib.redirect_stderr(err):
                code = check.main(self.arguments())
            self.assertEqual((code, err.getvalue()), (2, expected))

    def test_a_tilde_in_project_and_home_is_expanded(self):
        self.write(TASKS, LONG_TASK + "\n")
        env = dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root))
        code, out, err = self.child("--project", "~/project", "--home", "~/home", "--today", TODAY, "--json", env=env)
        self.assertEqual(code, 1, err)
        report = json.loads(out)
        self.assertEqual(Path(report["project"]), self.project)
        self.assertEqual([v["rule"] for v in report["violations"]], ["tasks-line-too-long"])
        code, out, err = self.child("--project", "~/none", "--home", str(self.home), env=env)
        self.assertEqual((code, out, err), (2, "", "error: --project: ~/none: not a directory\n"))
        code, out, err = self.child("--project", str(self.project), "--home", "~no-such-user-here/x", env=env)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(len(err.splitlines()), 1)

    def test_output_is_utf8_with_lf_whatever_the_console(self):
        self.rich()
        env = dict(os.environ, PYTHONIOENCODING="ascii")
        code, text, _ = self.child(*self.arguments(), env=env)
        self.assertEqual(code, 1)
        self.assertIn("Décider — 日本語", text)
        self.assertEqual(text, check.run(self.arguments())[1])

    def test_the_project_is_the_working_directory_by_default(self):
        self.write(TASKS, LONG_TASK + "\n")
        code, out, err = self.child("--home", str(self.home), "--json", cwd=self.project)
        self.assertEqual(code, 1, err)
        report = json.loads(out)
        self.assertEqual([v["rule"] for v in report["violations"]], ["tasks-line-too-long"])
        self.assertEqual(Path(report["project"]).resolve(), self.project.resolve())


DEFAULTS = 'schema_version = 1\n[process]\ndocs_dir = "docs"\nquestions = "all-together"\nrecommend = true\n' \
           '[roles]\nmanager_default = false\n[memory]\ndir = "docs/memory"\n'
PROCESS_KEYS = ["process.docs_dir", "process.questions", "process.recommend"]


class Settings(Case):
    """The process group, in a clone and in a skill copied on its own."""

    def setUp(self):
        super().setUp()
        self.clone = self.root / "clone"
        self.setup_dir = self.clone / "tools" / "setup"
        self.write("workflow_setup.py", "raise SystemExit('the setup tool must not be run')\n", self.setup_dir)
        self.write("defaults.toml", DEFAULTS, self.setup_dir)
        self.script = self.clone / "prd-implementation" / "scripts" / "check.py"
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(CHECK_PY, self.script)
        in_clone = mock.patch.object(check, "SETUP_DIR", self.setup_dir)
        in_clone.start()
        self.addCleanup(in_clone.stop)
        self.write(PLAN, "")
        self.write(PLAN, LONG + "\n", self.project / "planning")
        self.write(TASKS, LONG_TASK + "\n", self.project / "local-docs")
        self.project_file = self.project / ".agents" / "workflow.toml"

    def both(self, *extra: str) -> dict:
        """The report, in process and from the copy in the scratch clone."""
        code, report = self.run_check(*extra)
        child_code, out, err = self.child(*self.arguments("--json", *extra), script=self.script, runner=True)
        self.assertEqual((child_code, json.loads(out) if out else err), (code, report))
        return report

    def refused(self, *arguments: str) -> str:
        """The one line of the error, in process and as a child process."""
        arguments = arguments or tuple(self.arguments())
        with self.assertRaises(check.CheckError) as raised:
            check.run(list(arguments))
        code, out, err = self.child(*arguments, script=self.script, runner=True)
        self.assertEqual((code, out), (2, ""), err)
        self.assertEqual(err, f"error: {check.shown(str(raised.exception))}\n")
        self.assertEqual(len(err.splitlines()), 1)
        return err

    def test_the_shipped_default(self):
        report = self.both()
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["docs_from"], "process.docs_dir")
        self.assertEqual(Path(report["docs"]), self.docs)
        self.assertEqual(list(report["settings"]), PROCESS_KEYS)  # the process group, and no other
        self.assertEqual({key: (entry["value"], entry["layer"]) for key, entry in report["settings"].items()}, {
            "process.docs_dir": ("docs", "shipped"), "process.questions": ("all-together", "shipped"),
            "process.recommend": (True, "shipped"),
        })
        for entry in report["settings"].values():
            self.assertEqual(Path(entry["file"]), self.setup_dir / "defaults.toml")
        text = check.run(self.arguments())[1]
        self.assertIn('process.docs_dir = "docs"  (shipped)\nprocess.questions = "all-together"  (shipped)\n'
                      "process.recommend = true  (shipped)\n", text)
        self.assertNotIn("memory", text)

    def test_the_project_file_is_honoured(self):
        self.write("workflow.toml", '[process]\ndocs_dir = "planning"\nquestions = "all-together"\n[memory]\ndir = "m"\n',
                   self.project / ".agents")
        report = self.both()
        self.assertEqual([v["file"] for v in report["violations"]], [PLAN])
        self.assertEqual(Path(report["docs"]), self.project / "planning")
        setting = report["settings"]["process.docs_dir"]
        self.assertEqual((setting["value"], setting["layer"]), ("planning", "project"))
        self.assertEqual(Path(setting["file"]), self.project_file)
        self.assertEqual(report["settings"]["process.questions"]["value"], "all-together")
        self.assertEqual(report["settings"]["process.recommend"]["layer"], "shipped")
        self.assertEqual(list(report["settings"]), PROCESS_KEYS)
        self.assertIn('process.docs_dir = "planning"  (project)\n', check.run(self.arguments())[1])

    def test_later_layers_win(self):
        self.write("workflow.toml", '[process]\ndocs_dir = "user-docs"\nrecommend = false\n', self.home / ".agents")
        self.write("workflow.toml", '[process]\ndocs_dir = "planning"\n', self.project / ".agents")
        self.assertEqual(self.both()["settings"]["process.docs_dir"]["layer"], "project")
        self.write("workflow.local.toml", '\ufeff[process]\ndocs_dir = "local-docs"\n', self.project / ".agents")
        report = self.both()
        self.assertEqual([v["file"] for v in report["violations"]], [TASKS])
        self.assertEqual(report["settings"]["process.docs_dir"]["layer"], "local")
        self.assertEqual((report["settings"]["process.recommend"]["value"], report["settings"]["process.recommend"]["layer"]),
                         (False, "user"))

    def test_an_absolute_docs_dir(self):
        elsewhere = self.root / "other-repository" / "docs"
        self.write(TASKS, LONG_TASK + "\n", elsewhere)
        self.write("workflow.toml", "[process]\ndocs_dir = " + json.dumps(str(elsewhere)) + "\n", self.project / ".agents")
        report = self.both()
        self.assertEqual(Path(report["docs"]), elsewhere)
        self.assertEqual([v["rule"] for v in report["violations"]], ["tasks-line-too-long"])

    def test_docs_on_the_command_line_wins(self):
        self.write("workflow.toml", '[process]\ndocs_dir = "planning"\n', self.project / ".agents")
        report = self.both("--docs", str(self.project / "local-docs"))
        self.assertEqual(report["docs_from"], "--docs")
        self.assertEqual([v["file"] for v in report["violations"]], [TASKS])
        self.write("workflow.toml", '[process]\ndocs_dir = "not-there"\n', self.project / ".agents")
        self.assertEqual(self.both("--docs", str(self.docs))["violations"], [])

    def test_a_settings_file_that_cannot_be_used_is_an_error(self):
        cases = {
            "[process\n": "is not valid TOML",
            "\xff": "is not UTF-8 text (byte 0)",
            "[process]\ndocs_dir = 3\n": "process.docs_dir: expected a string, got an integer",
            '[process]\ndocs_dir = ["docs"]\n': "process.docs_dir: expected a string, got an array",
            '[process]\ndocs_dir = "  "\n': "process.docs_dir: must not be blank; it holds only white space",
            '[process]\ndocs_dir = ""\n': "process.docs_dir: must not be empty",
            'process = "docs"\n': "process: expected a table, got a string",
            '[process]\nquestions = "sometimes"\n':
                'process.questions: "sometimes" is not allowed; allowed values: one-at-a-time, all-together',
            "[process]\nquestions = 7\n": "process.questions: expected a string, got an integer",
            '[process]\nrecommend = "yes"\n': "process.recommend: expected a boolean, got a string",
            "[process]\nrecommend = 1\n": "process.recommend: expected a boolean, got an integer",
            '[process]\ndocs = "docs"\n': "process.docs: unknown key; known here: docs_dir, questions, recommend",
            '[process]\n"odd key" = 1\n': 'process."odd key": unknown key; known here: docs_dir, questions, recommend',
            "[process.docs_dir]\nx = 1\n": "process.docs_dir: expected a string, got a table",
            'docs_dir = "docs"\n': "docs_dir: unknown key; known here: schema_version, process, roles, memory, providers, setup",
            "[proces]\n": "proces: unknown key; known here: schema_version, process, roles, memory, providers, setup",
            "schema_version = 2\n": "schema_version: 2 is newer than this command reads (1)",
            'schema_version = "1"\n': "schema_version: expected an integer, got a string",
            "schema_version = true\n": "schema_version: expected an integer, got a boolean",
            "schema_version = 0\n": "schema_version: 0 is not a schema version; the first is 1",
            "schema_version = 1.0\n": "schema_version: expected an integer, got a float",
            "schema_version = 2026-10-05\n": "schema_version: expected an integer, got a date",
            "[process]\ndocs_dir = 2026-10-05T10:00:00\n": "process.docs_dir: expected a string, got a datetime",
            "[process]\ndocs_dir = 10:00:00\n": "process.docs_dir: expected a string, got a time",
        }
        for content, expected in cases.items():
            with self.subTest(content):
                self.project_file.parent.mkdir(exist_ok=True)
                self.project_file.write_bytes(content.encode("latin-1"))
                err = self.refused()
                self.assertTrue(err.startswith(f"error: {self.project_file}: {expected}"), err)

    def test_every_layer_is_checked(self):
        for file in (self.home / ".agents" / "workflow.toml", self.project_file,
                     self.project / ".agents" / "workflow.local.toml", self.setup_dir / "defaults.toml"):
            with self.subTest(file.name):
                before = file.read_bytes() if file.is_file() else None
                self.write(file.name, '[process]\nquestions = "never"\n', file.parent)
                self.assertTrue(self.refused().startswith(f"error: {file}: process.questions: "))
                file.unlink() if before is None else file.write_bytes(before)
        self.assertEqual(self.both()["violations"], [])

    def test_a_fault_is_an_error_even_when_a_later_layer_sets_the_key(self):
        self.write("workflow.toml", '[process]\ndocs_dir = 3\n', self.home / ".agents")
        self.write("workflow.toml", '[process]\ndocs_dir = "planning"\n', self.project / ".agents")
        self.assertIn("process.docs_dir: expected a string", self.refused())
        # And with --docs: the settings are read, and checked, all the same.
        self.assertIn("process.docs_dir", self.refused(*self.arguments("--docs", str(self.docs))))

    def test_several_faults_are_one_line(self):
        self.write("workflow.toml", '[process]\ndocs_dir = 3\nnope = 1\n', self.home / ".agents")
        self.write("workflow.toml", "top = 1\n", self.project / ".agents")
        err = self.refused()
        self.assertIn("process.docs_dir: expected a string, got an integer (and 2 more in the settings files)\n", err)

    def test_a_file_of_a_newer_schema_is_not_looked_into(self):
        self.write("workflow.toml", 'schema_version = 9\nnew_group = 1\n[process]\nnew_key = 1\n', self.project / ".agents")
        err = self.refused()
        self.assertIn("schema_version: 9 is newer than this command reads (1)", err)
        self.assertNotIn("more in the settings files", err)

    def test_other_groups_are_not_looked_at(self):
        self.write("workflow.toml",
                   '[roles]\nmanager_default = "perhaps"\nnope = 1\n[providers.x]\ntiers = 1\n[memory]\ndir = []\nx = 1\n',
                   self.project / ".agents")
        self.write("workflow.toml", 'memory = "nowhere"\nroles = 3\nproviders = []\n', self.home / ".agents")
        report = self.both()
        self.assertEqual(report["violations"], [])
        self.assertEqual(list(report["settings"]), PROCESS_KEYS)

    def test_a_settings_directory_that_is_not_one(self):
        self.write(".agents", "a file\n", self.project)
        self.assertEqual(self.refused(), f"error: {self.project / '.agents'}: is not a directory; workflow.toml is "
                                         "looked for in it\n")
        (self.project / ".agents").unlink()
        self.project_file.mkdir(parents=True)
        self.assertEqual(self.refused(), f"error: {self.project_file}: is not a file\n")

    def test_shipped_defaults_that_are_missing(self):
        (self.setup_dir / "defaults.toml").unlink()
        self.assertIn("defaults.toml: the shipped defaults are missing; the clone is incomplete\n", self.refused())
        self.write("defaults.toml", "schema_version = 1\n", self.setup_dir)
        self.assertIn("process.docs_dir: set in no settings file; name the sprint docs directory with --docs DIR\n",
                      self.refused())
        self.assertEqual(self.both("--docs", str(self.docs))["settings"], {})

    def test_a_link_with_no_target_in_place_of_a_settings_file(self):
        self.project_file.parent.mkdir()
        try:
            self.project_file.symlink_to(self.root / "gone.toml")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"no symbolic links here: {exc}")
        self.assertEqual(self.refused(), f"error: link target missing: {self.project_file}\n")

    def locked(self, directory: Path) -> None:
        if os.name != "posix" or os.geteuid() == 0:
            self.skipTest("taking a directory's permissions away keeps this process out only on POSIX, and not root")
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0)
        self.addCleanup(os.chmod, directory, 0o700)

    def test_a_home_that_cannot_be_searched(self):
        self.locked(self.home)
        self.assertEqual(self.refused(), f"error: {self.home / '.agents'}: cannot be read: Permission denied\n")

    def test_a_settings_directory_that_cannot_be_searched(self):
        for directory in (self.home / ".agents", self.project / ".agents"):
            with self.subTest(directory):
                self.locked(directory)
                self.assertEqual(self.refused(),
                                 f"error: {directory / 'workflow.toml'}: cannot be read: Permission denied\n")
                os.chmod(directory, 0o700)

    def test_a_settings_file_that_cannot_be_read(self):
        self.write("workflow.toml", '[process]\ndocs_dir = "planning"\n', self.project / ".agents")
        if os.name != "posix" or os.geteuid() == 0:
            self.skipTest("a file's permissions keep this process out only on POSIX, and not root")
        os.chmod(self.project_file, 0)
        self.addCleanup(os.chmod, self.project_file, 0o600)
        self.assertEqual(self.refused(), f"error: {self.project_file}: cannot be read: Permission denied\n")

    def test_a_project_that_cannot_be_searched(self):
        self.locked(self.project)
        err = self.refused(*self.arguments("--docs", str(self.root)))
        self.assertEqual(err, f"error: {self.project / '.agents'}: cannot be read: Permission denied\n")

    def test_a_home_that_cannot_be_found(self):
        with mock.patch.object(check.Path, "home", side_effect=RuntimeError("no home")):
            with self.assertRaises(check.CheckError) as raised:
                check.run(["--project", str(self.project), "--today", TODAY])
            self.assertEqual(str(raised.exception), "the user's home directory cannot be found; name one with --home DIR")
            # Named, it is not looked for; and a skill copied on its own needs none.
            self.assertEqual(check.run(self.arguments())[0], 0)
            with mock.patch.object(check, "SETUP_DIR", self.root / "no-clone"):
                self.assertEqual(check.run(["--project", str(self.project), "--today", TODAY])[0], 0)

    def test_a_skill_copied_on_its_own_uses_the_built_in_defaults(self):
        lone = self.root / "lone" / "prd-implementation"
        shutil.copytree(SKILL, lone, ignore=shutil.ignore_patterns("__pycache__"))
        self.write("workflow.toml", '[process]\ndocs_dir = "planning"\n', self.project / ".agents")
        self.write("workflow.toml", "not TOML at all [", self.home / ".agents")
        self.write(TASKS, LONG_TASK + "\n")
        code, out, err = self.child(*self.arguments("--json"), script=lone / "scripts" / "check.py", runner=True)
        self.assertEqual(code, 1, err)
        report = json.loads(out)
        self.assertEqual(Path(report["docs"]), self.docs)
        self.assertEqual(report["settings"], {
            "process.docs_dir": {"value": "docs", "layer": "built-in", "file": None},
            "process.questions": {"value": "all-together", "layer": "built-in", "file": None},
            "process.recommend": {"value": True, "layer": "built-in", "file": None},
        })
        self.assertEqual([v["file"] for v in report["violations"]], [TASKS])

    def test_the_built_in_defaults_are_those_of_the_settings_launcher_and_the_shipped_ones(self):
        import settings
        import tomllib
        of_the_launcher = {key: value for key, value in settings.BUILT_IN.items() if key.startswith("process.")}
        self.assertEqual(check.BUILT_IN, of_the_launcher)
        self.assertEqual(list(check.BUILT_IN), list(of_the_launcher))
        self.assertEqual(list(check.BUILT_IN), [f"process.{key}" for key in check.PROCESS_KEYS])
        self.assertEqual(check.BUILT_IN_LAYER, settings.BUILT_IN_LAYER)
        self.assertEqual(check.SETTINGS_SCHEMA_VERSION, settings.SCHEMA_VERSION)
        shipped = SKILL.parent / "tools" / "setup" / "defaults.toml"
        if shipped.is_file():
            data = tomllib.loads(shipped.read_text(encoding="utf-8"))
            self.assertEqual({f"process.{key}": value for key, value in data["process"].items()}, check.BUILT_IN)
            self.assertEqual(data["schema_version"], check.SETTINGS_SCHEMA_VERSION)

    def test_no_file_holds_the_path_of_one_machine(self):
        import re
        for file in sorted(SCRIPTS.glob("*.py")) + sorted(TESTS.glob("*.py")):
            raw = file.read_bytes()
            self.assertNotIn(b"\r", raw, file.name)
            for pattern in (r"/home/\w", r"/mnt/\w", r"/Users/\w", r"\b[A-Za-z]:\\\\\w"):
                self.assertIsNone(re.search(pattern, raw.decode("utf-8")), (file.name, pattern))


# --- Sprint workspaces --------------------------------------------------------

HASH = "0123456789abcdef0123456789abcdef01234567"
HARD_PLAN = "### P1.1 — A step\n\n> Tag: hard\n"
UNTAGGED_TASKS = "## Phase 1\n\n- [ ] **P1.1** — A step\n"
ENTRY_KEYS = {"branch", "where", "path", "busy", "locked", "docs", "docs_state", "found"}
snapshot = tree  # the helper above, by a name a worktree's path does not shadow


def foreign_path(*parts: str) -> str:
    """An absolute path of the other system: a drive's on POSIX, a POSIX one on
    Windows. The drive is put together, so no source line holds one."""
    return "/".join(["/srv" if os.name == "nt" else "D" + ":", *parts])


def sprint_docs(number: str, slug: str, *kinds: str) -> dict[str, str]:
    return {f"SPRINT{number}-{kind}-{slug}.md": f"# {kind}\n" for kind in kinds}


class SprintWorkspaces(Case):
    """Fake git directories, as git lays them out; git itself is not needed."""

    def setUp(self):
        super().setUp()
        self.git = self.project / ".git"
        self.write("HEAD", "ref: refs/heads/main\n", self.git)
        self.write("main", HASH + "\n", self.git / "refs" / "heads")

    def branch(self, name: str, git: Path | None = None) -> None:
        """A loose ref of the branch ``sprint/<name>``."""
        self.write(name, HASH + "\n", (git or self.git) / "refs" / "heads" / "sprint")

    def worktree(self, name: str, head: str, docs: dict[str, str] | None = None, git: Path | None = None,
                 gitdir: str | None = None) -> Path:
        """A worktree as `git worktree add` leaves it; ``head`` is a branch or a commit."""
        tree = self.root / f"project-{name}"
        admin = (git or self.git) / "worktrees" / name
        self.write("gitdir", (gitdir or str(tree / ".git")) + "\n", admin)
        self.write("HEAD", (head if head == HASH else f"ref: refs/heads/{head}") + "\n", admin)
        self.write("commondir", "../..\n", admin)
        self.write(".git", f"gitdir: {admin}\n", tree)
        for file, text in (docs or {}).items():
            self.write(file, text, tree / "docs")
        return tree

    def report(self, *extra: str) -> tuple[int, dict, str]:
        code, report = self.run_check(*extra)
        text = check.run(self.arguments(*extra))[1]
        self.assertEqual(check.render_text(report), text)
        return code, report, text

    def entry(self, branch: str, where: str, path, docs=None, state: str = "not-read", found=(), busy=None,
              locked=None) -> dict:
        return {"branch": branch, "where": where, "path": None if path is None else str(path), "busy": busy,
                "locked": locked, "docs": None if docs is None else str(docs), "docs_state": state,
                "found": list(found)}

    def test_a_worktree_with_its_docs(self):
        own = sprint_docs("01", "output-formats", "THOUGHTS", "PRD", "PLAN", "TASKS")
        other = {"SPRINT02-PLAN-other.md": LONG + "\n", "SPRINT01-PLAN-output-format.md": LONG + "\n"}
        tree = self.worktree("project-sprint-01", "sprint/01-output-formats", {**own, **other})
        self.branch("01-output-formats")
        self.write("SPRINT01-THOUGHTS-output-formats.md", "# THOUGHTS\n")
        code, report, text = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["notes"], [])
        self.assertEqual(Path(report["git"]), self.git)
        self.assertEqual(report["sprint_workspaces"], [self.entry(
            "sprint/01-output-formats", "worktree", tree, tree / "docs", "read", ["THOUGHTS", "PRD", "PLAN", "TASKS"])])
        self.assertIn(f"\nSprint workspaces: 1\nsprint/01-output-formats: worktree {tree}; "
                      "docs there: THOUGHTS, PRD, PLAN, TASKS\n\nViolations: 0\n", text)
        # And as a child process under the audit hook: still nothing is started or written.
        before = snapshot(self.root)
        child_code, out, err = self.child(*self.arguments(), runner=True)
        self.assertEqual((child_code, out), (0, text), err)
        self.assertEqual(snapshot(self.root), before)

    def test_a_worktree_with_no_docs_of_its_sprint(self):
        tree = self.worktree("wt", "sprint/01-a", {"SPRINT02-PRD-b.md": "# PRD\n"})
        bare = self.worktree("bare", "sprint/03-c")
        _, report, text = self.report()
        self.assertEqual(report["sprint_workspaces"], [
            self.entry("sprint/01-a", "worktree", tree, tree / "docs", "read"),
            self.entry("sprint/03-c", "worktree", bare, bare / "docs", "no-directory"),
        ])
        self.assertIn(f"sprint/01-a: worktree {tree}; docs there: none\n", text)
        self.assertIn(f"sprint/03-c: worktree {bare}; no docs directory there\n", text)

    def test_in_place(self):
        self.write("HEAD", "ref: refs/heads/sprint/02-mobile-layout\n", self.git)
        self.branch("02-mobile-layout")
        self.write("SPRINT02-PLAN-mobile-layout.md", LONG + "\n")
        self.write("SPRINT02-THOUGHTS-mobile-layout.md", "# THOUGHTS\n")
        code, report, text = self.report()
        self.assertEqual(code, 1)
        # Checked once, as the docs directory's own file.
        self.assertEqual([(v["file"], v["rule"]) for v in report["violations"]],
                         [("SPRINT02-PLAN-mobile-layout.md", "annotation-too-long")])
        self.assertEqual(report["sprint_workspaces"], [self.entry(
            "sprint/02-mobile-layout", "in-place", self.project, self.docs, "read", ["THOUGHTS", "PLAN"])])
        self.assertIn("\nsprint/02-mobile-layout: in place; docs there: THOUGHTS, PLAN\n", text)
        # The shared files were read from the sprint branch's copies: one note says so.
        self.assertEqual([(n["file"], n["rule"]) for n in report["notes"]],
                         [(str(self.docs), "shared-files-on-sprint-branch")])
        self.assertIn("the project root has sprint/02-mobile-layout checked out: ", text)
        self.assertIn("they are current on the default branch\n", text)

    def test_a_branch_only_loose_and_packed(self):
        self.branch("03-loose")
        self.branch("03-loose.lock")
        self.write("packed-refs", "# pack-refs with: peeled fully-peeled sorted \n"
                   f"{HASH} refs/heads/sprint/04-packed\n^{HASH}\n{HASH} refs/heads/feature/x\n"
                   f"{HASH} refs/heads/group/05-c/member\n{HASH} refs/tags/sprint/06-tag\n"
                   f"{HASH} refs/heads/sprint/7-short\n{HASH} refs/heads/sprint/08-a/b\n"
                   f"{HASH} refs/remotes/origin/sprint/09-remote\nnot a line of git's\n", self.git)
        self.write("x", HASH + "\n", self.git / "refs" / "heads" / "group" / "05-c")
        code, report, text = self.report()
        self.assertEqual((code, report["notes"]), (0, []))
        self.assertEqual(report["sprint_workspaces"], [self.entry("sprint/03-loose", "nowhere", None),
                                                       self.entry("sprint/04-packed", "nowhere", None)])
        self.assertIn("\nSprint workspaces: 2\nsprint/03-loose: checked out nowhere, a branch only; its docs were not "
                      "read\nsprint/04-packed: checked out nowhere, a branch only; its docs were not read\n", text)

    def test_a_branch_both_loose_and_packed_is_one_entry(self):
        self.branch("01-a")
        self.write("packed-refs", f"{HASH} refs/heads/sprint/01-a\n", self.git)
        tree = self.worktree("wt", "sprint/01-a")
        self.assertEqual([entry["where"] for entry in self.report()[1]["sprint_workspaces"]], ["worktree"])
        self.assertTrue(tree.is_dir())

    def test_a_prunable_worktree(self):
        tree = self.worktree("gone", "sprint/05-gone", sprint_docs("05", "gone", "PLAN"))
        shutil.rmtree(tree)
        # A directory whose .git is gone: git prunes it too, so its docs are not read.
        bare = self.worktree("no-dotgit", "sprint/06-no-dotgit", {"SPRINT06-PLAN-no-dotgit.md": LONG + "\n"})
        (bare / ".git").unlink()
        code, report, text = self.report()
        self.assertEqual((code, report["violations"], report["notes"]), (0, [], []))
        self.assertEqual(report["sprint_workspaces"], [self.entry("sprint/05-gone", "prunable", tree),
                                                       self.entry("sprint/06-no-dotgit", "prunable", bare)])
        self.assertIn(f"sprint/05-gone: worktree {tree} is missing (git calls it prunable); its docs were not read\n",
                      text)
        self.assertIn(f"sprint/06-no-dotgit: worktree {bare} is missing (git calls it prunable)", text)

    def test_a_locked_worktree_that_is_gone_is_not_prunable(self):
        reason = self.worktree("usb", "sprint/01-usb")
        self.write("locked", "on the usb drive\n", self.git / "worktrees" / "usb")
        silent = self.worktree("silent", "sprint/02-silent")
        self.write("locked", "", self.git / "worktrees" / "silent")
        live = self.worktree("live", "sprint/03-live", sprint_docs("03", "live", "PRD"))
        self.write("locked", "kept\n", self.git / "worktrees" / "live")
        shutil.rmtree(reason)
        shutil.rmtree(silent)
        code, report, text = self.report()
        self.assertEqual((code, report["notes"]), (0, []))
        self.assertEqual(report["sprint_workspaces"], [
            self.entry("sprint/01-usb", "locked", reason, locked="on the usb drive"),
            self.entry("sprint/02-silent", "locked", silent, locked=""),
            self.entry("sprint/03-live", "worktree", live, live / "docs", "read", ["PRD"], locked="kept"),
        ])
        self.assertIn(f"sprint/01-usb: worktree {reason} is missing (locked: on the usb drive); its docs were not "
                      "read\n", text)
        self.assertIn(f"sprint/02-silent: worktree {silent} is missing (locked); its docs were not read\n", text)
        self.assertIn(f"sprint/03-live: worktree {live}; docs there: PRD\n", text)

    def test_a_worktree_written_by_git_on_the_other_system(self):
        for name, ends in (("slash", "/.git"), ("backslash", "\\.git")):
            with self.subTest(name):
                shutil.rmtree(self.git / "worktrees", ignore_errors=True)
                written = foreign_path("workspace", "project-sprint-06-other")
                if name == "backslash" and os.name != "nt":
                    written = written.split("/")[0] + "\\" + "\\".join(written.split("/")[1:])
                self.worktree("other", "sprint/06-other", gitdir=written + ends)
                code, report, text = self.report()
                self.assertEqual((code, report["violations"], report["notes"]), (0, [], []))
                # Shown exactly as git wrote it, less its /.git: not converted, not looked at.
                self.assertEqual(report["sprint_workspaces"], [self.entry("sprint/06-other", "foreign", written)])
                self.assertIn(f"sprint/06-other: worktree {written} was written by git on another system; "
                              "not looked at\n", text)

    def test_a_detached_head_in_a_rebase_or_a_bisect_keeps_its_branch(self):
        names = sprint_docs("01", "merge", "PLAN", "TASKS")
        plan, tasks = list(names)
        merge = self.worktree("merge", HASH, {plan: HARD_PLAN, tasks: UNTAGGED_TASKS})
        self.write("head-name", "refs/heads/sprint/01-merge\n", self.git / "worktrees" / "merge" / "rebase-merge")
        apply = self.worktree("apply", HASH, sprint_docs("02", "apply", "PRD"))
        self.write("head-name", "refs/heads/sprint/02-apply\n", self.git / "worktrees" / "apply" / "rebase-apply")
        bisect = self.worktree("bisect", HASH, sprint_docs("03", "bisect", "THOUGHTS"))
        self.write("BISECT_START", "sprint/03-bisect\n", self.git / "worktrees" / "bisect")
        # Detached for no such reason, or a rebase or bisect that began detached: no branch.
        self.worktree("plain", HASH)
        self.worktree("from-detached", HASH)
        self.write("head-name", "detached HEAD\n", self.git / "worktrees" / "from-detached" / "rebase-merge")
        self.write("BISECT_START", HASH + "\n", self.git / "worktrees" / "from-detached")
        # And the project root itself, in a rebase of a sprint branch.
        self.write("HEAD", HASH + "\n", self.git)
        self.write("head-name", "refs/heads/sprint/04-here\n", self.git / "rebase-merge")
        code, report, text = self.report()
        self.assertEqual(code, 1)
        self.assertEqual(report["sprint_workspaces"], [
            self.entry("sprint/01-merge", "worktree", merge, merge / "docs", "read", ["PLAN", "TASKS"], busy="rebase"),
            self.entry("sprint/02-apply", "worktree", apply, apply / "docs", "read", ["PRD"], busy="rebase"),
            self.entry("sprint/03-bisect", "worktree", bisect, bisect / "docs", "read", ["THOUGHTS"], busy="bisect"),
            self.entry("sprint/04-here", "in-place", self.project, self.docs, "read", busy="rebase"),
        ])
        # Its docs are read and checked as any worktree's.
        self.assertEqual([(v["file"], v["rule"]) for v in report["violations"]],
                         [(str(merge / "docs" / tasks), "tasks-tag-mismatch")])
        self.assertIn(f"sprint/01-merge: worktree {merge} (mid-rebase); docs there: PLAN, TASKS\n", text)
        self.assertIn(f"sprint/03-bisect: worktree {bisect} (mid-bisect); docs there: THOUGHTS\n", text)
        self.assertIn("sprint/04-here: in place (mid-rebase); docs there: none\n", text)

    def test_refs_in_the_reftable_format_are_a_note_and_no_count(self):
        self.worktree("wt", "sprint/01-a")
        self.branch("01-a")
        for name in ("a reftable directory", "a HEAD that names refs/heads/.invalid"):
            with self.subTest(name):
                if name.startswith("a reftable"):
                    (self.git / "reftable").mkdir()
                else:
                    shutil.rmtree(self.git / "reftable")
                    self.write("HEAD", "ref: refs/heads/.invalid\n", self.git)
                code, report, text = self.report()
                self.assertEqual((code, report["violations"]), (0, []))
                self.assertEqual(Path(report["git"]), self.git)
                self.assertIsNone(report["sprint_workspaces"])  # not looked for, which is not "none"
                self.assertEqual([(n["file"], n["rule"]) for n in report["notes"]], [(str(self.git), "git-reftable")])
                self.assertIn("\nSprint workspaces: not looked for (see Notes)\n\nViolations: 0\n", text)
                self.assertNotIn("Sprint workspaces: 0", text)

    def test_only_a_regular_file_of_a_bounded_size_is_read_of_git(self):
        self.branch("01-loose")
        self.write("packed-refs", f"{HASH} refs/heads/sprint/02-packed\n" * 3, self.git)
        with mock.patch.object(check, "PACKED_REFS_LIMIT", 10):
            report = self.report()[1]
        self.assertEqual([e["branch"] for e in report["sprint_workspaces"]], ["sprint/01-loose"])
        self.assertEqual([(Path(n["file"]).name, n["rule"]) for n in report["notes"]], [("packed-refs", "git-unreadable")])
        self.assertIn("is larger than 10 bytes", report["notes"][0]["message"])
        self.worktree("big", "sprint/03-big")
        self.write("HEAD", "ref: refs/heads/sprint/03-big\n" + "x" * check.LINE_FILE_LIMIT, self.git / "worktrees" / "big")
        report = self.report()[1]
        self.assertNotIn("sprint/03-big", [e["branch"] for e in report["sprint_workspaces"]])
        self.assertIn(("HEAD", "git-file-malformed"), [(Path(n["file"]).name, n["rule"]) for n in report["notes"]])

    @unittest.skipUnless(os.name == "posix", "a device and a pipe as git's files: POSIX")
    def test_a_device_or_a_pipe_among_git_files_is_a_note(self):
        self.branch("01-a")
        self.worktree("fifo", "sprint/02-fifo")
        (self.git / "worktrees" / "fifo" / "HEAD").unlink()
        os.mkfifo(self.git / "worktrees" / "fifo" / "HEAD")  # read, it would block the command
        if Path("/dev/zero").exists():
            (self.git / "packed-refs").symlink_to("/dev/zero")
        code, out, err = self.child(*self.arguments("--json"), runner=True)
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual([e["branch"] for e in report["sprint_workspaces"]], ["sprint/01-a"])
        notes = {Path(n["file"]).name: n["message"] for n in report["notes"]}
        self.assertTrue(notes["HEAD"].startswith("is not a regular file"))
        if Path("/dev/zero").exists():
            self.assertTrue(notes["packed-refs"].startswith("is not a regular file"))
        # The project's .git file as a device: a note, no section.
        shutil.rmtree(self.git)
        if Path("/dev/zero").exists():
            self.git.symlink_to("/dev/zero")
            code, report, text = self.report()
            self.assertEqual((code, report["git"]), (0, None))
            self.assertEqual([n["rule"] for n in report["notes"]], ["git-file-malformed"])

    @unittest.skipUnless(os.name == "posix", "a link loop: POSIX")
    def test_a_git_link_that_loops_or_leads_nowhere_is_a_note(self):
        shutil.rmtree(self.git)
        for target in (self.git, self.root / "gone"):
            with self.subTest(str(target)):
                if self.git.is_symlink():
                    self.git.unlink()
                self.git.symlink_to(target)
                code, report, text = self.report()
                self.assertEqual((code, report["git"], report["sprint_workspaces"]), (0, None, []))
                self.assertEqual([(n["file"], n["rule"]) for n in report["notes"]],
                                 [(str(self.git), "git-unreadable")])
                self.assertNotIn("Sprint workspaces", text)

    def test_a_directory_with_no_head_is_not_a_git_directory(self):
        empty = self.root / "empty"
        empty.mkdir()
        shutil.rmtree(self.git)
        for content in (f"gitdir: {empty}\n", f"gitdir: {Path(empty.anchor)}\n"):
            with self.subTest(content):
                self.write(".git", content, self.project)
                report = self.report()[1]
                self.assertEqual(report["git"], None)
                self.assertEqual([n["rule"] for n in report["notes"]], ["git-dir-missing"])
                self.assertIn("is not a git directory: it holds no HEAD", report["notes"][0]["message"])
        (self.project / ".git").unlink()
        (self.project / ".git").mkdir()
        self.assertIn("is not a git directory", self.report()[1]["notes"][0]["message"])

    def test_docs_named_in_a_detached_worktree_inside_the_root(self):
        inner = self.worktree("inner", HASH)
        shutil.move(str(inner), str(self.project / "inner"))
        self.write("gitdir", str(self.project / "inner" / ".git") + "\n", self.git / "worktrees" / "inner")
        (self.project / "inner" / "docs").mkdir()
        tree = self.worktree("wt", "sprint/01-k", sprint_docs("01", "k", "PRD"))
        report = self.report("--docs", str(self.project / "inner" / "docs"))[1]
        # Mapped as docs/ in the inner worktree, the deepest: so docs/ in the sprint's.
        self.assertEqual(report["sprint_workspaces"], [
            self.entry("sprint/01-k", "worktree", tree, tree / "docs", "read", ["PRD"])])

    def test_docs_in_a_repository_of_their_own_inside_the_root(self):
        self.write("HEAD", "ref: refs/heads/main\n", self.docs / ".git")
        tree = self.worktree("wt", "sprint/01-a", {"SPRINT01-PLAN-a.md": LONG + "\n"})
        code, report, text = self.report()
        self.assertEqual((code, report["violations"]), (0, []))
        self.assertEqual(report["sprint_workspaces"], [self.entry("sprint/01-a", "worktree", tree, None, "outside")])
        self.assertIn("the docs directory is outside the repository, one for every worktree\n", text)

    def test_sprint_branches_are_in_the_order_of_their_numbers(self):
        for name in ("100-big", "10-ten", "07-b", "07-a", "09-nine"):
            self.branch(name)
        self.assertEqual([e["branch"] for e in self.report()[1]["sprint_workspaces"]],
                         ["sprint/07-a", "sprint/07-b", "sprint/09-nine", "sprint/10-ten", "sprint/100-big"])

    def test_a_relative_gitdir_of_a_worktree(self):
        tree = self.worktree("rel", "sprint/01-rel", sprint_docs("01", "rel", "PRD"),
                             gitdir="/".join([".."] * 4 + ["project-rel", ".git"]))
        entries = self.report()[1]["sprint_workspaces"]
        self.assertEqual(entries, [self.entry("sprint/01-rel", "worktree", tree, tree / "docs", "read", ["PRD"])])

    def test_a_git_file_with_gitdir(self):
        shutil.rmtree(self.git)
        real = self.root / "real-git"
        self.write("HEAD", "ref: refs/heads/main\n", real)
        self.write(".git", "gitdir: ../real-git\n", self.project)
        tree = self.worktree("wt", "sprint/01-a", sprint_docs("01", "a", "THOUGHTS"), git=real)
        self.branch("02-b", git=real)
        _, report, _ = self.report()
        self.assertEqual(Path(report["git"]), real)
        self.assertEqual(report["sprint_workspaces"], [
            self.entry("sprint/01-a", "worktree", tree, tree / "docs", "read", ["THOUGHTS"]),
            self.entry("sprint/02-b", "nowhere", None),
        ])

    def test_a_project_root_that_is_a_linked_worktree(self):
        # Not where the process runs the command, but read right: the main tree is a worktree here.
        main = self.root / "main"
        common = main / ".git"
        self.write("HEAD", "ref: refs/heads/sprint/01-main\n", common)
        self.write("SPRINT01-PLAN-main.md", LONG + "\n", main / "docs")
        shutil.rmtree(self.git)
        admin = common / "worktrees" / "project"
        self.write("gitdir", str(self.project / ".git") + "\n", admin)
        self.write("HEAD", "ref: refs/heads/sprint/02-here\n", admin)
        self.write("commondir", "../..\n", admin)
        self.write(".git", f"gitdir: {admin}\n", self.project)
        code, report, _ = self.report()
        self.assertEqual(Path(report["git"]), common)
        self.assertEqual(report["sprint_workspaces"], [
            self.entry("sprint/01-main", "worktree", main, main / "docs", "read", ["PLAN"]),
            self.entry("sprint/02-here", "in-place", self.project, self.docs, "read"),
        ])
        self.assertEqual([(v["file"], v["rule"]) for v in report["violations"]],
                         [(str(main / "docs" / "SPRINT01-PLAN-main.md"), "annotation-too-long")])
        self.assertEqual(code, 1)

    def test_docs_outside_the_repository(self):
        shared = self.root / "docs-repository"
        self.write("SPRINT01-PLAN-a.md", "### P1.1 — A\n", shared)
        tree = self.worktree("wt", "sprint/01-a", {"SPRINT01-PLAN-a.md": LONG + "\n"})
        code, report, text = self.report("--docs", str(shared))
        self.assertEqual((code, report["violations"]), (0, []))
        self.assertEqual(report["sprint_workspaces"], [self.entry("sprint/01-a", "worktree", tree, None, "outside")])
        self.assertIn(f"sprint/01-a: worktree {tree}; the docs directory is outside the repository, one for every "
                      "worktree\n", text)

    def test_docs_named_in_a_worktree_are_checked_once(self):
        tree = self.worktree("wt", "sprint/01-a", {"SPRINT01-PLAN-a.md": LONG + "\n"})
        self.write("SPRINT01-PLAN-a.md", LONG + "\n")  # the project root's copy is not the one named
        _, report, text = self.report("--docs", str(tree / "docs"))
        self.assertEqual([(v["file"], v["rule"]) for v in report["violations"]],
                         [("SPRINT01-PLAN-a.md", "annotation-too-long")])
        self.assertEqual(report["sprint_workspaces"], [
            self.entry("sprint/01-a", "worktree", tree, tree / "docs", "read", ["PLAN"])])

    def test_a_violation_in_a_worktree_tasks(self):
        names = sprint_docs("01", "a", "PLAN", "TASKS")
        plan, tasks = list(names)
        tree = self.worktree("wt", "sprint/01-a", {plan: HARD_PLAN, tasks: UNTAGGED_TASKS})
        self.write(plan, HARD_PLAN)
        self.write(tasks, "## Phase 1\n\n- [ ] **P1.1** **[hard]** — A step\n")
        code, report, text = self.report()
        self.assertEqual(code, 1)
        place = tree / "docs" / tasks
        self.assertEqual([(v["file"], v["line"], v["rule"]) for v in report["violations"]],
                         [(str(place), 3, "tasks-tag-mismatch")])
        self.assertEqual(report["summary"]["violations"], 1)
        self.assertIn(f"\nViolations: 1\n{place}:3: tasks-tag-mismatch: P1.1 carries `> Tag: hard` in the PLAN "
                      "(line 3); this line has no **[hard]**\n", text)
        self.assertTrue(text.endswith("\nResult: action needed\n"))
        # The worktree's TASKS is compared with the worktree's PLAN, not the project root's.
        self.write(plan, "### P1.1 — A step\n", tree / "docs")
        self.assertEqual(self.report()[1]["violations"], [])

    def test_links_in_a_worktrees_own_docs(self):
        link = "[S86](SPRINT86-PRD-macro-releases-ingest.md) [epic](EPIC03-PRD-a.md) [set](SPRINT87-PRD-b.md)\n"
        docs = {
            "SPRINT87-THOUGHTS-b.md": "Sprint: 87\n\n" + link,
            "SPRINT87-STATE-b.md": "[w](../deploy/RUNBOOK.md) [code](../src/a.py)\n",
            "SPRINT88-PRD-c.md": link,  # another sprint's copy in this worktree: stale, not read
            "DONE/SPRINT87-PLAN-b.md": link,
        }
        tree = self.worktree("wt", "sprint/87-b", docs)
        code, report, text = self.report()
        self.assertEqual(code, 1)
        thoughts, state = (str(tree / "docs" / name) for name in ("SPRINT87-THOUGHTS-b.md", "SPRINT87-STATE-b.md"))
        self.assertEqual([(v["file"], v["line"], v["rule"]) for v in report["violations"]], [
            (thoughts, 3, "link-other-sprint"), (thoughts, 3, "link-epic-doc"), (state, 1, "link-outside-set"),
            (state, 1, "link-outside-set")])
        self.assertIn(f"\n{thoughts}:3: link-other-sprint: a link to SPRINT86-PRD-macro-releases-ingest.md, a doc of "
                      "sprint 86: ", text)
        # The path from the root is the worktree's: its docs directory is docs/ there too.
        self.assertTrue(report["violations"][3]["message"].endswith("from the project root: `src/a.py`"))
        self.assertEqual(report["sprint_workspaces"][0]["found"], ["THOUGHTS", "STATE"])

    def test_a_doc_checked_in_the_worktree_is_not_reported_from_the_docs_directory(self):
        link = "[S86](SPRINT86-PRD-macro-releases-ingest.md)\n"
        tree = self.worktree("wt", "sprint/87-b", {"SPRINT87-THOUGHTS-b.md": link})
        self.write("SPRINT87-THOUGHTS-b.md", link)  # the start commit's copy on the default branch
        self.write("SPRINT87-PRD-b.md", link)  # not in the worktree: still checked here
        self.write("SPRINT88-THOUGHTS-c.md", link)  # a sprint with no worktree
        report = self.report()[1]
        self.assertEqual([(v["file"], v["rule"]) for v in report["violations"]], [
            ("SPRINT87-PRD-b.md", "link-other-sprint"), ("SPRINT88-THOUGHTS-c.md", "link-other-sprint"),
            (str(tree / "docs" / "SPRINT87-THOUGHTS-b.md"), "link-other-sprint")])
        # A worktree that is gone checks nothing, so the docs directory's copy is reported.
        shutil.rmtree(tree)
        self.assertIn("SPRINT87-THOUGHTS-b.md", [v["file"] for v in self.report()[1]["violations"]])

    def test_a_worktree_file_that_cannot_be_read_is_a_violation_with_its_path(self):
        tree = self.worktree("wt", "sprint/01-a")
        (tree / "docs").mkdir()
        (tree / "docs" / "SPRINT01-TASKS-a.md").write_bytes(b"caf\xe9\n")
        report = self.report()[1]
        self.assertEqual([(v["file"], v["rule"]) for v in report["violations"]],
                         [(str(tree / "docs" / "SPRINT01-TASKS-a.md"), "not-utf8")])

    def test_shared_files_in_a_worktree_are_not_checked(self):
        stale = {
            "DEFERRED.md": deferred(item(1, review="2000-01-01"), "A stray line\n"),
            "BACKLOG.md": "Latest assigned: B1\n\n- **B1** One\n  more\n- **B9** Nine\n",
            "BACKLOG-B7-orphan.md": "# An orphan at the earlier place\n",
            "BACKLOG/B8-orphan.md": "# An orphan\n",
            "SPRINT-INDEX.md": "anything\n",
            "SPRINT02-TASKS-other.md": LONG_TASK + "\n",
            "SPRINT01-STATE-a.md": LONG_TASK + "\n",
            "DONE/SPRINT01-TASKS-a.md": LONG_TASK + "\n",
            "DONE/README.md": LONG_TASK + "\n",
        }
        tree = self.worktree("wt", "sprint/01-a", stale)
        code, report, _ = self.report()
        self.assertEqual((code, report["deferred"], report["violations"], report["notes"]), (0, [], [], []))
        self.assertEqual(report["sprint_workspaces"][0]["found"], ["STATE"])
        self.assertTrue((tree / "docs" / "DONE").is_dir())

    def test_a_malformed_worktree_entry_is_a_note(self):
        good = self.worktree("good", "sprint/01-good")
        no_gitdir = self.git / "worktrees" / "no-gitdir"
        self.write("HEAD", "ref: refs/heads/sprint/02-x\n", no_gitdir)
        self.worktree("odd-head", "sprint/03-x")
        self.write("HEAD", "not a head\n", self.git / "worktrees" / "odd-head")
        self.worktree("empty", "sprint/04-x")
        self.write("gitdir", "", self.git / "worktrees" / "empty")
        self.worktree("latin", "sprint/05-x")
        (self.git / "worktrees" / "latin" / "gitdir").write_bytes(b"caf\xe9\n")
        self.worktree("no-head", "sprint/06-x")
        (self.git / "worktrees" / "no-head" / "HEAD").unlink()
        self.write("stray-file", "", self.git / "worktrees")
        (self.git / "packed-refs").write_bytes(b"\xff\n")
        code, report, text = self.report()
        self.assertEqual((code, report["violations"]), (0, []))
        self.assertEqual([entry["branch"] for entry in report["sprint_workspaces"]], ["sprint/01-good"])
        self.assertEqual(report["sprint_workspaces"][0]["path"], str(good))
        found = sorted((Path(n["file"]).relative_to(self.git).as_posix(), n["rule"]) for n in report["notes"])
        self.assertEqual(found, sorted([
            ("worktrees/no-gitdir/gitdir", "git-file-malformed"), ("worktrees/odd-head/HEAD", "git-file-malformed"),
            ("worktrees/empty/gitdir", "git-file-malformed"), ("worktrees/latin/gitdir", "git-file-malformed"),
            ("worktrees/no-head/HEAD", "git-file-malformed"), ("packed-refs", "git-unreadable"),
        ]))
        self.assertEqual(report["summary"]["notes"], 6)
        self.assertIn("Notes: 6\n", text)
        self.assertTrue(text.endswith("\nResult: nothing needs action\n"))

    def test_a_git_file_that_cannot_be_followed_is_a_note(self):
        shutil.rmtree(self.git)
        for content, rule in (("not a pointer\n", "git-file-malformed"), ("", "git-file-malformed"),
                              ("gitdir: ../nowhere\n", "git-dir-missing"),
                              (f"gitdir: {foreign_path('elsewhere', '.git')}\n", "git-dir-missing")):
            with self.subTest(content):
                self.write(".git", content, self.project)
                code, report, text = self.report()
                self.assertEqual((code, report["git"], report["sprint_workspaces"]), (0, None, []))
                self.assertEqual([(n["file"], n["rule"]) for n in report["notes"]],
                                 [(str(self.project / ".git"), rule)])
                self.assertNotIn("Sprint workspaces", text)

    def test_a_commondir_that_cannot_be_followed_is_a_note(self):
        self.write("commondir", "../gone\n", self.git)
        code, report, _ = self.report()
        self.assertEqual((code, report["git"]), (0, None))
        self.assertEqual([n["rule"] for n in report["notes"]], ["git-dir-missing"])

    def test_detached_heads_and_other_branches_are_left_out(self):
        self.worktree("detached", HASH)
        self.worktree("feature", "feature/x")
        self.worktree("member", "group/01-a/member")
        self.worktree("short", "sprint/1-a")
        code, report, text = self.report()
        self.assertEqual((code, report["sprint_workspaces"], report["notes"]), (0, [], []))
        self.assertIn("\nDeferred items: 0 open, 0 state unknown, 0 past its date\n\nSprint workspaces: 0\n\n"
                      "Violations: 0\n", text)

    def test_no_git_directory_changes_nothing(self):
        shutil.rmtree(self.git)
        self.write(TASKS, LONG_TASK + "\n")
        code, report, text = self.report()
        self.assertEqual((code, report["git"], report["sprint_workspaces"], report["notes"]), (1, None, [], []))
        self.assertNotIn("Sprint workspaces", text)
        self.assertIn("\nDeferred items: 0 open, 0 state unknown, 0 past its date\n\nViolations: 1\n", text)
        self.write(".git", "", self.project / "not-a-dir")  # nothing named .git in the root itself
        self.assertEqual(self.report()[2], text)

    def test_json_shape(self):
        self.worktree("wt", "sprint/01-a", sprint_docs("01", "a", "PRD"))
        self.branch("02-b")
        code, as_json = check.run(self.arguments("--json"))
        report = json.loads(as_json)
        self.assertEqual(list(report)[:9], ["schema_version", "today", "project", "docs", "docs_from", "settings",
                                            "deferred", "git", "sprint_workspaces"])
        for entry in report["sprint_workspaces"]:
            self.assertEqual(set(entry), ENTRY_KEYS)
            self.assertIn(entry["where"], ("in-place", "worktree", "prunable", "nowhere"))
            self.assertIn(entry["docs_state"], ("read", "no-directory", "unreadable", "outside", "not-read"))
        self.assertNotIn("committed", as_json)
        child_code, child_json, _ = self.child(*self.arguments("--json"))
        self.assertEqual((child_code, child_json), (code, as_json))

    def test_names_from_disk_are_escaped(self):
        self.worktree("odd", "sprint/01-a\x1b[31m")
        text = self.report()[2]
        self.assertIn("sprint/01-a\\u001b[31m: worktree ", text)
        self.assertNotIn("\x1b", text)

    @unittest.skipIf(shutil.which("git") is None, "git is not installed")
    def test_with_real_git(self):
        shutil.rmtree(self.git)
        git = shutil.which("git")
        env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_GLOBAL=str(self.home / "no-gitconfig"))

        def run(*arguments: str, cwd: Path = self.project) -> None:
            subprocess.run([git, "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c",
                            "init.defaultBranch=main", "-c", "commit.gpgsign=false", *arguments],
                           cwd=str(cwd), env=env, check=True, capture_output=True)

        self.write("SPRINT01-THOUGHTS-x.md", "# THOUGHTS\n")
        run("init", "-q")
        run("add", ".")
        run("commit", "-q", "-m", "Start sprint 01")
        tree = self.root / "project-sprint-01-x"
        run("worktree", "add", "-q", str(tree), "-b", "sprint/01-x")
        names = sprint_docs("01", "x", "PRD", "PLAN", "TASKS")
        plan, tasks = list(names)[1:]
        for name, text in {**names, plan: HARD_PLAN, tasks: UNTAGGED_TASKS}.items():
            self.write(name, text, tree / "docs")  # not committed: the report does not need it
        run("branch", "sprint/02-y")
        run("pack-refs", "--all")
        code, report, text = self.report()
        self.assertEqual(code, 1)
        self.assertEqual(report["notes"], [])
        entries = report["sprint_workspaces"]
        self.assertEqual([(e["branch"], e["where"], e["found"]) for e in entries],
                         [("sprint/01-x", "worktree", ["THOUGHTS", "PRD", "PLAN", "TASKS"]),
                          ("sprint/02-y", "nowhere", [])])
        self.assertEqual(Path(entries[0]["path"]).resolve(), tree.resolve())
        self.assertEqual([(Path(v["file"]).name, v["rule"]) for v in report["violations"]],
                         [(tasks, "tasks-tag-mismatch")])
        self.assertIn(f"sprint/01-x: worktree {entries[0]['path']}; docs there: THOUGHTS, PRD, PLAN, TASKS\n", text)

    @unittest.skipIf(shutil.which("git") is None, "git is not installed")
    def test_with_real_git_a_rebase_and_a_lock(self):
        shutil.rmtree(self.git)
        git = shutil.which("git")
        env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_GLOBAL=str(self.home / "no-gitconfig"))

        def run(*arguments: str, cwd: Path = self.project, check: bool = True) -> None:
            subprocess.run([git, "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c",
                            "init.defaultBranch=main", "-c", "commit.gpgsign=false", *arguments],
                           cwd=str(cwd), env=env, check=check, capture_output=True)

        self.write("f.txt", "a\n", self.project)
        self.write("README.md", "# Docs\n")
        run("init", "-q")
        run("add", ".")
        run("commit", "-q", "-m", "Start")
        tree = self.root / "project-sprint-01-rb"
        run("worktree", "add", "-q", str(tree), "-b", "sprint/01-rb")
        self.write("SPRINT01-PRD-rb.md", "# PRD\n", tree / "docs")
        self.write("f.txt", "b\n", tree)
        run("add", ".", cwd=tree)
        run("commit", "-q", "-m", "Sprint", cwd=tree)
        self.write("f.txt", "c\n", self.project)
        run("commit", "-q", "-a", "-m", "Main")
        run("rebase", "main", cwd=tree, check=False)  # stops at the conflict, HEAD detached
        locked = self.root / "project-sprint-02-lock"
        run("worktree", "add", "-q", str(locked), "-b", "sprint/02-lock")
        run("worktree", "lock", "--reason", "usb drive", str(locked))
        shutil.rmtree(locked)
        code, report, text = self.report()
        self.assertEqual((code, report["notes"]), (0, []))
        self.assertEqual([(e["branch"], e["where"], e["busy"], e["locked"], e["found"])
                          for e in report["sprint_workspaces"]],
                         [("sprint/01-rb", "worktree", "rebase", None, ["PRD"]),
                          ("sprint/02-lock", "locked", None, "usb drive", [])])
        self.assertIn(" (mid-rebase); docs there: PRD\n", text)
        self.assertIn(" is missing (locked: usb drive); its docs were not read\n", text)


if __name__ == "__main__":
    unittest.main()
