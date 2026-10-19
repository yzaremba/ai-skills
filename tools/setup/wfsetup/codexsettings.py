"""The Codex settings the framework needs (R6.7): reported, and written on
request into marked blocks of the user's Codex ``config.toml``.

How it is used

    render.PARTS      Part("codex-settings", codexsettings.fill, codexsettings.configure)
    doctor.CHECKS     Check("codex-settings", codexsettings.check, ..., configure=codexsettings.configure_check)

    render --apply-codex-settings [--worktree-root DIR] [--default-codex-permissions]
    render --remove-codex-settings
    doctor --only codex-settings [--codex-probe]

What the framework needs on Codex (docs/agent-roles-framework.md,
"Differences on Codex, and what to do about each")

    the limit    ``agents.max_concurrent_threads_per_session`` of 8 or more.
    the floor    ``features.multi_agent_v2.min_wait_timeout_ms`` of 300000 or
                 more, with ``default_wait_timeout_ms`` 3600000 beside it: a
                 ``wait_agent`` with a short timeout wakes its caller, and
                 every wake-up of a long-lived Manager reads its whole
                 context again (about 220K tokens in a measured run, where
                 models asked for 60 s and 300 s although the action notes
                 say 3600000). The floor makes the action notes binding.
    the profile  a permission profile under which ``.git`` of the repository
                 and the worktree root are writable, so that git's add,
                 commit and worktree commands run without an approval each.

What the provider's pages say (read on 2026-10-05)

  learn.chatgpt.com/docs/config-file/config-reference
    ``agents.max_concurrent_threads_per_session``: "Maximum number of
    spawned-agent threads that can be open concurrently, excluding the
    primary thread. When unset, Codex chooses the default." No number is
    given for that default. ``agents.max_threads``: "Legacy alias for
    `agents.max_concurrent_threads_per_session`."
    ``default_permissions``: "Name of the default permissions profile to
    apply to sandboxed tool calls. Built-ins are `:read-only`, `:workspace`,
    and `:danger-full-access`; custom profile names require matching
    `[permissions.<name>]` tables."
    ``permissions.<name>.extends``: "Optional parent profile applied before
    this named profile. Set it to another named profile, `:read-only`, or
    `:workspace`; `:danger-full-access`, undefined parents, and cycles are
    rejected."
    ``permissions.<name>.filesystem``: "Named filesystem permission profile.
    Each key is an absolute path or special token such as `:minimal` or
    `:workspace_roots`."
    ``permissions.<name>.filesystem.":workspace_roots".<subpath-or-glob>``:
    "Scoped filesystem access relative to each effective workspace root. Use
    `"."` for the root itself; glob subpaths can deny reads."

  learn.chatgpt.com/docs/permissions
    "Beta. Permission profiles are under active development and may change."
    "Create a named profile under `[permissions.<name>]`, then set the
    top-level `default_permissions` key to that profile name."
    "Permission profiles do not compose with the older sandbox settings.
    Configure either `default_permissions` and `[permissions]`, or
    `sandbox_mode` / `sandbox_workspace_write`, but not both."
    "If `sandbox_mode` appears in any loaded config file, you pass
    `--sandbox`, or the selected config profile sets `sandbox_mode`, Codex
    uses those older sandbox settings instead of `default_permissions`."
    "Prefer extending a built-in profile over starting from scratch so
    baseline protections carry forward."
    "More specific entries override broader ones."
    "Use nested entries under `:workspace_roots` to scope access to
    workspace-root relative subpaths." "Nested subpaths must stay inside
    their workspace root. Parent traversal such as `../other-repo` is
    rejected."
    Path forms of a filesystem table: a special token, ``/absolute/path``
    and ``~/path``. The page's own example of the shape:

        [permissions.project-edit]
        extends = ":workspace"

        [permissions.project-edit.filesystem.":workspace_roots"]
        "**/*.env" = "deny"

  learn.chatgpt.com/docs/config-file/config-advanced
    "Use `-c` / `--config` when you need to override an arbitrary key."
    "`--config` values are parsed as TOML." Example:
    ``codex --config model='"gpt-6.1-sol"'``.

  NOT ESTABLISHED by those pages, and so stated wherever the profile is
  written or printed: that a ``".git" = "write"`` entry under
  ``:workspace_roots`` lifts whatever protection ``:workspace`` keeps on
  ``.git`` (the pages say only that the more specific entry wins); that a
  session inside a linked git worktree, whose commits write into the
  ``.git`` of the main repository, is covered (that directory is outside
  the session's workspace root, so it is not); and the default number of
  threads.

What codex-cli 0.163.0 itself showed of the floor (2026-10-18; its config
validation, ``codex -c features.multi_agent_v2.<key>=<n> features list``,
which starts no model session; no page of the provider's was read for it)

    The table ``features.multi_agent_v2`` takes ``min_wait_timeout_ms``,
    ``default_wait_timeout_ms`` and ``max_wait_timeout_ms``, and ``enabled``;
    an unknown key in it is refused. ``features.multi_agent_v2 = true``, a
    plain switch, is accepted as well (an untagged enum of Codex's).
    Codex's own values: min 10000, default 30000, max 3600000. It refuses a
    config unless min <= default <= max ("default_wait_timeout_ms must be at
    least ... min_wait_timeout_ms"), so a min of 300000 alone is refused:
    the default goes with it. ``max_wait_timeout_ms`` is left unset.
    The table without ``enabled`` leaves the feature's switch where it was
    (``features list`` showed ``multi_agent_v2`` false before and after).
    The binary holds the message "Requested timeout of Nms was clamped to
    the minimum of Mms", and in a run requests of 10000 to 3600000 ms were
    honoured: the floor raises a shorter request, it does not refuse it.

  NOT ESTABLISHED: that the floor applies to a session in which the switch
  of ``multi_agent_v2`` is off (the clamp was not watched in a session);
  and whether a later Codex keeps these keys.

The two blocks, and why two
    A key written after a table header belongs to that table, so a block
    at the end of a file that has tables can hold tables only, and a
    top-level key must come before the first table.

    ``codex-settings``       at the end of the file: ``[agents]`` with the
                             limit, ``[features.multi_agent_v2]`` with the
                             floor, and the tables of the profile.
    ``codex-settings-top``   at the head of the file, and only where it is
                             needed: ``default_permissions``, and the limit
                             as a dotted key where the end form is not
                             valid TOML and this one is.

The limit, by what the user's file holds outside setup's blocks
    (``tomllib`` decides; ``_valid`` asks it for every case)

    nothing about ``agents``, or only          [agents] in the end block
      ``[agents.<name>]`` sub-tables
    top-level dotted keys ``agents.<other>``   a dotted key in the head block
      and no ``[agents]`` header               (a second definition of the
                                               table by a header is refused)
    an ``[agents]`` header without the key,    nothing: a table is defined
      an inline table, anything else           once. The one line to add to
                                               that table is printed
    the key itself, by a header or dotted      nothing: the user's value is
                                               reported, enough or not
    the legacy alias ``agents.max_threads``    nothing: reported, its value
                                               not read

The floor, by what the user's file holds outside setup's blocks
    (``tomllib`` decides; ``_valid`` asks it for every case)

    nothing at ``features.multi_agent_v2``:    [features.multi_agent_v2] in
      no ``features``, a ``[features]``        the end block, with the two
      table, dotted ``features.*`` keys,       keys
      other ``[features.<name>]`` tables
    anything at ``features.multi_agent_v2``,   nothing: a table is defined
      by a header, dotted keys or an inline    once. The user's values of the
      table, a sub-table of it among them      three keys are reported, with
                                               whether the floor is met, and
                                               the lines of the two keys the
                                               file does not set are printed
                                               (the default as the user's
                                               max where one is set), with
                                               what Codex would refuse
    ``features.multi_agent_v2`` a switch       nothing: the value is not
      (``= true``) or another value            read; making it a table, with
                                               ``enabled``, is the user's
    ``features`` an inline table, a plain      nothing: the lines to add are
      value or an array of tables              printed

    No form at the head of the file is needed: where the user's file
    defines nothing at ``features.multi_agent_v2``, ``tomllib`` found no
    text in which dotted keys at the head are valid and the table at the
    end is not (``[features.<name>]`` may follow dotted ``features.*`` keys).

The profile
    While the user's file sets ``sandbox_mode`` no ``[permissions]`` table
    is written and ``default_permissions`` is not set: Codex would ignore
    both. The profile is printed as text, with what the user would change.
    Setup never changes or removes ``sandbox_mode``. Only the user's
    ``config.toml`` is looked at: a project's config or a profile file that
    sets the key has the same effect, and the output says so.

    Where the key is absent the profile ``workflow`` is written only where
    ``default_permissions`` is set after the run. codex-cli 0.163.0
    refuses to load a config that defines a ``[permissions]`` profile and
    sets no ``default_permissions`` ("config defines `[permissions]`
    profiles but does not set `default_permissions`"); with
    ``sandbox_mode`` set, or with ``default_permissions`` set to any
    value, a built-in among them, it loads (``codex features list`` on
    scratch homes, 2026-10-18). So:

    ``--default-codex-permissions``      the profile in the end block, and
                                         ``default_permissions = "workflow"``
                                         in the head block
    the user's file sets                 the profile in the end block, not
      ``default_permissions``            selected; the user's value is
                                         reported and kept
    neither                              not written: printed as text, with
                                         what the user would do

    A profile of that name that the user defined is reported and kept. An
    end block that an earlier setup wrote with the profile and no
    ``default_permissions`` beside it is the config Codex refuses: ``doctor``
    reports it as an error, and the next run without the option takes the
    profile out of the block and says so.

    Its write roots: ``.git`` under ``:workspace_roots``, which names the
    ``.git`` of whatever project a session is in and needs no path of this
    machine; and the worktree root, an absolute or ``~/`` path that only the
    user gives, with ``--worktree-root``. That path is the user's content
    in the user's file. It is written there, marked as such, and nowhere
    else: the install record holds the block's hash.

What stays
    The blocks are the user's explicit choice. A later ``render`` without
    ``--apply-codex-settings`` leaves them as they are: the stale sweep of
    ``render`` removes links and generated files only. They go with
    ``render --remove-codex-settings``, and with the reversal of the record
    (``uninstall``). A run with ``--apply-codex-settings`` writes what its
    options say: without ``--worktree-root`` the profile has no worktree
    root, and without ``--default-codex-permissions`` it is not selected,
    and not written either unless the user's file sets
    ``default_permissions``; what such a run takes out of an earlier block
    is said in the output. A
    block edited by hand is kept and reported (exit code 3), as every block
    of setup's is. A block the record lists and the file no longer holds is
    taken out of the record by the next ``render``.

Reading the file
    The file is parsed, since TOML's rules decide what may be written. Of
    its values only those of ``doctor.CODEX_KEYS`` are ever printed. A file
    that does not parse is refused by the position of the fault alone.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import blocks, carried, fileops, fsio, homes, locations, paths, tomlio
from .errors import SetupError

# The two blocks of setup's in the user's Codex ``config.toml``.
BLOCK = "codex-settings"
TOP_BLOCK = "codex-settings-top"
BLOCK_NAMES = (BLOCK, TOP_BLOCK)

# The kind of this part's items in the report of ``render``.
KIND = "codex-settings"

PROFILE = "workflow"
THREADS_TABLE = "agents"
THREADS_NAME = "max_concurrent_threads_per_session"
THREADS_KEY = f"{THREADS_TABLE}.{THREADS_NAME}"
THREADS_ALIAS = "max_threads"
THREADS_NEEDED = 8
WAIT_PATH = ("features", "multi_agent_v2")
WAIT_TABLE = ".".join(WAIT_PATH)
WAIT_MIN = "min_wait_timeout_ms"
WAIT_DEFAULT = "default_wait_timeout_ms"
WAIT_MAX = "max_wait_timeout_ms"
WAIT_NAMES = (WAIT_MIN, WAIT_DEFAULT, WAIT_MAX)
WAIT_KEYS = tuple(f"{WAIT_TABLE}.{name}" for name in WAIT_NAMES)
WAIT_MIN_KEY, WAIT_DEFAULT_KEY, WAIT_MAX_KEY = WAIT_KEYS
WAIT_MIN_NEEDED = 300000
WAIT_DEFAULT_WANTED = 3600000
# Codex's own values where a key is not set (codex-cli 0.163.0).
WAIT_CODEX = {WAIT_MIN: 10000, WAIT_DEFAULT: 30000, WAIT_MAX: 3600000}
SANDBOX_KEY = "sandbox_mode"
PERMISSIONS_KEY = "default_permissions"
PERMISSIONS_TABLE = "permissions"
WORKSPACE_ROOTS = ":workspace_roots"
PARENT = ":workspace"

APPLY_OPTION = "--apply-codex-settings"
REMOVE_OPTION = "--remove-codex-settings"
WORKTREE_OPTION = "--worktree-root"
DEFAULT_OPTION = "--default-codex-permissions"
PROBE_OPTION = "--codex-probe"

# How one launch selects a profile; the quoting holds in bash, PowerShell
# and cmd alike (a TOML literal string inside one double-quoted argument).
PER_LAUNCH = f"codex -c \"{PERMISSIONS_KEY}='{PROFILE}'\""

UNSET = object()

# What became of the limit, and of the floor.
TABLE = "table"          # [agents] (or [features.multi_agent_v2]) in the end block
DOTTED = "dotted"        # a dotted key in the head block
USER_SET = "user-set"    # the user sets the key (for the floor: anything at features.multi_agent_v2)
ALIAS = "alias"          # the user sets the legacy alias
SWITCH = "switch"        # features.multi_agent_v2 is set to a value that is not a table
CANNOT = "cannot"        # no form is valid TOML beside the user's file

# What became of the profile, and of its selection.
WRITTEN = "written"
SANDBOX = "sandbox-mode"     # not written: sandbox_mode is set
THEIRS = "theirs"            # the user defines a profile of that name
NOT_ASKED = "not-asked"
NO_PROFILE = "no-profile"    # nothing of setup's to select
NO_DEFAULT = "no-default"    # not written: default_permissions would not be set after the run

REFUSES = (
    f"Codex (0.163.0) refuses to load a config that defines a [{PERMISSIONS_TABLE}] profile and sets no "
    f"{PERMISSIONS_KEY} while {SANDBOX_KEY} is unset"
)

APPROVAL = (
    f"until you change the sandbox model yourself, git commands that write under .git (add, commit, worktree) "
    "go through command-by-command approval"
)
UNCERTAIN = (
    "permission profiles are beta in Codex; that this entry lifts the protection of .git is read from the "
    "provider's pages (\"More specific entries override broader ones\") and was not tried here"
)

_UP_TO_DATE = "up-to-date"   # ``render.UP_TO_DATE``; ``render`` imports this module, so it is not imported here

_TOML_PLACE = re.compile(r"\(at (line \d+, column \d+|end of document)\)")


# --- The options -----------------------------------------------------------------

def configure(parser: Any) -> None:
    """The options of the part of ``render``."""
    parser.add_argument(
        APPLY_OPTION, action="store_true",
        help="write the Codex settings the framework needs into marked blocks of the user's Codex config.toml: "
        f"{THREADS_KEY} = {THREADS_NEEDED}; the wait floor {WAIT_MIN_KEY} = {WAIT_MIN_NEEDED} with "
        f"{WAIT_DEFAULT} = {WAIT_DEFAULT_WANTED}, unless the file defines {WAIT_TABLE} itself; and, unless the "
        f"file sets {SANDBOX_KEY}, the permission profile `{PROFILE}`, where {PERMISSIONS_KEY} is set after the "
        f"run (by {DEFAULT_OPTION}, or by your file). A key the file already sets is reported and left alone. "
        f"Once written, the blocks stay until {REMOVE_OPTION}",
    )
    parser.add_argument(
        WORKTREE_OPTION, metavar="DIR",
        help=f"with {APPLY_OPTION}: the directory your git worktrees are made under, made writable by the "
        "profile. An absolute path, written normalised (no . or .. left in it), or one that starts with ~/, "
        "written with / between its parts. The filesystem root and the home directory itself are refused. "
        "It is your input: it goes into your config.toml and nowhere else",
    )
    parser.add_argument(
        DEFAULT_OPTION, action="store_true",
        help=f"with {APPLY_OPTION}: also write and select the profile, with {PERMISSIONS_KEY} = \"{PROFILE}\". "
        f"Without it the profile is written, unselected, only where your file sets {PERMISSIONS_KEY} itself, "
        f"and otherwise printed as text: Codex refuses a config that defines a profile and sets no "
        f"{PERMISSIONS_KEY}",
    )
    parser.add_argument(
        REMOVE_OPTION, action="store_true",
        help=f"take out the blocks {APPLY_OPTION} wrote, where they still hold what setup wrote",
    )


def configure_check(parser: Any) -> None:
    """The option of the check of ``doctor``."""
    parser.add_argument(
        PROBE_OPTION, action="store_true",
        help="with the check `codex-settings`: print the steps of the one session that shows whether this "
        f"Codex ignores a `-c {PERMISSIONS_KEY}=...` override while {SANDBOX_KEY} is set (gate G4). doctor "
        "itself starts no session",
    )


def worktree_root(text: str) -> str:
    """``--worktree-root`` as it is written into the profile: an absolute
    path, normalised, or a ``~/`` path with ``/`` between its parts (the
    provider's page lists both forms). Anything else is a ``SetupError``:
    the profile is read from every directory, so a relative path would name
    a different place in each. Refused as well, after ``..`` is worked
    out: the filesystem root and the home directory itself, which would
    make everything, or everything of the user's, writable."""
    given = text.strip()
    if not given:
        raise SetupError(f"{WORKTREE_OPTION}: no directory was given")
    if locations.control_character(given):
        raise SetupError(f"{WORKTREE_OPTION}: the path holds a control character or a line break")
    if given.startswith("~"):
        rest = given[1:].replace("\\", "/")
        if rest and not rest.startswith("/"):
            raise SetupError(
                f"{WORKTREE_OPTION} {given}: another user's home is not a form the profile takes; give an "
                "absolute path, or one that starts with ~/"
            )
        tail = "/".join(part for part in rest.split("/") if part not in ("", "."))
        if ".." in tail.split("/"):
            raise SetupError(f"{WORKTREE_OPTION} {given}: a path with .. in it; give the directory itself")
        if not tail:
            raise SetupError(
                f"{WORKTREE_OPTION} {given}: the home directory itself; the profile would make everything in it "
                "writable. Give the directory your worktrees are made under"
            )
        return "~/" + tail
    if not os.path.isabs(given):
        raise SetupError(
            f"{WORKTREE_OPTION} {given}: not an absolute path. The profile is read by Codex from every "
            "directory, so setup does not guess which directory a relative path means; give an absolute "
            "path, or one that starts with ~/"
        )
    normal = os.path.normpath(given)
    if os.path.dirname(normal) == normal:
        raise SetupError(
            f"{WORKTREE_OPTION} {given}: the root of the file system; the profile would make everything "
            "writable. Give the directory your worktrees are made under"
        )
    try:
        own = os.path.normpath(os.path.expanduser("~"))
    except (RuntimeError, KeyError):
        own = ""
    if own and own != "~" and paths.same(normal, own):
        raise SetupError(
            f"{WORKTREE_OPTION} {given}: the home directory itself; the profile would make everything in it "
            "writable. Give the directory your worktrees are made under"
        )
    return normal


@dataclass(frozen=True)
class Want:
    """What a run asks for: the worktree root, as it is written, and
    whether the profile is selected. As what setup's blocks hold
    (``Facts.held``), ``profile`` says whether the end block defines the
    profile; a run does not ask for that."""

    root: str | None = None
    default: bool = False
    profile: bool = False


# --- Reading the file --------------------------------------------------------------

@dataclass
class Facts:
    """What the file holds, as far as setup needs it. ``values`` are the
    keys of ``KEYS`` as the whole file sets them, ``outside`` as the user
    sets them outside setup's blocks; a key that is not set is ``UNSET``."""

    present: bool
    fault: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    outside: dict[str, Any] = field(default_factory=dict)
    outside_text: str = ""
    alias: bool = False            # agents.max_threads is set outside the blocks
    profile_theirs: bool = False   # permissions.<PROFILE> is defined outside the blocks
    wait: Any = UNSET              # features.multi_agent_v2 outside the blocks; never printed
    found: dict[str, bytes | None] = field(default_factory=dict)   # each block, as it is in the file
    held: Want | None = None       # what setup's blocks hold now


def _dig(table: Any, *parts: str) -> Any:
    for part in parts:
        table = table.get(part, UNSET) if isinstance(table, dict) else UNSET
    return table


# The keys whose values setup reads; each is in ``doctor.CODEX_KEYS``.
KEYS = (THREADS_KEY, SANDBOX_KEY, PERMISSIONS_KEY, *WAIT_KEYS)


def _three(parsed: dict[str, Any]) -> dict[str, Any]:
    return {key: _dig(parsed, *key.split(".")) for key in KEYS}


def _parse(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """The text as TOML, or why not: the position of the fault and never
    what the line holds."""
    try:
        return tomllib.loads(text), None
    except (tomllib.TOMLDecodeError, RecursionError, ValueError) as exc:
        place = _TOML_PLACE.search(str(exc))
        return None, "is not valid TOML" + (f" ({place.group(1)})" if place else "")


def analyse(data: bytes | None) -> Facts:
    """What ``data``, the bytes of the user's ``config.toml`` (None for no
    file), holds. Nothing is written and nothing is raised: a file that
    cannot be read as TOML gives ``fault``."""
    unset = {key: UNSET for key in KEYS}
    names = {name: None for name in BLOCK_NAMES}
    if data is None:
        return Facts(False, values=dict(unset), outside=dict(unset), found=names)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return Facts(True, "is not UTF-8 text")
    whole, fault = _parse(text)
    if whole is None:
        return Facts(True, fault)
    try:
        found = {name: blocks.get(data, blocks.TOML, name) for name in BLOCK_NAMES}
        outside_text = "\n".join(blocks.outside(data, blocks.TOML)) + "\n"
    except blocks.Refusal as exc:
        return Facts(True, f"setup's markers in it cannot be read: {exc}")
    outside, fault = _parse(outside_text)
    if outside is None:
        # The file parses and its rest does not: something of the user's
        # leans on a table that one of setup's blocks opens.
        return Facts(True, "is not valid TOML once setup's blocks are taken out: text after a block of "
                           "setup's belongs to that block's last table; move it above the block")
    return Facts(
        True, None, _three(whole), _three(outside), outside_text,
        alias=_dig(outside, THREADS_TABLE, THREADS_ALIAS) is not UNSET,
        profile_theirs=_dig(outside, PERMISSIONS_TABLE, PROFILE) is not UNSET,
        wait=_dig(outside, *WAIT_PATH),
        found=found, held=_held(found),
    )


def _held(found: dict[str, bytes | None]) -> Want | None:
    """What setup's blocks hold now: the worktree root of the profile and
    whether it is selected. None where there is no block, or none that can
    be read (one edited into something else)."""
    if all(block is None for block in found.values()):
        return None
    root, default, profile = None, False, False
    for name, block in found.items():
        if block is None:
            continue
        parsed, _ = _parse(block.decode("utf-8", "replace"))
        if parsed is None:
            continue
        if name == TOP_BLOCK:
            default = parsed.get(PERMISSIONS_KEY) == PROFILE
        else:
            profile = isinstance(_dig(parsed, PERMISSIONS_TABLE, PROFILE), dict)
            files = _dig(parsed, PERMISSIONS_TABLE, PROFILE, "filesystem")
            if isinstance(files, dict):
                roots = [key for key, value in files.items() if key != WORKSPACE_ROOTS and value == "write"]
                root = roots[0] if roots else None
    return Want(root, default, profile)


# --- What to write -----------------------------------------------------------------

def limit_table() -> list[str]:
    return [f"[{THREADS_TABLE}]", f"{THREADS_NAME} = {THREADS_NEEDED}"]


def limit_dotted() -> list[str]:
    return [f"{THREADS_KEY} = {THREADS_NEEDED}"]


def wait_table() -> list[str]:
    return [f"[{WAIT_TABLE}]", f"{WAIT_MIN} = {WAIT_MIN_NEEDED}", f"{WAIT_DEFAULT} = {WAIT_DEFAULT_WANTED}"]


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def wait_order(values: dict[str, Any]) -> str | None:
    """What Codex would refuse in the three wait keys, ``values`` by their
    names (``UNSET`` for one the file does not set, which then takes
    Codex's own value), as one clause; None where min <= default <= max.
    A value that is not a whole number is not compared."""
    have = {name: WAIT_CODEX[name] if values.get(name, UNSET) is UNSET else values[name] for name in WAIT_NAMES}
    if not all(_whole(value) for value in have.values()):
        return None
    low, mid, high = (have[name] for name in WAIT_NAMES)
    if low <= mid <= high:
        return None
    given = ", ".join(
        f"{name} {have[name]}" + (" (Codex's own)" if values.get(name, UNSET) is UNSET else "")
        for name in WAIT_NAMES
    )
    return f"Codex refuses a config unless {WAIT_MIN} <= {WAIT_DEFAULT} <= {WAIT_MAX}, and these are {given}"


def profile_data(root: str | None) -> dict[str, Any]:
    """The profile as data: what the file must read back as."""
    files: dict[str, Any] = {}
    if root is not None:
        files[root] = "write"
    files[WORKSPACE_ROOTS] = {".git": "write"}
    return {
        "description": "The :workspace profile, with write access to .git and to the worktree root, for the "
                       "agent-roles workflow.",
        "extends": PARENT,
        "filesystem": files,
    }


def profile_lines(root: str | None, comments: bool = True) -> list[str]:
    """The profile as TOML lines, as the end block holds it and as it is
    printed."""
    data = profile_data(root)
    head = f"{PERMISSIONS_TABLE}.{tomlio.format_key(PROFILE)}"
    lines = [
        f"[{head}]",
        f"description = {tomlio.format_value(data['description'])}",
        f"extends = {tomlio.format_value(data['extends'])}",
        "",
    ]
    if root is not None:
        if comments:
            lines.append(
                f"# The path below is the worktree root you gave with {WORKTREE_OPTION}: your input, written "
                "as you gave it."
            )
        lines += [f"[{head}.filesystem]", f"{tomlio.format_key(root)} = \"write\"", ""]
    lines += [f"[{head}.filesystem.{tomlio.format_key(WORKSPACE_ROOTS)}]", "\".git\" = \"write\""]
    return lines


def default_lines() -> list[str]:
    return [f"{PERMISSIONS_KEY} = {tomlio.format_value(PROFILE)}"]


def _lines(text: str) -> list[str]:
    """The lines of a block's text, split at LF and nowhere else:
    ``str.splitlines`` also splits at U+2028, U+0085 and their like, which
    TOML does not take for a line end."""
    lines = text.split("\n")
    return lines[:-1] if lines and lines[-1] == "" else lines


def _valid(outside_text: str, top: list[str], end: list[str], expect: dict[tuple[str, ...], Any]) -> bool:
    """Whether the user's text with ``top`` before it and ``end`` after it
    is valid TOML that reads back with every value of ``expect``."""
    text = "".join(line + "\n" for line in top) + ("\n" if top else "") + outside_text
    text += ("\n" if end else "") + "".join(line + "\n" for line in end)
    parsed, _ = _parse(text)
    return parsed is not None and all(_dig(parsed, *path) == value for path, value in expect.items())


@dataclass
class Decision:
    """What ``--apply-codex-settings`` does for one file and one ``Want``:
    the text of each block (None for no block), what became of each
    setting, and the lines that say it."""

    end: str | None = None
    top: str | None = None
    limit: str = CANNOT
    wait: str = CANNOT
    profile: str = SANDBOX
    selected: str = NOT_ASKED
    lines: list[str] = field(default_factory=list)       # what is done, and what is left to the user
    printed: list[str] = field(default_factory=list)     # the profile as text, where it is not written
    expect: dict[tuple[str, ...], Any] = field(default_factory=dict)


def shown(value: Any) -> str:
    """The value of one of ``KEYS``, as it is printed."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = "".join(char if char.isprintable() else " " for char in value)
        return tomlio.format_value(text if len(text) <= 80 else text[:80] + "...")
    return f"a {type(value).__name__}, which is not a value this key takes"


def decide(facts: Facts, want: Want) -> Decision:
    """See the module: the limit, the wait floor, the profile and its
    selection, each by what the user's file holds outside setup's blocks."""
    found = Decision()
    end: list[str] = []
    top: list[str] = []
    text = facts.outside_text

    # The limit.
    limit = facts.outside[THREADS_KEY]
    line = f"{THREADS_NAME} = {THREADS_NEEDED}"
    if limit is not UNSET:
        found.limit = USER_SET
        enough = isinstance(limit, int) and not isinstance(limit, bool) and limit >= THREADS_NEEDED
        found.lines.append(
            f"{THREADS_KEY}: your file sets it to {shown(limit)}, so setup writes nothing for it and leaves "
            "yours alone; " + (
                "that is enough" if enough else
                f"the framework needs {THREADS_NEEDED} or more, and raising it is yours to do"
            )
        )
    elif facts.alias:
        found.limit = ALIAS
        found.lines.append(
            f"{THREADS_KEY}: your file sets {THREADS_TABLE}.{THREADS_ALIAS}, the legacy alias of the same "
            f"setting (its value is not read), so setup writes nothing beside it; make sure it is "
            f"{THREADS_NEEDED} or more"
        )
    elif _valid(text, [], limit_table(), {(THREADS_TABLE, THREADS_NAME): THREADS_NEEDED}):
        found.limit = TABLE
        end += [
            f"# Up to {THREADS_NEEDED} spawned agent threads may be open at once. The limit does not count the "
            "session's own thread.",
            *limit_table(),
        ]
        found.expect[(THREADS_TABLE, THREADS_NAME)] = THREADS_NEEDED
        found.lines.append(f"{THREADS_KEY}: set to {THREADS_NEEDED} in setup's block at the end of the file")
    elif _valid(text, limit_dotted(), [], {(THREADS_TABLE, THREADS_NAME): THREADS_NEEDED}):
        found.limit = DOTTED
        top += [
            f"# Up to {THREADS_NEEDED} spawned agent threads may be open at once. The limit does not count the "
            "session's own thread.",
            *limit_dotted(),
        ]
        found.expect[(THREADS_TABLE, THREADS_NAME)] = THREADS_NEEDED
        found.lines.append(
            f"{THREADS_KEY}: set to {THREADS_NEEDED} as a dotted key in setup's block at the head of the file: "
            f"your file sets other {THREADS_TABLE}.* keys at its top level, and a second [{THREADS_TABLE}] "
            "table is not valid TOML"
        )
    else:
        found.limit = CANNOT
        found.lines.append(
            f"{THREADS_KEY}: not written. Your file defines `{THREADS_TABLE}` itself, and TOML allows a table "
            f"to be defined once, so setup cannot add the key from a block of its own. Add this line to your "
            f"[{THREADS_TABLE}] table: {line}"
        )

    # The wait floor.
    _decide_wait(found, facts, end)

    # The profile: written only where default_permissions is set after the run.
    sandbox = facts.outside[SANDBOX_KEY]
    theirs = facts.outside[PERMISSIONS_KEY]
    data = profile_data(want.root)
    can_select = want.default and theirs is UNSET and _valid(text, default_lines(), [], {(PERMISSIONS_KEY,): PROFILE})
    if sandbox is not UNSET:
        found.profile = SANDBOX
        found.lines.append(
            f"permission profile: not written. Your file sets {SANDBOX_KEY} = {shown(sandbox)}, and while that "
            f"key is set in any loaded config Codex uses the older sandbox settings and ignores "
            f"{PERMISSIONS_KEY}. Setup never changes or removes {SANDBOX_KEY}; {APPROVAL}"
        )
        found.printed = [
            f"the permission profile `{PROFILE}`, as text; nothing of it was written:",
            *[f"    {one}" for one in profile_lines(want.root, comments=False) if one],
            f"to use it you would, yourself: remove {SANDBOX_KEY}, and any [sandbox_workspace_write] table, "
            f"from every config Codex loads (this file, a project's .codex/config.toml, a profile file); run "
            f"render {APPLY_OPTION} again, which then writes the profile; and select it with "
            f"{PERMISSIONS_KEY} = \"{PROFILE}\" (render {DEFAULT_OPTION}) or for one launch with {PER_LAUNCH}",
            UNCERTAIN,
        ]
        if want.root is None:
            found.printed.append(_no_root())
    elif facts.profile_theirs:
        found.profile = THEIRS
        found.lines.append(
            f"permission profile: not written. Your file already defines a profile named `{PROFILE}` under "
            f"[{PERMISSIONS_TABLE}], outside setup's block; it is yours and is left alone. For the framework "
            "it needs \".git\" = \"write\" under filesystem.\":workspace_roots\", and the worktree root as "
            "a writable path"
        )
    elif theirs is UNSET and not can_select:
        found.profile = NO_DEFAULT
        found.lines.append(
            f"permission profile: not written. {REFUSES}, and after this run your file would set none"
            + ("" if want.default else f": {DEFAULT_OPTION} was not given")
            + f". Setup writes the profile only where {PERMISSIONS_KEY} is set"
        )
        found.printed = [
            f"the permission profile `{PROFILE}`, as text; nothing of it was written:",
            *[f"    {one}" for one in profile_lines(want.root, comments=False) if one],
            f"to use it: run render {APPLY_OPTION} {DEFAULT_OPTION}, which writes it and selects it with "
            f"{PERMISSIONS_KEY} = \"{PROFILE}\"; or set {PERMISSIONS_KEY} yourself (any value, a built-in such as "
            f"\"{PARENT}\" among them) and run render {APPLY_OPTION} again, which then writes it unselected, for "
            f"one launch with {PER_LAUNCH}",
            UNCERTAIN,
        ]
        if want.root is None:
            found.printed.append(_no_root())
    elif _valid(text, [], profile_lines(want.root), {(PERMISSIONS_TABLE, PROFILE): data}):
        found.profile = WRITTEN
        if end:
            end.append("")
        end += [
            f"# The permission profile `{PROFILE}`: the built-in {PARENT} profile, with write access to .git in",
            "# each workspace root, so that git's add, commit and worktree commands need no approval each.",
            "# Permission profiles are beta in Codex. This one takes effect only where it is selected:",
            f"# by {PERMISSIONS_KEY} = \"{PROFILE}\", or for one launch with {PER_LAUNCH}.",
            f"# Codex ignores every permission profile while {SANDBOX_KEY} is set in any config it loads.",
            *profile_lines(want.root),
        ]
        found.expect[(PERMISSIONS_TABLE, PROFILE)] = data
        found.lines.append(
            f"permission profile: `{PROFILE}` defined in setup's block at the end of the file: it extends "
            f"{PARENT} and makes .git of each workspace root writable"
            + ("" if want.root is None else f", and the worktree root {want.root}")
            + f". Only this file was looked at: a project's config or a profile file that sets {SANDBOX_KEY} "
            "makes Codex ignore it"
        )
        found.lines.append(UNCERTAIN)
        if want.root is None:
            found.lines.append(_no_root())
        found.lines.append(
            "a session started inside a linked git worktree commits into the .git of the main repository, "
            "which is outside that session's workspace root: start sessions in the main repository, or add "
            f"that repository's .git as a writable path to a profile of your own, per project"
        )
    else:
        found.profile = CANNOT
        found.lines.append(
            f"permission profile: not written. Your file defines `{PERMISSIONS_TABLE}` in a form that a "
            f"[{PERMISSIONS_TABLE}.{PROFILE}] table cannot be added to; add the profile there yourself"
        )

    # Its selection.
    if not want.default:
        found.selected = NOT_ASKED
        if found.profile == WRITTEN:
            # Written unselected only beside a default_permissions of the user's.
            found.lines.append(
                f"{PERMISSIONS_KEY}: your file sets it to {shown(theirs)}; setup leaves it alone. The profile is "
                f"written and not selected: start Codex with {PER_LAUNCH} for one launch, or set "
                f"{PERMISSIONS_KEY} = \"{PROFILE}\" yourself for every session"
            )
    elif found.profile == SANDBOX:
        found.selected = SANDBOX
        found.lines.append(
            f"{PERMISSIONS_KEY}: not set, for the same reason: Codex ignores it while {SANDBOX_KEY} is set"
        )
    elif found.profile == NO_DEFAULT:
        found.selected = CANNOT
        found.lines.append(f"{PERMISSIONS_KEY}: not set: the key cannot be added to your file as it is")
    elif found.profile != WRITTEN:
        found.selected = NO_PROFILE
        found.lines.append(f"{PERMISSIONS_KEY}: not set: setup selects only the profile it wrote")
    elif theirs is not UNSET:
        found.selected = USER_SET
        same = "it already names the profile" if theirs == PROFILE else (
            f"to select the profile, set it to \"{PROFILE}\" yourself, or start one launch with {PER_LAUNCH}"
        )
        found.lines.append(
            f"{PERMISSIONS_KEY}: your file sets it to {shown(theirs)}, so setup writes nothing for it and "
            f"leaves yours alone; {same}"
        )
    elif _valid(text, default_lines(), [], {(PERMISSIONS_KEY,): PROFILE}):
        found.selected = WRITTEN
        top += [
            f"# Selects the permission profile `{PROFILE}`, which setup's block at the end of this file "
            f"defines, for every session ({DEFAULT_OPTION}).",
            *default_lines(),
        ]
        found.expect[(PERMISSIONS_KEY,)] = PROFILE
        found.lines.append(
            f"{PERMISSIONS_KEY}: set to \"{PROFILE}\" in setup's block at the head of the file, so every "
            "session uses the profile"
        )
    else:
        found.selected = CANNOT
        found.lines.append(f"{PERMISSIONS_KEY}: not set: the key cannot be added to your file as it is")

    if end:
        found.end = "\n".join([*_notice("the end"), *end]) + "\n"
    if top:
        found.top = "\n".join([
            *_notice("the head"),
            "# These are top-level keys: they are here because a key written after a table belongs to that table.",
            *top,
        ]) + "\n"
    return found


def _decide_wait(found: Decision, facts: Facts, end: list[str]) -> None:
    """The wait floor, into ``found`` and the lines of the end block; see
    the module. A value of the user's is reported and never changed."""
    wait = facts.wait
    pair = f"{WAIT_MIN} = {WAIT_MIN_NEEDED}; {WAIT_DEFAULT} = {WAIT_DEFAULT_WANTED}"
    expect = {(*WAIT_PATH, WAIT_MIN): WAIT_MIN_NEEDED, (*WAIT_PATH, WAIT_DEFAULT): WAIT_DEFAULT_WANTED}
    if wait is UNSET and _valid(facts.outside_text, [], wait_table(), expect):
        found.wait = TABLE
        if end:
            end.append("")
        end += [
            f"# Codex raises a wait_agent timeout below {WAIT_MIN_NEEDED} ms to that floor, and a wait with no "
            "timeout waits the",
            "# maximum: every wake-up of a waiting agent reads its whole context again.",
            *wait_table(),
        ]
        found.expect.update(expect)
        found.lines.append(
            f"{WAIT_MIN_KEY}: set to {WAIT_MIN_NEEDED}, with {WAIT_DEFAULT} = {WAIT_DEFAULT_WANTED}, in setup's "
            "block at the end of the file: Codex raises a shorter wait to the floor, and a wait with no timeout "
            "waits the maximum"
        )
    elif wait is UNSET:
        found.wait = CANNOT
        found.lines.append(
            f"{WAIT_MIN_KEY}: not written. Your file defines `features` in a form that a [{WAIT_TABLE}] table "
            f"cannot be added to; add {WAIT_TABLE} there yourself, with these lines: {pair}"
        )
    elif not isinstance(wait, dict):
        found.wait = SWITCH
        found.lines.append(
            f"{WAIT_MIN_KEY}: not written. Your file sets {WAIT_TABLE} itself, to a value that is not a table "
            "(its value is not read; true or false is the feature's switch), and TOML allows it to be defined "
            f"once. To set the floor, make it a [{WAIT_TABLE}] table yourself, with enabled = <the switch you "
            f"had> and these lines: {pair}"
        )
    else:
        found.wait = USER_SET
        theirs = {name: facts.outside[f"{WAIT_TABLE}.{name}"] for name in WAIT_NAMES}
        said = [f"{name} = {shown(value)}" for name, value in theirs.items() if value is not UNSET]
        low = theirs[WAIT_MIN]
        if low is UNSET:
            floor = f"the floor is Codex's own {WAIT_CODEX[WAIT_MIN]} ms"
        elif _whole(low) and low >= WAIT_MIN_NEEDED:
            floor = "the floor is met"
        else:
            floor = f"the framework needs {WAIT_MIN} of {WAIT_MIN_NEEDED} or more, and raising it is yours to do"
        add: dict[str, int] = {}
        if low is UNSET:
            add[WAIT_MIN] = WAIT_MIN_NEEDED
        if theirs[WAIT_DEFAULT] is UNSET:
            high = theirs[WAIT_MAX]
            add[WAIT_DEFAULT] = high if _whole(high) else WAIT_DEFAULT_WANTED
        text = (
            f"{WAIT_TABLE}: your file defines it, outside setup's block, so setup writes nothing for the wait "
            f"floor and leaves yours alone; it sets {', '.join(said) if said else 'none of the wait keys'}; {floor}"
        )
        if add:
            text += ". Add to that table, in the form your file gives it: " + "; ".join(
                f"{name} = {value}" for name, value in add.items()
            )
        order = wait_order({**theirs, **add})
        if order:
            text += f". {'With those lines' if add else 'As it is'}, {order}: change your values so that they hold"
        found.lines.append(text)


def _no_root() -> str:
    return (
        f"no worktree root is in the profile: a worktree made beside the repository is outside the workspace "
        f"and stays read-only. Give {WORKTREE_OPTION} DIR with {APPLY_OPTION} to add the directory your "
        "worktrees are made under"
    )


def _notice(where: str) -> list[str]:
    return [
        f"# Codex settings for the agent-roles workflow, written by workflow setup at your request",
        f"# (render {APPLY_OPTION}), at {where} of this file. Setup changes nothing outside its markers and",
        f"# never touches {SANDBOX_KEY}. It reports an edit made between the markers and does not overwrite it.",
        f"# To change the block, run render {APPLY_OPTION} again; to take it out, render {REMOVE_OPTION}.",
    ]


# --- The part of render ------------------------------------------------------------

def _reach(run: Any, path: Path) -> tuple[str | None, str, bytes | None]:
    """Whether this run may write ``path``, the user's ``config.toml``: a
    status and its line where it may not, else None and the file's bytes
    (None for no file). The other side's file is skipped; a link on this
    side needs ``--follow-config-symlinks``."""
    from . import render

    standing = run.standing(path)
    if standing.kind == homes.UNKNOWN:
        return render.ERROR, f"{path}: {standing.describe()}", None
    if not standing.writes:
        return render.SKIPPED, standing.describe(), None
    if standing.through_link and not run.follow:
        return render.NEEDS_FLAG, f"{standing.describe()}; give {render.FOLLOW_OPTION} to write there", None
    try:
        seen = fsio.look(path)
        if seen.kind == fsio.ABSENT:
            return None, "", None
        if seen.kind == fsio.LINK:
            real = Path(os.path.realpath(path))
            if not os.path.lexists(real):
                return None, "", None  # the link leads nowhere yet: the file is made where it leads
            if not os.path.isfile(real):
                return render.CONFLICT, f"{path}: the link does not lead to a file", None
            return None, "", fsio.read_bytes(real)
        if seen.kind != fsio.FILE:
            return render.CONFLICT, f"{path}: a {seen.kind} is there, where the Codex config file would be", None
        return None, "", fsio.read_bytes(path)
    except SetupError as exc:
        return render.ERROR, exc.lines[0], None


def _item(run: Any, provider: Any, path: Path, name: str, status: str, says: str) -> Any:
    from . import render

    item = render.Item(name, path, status, says, key=run.roots.key(path), provider=provider.name,
                       place=homes.CONFIG, kind=KIND)
    run.items.append(item)
    return item


def _mine(item: Any, provider: Any) -> Any:
    """Make an item ``Run.block`` or ``Run.drop_block`` gave this part's:
    listed under the Codex config place, and counted as Codex settings."""
    if item is not None:
        item.provider, item.place, item.kind, item.project = provider.name, homes.CONFIG, KIND, False
    return item


def fill(run: Any) -> None:
    """The part of ``render``; see the module. Without an option of its
    own it writes nothing and removes nothing: it only takes out of the
    record a block that is no longer in the file."""
    apply = bool(run.option("apply_codex_settings", False))
    remove = bool(run.option("remove_codex_settings", False))
    root_text = run.option("worktree_root", None)
    default = bool(run.option("default_codex_permissions", False))

    wrong = []
    if apply and remove:
        wrong.append(f"{APPLY_OPTION} and {REMOVE_OPTION}: one or the other")
    if not apply:
        wrong += [
            f"{option}: goes with {APPLY_OPTION}; nothing is written to the Codex config without it"
            for option, given in ((WORKTREE_OPTION, root_text is not None), (DEFAULT_OPTION, default)) if given
        ]
    root = None
    if apply and root_text is not None:
        try:
            root = worktree_root(str(root_text))
        except SetupError as exc:
            wrong += exc.lines
    if wrong:
        run.fail(*wrong)
        return

    provider = run.homes.provider(homes.CODEX)
    if not provider.installed or not any(place.name == homes.CONFIG for place in provider.places):
        if apply or remove:
            run.notes.append("codex settings: Codex is not installed; nothing is written for it")
        return
    path = provider.place(homes.CONFIG).path
    key = run.roots.key(path)

    if not apply and not remove:
        _forget_gone(run, provider, path, key)
        return

    status, says, data = _reach(run, path)
    if status is not None:
        _item(run, provider, path, BLOCK, status, says)
        return
    facts = analyse(data)
    if facts.fault is not None:
        run.fail(
            f"{path}: {facts.fault}; setup writes nothing into a Codex config it cannot read. Repair the file "
            f"and run render {APPLY_OPTION if apply else REMOVE_OPTION} again"
        )
        return

    if remove:
        dropped = [_mine(run.drop_block(path, name), provider) for name in BLOCK_NAMES]
        if not any(item is not None for item in dropped):
            run.notes.append(f"codex settings: the record lists no block of setup's in {path}; nothing to remove")
        return

    want = Want(root, default)
    found = decide(facts, want)
    top = "" if found.top is None else found.top
    end = "" if found.end is None else found.end
    if not _valid(facts.outside_text, _lines(top), _lines(end), found.expect):
        run.fail(f"{path}: setup's blocks would not read back as intended beside the file's own text; nothing is written")
        return
    from . import render

    absent = _absent_options(facts.held, want, found)
    for name, content, place in ((BLOCK, found.end, fileops.END), (TOP_BLOCK, found.top, fileops.HEAD)):
        why = absent.get(name)
        if content is not None:
            item = _mine(run.block(provider, path, name, content, place), provider)
            if why and item.status in (render.UPDATE, render.REPLACE):
                item.says = f"{item.says}; {why}"
            continue
        item = _mine(run.drop_block(path, name), provider)
        if item is None and name == BLOCK:
            _item(run, provider, path, name, _UP_TO_DATE, "nothing for setup to write; see the notes")
        elif item is not None and why and item.status == render.REMOVE:
            item.says = f"removed, with nothing else in it: {why}"
    run.notes.extend(f"codex settings: {line}" for line in found.lines)
    # Setup's own profile files may carry the key after setup's part.
    for subject, _, keys in carried.parts(run.record):
        if SANDBOX_KEY in keys:
            run.notes.append(
                f"codex settings: {subject} sets {SANDBOX_KEY} after setup's part, so a session started with that "
                "profile uses the older sandbox settings and ignores the permission profile"
            )
    run.notes.extend(_taken_out(facts.held, want, found))
    run.notes.extend(found.printed)
    if want.root is not None and not want.root.startswith("~") and not os.path.isdir(want.root):
        run.notes.append(f"codex settings: the worktree root {want.root} is not a directory on this machine yet")


def _absent_options(held: Want | None, want: Want, found: Decision) -> dict[str, str]:
    """For each block, the part this run takes out of it because an option
    is absent, naming the option: a run writes what its own options say."""
    said: dict[str, str] = {}
    if held is None:
        return said
    if held.profile and found.profile == NO_DEFAULT and not want.default:
        said[BLOCK] = (
            f"the permission profile `{PROFILE}` is taken out, because {DEFAULT_OPTION} was not given to this run "
            f"and your file sets no {PERMISSIONS_KEY}"
        )
    elif held.root is not None and want.root is None and found.profile == WRITTEN:
        said[BLOCK] = (
            f"the worktree root {held.root} is taken out of the profile, because {WORKTREE_OPTION} was not given "
            "to this run"
        )
    if held.default and not want.default:
        said[TOP_BLOCK] = f"{PERMISSIONS_KEY} is taken out, because {DEFAULT_OPTION} was not given to this run"
    return said


def _taken_out(held: Want | None, want: Want, found: Decision) -> list[str]:
    """What this run takes out of an earlier block, and the option whose
    absence took it out, said once."""
    said = _absent_options(held, want, found)
    lines = []
    if BLOCK in said and found.profile == NO_DEFAULT:
        lines.append(
            f"codex settings: the earlier block defined the permission profile `{PROFILE}`, and this run was given "
            f"no {DEFAULT_OPTION} while your file sets no {PERMISSIONS_KEY}, so the profile is taken out: "
            f"{REFUSES}. Give the option to keep it, selected"
        )
    elif BLOCK in said:
        lines.append(
            f"codex settings: the earlier block held the worktree root {held.root}, and this run was given no "
            f"{WORKTREE_OPTION}, so the profile no longer has it; give the option again to keep it"
        )
    if TOP_BLOCK in said:
        lines.append(
            f"codex settings: the earlier run selected the profile, and this run was given no {DEFAULT_OPTION}, "
            f"so {PERMISSIONS_KEY} is taken out again; give the option again to keep it"
        )
    return lines


def _forget_gone(run: Any, provider: Any, path: Path, key: str | None) -> None:
    """A run without this part's options: a block the record lists and the
    file no longer holds is taken out of the record. Anything else, a file
    that cannot be read among it, is left exactly as it is."""
    listed = [name for name in BLOCK_NAMES if run._recorded(key, "text", "blocks", name) is not None]
    if not listed:
        return
    status, _, data = _reach(run, path)
    if status is not None:
        return
    for name in listed:
        try:
            gone = data is None or blocks.get(data, blocks.TOML, name) is None
        except blocks.Refusal:
            return
        if gone:
            run.drop_block(path, name)  # a block, as the record holds it: doctor tells it by that kind


# --- The check of doctor -----------------------------------------------------------

def _bytes(path: Path) -> bytes | None:
    seen = fsio.look(path)
    if seen.kind == fsio.ABSENT:
        return None
    if seen.kind == fsio.LINK:
        real = Path(os.path.realpath(path))
        if not os.path.isfile(real):  # ``isfile`` opens nothing: a FIFO is not one
            raise SetupError(f"{path}: the link does not lead to a file")
        return fsio.read_bytes(real)
    if seen.kind != fsio.FILE:
        raise SetupError(f"{path}: not a file that can be read: a {seen.kind} is there")
    return fsio.read_bytes(path)


def check(context: Any) -> list[Any]:
    """The check ``codex-settings`` of ``doctor``: the three keys, as
    ``doctor.check_codex_settings`` reports them, then setup's blocks by the
    record, and what ``render --apply-codex-settings`` would do now and
    would leave to the user. Nothing is written."""
    from . import doctor

    findings = list(doctor.check_codex_settings(context))
    read = doctor.codex_settings(context)
    if read is None or read.fault is not None:
        return findings
    path = read.path
    try:
        facts = analyse(_bytes(path))
    except SetupError as exc:
        return findings + [doctor.warning(f"{path}: {exc.lines[0]}", path)]
    if facts.fault is not None:
        return findings + [doctor.warning(f"{path}: {facts.fault}; setup's blocks cannot be checked", path)]

    findings.extend(_block_findings(context, path, facts))
    if facts.held is not None and facts.held.profile and facts.values[PERMISSIONS_KEY] is UNSET \
            and facts.values[SANDBOX_KEY] is UNSET:
        # Written so by an earlier setup, which defined the profile unselected.
        findings.append(doctor.error(
            f"setup's block {BLOCK} defines the permission profile `{PROFILE}` and the file sets no "
            f"{PERMISSIONS_KEY}: {REFUSES}, so Codex will not start. Fix it with render {APPLY_OPTION} "
            f"{DEFAULT_OPTION}, which selects the profile, or with render {REMOVE_OPTION}, which takes setup's "
            f"blocks out; render {APPLY_OPTION} alone takes the profile out of the block",
            f"{path}: block {BLOCK}",
        ))
    held = facts.held or Want()
    found = decide(facts, held)
    asked = f"render {APPLY_OPTION}"
    if held.root is not None:
        asked += f" {WORKTREE_OPTION} <the same directory>"
    if held.default:
        asked += f" {DEFAULT_OPTION}"
    whose = context.whose(path)
    if whose:
        findings.append(doctor.info(f"{asked}, run on this side, would skip the file:{whose}"))
    elif any(facts.found.values()) and _as_decided(facts, found):
        findings.append(doctor.info(
            f"{asked} would change nothing: setup's blocks hold what that run writes"
        ))
    else:
        findings.extend(doctor.info(f"{asked} would now: {line}") for line in found.lines if line != UNCERTAIN)
    if not whose:
        if found.printed:
            findings.append(doctor.info(
                f"{asked} would print the permission profile `{PROFILE}` as text, with what you would change "
                "to use it"
            ))
    sandbox = facts.values[SANDBOX_KEY]
    if sandbox is not UNSET and found.profile != SANDBOX:
        # Set inside a block of setup's that was edited: the user's doing all the same.
        findings.append(doctor.info(f"{SANDBOX_KEY} is set: {APPROVAL}"))
    findings.extend(_probe_findings(context, sandbox))
    return findings


def _as_decided(facts: Facts, found: Decision) -> bool:
    """Whether each of setup's blocks in the file holds exactly what
    ``found`` would write there, and no block is there that it would not."""
    for name, content in ((BLOCK, found.end), (TOP_BLOCK, found.top)):
        there = facts.found.get(name)
        if (there is None) != (content is None):
            return False
        if there is not None and content is not None:
            if there.replace(b"\r\n", b"\n") != blocks.render(blocks.TOML, name, content):
                return False
    return True


def _either_ending(block: bytes) -> set[str]:
    """The hashes a block may have in the record: of its bytes, and of the
    same lines with LF and with CRLF. A block whose line endings were
    converted with its file is setup's still (``blocks.as_written``)."""
    plain = block.replace(b"\r\n", b"\n")
    return {fsio.sha256(block), fsio.sha256(plain), fsio.sha256(plain.replace(b"\n", b"\r\n"))}


def _block_findings(context: Any, path: Path, facts: Facts) -> list[Any]:
    from . import doctor

    try:
        entry = context.record.get(context.roots.key(path) or "")
    except SetupError as exc:
        return [doctor.warning(f"setup's blocks: the install record cannot be read ({exc.lines[0]})")]
    listed = (entry or {}).get("blocks") or {} if (entry or {}).get("kind") == "text" else {}
    findings = []
    for name in BLOCK_NAMES:
        there, known = facts.found.get(name), listed.get(name)
        wrote = known.get("sha256") if isinstance(known, dict) else known
        subject = f"{path}: block {name}"
        if there is None and known is None:
            if name == BLOCK:
                findings.append(doctor.info(
                    f"setup has written no block into the file; render {APPLY_OPTION} writes one, and nothing "
                    "else does", subject,
                ))
        elif there is None:
            findings.append(doctor.info(
                f"setup's block {name}: the record lists it and it is no longer in the file; the next render "
                "takes it out of the record", subject,
            ))
        elif known is None:
            findings.append(doctor.info(
                f"setup's block {name}: its markers are in the file, and the record does not list it (written by "
                f"another install, or the record was removed); render {APPLY_OPTION} takes it over where it "
                "holds exactly what setup writes, and otherwise keeps it and reports it", subject,
            ))
        elif wrote not in _either_ending(there):
            findings.append(doctor.info(
                f"setup's block {name}: in the file, and changed by hand since setup wrote it (the check "
                "`hand-edits` says what render does with it)", subject,
            ))
        else:
            findings.append(doctor.fine(f"setup's block {name}: in the file, as setup wrote it", subject))
    return findings


def probe_lines(sandbox: Any = UNSET) -> list[str]:
    """The steps of the G4 probe, for the ``sandbox_mode`` the user's file
    sets. One session, started by the user; nothing here starts it."""
    if sandbox is UNSET:
        return [
            f"G4 probe: does not apply here: {SANDBOX_KEY} is not set in this file, so there is no older sandbox "
            f"setting for a `-c {PERMISSIONS_KEY}=...` override to be ignored in favour of"
        ]
    tight = sandbox == "read-only"
    override = PARENT if tight else ":read-only"
    command = f"codex -c \"{PERMISSIONS_KEY}='{override}'\""
    if tight:
        honoured = "the file is created without a question"
        ignored = "Codex asks for approval, or the sandbox refuses the write"
    else:
        honoured = "Codex asks for approval, or the sandbox refuses the write"
        ignored = "the file is created without a question"
    return [
        f"G4 probe: one Codex session, started by you; doctor starts none. Your config stays as it is "
        f"({SANDBOX_KEY} = {shown(sandbox)})",
        "G4 probe, step 1: make a scratch repository, outside any project: mkdir g4-probe; cd g4-probe; "
        "git init; git commit --allow-empty -m first",
        f"G4 probe, step 2: in that directory start: {command}   (the same quoting in bash, PowerShell and "
        f"cmd; the override names the built-in profile {override}, the opposite of your {SANDBOX_KEY} for a "
        "write in the workspace)",
        "G4 probe, step 3: type /status and note what it shows for the sandbox or the permissions",
        "G4 probe, step 4: ask: Create an empty file named g4-probe.txt in this directory with one shell "
        "command, and tell me exactly what happened and whether you needed approval.",
        f"G4 probe, step 4, outcome A: {ignored}: the override was ignored and {SANDBOX_KEY} decided, as the "
        "permissions page says. A permission profile then has no effect on this machine, by config or by "
        f"`-c`, until {SANDBOX_KEY} is taken out of every loaded config, which is yours to do; setup is "
        "right to write none",
        f"G4 probe, step 4, outcome B: {honoured}: the override was honoured although {SANDBOX_KEY} is set, "
        f"which is not what the page says. Then the profile can be selected for one launch ({PER_LAUNCH}) "
        f"without touching {SANDBOX_KEY}: report it, since setup's rule of writing no profile while "
        f"{SANDBOX_KEY} is set would then be looked at again",
        "G4 probe, step 5, in the same session: ask: Run `git commit --allow-empty -m probe` and tell me "
        "exactly what happened, and whether you needed approval. An approval request, or a refusal, is the "
        "command-by-command approval of git under the sandbox in effect; a commit with no question means "
        ".git is writable under it",
        "G4 probe, step 6: leave the session, note the Codex version (codex --version) with the outcomes, and "
        "remove the g4-probe directory",
    ]


def _probe_findings(context: Any, sandbox: Any) -> list[Any]:
    from . import doctor

    if not context.option("codex_probe", False):
        if sandbox is UNSET:
            return []
        return [doctor.info(
            f"gate G4 (whether this Codex ignores a `-c {PERMISSIONS_KEY}=...` override while {SANDBOX_KEY} is "
            f"set) is not proved: `doctor --only codex-settings {PROBE_OPTION}` prints the steps of the one "
            "session that shows it"
        )]
    return [doctor.info(line) for line in probe_lines(sandbox)]
