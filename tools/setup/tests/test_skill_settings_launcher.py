"""The settings launcher inside the process skills and the memory skill:
scripts/settings.py.

Every run is a child process started with ``sys.executable`` from a scratch
working directory, with a scratch home, as a skill would start it.
"""
from __future__ import annotations

# The tests directory is on sys.path however this file is run (by path, by dotted name, discover, run.py).
import sys as _sys
from pathlib import Path as _Path
_sys.path[:0] = {str(_Path(__file__).resolve().parent)} - set(_sys.path)

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
SKILLS = ("prd-implementation", "epic-implementation", "project-memory")
LAUNCHERS = [CLONE / skill / "scripts" / "settings.py" for skill in SKILLS]
LAUNCHER = LAUNCHERS[0]
# What is printed without a key. ``roles`` is served only when asked for.
GROUPS = ("process", "memory")
ROLES = "roles"
KNOWN = b"not a setting a skill reads; known groups: process, memory, roles\n"
# The keys a skill reads, in the order they are printed.
KEYS = {
    "process": ("docs_dir", "questions", "recommend", "density"),
    "memory": ("dir",),
    "roles": ("max_parallel_coders",),
}


def shipped_defaults(groups: tuple[str, ...] = GROUPS) -> dict[str, object]:
    """The skill's keys of these groups of defaults.toml, by dotted key."""
    data = tomllib.loads(support.DEFAULTS.read_text(encoding="utf-8"))
    return {f"{group}.{key}": data[group][key] for group in groups for key in KEYS[group]}


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

    def settings(self, done: subprocess.CompletedProcess) -> dict:
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        return json.loads(done.stdout.decode("utf-8"))["settings"]

    def lone_copy(self, skill: str) -> Path:
        """The skill directory copied on its own: no clone around it."""
        target = self.root / "lone" / "skills" / skill
        shutil.copytree(CLONE / skill, target, ignore=shutil.ignore_patterns("__pycache__"))
        return target / "scripts" / "settings.py"

    def values(self, *argv: str, script: Path = LAUNCHER) -> dict:
        """The key -> (value, layer, file) of a run that must succeed."""
        found = self.settings(self.launcher(*argv, script=script))
        return {key: (entry["value"], entry["layer"], entry["file"]) for key, entry in found.items()}

    def stopped(self, done: subprocess.CompletedProcess, *parts: str) -> None:
        self.assertEqual((done.returncode, done.stdout), (2, b""), done.stderr)
        text = done.stderr.decode("utf-8")
        self.assertTrue(text.startswith("error: "), text)
        self.assertEqual(len(text.splitlines()), 1, text)
        for part in parts:
            self.assertIn(part, text)
        self.assertNotIn("Traceback", text)


class TheCopies(unittest.TestCase):
    def test_the_launchers_are_byte_identical(self) -> None:
        self.assertEqual(len(LAUNCHERS), 3)
        first = LAUNCHER.read_bytes()
        for file in LAUNCHERS[1:]:
            with self.subTest(skill=file.parent.parent.name):
                self.assertEqual(file.read_bytes(), first)

    def test_no_other_skill_of_the_repository_carries_one(self) -> None:
        found = sorted(file.parent.parent.name for file in CLONE.glob("*/scripts/settings.py"))
        self.assertEqual(found, sorted(SKILLS))

    def test_the_file_is_utf8_with_line_feeds_and_names_no_machine_path(self) -> None:
        raw = LAUNCHER.read_bytes()
        self.assertNotIn(b"\r", raw)
        text = raw.decode("utf-8")
        for pattern in (r"/home/", r"/mnt/", r"/Users/", r"\b[A-Za-z]:[\\/]"):
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_it_imports_only_the_standard_library(self) -> None:
        imports = re.findall(r"^(?:from|import) +([\w.]+)", LAUNCHER.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertEqual(
            sorted(set(imports)), ["__future__", "argparse", "json", "os", "pathlib", "stat", "sys", "tomllib"]
        )


class Layers(LauncherCase):
    """The settings files are read by the script itself, from scratch layers."""

    def test_without_files_every_key_is_built_in(self) -> None:
        found = self.values("--json")
        self.assertEqual(list(found), list(shipped_defaults()))
        for key, (value, layer, file) in found.items():
            self.assertEqual((value, layer, file), (shipped_defaults()[key], "built-in", None))

    def test_text_output_has_the_layer(self) -> None:
        self.write(self.user_file, '[process]\nquestions = "one-at-a-time"\n')
        done = self.launcher("process")
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertEqual(done.stdout, (
            b'process.docs_dir = "docs"  (built-in)\n'
            b'process.questions = "one-at-a-time"  (user)\n'
            b"process.recommend = true  (built-in)\n"
            b'process.density = "brief"  (built-in)\n'
        ))

    def test_without_a_key_both_groups_and_no_other(self) -> None:
        found = self.settings(self.launcher("--json"))
        self.assertEqual(list(found), list(shipped_defaults()))
        self.assertEqual(self.launcher().stdout.count(b"\n"), len(shipped_defaults()))

    def test_one_dotted_key(self) -> None:
        self.assertEqual(self.settings(self.launcher("memory.dir", "--json")), {
            "memory.dir": {"value": "docs/memory", "layer": "built-in", "file": None},
        })

    def test_the_user_file_wins_over_built_in(self) -> None:
        self.write(self.user_file, '[process]\nquestions = "one-at-a-time"\ndensity = "full"\n')
        for script in LAUNCHERS:
            with self.subTest(script=script.parent.parent.name):
                found = self.values("--json", script=script)
                self.assertEqual(found["process.questions"], ("one-at-a-time", "user", str(self.user_file)))
                self.assertEqual(found["process.density"], ("full", "user", str(self.user_file)))
                self.assertEqual(found["process.docs_dir"], ("docs", "built-in", None))

    def test_the_project_files_are_read_only_with_project(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "planning/docs"\n\n[memory]\ndir = "lessons"\n')
        self.assertEqual(self.values("--json")["process.docs_dir"], ("docs", "built-in", None))
        found = self.values("--json", "--project", str(self.project))
        self.assertEqual(found["process.docs_dir"], ("planning/docs", "project", str(self.project_file)))
        self.assertEqual(found["memory.dir"][0], "lessons")
        self.assertEqual(found["process.questions"][1], "built-in")
        # The memory skill reads its one setting as its text says.
        memory = self.launcher("memory", "--project", str(self.project), script=LAUNCHERS[2])
        self.assertEqual((memory.returncode, memory.stdout), (0, b'memory.dir = "lessons"  (project)\n'))

    def test_later_layers_win_key_by_key(self) -> None:
        self.write(self.user_file, '[process]\ndocs_dir = "u"\nquestions = "one-at-a-time"\ndensity = "full"\n')
        self.write(self.project_file, '[process]\ndocs_dir = "p"\nquestions = "all-together"\n')
        self.write(self.local_file, '[process]\ndocs_dir = "l"\n')
        found = self.values("process", "--json", "--project", str(self.project))
        self.assertEqual(found["process.docs_dir"], ("l", "local", str(self.local_file)))
        self.assertEqual(found["process.questions"], ("all-together", "project", str(self.project_file)))
        self.assertEqual(found["process.density"], ("full", "user", str(self.user_file)))
        self.assertEqual(found["process.recommend"], (True, "built-in", None))

    def test_recommend_takes_true_false_or_accept(self) -> None:
        for text, value in (("true", True), ("false", False), ('"accept"', "accept")):
            with self.subTest(text=text):
                self.write(self.user_file, f"[process]\nrecommend = {text}\n")
                self.assertEqual(self.values("process.recommend", "--json")["process.recommend"][0], value)

    def test_the_roles_group_prints_the_one_key(self) -> None:
        self.write(self.user_file, "[roles]\nmax_parallel_coders = 2\n")
        for script in LAUNCHERS:
            with self.subTest(script=script.parent.parent.name):
                one = self.launcher("roles.max_parallel_coders", script=script)
                self.assertEqual((one.returncode, one.stderr), (0, b""))
                self.assertEqual(one.stdout, b"roles.max_parallel_coders = 2  (user)\n")
                group = self.launcher(ROLES, script=script)
                self.assertEqual(group.stdout, one.stdout)
                self.assertEqual(list(self.settings(self.launcher(ROLES, "--json", script=script))),
                                 list(shipped_defaults((ROLES,))))

    def test_a_project_sets_a_roles_key(self) -> None:
        self.write(self.project_file, "[roles]\nmax_parallel_coders = 5\n")
        found = self.settings(self.launcher("roles.max_parallel_coders", "--json", "--project", str(self.project)))
        self.assertEqual(found, {
            "roles.max_parallel_coders": {"value": 5, "layer": "project", "file": str(self.project_file)},
        })

    def test_a_key_outside_the_groups_is_refused(self) -> None:
        for key in ("providers", "providers.codex.tiers.fast", "schema_version", "", "x", "role", "roles2.x"):
            with self.subTest(key=key):
                done = self.launcher(key, "--json")
                self.assertEqual((done.returncode, done.stdout), (2, b""))
                self.assertIn(KNOWN, done.stderr)
                self.assertNotIn(b"Traceback", done.stderr)

    def test_a_key_it_does_not_have_is_refused(self) -> None:
        for key in ("process.nope", "memory.dir.x", "roles.enabled", "roles.manager_default", "roles.high_stakes",
                    "roles.coder.tier", "roles.nope"):
            with self.subTest(key=key):
                done = self.launcher(key)
                self.stopped(done, f"{key}: no such setting; known: ")

    def test_the_launcher_writes_nothing(self) -> None:
        self.write(self.user_file, "[roles]\nmax_parallel_coders = 2\n")
        before = sorted(str(path) for path in self.root.rglob("*"))
        text = self.user_file.read_bytes()
        for key in (ROLES, "roles.max_parallel_coders", "process"):
            self.assertEqual(self.launcher(key).returncode, 0)
        self.assertEqual(sorted(str(path) for path in self.root.rglob("*")), before)
        self.assertEqual(self.user_file.read_bytes(), text)

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
        refused = self.child(LAUNCHER, "providers", *home, env=env)
        self.assertNotIn(b"\r", refused.stderr)


class BadFiles(LauncherCase):
    """A bad value of a key that is read, or a file that cannot be read,
    stops with exit 2 naming the file and the key; anything else is not judged."""

    def test_a_bad_value_names_the_file_and_the_key(self) -> None:
        cases = (
            ("process.docs_dir", "[process]\ndocs_dir = 1\n", "expected a string, got an integer"),
            ("process.docs_dir", '[process]\ndocs_dir = ""\n', "must not be empty"),
            ("process.docs_dir", '[process]\ndocs_dir = "  "\n', "must not be blank"),
            ("memory.dir", '[memory]\ndir = " "\n', "must not be blank"),
            ("process.questions", '[process]\nquestions = "both"\n', '"both" is not allowed; allowed values: one-at-a-time, all-together'),
            ("process.density", '[process]\ndensity = "huge"\n', "is not allowed"),
            ("process.recommend", '[process]\nrecommend = "yes"\n', '"yes" is not allowed; allowed values: true, false, accept'),
            ("process.recommend", "[process]\nrecommend = 1\n", "1 is not allowed"),
            ("roles.max_parallel_coders", "[roles]\nmax_parallel_coders = 0\n", "0 is too small; the least allowed is 1"),
            ("roles.max_parallel_coders", '[roles]\nmax_parallel_coders = "2"\n', "expected an integer, got a string"),
            ("roles.max_parallel_coders", "[roles]\nmax_parallel_coders = true\n", "expected an integer, got a boolean"),
        )
        for key, text, message in cases:
            for file in (self.user_file, self.project_file, self.local_file):
                with self.subTest(key=key, file=file.name, text=text):
                    self.write(file, text)
                    done = self.launcher(key, "--project", str(self.project))
                    self.stopped(done, f"{file}: {key}: ", message)
                    file.unlink()

    def test_a_later_layer_does_not_hide_a_bad_value(self) -> None:
        self.write(self.user_file, "[process]\ndocs_dir = 1\n")
        self.write(self.project_file, '[process]\ndocs_dir = "ok"\n')
        self.stopped(self.launcher("process.docs_dir", "--project", str(self.project)),
                     str(self.user_file), "process.docs_dir")

    def test_a_group_that_is_not_a_table_is_a_fault_when_it_is_read(self) -> None:
        self.write(self.user_file, "process = 3\n")
        self.stopped(self.launcher("process"), f"{self.user_file}: process: expected a table, got an integer")

    def test_a_fault_in_a_group_not_asked_for_does_not_get_in_the_way(self) -> None:
        self.write(self.user_file, "[roles]\nmax_parallel_coders = 0\n")
        self.assertEqual(self.values("--json")["process.docs_dir"][0], "docs")
        self.stopped(self.launcher("roles.max_parallel_coders"), "roles.max_parallel_coders")

    def test_a_file_that_is_not_toml_or_not_utf8(self) -> None:
        self.write(self.user_file, "[process\ndocs_dir = \n")
        self.stopped(self.launcher("process"), f"{self.user_file}: not valid TOML")
        self.user_file.write_bytes(b'[process]\ndocs_dir = "\xff\xfe"\n')
        self.stopped(self.launcher("process"), f"{self.user_file}: not UTF-8")
        self.write(self.local_file, "= 1\n")
        self.user_file.unlink()
        self.stopped(self.launcher("process", "--project", str(self.project)), f"{self.local_file}: not valid TOML")

    def test_a_dot_agents_that_is_not_a_directory(self) -> None:
        (self.home / ".agents").write_text("x\n", encoding="utf-8")
        self.stopped(self.launcher("process"), f"{self.home / '.agents'}: not a directory")
        (self.project / ".agents").write_text("x\n", encoding="utf-8")
        (self.home / ".agents").unlink()
        self.stopped(self.launcher("process", "--project", str(self.project)),
                     f"{self.project / '.agents'}: not a directory")

    def test_other_keys_are_not_judged(self) -> None:
        self.write(self.user_file, (
            "schema_version = 99\nunknown = 1\ninstall = 5\n"
            "[roles]\nenabled = \"maybe\"\nmanager_default = 3\nhigh_stakes = []\nmax_parallel_coders = 4\n"
            '[process]\nold = {a = 1}\n[providers.x]\ny = 1\n[setup]\nenabled = 7\n'
        ))
        self.write(self.project_file, 'install = ["a"]\n[project]\nenabled = 1\n[memory]\nother = 1\n')
        found = self.values("--json", "--project", str(self.project))
        self.assertEqual(found["process.docs_dir"], ("docs", "built-in", None))
        self.assertEqual(self.values("roles.max_parallel_coders", "--json")["roles.max_parallel_coders"][0], 4)


class PlacesAndOptions(LauncherCase):
    """``--project`` and ``--home``: an empty value is never "not given"."""

    EMPTY = b": an empty value is not a directory; name one, or leave the option out\n"

    def refused(self, done: subprocess.CompletedProcess, message: bytes) -> None:
        self.assertEqual((done.returncode, done.stdout), (2, b""), done.stderr)
        self.assertIn(message, done.stderr)
        self.assertNotIn(b"Traceback", done.stderr)

    def test_in_the_clone_an_empty_value_is_refused(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "planning"\n')
        for script in LAUNCHERS:
            for empty in ("", "  "):
                with self.subTest(script=script.parent.parent.name, empty=empty):
                    done = self.launcher("process.docs_dir", "--project", empty, script=script)
                    self.refused(done, b"error: --project" + self.EMPTY)
                    # --home is not added here: an empty one must not mean the real home.
                    done = self.child(script, "process.docs_dir", "--home", empty)
                    self.refused(done, b"error: --home" + self.EMPTY)
                    done = self.child(script, "--json", "--home", empty, "--project", str(self.project))
                    self.refused(done, b"error: --home" + self.EMPTY)

    def test_in_the_clone_a_place_that_is_not_a_directory_is_refused(self) -> None:
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
    """The skill reached through a link elsewhere reads the same files."""

    def check(self, linked: Path) -> None:
        script = linked / "scripts" / "settings.py"
        self.assertTrue(script.is_file())
        self.write(self.user_file, '[process]\ndensity = "full"\n')
        self.assertEqual(self.values("--json", script=script), self.values("--json"))
        self.assertEqual(self.values("process.density", "--json", script=script)["process.density"][1], "user")

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
        # may be on a network path: the skill is copied to the scratch
        # directory, and the junction points at that copy.
        copy = self.root / "clone" / "prd-implementation"
        shutil.copytree(CLONE / "prd-implementation", copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        linked = self.root / "provider-home" / "skills" / "prd-implementation"
        linked.parent.mkdir(parents=True)
        try:
            _winapi.CreateJunction(str(copy), str(linked))
        except OSError as exc:
            self.skipTest(f"no junction can be made here: {exc}")
        self.addCleanup(os.rmdir, linked)
        self.check(linked)


class CopiedOnItsOwn(LauncherCase):
    """A skill directory with no clone around it reads the same files."""

    def test_the_built_in_defaults_equal_the_shipped_ones(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                done = self.launcher("--json", script=self.lone_copy(skill))
                self.assertEqual((done.returncode, done.stderr), (0, b""))
                report = json.loads(done.stdout.decode("utf-8"))
                self.assertEqual(report["schema_version"], 1)
                self.assertEqual(
                    {key: entry["value"] for key, entry in report["settings"].items()}, shipped_defaults()
                )
                self.assertEqual(list(report["settings"]), list(shipped_defaults()))
                for entry in report["settings"].values():
                    self.assertEqual((entry["layer"], entry["file"]), ("built-in", None))
                self.assertNotIn(b"\r", done.stdout)

    def test_the_built_in_roles_key_equals_the_shipped_one(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                script = self.lone_copy(skill)
                report = json.loads(self.launcher(ROLES, "--json", script=script).stdout.decode("utf-8"))
                self.assertEqual(
                    {key: entry["value"] for key, entry in report["settings"].items()}, shipped_defaults((ROLES,))
                )
                one = self.launcher("roles.max_parallel_coders", script=script)
                self.assertEqual(one.stdout, b"roles.max_parallel_coders = 3  (built-in)\n")

    def test_a_copy_outside_the_clone_reads_the_files(self) -> None:
        self.write(self.user_file, '[process]\nquestions = "one-at-a-time"\n')
        self.write(self.project_file, '[process]\ndocs_dir = "planning"\n')
        self.write(self.local_file, '[memory]\ndir = "mine"\n')
        for skill in SKILLS:
            with self.subTest(skill=skill):
                script = self.lone_copy(skill)
                self.assertFalse((script.parents[2] / "tools").exists())
                done = self.launcher("--project", str(self.project), "--json", script=script)
                self.assertEqual((done.returncode, done.stderr), (0, b""))
                found = json.loads(done.stdout.decode("utf-8"))["settings"]
                self.assertEqual(found["process.questions"],
                                 {"value": "one-at-a-time", "layer": "user", "file": str(self.user_file)})
                self.assertEqual(found["process.docs_dir"],
                                 {"value": "planning", "layer": "project", "file": str(self.project_file)})
                self.assertEqual(found["memory.dir"],
                                 {"value": "mine", "layer": "local", "file": str(self.local_file)})

    def test_a_bad_value_stops_a_copy_outside_the_clone(self) -> None:
        self.write(self.project_file, "[process]\nrecommend = 5\n")
        done = self.launcher("process", "--project", str(self.project), script=self.lone_copy("project-memory"))
        self.stopped(done, f"{self.project_file}: process.recommend: ")

    def test_the_text_and_no_note(self) -> None:
        done = self.launcher(script=self.lone_copy("prd-implementation"))
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertIn(b'process.docs_dir = "docs"  (built-in)\n', done.stdout)
        self.assertIn(b'memory.dir = "docs/memory"  (built-in)\n', done.stdout)


if __name__ == "__main__":
    unittest.main()
