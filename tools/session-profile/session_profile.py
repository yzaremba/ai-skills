#!/usr/bin/env python3
"""Show the role, model and effort a provider recorded for each agent of a session.

Usage:
    session_profile.py [--json] [--full-paths] <provider> <session>

<provider> is ``claude-code`` or ``codex``. <session> is a session id, or a
path to one record file of the session.

The values come from the provider's own session record, never from what an
agent said about itself. Only identifier fields are read and printed; no
message, prompt, instruction or tool text is ever printed. A value that is
not shaped like an identifier (a role holding a sentence, say) counts as
absent.

Neither record format is a published interface. The reader therefore skips
lines it cannot parse, ignores fields it does not know, and reports a value
it cannot find as "not recorded" (``null`` with ``--json``). It prints the
provider version found in the record next to the version it was written
against, so a drift between the two is visible.

Standard library only, Python 3.11 or later, the same code on Linux and
Windows.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterator

NOT_RECORDED = "not recorded"

# The provider versions whose record layout this reader was written against.
WRITTEN_AGAINST = {"claude-code": "2.1.289", "codex": "0.160.0"}

# --- Field tables -----------------------------------------------------------
# Each table lists, in order of preference, where a value is looked for. A
# table entry is a key path. Adding a newly found location is one more entry.

# Codex: the payload of a rollout's ``session_meta`` record.
_SPAWN = ("source", "subagent", "thread_spawn")
CODEX_META_FIELDS = {
    "role": (("agent_role",), _SPAWN + ("agent_role",)),
    "path": (("agent_path",), _SPAWN + ("agent_path",)),
    "nickname": (("agent_nickname",), _SPAWN + ("agent_nickname",)),
    "parent": (("parent_thread_id",), _SPAWN + ("parent_thread_id",)),
    "kind": (("thread_source",),),
    "version": (("cli_version",),),
    "id": (("id",),),
}
# Codex: the payload of each ``turn_context`` record.
CODEX_TURN_FIELDS = {
    "model": (("model",), ("collaboration_mode", "settings", "model")),
    "effort": (("effort",), ("collaboration_mode", "settings", "reasoning_effort")),
}

# Claude Code: a subagent's ``agent-<id>.meta.json`` beside its transcript.
CLAUDE_META_FIELDS = {
    "role": (("agentType",),),
    "parent": (("parentAgentId",),),
}
# Claude Code: an ``assistant`` entry of a transcript.
CLAUDE_ENTRY_FIELDS = {
    "role": (("attributionAgent",),),
    "model": (("message", "model"),),
    "effort": (("effort",), ("perTurnEffort",)),
}
# A model value Claude Code writes for entries it made up itself (API errors).
CLAUDE_SYNTHETIC_MODEL = "<synthetic>"

_IDENT = re.compile(r"[\w.\-:\[\]/@+<>]{1,120}")
_UUID_AT_END = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_SESSION_ID = re.compile(r"[\w\-]{1,120}")
# A role or agent-type name, or a nickname: one token, no spaces. Seen in
# records: ``general-purpose``, ``sprint-coder``, ``Explore``,
# ``collab_probe_role``, ``Ada``; a plugin's agent type is ``plugin:name``.
_NAME = re.compile(r"[\w.\-:]{1,64}")
# A Codex agent path: ``/root/coder``, ``/root/a/b/c``.
_AGENT_PATH = re.compile(r"/?[\w.\-]+(?:/[\w.\-]+)*")
_AGENT_PATH_MAX = 120
_SHOWN_ARGUMENT_MAX = 80


class SessionNotFound(Exception):
    """The session, or its record, could not be located."""


class AmbiguousSession(Exception):
    """More than one record claims to be the same thread."""


# --- Small helpers ----------------------------------------------------------

def _ident(value: Any) -> str | None:
    """Return ``value`` if it is a short identifier token, else None.

    Models, efforts, ids and versions are single tokens. Anything else found
    in such a field is treated as absent, which also keeps free text out of
    the output if a record is not shaped as expected.
    """
    if isinstance(value, str) and _IDENT.fullmatch(value):
        return value
    return None


def _name(value: Any) -> str | None:
    """A role, agent-type or nickname token, else None. No spaces, so no prose."""
    if isinstance(value, str) and _NAME.fullmatch(value):
        return value
    return None


def _agent_path(value: Any) -> str | None:
    """A slash-separated path of name segments, else None."""
    if isinstance(value, str) and len(value) <= _AGENT_PATH_MAX and _AGENT_PATH.fullmatch(value):
        return value
    return None


def _existing_file(argument: str) -> Path | None:
    """The argument as a path if it names a file, else None.

    An argument the system cannot take as a path at all (too long, or with a
    character a path may not hold) is simply not a file.
    """
    try:
        path = Path(argument)
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def _not_a_session(argument: str) -> SessionNotFound:
    shown = argument if len(argument) <= _SHOWN_ARGUMENT_MAX else argument[:_SHOWN_ARGUMENT_MAX] + "..."
    return SessionNotFound(f"session not found: neither a record file nor a session id: {shown}")


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        return path.absolute()


def _dig(obj: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _lookup(obj: Any, paths: tuple[tuple[str, ...], ...], clean=_ident) -> tuple[str | None, str | None]:
    """First usable value among ``paths``, with the dotted path it came from."""
    for path in paths:
        value = clean(_dig(obj, path))
        if value is not None:
            return value, ".".join(path)
    return None, None


class Records:
    """Iterate the JSON objects of a JSONL file, skipping what is not one."""

    def __init__(self, path: Path, needle: str | None = None):
        self.path = path
        # Lines without the needle are passed over unparsed and uncounted.
        self.needle = needle
        self.malformed = 0
        self.unreadable = False

    def __iter__(self) -> Iterator[dict]:
        try:
            handle = self.path.open(encoding="utf-8", errors="replace")
        except OSError:
            self.unreadable = True
            return
        with handle:
            try:
                for line in handle:
                    if self.needle is not None and self.needle not in line:
                        continue
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except (ValueError, RecursionError):
                        self.malformed += 1
                        continue
                    if isinstance(record, dict):
                        yield record
                    else:
                        self.malformed += 1
            except OSError:
                self.unreadable = True


class Profiles:
    """Distinct (model, effort) pairs in order of first appearance, counted."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str | None, str | None], int] = {}

    def add(self, model: str | None, effort: str | None) -> None:
        key = (model, effort)
        self._counts[key] = self._counts.get(key, 0) + 1

    def as_list(self) -> list[dict]:
        return [{"model": m, "effort": e, "count": n} for (m, e), n in self._counts.items()]


def _new_agent(agent_id: str | None, record: Path, count_unit: str) -> dict:
    return {
        "id": agent_id,
        "parent_id": None,
        "depth": 0,
        "role": None,
        "role_source": None,
        "name": None,
        "kind": None,
        "profiles": [],
        "count_unit": count_unit,
        "effort_sources": [],
        "provider_versions": [],
        "record": str(record),
        "malformed_lines": 0,
        "readable": True,
        "notes": [],
    }


def _add_unique(items: list, value: Any) -> None:
    if value is not None and value not in items:
        items.append(value)


def _order_tree(agents: list[dict]) -> list[dict]:
    """Parents before their children, depth set from the parent links."""
    by_id = {a["id"]: a for a in agents if a["id"] is not None}
    children: dict[str | None, list[dict]] = {}
    for agent in agents:
        parent = agent["parent_id"] if agent["parent_id"] in by_id and agent["parent_id"] != agent["id"] else None
        children.setdefault(parent, []).append(agent)
    ordered: list[dict] = []
    seen: set[int] = set()

    def walk(start: dict) -> None:
        # An explicit stack: a chain of parents may be deeper than the
        # interpreter lets a function call itself.
        stack = [(start, 0)]
        while stack:
            agent, depth = stack.pop()
            if id(agent) in seen:
                continue
            seen.add(id(agent))
            agent["depth"] = depth
            ordered.append(agent)
            if agent["id"] is not None:
                for child in reversed(children.get(agent["id"], [])):
                    stack.append((child, depth + 1))

    for root in children.get(None, []):
        walk(root)
    for agent in agents:  # anything left is part of a parent cycle
        walk(agent)
    return ordered


def _report(provider: str, session: str | None, agents: list[dict], notes: list[str] | None = None) -> dict:
    versions: list[str] = []
    for agent in agents:
        for version in agent["provider_versions"]:
            _add_unique(versions, version)
    return {
        "provider": provider,
        "session": session,
        "provider_versions": versions,
        "written_against": WRITTEN_AGAINST[provider],
        "notes": notes or [],
        "agents": agents,
    }


# --- Codex ------------------------------------------------------------------

def codex_home() -> Path:
    value = os.environ.get("CODEX_HOME")
    return Path(value) if value else Path.home() / ".codex"


def _codex_meta(path: Path) -> dict:
    """The payload of the rollout's first ``session_meta`` record, or {}.

    Codex writes it as the first line, but nothing promises that, so the file
    is read until one is found. Lines that do not name the record type are
    passed over without being parsed. A later ``session_meta`` is not this
    thread's own (seen: it carries another thread's id) and is not read.
    """
    for record in Records(path, needle="session_meta"):
        if record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
            return record["payload"]
    return {}


def _codex_thread_id(path: Path, meta: dict) -> tuple[str, bool]:
    """The thread a rollout belongs to, and whether its ``session_meta`` disagrees.

    A rollout is named ``rollout-<time>-<thread id>.jsonl``. The id in the name
    is preferred: a ``session_meta`` naming another thread is suspect and must
    not make this file stand in for that thread.
    """
    meta_id, _ = _lookup(meta, CODEX_META_FIELDS["id"])
    match = _UUID_AT_END.search(path.stem)
    if match:
        name_id = match.group(1)
        return name_id, meta_id is not None and meta_id.lower() != name_id.lower()
    return meta_id or path.stem, False


def _codex_search_dir(record: Path) -> tuple[Path, bool]:
    """Where the children of a rollout given by path are looked for.

    The whole ``sessions`` directory the file is under, searched at any depth;
    or, for a file under no such directory, only the file's own directory.
    """
    sessions = codex_home() / "sessions"
    resolved = _resolved(record)
    if resolved.is_relative_to(_resolved(sessions)):
        return sessions, True
    for parent in resolved.parents:
        if parent.name == "sessions":
            return parent, True
    return resolved.parent, False


def _codex_index(search_dir: Path, recursive: bool = True) -> dict[str, list[tuple[Path, dict, bool]]]:
    """Every rollout found, by thread id. More than one under an id is kept, not chosen from."""
    index: dict[str, list[tuple[Path, dict, bool]]] = {}
    try:
        found = search_dir.rglob("*.jsonl") if recursive else search_dir.glob("*.jsonl")
        paths = sorted(p for p in found if p.is_file())
    except OSError:
        paths = []
    for path in paths:
        meta = _codex_meta(path)
        thread_id, suspect = _codex_thread_id(path, meta)
        index.setdefault(thread_id, []).append((path, meta, suspect))
    return index


def _codex_agent(thread_id: str, path: Path, meta: dict, suspect: bool = False) -> dict:
    agent = _new_agent(thread_id, path, "turns")
    if suspect:
        agent["notes"].append(
            "session_meta names another thread than the file name does; the id is taken from the file name"
        )
    agent["parent_id"], _ = _lookup(meta, CODEX_META_FIELDS["parent"])
    agent["role"], agent["role_source"] = _lookup(meta, CODEX_META_FIELDS["role"], _name)
    if agent["role_source"]:
        agent["role_source"] = "session_meta." + agent["role_source"]
    agent_path, _ = _lookup(meta, CODEX_META_FIELDS["path"], _agent_path)
    nickname, _ = _lookup(meta, CODEX_META_FIELDS["nickname"], _name)
    agent["name"] = f"{agent_path} ({nickname})" if agent_path and nickname else agent_path or nickname
    agent["kind"], _ = _lookup(meta, CODEX_META_FIELDS["kind"])
    version, _ = _lookup(meta, CODEX_META_FIELDS["version"])
    _add_unique(agent["provider_versions"], version)

    profiles = Profiles()
    records = Records(path)
    for record in records:
        if record.get("type") != "turn_context":
            continue
        payload = record.get("payload")
        model, _ = _lookup(payload, CODEX_TURN_FIELDS["model"])
        effort, source = _lookup(payload, CODEX_TURN_FIELDS["effort"])
        profiles.add(model, effort)
        if source:
            _add_unique(agent["effort_sources"], "turn_context." + source)
    agent["profiles"] = profiles.as_list()
    agent["malformed_lines"] = records.malformed
    agent["readable"] = not records.unreadable
    return agent


def read_codex(session: str) -> dict:
    notes: list[str] = []
    as_path = _existing_file(session)
    if as_path is not None:
        search_dir, recursive = _codex_search_dir(as_path)
        if not recursive:
            notes.append(
                "the record is under no sessions directory; spawned threads were looked for in its own directory only"
            )
        index = _codex_index(search_dir, recursive)
        meta = _codex_meta(as_path)
        root_id, suspect = _codex_thread_id(as_path, meta)
        given = _resolved(as_path)
        others = [path.name for path, _, _ in index.get(root_id, []) if _resolved(path) != given]
        if others:
            notes.append(f"thread {root_id} is also the id of {', '.join(others)}; the file given is the one read")
        index[root_id] = [(as_path, meta, suspect)]
    else:
        if not _SESSION_ID.fullmatch(session):
            raise _not_a_session(session)
        sessions = codex_home() / "sessions"
        if not sessions.is_dir():
            raise SessionNotFound(f"no sessions directory under the Codex home ({sessions})")
        index = _codex_index(sessions)
        root_id = session
        if root_id not in index:
            raise SessionNotFound(f"no rollout for session {session} under {sessions}")

    children: dict[str, list[str]] = {}
    for thread_id, entries in index.items():
        for _, meta, _ in entries:
            parent, _ = _lookup(meta, CODEX_META_FIELDS["parent"])
            if parent and parent != thread_id and thread_id not in children.setdefault(parent, []):
                children[parent].append(thread_id)

    wanted: list[str] = []
    seen: set[str] = set()
    queue = [root_id]
    for thread_id in queue:  # the list grows as it is walked
        if thread_id in seen:
            continue
        seen.add(thread_id)
        wanted.append(thread_id)
        queue.extend(children.get(thread_id, []))

    for thread_id in wanted:
        if len(index[thread_id]) > 1:
            names = ", ".join(path.name for path, _, _ in index[thread_id])
            hint = "give the path of the one meant" if thread_id == root_id else "they cannot both be its record"
            raise AmbiguousSession(f"thread {thread_id} has {len(index[thread_id])} rollouts ({names}); {hint}")

    agents = [_codex_agent(thread_id, *index[thread_id][0]) for thread_id in wanted]
    return _report("codex", root_id, _order_tree(agents), notes)


# --- Claude Code ------------------------------------------------------------

def claude_config_dir() -> Path:
    value = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(value) if value else Path.home() / ".claude"


def _read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _claude_agent(agent_id: str | None, path: Path, meta: dict, kind: str) -> dict:
    agent = _new_agent(agent_id, path, "responses")
    agent["kind"] = kind
    agent["role"], source = _lookup(meta, CLAUDE_META_FIELDS["role"], _name)
    if source:
        agent["role_source"] = "meta.json:" + source
    agent["parent_id"], _ = _lookup(meta, CLAUDE_META_FIELDS["parent"])

    profiles = Profiles()
    seen_messages: set[str] = set()
    records = Records(path)
    for record in records:
        _add_unique(agent["provider_versions"], _ident(record.get("version")))
        if record.get("type") != "assistant":
            continue
        model, _ = _lookup(record, CLAUDE_ENTRY_FIELDS["model"])
        if model == CLAUDE_SYNTHETIC_MODEL:
            continue
        if agent["role"] is None:
            agent["role"], source = _lookup(record, CLAUDE_ENTRY_FIELDS["role"], _name)
            if source:
                agent["role_source"] = "assistant entry:" + source
        effort, source = _lookup(record, CLAUDE_ENTRY_FIELDS["effort"])
        if source:
            _add_unique(agent["effort_sources"], "assistant entry:" + source)
        # One response is written as one entry per content block; count it once.
        message_id = _ident(_dig(record, ("message", "id")))
        if message_id is not None:
            if message_id in seen_messages:
                continue
            seen_messages.add(message_id)
        profiles.add(model, effort)
    agent["profiles"] = profiles.as_list()
    agent["malformed_lines"] = records.malformed
    agent["readable"] = not records.unreadable
    return agent


def _claude_subagent(path: Path, session_id: str | None) -> dict:
    agent_id = path.stem.removeprefix("agent-")
    meta = _read_json_object(path.with_name(path.stem + ".meta.json"))
    agent = _claude_agent(agent_id, path, meta, "subagent")
    if agent["parent_id"] is None:
        agent["parent_id"] = session_id
    return agent


def _claude_session_of(subagent: Path) -> str | None:
    for parent in subagent.parents:
        if parent.name == "subagents":
            return parent.parent.name or None
    return None


def _is_claude_subagent(path: Path) -> bool:
    return path.name.startswith("agent-") and "subagents" in path.parts


def read_claude(session: str) -> dict:
    as_path = _existing_file(session)
    if as_path is not None:
        if _is_claude_subagent(_resolved(as_path)):
            session_id = _claude_session_of(_resolved(as_path))
            return _report("claude-code", session_id, [_claude_subagent(as_path, session_id)])
        main: Path | None = as_path
        session_dir = as_path.with_suffix("")
        session_id = as_path.stem
    else:
        if not _SESSION_ID.fullmatch(session):
            raise _not_a_session(session)
        projects = claude_config_dir() / "projects"
        if not projects.is_dir():
            raise SessionNotFound(f"no projects directory under the Claude Code config directory ({projects})")
        session_id = session
        homes = sorted(
            {p.parent for p in projects.glob(f"*/{session}.jsonl") if p.is_file()}
            | {p.parent for p in projects.glob(f"*/{session}") if (p / "subagents").is_dir()}
        )
        if not homes:
            raise SessionNotFound(f"no transcript for session {session} under {projects}")
        if len(homes) > 1:
            names = ", ".join(h.name for h in homes)
            raise SessionNotFound(f"session {session} is in more than one project ({names}); give the path of its transcript")
        main = homes[0] / f"{session}.jsonl"
        if not main.is_file():
            main = None
        session_dir = homes[0] / session

    agents: list[dict] = []
    if main is not None:
        agents.append(_claude_agent(session_id, main, {}, "main"))
    if session_dir.is_dir():
        for path in sorted(p for p in session_dir.rglob("agent-*.jsonl") if p.is_file()):
            agents.append(_claude_subagent(path, session_id))
    return _report("claude-code", session_id, _order_tree(agents))


# --- Output -----------------------------------------------------------------

READERS = {"claude-code": read_claude, "codex": read_codex}
HOMES = {"claude-code": claude_config_dir, "codex": codex_home}


def present_records(report: dict, full_paths: bool = False) -> None:
    """Rewrite each agent's ``record`` into the form that is printed.

    By default that is the path below the provider home, with forward
    slashes, or the bare file name for a record kept elsewhere, so the
    output names no directory of the machine. ``full_paths`` gives the
    absolute path instead.
    """
    home = _resolved(HOMES[report["provider"]]())
    for agent in report["agents"]:
        path = _resolved(Path(agent["record"]))
        if full_paths:
            agent["record"] = str(path)
        elif path.is_relative_to(home):
            agent["record"] = path.relative_to(home).as_posix()
        else:
            agent["record"] = path.name


def _shown(value: Any) -> str:
    return NOT_RECORDED if value is None else str(value)


def render_text(report: dict, full_paths: bool = False) -> str:
    versions = ", ".join(report["provider_versions"]) or NOT_RECORDED
    lines = [
        f"provider: {report['provider']}",
        f"session: {_shown(report['session'])}",
        f"provider version recorded: {versions} (reader written against {report['written_against']})",
        f"agents: {len(report['agents'])}",
    ]
    lines.extend(f"note: {note}" for note in report.get("notes", []))
    for agent in report["agents"]:
        pad = "  " * agent["depth"]
        lines.append("")
        lines.append(f"{pad}agent {_shown(agent['id'])}")
        fields = [
            ("kind", _shown(agent["kind"])),
            ("parent", _shown(agent["parent_id"]) if agent["depth"] or agent["parent_id"] else "none"),
            ("role", _shown(agent["role"])),
        ]
        if agent["name"]:
            fields.append(("name", agent["name"]))
        if not agent["profiles"]:
            fields.append(("model", NOT_RECORDED))
            fields.append(("effort", NOT_RECORDED))
        for profile in agent["profiles"]:
            unit = agent["count_unit"] if profile["count"] != 1 else agent["count_unit"].removesuffix("s")
            fields.append(("model", f"{_shown(profile['model'])}  ({profile['count']} {unit})"))
            fields.append(("effort", _shown(profile["effort"])))
        fields.append(("version", ", ".join(agent["provider_versions"]) or NOT_RECORDED))
        fields.append(("record", agent["record"] if full_paths else Path(agent["record"]).name))
        if agent["malformed_lines"]:
            fields.append(("skipped", f"{agent['malformed_lines']} malformed lines"))
        if not agent["readable"]:
            fields.append(("note", "record could not be read"))
        for note in agent.get("notes", []):
            fields.append(("note", note))
        for key, value in fields:
            lines.append(f"{pad}  {key + ':':<9}{value}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="session_profile.py",
        description=(
            "Print each agent of a session with the role name, model and effort the "
            "provider recorded for it, and the provider version the record was written by. "
            "No transcript text is printed."
        ),
        epilog=(
            "<session> is either a session id or the path of one record file.\n"
            "  claude-code  id: the session's UUID, looked up as\n"
            "               <config>/projects/<project>/<id>.jsonl, where <config> is\n"
            "               $CLAUDE_CONFIG_DIR or ~/.claude. Subagents are read from\n"
            "               <id>/subagents/agent-<agent>.jsonl beside it.\n"
            "               path: a main transcript prints the whole session; a subagent\n"
            "               transcript prints that one agent.\n"
            "  codex        id: the thread id of the session's first rollout, looked up\n"
            "               under <home>/sessions, where <home> is $CODEX_HOME or ~/.codex.\n"
            "               path: a rollout file. Either way the threads spawned from it,\n"
            "               at any depth, are found by parent_thread_id and listed with it.\n"
            "               For a path they are looked for in the sessions directory the\n"
            "               file is under; for a file under no directory named sessions,\n"
            "               in the file's own directory only, not below it.\n"
            "               A thread's id is the one in its rollout's file name. Two\n"
            "               rollouts with one id are reported, not chosen between.\n"
            "A role, nickname or agent path that is not an identifier (it holds a space,\n"
            "say) is treated as not recorded, so no free text is printed.\n"
            "The record of an agent is printed as its file name; with --json, as its path\n"
            "below the provider home, or the file name if it is kept elsewhere.\n"
            "A value the record does not hold is shown as \"not recorded\" (null with --json).\n"
            "A model with a different effort, or a change of model, is a separate line with\n"
            "its count of turns (codex) or responses (claude-code).\n"
            "Exit status: 0 on success, 1 if the session is not found or two records claim\n"
            "one thread id, 2 on a usage error."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("provider", choices=sorted(READERS), help="which provider's record to read")
    parser.add_argument("session", help="a session id, or the path of a record file")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    parser.add_argument(
        "--full-paths", action="store_true", help="print the absolute path of each record file"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    try:
        report = READERS[args.provider](args.session)
    except (SessionNotFound, AmbiguousSession) as error:
        print(f"session_profile: {error}", file=sys.stderr)
        return 1
    present_records(report, args.full_paths)
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(render_text(report, args.full_paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
