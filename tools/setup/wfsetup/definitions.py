"""A role's definition for one provider: its text, and what it was made from.

How it is used

    built = definitions.build(where, ["claude-code", "codex"])   # nothing is written
    for found in built:
        found.provider, found.definition, found.name     # "codex", "coder-hard", "coder-hard.toml"
        found.text, found.size, found.sha256             # the file, whole
        found.inputs                                     # the digest the record keeps
        found.model, found.effort

    definitions.digests(where, providers)    # {(provider, definition): inputs}; what doctor compares
    definitions.user_level(where)            # the same locations without the project
    definitions.materials(where, providers, select)   # what a definition is made from, before a format

``materials`` is the half of ``build`` that reads: for each provider and each
role ``select`` names for it, the body parts (``ROLE.md``, the includes, the
binding rows, the provider's action notes), the source texts, and the model
and effort the settings of ``where`` resolve. ``build`` gives each one a
file format. ``entry`` gives the same material the formats of a session's
entry points, so a loaded role and a starting role hold the text of the
role's definition, byte for byte.

``build`` reads the clone and the settings of ``where`` and returns every
definition of the providers asked for. It knows no home and no directory:
the caller decides where a file goes. So the same call gives the user-level
definitions (``where`` without a project, see ``user_level``) and, with a
project, what that project's settings make of them; the two differ only in
the roles the project's settings change.

Which definitions a provider gets (``providers_of``)
    claude-code   every role with ``entry.dispatch`` or ``entry.start``: a
                  dispatched role is an agent file, and so is the role a
                  session starts as (``claude --agent <role>``).
    codex         every role with ``entry.dispatch``. A starting role is not
                  an agent file there but the session's own instructions, and
                  a loaded role is a skill on both providers; neither is made
                  here.
    A role with ``[profile.hard]`` gives a second definition, ``<role>-hard``,
    wherever it gives the first. A role with no such entry gives nothing.

The file (provider facts read on 2026-10-05)
    claude-code   ``<definition>.md``: frontmatter ``name``, ``description``,
                  ``model``, ``effort`` and ``disallowedTools``, then the body
                  (code.claude.com/docs/en/sub-agents: ``tools`` "Inherits
                  every tool available to subagents if omitted";
                  ``disallowedTools`` "Tools to deny, removed from inherited
                  or specified list"). There is never a ``tools`` line. The
                  description is always a double-quoted YAML string.
    codex         ``<definition>.toml``: ``name`` (underscores for hyphens),
                  ``description``, ``model``, ``model_reasoning_effort``,
                  ``sandbox_mode`` and ``developer_instructions``
                  (learn.chatgpt.com/docs/agent-configuration/subagents:
                  "Codex identifies the custom agent by its `name` field").
                  The text is parsed again with ``tomllib`` before it is
                  returned.
    ``effort`` and ``model_reasoning_effort`` are left out for a model that
    takes no effort setting.

Limits (``role.toml`` ``[limits]``)
    edits = false      claude-code denies ``EDIT_TOOLS``; codex asks for
                       ``sandbox_mode = "read-only"``, which costs nothing
                       where Codex ignores it.
    commands = false   claude-code denies ``COMMAND_TOOLS``, which closes the
                       other way to change a file. Codex has no key for it.
    dispatches = []    claude-code denies ``DISPATCH_TOOLS``: the tool that
                       spawns one agent and the one that runs a script
                       spawning many. Codex has no key
                       for it. A list that is not empty stays an instruction
                       on both: the ``Agent(a, b)`` form is an allowlist only
                       for a main-thread agent and needs a ``tools`` line.
    What a provider cannot enforce stays in the role's text.

The body, the same on both providers
    the notice, ``ROLE.md``, its includes in ``role.toml``'s order, the
    role's rows of ``roles/bindings.toml`` as the section "Your bindings",
    and the provider's ``actions.md``; joined by ``roles.join_text``, the
    join whose result source validation measures. The notice says the file
    is generated and names its sources by their paths in the repository: an
    HTML comment after the frontmatter on Claude Code; on Codex comment
    lines at the head of the file and one plain line at the head of the
    instructions (``notice_inline``). The hard definition has the rows of its role.

Nothing in a definition is a path of one machine: the sources hold none
(source validation), and nothing here adds one.

The inputs digest (``Generated.inputs``)
    ``INPUTS_SCHEME`` and the SHA-256 of a fixed JSON form of: the scheme,
    the provider, the definition and its role; the hash of each source file
    by its path in the clone (``ROLE.md``, ``role.toml``, each include, the
    provider's ``actions.md``), each taken of the text as ``roles.join_text``
    cleans it, so a CRLF checkout gives the same hash; the role's binding
    rows; the model and the effort. The title, the description, the limits
    and the entry flags are in ``role.toml``. The digest changes when any of
    these changes and not otherwise: another role's files, its rows, another
    provider's notes or a setting for another definition leave it as it was.
    ``FORMAT`` is part of the scheme; raise it when this module would write
    different text from the same inputs.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import dictionary, paths, profiles, roles, settings, tomlio
from .errors import SetupError
from .locations import Locations

CLAUDE_CODE = "claude-code"
CODEX = "codex"
PROVIDERS = (CLAUDE_CODE, CODEX)

FORMAT = 2
# Every digest ``render`` records starts with "render:"; see ``render``.
INPUTS_SCHEME = f"render:role-definition:{FORMAT}"

# The tools a Claude Code definition denies (code.claude.com/docs/en/tools-reference,
# read 2026-10-05: "Edit: Makes targeted edits to specific files", "Write:
# Creates or overwrites files", "NotebookEdit: Modifies Jupyter notebook
# cells"; "Bash: Executes shell commands in your environment", "PowerShell:
# Executes PowerShell commands natively", "Monitor: Runs a command in the
# background"; "Agent: Spawns a subagent with its own context window";
# "Workflow: Runs a dynamic workflow: a script that orchestrates many
# subagents in the background and returns one consolidated result").
# code.claude.com/docs/en/sub-agents, the same day: a subagent never has
# ``Workflow`` ("The first filter removes these tools, even when listed in
# the tools field"), so denying it matters for a role that is a session's
# main thread (``claude --agent``) and costs nothing elsewhere.
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
COMMAND_TOOLS = ("Bash", "PowerShell", "Monitor")
DISPATCH_TOOLS = ("Agent", "Workflow")

READ_ONLY = "read-only"
BINDINGS_FILE = "bindings.toml"
ACTIONS_FILE = "actions.md"
OWNS = "owns"

# A definition above this many bytes is worth a look; nothing enforces it.
SIZE_FLAG = 16_000

RENDER_COMMAND = "python tools/setup/workflow_setup.py render"

_SUFFIX = {CLAUDE_CODE: ".md", CODEX: ".toml"}
_PLAIN = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")
_YAML_WORDS = frozenset({"true", "false", "yes", "no", "on", "off", "null", "y", "n"})


@dataclass(frozen=True)
class Binding:
    """One row of the binding table."""

    role: str
    skill: str
    stage: str
    part: str
    note: str | None = None


@dataclass(frozen=True)
class Generated:
    """One definition for one provider. ``name`` is the file's name in the
    provider's agents directory; ``sources`` are the files it was made from,
    by their paths in the clone."""

    provider: str
    definition: str
    role: str
    name: str
    text: str
    inputs: str
    model: str
    effort: str | None
    sources: tuple[str, ...] = ()

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Material:
    """What one definition is made from on one provider, before a format:
    ``body`` is the role's text, its includes, its binding rows and the
    provider's action notes, in that order; ``files`` maps each source's
    path in the clone to its text."""

    provider: str
    definition: str
    role: roles.Role
    body: tuple[str, ...]
    files: dict[str, str]
    rows: tuple[Binding, ...]
    model: str
    effort: str | None

    @property
    def limits(self) -> dict[str, Any]:
        limits = self.role.data.get("limits")
        return limits if isinstance(limits, dict) else {}

    def digest(self, scheme: str = "", **more: Any) -> str:
        """The inputs digest of a file made from this material; see
        ``inputs_digest``."""
        return inputs_digest(self.provider, self.definition, self.role.name, self.files, self.rows, self.model,
                             self.effort, scheme=scheme or INPUTS_SCHEME, **more)


def user_level(where: Locations) -> Locations:
    """``where`` without its project: what the definitions of a home are
    made from. A project's settings never reach a home's files."""
    return dataclasses.replace(where, project=None)


def file_name(provider: str, definition: str) -> str:
    return definition + _SUFFIX[provider]


def codex_name(definition: str) -> str:
    """The agent name Codex is given: underscores where the id has hyphens."""
    return definition.replace("-", "_")


def providers_of(role: roles.Role) -> tuple[str, ...]:
    """The providers that get an agent file for ``role``; see the module."""
    entry = role.data.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    dispatch, start = entry.get("dispatch") is True, entry.get("start") is True
    found = []
    if dispatch or start:
        found.append(CLAUDE_CODE)
    if dispatch:
        found.append(CODEX)
    return tuple(found)


def denied_tools(limits: dict[str, Any]) -> tuple[str, ...]:
    """What a Claude Code definition denies for these limits."""
    denied: list[str] = []
    if limits.get("edits") is False:
        denied.extend(EDIT_TOOLS)
    if limits.get("commands") is False:
        denied.extend(COMMAND_TOOLS)
    if limits.get("dispatches") == []:
        denied.extend(DISPATCH_TOOLS)
    return tuple(denied)


def description_of(role: roles.Role, definition: str) -> str:
    """The role's sentence; the hard definition says first what it is for,
    so that a dispatcher choosing by description can tell the two apart."""
    if definition == role.name:
        return role.description
    return f"The {role.title} for steps marked hard. {role.description}"


# --- Reading the sources -------------------------------------------------------

def _read(file: Path, problems: list[str]) -> str | None:
    try:
        if paths.kind(file) != paths.FILE:
            problems.append(f"{file}: missing or not a file; a role definition is made from it")
            return None
        return file.read_bytes().decode("utf-8-sig")
    except SetupError as exc:
        problems.extend(exc.lines)
    except OSError as exc:
        problems.append(f"{file}: cannot be read: {paths.reason(exc)}")
    except UnicodeDecodeError as exc:
        problems.append(f"{file}: is not UTF-8 text (byte {exc.start})")
    return None


def bindings(where: Locations) -> dict[str, tuple[Binding, ...]]:
    """The rows of ``roles/bindings.toml`` by role, in the file's order. A
    row that is not in the format is left out; source validation reports it."""
    data = tomlio.load_if_present(where.roles_dir / BINDINGS_FILE) or {}
    rows = data.get("binding", [])
    found: dict[str, list[Binding]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        values = [row.get(key) for key in ("role", "skill", "stage", "part")]
        if not all(isinstance(value, str) and value.strip() for value in values):
            continue
        note = row.get("note")
        note = " ".join(note.split()) if isinstance(note, str) and note.strip() else None
        found.setdefault(values[0], []).append(Binding(*values, note))
    return {role: tuple(rows) for role, rows in found.items()}


def bindings_section(rows: Iterable[Binding]) -> str:
    """A role's rows as the section its text refers to ("the stage file
    your binding names")."""
    rows = list(rows)
    lines = ["## Your bindings", ""]
    if not rows:
        lines.append(
            "None: no stage file of the process skills is bound to you. Your brief and this role are all "
            "you work from."
        )
        return "\n".join(lines)
    lines.append(
        "Each row binds you to one stage file of a process skill and names your part in that stage. "
        "\"The stage file your binding names\" is the file of the row that covers the work at hand. It is "
        "in the `references/` directory of the installed skill; read it there before you act on it, and "
        "take no part in a stage that has no row here."
    )
    lines.append("")
    for row in rows:
        if row.part == OWNS:
            says = "you do everything the stage file asks of whoever runs the stage."
        else:
            says = "" if row.note else "the part the stage file defines under that name."
        if row.note:
            says = f"{says} {row.note}".strip()
        lines.append(f"- Skill `{row.skill}`, stage file `{row.stage}`, part `{row.part}`: {says}")
    return "\n".join(lines)


# --- The notice ------------------------------------------------------------------

def notice_lines(provider: str, role: str, definition: str) -> list[str]:
    """The notice, one sentence a line. No line holds two hyphens in a row,
    so the lines can stand inside an HTML comment."""
    what = f"the role {role}" if definition == role else f"the definition {definition} of the role {role}"
    return [
        f"Generated by workflow setup for {what}. Do not edit this file.",
        f"Sources, in the skills repository: roles/{role}/ (ROLE.md, role.toml), roles/{roles.SHARED_DIR}/, "
        f"roles/{BINDINGS_FILE}, providers/{provider}/{ACTIONS_FILE}, and the workflow settings.",
        f"To change it, change a source and run `{RENDER_COMMAND}` in that repository.",
        "Setup does not overwrite an edit made here; it reports the file as edited by hand.",
    ]


def notice_inline(role: str) -> str:
    """The notice as the first paragraph of instructions a model reads: one
    line, and nothing a model could take for a task."""
    return (
        f"[This text is generated by workflow setup from roles/{role}/ of the skills repository. It is "
        "not edited by hand.]"
    )


# --- The two formats ---------------------------------------------------------------

def yaml_quoted(text: str) -> str:
    """``text`` as a double-quoted YAML scalar on one line."""
    out = ['"']
    for char in text:
        code = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif char == "\r":
            out.append("\\r")
        elif code < 0x20 or 0x7F <= code <= 0x9F:
            out.append(f"\\x{code:02X}")
        elif code in (0x2028, 0x2029, 0xFEFF):
            out.append(f"\\u{code:04X}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def yaml_scalar(text: str) -> str:
    """``text`` plain where that can only be read as the same string, and
    double-quoted otherwise."""
    if _PLAIN.fullmatch(text) and text.lower() not in _YAML_WORDS:
        return text
    return yaml_quoted(text)


def claude_code_text(fields: dict[str, Any], notice: list[str], body: list[str]) -> str:
    lines = ["---", f"name: {yaml_scalar(fields['name'])}", f"description: {yaml_quoted(fields['description'])}",
             f"model: {yaml_scalar(fields['model'])}"]
    if fields.get("effort") is not None:
        lines.append(f"effort: {yaml_scalar(fields['effort'])}")
    if fields.get("denied"):
        lines.append(f"disallowedTools: {', '.join(fields['denied'])}")
    lines.append("---")
    comment = "\n".join(["<!--", *notice, "-->"])
    return "\n".join(lines) + "\n\n" + roles.join_text([comment, *body])


def codex_text(fields: dict[str, Any], notice: list[str], body: list[str]) -> str:
    data: dict[str, Any] = {
        "name": codex_name(fields["name"]),
        "description": fields["description"],
        "model": fields["model"],
    }
    if fields.get("effort") is not None:
        data["model_reasoning_effort"] = fields["effort"]
    if fields.get("read_only"):
        data["sandbox_mode"] = READ_ONLY
    data["developer_instructions"] = roles.join_text([notice_inline(fields["role"]), *body])
    text = tomlio.dumps(data, header=notice)
    try:
        again = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SetupError(f"the Codex definition {fields['name']}: the generated text is not valid TOML: {exc}") from None
    if again != data:
        raise SetupError(f"the Codex definition {fields['name']}: the generated text does not read back as written")
    return text


# --- The digest --------------------------------------------------------------------

def _text_hash(text: str) -> str:
    return hashlib.sha256(roles.join_text([text]).encode("utf-8")).hexdigest()


def inputs_digest(provider: str, definition: str, role: str, files: dict[str, str], rows: Iterable[Binding],
                  model: str, effort: str | None, *, scheme: str = INPUTS_SCHEME, **more: Any) -> str:
    """The digest of what one definition is made from; see the module.
    ``files`` maps each source's path in the clone to its text. Another
    generator of ``render`` gives a ``scheme`` of its own, and in ``more``
    whatever else its text is made from."""
    form = {
        "scheme": scheme,
        "provider": provider,
        "definition": definition,
        "role": role,
        "files": {name: _text_hash(text) for name, text in files.items()},
        "bindings": [[row.skill, row.stage, row.part, row.note] for row in rows],
        "model": model,
        "effort": effort,
    }
    if more:
        form["more"] = more
    raw = json.dumps(form, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return f"{scheme}:{hashlib.sha256(raw).hexdigest()}"


# --- Building ------------------------------------------------------------------------

def materials(where: Locations, providers: Iterable[str] = PROVIDERS, select: Any = None,
              hard: bool = True) -> list[Material]:
    """What each definition is made from: by provider in the order given,
    then by role, then a role's hard definition after its normal one
    (left out without ``hard``). ``select(role)`` names the providers that
    want the role; it is ``providers_of`` where none is given. Nothing is
    written. Every reason one cannot be made is reported together, as one
    ``SetupError``: a source that cannot be read, a provider that has roles
    to get and no dictionary, a profile that does not resolve."""
    providers = list(providers)
    select = providers_of if select is None else select
    unknown = [name for name in providers if name not in PROVIDERS]
    if unknown:
        raise SetupError(f"{', '.join(unknown)}: setup writes role definitions for {', '.join(PROVIDERS)} only")
    loaded = roles.load_all(where)

    def wanted_definitions(role: roles.Role) -> list[roles.Definition]:
        return [definition for definition in role.definitions if hard or definition.id == role.name]

    wanted = {name: [role for role in loaded.values() if name in select(role)] for name in providers}
    if not any(wanted.values()):
        return []

    problems: list[str] = []
    known = dictionary.files(where)
    for name in providers:
        if wanted[name] and name not in known:
            problems.append(
                f"{name}: no such provider among those with a dictionary ({', '.join(known) or 'none'}): "
                f"providers/{name}/{dictionary.DICTIONARY_FILE} is missing, so no model can be named for "
                f"its role definitions ({', '.join(d.id for role in wanted[name] for d in wanted_definitions(role))})"
            )
    # Resolved as ``profiles.resolution`` does, but for the providers asked
    # for only: a setting that a provider nobody installed cannot take must
    # not stop the others.
    resolved: dict[tuple[str, str], profiles.Resolved] = {}
    try:
        entries = {
            key: entry for group in profiles.GROUPS for key, entry in settings.resolve(where, (group,)).items()
        }
        dictionaries = dictionary.load_all(where)
    except SetupError as exc:
        problems.extend(exc.lines)
    else:
        for name in providers:
            for role in wanted[name] if name in dictionaries else []:
                for definition in wanted_definitions(role):
                    try:
                        resolved[(definition.id, name)] = profiles.resolve_definition(
                            definition, dictionaries[name], entries
                        )
                    except SetupError as exc:
                        problems.extend(exc.lines)
    try:
        rows = bindings(where)
    except SetupError as exc:
        problems.extend(exc.lines)
        rows = {}

    texts: dict[Path, str | None] = {}

    def text_of(file: Path) -> str | None:
        if file not in texts:
            texts[file] = _read(file, problems)
        return texts[file]

    def relative(file: Path) -> str:
        return file.relative_to(where.clone).as_posix()

    found: list[Material] = []
    for name in providers:
        if name not in known:
            continue  # said above
        actions_file = where.providers_dir / name / ACTIONS_FILE
        for role in wanted[name]:
            directory = role.file.parent
            includes = role.data.get("includes")
            includes = [item for item in includes if isinstance(item, str)] if isinstance(includes, list) else []
            files = [directory / roles.TEXT_FILE, role.file,
                     *[where.roles_dir / roles.SHARED_DIR / item for item in includes], actions_file]
            read = {relative(file): text_of(file) for file in files}
            if any(text is None for text in read.values()):
                continue
            mine = rows.get(role.name, ())
            body = (read[relative(directory / roles.TEXT_FILE)],
                    *[read[relative(where.roles_dir / roles.SHARED_DIR / item)] for item in includes],
                    bindings_section(mine), read[relative(actions_file)])
            for definition in wanted_definitions(role):
                profile = resolved.get((definition.id, name))
                if profile is None:
                    continue  # no dictionary, or the resolution failed: said above
                found.append(Material(
                    provider=name, definition=definition.id, role=role, body=body,  # type: ignore[arg-type]
                    files=read, rows=tuple(mine), model=profile.model, effort=profile.effort,  # type: ignore[arg-type]
                ))
    if problems:
        raise SetupError(*problems)
    return found


def build(where: Locations, providers: Iterable[str] = PROVIDERS) -> list[Generated]:
    """Every definition of ``providers``, by provider in the order given and
    then by definition. Nothing is written. Every reason one cannot be made
    is reported together, as one ``SetupError``; see ``materials``."""
    problems: list[str] = []
    built: list[Generated] = []
    for found in materials(where, providers):
        role, name = found.role, found.provider
        fields = {
            "name": found.definition,
            "role": role.name,
            "description": description_of(role, found.definition),
            "model": found.model,
            "effort": found.effort,
            "denied": denied_tools(found.limits),
            "read_only": found.limits.get("edits") is False,
        }
        notice = notice_lines(name, role.name, found.definition)
        try:
            text = (claude_code_text if name == CLAUDE_CODE else codex_text)(fields, notice, list(found.body))
        except SetupError as exc:
            problems.extend(exc.lines)
            continue
        built.append(Generated(
            provider=name, definition=found.definition, role=role.name, name=file_name(name, found.definition),
            text=text, inputs=found.digest(), model=found.model, effort=found.effort, sources=tuple(found.files),
        ))
    if problems:
        raise SetupError(*problems)
    return built


def digests(where: Locations, providers: Iterable[str] = PROVIDERS) -> dict[tuple[str, str], str]:
    """The inputs digest of each definition, by provider and definition id,
    from the sources and settings as they are now. Nothing is written. A
    recorded ``inputs`` that differs from it is drift: the file was made
    from other sources or settings than today's."""
    return {(found.provider, found.definition): found.inputs for found in build(where, providers)}
