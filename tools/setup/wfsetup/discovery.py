"""Whether a provider itself lists what setup installed: the check ``discovery``.

How ``doctor`` uses it

    Check("discovery", discovery.check_discovery, "...", configure=discovery.configure)

    doctor                                  # the offline part: no session is started
    doctor --prove-discovery                # also the session probes: each spends quota
    doctor --prove-discovery --save-probe DIR

What counts (R6.3, R8.1)
    A provider's own output that lists the item. A model's answer does not
    count and is never read: no parser here looks at a field that holds
    what a model wrote.

The items, per installed provider
    skill             a skill of the clone installed for the provider
    loaded role       a role installed as a skill the user loads
    role definition   a generated agent file
    starting role     the role a session starts as: on Codex the profile
                      file, on Claude Code the role's agent file

The states
    proven     the provider's output lists the item; the finding names the
               command. An ``ok`` finding.
    unproven   no provider output that was read could list it. On a plain
               run that is ``info``, and all of it is one line: the items
               by provider, each with why and what would prove it. With
               ``--prove-discovery`` an item the probes did not prove is a
               warning, a finding of its own. Never an error.
    missing    an output was read that should list the item, and does not.
               An error.
    Two more things are said and are no state: an item that is not on disk
    (``info``; the check ``missing`` is about those) and an item whose file
    the provider could not load (an error): a definition that is not a
    regular file, does not parse or lacks a required key, a skill directory
    with no readable ``SKILL.md``. A provider whose program is not on PATH
    is not checked, and that is ``info``, as for every check that starts a
    program.

What proves what (read and run on 2026-10-05: Codex CLI 0.160.0, Claude
Code 2.1.290)

  Codex, offline. No command below sends a model request: each was run in
  a scratch home that held no credentials and exited with code 0.
    ``codex debug prompt-input <prompt>``
        "Render the exact model-visible prompt input list as JSON"
        (learn.chatgpt.com/docs/developer-commands). A JSON list of
        messages; a developer message holds ``<skills_instructions>`` with
        "### Skill roots" (``- `r0` = `<directory>` ``) and "### Available
        skills" (``- <name>: <description> (file: r0/<name>/SKILL.md)``).
        It proves a skill the model may load by itself. A skill with
        ``policy.allow_implicit_invocation: false`` is not in that list,
        with no warning (PLAN P2.2), so its absence there says nothing.
    ``codex app-server --listen stdio://``, request ``skills/list``
        "list skills for one or more `cwd` values (supports `forceReload`
        ...)" (learn.chatgpt.com/docs/app-server). JSON lines on standard
        input and output; "Clients must send a single `initialize` request
        per transport connection before invoking any other method on that
        connection, then acknowledge with an `initialized` notification."
        The answer holds ``result.data[].skills[]``, each with ``name``,
        ``enabled``, ``scope`` and ``path`` (the schema that ``codex
        app-server generate-json-schema`` writes). It lists the
        invoke-only skills too, so it proves those and every loaded role.
        "The app-server command and WebSocket transport are experimental"
        (the same page): where it gives no answer, an invoke-only skill is
        unproven and the reason is said.
    ``codex --profile <role> debug prompt-input <prompt>``
        ``--profile`` is an option of ``codex`` and is refused after the
        subcommand ("unexpected argument '--profile'"). The role's
        instructions are the first text of the first developer message. A
        profile file that does not exist changes nothing and the command
        still exits with code 0, so the proof is the role's own notice
        line in the output, never the exit code.
    Role definitions have no offline proof: the prompt input holds messages
    and no tool text, ``config/read`` of the app server gives ``agents`` as
    null with three agent files in place, and no request of the app server
    lists custom agents.

  Claude Code, offline: nothing. ``claude agents`` lists background
  sessions, ``claude doctor`` prints "installation and settings
  diagnostics", and ``claude plugin validate <dir>`` validates files and
  names none of them (code.claude.com/docs/en/cli-reference). Every item is
  unproven until a session is started.

  The session probes (``--prove-discovery``). EACH STARTS ONE SESSION WITH
  A MODEL AND SPENDS QUOTA. Each has a fixed argument list, no shell, a
  time limit, the working directory and environment of the offline probes,
  and prints nothing of the session but the names it extracted.
    ``claude -p <prompt> --output-format stream-json --verbose
      --no-session-persistence --max-turns 1``
        "The `system/init` event reports session metadata including the
        model, tools, MCP servers, and loaded plugins. It is the first
        event in the stream unless startup events precede it"
        (code.claude.com/docs/en/headless). The Agent SDK reference gives
        the event ``agents``, ``skills`` and ``slash_commands`` as well;
        that is not said on the headless page, so the reader takes any of
        those keys that is there and reports the keys it saw. The stream
        is read up to that event and no further, and the program is then
        ended: on Linux with SIGTERM, on which "Claude Code exits with
        code 143 ... starts no new tool call, sends no new model request"
        (the same page); on Windows by ending its process tree. The first
        request may already be on its way by then: the cost is at most one
        turn of a one-line prompt.
    ``codex exec --json --skip-git-repo-check --ephemeral --sandbox
      read-only <prompt>``
        "Print newline-delimited JSON events" (developer-commands). The
        reader looks for a tool definition named ``spawn_agent`` that the
        provider wrote (an object with that ``name`` and a ``description``
        or ``parameters``, and no ``arguments``: a call of the tool is a
        model's doing and is not read) and for the agent names in its
        text. UNVERIFIED: no document says the event stream carries tool
        definitions, and the session records of 0.160.0 that were looked
        at hold none. Where it does not, the definitions stay unproven
        with the event types seen, and the question goes to the user.

Where the probes run
    The working directory is the project (``--project``), else the home.
    The environment is ``homes.child_environment``'s, as for every program
    setup starts: the caller's, and for a scratch home (``--home``) it
    also points the provider at that home: ``HOME`` (and ``USERPROFILE``
    on Windows), ``CODEX_HOME`` and ``CLAUDE_CONFIG_DIR``. For the real
    home nothing is set: the provider finds its home as it always does.

    A provider's program may write state of its own into its home when it
    starts (Codex: its bundled skills, an installation id). Setup writes
    nothing there.

``--save-probe DIR``
    Writes what each probe gave, reduced to its listing parts, as one JSON
    file per probe in DIR (created if absent), so that the readers here
    can be tested on output captured from a real provider. Saved: the
    arguments the program was started with after its name, how the run
    ended, the names of keys, the names of event and message types, and
    the lists of names (skills, agents, commands, tools, plugins, servers).
    Not saved: any description, prompt or instruction text, anything a
    model wrote, any path, any id.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import definitions, entry, fsio, homes, modellist, paths, validate
from .errors import SetupError

PROVEN = "proven"
UNPROVEN = "unproven"
MISSING = "missing"
STATES = (PROVEN, UNPROVEN, MISSING)

# The kinds of item.
SKILL = "skill"
LOADED = "loaded role"
DEFINITION = "role definition"
START = "starting role"

# How long a started program may take, in seconds. Read when it is started.
OFFLINE_TIMEOUT = 60.0
SESSION_TIMEOUT = 180.0
# How long a program that was told to stop is waited for before it is ended.
STOP_GRACE = 10.0

MAX_OUTPUT = modellist.MAX_OUTPUT

# The user prompt ``codex debug prompt-input`` appends. Nothing is sent.
OFFLINE_PROMPT = "workflow setup discovery check"
# The prompt of a session probe: one line that needs no tool.
SESSION_PROMPT = "Reply with the single word ok."

APP_SERVER_ARGS = ("app-server", "--listen", "stdio://")
CLIENT_NAME = "workflow-setup-doctor"
LIST_REQUEST_ID = 1
CLAUDE_SESSION_ARGS = (
    "-p", SESSION_PROMPT, "--output-format", "stream-json", "--verbose", "--no-session-persistence",
    "--max-turns", "1",
)
CODEX_SESSION_ARGS = (
    "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only", SESSION_PROMPT,
)

# The keys of Claude Code's ``system/init`` event that list what a session
# found, where the event has them.
AGENT_KEYS = ("agents",)
SKILL_KEYS = ("skills", "slash_commands")
# The tool whose text names the agent types of a Codex session.
SPAWN_TOOL = "spawn_agent"
# What marks an object as a call of a tool, which a model made.
_CALL_KEYS = frozenset({"arguments", "call_id", "input", "output"})

_ROOT = re.compile(r"^- `(r\d+)` = `([^`]+)`\s*$")
_ENTRY = re.compile(r"^- (\S+): .*\(file: (r\d+)/([^)]*SKILL\.md)\)\s*$")
_SKILLS_HEADING = "### Available skills"
_SKILLS_TAG = "skills_instructions"
_TAG = re.compile(r"^<([A-Za-z_][A-Za-z0-9_ ]*)>")
_SKIPPED = ("skipped loading", "ignoring invalid")
_NAME = re.compile(r"[A-Za-z0-9_.:/-]{1,80}")


# --- Starting a program ----------------------------------------------------------

@dataclass
class Ran:
    """What a started program gave. ``fault`` is why it gave nothing that
    can be used, and reads on after the command's name; ``stopped`` is
    whether it was ended here once the line that was waited for came."""

    lines: list[str] = field(default_factory=list)
    code: int | None = None
    said: str = ""
    stopped: bool = False
    fault: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def outcome(self) -> str:
        """How the run ended, in a few words and with nothing it printed."""
        if self.fault is not None:
            return self.fault.split(":")[0]
        return "ended here after the line that was waited for" if self.stopped else f"exited with code {self.code}"


def start(argv: Iterable[str], environ: dict[str, str], cwd: Path, timeout: float, *,
          send: Iterable[str] = (), until: Callable[[str], bool] | None = None) -> Ran:
    """Start a program with a fixed argument list and no shell, and read
    what it prints, line by line. ``send`` is written to its standard input
    as lines, which then stays open. With ``until``, reading stops at the
    first line for which it is true and the program is told to stop, then
    ended; without it the program is waited for. One that does not get
    there within ``timeout`` seconds is ended with what it started."""
    send = list(send)
    with fsio.scratch_file() as err:
        options: dict[str, Any] = {"start_new_session": True} if os.name == "posix" else {}
        try:
            process = subprocess.Popen(
                list(argv), stdin=subprocess.PIPE if send else subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=err, env=dict(environ), cwd=str(cwd), shell=False, **options,
            )
        except (OSError, ValueError) as exc:
            return Ran(fault=f"could not be started: {paths.reason(exc)}")
        ran = Ran()
        seen = {"hit": False, "over": False}
        done = threading.Event()

        def read() -> None:
            size = 0
            try:
                for raw in process.stdout:  # type: ignore[union-attr]
                    size += len(raw)
                    if size > MAX_OUTPUT:
                        seen["over"] = True
                        break
                    text = raw.decode("utf-8-sig" if not ran.lines else "utf-8", errors="replace").rstrip("\r\n")
                    ran.lines.append(text)
                    if until is not None and until(text):
                        seen["hit"] = True
                        break
            except (OSError, ValueError):
                pass
            finally:
                done.set()

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            if send:
                try:
                    process.stdin.write("".join(line + "\n" for line in send).encode("utf-8"))  # type: ignore[union-attr]
                    process.stdin.flush()  # type: ignore[union-attr]
                except (OSError, ValueError):
                    pass  # it ended before it read; what it printed says the rest
            finished = done.wait(timeout)
            if finished and not seen["hit"] and not seen["over"]:
                try:
                    ran.code = process.wait(STOP_GRACE)
                except subprocess.TimeoutExpired:
                    finished = False  # it closed its output and runs on
            if not finished:
                ran.fault = f"did not finish within {timeout:g} seconds"
            elif seen["over"]:
                ran.fault = f"printed more than {MAX_OUTPUT} bytes"
            elif seen["hit"]:
                ran.stopped = True
                _stop(process, served=bool(send))
        finally:
            if process.poll() is None:
                modellist._end(process)
            reader.join(2.0)
            # The output is closed only once its reader is done: closing it
            # under a reader that something still holds open would wait.
            for stream in (process.stdin, None if reader.is_alive() else process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except (OSError, ValueError):
                    pass
        if ran.code is None:
            ran.code = process.poll()
        err.seek(0)
        ran.said = modellist._first_line(err.read(4096).decode("utf-8", errors="replace"))
        return ran


def _stop(process: subprocess.Popen, served: bool) -> None:
    """Tell a program that gave what was wanted to stop, and wait a little.
    One that reads requests ends when its input does. Any other gets
    SIGTERM, with what it started, where there is such a signal; the caller
    ends what is still running after that."""
    try:
        if process.stdin is not None:
            process.stdin.close()
    except (OSError, ValueError):
        pass
    if served:
        try:
            process.wait(STOP_GRACE)
            return
        except subprocess.TimeoutExpired:
            pass
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(STOP_GRACE)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _failed(ran: Ran, nothing: bool = True) -> str | None:
    """Why a program that was waited for gave nothing to read, else None."""
    if ran.fault is not None:
        return ran.fault
    if ran.code not in (0, None) and not ran.stopped:
        return f"exited with code {ran.code}" + (f": {ran.said}" if ran.said else "")
    if nothing and not ran.text.strip():
        return "printed nothing"
    return None


# --- Reading: Codex's prompt input -----------------------------------------------

@dataclass(frozen=True)
class PromptInput:
    """``codex debug prompt-input``, as far as it is read. ``skills`` is
    None when the output has no skills section."""

    roles: tuple[str, ...]                       # the role of each message, in order
    texts: tuple[tuple[str, str], ...]           # (role, text) of each text part
    skills: dict[str, tuple[str, str]] | None    # name -> (root id, file below the root)
    roots: dict[str, str]
    unread: int                                  # entry lines of the section that could not be read
    tags: tuple[str, ...]

    def shows(self, line: str) -> bool:
        """Whether an instruction line is in a developer message (in any
        message, where the output names no developer)."""
        mine = [text for role, text in self.texts if role == "developer"] or [text for _, text in self.texts]
        return any(line in text for text in mine)


def parse_prompt_input(text: str) -> PromptInput:
    """Read what ``codex debug prompt-input`` printed. A ``ValueError``
    says why it is not that."""
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        raise ValueError("printed what is not JSON") from None
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("printed JSON that is not a list of messages")
    roles, texts = [], []
    for item in payload:
        role = item.get("role") if isinstance(item.get("role"), str) else ""
        roles.append(role)
        content = item.get("content")
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append((role, part["text"]))
    if not texts:
        raise ValueError("printed a list with no message text in it")
    roots: dict[str, str] = {}
    skills: dict[str, tuple[str, str]] | None = None
    unread = 0
    tags: list[str] = []
    for _, body in texts:
        inside = False
        for line in body.splitlines():
            tag = _TAG.match(line)
            if tag and tag.group(1) not in tags:
                tags.append(tag.group(1))
            root = _ROOT.match(line)
            if root:
                roots[root.group(1)] = root.group(2)
            if line.strip() == _SKILLS_HEADING:
                inside = True
                skills = {} if skills is None else skills
                continue
            if inside and (line.startswith("#") or line.startswith("</")):
                inside = False
            if inside and line.startswith("- "):
                found = _ENTRY.match(line)
                if found:
                    skills.setdefault(found.group(1), (found.group(2), found.group(3)))  # type: ignore[union-attr]
                else:
                    unread += 1
    return PromptInput(tuple(roles), tuple(texts), skills, roots, unread, tuple(tags))


def skipped_lines(*texts: str) -> list[str]:
    """The lines in which Codex says it skipped something it found."""
    return [
        modellist._first_line(line) for text in texts for line in text.splitlines()
        if any(mark in line.lower() for mark in _SKIPPED)
    ]


def reduce_prompt_input(found: PromptInput) -> dict[str, Any]:
    return {
        "message_roles": list(found.roles),
        "tags": list(found.tags),
        "skills_section": found.skills is not None,
        "skill_roots": sorted(found.roots),
        "skills": sorted(found.skills or {}),
        "unread_entry_lines": found.unread,
    }


# --- Reading: the app server's skills list ---------------------------------------

@dataclass(frozen=True)
class Listed:
    name: str
    enabled: bool
    scope: str | None
    path: str | None


@dataclass(frozen=True)
class SkillsList:
    skills: tuple[Listed, ...]
    errors: int
    keys: tuple[str, ...]

    def named(self, name: str) -> list[Listed]:
        return [one for one in self.skills if one.name == name]


def list_requests(cwd: Path) -> list[str]:
    """The lines sent to ``codex app-server``: the handshake, then the one
    request."""
    requests = [
        {"method": "initialize", "id": 0, "params": {"clientInfo": {"name": CLIENT_NAME, "version": "1"}}},
        {"method": "initialized"},
        {"method": "skills/list", "id": LIST_REQUEST_ID, "params": {"cwds": [str(cwd)], "forceReload": True}},
    ]
    return [json.dumps(request, ensure_ascii=True) for request in requests]


def _json_object(line: str) -> dict[str, Any] | None:
    if not line.startswith("{"):
        return None
    try:
        found = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return found if isinstance(found, dict) else None


def is_list_answer(line: str) -> bool:
    found = _json_object(line)
    return found is not None and found.get("id") == LIST_REQUEST_ID and ("result" in found or "error" in found)


def parse_skills_list(lines: Iterable[str]) -> SkillsList:
    """Read the answer to ``skills/list`` out of what the app server
    printed. A ``ValueError`` says why there is none."""
    answer = None
    for line in lines:
        if is_list_answer(line):
            answer = _json_object(line)
    if answer is None:
        raise ValueError("gave no answer to skills/list")
    if "error" in answer:
        error = answer["error"]
        message = error.get("message") if isinstance(error, dict) else None
        raise ValueError("refused skills/list" + (f": {modellist._first_line(message)}" if isinstance(message, str) else ""))
    result = answer.get("result")
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        raise ValueError("answered skills/list with no list in `result.data`")
    listed, errors, keys = [], 0, set()
    for one in data:
        if not isinstance(one, dict) or not isinstance(one.get("skills"), list):
            raise ValueError("answered skills/list with an entry that has no `skills` list")
        errors += len(one["errors"]) if isinstance(one.get("errors"), list) else 0
        for skill in one["skills"]:
            if not isinstance(skill, dict) or not isinstance(skill.get("name"), str):
                raise ValueError("answered skills/list with a skill that has no name")
            keys.update(skill)
            listed.append(Listed(
                skill["name"], skill.get("enabled") is not False,
                skill.get("scope") if isinstance(skill.get("scope"), str) else None,
                skill.get("path") if isinstance(skill.get("path"), str) else None,
            ))
    return SkillsList(tuple(listed), errors, tuple(sorted(keys)))


def reduce_skills_list(found: SkillsList) -> dict[str, Any]:
    return {
        "skill_keys": list(found.keys),
        "load_errors": found.errors,
        "skills": [{"name": one.name, "enabled": one.enabled, "scope": one.scope} for one in found.skills],
    }


# --- Reading: Claude Code's first event ------------------------------------------

@dataclass(frozen=True)
class Listing:
    """The ``system/init`` event, reduced: the names of its keys, and for
    each key that holds a list of names, the names."""

    keys: tuple[str, ...]
    lists: dict[str, tuple[str, ...]]

    def names(self, keys: Iterable[str]) -> set[str] | None:
        """The names under those of ``keys`` that the event has, without a
        leading ``/``; None when it has none of them."""
        found = [self.lists[key] for key in keys if key in self.lists]
        if not found:
            return None
        return {name.removeprefix("/") for names in found for name in names}

    def has(self, keys: Iterable[str]) -> list[str]:
        return [key for key in keys if key in self.lists]


def claude_init(line: str) -> dict[str, Any] | None:
    """The event, when ``line`` is the ``system/init`` line of a stream."""
    found = _json_object(line)
    if found is not None and found.get("type") == "system" and found.get("subtype") == "init":
        return found
    return None


def _names(value: Any) -> tuple[str, ...] | None:
    """The names of a list of strings, or of objects with a ``name``; None
    for anything else. A string that is no name (a sentence, a path of
    several lines) makes the list no list of names."""
    if not isinstance(value, list):
        return None
    found = []
    for one in value:
        name = one if isinstance(one, str) else one.get("name") if isinstance(one, dict) else None
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            return None
        found.append(name)
    return tuple(found)


def listing_of(event: dict[str, Any]) -> Listing:
    lists = {}
    for key, value in event.items():
        names = _names(value)
        if names is not None:
            lists[key] = names
    return Listing(tuple(sorted(event)), lists)


def reduce_listing(found: Listing) -> dict[str, Any]:
    return {"keys": list(found.keys), "lists": {key: list(names) for key, names in sorted(found.lists.items())}}


# --- Reading: Codex's event stream -----------------------------------------------

@dataclass(frozen=True)
class Events:
    """``codex exec --json``, as far as it is read. ``spawn`` is every
    string of the spawn tool's definition, where the stream holds one."""

    types: tuple[str, ...]
    keys: dict[str, tuple[str, ...]]
    tools: tuple[str, ...]
    spawn: tuple[str, ...] | None
    spawn_paths: tuple[str, ...]

    def names(self, wanted: Iterable[str]) -> set[str]:
        """Those of ``wanted`` that the spawn tool's text holds as whole
        names."""
        found = set()
        for name in wanted:
            whole = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(name) + r"(?![A-Za-z0-9_-])")
            if any(whole.search(text) for text in self.spawn or ()):
                found.add(name)
        return found


def _is_definition(value: dict[str, Any]) -> bool:
    return (isinstance(value.get("name"), str) and ("description" in value or "parameters" in value)
            and not _CALL_KEYS & set(value))


def _strings(value: Any, path: str, texts: list[str], where: list[str]) -> None:
    if isinstance(value, str):
        texts.append(value)
        where.append(path)
    elif isinstance(value, dict):
        for key, inner in value.items():
            _strings(inner, f"{path}.{key}" if path else str(key), texts, where)
    elif isinstance(value, list):
        for inner in value:
            _strings(inner, path + "[]", texts, where)


def _definitions(value: Any, depth: int = 0) -> Iterable[dict[str, Any]]:
    if depth > 40:
        return
    if isinstance(value, dict):
        if _is_definition(value):
            yield value
            return
        if _CALL_KEYS & set(value):
            return  # a tool call and what came of it: a model's doing
        for inner in value.values():
            yield from _definitions(inner, depth + 1)
    elif isinstance(value, list):
        for inner in value:
            yield from _definitions(inner, depth + 1)


def parse_events(lines: Iterable[str]) -> Events:
    """Read what ``codex exec --json`` printed. A ``ValueError`` when no
    line is a JSON event."""
    types: list[str] = []
    keys: dict[str, set[str]] = {}
    tools: list[str] = []
    spawn: list[str] | None = None
    where: list[str] = []
    for line in lines:
        event = _json_object(line)
        if event is None:
            continue
        kind = event.get("type") if isinstance(event.get("type"), str) else "(no type)"
        item = event.get("item")
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            kind = f"{kind}/{item['type']}"
        if kind not in types:
            types.append(kind)
        keys.setdefault(kind, set()).update(event)
        for found in _definitions(event):
            if found["name"] not in tools:
                tools.append(found["name"])
            if found["name"] == SPAWN_TOOL:
                spawn = [] if spawn is None else spawn
                _strings({key: value for key, value in found.items() if key != "name"}, "", spawn, where)
    if not types:
        raise ValueError("printed no JSON event")
    return Events(
        tuple(types), {kind: tuple(sorted(found)) for kind, found in keys.items()}, tuple(tools),
        None if spawn is None else tuple(spawn), tuple(dict.fromkeys(where)),
    )


def reduce_events(found: Events, wanted: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "event_types": list(found.types),
        "event_keys": {kind: list(keys) for kind, keys in found.keys.items()},
        "tool_definitions": list(found.tools),
        "spawn_tool_found": found.spawn is not None,
        "spawn_tool_text_at": list(found.spawn_paths),
        "agent_names_found": sorted(found.names(wanted)),
    }


# --- The items ---------------------------------------------------------------------

@dataclass
class Item:
    """One thing setup installed for a provider. ``name`` is the name the
    provider knows it by."""

    provider: str
    kind: str
    name: str
    path: Path
    invoke_only: bool = False
    line: str | None = None      # a starting role on Codex: the line its instructions begin with
    state: str | None = None
    why: str = ""
    fault: str | None = None     # the file cannot be loaded
    absent: bool = False
    unchecked: bool = False      # the provider's program is not on PATH

    def settle(self, state: str, why: str) -> None:
        self.state, self.why = state, why


def expected(context: Any, provider: homes.Provider) -> list[Item]:
    """What ``render`` installs for ``provider`` in the home, from the
    sources and settings as they are now. A ``SetupError`` where the
    sources do not allow it."""
    where = context.user_level
    name = provider.name
    skills = provider.place(homes.SKILLS).path
    agents = provider.place(homes.AGENTS).path
    off = definitions.disabled(where, context.sources.skills)
    items = [
        Item(name, SKILL, skill.name, skills / skill.name, invoke_only=skill.invoke_only)
        for skill in context.sources.skills.values()
        if name in skill.providers and not skill.own_setup and skill.name not in off
    ]
    items += [
        Item(name, LOADED, made.role, skills / made.role, invoke_only=True)
        for made in entry.skills(where, [name], context.homes) if made.name.endswith(entry.SKILL_FILE)
    ]
    items += [
        Item(name, DEFINITION, definitions.codex_name(made.definition) if name == homes.CODEX else made.definition,
             agents / made.name)
        for made in definitions.build(where, [name], context.homes)
    ]
    if name == homes.CODEX:
        items += [
            Item(name, START, made.role, provider.place(homes.PROFILES).path / made.name)
            for made in entry.profiles(where, [name], context.homes)
        ]
    else:
        items += [
            Item(name, START, role, agents / definitions.file_name(name, role))
            for role in entry.start_roles(where)
        ]
    return items


def _regular_file(path: Path) -> bytes:
    seen = fsio.look(path)
    if seen.kind != fsio.FILE:
        raise SetupError(f"not a regular file: a {seen.kind} is there")
    return fsio.read_bytes(path)


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SetupError("is not UTF-8 text") from None


def _toml(data: bytes, required: Iterable[str]) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(_text(data))
    except (tomllib.TOMLDecodeError, RecursionError):
        raise SetupError("is not valid TOML") from None
    lacking = [key for key in required if not isinstance(parsed.get(key), str) or not parsed[key].strip()]
    if lacking:
        raise SetupError(f"has no {' or '.join(lacking)}: Codex needs each as a string that is not empty")
    return parsed


def _frontmatter(data: bytes, required: Iterable[str]) -> dict[str, str]:
    fields, faults = validate.parse_frontmatter(_text(data))
    if fields is None:
        raise SetupError("has no frontmatter that can be read")
    found = {key: one.value for key, one in fields.items()}
    lacking = [key for key in required if not isinstance(found.get(key), str) or not found[key].strip()]
    if lacking:
        raise SetupError(f"has no {' or '.join(lacking)} in its frontmatter")
    return found


def structure(item: Item) -> None:
    """Look at the item's file as the provider must be able to: set
    ``absent`` where nothing is installed, ``fault`` where what is there
    cannot be loaded, and ``line`` for a Codex profile."""
    try:
        if fsio.look(item.path).kind == fsio.ABSENT:
            item.absent = True
            return
        if item.kind in (SKILL, LOADED):
            file = item.path / validate.SKILL_FILE
            if not os.path.isfile(file):
                raise SetupError(f"has no {validate.SKILL_FILE} that is a file")
            _frontmatter(fsio.read_bytes(Path(os.path.realpath(file))), ("name", "description"))
        elif item.provider == homes.CODEX and item.kind == DEFINITION:
            parsed = _toml(_regular_file(item.path), ("name", "description", "developer_instructions"))
            if parsed["name"] != item.name:
                raise SetupError(f"names the agent {parsed['name']}, and setup installed it as {item.name}")
        elif item.provider == homes.CODEX:
            parsed = _toml(_regular_file(item.path), ("developer_instructions",))
            item.line = next((line for line in parsed["developer_instructions"].splitlines() if line.strip()), None)
        else:
            found = _frontmatter(_regular_file(item.path), ("name", "description"))
            if found["name"] != item.name:
                raise SetupError(f"names the agent {found['name']}, and setup installed it as {item.name}")
    except SetupError as exc:
        item.fault = exc.lines[0].removeprefix(f"{item.path}: ")
    except (OSError, ValueError) as exc:
        item.fault = f"cannot be read: {paths.reason(exc)}"


# --- The probes --------------------------------------------------------------------

class Saver:
    """Writes the reduced form of each probe into a directory; see the
    module. With no directory it keeps nothing."""

    def __init__(self, directory: str | None) -> None:
        # The path as ``save_directory`` settled it: absolute, with no
        # ``..`` left for the system to read otherwise than the text does.
        self.directory = None if not directory else Path(os.path.realpath(os.path.expanduser(directory)))
        self.saved: list[str] = []

    def save(self, name: str, args: Iterable[str], ran: Ran, reduced: dict[str, Any] | None,
             unread: str | None = None) -> None:
        if self.directory is None:
            return
        # The prompts are fixed texts of this module and are left out all the same.
        shown = ["<prompt>" if one in (OFFLINE_PROMPT, SESSION_PROMPT) else one for one in args]
        # Why nothing was read, without what the program itself said.
        why = None if unread is None else unread.split(":")[0]
        data = {"probe": name, "arguments": shown, "outcome": ran.outcome(), "unread": why, "listing": reduced}
        try:
            # The directory the user named is the one place this may write,
            # and ``fsio`` refuses it where its real place is in the clone.
            with fsio.confined([_existing(self.directory)]):
                fsio.make_directories(self.directory)
                file = self.directory / f"{name}.json"
                fsio.atomic_write(
                    file, (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                )
        except SetupError as exc:
            raise SetupError(f"{self.directory}: the probe output cannot be saved: {exc.lines[0]}") from None
        self.saved.append(f"{name}.json")


def save_directory(text: str, clone: Path) -> str:
    """``--save-probe DIR`` as it may be used: a path with no control
    character, outside the clone setup runs from."""
    from . import locations

    locations.path_argument(text, SAVE_OPTION)
    # Every link is followed first and ``..`` taken out after: ``link/../x``
    # is where the system finds it, not where the text seems to say.
    real = os.path.realpath(os.path.expanduser(text))
    # Asked of the directory it will be made in, where it is not there yet.
    with fsio.confined([_existing(Path(real))], [clone]):
        refused = fsio.admits(os.path.join(real, "probe.json"))
    if paths.inside(real, os.path.realpath(clone)) or (refused is not None and "never writes to" in refused):
        raise SetupError(f"{SAVE_OPTION}: {text}: inside the clone setup runs from; setup writes nothing there")
    return real


def _existing(directory: Path) -> Path:
    """``directory``, or the nearest directory above it that exists: the
    place a directory that is still to be made is made in."""
    probe = Path(directory)
    while not os.path.isdir(probe) and probe.parent != probe:
        probe = probe.parent
    return probe


def child_environment(context: Any) -> dict[str, str]:
    """The environment a provider is started in; see the module."""
    found = context.homes
    if not found.scratch:
        environ = dict(context.environ)
        environ.pop(fsio.STOP_VARIABLE, None)
        return environ
    return homes.child_environment(found)


def working_directory(context: Any) -> Path:
    return context.homes.project or context.homes.home


def _shown(program: str, args: Iterable[str]) -> str:
    words = ["<prompt>" if one in (OFFLINE_PROMPT, SESSION_PROMPT) else one for one in args]
    return "`" + " ".join([program, *words]) + "`"


def _set(items: Iterable[Item], state: str, why: str) -> None:
    for item in items:
        if item.state is None:
            item.settle(state, why)


def probe_codex(context: Any, provider: homes.Provider, items: list[Item], notes: list[tuple[str, str]],
                saver: Saver, prove: bool) -> None:
    program = provider.program_file
    environ, cwd = child_environment(context), working_directory(context)
    skills = [item for item in items if item.kind in (SKILL, LOADED)]
    asked = _shown("codex", ("debug", "prompt-input", OFFLINE_PROMPT))
    server = "`skills/list` of " + _shown("codex", APP_SERVER_ARGS)

    visible: PromptInput | None = None
    visible_fault = listed_fault = "was not started: nothing installed needs it"
    listed: SkillsList | None = None
    if skills:
        args = ("debug", "prompt-input", OFFLINE_PROMPT)
        ran = start((program, *args), environ, cwd, OFFLINE_TIMEOUT)
        visible_fault = _failed(ran)
        if visible_fault is None:
            try:
                visible = parse_prompt_input(ran.text)
                if visible.skills is None:
                    visible, visible_fault = None, "printed a prompt with no skills section"
            except ValueError as exc:
                visible_fault = str(exc)
        notes.extend(("warning", f"codex: {asked} says: {line}") for line in skipped_lines(ran.text, ran.said))
        saver.save("codex-prompt-input", args, ran, None if visible is None else reduce_prompt_input(visible), visible_fault)

        ran = start((program, *APP_SERVER_ARGS), environ, cwd, OFFLINE_TIMEOUT, send=list_requests(cwd),
                    until=is_list_answer)
        listed_fault = _failed(ran, nothing=False)
        if listed_fault is None:
            try:
                listed = parse_skills_list(ran.lines)
            except ValueError as exc:
                listed_fault = str(exc)
        if listed is not None and listed.errors:
            notes.append(("warning", f"codex: {server} reports {listed.errors} skills that it could not load"))
        saver.save("codex-skills-list", APP_SERVER_ARGS, ran, None if listed is None else reduce_skills_list(listed),
                   listed_fault)

    for item in skills:
        in_prompt = visible is not None and item.name in (visible.skills or {})
        entries = [] if listed is None else listed.named(item.name)
        enabled = any(one.enabled for one in entries)
        if in_prompt:
            item.settle(PROVEN, f"in the model-visible skills list of {asked}")
        elif enabled and (item.invoke_only or visible is None):
            by_design = "; not in the model-visible list by design (invoke-only)" if item.invoke_only else ""
            item.settle(PROVEN, f"listed by {server}{by_design}")
        elif enabled:
            item.settle(MISSING, f"not in the model-visible skills list of {asked}, though {server} has it")
        elif entries:
            item.settle(MISSING, f"{server} lists it as disabled")
        elif item.invoke_only and listed is None:
            item.settle(UNPROVEN, (
                f"not provable offline: invoke-only, so absent from the model-visible list of {asked} by design; "
                f"{server} would list it, and that {listed_fault}"
            ))
        elif visible is None and listed is None:
            item.settle(UNPROVEN, f"{asked} {visible_fault}; {server} {listed_fault}")
        elif item.invoke_only or visible is None:
            item.settle(MISSING, f"{server} does not list it")
        else:
            item.settle(MISSING, f"not in the model-visible skills list of {asked}" + (
                "" if listed is None else f", nor in {server}"
            ))

    for item in items:
        if item.kind != START:
            continue
        args = ("--profile", item.name, "debug", "prompt-input", OFFLINE_PROMPT)
        shown = _shown("codex", args)
        ran = start((program, *args), environ, cwd, OFFLINE_TIMEOUT)
        fault, found = _failed(ran), None
        if fault is None:
            try:
                found = parse_prompt_input(ran.text)
            except ValueError as exc:
                fault = str(exc)
        if found is None:
            item.settle(UNPROVEN, f"{shown} {fault}")
        elif item.line is not None and found.shows(item.line):
            item.settle(PROVEN, f"{shown} shows the role's instructions")
        else:
            item.settle(MISSING, (
                f"{shown} does not show the role's instructions (the line they begin with is in no developer "
                "message); Codex takes a profile it cannot find for no profile, without a word"
            ))
        saver.save(f"codex-profile-{item.name}", args, ran,
                   None if found is None else {**reduce_prompt_input(found),
                                               "instructions_shown": item.state == PROVEN}, fault)

    agents = [item for item in items if item.kind == DEFINITION]
    if not agents:
        return
    if not prove:
        _set(agents, UNPROVEN, (
            "no offline output of Codex lists custom agents: the prompt input holds no tool text and the app "
            f"server has no request for them; `doctor {PROVE_OPTION}` starts one session and looks for the agent "
            "names in the spawn tool's text"
        ))
        return
    shown = _shown("codex", CODEX_SESSION_ARGS)
    ran = start((program, *CODEX_SESSION_ARGS), environ, cwd, SESSION_TIMEOUT)
    fault, events = _failed(ran), None
    if fault is None or ran.lines:
        try:
            events = parse_events(ran.lines)
        except ValueError as exc:
            fault = fault or str(exc)
    wanted = [item.name for item in agents]
    saver.save("codex-exec-events", CODEX_SESSION_ARGS, ran, None if events is None else reduce_events(events, wanted),
               fault)
    if events is None:
        _set(agents, UNPROVEN, f"{shown} {fault}")
    elif events.spawn is None:
        _set(agents, UNPROVEN, (
            f"{shown} {f'{fault}, and ' if fault else ''}printed no definition of the {SPAWN_TOOL} tool; its "
            f"events were: {', '.join(events.types)}. No output of Codex that setup can read lists custom agents"
        ))
    else:
        found = events.names(wanted)
        for item in agents:
            if item.name in found:
                item.settle(PROVEN, f"named in the {SPAWN_TOOL} tool's text in the event stream of {shown}")
            else:
                item.settle(MISSING, f"not named in the {SPAWN_TOOL} tool's text in the event stream of {shown}")


def probe_claude(context: Any, provider: homes.Provider, items: list[Item], notes: list[tuple[str, str]],
                 saver: Saver, prove: bool) -> None:
    if not prove:
        _set(items, UNPROVEN, (
            "Claude Code has no command that lists agents or skills without a session; "
            f"`doctor {PROVE_OPTION}` starts one and reads its first event"
        ))
        return
    shown = _shown("claude", CLAUDE_SESSION_ARGS)
    ran = start((provider.program_file, *CLAUDE_SESSION_ARGS), child_environment(context), working_directory(context),
                SESSION_TIMEOUT, until=lambda line: claude_init(line) is not None)
    event = next((found for found in map(claude_init, ran.lines) if found is not None), None)
    if event is None:
        fault = _failed(ran) or "printed no `system/init` event"
        saver.save("claude-code-init", CLAUDE_SESSION_ARGS, ran, None, fault)
        _set(items, UNPROVEN, f"{shown} {fault}")
        return
    listing = listing_of(event)
    saver.save("claude-code-init", CLAUDE_SESSION_ARGS, ran, reduce_listing(listing))
    first = f"the `system/init` event of {shown}"
    seen = f"its keys were: {', '.join(listing.keys)}"
    agents, skills = listing.names(AGENT_KEYS), listing.names(SKILL_KEYS)
    for item in items:
        if item.state is not None:
            continue
        if item.kind in (DEFINITION, START):
            if agents is None:
                item.settle(UNPROVEN, f"{first} has no key that lists agents ({' or '.join(AGENT_KEYS)}); {seen}")
            elif item.name in agents:
                item.settle(PROVEN, f"listed under `{'`, `'.join(listing.has(AGENT_KEYS))}` in {first}")
            else:
                item.settle(MISSING, f"not listed under `{'`, `'.join(listing.has(AGENT_KEYS))}` in {first}")
        elif skills is None:
            item.settle(UNPROVEN, f"{first} has no key that lists skills ({' or '.join(SKILL_KEYS)}); {seen}")
        elif item.name in skills:
            under = [key for key in listing.has(SKILL_KEYS) if item.name in {n.removeprefix("/") for n in listing.lists[key]}]
            item.settle(PROVEN, f"listed under `{'`, `'.join(under)}` in {first}")
        elif item.invoke_only:
            item.settle(UNPROVEN, (
                f"not listed under `{'`, `'.join(listing.has(SKILL_KEYS))}` in {first}; it is invoke-only, and no "
                "document says such a skill is listed there"
            ))
        else:
            item.settle(MISSING, f"not listed under `{'`, `'.join(listing.has(SKILL_KEYS))}` in {first}")


PROBES = {homes.CODEX: probe_codex, homes.CLAUDE_CODE: probe_claude}


# --- The check ---------------------------------------------------------------------

PROVE_OPTION = "--prove-discovery"
SAVE_OPTION = "--save-probe"


def configure(parser: Any) -> None:
    parser.add_argument(
        PROVE_OPTION, action="store_true",
        help="the check `discovery` also starts the session probes: one `claude -p` session, ended at its first "
        "event, and one `codex exec` session. EACH STARTS A SESSION WITH A MODEL AND SPENDS QUOTA. Without it "
        "the check starts offline commands only",
    )
    parser.add_argument(
        SAVE_OPTION, metavar="DIR", default=None,
        help="write what each probe of the check `discovery` gave into DIR, one JSON file per probe, reduced to "
        "names: keys, event types and the lists of skills, agents, commands and tools. No description, prompt, "
        "model output, path or id is saved. The one thing doctor writes",
    )


@dataclass
class Survey:
    items: list[Item]
    notes: list[tuple[str, str]]     # (severity, line)
    saved: list[str]

    def count(self, state: str) -> int:
        return sum(1 for item in self.items if item.state == state)


def survey(context: Any) -> Survey:
    """Every item of every installed provider with its state; see the
    module. A ``SetupError`` where the sources do not allow a plan."""
    prove = bool(context.option("prove_discovery", False))
    save = context.option("save_probe")
    if save is not None:
        save = save_directory(save, context.homes.clone)
    saver = Saver(save)
    found = Survey([], [], saver.saved)
    for provider in context.installed():
        if provider.name not in PROBES:
            continue
        items = expected(context, provider)
        for item in items:
            structure(item)
        found.items.extend(items)
        ready = [item for item in items if not item.absent and item.fault is None]
        if not ready:
            continue
        if provider.program_file is None:
            for item in ready:
                item.unchecked = True
            continue
        PROBES[provider.name](context, provider, ready, found.notes, saver, prove)
    return found


def _plural(count: int, kind: str) -> str:
    return f"{count} {kind}{'' if count == 1 else 's'}"


def check_discovery(context: Any) -> list[Any]:
    """Whether each provider lists what setup installed for it (R6.3)."""
    from . import doctor  # at the call: ``doctor`` imports this module for its registry

    if not context.sources.ok:
        return [doctor.info(doctor.NOT_PLANNED)]
    found = survey(context)
    if not found.items:
        return [doctor.info("no provider that setup installs for is here; nothing to check")]
    findings = []
    make = {doctor.ERROR: doctor.error, doctor.WARNING: doctor.warning, doctor.INFO: doctor.info}
    findings.extend(make[severity](line) for severity, line in found.notes)

    absent = [item for item in found.items if item.absent]
    if len(absent) == len(found.items):
        return [*findings, doctor.info(
            f"nothing that setup installs is in this home ({_plural(len(absent), 'item')}); the check `missing` "
            "says what render would create"
        )]
    for item in found.items:
        if item.fault is not None:
            findings.append(doctor.error(
                f"{item.provider}: the {item.kind} {item.name} cannot be loaded: {item.path}: {item.fault}", item.path,
            ))
    # Unproven is a warning only where proof was asked for and not had; on
    # a plain run it is what was to be expected, said in one line.
    prove = bool(context.option("prove_discovery", False))
    severity = {PROVEN: doctor.fine, UNPROVEN: doctor.warning, MISSING: doctor.error}
    groups: dict[tuple[str, str, str, str], list[str]] = {}
    for item in found.items:
        if item.state is not None:
            groups.setdefault((item.provider, item.state, item.kind, item.why), []).append(item.name)
    unproven: list[str] = []
    for (provider, state, kind, why), names in groups.items():
        what = f"the {kind} {names[0]}" if len(names) == 1 else f"{_plural(len(names), kind)} ({', '.join(names)})"
        line = f"{provider}: {state}: {what}: {why}"
        if state == UNPROVEN and not prove:
            unproven.append(line)
        else:
            findings.append(severity[state](line, f"{provider}: {state}"))
    if unproven:
        findings.append(doctor.info(
            f"{_plural(found.count(UNPROVEN), 'item')} not proven on this run, which started no session: "
            + "; ".join(unproven), UNPROVEN,
        ))
    for provider in dict.fromkeys(item.provider for item in found.items if item.unchecked):
        names = [f"{item.kind} {item.name}" for item in found.items if item.unchecked and item.provider == provider]
        program = context.homes.provider(provider).program
        findings.append(doctor.info(
            f"{provider}: the program `{program}` is not on PATH, so nothing can be asked of it; not checked: "
            f"{', '.join(names)}"
        ))
    if absent:
        findings.append(doctor.info(
            "not in this home, so not checked (the check `missing` is about these): "
            + ", ".join(f"{item.provider} {item.kind} {item.name}" for item in absent)
        ))
    if found.saved:
        findings.append(doctor.info(
            f"saved, reduced to names, in {context.option('save_probe')}: {', '.join(found.saved)}"
        ))
    checked = [item for item in found.items if item.state is not None]
    if checked:
        counts = ", ".join(f"{found.count(state)} {state}" for state in STATES)
        more = "" if context.option("prove_discovery", False) or not found.count(UNPROVEN) else (
            f"; `doctor {PROVE_OPTION}` starts one session for each provider, which spends quota, to prove more"
        )
        findings.append(doctor.info(f"{_plural(len(checked), 'item')} asked of the providers: {counts}{more}"))
    return findings
