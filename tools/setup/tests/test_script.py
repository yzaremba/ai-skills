"""``workflow_setup.py`` itself: an interrupt or a signal is one line and an
exit code from its first statement on, and a reader that went away is not
a second error.

Run from the repository root:
    python -B -m unittest discover -s tools/setup/tests
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support


class StartUpTests(unittest.TestCase):
    """The script beside a stand-in package whose ``cli`` module is
    interrupted while it is being loaded."""

    def script(self, body: str) -> Path:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        shutil.copy(support.SCRIPT, root / "workflow_setup.py")
        (root / "wfsetup").mkdir()
        (root / "wfsetup" / "__init__.py").write_text("", encoding="utf-8")
        (root / "wfsetup" / "cli.py").write_text(body, encoding="utf-8")
        return root / "workflow_setup.py"

    def run_script(self, body: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(self.script(body)), "validate"], stdin=subprocess.DEVNULL, capture_output=True,
            timeout=60,
        )

    def check(self, done: subprocess.CompletedProcess, code: int) -> None:
        said = done.stderr.decode("utf-8", "replace")
        self.assertEqual(done.returncode, code, said)
        self.assertNotIn("Traceback", said)
        self.assertEqual(len(said.strip().splitlines()), 1, said)
        self.assertTrue(said.startswith("error: interrupted"), said)
        self.assertEqual(done.stdout, b"")

    def test_an_interrupt_while_the_package_is_loaded(self) -> None:
        self.check(self.run_script("raise KeyboardInterrupt()\n"), 130)

    @unittest.skipUnless(hasattr(signal, "SIGTERM") and os.name == "posix", "needs a signal a process can send itself")
    def test_a_signal_while_the_package_is_loaded(self) -> None:
        body = "import os, signal, time\nos.kill(os.getpid(), signal.SIG)\ntime.sleep(5)\n"
        self.check(self.run_script(body.replace("SIG", "SIGTERM")), 128 + signal.SIGTERM)
        self.check(self.run_script(body.replace("SIG", "SIGHUP")), 128 + signal.SIGHUP)

    @unittest.skipUnless(os.name == "posix", "needs a signal a process can send itself")
    def test_a_signal_while_the_interpreter_shuts_down_does_not_change_the_code(self) -> None:
        body = (
            "import atexit, os, signal\n"
            "def run_from_command_line():\n"
            "    atexit.register(lambda: os.kill(os.getpid(), signal.SIGINT))\n"
            "    return 3\n"
        )
        done = self.run_script(body)
        self.assertEqual(done.returncode, 3, done.stderr.decode("utf-8", "replace"))
        self.assertEqual(done.stderr, b"")

    def test_nothing_is_imported_before_interrupts_are_taken_care_of(self) -> None:
        import ast

        tree = ast.parse(support.SCRIPT.read_text(encoding="utf-8"))
        top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = sorted(alias.name for node in top for alias in getattr(node, "names", []))
        self.assertEqual(names, ["annotations", "sys"])


class OutputTests(support.ScratchCase):
    """A reader of the output that went away."""

    def run_tool(self, *args: str, stdout) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(support.SCRIPT), *args], stdin=subprocess.DEVNULL, stdout=stdout,
            stderr=subprocess.PIPE, env=support.child_environment(), timeout=120,
        )

    def test_help_into_a_closed_pipe_is_not_a_second_error(self) -> None:
        for args in (("--help",), ("render", "--help"), ("uninstall", "--help"), ("homes", "--home", str(self.home))):
            with self.subTest(args=args):
                reader, writer = os.pipe()
                os.close(reader)
                try:
                    done = self.run_tool(*args, stdout=writer)
                finally:
                    os.close(writer)
                said = done.stderr.decode("utf-8", "replace")
                # Windows reports a reader that went away as a write that
                # failed ("Invalid argument"): one line, and the error code.
                self.assertIn(done.returncode, (0, 141) if os.name == "posix" else (0, 2, 141), said)
                self.assertLessEqual(len(said.strip().splitlines()), 1, said)
                self.assertNotIn("Exception ignored", said)
                self.assertNotIn("Traceback", said)

    @unittest.skipUnless(os.path.exists("/dev/full"), "needs a device that is full")
    def test_a_full_device_is_not_reported_twice(self) -> None:
        for args in (("--help",), ("render", "--help"), ("homes", "--home", str(self.home))):
            with self.subTest(args=args):
                with open("/dev/full", "wb") as full:
                    done = self.run_tool(*args, stdout=full)
                said = done.stderr.decode("utf-8", "replace")
                self.assertIn(done.returncode, (0, 2), said)
                self.assertNotIn("Exception ignored", said)
                self.assertNotIn("Traceback", said)
                self.assertLessEqual(len(said.strip().splitlines()), 1, said)


if __name__ == "__main__":
    unittest.main()
