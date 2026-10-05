"""``check.py`` of the sprint skill reads the process group as ``show`` does.

``prd-implementation/scripts/check.py`` must start no process, so it cannot
ask the setup tool: it reads the settings files itself. This test holds the
two readers together. Over a table of scratch homes and projects, valid and
not, it runs ``workflow_setup.py show process --json`` and ``check.py
--json`` as child processes and asserts the same values, layers and files,
and the same success or failure.

Both run on the repository itself (its shipped defaults), with a scratch
home and a scratch project; nothing of the real home is read.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import support
from wfsetup import schema

CLONE = support.REPOSITORY
CHECK_PY = CLONE / "prd-implementation" / "scripts" / "check.py"
TODAY = "2026-10-05"

USER, PROJECT, LOCAL = "user", "project", "local"


class Case:
    """One row of the table: the files of the layers, and what must follow.

    ``error`` is None when both readers succeed; otherwise it is the layer
    whose file both must name, and ``names`` holds what else both errors
    must hold (the key, and the words for the fault).
    """

    def __init__(self, name: str, files: dict[str, str | bytes] | None = None, error: str | None = None,
                 names: tuple[str, ...] = (), expect: dict[str, tuple[object, str]] | None = None) -> None:
        self.name = name
        self.files = files or {}
        self.error = error
        self.names = names
        self.expect = expect or {}


SHIPPED = {
    "process.docs_dir": ("docs", "shipped"),
    "process.questions": ("one-at-a-time", "shipped"),
    "process.recommend": (True, "shipped"),
}

TABLE = [
    # --- valid ---------------------------------------------------------------
    Case("defaults only", expect=SHIPPED),
    Case("a user layer", {USER: '[process]\nquestions = "all-together"\n'},
         expect={**SHIPPED, "process.questions": ("all-together", "user")}),
    Case("a project layer", {PROJECT: '[process]\ndocs_dir = "planning/docs"\n'},
         expect={**SHIPPED, "process.docs_dir": ("planning/docs", "project")}),
    Case("a local layer", {LOCAL: "[process]\nrecommend = false\n"},
         expect={**SHIPPED, "process.recommend": (False, "local")}),
    Case("user, project and local layers, each winning one key", {
        USER: '[process]\ndocs_dir = "u"\nquestions = "all-together"\nrecommend = false\n',
        PROJECT: '[process]\ndocs_dir = "p"\nrecommend = true\n',
        LOCAL: '[process]\ndocs_dir = "l"\n',
    }, expect={"process.docs_dir": ("l", "local"), "process.questions": ("all-together", "user"),
               "process.recommend": (True, "project")}),
    Case("a later layer that sets the shipped value again", {PROJECT: '[process]\ndocs_dir = "docs"\n'},
         expect={**SHIPPED, "process.docs_dir": ("docs", "project")}),
    Case("an empty process table", {USER: "[process]\n", PROJECT: "schema_version = 1\n", LOCAL: ""}, expect=SHIPPED),
    Case("a byte order mark", {PROJECT: '\ufeff[process]\ndocs_dir = "bom"\n'},
         expect={**SHIPPED, "process.docs_dir": ("bom", "project")}),
    Case("a value that is not ASCII, and an absolute one", {
        USER: '[process]\ndocs_dir = "café/中"\n', LOCAL: '[process]\ndocs_dir = "/srv/elsewhere/docs"\n',
    }, expect={**SHIPPED, "process.docs_dir": ("/srv/elsewhere/docs", "local")}),
    Case("an inline table and dotted keys", {
        USER: 'process = { docs_dir = "inline" }\n', PROJECT: 'process.questions = "all-together"\n',
    }, expect={**SHIPPED, "process.docs_dir": ("inline", "user"), "process.questions": ("all-together", "project")}),
    # A fault in another group must not reach a reader of the process group.
    Case("a fault in [memory]", {USER: "[memory]\ndir = []\nnope = 1\n", PROJECT: 'memory = "nowhere"\n'}, expect=SHIPPED),
    Case("a fault in [roles]", {
        USER: '[roles]\nmax_parallel_coders = 0\nmanager_default = "perhaps"\n', PROJECT: "[roles.Not_An_Id]\ntier = 1\n",
        LOCAL: '[roles.coder]\ntier = "enormous"\n[process]\ndocs_dir = "l"\n',
    }, expect={**SHIPPED, "process.docs_dir": ("l", "local")}),
    Case("a fault in [providers]", {
        USER: "[providers.codex]\ntiers = 1\n", PROJECT: 'providers = "none"\n', LOCAL: "[providers.x.efforts]\nlow = 3\n",
    }, expect=SHIPPED),
    # --- not valid -------------------------------------------------------------
    Case("a bad enumeration value", {USER: '[process]\nquestions = "sometimes"\n'}, USER,
         ("process.questions", '"sometimes" is not allowed', "allowed values: one-at-a-time, all-together")),
    Case("an enumeration value of another case", {LOCAL: '[process]\nquestions = "All-Together"\n'}, LOCAL,
         ("process.questions", "is not allowed")),
    Case("an unknown key under [process]", {PROJECT: '[process]\ndocs = "docs"\n'}, PROJECT,
         ("process.docs", "unknown key; known here: docs_dir, questions, recommend")),
    Case("an unknown quoted key under [process]", {PROJECT: '[process]\n"docs dir" = "docs"\n'}, PROJECT,
         ('process."docs dir"', "unknown key")),
    Case("an unknown top-level key", {LOCAL: 'docs_dir = "docs"\n'}, LOCAL,
         ("docs_dir: unknown key; known here: schema_version, process, roles, memory, providers",)),
    Case("an unknown top-level table", {USER: '[proces]\ndocs_dir = "docs"\n'}, USER, ("proces: unknown key",)),
    Case("a wrong type: an integer for a string", {PROJECT: "[process]\ndocs_dir = 3\n"}, PROJECT,
         ("process.docs_dir: expected a string, got an integer",)),
    Case("a wrong type: a string for a boolean", {USER: '[process]\nrecommend = "yes"\n'}, USER,
         ("process.recommend: expected a boolean, got a string",)),
    Case("a wrong type: an integer for a boolean", {USER: "[process]\nrecommend = 1\n"}, USER,
         ("process.recommend: expected a boolean, got an integer",)),
    Case("a wrong type: a boolean for a string", {LOCAL: "[process]\nquestions = true\n"}, LOCAL,
         ("process.questions: expected a string, got a boolean",)),
    Case("a wrong type: an array", {LOCAL: '[process]\ndocs_dir = ["docs"]\n'}, LOCAL,
         ("process.docs_dir: expected a string, got an array",)),
    Case("a wrong type: a table for a value", {LOCAL: '[process.docs_dir]\nx = "docs"\n'}, LOCAL,
         ("process.docs_dir: expected a string, got a table",)),
    Case("a wrong type: a date", {LOCAL: "[process]\ndocs_dir = 2026-10-05\n"}, LOCAL,
         ("process.docs_dir: expected a string, got a date",)),
    Case("a wrong type: the group is not a table", {PROJECT: 'process = "docs"\n'}, PROJECT,
         ("process: expected a table, got a string",)),
    Case("a blank string", {PROJECT: '[process]\ndocs_dir = "  \\t"\n'}, PROJECT,
         ("process.docs_dir: must not be blank",)),
    Case("an empty string", {USER: '[process]\ndocs_dir = ""\n'}, USER, ("process.docs_dir: must not be empty",)),
    Case("a newer schema_version", {USER: "schema_version = 2\n"}, USER, ("schema_version: 2 is newer than",)),
    Case("a newer schema_version in a file that sets nothing else wrong", {
        PROJECT: 'schema_version = 99\n[process]\ndocs_dir = "later"\n',
    }, PROJECT, ("schema_version: 99 is newer than",)),
    Case("a schema_version below the first", {LOCAL: "schema_version = 0\n"}, LOCAL,
         ("schema_version: 0 is not a schema version",)),
    Case("a schema_version that is a string", {LOCAL: 'schema_version = "1"\n'}, LOCAL,
         ("schema_version: expected an integer, got a string",)),
    Case("a schema_version that is a boolean", {USER: "schema_version = true\n"}, USER,
         ("schema_version: expected an integer, got a boolean",)),
    Case("a fault in a layer that a later layer overrides", {
        USER: "[process]\ndocs_dir = 3\n", PROJECT: '[process]\ndocs_dir = "p"\n',
    }, USER, ("process.docs_dir: expected a string, got an integer",)),
    Case("a fault in [process] beside faults in other groups", {
        PROJECT: '[memory]\ndir = []\n[roles]\nnope = 1\n[process]\nquestions = "x"\n',
    }, PROJECT, ("process.questions",)),
    Case("a file that is not TOML", {PROJECT: "[process\n"}, PROJECT, ("is not valid TOML",)),
    Case("a file that is not UTF-8", {USER: b"[process]\ndocs_dir = \"caf\xe9\"\n"}, USER, ("is not UTF-8 text (byte ",)),
]


class Agreement(support.ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.docs = self.root / "any-docs"
        self.docs.mkdir()
        self.files = {USER: self.user_file, PROJECT: self.project_file, LOCAL: self.local_file}
        # ``~`` leads to the scratch directory on every platform.
        self.env = support.child_environment()
        self.env.update({"HOME": str(self.root), "USERPROFILE": str(self.root)})

    def child(self, *command: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", *command], cwd=self.root, env=self.env, capture_output=True,
                              timeout=120, check=False)

    def both(self, project: str | None = None, home: str | None = None) -> tuple[subprocess.CompletedProcess, ...]:
        places = ["--project", str(self.project) if project is None else project,
                  "--home", str(self.home) if home is None else home]
        tool = self.child(str(support.SCRIPT), "show", "process", "--json", *places)
        # --docs keeps the directory the setting names out of the comparison.
        check = self.child(str(CHECK_PY), "--json", "--docs", str(self.docs), "--today", TODAY, *places)
        return tool, check

    def agree(self, tool: subprocess.CompletedProcess, check: subprocess.CompletedProcess) -> dict | None:
        """Assert the same outcome. Returns the settings, or None when both refused."""
        self.assertNotIn(b"Traceback", tool.stderr + check.stderr)
        self.assertEqual(tool.returncode == 0, check.returncode == 0, (tool.stderr, check.stderr))
        if tool.returncode != 0:
            self.assertEqual((tool.returncode, tool.stdout), (2, b""))
            self.assertEqual((check.returncode, check.stdout), (2, b""))
            self.assertTrue(check.stderr.startswith(b"error: "))
            self.assertEqual(len(check.stderr.splitlines()), 1, check.stderr)
            return None
        self.assertEqual((tool.stderr, check.stderr), (b"", b""))
        of_the_tool = json.loads(tool.stdout.decode("utf-8"))["settings"]
        of_check = json.loads(check.stdout.decode("utf-8"))["settings"]
        self.assertEqual(of_check, of_the_tool)
        self.assertEqual(list(of_check), list(of_the_tool))  # and in the same order
        return of_check

    def test_the_table(self) -> None:
        for case in TABLE:
            with self.subTest(case.name):
                for file in self.files.values():
                    file.unlink(missing_ok=True)
                for layer, content in case.files.items():
                    data = content if isinstance(content, bytes) else content.encode("utf-8")
                    self.files[layer].parent.mkdir(exist_ok=True)
                    self.files[layer].write_bytes(data)
                tool, check = self.both()
                settings = self.agree(tool, check)
                if case.error is None:
                    self.assertIsNotNone(settings, (tool.stderr, check.stderr))
                    found = {key: (entry["value"], entry["layer"]) for key, entry in settings.items()}
                    self.assertEqual(found, case.expect)
                    layer_files = {**{layer: str(file) for layer, file in self.files.items()},
                                   "shipped": str(support.DEFAULTS)}
                    for entry in settings.values():
                        self.assertEqual(entry["file"], layer_files[entry["layer"]])
                else:
                    self.assertIsNone(settings, "both were expected to refuse")
                    for stderr in (tool.stderr.decode("utf-8"), check.stderr.decode("utf-8")):
                        self.assertIn(str(self.files[case.error]), stderr)  # the file is named
                        for name in case.names:  # and the key, with the fault
                            self.assertIn(name, stderr)

    def test_a_validation_error_is_worded_as_the_tool_words_it(self) -> None:
        for case in TABLE:
            if case.error is None or any("newer than" in name for name in case.names):
                continue  # each names itself there: "this tool", "this command"
            with self.subTest(case.name):
                for file in self.files.values():
                    file.unlink(missing_ok=True)
                for layer, content in case.files.items():
                    self.files[layer].parent.mkdir(exist_ok=True)
                    self.files[layer].write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
                tool, check = self.both()
                first = tool.stderr.decode("utf-8").splitlines()[0]
                self.assertTrue(check.stderr.decode("utf-8").startswith(first), (first, check.stderr))

    def test_a_tilde_in_project_and_in_home(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "from-the-project"\n')
        self.write(self.user_file, '[process]\nquestions = "all-together"\n')
        expected = self.agree(*self.both())
        self.assertEqual(expected["process.docs_dir"]["layer"], "project")
        self.assertEqual(expected["process.questions"]["layer"], "user")
        for places in ({"project": "~/project"}, {"home": "~/home"}, {"project": "~/project", "home": "~/home"},
                       {"project": "~"}, {"home": "~"}):
            with self.subTest(places):
                settings = self.agree(*self.both(**places))
                self.assertIsNotNone(settings)
                if "~" not in places.values():
                    self.assertEqual(settings, expected)
        # ``~`` alone is the scratch root, which has no settings: the shipped values.
        alone = self.agree(*self.both(project="~", home="~"))
        self.assertEqual({entry["layer"] for entry in alone.values()}, {"shipped"})
        for places in ({"project": "~/none"}, {"home": "~/none"}, {"project": "~no-such-user-here/project"}):
            with self.subTest(places):
                self.assertIsNone(self.agree(*self.both(**places)))

    def test_places_that_are_refused(self) -> None:
        a_file = str(self.write(self.root / "a-file", "x\n"))
        for places in ({"project": ""}, {"home": ""}, {"project": "  "}, {"home": " "},
                       {"project": str(self.root / "none")}, {"home": str(self.root / "none")},
                       {"project": a_file}, {"home": a_file}):
            with self.subTest(places):
                tool, check = self.both(**places)
                self.assertIsNone(self.agree(tool, check))
                option = "--project" if "project" in places else "--home"
                for stderr in (tool.stderr, check.stderr):
                    self.assertTrue(stderr.decode("utf-8").startswith(f"error: {option}: "), stderr)
                self.assertEqual(tool.stderr, check.stderr)

    def test_a_settings_directory_that_is_not_one(self) -> None:
        for directory in (self.user_file.parent, self.project_file.parent):
            with self.subTest(directory):
                self.write(directory, "a file\n")
                tool, check = self.both()
                self.assertIsNone(self.agree(tool, check))
                self.assertEqual(tool.stderr, check.stderr)
                directory.unlink()
        self.project_file.mkdir(parents=True)
        tool, check = self.both()
        self.assertIsNone(self.agree(tool, check))
        self.assertEqual(tool.stderr, check.stderr)

    def test_a_link_with_no_target(self) -> None:
        self.project_file.parent.mkdir()
        try:
            os.symlink(self.root / "gone.toml", self.project_file)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are not permitted here: {exc}")
        tool, check = self.both()
        self.assertIsNone(self.agree(tool, check))
        self.assertEqual(tool.stderr, check.stderr)

    @unittest.skipUnless(support.can_lock_directories(), "permissions do not keep this process out")
    def test_places_that_cannot_be_read(self) -> None:
        self.write(self.project_file, '[process]\ndocs_dir = "p"\n')
        self.user_file.parent.mkdir()
        for locked in (self.home, self.user_file.parent, self.project_file.parent, self.project_file):
            with self.subTest(locked):
                os.chmod(locked, 0)
                try:
                    tool, check = self.both()
                finally:
                    os.chmod(locked, 0o700)
                self.assertIsNone(self.agree(tool, check))
                self.assertEqual(tool.stderr, check.stderr)
                self.assertIn(b"cannot be read: Permission denied", check.stderr)


class TheSameSchema(unittest.TestCase):
    """What ``check.py`` holds of the schema, against the schema itself."""

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(CHECK_PY.parent))
        try:
            import check
        finally:
            sys.path.remove(str(CHECK_PY.parent))
        cls.check = check

    def test_the_version_and_the_top_level_keys(self) -> None:
        self.assertEqual(self.check.SETTINGS_SCHEMA_VERSION, schema.SCHEMA_VERSION)
        self.assertEqual(self.check.VERSION_KEY, schema.VERSION_KEY)
        self.assertEqual(self.check.SETTINGS_GROUPS, schema.GROUPS)

    def test_the_process_group(self) -> None:
        group = schema.SCHEMA[self.check.GROUP]
        self.assertIsNone(group.each)  # fixed keys only: check.py knows no named entries
        self.assertEqual(list(self.check.PROCESS_KEYS), list(group.keys))
        for key, node in group.keys.items():
            with self.subTest(key):
                self.assertIsInstance(node, schema.Value)
                self.assertIsNone(node.minimum)  # check.py knows no least value
                self.assertEqual(self.check.PROCESS_KEYS[key], (node.type, tuple(node.choices)))

    def test_the_built_in_defaults_are_the_shipped_ones(self) -> None:
        import tomllib
        shipped = tomllib.loads(support.DEFAULTS.read_text(encoding="utf-8"))
        self.assertEqual(self.check.BUILT_IN, {f"process.{key}": value for key, value in shipped["process"].items()})

    def test_check_py_does_not_import_the_tool(self) -> None:
        source = CHECK_PY.read_text(encoding="utf-8")
        for word in ("wfsetup", "workflow_setup import", "import subprocess", "import os"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
