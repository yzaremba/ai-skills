"""The settings launcher inside the process skills: scripts/settings.py.

Every run is a child process started with ``sys.executable`` from a scratch
working directory, with a scratch home, as a skill would start it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

import support

CLONE = support.SETUP.parents[1]
SKILLS = ("prd-implementation", "epic-implementation")
LAUNCHERS = [CLONE / skill / "scripts" / "settings.py" for skill in SKILLS]
LAUNCHER = LAUNCHERS[0]
GROUPS = ("process", "memory")


def shipped_defaults() -> dict[str, object]:
    """The process and memory groups of defaults.toml, by dotted key."""
    data = tomllib.loads(support.DEFAULTS.read_text(encoding="utf-8"))
    return {f"{group}.{key}": value for group in GROUPS for key, value in data[group].items()}


class LauncherCase(support.ScratchCase):
    def child(self, script: Path, *argv: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        if env is None:
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        return subprocess.run(
            [sys.executable, "-B", str(script), *argv],
            cwd=self.root, env=env, capture_output=True, timeout=120,
        )

    def launcher(self, *argv: str, script: Path = LAUNCHER) -> subprocess.CompletedProcess:
        return self.child(script, *argv, "--home", str(self.home))

    def tool(self, *argv: str) -> subprocess.CompletedProcess:
        return self.child(support.SCRIPT, "show", *argv, "--home", str(self.home))

    def settings(self, done: subprocess.CompletedProcess) -> dict:
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        return json.loads(done.stdout.decode("utf-8"))["settings"]

    def lone_copy(self, skill: str) -> Path:
        """The skill directory copied on its own: no clone around it."""
        target = self.root / "lone" / "skills" / skill
        shutil.copytree(CLONE / skill, target, ignore=shutil.ignore_patterns("__pycache__"))
        return target / "scripts" / "settings.py"


class TheTwoCopies(unittest.TestCase):
    def test_the_two_launchers_are_byte_identical(self) -> None:
        first, second = (file.read_bytes() for file in LAUNCHERS)
        self.assertEqual(first, second)

    def test_the_file_is_utf8_with_line_feeds_and_names_no_machine_path(self) -> None:
        raw = LAUNCHER.read_bytes()
        self.assertNotIn(b"\r", raw)
        text = raw.decode("utf-8")
        for pattern in (r"/home/", r"/mnt/", r"/Users/", r"\b[A-Za-z]:[\\/]"):
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_it_imports_only_the_standard_library(self) -> None:
        imports = re.findall(r"^(?:from|import) +([\w.]+)", LAUNCHER.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertEqual(
            sorted(set(imports)), ["__future__", "argparse", "json", "pathlib", "subprocess", "sys"]
        )


class InTheClone(LauncherCase):
    def test_a_group_gives_what_show_gives(self) -> None:
        self.write(self.user_file, '[process]\nquestions = "all-together"\n')
        for script in LAUNCHERS:
            for group in GROUPS:
                with self.subTest(script=script.parent.parent.name, group=group):
                    ours = self.launcher(group, "--json", script=script)
                    theirs = self.tool(group, "--json")
                    self.assertEqual(self.settings(ours), self.settings(theirs))
                    self.assertEqual(ours.stdout, theirs.stdout)
        self.assertEqual(self.settings(self.launcher("process", "--json"))["process.questions"]["layer"], "user")

    def test_text_output_is_what_show_prints(self) -> None:
        ours, theirs = self.launcher("process"), self.tool("process")
        self.assertEqual((ours.returncode, ours.stderr), (0, b""))
        self.assertEqual(ours.stdout, theirs.stdout)
        self.assertIn(b'process.docs_dir = "docs"  (shipped)\n', ours.stdout)

    def test_without_a_key_both_groups_and_no_other(self) -> None:
        found = self.settings(self.launcher("--json"))
        expected = {**self.settings(self.tool("process", "--json")), **self.settings(self.tool("memory", "--json"))}
        self.assertEqual(found, expected)
        self.assertEqual(list(found), list(shipped_defaults()))
        text = self.launcher()
        self.assertEqual(text.stdout, self.tool("process").stdout + self.tool("memory").stdout)

    def test_one_dotted_key(self) -> None:
        found = self.settings(self.launcher("memory.dir", "--json"))
        self.assertEqual(found, {
            "memory.dir": {"value": "docs/memory", "layer": "shipped", "file": str(support.DEFAULTS)},
        })

    def test_a_project_override_is_honoured_with_project(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "planning/docs"\n\n[memory]\ndir = "lessons"\n')
        without = self.settings(self.launcher("--json"))
        self.assertEqual(without["process.docs_dir"]["value"], "docs")
        found = self.settings(self.launcher("--json", "--project", str(self.project)))
        self.assertEqual(found["process.docs_dir"], {
            "value": "planning/docs", "layer": "project", "file": str(self.project_file),
        })
        self.assertEqual(found["memory.dir"]["value"], "lessons")
        self.assertEqual(found["process.questions"]["layer"], "shipped")
        self.assertEqual(found, {
            **self.settings(self.tool("process", "--json", "--project", str(self.project))),
            **self.settings(self.tool("memory", "--json", "--project", str(self.project))),
        })

    def test_a_fault_in_another_group_does_not_get_in_the_way(self) -> None:
        self.write(self.user_file, "[roles]\nmax_parallel_coders = 0\n")
        self.assertEqual(self.settings(self.launcher("--json"))["process.docs_dir"]["value"], "docs")

    def test_the_tools_error_and_exit_code_come_through(self) -> None:
        self.write(self.user_file, "[process]\ndocs_dir = 1\n")
        done = self.launcher("process", "--json")
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertEqual(
            done.stderr.decode("utf-8"),
            f"error: {self.user_file}: process.docs_dir: expected a string, got an integer\n",
        )
        unknown = self.launcher("process.nope")
        self.assertEqual((unknown.returncode, unknown.stdout), (2, b""))
        self.assertIn(b"process.nope: no such setting", unknown.stderr)

    def test_a_key_outside_the_two_groups_is_refused(self) -> None:
        for key in ("roles", "roles.coder.tier", "providers", "providers.codex.tiers.fast", "schema_version", "", "x"):
            with self.subTest(key=key):
                done = self.launcher(key, "--json")
                self.assertEqual((done.returncode, done.stdout), (2, b""))
                self.assertIn(b"not a setting a skill reads; known groups: process, memory\n", done.stderr)
                self.assertNotIn(b"Traceback", done.stderr)

    def test_output_is_utf8_with_line_feeds_whatever_the_locale(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "café/中"\n')
        env = {key: value for key, value in os.environ.items() if not key.startswith(("LC_", "PYTHON"))}
        env.update({"LANG": "C", "LC_ALL": "C", "PYTHONIOENCODING": "ascii"})
        home = ["--home", str(self.home)]
        text = self.child(LAUNCHER, *home, env=env)
        self.assertEqual((text.returncode, text.stderr), (0, b""))
        self.assertIn('process.docs_dir = "café/中"  (user)\n'.encode("utf-8"), text.stdout)
        self.assertNotIn(b"\r", text.stdout)
        self.assertTrue(text.stdout.endswith(b"\n"))
        as_json = self.child(LAUNCHER, "--json", *home, env=env)
        self.assertEqual((as_json.returncode, as_json.stderr), (0, b""))
        self.assertNotIn(b"\r", as_json.stdout)
        self.assertTrue(as_json.stdout.endswith(b"\n"))
        report = json.loads(as_json.stdout.decode("utf-8"))
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["settings"]["process.docs_dir"]["value"], "café/中")
        refused = self.child(LAUNCHER, "roles", *home, env=env)
        self.assertNotIn(b"\r", refused.stderr)


class PlacesAndOptions(LauncherCase):
    """``--project`` and ``--home``: an empty value is never "not given"."""

    EMPTY = b": an empty value is not a directory; name one, or leave the option out\n"

    def refused(self, done: subprocess.CompletedProcess, message: bytes) -> None:
        self.assertEqual((done.returncode, done.stdout), (2, b""), done.stderr)
        self.assertIn(message, done.stderr)
        self.assertNotIn(b"Traceback", done.stderr)

    def test_in_the_clone_an_empty_value_reaches_the_tool_and_is_refused(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "planning"\n')
        for script in LAUNCHERS:
            for empty in ("", "  "):
                with self.subTest(script=script.parent.parent.name, empty=empty):
                    done = self.launcher("process.docs_dir", "--project", empty, script=script)
                    self.refused(done, b"error: --project" + self.EMPTY)
                    self.assertEqual(done.stderr, self.tool("process.docs_dir", "--project", empty).stderr)
                    # --home is not added here: an empty one must not mean the real home.
                    done = self.child(script, "process.docs_dir", "--home", empty)
                    self.refused(done, b"error: --home" + self.EMPTY)
                    done = self.child(script, "--json", "--home", empty, "--project", str(self.project))
                    self.refused(done, b"error: --home" + self.EMPTY)

    def test_in_the_clone_a_place_that_is_not_a_directory_is_refused_by_the_tool(self) -> None:
        missing = str(self.root / "none")
        self.refused(self.launcher("process", "--project", missing), f"--project: {missing}: not a directory\n".encode())
        self.refused(self.child(LAUNCHER, "process", "--home", missing), f"--home: {missing}: not a directory\n".encode())

    def test_a_copy_on_its_own_refuses_an_empty_value_itself(self) -> None:
        script = self.lone_copy("prd-implementation")
        for empty in ("", " \t"):
            with self.subTest(empty=empty):
                self.refused(self.launcher("process.docs_dir", "--project", empty, script=script),
                             b"error: --project" + self.EMPTY)
                self.refused(self.child(script, "process.docs_dir", "--home", empty), b"error: --home" + self.EMPTY)
                self.refused(self.child(script, "--json", "--home", empty), b"error: --home" + self.EMPTY)

    def test_a_copy_on_its_own_refuses_a_place_that_is_not_a_directory(self) -> None:
        script = self.lone_copy("epic-implementation")
        missing = str(self.root / "none")
        a_file = str(self.write(self.root / "a-file", "x\n"))
        for place in (missing, a_file):
            with self.subTest(place=place):
                done = self.launcher("process.docs_dir", "--project", place, script=script)
                self.refused(done, f"error: --project: {place}: not a directory\n".encode())
                self.assertEqual(len(done.stderr.splitlines()), 1)
                done = self.child(script, "process.docs_dir", "--home", place)
                self.refused(done, f"error: --home: {place}: not a directory\n".encode())
        done = self.launcher("process.docs_dir", "--project", str(self.project), script=script)
        self.assertEqual((done.returncode, done.stdout), (0, b'process.docs_dir = "docs"  (built-in)\n'))

    def test_a_copy_on_its_own_expands_a_tilde_as_the_tool_does(self) -> None:
        script = self.lone_copy("prd-implementation")
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        env.update({"HOME": str(self.root), "USERPROFILE": str(self.root)})
        done = self.child(script, "process.docs_dir", "--project", "~/project", "--home", "~/home", env=env)
        self.assertEqual((done.returncode, done.stdout), (0, b'process.docs_dir = "docs"  (built-in)\n'))
        self.refused(self.child(script, "process.docs_dir", "--project", "~/none", env=env),
                     b"error: --project: ~/none: not a directory\n")

    def test_an_abbreviated_option_is_refused(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "planning"\n')
        lone = self.lone_copy("prd-implementation")
        for script in (*LAUNCHERS, lone):
            for option, value in (("--proj", str(self.project)), ("--pro", str(self.project)), ("--hom", str(self.home)),
                                  ("--js", None)):
                with self.subTest(script=script.parent.parent.name, option=option):
                    argv = ["process.docs_dir", option] + ([] if value is None else [value])
                    done = self.child(script, *argv, "--home", str(self.home)) if option != "--hom" \
                        else self.child(script, *argv)
                    self.assertEqual((done.returncode, done.stdout), (2, b""))
                    self.assertIn(b"unrecognized arguments", done.stderr)
                    self.assertNotIn(b"Traceback", done.stderr)
        # Written in full, the same options work.
        done = self.launcher("process.docs_dir", "--project", str(self.project))
        self.assertEqual((done.returncode, done.stdout), (0, b'process.docs_dir = "planning"  (project)\n'))


class ThroughALink(LauncherCase):
    """The skill reached through a link elsewhere still finds the clone."""

    def check(self, linked: Path, clone: Path = CLONE) -> None:
        script = linked / "scripts" / "settings.py"
        self.assertTrue(script.is_file())
        self.assertFalse((linked.parent.parent / "tools").exists())
        defaults = (clone / "tools" / "setup" / "defaults.toml").resolve()
        found = self.settings(self.launcher("--json", script=script))
        self.assertEqual(
            {key: entry["value"] for key, entry in found.items()},
            {key: entry["value"] for key, entry in self.settings(self.launcher("--json")).items()},
        )
        for entry in found.values():
            self.assertEqual((entry["layer"], Path(entry["file"])), ("shipped", defaults))

    def test_through_a_symlinked_skill_directory(self) -> None:
        linked = self.root / "provider-home" / "skills" / "prd-implementation"
        linked.parent.mkdir(parents=True)
        try:
            os.symlink(CLONE / "prd-implementation", linked, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are not permitted here: {exc}")
        self.check(linked)

    @unittest.skipUnless(sys.platform == "win32", "junctions are a Windows matter")
    def test_through_a_junction_to_the_skill_directory(self) -> None:
        import _winapi

        # A junction reaches only a local volume, and the clone under test
        # may be on a network path: the skill and the setup tool are copied
        # to the scratch directory, and the junction points at that copy.
        clone = self.root / "clone"
        skip = shutil.ignore_patterns("__pycache__", "tests")
        shutil.copytree(CLONE / "prd-implementation", clone / "prd-implementation", ignore=skip)
        shutil.copytree(support.SETUP, clone / "tools" / "setup", ignore=skip)
        linked = self.root / "provider-home" / "skills" / "prd-implementation"
        linked.parent.mkdir(parents=True)
        try:
            _winapi.CreateJunction(str(clone / "prd-implementation"), str(linked))
        except OSError as exc:
            self.skipTest(f"no junction can be made here: {exc}")
        self.addCleanup(os.rmdir, linked)
        self.check(linked, clone)


class CopiedOnItsOwn(LauncherCase):
    """A skill directory with no clone around it prints its built-in defaults."""

    def test_the_built_in_defaults_equal_the_shipped_ones(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                done = self.launcher("--json", script=self.lone_copy(skill))
                self.assertEqual(done.returncode, 0)
                report = json.loads(done.stdout.decode("utf-8"))
                self.assertEqual(report["schema_version"], 1)
                self.assertEqual(
                    {key: entry["value"] for key, entry in report["settings"].items()}, shipped_defaults()
                )
                self.assertEqual(list(report["settings"]), list(shipped_defaults()))
                for entry in report["settings"].values():
                    self.assertEqual((entry["layer"], entry["file"]), ("built-in", None))
                self.assertIn(b"built-in defaults", done.stderr)
                self.assertNotIn(b"\r", done.stdout + done.stderr)

    def test_the_text_has_the_tools_form(self) -> None:
        done = self.launcher(script=self.lone_copy("prd-implementation"))
        self.assertEqual(done.returncode, 0)
        shipped = self.tool("process").stdout + self.tool("memory").stdout
        self.assertEqual(done.stdout, shipped.replace(b"(shipped)", b"(built-in)"))

    def test_a_group_and_a_key(self) -> None:
        script = self.lone_copy("prd-implementation")
        group = json.loads(self.launcher("memory", "--json", script=script).stdout.decode("utf-8"))
        self.assertEqual(list(group["settings"]), ["memory.dir"])
        key = self.launcher("process.questions", script=script)
        self.assertEqual(key.stdout, b'process.questions = "one-at-a-time"  (built-in)\n')

    def test_no_settings_file_is_read_and_the_note_says_so(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "planning"\n')
        done = self.launcher("process.docs_dir", "--project", str(self.project),
                             script=self.lone_copy("prd-implementation"))
        self.assertEqual(done.stdout, b'process.docs_dir = "docs"  (built-in)\n')
        self.assertIn(b"no settings file was read", done.stderr)

    def test_keys_it_does_not_have_are_refused(self) -> None:
        script = self.lone_copy("epic-implementation")
        for key in ("roles", "providers.codex", "process.nope", "memory.dir.x", "processes"):
            with self.subTest(key=key):
                done = self.launcher(key, script=script)
                self.assertEqual((done.returncode, done.stdout), (2, b""))
                self.assertTrue(done.stderr.startswith(b"error: "))
                self.assertNotIn(b"Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
