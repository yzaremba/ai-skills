#!/usr/bin/env python3
"""Print the settings a skill or a role reads.

Usage:
    python scripts/settings.py [KEY] [--project DIR] [--home DIR] [--json]

KEY is ``process``, ``memory`` or ``roles``, or a dotted key in one of
them, such as ``process.docs_dir`` or ``roles.max_parallel_coders``. Without
KEY the process and memory groups are printed: ``roles`` is printed only
when it is asked for, so a fault in it stops no skill that does not read
it. Any other group is refused. Nothing is ever written.

--project DIR names the project whose settings files are read
(DIR/.agents/workflow.toml and DIR/.agents/workflow.local.toml). The
project is only ever that directory; it is not taken from the working
directory. Without it only the shipped and the user's settings are read.
--home DIR stands in for the user's home directory. A DIR that is empty or
is not a directory is refused, here as by the setup tool; an empty one is
never taken to mean "not given". Options are written in full: an
abbreviation is refused.

Text output is one line per value:

    process.docs_dir = "docs"  (shipped)

With --json the output is one object: "schema_version", and "settings",
which maps each dotted key to its "value", "layer" and "file". For the
whole ``roles`` group the text is what the setup tool prints for it, the
resolved profiles included; a role asks for the one key it reads.

The values come from the setup tool of the clone this skill belongs to
(tools/setup/workflow_setup.py show). The clone is found from this file's
own resolved path, so a skill reached through a symlink or a Windows
junction still finds it. A skill copied on its own has no setup tool: the
built-in defaults below are printed, with the layer "built-in" and no
file, a note on stderr says so, and no settings file is read; --project
and --home are still checked to name a directory.

Exit code 0, or 2 on an error, which is printed to stderr.

Standard library only; the same code on Linux and Windows. This file is
kept byte-identical in every skill that carries it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

GROUPS = ("process", "memory", "roles")
# What is printed without KEY.
DEFAULT_GROUPS = ("process", "memory")

# A copy of these groups of tools/setup/defaults.toml, for a skill that
# was copied without the clone. The two must stay equal.
SCHEMA_VERSION = 1
BUILT_IN = {
    "process.docs_dir": "docs",
    "process.questions": "all-together",
    "process.recommend": True,
    "memory.dir": "docs/memory",
    "roles.enabled": True,
    "roles.manager_default": False,
    "roles.high_stakes": False,
    "roles.max_parallel_coders": 3,
}
BUILT_IN_LAYER = "built-in"

EXIT_ERROR = 2

# This file is <clone>/<skill>/scripts/settings.py. The path is made real
# before the clone is taken from it: through a link to the skill, a path
# built with ".." would lead somewhere else.
_HERE = Path(__file__).resolve()
SETUP_TOOL = _HERE.parents[2] / "tools" / "setup" / "workflow_setup.py"


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return EXIT_ERROR


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="settings.py",
        allow_abbrev=False,
        description="Print the settings a skill or a role reads, and the layer each came from.",
    )
    parser.add_argument(
        "key",
        nargs="?",
        metavar="KEY",
        help=f"a group ({', '.join(GROUPS)}) or a dotted key such as process.docs_dir; "
        f"{' and '.join(DEFAULT_GROUPS)} when omitted",
    )
    parser.add_argument(
        "--project",
        metavar="DIR",
        help="the project whose settings files are read; without it no project file is read",
    )
    parser.add_argument(
        "--home",
        metavar="DIR",
        help="use DIR in place of the user's home directory (for tests and trial runs)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    return parser.parse_args(argv)


def _from_tool(args: argparse.Namespace, keys: list[str]) -> int:
    """Ask the setup tool, one run per key, and print what it printed."""
    # An option given with an empty value is passed on as it is, for the
    # tool to refuse: dropped here, it would be read as "not given".
    places: list[str] = []
    if args.project is not None:
        places += ["--project", args.project]
    if args.home is not None:
        places += ["--home", args.home]
    settings: dict = {}
    version = SCHEMA_VERSION
    text = b""
    for key in keys:
        command = [sys.executable, "-B", str(SETUP_TOOL), "show", key, *places]
        if args.json:
            command.append("--json")
        # The tool's errors go straight to stderr; its stdout is UTF-8 with LF.
        done = subprocess.run(command, stdout=subprocess.PIPE, check=False)
        if done.returncode != 0:
            return done.returncode
        if args.json:
            report = json.loads(done.stdout.decode("utf-8"))
            version = report.get("schema_version", version)
            settings.update(report.get("settings", {}))
        else:
            text += done.stdout
    if args.json:
        print(json.dumps({"schema_version": version, "settings": settings}, indent=2))
    else:
        sys.stdout.flush()
        sys.stdout.buffer.write(text)
        sys.stdout.buffer.flush()
    return 0


def _format(value: object) -> str:
    """A built-in value as the tool writes it: TOML text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _refused(args: argparse.Namespace) -> str | None:
    """What the setup tool would refuse about ``--home`` and ``--project``,
    for a skill that has no tool to refuse it."""
    for option, text in (("--home", args.home), ("--project", args.project)):
        if text is None:
            continue
        if not text.strip():
            return f"{option}: an empty value is not a directory; name one, or leave the option out"
        try:
            found = Path(text).expanduser().is_dir()
        except (OSError, RuntimeError, KeyError, ValueError):
            found = False
        if not found:
            return f"{option}: {text}: not a directory"
    return None


def _from_built_in(args: argparse.Namespace, keys: list[str]) -> int:
    """Print the built-in defaults: there is no setup tool to ask."""
    refused = _refused(args)
    if refused is not None:
        return _fail(refused)
    found: dict = {}
    for key in keys:
        matched = {name: value for name, value in BUILT_IN.items() if name == key or name.startswith(key + ".")}
        if not matched:
            known = ", ".join(name for name in BUILT_IN if name.split(".")[0] == key.split(".")[0])
            return _fail(f"{key}: no such setting; known: {known}")
        found.update(matched)
    print(
        "note: no setup tool beside this skill; these are the skill's built-in defaults, "
        "and no settings file was read",
        file=sys.stderr,
    )
    if args.json:
        report = {
            "schema_version": SCHEMA_VERSION,
            "settings": {
                name: {"value": value, "layer": BUILT_IN_LAYER, "file": None} for name, value in found.items()
            },
        }
        print(json.dumps(report, indent=2))
    else:
        for name, value in found.items():
            print(f"{name} = {_format(value)}  ({BUILT_IN_LAYER})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.key is None:
        keys = list(DEFAULT_GROUPS)
    elif args.key.split(".")[0] in GROUPS:
        keys = [args.key]
    else:
        return _fail(f"{args.key}: not a setting a skill reads; known groups: {', '.join(GROUPS)}")
    if SETUP_TOOL.is_file():
        return _from_tool(args, keys)
    return _from_built_in(args, keys)


if __name__ == "__main__":
    # Output is UTF-8 with LF on every platform, whatever the console's own
    # encoding is.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
