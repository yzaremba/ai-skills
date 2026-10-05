"""Tests for command discovery: a command is a module, found by its name.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support
from wfsetup import commands
from wfsetup.errors import SetupError

DUMMY = '''"""Say hello: the help text of a command made for a test."""
SUMMARY = "say hello"


def configure(parser):
    parser.add_argument("name")


def run(args):
    print(f"hello {args.name}")
    return 7
'''

BARE = '''def run(args):
    print("bare")
    return 0
'''


class DiscoveryCase(support.ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.extra = Path(scratch.name)
        # A second directory on the package's path stands in for a file
        # added to wfsetup/commands/. Modules imported from it are forgotten
        # again when the test ends.
        patch = mock.patch.object(commands, "__path__", [*commands.__path__, str(self.extra)])
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.forget)
        importlib.invalidate_caches()

    def forget(self) -> None:
        for name in list(sys.modules):
            module = sys.modules[name]
            if name.startswith("wfsetup.commands.") and str(self.extra) in str(getattr(module, "__file__", "")):
                del sys.modules[name]
                vars(commands).pop(name.rsplit(".", 1)[1], None)

    def add(self, name: str, text: str = DUMMY) -> None:
        file = self.extra / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        importlib.invalidate_caches()

    def imported(self) -> set[str]:
        return {name.rsplit(".", 1)[1] for name in sys.modules if name.startswith("wfsetup.commands.")}


class DiscoveryTests(DiscoveryCase):
    def test_show_is_a_shipped_command(self) -> None:
        self.assertIn("show", commands.discover())
        self.assertIn("show", commands.names())

    def test_every_shipped_command_is_a_file_in_the_commands_directory(self) -> None:
        directory = support.SETUP / "wfsetup" / "commands"
        files = {p.stem.replace("_", "-") for p in directory.glob("*.py") if not p.name.startswith("_")}
        self.assertIn("show", files)
        self.assertLessEqual(set(commands.discover()), files)

    def test_a_module_added_to_the_package_is_a_command(self) -> None:
        self.add("say_hello.py")
        found = list(commands.discover())
        self.assertIn("say-hello", found)
        self.assertIn("show", found)
        self.assertEqual(found, sorted(found))
        self.assertEqual(support.run("say-hello", "there"), (7, "hello there\n", ""))

    def test_a_new_command_is_listed_in_the_help(self) -> None:
        self.add("say_hello.py")
        code, out, _ = support.run("--help")
        self.assertEqual(code, 0)
        self.assertIn("say-hello", out)
        self.assertIn("say hello", out)
        self.assertIn("show", out)
        own = support.run("say-hello", "--help")[1]
        self.assertIn("the help text of a command made for a test", own)

    def test_a_command_needs_only_run(self) -> None:
        self.add("bare.py", BARE)
        self.assertEqual(support.run("bare"), (0, "bare\n", ""))
        self.assertIn("bare", support.run("--help")[1])

    def test_names_imports_nothing(self) -> None:
        self.add("say_hello.py")
        self.add("broken.py", "import no_such_module_anywhere\n")
        before = set(sys.modules)
        self.assertLessEqual({"say-hello", "broken", "show"}, set(commands.names()))
        self.assertEqual(set(sys.modules), before)

    def test_only_the_command_named_is_imported(self) -> None:
        self.add("say_hello.py")
        self.add("other.py", DUMMY)
        self.assertEqual(support.run("say-hello", "you")[0], 7)
        self.assertIn("say_hello", self.imported())
        self.assertNotIn("other", self.imported())


class HelperTests(DiscoveryCase):
    """What is under commands/ and is not a command breaks nothing."""

    def test_a_module_with_a_leading_underscore_is_not_a_command(self) -> None:
        self.add("_helper.py", "raise RuntimeError('never imported')\n")
        self.assertNotIn("-helper", commands.names())
        self.assertNotIn("_helper", commands.names())
        self.assertEqual(support.run("--help")[0], 0)
        self.assertNotIn("_helper", self.imported())

    def test_a_module_without_run_is_a_helper_and_not_a_command(self) -> None:
        self.add("half_done.py", 'SUMMARY = "nothing else"\nVALUE = 1\n')
        self.assertNotIn("half-done", commands.discover())
        self.assertIsNone(commands.load("half-done"))
        self.assertEqual(self.show("process")[0], 0)
        code, out, _ = support.run("--help")
        self.assertEqual(code, 0)
        self.assertNotIn("half-done", out)
        code, out, err = support.run("half-done")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("invalid choice", err)
        self.assertNotIn("Traceback", err)

    def test_a_subpackage_is_not_a_command(self) -> None:
        self.add("toolkit/__init__.py", "raise RuntimeError('never imported')\n")
        self.add("toolkit/inner.py", DUMMY)
        self.assertNotIn("toolkit", commands.names())
        self.assertEqual(self.show("process")[0], 0)
        self.assertEqual(support.run("--help")[0], 0)
        self.assertEqual(support.run("toolkit")[0], 2)


class FaultyModuleTests(DiscoveryCase):
    """One faulty command module does not take the others down."""

    FAULTS = {
        "an import that fails": ("import no_such_module_anywhere\n" + DUMMY, "ModuleNotFoundError"),
        "a syntax error": ("def run(:\n", "SyntaxError"),
        "an error at import": ("raise RuntimeError('boom at import')\n" + DUMMY, "RuntimeError: boom at import"),
        "a configure that raises": (DUMMY.replace('parser.add_argument("name")', "raise KeyError('bad configure')"), "KeyError"),
    }

    def test_the_other_commands_still_run(self) -> None:
        for name, (text, _) in self.FAULTS.items():
            with self.subTest(name):
                self.add("broken.py", text)
                self.assertEqual(self.show("process.recommend"), (0, "process.recommend = true  (shipped)\n", ""))
                self.assertIn("show", commands.discover())
                self.forget()

    def test_it_is_listed_as_unavailable_with_the_reason(self) -> None:
        for name, (text, reason) in self.FAULTS.items():
            with self.subTest(name):
                self.add("broken.py", text)
                code, out, err = support.run("--help")
                self.assertEqual((code, err), (0, ""))
                flat = " ".join(out.split())
                self.assertIn("broken unavailable: ", flat)
                self.assertIn(reason, flat)
                self.assertIn("show", flat)
                self.forget()

    def test_asked_for_it_fails_with_one_line(self) -> None:
        for name, (text, reason) in self.FAULTS.items():
            with self.subTest(name):
                self.add("broken.py", text)
                code, out, err = support.run("broken", "x")
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("error: command broken: unavailable: "), err)
                self.assertIn(reason, err)
                self.assertEqual(err.count("\n"), 1)
                self.forget()

    def test_survey_tells_commands_from_unavailable_modules(self) -> None:
        self.add("broken.py", "import no_such_module_anywhere\n")
        self.add("say_hello.py")
        found, unavailable = commands.survey()
        self.assertIn("say-hello", found)
        self.assertNotIn("broken", found)
        self.assertIn("ModuleNotFoundError", unavailable["broken"])
        with self.assertRaises(SetupError):
            commands.load("broken")
        with self.assertRaises(SetupError):
            commands.load("no-such-command")

    def test_a_percent_sign_in_a_summary_or_a_reason_is_plain_text(self) -> None:
        self.add("broken.py", "raise RuntimeError('100% wrong')\n")
        self.add("say_hello.py", DUMMY.replace('"say hello"', '"say 50% hello"'))
        code, out, _ = support.run("--help")
        self.assertEqual(code, 0)
        self.assertIn("100% wrong", out)
        self.assertIn("say 50% hello", out)


class AbbreviationTests(DiscoveryCase):
    def test_an_option_is_never_abbreviated(self) -> None:
        self.assertEqual(self.show("process", "--json")[0], 0)
        for short in ("--js", "--jso"):
            with self.subTest(short):
                code, out, err = self.show("process", short)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("unrecognized arguments", err)
        code, _, err = support.run("show", "process", "--hom", str(self.home))
        self.assertEqual(code, 2)
        self.assertIn("unrecognized arguments", err)
        code, _, err = support.run("show", "--proj", str(self.project), "--home", str(self.home))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
