"""Argument parsing, and the one place errors are printed.

No fault of the input ends in a traceback. A ``SetupError`` is printed as
it is, one ``error:`` line per problem; anything the system refused that no
module turned into one (``OSError``) is printed by the backstop in ``main``
as ``error: <file>: <reason>``. Both exit with ``EXIT_ERROR``.

An interrupt (Ctrl-C) ends every command with one line and
``EXIT_INTERRUPT`` (130), never a traceback, from the first statement of
the script on. One that arrives earlier, while Python itself is starting,
is Python's to report: no code of the tool runs yet. A real process
(``run_from_command_line``) takes SIGTERM and SIGHUP, and Ctrl-Break on
Windows, the same way, and exits with 128 plus the signal's number: the
run stops where it is, the lock is given back, and what a run that writes
had under way is settled from the disk by the next one (``fileops``). A
kill that cannot be caught (SIGKILL, the power) leaves the same on disk,
and the lock besides.

Options are never abbreviated (``allow_abbrev=False`` on every parser): an
abbreviation that is unique today turns ambiguous when a command gains an
option, and a caller's script would break with it.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
from types import FrameType, ModuleType
from typing import Callable

from . import commands, fsio, paths
from .errors import EXIT_ERROR, EXIT_INTERRUPT, EXIT_PIPE, SetupError

PROG = "workflow_setup.py"
DESCRIPTION = "Set up and inspect the workflow: settings, skills, roles and rules."


def _add(subparsers: argparse._SubParsersAction, name: str, module: ModuleType) -> None:
    sub = subparsers.add_parser(
        name,
        help=str(getattr(module, "SUMMARY", "")).replace("%", "%%"),
        description=module.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    configure = getattr(module, "configure", None)
    if configure is not None:
        configure(sub)
    sub.set_defaults(run=module.run)


def _refuse(name: str, why: str) -> Callable[[argparse.Namespace], int]:
    def run(args: argparse.Namespace) -> int:
        raise SetupError(f"command {name}: unavailable: {why}")
    return run


def build_parser(argv: list[str]) -> argparse.ArgumentParser:
    """The parser for ``argv``.

    When ``argv`` starts with a command's name, that command's module is the
    only one imported, so a fault in another command's module cannot get in
    the way. Otherwise (``--help``, no command, a name that is not one)
    every candidate is imported for the list, each on its own: one that
    fails is listed as unavailable.
    """
    parser = argparse.ArgumentParser(prog=PROG, description=DESCRIPTION, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    if argv and argv[0] in commands.names():
        name = argv[0]
        module = commands.load(name)
        if module is not None:
            try:
                _add(subparsers, name, module)
            except Exception as exc:  # the module's own ``configure``
                raise SetupError(f"command {name}: unavailable: {commands.reason(exc)}") from None
            return parser
    found, unavailable = commands.survey()
    for name in commands.names():
        if name in found:
            try:
                # Tried on a parser of its own first: a subparser cannot be
                # taken back once it is added.
                configure = getattr(found[name], "configure", None)
                if configure is not None:
                    configure(argparse.ArgumentParser(allow_abbrev=False))
                _add(subparsers, name, found[name])
                continue
            except Exception as exc:
                unavailable[name] = commands.reason(exc)
        if name in unavailable:
            why = unavailable[name]
            stub = subparsers.add_parser(
                name, help=f"unavailable: {why}".replace("%", "%%"), add_help=False, allow_abbrev=False
            )
            stub.set_defaults(run=_refuse(name, why))
    return parser


def _complain(*lines: str) -> None:
    """Print error lines to stderr; a stderr that cannot be written to is
    not a second error."""
    try:
        for line in lines:
            print(f"error: {line}", file=sys.stderr)
        if sys.stderr is not None:
            sys.stderr.flush()
    except (OSError, ValueError):
        pass


class Signalled(KeyboardInterrupt):
    """The process was told to end by a signal other than the interrupt.
    It is an interrupt to everything that handles one."""

    def __init__(self, number: int) -> None:
        super().__init__(number)
        self.number = number


INTERRUPTED = (
    "interrupted{by}: the run was stopped before it ended. If it was writing, what it had changed is recorded "
    "or is settled from the disk by the next run that writes; nothing is left half written"
)


def _interrupted(exc: BaseException) -> int:
    """Say that the run was interrupted, in one line, and give its exit code."""
    number = exc.number if isinstance(exc, Signalled) else None
    by = ""
    if number is not None:
        try:
            by = f" by {signal.Signals(number).name}"
        except ValueError:
            by = f" by signal {number}"
    _complain(INTERRUPTED.format(by=by))
    return EXIT_INTERRUPT if number is None else 128 + number


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code.

    A ``SetupError`` is printed to stderr, one ``error:`` line per problem,
    and gives ``EXIT_ERROR``. A usage error leaves through ``argparse``,
    with the same code. An ``OSError`` that no module handled is printed as
    ``error: <file>: <reason>``, with the same code again. An interrupt is
    one line and ``EXIT_INTERRUPT``. A broken pipe is left to the caller
    (``run_from_command_line``).
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        args = build_parser(argv).parse_args(argv)
        return args.run(args)
    except KeyboardInterrupt as exc:
        return _interrupted(exc)
    except SetupError as exc:
        _complain(*exc.lines)
    except BrokenPipeError:
        raise
    except OSError as exc:
        why = paths.reason(exc)
        _complain(why if exc.filename is None else f"{exc.filename}: {why}")
    except RecursionError:
        _complain("the input is nested too deeply to read")
    except UnicodeError as exc:
        # Text that is no text (half of a surrogate pair from a settings
        # file) reached a place that writes it.
        _complain(f"text that cannot be written as UTF-8 was read from a file: {' '.join(str(exc).split())[:200]}")
    return EXIT_ERROR


def _discard_stdout() -> None:
    """Point stdout at the null device, after a write to it failed: the
    interpreter flushes stdout once more as it exits, and would then report
    the same failure again, with an exit code of its own."""
    try:
        os.dup2(fsio.null_output(), sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        pass


def _flush_stderr() -> None:
    """Flush stderr here, where a failure is not a second error: left to
    the interpreter's exit, it would be reported ("Exception ignored") and
    change the exit code."""
    try:
        if sys.stderr is not None:
            sys.stderr.flush()
    except (OSError, ValueError):
        try:
            os.dup2(fsio.null_output(), sys.stderr.fileno())
        except (OSError, ValueError, AttributeError):
            pass


def _take_signals() -> None:
    """Let the signals that ask a process to end do so as an interrupt
    does: an exception in the main thread, so that every ``finally`` runs.
    Where a signal does not exist, or cannot be taken (not the main
    thread), it keeps what the system does with it."""
    def stop(number: int, frame: FrameType | None) -> None:
        raise Signalled(number)

    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            if signal.getsignal(number) is signal.SIG_IGN:
                continue  # ignored on purpose by whoever started this (nohup)
            signal.signal(number, stop)
        except (OSError, ValueError, RuntimeError):
            pass


def run_from_command_line() -> int:
    """``main`` for a real process.

    Output is UTF-8 with LF on every platform, whatever the console's own
    encoding is. Stdout is flushed here, inside the entry point, so that a
    failed write decides the exit code: a caller must never take an empty
    or cut-off output for success. A write that fails (a full device, a
    closed stdout) gives ``EXIT_ERROR`` and a line on stderr; a reader that
    went away (a broken pipe) gives ``EXIT_PIPE`` and no line.
    """
    for stream in (sys.stderr, sys.stdout):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", newline="\n")
        except (OSError, ValueError):
            pass  # a stream that cannot be set up fails at its first write
    if sys.stdout is None or sys.stdout.closed:
        _complain("the output cannot be written: standard output is closed")
        return EXIT_ERROR
    try:
        _take_signals()
        try:
            code = main()
        except SystemExit as exc:
            # ``argparse`` leaves this way: ``--help`` (0) and a usage
            # error (2). What it printed is flushed here like any output.
            code = exc.code if isinstance(exc.code, int) else 0 if exc.code is None else EXIT_ERROR
        sys.stdout.flush()
        return code
    except KeyboardInterrupt as exc:  # outside ``main``: while the output was flushed
        _discard_stdout()
        return _interrupted(exc)
    except BrokenPipeError:
        _discard_stdout()
        return EXIT_PIPE
    except OSError as exc:
        _discard_stdout()
        _complain(f"the output cannot be written: {paths.reason(exc)}")
        return EXIT_ERROR
    finally:
        _flush_stderr()
