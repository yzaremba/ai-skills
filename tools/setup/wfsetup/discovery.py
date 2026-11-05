"""Whether a provider itself lists what setup installed: the check ``discovery``.

How ``doctor`` uses it

    Check("discovery", discovery.check_discovery, "...")

    doctor                                  # offline commands only: no session is started

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
    unproven   no provider output that was read could list it. That is
               ``info``, and all of it is one line: the items by provider,
               each with why. Never an error.
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
    lists custom agents. They are unproven.

  Claude Code, offline: nothing. ``claude agents`` lists background
  sessions, ``claude doctor`` prints "installation and settings
  diagnostics", and ``claude plugin validate <dir>`` validates files and
  names none of them (code.claude.com/docs/en/cli-reference). Every item
  is unproven. Setup starts no session with a model, so it spends no quota.

Where the commands run
    The working directory is the project (``--project``), else the home.
    The environment is ``homes.child_environment``'s, as for every program
    setup starts: the caller's, and for a scratch home (``--home``) it
    also points the provider at that home: ``HOME`` (and ``USERPROFILE``
    on Windows), ``CODEX_HOME`` and ``CLAUDE_CONFIG_DIR``. For the real
    home nothing is set: the provider finds its home as it always does.

    A provider's program may write state of its own into its home when it
    starts (Codex: its bundled skills, an installation id). Setup writes
    nothing there.
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

from . import definitions, entry, fsio, homes, modellist, paths, settings, validate
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
# How long a program that was told to stop is waited for before it is ended.
STOP_GRACE = 10.0

MAX_OUTPUT = modellist.MAX_OUTPUT

# The user prompt ``codex debug prompt-input`` appends. Nothing is sent.
OFFLINE_PROMPT = "workflow setup discovery check"

APP_SERVER_ARGS = ("app-server", "--listen", "stdio://")
CLIENT_NAME = "workflow-setup-doctor"
LIST_REQUEST_ID = 1

_ROOT = re.compile(r"^- `(r\d+)` = `([^`]+)`\s*$")
_ENTRY = re.compile(r"^- (\S+): .*\(file: (r\d+)/([^)]*SKILL\.md)\)\s*$")
_SKILLS_HEADING = "### Available skills"
_SKILLS_TAG = "skills_instructions"
_TAG = re.compile(r"^<([A-Za-z_][A-Za-z0-9_ ]*)>")
_SKIPPED = ("skipped loading", "ignoring invalid")


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
    setting = settings.resolve(where, ("roles",)).get("roles.enabled")
    installed = definitions.home_selection(where, context.sources.skills, setting is None or setting.value is not False).units
    items = [
        Item(name, SKILL, skill.name, skills / skill.name, invoke_only=skill.invoke_only)
        for skill in context.sources.skills.values()
        if name in skill.providers and not skill.own_setup and skill.name in installed
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
    words = ["<prompt>" if one == OFFLINE_PROMPT else one for one in args]
    return "`" + " ".join([program, *words]) + "`"


def _set(items: Iterable[Item], state: str, why: str) -> None:
    for item in items:
        if item.state is None:
            item.settle(state, why)


def probe_codex(context: Any, provider: homes.Provider, items: list[Item], notes: list[tuple[str, str]]) -> None:
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

    _set([item for item in items if item.kind == DEFINITION], UNPROVEN, (
        "no offline output of Codex lists custom agents: the prompt input holds no tool text and the app "
        "server has no request for them"
    ))


def probe_claude(context: Any, provider: homes.Provider, items: list[Item], notes: list[tuple[str, str]]) -> None:
    _set(items, UNPROVEN, "Claude Code has no command that lists agents or skills without a session")


PROBES = {homes.CODEX: probe_codex, homes.CLAUDE_CODE: probe_claude}


# --- The check ---------------------------------------------------------------------

@dataclass
class Survey:
    items: list[Item]
    notes: list[tuple[str, str]]     # (severity, line)

    def count(self, state: str) -> int:
        return sum(1 for item in self.items if item.state == state)


def survey(context: Any) -> Survey:
    """Every item of every installed provider with its state; see the
    module. A ``SetupError`` where the sources do not allow a plan."""
    found = Survey([], [])
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
        PROBES[provider.name](context, provider, ready, found.notes)
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
    # Unproven is what was to be expected of an offline check, said in one line.
    severity = {PROVEN: doctor.fine, MISSING: doctor.error}
    groups: dict[tuple[str, str, str, str], list[str]] = {}
    for item in found.items:
        if item.state is not None:
            groups.setdefault((item.provider, item.state, item.kind, item.why), []).append(item.name)
    unproven: list[str] = []
    for (provider, state, kind, why), names in groups.items():
        what = f"the {kind} {names[0]}" if len(names) == 1 else f"{_plural(len(names), kind)} ({', '.join(names)})"
        line = f"{provider}: {state}: {what}: {why}"
        if state == UNPROVEN:
            unproven.append(line)
        else:
            findings.append(severity[state](line, f"{provider}: {state}"))
    if unproven:
        findings.append(doctor.info(
            f"{_plural(found.count(UNPROVEN), 'item')} not proven offline: "
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
    checked = [item for item in found.items if item.state is not None]
    if checked:
        counts = ", ".join(f"{found.count(state)} {state}" for state in STATES)
        findings.append(doctor.info(f"{_plural(len(checked), 'item')} asked of the providers: {counts}"))
    return findings
