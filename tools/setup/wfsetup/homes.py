"""The providers' homes of a run, which side owns each path, and the clone.

How a command uses it

    homes.add_arguments(parser)                     # --allow-unshared-clone
    found = homes.resolve(locations.from_args(args))
    homes.require_shared_clone(found, args.allow_unshared_clone)   # before a write
    roots = found.roots()                           # with a home's own anchor
    sorter = homes.Classifier(found)
    for provider in found.installed():
        place = provider.place(homes.SKILLS)
        standing = sorter.standing(place.path / "json-tools")
        if not standing.writes:
            print(standing.describe()); continue    # the other side's, or done
        entry = sorter.entry(place.path / "json-tools")
        ...                                         # then a fileops.Plan

    homes.report(found)                             # what the homes command prints
    homes.child_environment(found)                  # the environment of a provider's program

Nothing here writes. Nothing here opens a file of a home: a path is looked
at (``lstat``), a link's text is read, a directory's names are listed.

Sides
    A machine has one side or two. ``linux`` is a Linux with no Windows
    beside it; ``wsl`` and ``windows`` are the two sides of one machine. A
    run handles the homes of the side it runs on, and only those.

    WSL is told by the kernel release (``/proc/sys/kernel/osrelease``
    holds "microsoft" on WSL 1 and 2): the kernel says it, whatever the
    environment of the process is and whether or not Windows programs can
    be started. A kernel built by the user may not say so, so the
    ``WSLInterop`` entry of ``binfmt_misc``, which WSL registers, counts as
    well. An environment variable is not asked: ``sudo`` and ``cron`` drop
    ``WSL_DISTRO_NAME``.

    A path is on the other side when its real path is there:
      from WSL      under a mount point of a Windows drive, read from the
                    mount table (a ``drvfs`` file system), and under
                    ``/mnt/<letter>/`` whether mounted or not, so that a
                    link to an unmounted drive is not taken for this side;
      from Windows  under ``\\\\wsl.localhost\\`` or ``\\\\wsl$\\``.
    No drive letter and no user name is part of the test.

Homes (checked 2026-10-05)
    Claude Code   ``CLAUDE_CONFIG_DIR``, else ``~/.claude``; on Windows
                  ``~`` is ``%USERPROFILE%`` (code.claude.com/docs/en/settings,
                  "Configuration directory"; .../env-vars). Skills in
                  ``skills/`` (.../skills), role definitions in ``agents/``
                  (.../sub-agents), rules in ``rules/`` and the user's
                  instructions in ``CLAUDE.md`` (.../memory). The pages
                  write these as ``~/.claude/...``; that each moves with
                  ``CLAUDE_CONFIG_DIR`` is read from "to keep the
                  home-directory files somewhere else" and is not said of
                  each directory by name.
    Codex         ``CODEX_HOME``, else ``~/.codex``
                  (learn.chatgpt.com/docs/agent-configuration/agents-md);
                  on Windows ``%USERPROFILE%\\.codex``
                  (.../windows/windows-app). ``AGENTS.md`` and
                  ``config.toml`` (.../config-file/config-basic) and
                  ``agents/`` (.../agent-configuration/subagents) are in
                  it, and so is a profile, ``<name>.config.toml``, which
                  ``codex --profile <name>`` reads
                  (.../config-file/config-advanced: "Create a separate TOML
                  file for each profile", at
                  ``~/.codex/profile-name.config.toml``); the place
                  ``profiles`` is the Codex home itself. User skills are not: they are in
                  ``$HOME/.agents/skills`` (.../build-skills), whatever
                  ``CODEX_HOME`` is.
                  UNVERIFIED: no page says where user skills are on
                  Windows. The Codex source joins ``.agents\\skills`` to the
                  home directory, so ``%USERPROFILE%\\.agents\\skills`` is
                  used here; gate G7 proves or refutes it (P6.3).
    ``--home DIR`` makes DIR the user's home and the providers' homes
    ``DIR/.claude`` and ``DIR/.codex``; the two variables are not read.

    A provider counts as installed when its program is on ``PATH`` or its
    home exists.

    A provider's program started for a scratch home must not read the real
    one. ``child_environment`` is the one place the environment of every
    such program is built: for a scratch home it is the caller's with
    ``HOME`` (and ``USERPROFILE`` on Windows), ``CODEX_HOME`` and
    ``CLAUDE_CONFIG_DIR`` pointed at the scratch home and its provider
    homes; for the real home it is the caller's, untouched. The model list,
    the version check, the collaboration skill's doctor and the discovery
    probes all start their program with it.

    A home that a variable puts outside the user's home gets an anchor of
    its own in the install record, ``claude-code-home:`` or ``codex-home:``,
    the same in every run (``Homes.roots``).

What ``Classifier.standing`` says of a path setup would write
    this-side    Nothing between the home and the path is a link, and the
                 path is on this side. Written by this run.
    shared       The path is, or lies under, a link that leads elsewhere on
                 this side: into another home, as a rule. Written once, by
                 this run, where the link leads. ``fileops`` writes through
                 a link only with ``--follow-config-symlinks``; without it
                 the plan is refused, as for any linked config path.
    handled      The real path is one this classifier already answered for
                 under another name: two homes share the directory. Not
                 written again (R6.10: once where two homes share).
    other-side   The real path is on the other side's file system. This run
                 skips it and says that side owns it; ``doctor`` only reads
                 it. The run on the other side writes it.
    unknown      The path could not be looked at. Nothing is written.

What ``Classifier.entry`` says of what is at a path now
    absent            nothing; a link may be created
    own-setup         a skill that has a setup of its own (R1.2), whatever
                      is there: never created, changed or removed here
    plain             a file or directory of its own: a copy
    link-to-clone     a link into the clone this run uses
    link-this-side    a link to somewhere else on this side
    link-other-side   a link whose target is on the other side
    link-broken       a link that leads nowhere on this side
    unknown           could not be looked at
    Whether setup made an entry is the record's to say, not this module's:
    ``fileops`` creates a link only where nothing is, or where the record
    shows its own link, and anything else stops the plan as a conflict.
    A link is an entry of the directory it is in, so a link in this side's
    home is this side's to remove (as a link, its text kept in the record)
    even when it leads to the other side. What it leads to is not.

The clone (R6.9)
    The clone is the one the tool runs from. Against the real homes of a
    machine with two sides it must be readable by both: from WSL its real
    path is on a Windows drive; on Windows its real path is on a drive
    letter and not under a UNC name (``os.path.realpath`` turns a mapped
    network drive into its UNC name). ``require_shared_clone`` refuses
    anything else unless ``--allow-unshared-clone`` is given. A scratch
    home, and a Linux with no Windows side, are not checked.

Links
    ``fileops.Plan.create_link`` makes them, ``fsio`` knows how: a symlink
    on Linux, a junction on Windows. The link's text is the clone's path as
    this side writes it (from WSL ``/mnt/<drive>/...``, on Windows the
    drive path): the directory it is in is read by this side only. The
    record holds the target as ``clone:<relative path>``.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import fileops, fsio, paths
from .errors import SetupError
from .locations import Locations
from .manifest import Roots

LINUX = "linux"
WSL = "wsl"
WINDOWS = "windows"

CLAUDE_CODE = "claude-code"
CODEX = "codex"

# The places of a home.
SKILLS = "skills"
AGENTS = "agents"
RULES = "rules"
INSTRUCTIONS = "instructions"
CONFIG = "config"
OLD_SKILLS = "old-skills"
PROFILES = "profiles"

# Where a home came from.
FROM_OPTION = "--home"
FROM_DEFAULT = "default"

# A skill with a setup of its own (R1.2).
OWN_SETUP_SKILLS = frozenset({"multiagent-collab"})

# Standings.
THIS_SIDE = "this-side"
SHARED = "shared"
HANDLED = "handled"
OTHER_SIDE = "other-side"
# Through a link, to a place setup changes under no option: outside the
# homes of the run, or inside a clone. ``render`` says so for the place.
OUTSIDE = "outside"
UNKNOWN = "unknown"

# Entries.
ABSENT = "absent"
OWN_SETUP = "own-setup"
PLAIN = "plain"
LINK_TO_CLONE = "link-to-clone"
LINK_THIS_SIDE = "link-this-side"
LINK_OTHER_SIDE = "link-other-side"
LINK_BROKEN = "link-broken"

REPORT_SCHEMA_VERSION = 1

_OSRELEASE = "/proc/sys/kernel/osrelease"
_INTEROP = ("/proc/sys/fs/binfmt_misc/WSLInterop", "/proc/sys/fs/binfmt_misc/WSLInterop-late")
_MOUNTS = "/proc/self/mounts"
_DRIVE_MOUNT = re.compile(r"/mnt/[A-Za-z](/|$)")
_WSL_SHARES = ("\\\\wsl.localhost\\", "\\\\wsl$\\")


# --- The side -----------------------------------------------------------------

def is_wsl(release: str, interop: bool) -> bool:
    """Whether a Linux with this kernel release is WSL; see the module."""
    return "microsoft" in release.lower() or interop


def _read_small(file: str) -> str:
    try:
        with open(file, "r", encoding="utf-8", errors="replace") as stream:
            return stream.read(1 << 20)
    except OSError:
        return ""


def detect_side() -> str:
    if os.name == "nt":
        return WINDOWS
    release = _read_small(_OSRELEASE)
    return WSL if is_wsl(release, any(os.path.exists(entry) for entry in _INTEROP)) else LINUX


def drive_mounts(table: str) -> tuple[str, ...]:
    """The mount points of Windows drives in a mount table (the text of
    ``/proc/self/mounts``). WSL 1 mounts a drive as ``drvfs``; WSL 2 as
    ``9p`` with ``aname=drvfs`` among the options. Other ``9p`` mounts of
    WSL (its drivers, its GUI) are not drives."""
    found = []
    for line in table.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        kind, options = fields[2], fields[3]
        if kind == "drvfs" or (kind == "9p" and "aname=drvfs" in options):
            # The table writes a space, a tab, a newline and a backslash in
            # a name as a backslash and three octal digits.
            found.append(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), fields[1]))
    return tuple(found)


def _under(text: str, base: str) -> bool:
    base = base.rstrip("/")
    return bool(base) and (text == base or text.startswith(base + "/"))


@dataclass(frozen=True)
class Host:
    """The machine as a run sees it: the side, the environment, and on WSL
    where the Windows drives are mounted. A test builds one by hand."""

    side: str
    environ: Mapping[str, str] = field(default_factory=dict)
    mounts: tuple[str, ...] = ()

    @classmethod
    def current(cls) -> "Host":
        side = detect_side()
        mounts = drive_mounts(_read_small(_MOUNTS)) if side == WSL else ()
        return cls(side, dict(os.environ), mounts)

    @property
    def other(self) -> str | None:
        """The name of the other side; None where there is none."""
        return {WSL: WINDOWS, WINDOWS: WSL}.get(self.side)

    def foreign(self, text: str) -> bool:
        """Whether the absolute path ``text`` is on the other side's file
        system. Only the text is looked at; give a real path."""
        if self.side == WSL:
            return bool(_DRIVE_MOUNT.match(text)) or any(_under(text, mount) for mount in self.mounts)
        if self.side == WINDOWS:
            plain = fsio.clean_target(text).replace("/", "\\").lower()
            return plain.startswith(_WSL_SHARES)
        return False

    def other_side(self, path: Path | str) -> str | None:
        """The other side's name when the real path of ``path`` is on its
        file system, else None. A link that leads nowhere is followed as
        far as its text goes."""
        return self.other if self.foreign(os.path.realpath(path)) else None


# --- The homes ----------------------------------------------------------------

@dataclass(frozen=True)
class Place:
    """One named path of a home that setup uses."""

    name: str
    path: Path
    directory: bool


@dataclass(frozen=True)
class Provider:
    name: str
    program: str
    home: Path
    home_from: str            # FROM_OPTION, FROM_DEFAULT, or the variable's name
    program_file: str | None  # where the program was found on PATH
    home_exists: bool
    places: tuple[Place, ...]
    anchor: str | None        # the home's own anchor, when it is outside the user's home

    @property
    def installed(self) -> bool:
        return self.program_file is not None or self.home_exists

    def place(self, name: str) -> Place:
        for place in self.places:
            if place.name == name:
                return place
        raise SetupError(f"{self.name}: has no place called {name}")


@dataclass(frozen=True)
class Homes:
    """The installed providers and their homes, for one run."""

    host: Host
    home: Path
    scratch: bool
    clone: Path
    project: Path | None
    providers: tuple[Provider, ...]

    def provider(self, name: str) -> Provider:
        for provider in self.providers:
            if provider.name == name:
                return provider
        raise SetupError(f"{name}: not a provider setup knows")

    def installed(self) -> list[Provider]:
        return [provider for provider in self.providers if provider.installed]

    @property
    def extra(self) -> dict[str, Path]:
        return {provider.anchor: provider.home for provider in self.providers if provider.anchor is not None}

    def roots(self) -> Roots:
        """The roots of the run, for ``fileops`` and the record."""
        return Roots(self.home, self.project, self.clone, tuple(self.extra.items()))


def child_environment(homes: Homes) -> dict[str, str]:
    """The environment of every program started for the homes of a run;
    see the module. A copy: the caller may add to it."""
    environ = dict(homes.host.environ)
    # What stops this process for a crash test is not handed to a program
    # it starts.
    environ.pop(fsio.STOP_VARIABLE, None)
    if homes.scratch:
        environ["HOME"] = str(homes.home)
        if os.name == "nt":
            environ["USERPROFILE"] = str(homes.home)
        environ["CODEX_HOME"] = str(homes.provider(CODEX).home)
        environ["CLAUDE_CONFIG_DIR"] = str(homes.provider(CLAUDE_CODE).home)
    return environ


def add_arguments(parser: Any) -> None:
    """Add ``--allow-unshared-clone``, which means the same in every
    command that installs: ``require_shared_clone(homes, args.allow_unshared_clone)``."""
    parser.add_argument(
        "--allow-unshared-clone",
        action="store_true",
        help="install from a clone that only this side can read. Without it, on a machine with "
        "a Windows side and a WSL side, a clone that both cannot read is refused: every home "
        "links to one shared clone. Not asked with --home",
    )


def _home_from_variable(host: Host, variable: str) -> Path | None:
    text = host.environ.get(variable, "")
    if not text.strip():
        return None  # unset, or set to nothing
    try:
        path = Path(text).expanduser()
    except (RuntimeError, KeyError):
        raise SetupError(f"{variable}: {text}: the home directory of that user cannot be found") from None
    if not path.is_absolute():
        raise SetupError(f"{variable}: {text}: not an absolute path; setup will not guess which directory it means")
    return paths.absolute(path)


def _program(host: Host, program: str) -> str | None:
    search = host.environ.get("PATH", "")
    if not search:
        return None
    try:
        return shutil.which(program, path=search)
    except (OSError, ValueError):
        return None


def _exists(path: Path) -> bool:
    try:
        return paths.kind(path) == paths.DIRECTORY
    except SetupError:
        return True  # something is there, readable or not


def _anchor(name: str, home: Path, user_home: Path) -> str | None:
    inside = Roots(user_home).key(home) is not None
    return None if inside else f"{name}-home"


def resolve(locations: Locations, host: Host | None = None) -> Homes:
    """The homes of the run that ``locations`` describes."""
    host = Host.current() if host is None else host
    user_home = paths.absolute(locations.home)
    scratch = not locations.real_home

    def home_of(variable: str, default: str) -> tuple[Path, str]:
        named = None if scratch else _home_from_variable(host, variable)
        if named is not None:
            return named, variable
        return user_home / default, FROM_OPTION if scratch else FROM_DEFAULT

    claude, claude_from = home_of("CLAUDE_CONFIG_DIR", ".claude")
    codex, codex_from = home_of("CODEX_HOME", ".codex")
    providers = (
        Provider(
            name=CLAUDE_CODE, program="claude", home=claude, home_from=claude_from,
            program_file=_program(host, "claude"), home_exists=_exists(claude),
            places=(
                Place(SKILLS, claude / "skills", True),
                Place(AGENTS, claude / "agents", True),
                Place(RULES, claude / "rules", True),
                Place(INSTRUCTIONS, claude / "CLAUDE.md", False),
            ),
            anchor=_anchor(CLAUDE_CODE, claude, user_home),
        ),
        Provider(
            name=CODEX, program="codex", home=codex, home_from=codex_from,
            program_file=_program(host, "codex"), home_exists=_exists(codex),
            places=(
                # User skills are beside the Codex home, in the user's own
                # home, and do not move with CODEX_HOME. On Windows this
                # place is UNVERIFIED (see the module; gate G7).
                Place(SKILLS, user_home / ".agents" / "skills", True),
                Place(AGENTS, codex / "agents", True),
                Place(INSTRUCTIONS, codex / "AGENTS.md", False),
                Place(CONFIG, codex / "config.toml", False),
                # Deprecated, and still read by Codex: setup installs
                # nothing here; doctor and the v1 migration look at it.
                Place(OLD_SKILLS, codex / "skills", True),
                # The home itself, where a profile file goes. Last: it
                # holds the places above, and is asked for after them.
                Place(PROFILES, codex, True),
            ),
            anchor=_anchor(CODEX, codex, user_home),
        ),
    )
    clone = paths.absolute(locations.clone)
    project = None if locations.project is None else paths.absolute(locations.project)
    return Homes(host=host, home=user_home, scratch=scratch, clone=clone, project=project, providers=providers)


# --- Whose a path is ----------------------------------------------------------

@dataclass(frozen=True)
class Standing:
    """Whose a path is, for a run that would write it."""

    kind: str
    path: Path
    real: Path | None = None
    side: str | None = None     # OTHER_SIDE: the side that owns it
    link: Path | None = None    # the link the path is, or lies under
    target: str | None = None   # that link's own text
    first: Path | None = None   # HANDLED: the path that was answered for first
    reason: str | None = None   # UNKNOWN

    @property
    def writes(self) -> bool:
        """Whether this run writes the path at all."""
        return self.kind in (THIS_SIDE, SHARED)

    @property
    def through_link(self) -> bool:
        """Whether writing it means writing through a link, which
        ``fileops`` does only with ``--follow-config-symlinks``."""
        return self.kind == SHARED

    def _link(self) -> str:
        if self.link is None:
            return ""
        what = "a link" if self.link == self.path else f"under the link {self.link}"
        return f"{what} to {self.target}"

    def describe(self) -> str:
        if self.kind == THIS_SIDE:
            return "this side"
        if self.kind == SHARED:
            return f"shared, on this side: {self._link()}; written once, where the link leads"
        if self.kind == HANDLED:
            return f"shared and already handled: the same place as {self.first}"
        if self.kind == OTHER_SIDE:
            via = f"{self._link()}; " if self.link is not None else ""
            return f"other side ({self.side}): {via}skipped here, the {self.side} side owns it"
        if self.kind == OUTSIDE:
            return (
                f"{self._link()}, which leads out of the directories this run may write to: skipped, whatever the "
                f"options ({self.reason}). If that place is a provider's home, name it as one (CLAUDE_CONFIG_DIR, "
                "CODEX_HOME) or run setup with it as --home"
            )
        return f"cannot be told ({self.reason}); nothing is written"


@dataclass(frozen=True)
class Entry:
    """What is at a path now."""

    kind: str
    path: Path
    found: str | None = None    # PLAIN: file, directory or other
    target: str | None = None   # a link's own text
    real: Path | None = None
    side: str | None = None     # LINK_OTHER_SIDE
    reason: str | None = None   # UNKNOWN

    def describe(self) -> str:
        if self.kind == ABSENT:
            return "absent"
        if self.kind == OWN_SETUP:
            was = f" (a link to {self.target})" if self.target is not None else ""
            return f"managed by its own setup{was}; left alone"
        if self.kind == PLAIN:
            return f"a {self.found} of its own, not a link"
        if self.kind == LINK_TO_CLONE:
            return f"a link into the clone: {self.target}"
        if self.kind == LINK_THIS_SIDE:
            return f"a link to elsewhere on this side: {self.target}"
        if self.kind == LINK_OTHER_SIDE:
            return f"a link to the other side ({self.side}): {self.target}"
        if self.kind == LINK_BROKEN:
            return f"a link that leads nowhere: {self.target}"
        return f"cannot be told ({self.reason})"


_fold = paths.fold
_inside = paths.inside


class Classifier:
    """Answers for the paths of one run. It remembers the real paths it
    answered for, which is how a second name for one place is found; ask in
    the order the run writes."""

    def __init__(self, homes: Homes) -> None:
        self.homes = homes
        self.host = homes.host
        self.roots = homes.roots()
        self._first: dict[str, Path] = {}
        self._skill_places = {
            _fold(place.path)
            for provider in homes.providers for place in provider.places
            if place.name in (SKILLS, OLD_SKILLS)
        }
        self._clone = os.path.realpath(homes.clone)

    def standing(self, path: Path) -> Standing:
        """Whose ``path`` is: a place, or anything below a home."""
        path = paths.absolute(path)
        try:
            problem = fileops.symlink_in_the_way(self.roots, path)
            real = Path(os.path.realpath(path))
        except (SetupError, OSError, ValueError) as exc:
            return Standing(UNKNOWN, path, reason=_reason(exc))
        link = None if problem is None else problem.link
        target = None if problem is None else problem.resolves_to
        if self.host.foreign(str(real)):
            return Standing(OTHER_SIDE, path, real=real, side=self.host.other, link=link, target=target)
        first = self._first.setdefault(_fold(real), path)
        if _fold(first) != _fold(path):
            return Standing(HANDLED, path, real=real, link=link, target=target, first=first)
        if problem is None:
            return Standing(THIS_SIDE, path, real=real)
        return Standing(SHARED, path, real=real, link=link, target=target)

    def entry(self, path: Path) -> Entry:
        """What is at ``path`` now, the link itself and not what it leads
        to."""
        path = paths.absolute(path)
        try:
            seen = fsio.look(path)
        except SetupError as exc:
            return Entry(UNKNOWN, path, reason=_reason(exc))
        if paths.fold_key(path.name) in OWN_SETUP_SKILLS and _fold(path.parent) in self._skill_places:
            return Entry(OWN_SETUP, path, target=seen.target)
        if seen.kind == fsio.ABSENT:
            return Entry(ABSENT, path)
        if seen.kind != fsio.LINK:
            return Entry(PLAIN, path, found=seen.kind)
        real = Path(os.path.realpath(path))
        # The clone first: seen from WSL the shared clone is on a Windows
        # drive, and a link into it is setup's kind of link all the same.
        if _inside(real, self._clone) and os.path.exists(real):
            return Entry(LINK_TO_CLONE, path, target=seen.target, real=real)
        if self.host.foreign(str(real)):
            return Entry(LINK_OTHER_SIDE, path, target=seen.target, real=real, side=self.host.other)
        if not os.path.exists(real):
            return Entry(LINK_BROKEN, path, target=seen.target, real=real)
        return Entry(LINK_THIS_SIDE, path, target=seen.target, real=real)


def _reason(exc: BaseException) -> str:
    return exc.lines[0] if isinstance(exc, SetupError) and exc.lines else paths.reason(exc)


# --- The clone ----------------------------------------------------------------

@dataclass(frozen=True)
class CloneStanding:
    """``shared`` is True, False, or None where the question is not asked."""

    path: Path
    real: Path
    shared: bool | None
    why: str


def clone_standing(homes: Homes) -> CloneStanding:
    """Whether both sides can read the clone; see the module."""
    path = homes.clone
    real = Path(os.path.realpath(path))
    host = homes.host
    if homes.scratch:
        return CloneStanding(path, real, None, "not asked: a scratch home (--home)")
    if host.side == LINUX:
        return CloneStanding(path, real, None, "not asked: this machine has no Windows side")
    if host.side == WSL:
        if host.foreign(str(real)):
            return CloneStanding(path, real, True, "on a Windows drive, which both sides read")
        return CloneStanding(path, real, False, "inside WSL, where the Windows side's links cannot lead")
    if host.foreign(str(real)):
        return CloneStanding(path, real, False, "inside WSL, reached over the network name; a junction cannot lead there")
    if fsio.local_drive_path(str(real)):
        return CloneStanding(path, real, True, "on a local drive, which both sides read")
    return CloneStanding(path, real, False, "not on a local drive; a junction cannot lead there")


def require_shared_clone(homes: Homes, allow_unshared: bool = False) -> CloneStanding:
    """Refuse a clone that both sides cannot read (R6.9), unless
    ``allow_unshared``. To be called before a command writes."""
    found = clone_standing(homes)
    if found.shared is False and not allow_unshared:
        raise SetupError(
            f"{found.real}: the clone setup runs from is {found.why}. Every home, on Windows and in "
            "WSL, links to one clone that both can read",
            "clone the repository to a directory on a Windows drive (seen from WSL under "
            "/mnt/<drive>/) and run setup from that clone, on each side",
            "or give --allow-unshared-clone to install from this clone for this side alone",
        )
    return found


# --- The report ---------------------------------------------------------------

def _text(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _listed(standing: Standing, place: Place) -> bool:
    """Whether the names in a place are listed: a directory of this side.
    The other side's directory is left to the other side's run. The Codex
    home itself is not listed: what it holds beside setup's files (sessions,
    logs, the user's configuration) is no entry setup would make or meet."""
    return place.directory and standing.writes and place.name != PROFILES


def report(homes: Homes) -> dict[str, Any]:
    """Everything this module knows of a run, as plain data: what the
    ``homes`` command prints and ``doctor`` starts from. It reads no file."""
    sorter = Classifier(homes)
    clone = clone_standing(homes)
    providers = []
    for provider in homes.providers:
        places = []
        for place in provider.places:
            standing = sorter.standing(place.path)
            entries = []
            if _listed(standing, place):
                try:
                    names = paths.entries(place.path)
                except SetupError:
                    names = []
                for item in names:
                    if fsio.is_credentials(item):
                        continue
                    entry = sorter.entry(item)
                    entries.append({
                        "name": item.name, "kind": entry.kind, "target": entry.target,
                        "real": _text(entry.real), "side": entry.side, "says": entry.describe(),
                    })
            try:
                present = fsio.look(place.path).kind != fsio.ABSENT
            except SetupError:
                present = True
            places.append({
                "name": place.name, "path": str(place.path), "directory": place.directory,
                "present": present, "standing": standing.kind, "writes": standing.writes,
                "side": standing.side, "link": _text(standing.link), "target": standing.target,
                "real": _text(standing.real), "first": _text(standing.first), "says": standing.describe(),
                "entries": entries,
            })
        providers.append({
            "name": provider.name, "installed": provider.installed, "program": provider.program,
            "program_file": provider.program_file, "home": str(provider.home),
            "home_from": provider.home_from, "home_exists": provider.home_exists,
            "anchor": provider.anchor, "places": places,
        })
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "side": homes.host.side,
        "other_side": homes.host.other,
        "home": str(homes.home),
        "scratch": homes.scratch,
        "clone": {"path": str(clone.path), "real": str(clone.real), "shared": clone.shared, "why": clone.why},
        "providers": providers,
    }


def report_lines(found: dict[str, Any]) -> list[str]:
    """The report as text, one fact per line."""
    other = found["other_side"]
    lines = [
        f"side: {found['side']}" + (f" (the other side is {other})" if other else " (no other side)"),
        f"home: {found['home']}" + (" (scratch, --home)" if found["scratch"] else ""),
    ]
    clone = found["clone"]
    shared = {True: "yes", False: "no", None: "not asked"}[clone["shared"]]
    why = clone["why"].removeprefix("not asked: ")
    lines.append(f"clone: {clone['real']}")
    lines.append(f"  shared by both sides: {shared} ({why})")
    for provider in found["providers"]:
        program = provider["program_file"] or "not on PATH"
        there = "exists" if provider["home_exists"] else "does not exist"
        lines.append("")
        lines.append(f"{provider['name']}: {'installed' if provider['installed'] else 'not installed'}")
        lines.append(f"  program {provider['program']}: {program}")
        anchor = f", anchor {provider['anchor']}:" if provider["anchor"] else ""
        lines.append(f"  home: {provider['home']} ({provider['home_from']}; {there}{anchor})")
        for place in provider["places"]:
            present = "" if place["present"] else " [absent]"
            lines.append(f"  {place['name']}: {place['path']}{present}")
            lines.append(f"    {place['says']}")
            for entry in place["entries"]:
                lines.append(f"    - {entry['name']}: {entry['says']}")
    return lines
