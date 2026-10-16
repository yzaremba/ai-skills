"""A provider's program, replaced by a stub that prints what a test says.

No test starts a real provider (R6.8). A test that needs one builds a
``StubProgram`` in its scratch directory and points ``PATH`` at
``stub.bin``; the code under test then finds the program on ``PATH`` and
starts it, exactly as it finds and starts the real one.

The program is a launcher named as the provider's (``codex``; on Windows
``codex.cmd``) that starts ``stub.py`` beside it with this interpreter. The
stub reads ``answers.json``, picks the answer of its mode (``version`` when
``--version`` is among its arguments, ``bundled`` when ``--bundled`` is,
else ``live``), appends its arguments
to ``calls.jsonl``, then sleeps, prints and exits as the answer says.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import support

LIVE = "live"
BUNDLED = "bundled"
VERSION = "version"  # the answer when ``--version`` is among the arguments

# A variable the stub reports back, to show whose environment it was given.
MARK = "WFSETUP_TEST_MARK"

_STUB = r'''import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "answers.json"), encoding="utf-8") as handle:
    answers = json.load(handle)
arguments = sys.argv[1:]
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": arguments, "mark": os.environ.get("WFSETUP_TEST_MARK")}) + "\n")
answer = answers["version" if "--version" in arguments else "bundled" if "--bundled" in arguments else "live"]
time.sleep(answer["sleep"])
sys.stdout.buffer.write(answer["stdout"].encode("utf-8"))
sys.stdout.flush()
sys.stderr.write(answer["stderr"])
sys.exit(answer["code"])
'''


def fixture(name: str) -> str:
    """The text of a saved list in ``fixtures/``."""
    return (support.FIXTURES / name).read_text(encoding="utf-8")


class StubProgram:
    def __init__(self, directory: Path, name: str = "codex") -> None:
        self.directory = directory
        self.bin = directory / "bin"
        self.bin.mkdir(parents=True)
        self.script = self.bin / "stub.py"
        self.script.write_text(_STUB, encoding="utf-8", newline="\n")
        self._answers = {
            mode: {"stdout": "", "stderr": "", "code": 0, "sleep": 0} for mode in (LIVE, BUNDLED, VERSION)
        }
        self._save()
        if os.name == "nt":
            self.program = self.bin / f"{name}.cmd"
            self.program.write_text(
                f'@"{sys.executable}" -B "{self.script}" %*\r\n', encoding="utf-8", newline=""
            )
        else:
            self.program = self.bin / name
            self.program.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" -B "{self.script}" "$@"\n', encoding="utf-8", newline="\n"
            )
            os.chmod(self.program, 0o755)

    def _save(self) -> None:
        (self.bin / "answers.json").write_text(json.dumps(self._answers), encoding="utf-8")

    def answer(self, mode: str, stdout: str = "", *, code: int = 0, stderr: str = "", sleep: float = 0) -> None:
        """What the stub does when started in ``mode``."""
        self._answers[mode] = {"stdout": stdout, "stderr": stderr, "code": code, "sleep": sleep}
        self._save()

    def calls(self) -> list[list[str]]:
        """The argument list of every start, in order."""
        return [call["argv"] for call in self._calls()]

    def marks(self) -> list[str | None]:
        return [call["mark"] for call in self._calls()]

    def _calls(self) -> list[dict]:
        log = self.bin / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def environ(self, **more: str) -> dict[str, str]:
        """This process's environment with ``PATH`` holding the stub's
        directory and nothing else."""
        return {**os.environ, "PATH": str(self.bin), **more}
