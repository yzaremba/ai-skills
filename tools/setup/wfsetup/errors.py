"""The error a user can act on."""
from __future__ import annotations

# The exit code of a run that could not do what was asked.
EXIT_ERROR = 2

# The exit code when the reader of the output went away before it was all
# written (``show | head -1``): what a shell reports for a program ended by
# SIGPIPE, 128 + 13. Nothing is printed; there is no one left to read it.
EXIT_PIPE = 141


class SetupError(Exception):
    """A problem with the input: a settings file, an argument, a path.

    It holds one line per problem. The command line prints each to stderr
    and exits with ``EXIT_ERROR``; no traceback is shown.
    """

    def __init__(self, *lines: str) -> None:
        super().__init__("\n".join(lines))
        self.lines = list(lines)
