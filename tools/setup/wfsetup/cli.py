"""Argument parsing, and the one place errors are printed.

No fault of the input ends in a traceback. A ``SetupError`` is printed as
it is, one ``error:`` line per problem; anything the system refused that no
module turned into one (``OSError``) is printed by the backstop in ``main``
as ``error: <file>: <reason>``. Both exit with ``EXIT_ERROR``.

Options are never abbreviated (``allow_abbrev=False`` on every parser): an
abbreviation that is unique today turns ambiguous when a command gains an
option, and a caller's script would break with it.
"""
from __future__ import annotations

import argparse
import os
import sys
from types import ModuleType
from typing import Callable

from . import commands, paths
from .errors import EXIT_ERROR, EXIT_PIPE, SetupError

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


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code.

    A ``SetupError`` is printed to stderr, one ``error:`` line per problem,
    and gives ``EXIT_ERROR``. A usage error leaves through ``argparse``,
    with the same code. An ``OSError`` that no module handled is printed as
    ``error: <file>: <reason>``, with the same code again. A broken pipe is
    left to the caller (``run_from_command_line``).
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        args = build_parser(argv).parse_args(argv)
        return args.run(args)
    except SetupError as exc:
        _complain(*exc.lines)
    except BrokenPipeError:
        raise
    except OSError as exc:
        why = paths.reason(exc)
        _complain(why if exc.filename is None else f"{exc.filename}: {why}")
    except RecursionError:
        _complain("the input is nested too deeply to read")
    return EXIT_ERROR


def _discard_stdout() -> None:
    """Point stdout at the null device, after a write to it failed: the
    interpreter flushes stdout once more as it exits, and would then report
    the same failure again, with an exit code of its own."""
    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
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
        code = main()
        sys.stdout.flush()
        return code
    except BrokenPipeError:
        _discard_stdout()
        return EXIT_PIPE
    except OSError as exc:
        _discard_stdout()
        _complain(f"the output cannot be written: {paths.reason(exc)}")
        return EXIT_ERROR
