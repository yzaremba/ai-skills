#!/usr/bin/env python3
"""Print the settings a skill or a role reads.

Usage:
    python scripts/settings.py [KEY] [--project DIR] [--home DIR] [--json]

KEY is ``process``, ``memory`` or ``roles``, or a dotted key in one of
them, such as ``process.docs_dir`` or ``roles.max_parallel_coders``. Without
KEY the process and memory groups are printed: ``roles`` is printed only
when it is asked for, so a fault in it stops no skill that does not read
it. Any other group is refused. Nothing is ever written.

The keys read are process.docs_dir, process.questions, process.recommend,
process.density, memory.dir and roles.max_parallel_coders. This file reads
the settings files itself, with tomllib, over the built-in defaults below;
it needs no setup tool, so a skill copied on its own reads them too. The
layers, each over the one before it, key by key:

    built-in   the defaults below (no file)
    user       ~/.agents/workflow.toml
    project    DIR/.agents/workflow.toml          (with --project)
    local      DIR/.agents/workflow.local.toml    (with --project)

A bad value of a key that is read (the wrong type, a value not allowed,
an empty or blank string, an integer below 1) stops with exit code 2,
naming the file and the key. So does a file that is not UTF-8 or not
TOML, and a ``.agents`` that is not a directory. Every other key in a
file, such as an old key, ``install`` or ``schema_version``, is not judged
here: the setup tool's ``--check`` reports it.

--project DIR names the project whose settings files are read. The
project is only ever that directory; it is not taken from the working
directory. Without it only the user's file is read.
--home DIR stands in for the user's home directory. A DIR that is empty or
is not a directory is refused; an empty one is never taken to mean "not
given". Options are written in full: an abbreviation is refused.

Text output is one line per value, with the layer it came from:

    process.docs_dir = "docs"  (built-in)

With --json the output is one object: "schema_version", and "settings",
which maps each dotted key to its "value", "layer" and "file" (the path of
the file the value came from, null for built-in).

Exit code 0, or 2 on an error, which is printed to stderr.

Standard library only; the same code on Linux and Windows. This file is
kept byte-identical in every skill that carries it.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tomllib
from pathlib import Path

GROUPS = ("process", "memory", "roles")
# What is printed without KEY.
DEFAULT_GROUPS = ("process", "memory")

# The keys this file reads, with their built-in values. The two must stay
# equal to the same keys of tools/setup/defaults.toml.
SCHEMA_VERSION = 1
BUILT_IN = {
    "process.docs_dir": "docs",
    "process.questions": "all-together",
    "process.recommend": True,
    "process.density": "brief",
    "memory.dir": "docs/memory",
    "roles.max_parallel_coders": 3,
}
BUILT_IN_LAYER = "built-in"
# What each key takes: its type, the values it is limited to, the least integer.
CHOICES = {
    "process.questions": ("one-at-a-time", "all-together"),
    "process.density": ("brief", "full"),
}
# process.recommend takes true, false, or this word.
RECOMMEND_WORDS = ("accept",)

EXIT_ERROR = 2


class SettingsError(Exception):
    """A fault in a place or a settings file; the message is for the user."""


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


def _format(value: object) -> str:
    """A value as TOML writes it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _type_name(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "table"
    return type(value).__name__.lower()


def _article(name: str) -> str:
    return ("an " if name[0] in "aeiou" else "a ") + name


def _place(option: str, text: str | None) -> Path | None:
    """The directory ``--home`` or ``--project`` names, or None if not given."""
    if text is None:
        return None
    if not text.strip():
        raise SettingsError(f"{option}: an empty value is not a directory; name one, or leave the option out")
    try:
        path = Path(text).expanduser()
        found = path.is_dir()
    except (OSError, RuntimeError, KeyError, ValueError):
        found = False
    if not found:
        raise SettingsError(f"{option}: {text}: not a directory")
    return path


def _problem(key: str, value: object) -> str | None:
    """What is wrong with ``value`` for ``key``, or None."""
    actual = _type_name(value)
    if key == "process.recommend":
        if actual != "boolean" and value not in RECOMMEND_WORDS:
            shown = _format(value) if actual in ("string", "integer") else _article(actual)
            return f"{shown} is not allowed; allowed values: true, false, {', '.join(RECOMMEND_WORDS)}"
        return None
    wanted = _type_name(BUILT_IN[key])
    if actual != wanted:
        return f"expected {_article(wanted)}, got {_article(actual)}"
    if key in CHOICES and value not in CHOICES[key]:
        return f"{_format(value)} is not allowed; allowed values: {', '.join(CHOICES[key])}"
    if wanted == "integer" and value < 1:
        return f"{value} is too small; the least allowed is 1"
    if wanted == "string" and not value:
        return "must not be empty"
    if wanted == "string" and not value.strip():
        return "must not be blank; it holds only white space"
    return None


def _read_file(file: Path, keys: list[str]) -> dict[str, object]:
    """The values of ``keys`` that ``file`` holds; none if it is not there."""
    try:
        is_directory = file.parent.is_dir()
        exists = is_directory or file.parent.exists()
    except OSError as exc:
        raise SettingsError(f"{file}: cannot be read: {exc.strerror or exc}") from None
    if not is_directory:
        if exists:
            raise SettingsError(f"{file.parent}: not a directory")
        if os.path.lexists(file.parent):  # a link to nowhere, or a link loop
            raise SettingsError(f"{file.parent}: not a directory: link target missing")
        return {}
    try:
        if not stat.S_ISREG(file.stat().st_mode):  # looked at first: a FIFO would block the read
            raise SettingsError(f"{file}: is not a file")
        raw = file.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise SettingsError(f"{file}: cannot be read: {exc.strerror or exc}") from None
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SettingsError(f"{file}: not UTF-8: {exc.reason}") from None
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{file}: not valid TOML: {exc}") from None
    except RecursionError:
        raise SettingsError(f"{file}: not valid TOML: arrays or inline tables are nested too deeply") from None
    except ValueError:
        raise SettingsError(f"{file}: not valid TOML: it holds an integer with too many digits") from None
    found: dict[str, object] = {}
    for key in keys:
        group, name = key.split(".", 1)
        table = data.get(group)
        if table is None:
            continue
        if not isinstance(table, dict):
            raise SettingsError(f"{file}: {group}: expected a table, got {_article(_type_name(table))}")
        if name in table:
            problem = _problem(key, table[name])
            if problem is not None:
                raise SettingsError(f"{file}: {key}: {problem}")
            found[key] = table[name]
    return found


def _resolve(args: argparse.Namespace, keys: list[str]) -> dict[str, dict]:
    """Each key's value, layer and file: the built-in value, then the
    user's file, then the project's, then the project's local file."""
    home = _place("--home", args.home)
    project = _place("--project", args.project)
    if home is None:
        home = Path.home()
    layers = [("user", home / ".agents" / "workflow.toml")]
    if project is not None:
        layers.append(("project", project / ".agents" / "workflow.toml"))
        layers.append(("local", project / ".agents" / "workflow.local.toml"))
    resolved = {key: {"value": BUILT_IN[key], "layer": BUILT_IN_LAYER, "file": None} for key in keys}
    for layer, file in layers:
        for key, value in _read_file(file, keys).items():
            resolved[key] = {"value": value, "layer": layer, "file": str(file)}
    return resolved


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.key is None:
        groups = list(DEFAULT_GROUPS)
        keys = [name for name in BUILT_IN if name.split(".")[0] in groups]
    elif args.key.split(".")[0] in GROUPS:
        keys = [name for name in BUILT_IN if name == args.key or name.startswith(args.key + ".")]
        if not keys:
            known = ", ".join(name for name in BUILT_IN if name.split(".")[0] == args.key.split(".")[0])
            return _fail(f"{args.key}: no such setting; known: {known}")
    else:
        return _fail(f"{args.key}: not a setting a skill reads; known groups: {', '.join(GROUPS)}")
    try:
        found = _resolve(args, keys)
    except SettingsError as exc:
        return _fail(str(exc))
    if args.json:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "settings": found}, indent=2, ensure_ascii=False))
    else:
        for name, entry in found.items():
            print(f"{name} = {_format(entry['value'])}  ({entry['layer']})")
    return 0


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
