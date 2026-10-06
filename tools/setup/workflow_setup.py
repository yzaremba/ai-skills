#!/usr/bin/env python3
"""Set up and inspect the workflow: settings, and later the installed files.

Usage:
    python tools/setup/workflow_setup.py <command> [options]
    python tools/setup/workflow_setup.py --help

It can be run by path from any directory. The code is in the package
``wfsetup`` beside this file; each command is one module under
``wfsetup/commands``.

Standard library only, Python 3.11 or later, the same code on Linux and
Windows.

An interrupt (Ctrl-C) or a signal that asks the process to end is one line
and an exit code (130, or 128 plus the signal's number) from the first
statement of this file to the last: also while the modules are still being
loaded, and while the interpreter shuts down. Nothing in this file is
imported before that is arranged, and everything else is imported inside
``main``. Before the first statement of this file Python is still starting
and none of this is in force: an interrupt in that instant is reported by
Python itself, and the tool has changed nothing by then.
"""
from __future__ import annotations

import sys


class _Stopped(KeyboardInterrupt):
    """Told to end by a signal while the package was still being loaded."""

    def __init__(self, number: int) -> None:
        super().__init__(number)
        self.number = number


def _stop(number: int, frame: object) -> None:
    raise _Stopped(number)


def _interrupted(exc: BaseException) -> int:
    """One line and the exit code of an interrupt: 130, or 128 plus the
    signal's number. Nothing was read or written yet."""
    number = getattr(exc, "number", None)
    try:
        sys.stderr.write("error: interrupted: the run was stopped before it started; nothing was changed\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    return 130 if not isinstance(number, int) else 128 + number


def main() -> int:
    """Run one command; see ``wfsetup.cli``."""
    if sys.version_info < (3, 11):
        sys.stderr.write("error: workflow_setup.py needs Python 3.11 or later\n")
        return 2
    # No bytecode is written. The tool runs from the shared clone, and the
    # clone is changed only by `git pull`: a run must not leave `__pycache__`
    # directories in it, least of all from two systems that read the same
    # files. Set before the package is imported, because importing is what
    # writes them.
    sys.dont_write_bytecode = True
    try:
        import signal

        # From here on a signal that asks the process to end is an
        # interrupt, not a silent death; the package takes the same signals
        # over once it is loaded.
        for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
            number = getattr(signal, name, None)
            if number is None:
                continue
            try:
                if signal.getsignal(number) is not signal.SIG_IGN:
                    signal.signal(number, _stop)
            except (OSError, ValueError, RuntimeError):
                pass
        from pathlib import Path

        # The package is found from this file's real location, so a link to
        # the script, or a working directory elsewhere, changes nothing.
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        from wfsetup.cli import run_from_command_line
    except KeyboardInterrupt as exc:
        return _interrupted(exc)
    return run_from_command_line()


def _leave(code: int) -> None:
    """End with ``code``. The run is over and its output is written: a
    signal that arrives while the interpreter shuts down must not turn that
    into a death by signal with no word."""
    try:
        import signal

        for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"):
            number = getattr(signal, name, None)
            if number is not None:
                try:
                    signal.signal(number, signal.SIG_IGN)
                except (OSError, ValueError, RuntimeError):
                    pass
    except KeyboardInterrupt:
        pass
    sys.exit(code)


if __name__ == "__main__":
    try:
        _code = main()
    except KeyboardInterrupt as _exc:
        _code = _interrupted(_exc)
    try:
        _leave(_code)
    except KeyboardInterrupt:
        sys.exit(_code)
