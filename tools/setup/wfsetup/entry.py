"""How a session becomes a role: the files of its entry points, as text.

How it is used

    entry.skills(where, ["claude-code", "codex"])   # a loaded role, as a skill: two files each
    entry.profiles(where)                           # codex: <role>.config.toml, per starting role
    entry.starting_role(where)                      # the one role with entry.start; else a SetupError
    entry.manager_default(where)                    # the setting roles.manager_default, for where
    entry.project_block(where)                      # codex: the project default, as a block's text
    entry.project_definitions(where, providers)     # the definitions a project's settings change
    entry.digests(where, providers)                 # {(provider, kind, name): inputs}; what doctor compares
    entry.project_digests(where, providers)         # the same for a project's definitions

Nothing here writes, and nothing here knows a home or a directory: the
caller (``render``) decides where a text goes. Every text is made from
``definitions.materials``, so it holds the role's text, its includes, its
binding rows and the provider's action notes exactly as the role's
definition does.

The entry points (provider facts read on 2026-10-05)

  A loaded role (``entry.load = true``): a skill of the role's name, for
  each provider, that the user invokes and the model never loads by itself.
    claude-code   ``/<role>``. ``disable-model-invocation: true`` in the
                  frontmatter (code.claude.com/docs/en/skills: "Set to
                  `true` to prevent Claude from automatically loading this
                  skill. Use for workflows you want to trigger manually with
                  `/name`.").
    codex         ``$<role>``. ``agents/openai.yaml`` with
                  ``policy.allow_implicit_invocation: false``
                  (learn.chatgpt.com/docs/build-skills: "When `false`, Codex
                  won't implicitly invoke the skill based on user prompt;
                  explicit `$skill` invocation still works.").
    Each provider's copy carries both declarations: where two homes share
    one skills directory the copy is written once, and it must be
    invoke-only for whichever provider reads it. The copies differ in the
    ``compatibility`` line, the action notes and the profile.

    A skill does not switch the session's model. Claude Code: a skill's
    ``model`` key "applies for the rest of the current turn and isn't saved
    to settings. The session model resumes when you send your next prompt"
    (.../skills), so the key is not written. Codex: the skills page names no
    model setting. The skill therefore names the role's profile and has the
    session tell the user how to switch to it: ``/model <name>`` and
    ``/effort <level>`` on Claude Code (code.claude.com/docs/en/model-config:
    "use `/model <alias|name>` to switch immediately"; "`/effort` followed
    by a level name to set it directly"), ``/model`` on Codex (the action
    notes of the repository).

    A project cannot override a loaded role: the skill is user-level, and
    a provider's personal skill wins over a project skill of the same name
    (the Phase 5 review's finding S13; Codex does not merge two skills of
    one name). So the skill carries
    the user-level profile, its profile paragraph says that a project may
    set another and which command prints it (``PROJECT_PROFILE``), and
    ``render --project`` reports each loaded role whose profile the
    project changes.

    The text begins with what makes it a loaded role (the one-active-role
    rule, where the role's own text does not state it, and the profile),
    and the role's text follows: after a compaction Claude Code keeps "the
    first 5,000 tokens of each" invoked skill, and "Re-attached skills share
    a combined budget of 25,000 tokens" (.../skills). ``Made.tokens`` is a
    conservative estimate, one token per ``BYTES_PER_TOKEN`` bytes, and
    ``Made.over_limit`` says that the end of the skill is likely to be cut.

  A starting role (``entry.start = true``).
    claude-code   ``claude --agent <role>``, served by the role's agent
                  file, which ``definitions`` makes; nothing is made here.
                  For a project: ``"agent": "<role>"`` in its
                  ``.claude/settings.json`` (code.claude.com/docs/en/sub-agents:
                  "To make it the default for every session in a project,
                  set `agent` in `.claude/settings.json`").
    codex         ``codex --profile <role>``, which reads
                  ``<role>.config.toml`` in the Codex home
                  (learn.chatgpt.com/docs/config-file/config-advanced:
                  "Create a separate TOML file for each profile"; "In Codex
                  0.134.0 and later, `--profile` no longer reads
                  `[profiles.profile-name]` from `config.toml`"). The file
                  holds ``model``, ``model_reasoning_effort`` and
                  ``developer_instructions`` at the top level (.../config-reference:
                  "Additional developer instructions injected into the
                  session"). For a project: the same keys in a marked block
                  at the head of its ``.codex/config.toml``. The precedence
                  (.../config-basic), highest first: "CLI flags and
                  `--config` overrides", "Project config files:
                  `.codex/config.toml` ... (closest wins; trusted projects
                  only)", "Profile files selected with `--profile
                  profile-name`", "User config: `~/.codex/config.toml`". So a
                  project's keys beat a profile's, and are read only in a
                  trusted project; the notice in both texts says so.

The inputs digests
    ``LOADED_SCHEME`` and ``PROFILE_SCHEME``, each with the SHA-256 of what
    ``definitions.inputs_digest`` hashes for the role on that provider and
    the name of the file. ``agents/openai.yaml`` of a loaded role is made
    from the role's name and title alone, and its digest from those. Raise
    a scheme's number when this module would write different text from the
    same inputs.
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from typing import Any, Iterable

from . import definitions, roles, settings, tomlio
from .definitions import CLAUDE_CODE, CODEX, PROVIDERS
from .errors import SetupError
from .locations import Locations

# 2: the profile paragraph says that a project may set another profile.
LOADED_SCHEME = "render:loaded-role:2"
PROFILE_SCHEME = "render:codex-profile:1"

# The kinds of ``Made``.
LOADED = "loaded-role"
PROFILE = "codex-profile"

SKILL_FILE = "SKILL.md"
OPENAI_FILE = "agents/openai.yaml"
PROFILE_SUFFIX = ".config.toml"

# A project's defaults.
MANAGER_DEFAULT_KEY = "roles.manager_default"
AGENT_KEY = "agent"
CLAUDE_SETTINGS = ".claude/settings.json"
CODEX_CONFIG = ".codex/config.toml"
BLOCK_NAME = "starting-role"
BLOCK_KEYS = ("model", "model_reasoning_effort", "developer_instructions")
PROJECT_AGENTS = {CLAUDE_CODE: ".claude/agents", CODEX: ".codex/agents"}

# What Claude Code keeps of an invoked skill after a compaction, and the
# budget all of them share (see the module).
COMPACTION_TOKENS = 5_000
COMPACTION_BUDGET = 25_000
# English prose runs near four bytes a token; three errs toward "too long".
BYTES_PER_TOKEN = 3

# A loaded role is a user-level skill, and a provider's own skill wins over
# a project's of the same name: a project's settings cannot change this
# text. The paragraph says so, and where the project's profile is printed.
PROJECT_PROFILE = (
    "That profile is the user-level one: this text is installed once for the user, and a project's settings do "
    "not change it. A project may set another profile for this role, and "
    "`python tools/setup/workflow_setup.py show roles --project <the project>`, run in the skills repository, "
    "prints it."
)

ONE_ROLE = "Loading this role suspends any other role loaded in this session. One role is active at a time."
_ONE_ROLE_SAID = re.compile(r"suspends\s+any\s+other\s+role", re.I)

INVOKE = {CLAUDE_CODE: "/{role}", CODEX: "${role}"}
START = {CLAUDE_CODE: "claude --agent {role}", CODEX: "codex --profile {role}"}


@dataclass(frozen=True)
class Made:
    """One generated file of an entry point. ``name`` is its path below the
    place it goes to, with ``/``: ``manager/SKILL.md`` in a skills
    directory, ``manager.config.toml`` in the Codex home."""

    provider: str
    kind: str
    role: str
    name: str
    text: str
    inputs: str
    model: str | None = None
    effort: str | None = None

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def tokens(self) -> int:
        """About how many tokens the text is, erring high."""
        return -(-self.size // BYTES_PER_TOKEN)

    @property
    def over_limit(self) -> bool:
        """Whether a compaction on Claude Code is likely to cut its end."""
        return self.provider == CLAUDE_CODE and self.name.endswith(SKILL_FILE) and self.tokens > COMPACTION_TOKENS


# --- Which roles -------------------------------------------------------------------

def _flag(role: roles.Role, key: str) -> bool:
    entry = role.data.get("entry")
    return isinstance(entry, dict) and entry.get(key) is True


def loads(role: roles.Role) -> bool:
    return _flag(role, "load")


def starts(role: roles.Role) -> bool:
    return _flag(role, "start")


def loaded_roles(where: Locations) -> list[str]:
    return [name for name, role in roles.load_all(where).items() if loads(role)]


def start_roles(where: Locations) -> list[str]:
    return [name for name, role in roles.load_all(where).items() if starts(role)]


def starting_role(where: Locations) -> str:
    """The role a session starts as: the one role with ``entry.start``.
    None, or more than one, is a ``SetupError``: a project default names
    one role."""
    found = start_roles(where)
    if len(found) == 1:
        return found[0]
    if not found:
        raise SetupError(
            f"{MANAGER_DEFAULT_KEY} is set, and no role has `start = true` under [entry] in its role.toml: "
            "there is no role for a session to start as"
        )
    raise SetupError(
        f"{MANAGER_DEFAULT_KEY} is set, and {len(found)} roles have `start = true` under [entry] in their "
        f"role.toml ({', '.join(found)}): a project's sessions start as one role, so exactly one may have it"
    )


def manager_default(where: Locations) -> bool:
    """Whether the settings of ``where`` ask that a session starts as the
    starting role: ``roles.manager_default``, the project's layers included
    when ``where`` has a project."""
    found = settings.resolve(where, ("roles",)).get(MANAGER_DEFAULT_KEY)
    return found is not None and found.value is True


# --- The texts ---------------------------------------------------------------------

def _notice(provider: str, role: str, first: str) -> list[str]:
    """The notice of ``definitions`` with a first line of its own."""
    return [first, *definitions.notice_lines(provider, role, role)[1:]]


def _profile_words(model: str, effort: str | None) -> str:
    return f"the model `{model}` with " + ("no effort setting" if effort is None else f"the effort `{effort}`")


def _switch(provider: str, model: str, effort: str | None) -> str:
    """The profile paragraph of a loaded role: what the role is meant to
    run on, that loading did not switch to it, and the provider's way."""
    profile = _profile_words(model, effort)
    if provider == CLAUDE_CODE:
        way = f"`/model {model}` switches" if effort is None else f"`/model {model}` and `/effort {effort}` switch"
        why = "a skill cannot set a session's model beyond the turn that loads it"
    else:
        way = "`/model`, choosing that model" + ("" if effort is None else " and that reasoning effort") + ", switches"
        why = "a skill has no model setting on Codex"
    return (
        f"**Profile.** This role is meant to run on {profile}. Loading it did not switch the session: {why}. "
        f"In your first reply as this role, name that profile in one line and tell the user that {way} "
        "the session to it. Say it once, and do the role's work on whatever the session runs on. "
        f"{PROJECT_PROFILE}"
    )


def _loaded_section(found: definitions.Material) -> str:
    role = found.role
    lines = [
        f"**Loaded role.** The user loaded the {role.title} role into this session. From here on the session "
        "acts as this role, by the text below, until the user says in a message to switch back or loads another."
    ]
    if not _ONE_ROLE_SAID.search(found.body[0]):
        lines.append(ONE_ROLE)
    lines.append(_switch(found.provider, found.model, found.effort))
    return "\n\n".join(lines)


def skill_text(found: definitions.Material) -> str:
    """``SKILL.md`` of a loaded role for the material's provider."""
    role, provider = found.role, found.provider
    description = f"Load the {role.title} role into this session. {role.description}"
    head = [
        "---",
        f"name: {definitions.yaml_scalar(role.name)}",
        f"description: {definitions.yaml_quoted(description)}",
        f"compatibility: {provider}",
        "disable-model-invocation: true",
        "---",
    ]
    notice = _notice(provider, role.name, (
        f"Generated by workflow setup: the role {role.name} as a skill the user loads into a session. "
        "Do not edit this file."
    ))
    comment = "\n".join(["<!--", *notice, "-->"])
    return "\n".join(head) + "\n\n" + roles.join_text([comment, _loaded_section(found), *found.body])


def openai_text(role: roles.Role) -> str:
    """``agents/openai.yaml`` of a loaded role: invoke-only on Codex."""
    lines = [
        f"# Generated by workflow setup for the loaded role {role.name}. Do not edit this file.",
        f"# To change it, change roles/{role.name}/ in the skills repository and run "
        f"`{definitions.RENDER_COMMAND}` there.",
        "interface:",
        f"  display_name: {definitions.yaml_quoted(role.title)}",
        f"  short_description: {definitions.yaml_quoted(f'Load the {role.title} role into this session')}",
        "",
        "policy:",
        "  allow_implicit_invocation: false",
    ]
    return "\n".join(lines) + "\n"


def _session_data(found: definitions.Material) -> dict[str, Any]:
    """The three keys that make a Codex session the role."""
    data: dict[str, Any] = {"model": found.model}
    if found.effort is not None:
        data["model_reasoning_effort"] = found.effort
    data["developer_instructions"] = roles.join_text([definitions.notice_inline(found.role.name), *found.body])
    return data


def _toml(data: dict[str, Any], header: list[str], what: str) -> str:
    text = tomlio.dumps(data, header=header)
    try:
        again = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SetupError(f"{what}: the generated text is not valid TOML: {exc}") from None
    if again != data:
        raise SetupError(f"{what}: the generated text does not read back as written")
    return text


def profile_text(found: definitions.Material) -> str:
    """``<role>.config.toml``: the profile ``codex --profile <role>`` reads."""
    role = found.role.name
    notice = _notice(CODEX, role, (
        f"Generated by workflow setup: the profile that starts a Codex session as the role {role}. "
        "Do not edit this file."
    ))
    notice.insert(1, (
        f"Start with `{START[CODEX].format(role=role)}`. Codex reads this file as a layer over config.toml in "
        "its home. A project's .codex/config.toml is a layer above it, read only in a trusted project: a key "
        "set there wins over the same key here."
    ))
    return _toml(_session_data(found), notice, f"the Codex profile {role}")


def block_text(found: definitions.Material) -> str:
    """The project default on Codex: the text between setup's markers at
    the head of a project's ``.codex/config.toml``."""
    role = found.role.name
    notice = [
        f"Generated by workflow setup: a Codex session in this project starts as the role {role}, because "
        f"{MANAGER_DEFAULT_KEY} is set for the project. Do not edit between the markers.",
        "Codex reads this file only in a trusted project. A key set here wins over the same key of a profile "
        "(codex --profile), and a command-line override wins over both.",
        definitions.notice_lines(CODEX, role, role)[1],
        f"To change it, change a source and run `{definitions.RENDER_COMMAND} --project <this project>` in "
        f"that repository. To take it out, set {MANAGER_DEFAULT_KEY} = false and run the same.",
        "Setup does not overwrite an edit made between the markers; it reports the block as edited by hand.",
    ]
    return _toml(_session_data(found), notice, f"the project default of the role {role}")


# --- Building ----------------------------------------------------------------------

def _wanted(providers: Iterable[str]) -> list[str]:
    return [name for name in providers if name in PROVIDERS]


def skills(where: Locations, providers: Iterable[str] = PROVIDERS) -> list[Made]:
    """The skill of every loaded role, for each of ``providers``: by
    provider, by role, ``SKILL.md`` and then ``agents/openai.yaml``. The
    model and effort are those the settings of ``where`` resolve."""
    made: list[Made] = []
    found = definitions.materials(
        where, _wanted(providers), lambda role: PROVIDERS if loads(role) else (), hard=False
    )
    for one in found:
        role = one.role.name
        made.append(Made(
            one.provider, LOADED, role, f"{role}/{SKILL_FILE}", skill_text(one),
            one.digest(LOADED_SCHEME, file=SKILL_FILE), one.model, one.effort,
        ))
        form = {"scheme": LOADED_SCHEME, "provider": one.provider, "role": role, "title": one.role.title,
                "file": OPENAI_FILE}
        raw = json.dumps(form, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        made.append(Made(
            one.provider, LOADED, role, f"{role}/{OPENAI_FILE}", openai_text(one.role),
            f"{LOADED_SCHEME}:{hashlib.sha256(raw).hexdigest()}",
        ))
    return made


def _start_materials(where: Locations) -> list[definitions.Material]:
    return definitions.materials(where, [CODEX], lambda role: (CODEX,) if starts(role) else (), hard=False)


def profiles(where: Locations, providers: Iterable[str] = PROVIDERS) -> list[Made]:
    """The Codex profile of every starting role; nothing unless ``codex``
    is among ``providers``."""
    if CODEX not in providers:
        return []
    return [
        Made(CODEX, PROFILE, one.role.name, one.role.name + PROFILE_SUFFIX, profile_text(one),
             one.digest(PROFILE_SCHEME, file=PROFILE_SUFFIX), one.model, one.effort)
        for one in _start_materials(where)
    ]


def project_block(where: Locations) -> tuple[str, str]:
    """The starting role of ``where`` and the text of its project default
    on Codex, made from the settings of ``where`` (the project's layers
    included)."""
    role = starting_role(where)
    for one in _start_materials(where):
        if one.role.name == role:
            return role, block_text(one)
    raise SetupError(f"the role {role}: no project default can be made for Codex")


def project_definitions(where: Locations, providers: Iterable[str] = PROVIDERS) -> list[definitions.Generated]:
    """The definitions that the project's settings change: those whose text,
    built with the project of ``where``, differs from the user-level one. A
    project that changes no role's profile gives none."""
    if where.project is None:
        return []
    names = _wanted(providers)
    user = {(found.provider, found.definition): found.text
            for found in definitions.build(definitions.user_level(where), names)}
    return [found for found in definitions.build(where, names)
            if user.get((found.provider, found.definition)) != found.text]


def digests(where: Locations, providers: Iterable[str] = PROVIDERS) -> dict[tuple[str, str, str], str]:
    """The inputs digest of every file ``skills`` and ``profiles`` give, by
    provider, kind and name, from the sources and settings as they are now.
    Nothing is written. For a home, give ``definitions.user_level(where)``."""
    made = [*skills(where, providers), *profiles(where, providers)]
    return {(one.provider, one.kind, one.name): one.inputs for one in made}


def project_digests(where: Locations, providers: Iterable[str] = PROVIDERS) -> dict[tuple[str, str], str]:
    """The inputs digest of each definition a project holds, by provider
    and the file's name in the project's agents directory."""
    return {(found.provider, found.name): found.inputs for found in project_definitions(where, providers)}
