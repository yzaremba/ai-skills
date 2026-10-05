#!/usr/bin/env python3
"""Cut Codex rollouts down to a fixture for session_profile.py.

Usage:
    reduce_codex.py <rollout> [<rollout> ...] <output directory>

Each <rollout> is one ``rollout-<date>T<time>-<thread id>.jsonl`` of a
session: the main thread's and those of the threads spawned from it. Codex
keeps them all in one directory per day, so the ones wanted are named one by
one. The output directory is written as a Codex home:

    <output>/sessions/<year>/<month>/<day>/rollout-<date>T<time>-<thread id>.jsonl

The file name is kept, because it carries the thread id; the day directory
is taken from the name, never from where the source file was.

Of each rollout only the ``session_meta`` and ``turn_context`` records are
kept, in their order, and of those only the fields the reader reads, and
only where the value is a short identifier token (an agent path may hold
slashes). Everything else is dropped: messages, instructions, tool calls
and their output, working directories, sandbox and permission settings, git
information, account ids, timestamps, every path of the machine.

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SPAWN = ("payload", "source", "subagent", "thread_spawn")
_SETTINGS = ("payload", "collaboration_mode", "settings")

# Key paths kept, by record type. These are the paths session_profile.py reads.
KEEP = {
    "session_meta": (
        ("payload", "id"),
        ("payload", "parent_thread_id"),
        ("payload", "agent_role"),
        ("payload", "agent_path"),
        ("payload", "agent_nickname"),
        ("payload", "thread_source"),
        ("payload", "cli_version"),
        _SPAWN + ("parent_thread_id",),
        _SPAWN + ("agent_role",),
        _SPAWN + ("agent_path",),
        _SPAWN + ("agent_nickname",),
    ),
    "turn_context": (
        ("payload", "model"),
        ("payload", "effort"),
        _SETTINGS + ("model",),
        _SETTINGS + ("reasoning_effort",),
    ),
}

_TOKEN = re.compile(r"[\w.\-:]{1,64}")
_AGENT_PATH = re.compile(r"/?[\w.\-]+(?:/[\w.\-]+)*")
_AGENT_PATH_MAX = 120
_ROLLOUT_NAME = re.compile(
    r"rollout-(\d{4})-(\d{2})-(\d{2})T\d{2}-\d{2}-\d{2}-"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.jsonl"
)


def token(value):
    """The value if it is one short identifier token, else None."""
    if isinstance(value, str) and _TOKEN.fullmatch(value):
        return value
    return None


def agent_path(value):
    """The value if it is a slash-separated path of name segments, else None."""
    if isinstance(value, str) and len(value) <= _AGENT_PATH_MAX and _AGENT_PATH.fullmatch(value):
        return value
    return None


def dig(obj, path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def reduce_record(record: dict) -> dict:
    kept: dict = {"type": record["type"], "payload": {}}
    for path in KEEP[record["type"]]:
        clean = agent_path if path[-1] == "agent_path" else token
        value = clean(dig(record, path))
        if value is None:
            continue
        target = kept
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value
    return kept


def reduce_rollout(source: Path, target: Path) -> int:
    kept: list[dict] = []
    with source.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("type") in KEEP:
                kept.append(reduce_record(record))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for record in kept:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return len(kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("rollouts", type=Path, nargs="+", metavar="rollout", help="a rollout file of the session")
    parser.add_argument("output", type=Path, help="the directory to write the Codex home into")
    args = parser.parse_args(argv)

    named = []
    for source in args.rollouts:
        match = _ROLLOUT_NAME.fullmatch(source.name)
        if match is None:
            print(f"reduce_codex: not named like a rollout: {source.name}", file=sys.stderr)
            return 2
        if not source.is_file():
            print(f"reduce_codex: no such rollout: {source.name}", file=sys.stderr)
            return 1
        named.append((source, match.groups()))
    for source, (year, month, day) in named:
        target = args.output / "sessions" / year / month / day / source.name
        print(f"{source.name}: {reduce_rollout(source, target)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
