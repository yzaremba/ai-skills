"""Reduce Codex's offline discovery output to what the readers of
``wfsetup/discovery.py`` look at, with nothing of the machine it ran on.

    python reduce_codex_discovery.py prompt-input full.json out.json HOME CLONE
    python reduce_codex_discovery.py skills-list full.jsonl out.jsonl HOME CLONE

``prompt-input``: what ``codex debug prompt-input`` printed. Kept: each
message's ``type`` and ``role``, the skills section whole, and the first
lines of every other text (enough to tell which block it is, and for a
profile the lines its instructions begin with). Dropped: message ids and
metadata, the rest of each text, the environment block's content.

``skills-list``: what ``codex app-server`` printed, one JSON object a line.
Kept: the answers' ids, the skills with ``name``, ``enabled``, ``scope``,
``path``, ``pluginId`` and the first words of ``description``, and each
notification's method. Dropped: the rest.

In both, HOME (the home the command ran in) becomes ``/home/user`` and
CLONE (the repository) ``/home/user/clone``.
"""
from __future__ import annotations

import json
import sys

KEEP_LINES = 4
KEEP_WORDS = 6


def rename(text: str, home: str, clone: str) -> str:
    return text.replace(clone, "/home/user/clone").replace(home, "/home/user")


def prompt_input(text: str, home: str, clone: str) -> str:
    reduced = []
    for message in json.loads(text):
        parts = []
        for part in message.get("content", []):
            body = part.get("text", "")
            if "<skills_instructions>" not in body:
                lines = body.splitlines()
                first = lines[0] if lines else ""
                body = first if first.startswith("<environment_context>") else "\n".join(lines[:KEEP_LINES])
                if len(lines) > 1:
                    body += "\n[...]"
            parts.append({"type": part.get("type"), "text": rename(body, home, clone)})
        reduced.append({"type": message.get("type"), "role": message.get("role"), "content": parts})
    return json.dumps(reduced, indent=2, ensure_ascii=False) + "\n"


def skills_list(text: str, home: str, clone: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        found = json.loads(line)
        if "method" in found:
            lines.append({"method": found["method"]})
            continue
        result = found.get("result", {})
        if "data" not in result:
            lines.append({"id": found.get("id"), "result": {}})
            continue
        data = []
        for one in result["data"]:
            skills = [
                {
                    "name": skill["name"],
                    "description": " ".join(skill.get("description", "").split()[:KEEP_WORDS]),
                    "enabled": skill.get("enabled"),
                    "path": rename(skill.get("path", ""), home, clone),
                    "pluginId": skill.get("pluginId"),
                    "scope": skill.get("scope"),
                }
                for skill in one.get("skills", [])
            ]
            data.append({"cwd": rename(one.get("cwd", ""), home, clone), "errors": one.get("errors", []),
                         "skills": skills})
        lines.append({"id": found.get("id"), "result": {"data": data}})
    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def main(argv: list[str]) -> int:
    if len(argv) != 5 or argv[0] not in ("prompt-input", "skills-list"):
        print(__doc__, file=sys.stderr)
        return 2
    kind, source, target, home, clone = argv
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    reduced = (prompt_input if kind == "prompt-input" else skills_list)(text, home, clone)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(reduced)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
