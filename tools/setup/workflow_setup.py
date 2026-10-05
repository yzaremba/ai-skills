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
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.stderr.write("error: workflow_setup.py needs Python 3.11 or later\n")
    sys.exit(2)

# No bytecode is written. The tool runs from the shared clone, and the clone
# is changed only by `git pull`: a run must not leave `__pycache__`
# directories in it, least of all from two systems that read the same files.
# Set before the package is imported, because importing is what writes them.
sys.dont_write_bytecode = True

# The package is found from this file's real location, so a link to the
# script, or a working directory elsewhere, changes nothing.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from wfsetup.cli import run_from_command_line  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_from_command_line())
