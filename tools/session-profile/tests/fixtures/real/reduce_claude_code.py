#!/usr/bin/env python3
"""Cut a Claude Code session record down to a fixture for session_profile.py.

Usage:
    reduce_claude_code.py [--project NAME] [--responses N] <main transcript> <output directory>

<main transcript> is ``<config>/projects/<project>/<session>.jsonl``. Its
subagents are taken from ``<session>/subagents/`` beside it. The output
directory is written as a config home:

    <output>/projects/<NAME>/<session>.jsonl
    <output>/projects/<NAME>/<session>/subagents/agent-<id>.jsonl
    <output>/projects/<NAME>/<session>/subagents/agent-<id>.meta.json

Only the fields the reader reads are kept, and only where the value is a
short identifier token. Everything else is dropped: message content, tool
input and output, prompts, descriptions, working directories, every path.
The project directory name, which encodes a path of the machine, is
replaced by NAME.

Of each transcript the following entries are kept, in their order:
the first two ``agent-setting`` entries, the first ``user`` entry (as its
type and version only) and every ``assistant`` entry of the first N
responses (a response is one ``message.id``; it is written as one entry per
content block).

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Key paths kept, by entry type. These are the paths session_profile.py reads.
KEEP = {
    "assistant": (
        ("type",), ("version",), ("effort",), ("perTurnEffort",), ("attributionAgent",),
        ("message", "id"), ("message", "model"),
    ),
    "agent-setting": (("type",), ("agentSetting",)),
    "user": (("type",), ("version",)),
}
KEEP_META = ("agentType", "parentAgentId")
SETTING_ENTRIES = 2
USER_ENTRIES = 1

_TOKEN = re.compile(r"[\w.\-:]{1,64}")


def token(value):
    """The value if it is one short identifier token, else None."""
    if isinstance(value, str) and _TOKEN.fullmatch(value):
        return value
    return None


def dig(obj, path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def reduce_entry(entry: dict) -> dict:
    kept: dict = {}
    for path in KEEP[entry["type"]]:
        value = token(dig(entry, path))
        if value is None:
            continue
        target = kept
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value
    return kept


def reduce_transcript(source: Path, target: Path, responses: int) -> int:
    kept: list[dict] = []
    counts = {"agent-setting": 0, "user": 0}
    limits = {"agent-setting": SETTING_ENTRIES, "user": USER_ENTRIES}
    messages: list[str] = []
    with source.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") not in KEEP:
                continue
            kind = entry["type"]
            if kind in limits:
                if counts[kind] >= limits[kind]:
                    continue
                counts[kind] += 1
            else:
                message = token(dig(entry, ("message", "id")))
                if message is None:
                    continue
                if message not in messages:
                    if len(messages) >= responses:
                        continue
                    messages.append(message)
            kept.append(reduce_entry(entry))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in kept:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return len(kept)


def reduce_meta(source: Path, target: Path) -> None:
    try:
        meta = json.loads(source.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return
    if not isinstance(meta, dict):
        return
    kept = {key: token(meta.get(key)) for key in KEEP_META if token(meta.get(key)) is not None}
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(kept, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("transcript", type=Path, help="the session's main transcript")
    parser.add_argument("output", type=Path, help="the directory to write the config home into")
    parser.add_argument("--project", default="-fixture-toy", help="the project directory name to write")
    parser.add_argument("--responses", type=int, default=3, help="responses kept per agent")
    args = parser.parse_args(argv)

    if not args.transcript.is_file():
        print("reduce_claude_code: no such transcript", file=sys.stderr)
        return 1
    if not _TOKEN.fullmatch(args.project):
        print("reduce_claude_code: --project must be one name", file=sys.stderr)
        return 2
    session = args.transcript.stem
    project = args.output / "projects" / args.project
    written = [(f"{session}.jsonl", reduce_transcript(args.transcript, project / f"{session}.jsonl", args.responses))]
    subagents = args.transcript.with_suffix("") / "subagents"
    if subagents.is_dir():
        for source in sorted(subagents.glob("agent-*.jsonl")):
            target = project / session / "subagents" / source.name
            written.append((source.name, reduce_transcript(source, target, args.responses)))
            meta = source.with_name(source.stem + ".meta.json")
            if meta.is_file():
                reduce_meta(meta, target.with_name(meta.name))
    for name, count in written:
        print(f"{name}: {count} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
