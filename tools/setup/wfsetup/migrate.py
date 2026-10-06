"""What a v1 install left in a home, and how ``render --migrate-v1`` removes it.

How it is used

    render.PARTS = (..., Part("migrate", migrate.fill, migrate.configure))
    migrate.cleared(run, path)        # Run.link: this plan removes what is there
    migrate.conflict(run, path)       # Run.link: a conflict's wording, for a v1 leftover
    migrate.report(run)               # the "migration" object of the report
    migrate.lines(report)             # the same as text
    migrate.left(run)                 # how many kept items an option would remove
    migrate.findings(context)         # doctor's check ``v1``
    migrate.leftover_paths(context)   # doctor's check ``missing`` leaves these to ``v1``

v1 (the repository's README at tag ``v1.0``) was installed by hand: the
skills by cloning the repository into a skills directory or by copying or
linking one skill directory; the rules ``prd-implementation.md``,
``epic-implementation.md`` and ``avoid-bash-injection-heuristics.md`` by
copying or linking each file into the Claude Code ``rules`` directory; the
agent by copying or linking ``agents/sprint-coder.md`` into ``agents``; and
the two process rules by ``@rules/...`` import lines in ``CLAUDE.md``.

The places looked at, in each installed provider's home
    rules/<one of the three rule files>                Claude Code
    agents/sprint-coder.md                             Claude Code
    <a skills place>/<name>                            both providers: the
        place setup links into, and for Codex the deprecated
        ``<codex home>/skills`` as well. The names are the four v1 skills
        (``V1_SKILLS``) and the two skills that replace the v1 rules
        (``PROCESS_SKILLS``): a hand-kept skill-shaped copy of a v1 rule.
    a directory in a skills place that is a git clone  reported, see below
    the two import lines in ``CLAUDE.md``              Claude Code
    Nothing else is a v1 location, and ``--remove-stale`` refuses any other
    path. A skill with a setup of its own is never looked at.

What is there, and what becomes of it
    known         A regular file whose SHA-256 is that of a committed
                  version of the file it is named after
                  (``v1-known-hashes.json``, LF or CRLF); a skill directory
                  in which every file is a committed version of that
                  skill's file at the same path and which holds nothing
                  else; a v1 link (below). Removed: a file after a backup,
                  a link as a link.
    edited        A file that matches no committed version; a skill
                  directory with a file that differs or is not the skill's,
                  a link, or an empty directory inside. Kept and reported
                  with the files that differ. ``--remove-stale PATH``
                  removes it: every file after a backup, every link as a
                  link, then the directories.
    unrecognised  A link whose target is not recognised. Kept; removed (the
                  link, never its target) with ``--remove-stale PATH``.
    clone         A directory with a ``.git`` entry, or one that holds what
                  a clone of this repository holds (``doctor.holds_clone``):
                  never removed, with or without the option. It is the
                  user's to move away. A skills place that is such a
                  directory, or whose real path lies inside one (the clone
                  setup runs from among them), is a clone as a whole:
                  nothing in it is looked at, and nothing is written there.

    A copy an interrupted run was removing
        A run that is stopped between the files of a known copy and its
        directory leaves a directory with fewer files, or none, and the
        record holds each removed file (``removed-file``). Such a directory
        is setup's own work in progress and not an edited copy: what is
        left of it is "known" while every file still there is a committed
        version, and the next run finishes the removal.
    Inside a skill copy a ``__pycache__`` directory that holds only
    ``.pyc`` and ``.pyo`` files is what running the skill's scripts left:
    it does not make the copy "edited", and it goes with the copy, each
    file after a backup like any other. An editor's leftover, or any other
    unknown file, does. A credentials file, a link whose text names one,
    or an entry that is neither a file, a directory nor a link, is never
    touched: such a copy is kept and ``--remove-stale`` refuses it.

A v1 link
    A link is removed as a link and never followed. It is a v1 link, and
    removed without being asked for, only when
      - it is at a rule's or the agent's place and leads to a regular file
        whose hash is known: a copy, or a clone's own file; or
      - it is at a skill's place and leads to a directory in which every
        file is a known committed version (a copy, wherever it is: another
        home's among them, as from a WSL home into the Windows home); or
      - it is at a skill's place, its target has the skill's name, and it
        leads into the clone this run uses; or
      - it leads nowhere, its target ends in the v1 file's own path
        (``agents/sprint-coder.md``, the rule's file name, the skill's
        name) and names a place inside the clone this run uses, which
        moved on to v2.
    Every other link is "unrecognised", into whatever tree it leads:
    another clone of this repository, a git tree of the user's that holds
    a skill of a v1 skill's name, a directory that is gone. It is kept and
    reported, and goes with ``--remove-stale``. One link is never removed,
    with the option or without: a link whose text names a credentials
    file. Setup makes no link to such a file, so it could not put this one
    back; it is reported, and is the user's to remove.

Whose a place is
    As everywhere in ``render``: a place whose real path is on the other
    side is skipped and reported (``doctor`` reads it and says it is that
    side's to migrate); one under a link on this side needs
    ``--follow-config-symlinks``.

The instructions files
    ``CLAUDE.md``: the lines ``@rules/prd-implementation.md`` and
    ``@rules/epic-implementation.md`` are removed, exactly those and only
    whole lines, and the pointer block ``process`` is added at the end.
    ``AGENTS.md`` of Codex: the same block. A file that is not there is
    created holding the block alone: the pointer is as useful there, and
    the way back removes a file setup created. A block edited by hand since
    setup wrote it is kept and reported, as ``render`` does for any block;
    ``--overwrite-edited`` writes it again.

One plan with the other parts
    What this part removes at a path where another part then links must be
    in the plan before that link. So the part plans when it is first asked:
    ``Run.link`` asks ``cleared`` before it looks at what is in the way,
    which plans the whole migration then, whatever the part's place in
    ``render.PARTS`` is; ``fill`` plans only if no link asked first. An
    entry the plan clears is not a conflict for ``Run.link``, and
    ``fileops`` keeps what was removed in the link's own entry
    (``replaced``) for the way back.

Nothing here writes: ``fill`` adds actions to the run's plan.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import blocks, fileops, fsio, homes, locations, paths
from .errors import SetupError

KNOWN_FILE = Path(__file__).resolve().parents[1] / "v1-known-hashes.json"
KNOWN_SCHEMA = 1

MIGRATE_OPTION = "--migrate-v1"
STALE_OPTION = "--remove-stale"

# The v1 files, by the path each had in the repository.
PROCESS_RULES = ("prd-implementation.md", "epic-implementation.md")
BASH_RULE = "avoid-bash-injection-heuristics.md"
BASH_RULE_NOW = "rules/avoid-bash-injection-heuristics/avoid-bash-injection-heuristics.md"
# A rule file in a home's ``rules``, to the repository paths whose committed
# versions it may be a copy of.
V1_RULES: dict[str, tuple[str, ...]] = {
    "prd-implementation.md": ("prd-implementation.md",),
    "epic-implementation.md": ("epic-implementation.md",),
    BASH_RULE: (BASH_RULE, BASH_RULE_NOW),
}
V1_AGENT = "sprint-coder.md"
V1_AGENT_SOURCE = "agents/sprint-coder.md"
V1_SKILLS = ("csv-tools", "json-tools", "self-reflection", "usage-cost")
PROCESS_SKILLS = ("prd-implementation", "epic-implementation")

IMPORT_LINES = tuple(f"@rules/{name}" for name in PROCESS_RULES)
BLOCK_NAME = "process"
POINTER = (
    "Sprint and epic work follows two skills: `prd-implementation` (one sprint, from the backlog to\n"
    "completion) and `epic-implementation` (an effort of several sprints). Both are installed as\n"
    "skills and are invoked by their names; load the one that applies before starting, planning or\n"
    "implementing a sprint or an epic.\n"
)

# What a location holds.
RULE = "rule"
AGENT = "agent"
SKILL = "skill"
CLONE = "clone"

# What became of what is there.
KNOWN = "known"
EDITED = "edited"
UNRECOGNISED = "unrecognised"

# An item's status in the report.
REMOVE = "remove"
EDIT = "edit"
UP_TO_DATE = "up-to-date"
KEPT = "kept"
NEVER = "never-removed"
SKIPPED = "skipped"
NEEDS_FLAG = "needs-flag"

ERROR = "error"
INFO = "info"

SKILL_FILE = "SKILL.md"
_DERIVED_DIRECTORY = "__pycache__"
_DERIVED_SUFFIXES = (".pyc", ".pyo")
_SHOWN = 5

DANGLING = (
    "project-level links to the removed rule copies will dangle: a project whose .claude/rules/ links to a "
    "rule file in this directory loses that rule. Setup does not know which projects do, and does not migrate "
    "a project; look for such links, and remove them or point the project at the skills"
)


# --- The known hashes ------------------------------------------------------------

@dataclass(frozen=True)
class Known:
    """The committed versions: a repository path to the hashes of its
    versions, LF and CRLF."""

    files: dict[str, frozenset[str]]
    built_from: str | None = None

    def matches(self, sources: tuple[str, ...], digest: str) -> bool:
        return any(digest in self.files.get(source, ()) for source in sources)

    def has(self, source: str) -> bool:
        return source in self.files


_cache: dict[str, Known] = {}


def load_known(file: Path) -> Known:
    # Looked at before it is opened: a FIFO there would block the read.
    if paths.kind(file) != paths.FILE:
        raise SetupError(f"{file}: not a file; the list of v1 hashes is part of the clone, which is incomplete")
    try:
        data = json.loads(file.read_bytes().decode("utf-8"))
    except OSError as exc:
        raise SetupError(f"{file}: cannot be read: {paths.reason(exc)}") from None
    except ValueError as exc:
        raise SetupError(f"{file}: is not valid JSON: {' '.join(str(exc).split())}") from None
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict) or data.get("schema_version") != KNOWN_SCHEMA or not all(
        isinstance(hashes, list) and all(isinstance(one, str) for one in hashes) for hashes in files.values()
    ):
        raise SetupError(f"{file}: is not a list of v1 hashes this setup reads (schema_version {KNOWN_SCHEMA})")
    built = data.get("built_from")
    return Known({name: frozenset(hashes) for name, hashes in files.items()}, built if isinstance(built, str) else None)


def known() -> Known:
    """The hashes of ``KNOWN_FILE``, read once."""
    ident = str(KNOWN_FILE)
    if ident not in _cache:
        _cache[ident] = load_known(KNOWN_FILE)
    return _cache[ident]


# --- What is there ---------------------------------------------------------------

@dataclass
class Found:
    """One v1 leftover: what is at one v1 location, or a clone."""

    provider: str
    place: str
    path: Path
    what: str                      # RULE, AGENT, SKILL, CLONE
    name: str
    entry: str                     # fsio.FILE, DIRECTORY or LINK
    state: str                     # KNOWN, EDITED, UNRECOGNISED, CLONE
    says: str                      # what it is, without the path
    standing: homes.Standing
    target: str | None = None      # a link's own text
    files: list[tuple[Path, str]] = field(default_factory=list)   # each file with its hash
    links: list[tuple[Path, str]] = field(default_factory=list)   # each link inside with its text
    directories: list[Path] = field(default_factory=list)         # deepest first, the path itself last
    differs: list[str] = field(default_factory=list)
    blocked: str | None = None     # why not even --remove-stale removes it

    @property
    def mine(self) -> bool:
        return self.standing.writes

    @property
    def rule(self) -> bool:
        return self.what == RULE


def fold(path: Path | str) -> str:
    return paths.fold(paths.absolute(path))


def quoted(path: Path | str) -> str:
    text = os.fspath(path)
    if os.name == "nt":
        return f'"{text}"' if re.search(r"\s", text) else text
    return shlex.quote(text)


def stale_flag(path: Path | str) -> str:
    """The command that removes a kept item, as the user types it."""
    return f"render {MIGRATE_OPTION} {STALE_OPTION} {quoted(path)}"


def _named(what: str, name: str) -> str:
    if what == RULE:
        return f"the v1 rule {name}"
    if what == AGENT:
        return "the v1 agent sprint-coder"
    if name in PROCESS_SKILLS:
        return f"the skill {name} (a hand-kept, skill-shaped copy of v1)"
    return f"the v1 skill {name}"


def _sources(what: str, name: str) -> tuple[str, ...]:
    if what == RULE:
        return V1_RULES[name]
    return (V1_AGENT_SOURCE,)


def _several(names: list[str]) -> str:
    shown = ", ".join(names[:_SHOWN])
    return shown + (f" and {len(names) - _SHOWN} more" if len(names) > _SHOWN else "")


def _is_clone(directory: Path, skills: Any = ()) -> bool:
    """``doctor``'s rule for another clone of this repository, by what the
    directory holds; git is not asked."""
    from . import doctor  # not at import: doctor imports render, which imports this module
    return doctor.holds_clone(directory, skills)


def _git(directory: Path) -> bool:
    return os.path.lexists(directory / ".git")


def clone_around(path: Path, skills: Any, clone: Path | None = None) -> Path | None:
    """The clone that the real path of ``path`` is, or lies inside: the
    clone setup runs from, a directory with a ``.git`` entry, or one that
    holds what a clone of this repository holds. None where there is none.
    The rule under which a place is left alone, so the wide one."""
    from . import doctor
    try:
        real = Path(os.path.realpath(path))
    except (OSError, ValueError):
        return None
    if clone is not None:
        own = Path(os.path.realpath(clone))
        if paths.inside(real, own):
            return own
    if _git(real) or _is_clone(real, skills):
        return real
    return doctor.clone_above(real)


def repository_around(path: Path, clone: Path) -> Path | None:
    """The clone of this repository that the real path of ``path`` is, or
    lies inside: the clone setup runs from, or a directory that holds what
    a clone holds (``doctor.looks_like_clone``), at the path or above it.
    None where there is none. The rule under which ``render`` writes
    nothing in a place, so a ``.git`` entry alone does not count: a user
    may keep a home's own directory under git."""
    from . import doctor
    try:
        real = Path(os.path.realpath(path))
        own = Path(os.path.realpath(clone))
    except (OSError, ValueError):
        return None
    return own if paths.inside(real, own) else doctor.clone_above(real)


def _parts(text: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", fsio.clean_target(text)) if part]


def _scan(root: Path, skill: str, table: Known,
          emptied: Callable[[Path], bool] | None = None) -> tuple[list, list, list, list[str], str | None, bool]:
    """A skill directory, without following a link: its files with their
    hashes, its links, its directories (deepest first, ``root`` last), the
    names that keep it from being a known copy, why it cannot be removed at
    all, and whether a ``.git`` entry is in it. ``emptied(directory)`` says
    that the record holds a file setup removed below ``directory``: one
    that is empty for that reason does not count against the copy."""
    emptied = emptied or (lambda directory: False)
    files: list[tuple[Path, str]] = []
    links: list[tuple[Path, str]] = []
    directories: list[Path] = []
    differs: list[str] = []
    blocked: list[str] = []
    git = False

    def walk(directory: Path, relative: str, derived: bool) -> None:
        nonlocal git
        try:
            names = sorted(os.listdir(directory))
        except OSError as exc:
            blocked.append(f"{relative or '.'}: cannot be read: {paths.reason(exc)}")
            return
        if not names and relative and not derived and not emptied(directory):
            differs.append(f"{relative}/ (an empty directory)")
        for name in names:
            path = directory / name
            inner = f"{relative}/{name}" if relative else name
            if name == ".git":
                git = True
                continue
            try:
                seen = fsio.look(path)
            except SetupError as exc:
                blocked.append(f"{inner}: {exc.lines[0]}")
                continue
            if seen.kind == fsio.LINK:
                links.append((path, seen.target or ""))
                differs.append(f"{inner} (a link)")
                if fsio.is_credentials(seen.target or ""):
                    blocked.append(f"{inner}: a link to a credentials file, which setup neither removes nor makes")
            elif seen.kind == fsio.DIRECTORY:
                walk(path, inner, name == _DERIVED_DIRECTORY)
                directories.append(path)
            elif seen.kind != fsio.FILE:
                blocked.append(f"{inner}: neither a file, a directory nor a link")
            elif fsio.is_credentials(path):
                blocked.append(f"{inner}: a credentials file, which setup never opens")
            else:
                try:
                    digest = fsio.sha256(fsio.read_bytes(path))
                except SetupError as exc:
                    blocked.append(f"{inner}: {exc.lines[0]}")
                    continue
                files.append((path, digest))
                if derived and name.endswith(_DERIVED_SUFFIXES):
                    continue  # what running a script left; it goes with the copy
                if not table.matches((f"{skill}/{inner}",), digest):
                    differs.append(inner if table.has(f"{skill}/{inner}") else f"{inner} (not a file of the skill)")

    walk(root, "", False)
    directories.append(root)
    if not files and not differs and not emptied(root):
        differs.append("(it holds no file)")
    return files, links, directories, differs, "; ".join(blocked) or None, git


def _skill_directory(base: dict[str, Any], path: Path, name: str, table: Known, skills: Any,
                     emptied: Callable[[Path], bool] | None = None) -> Found:
    files, links, directories, differs, blocked, git = _scan(path, name, table, emptied)
    found = Found(**base, entry=fsio.DIRECTORY, state=KNOWN, says="", files=files, links=links,
                  directories=directories, differs=differs, blocked=blocked)
    what = _named(SKILL, name)
    resumed = emptied is not None and emptied(path)
    if git or _is_clone(path, skills):
        found.what, found.state = CLONE, CLONE
        found.says = "a git clone, in a directory the provider reads skills from"
    elif blocked is not None:
        found.state = EDITED
        found.says = f"a copy of {what} that setup cannot remove ({blocked})"
    elif differs:
        found.state = EDITED
        count = len(differs)
        found.says = (
            f"a copy of {what} in which {count} {'entry matches' if count == 1 else 'entries match'} no committed "
            f"version ({_several(differs)}): edited by hand, or not from this repository"
        )
    elif resumed:
        left = f"{len(files)} of its files are" if len(files) != 1 else "1 of its files is"
        found.says = (
            f"what an interrupted run of setup left of a copy of {what}, which it was removing or putting back "
            f"({left} there, each a known committed version; the others are in the record)"
        )
    else:
        found.says = f"a copy of {what}, every file a known committed version"
    return found


def _link(base: dict[str, Any], path: Path, what: str, name: str, seen: fsio.Seen, table: Known, skills: Any,
          clone: Path | None = None) -> Found:
    target = seen.target or ""
    found = Found(**base, entry=fsio.LINK, state=UNRECOGNISED, says="", target=target)
    real = Path(os.path.realpath(path))
    if fsio.is_credentials(target) or fsio.is_credentials(real):
        # Setup makes no link to a credentials file, so it could not put
        # this one back: it is never removed, with or without the option.
        found.blocked = "a link to a credentials file, which setup neither removes nor makes"
        found.says = f"a link to {target}, a credentials file; where {_named(what, name)} would be"
        return found
    tail = _parts(target)
    named = _named(what, name)
    wanted = ["agents", V1_AGENT] if what == AGENT else [name]
    tail_fits = tail[-len(wanted):] == wanted
    # Where the link's own text leads, whether anything is there or not.
    lexical = Path(os.path.normpath(os.path.join(path.parent, fsio.clean_target(target))))

    def unrecognised(why: str) -> Found:
        found.says = f"a link to {target}, {why}; where {named} would be"
        return found

    def recognised(why: str) -> Found:
        found.state, found.says = KNOWN, f"a link to {target}: {why}"
        return found

    def in_this_clone(one: Path | None) -> bool:
        if clone is None or one is None:
            return False
        try:
            return paths.inside(os.path.realpath(one), os.path.realpath(clone)) or paths.inside(one, clone)
        except (OSError, ValueError):
            return False

    if not os.path.exists(real):
        if not tail_fits:
            return unrecognised("which leads nowhere and does not name the v1 file")
        if in_this_clone(lexical):
            return recognised(f"{named}, as a link into the clone setup runs from, which no longer has it")
        return unrecognised("which leads nowhere, outside the clone setup runs from")
    if what in (RULE, AGENT):
        if not os.path.isfile(real) or fsio.is_credentials(real):
            return unrecognised("which is not a file")
        try:
            digest = fsio.sha256(fsio.read_bytes(real))
        except SetupError:
            return unrecognised("which cannot be read")
        if table.matches(_sources(what, name), digest):
            return recognised(f"{named}, as a link to a known committed version")
        return unrecognised("a file that matches no committed version")
    if not os.path.isdir(real) or not os.path.isfile(real / SKILL_FILE):
        return unrecognised("which is not a skill directory")
    if tail_fits and real.name == name and in_this_clone(real):
        # By the link's own text alone, no link followed.
        if clone is not None and (paths.inside(lexical, clone) or paths.inside(lexical, os.path.realpath(clone))):
            return recognised(f"{named}, as a link into the clone setup runs from, which setup did not make")
        # The link's own text names another place (the other side's copy of
        # the skill, say), and that place is a link into the clone.
        return recognised(
            f"{named}, as a link to another place that itself leads into the clone setup runs from; setup did not "
            "make it"
        )
    files, _, _, differs, blocked, git = _scan(real, name, table)
    if files and not differs and blocked is None and not git:
        return recognised(f"{named}, as a link to a copy whose every file is a known committed version")
    return unrecognised("a directory setup does not recognise as a copy or a clone of the skill")


def _places(provider: homes.Provider) -> list[tuple[homes.Place, str, tuple[str, ...]]]:
    """The places of a provider's home that hold v1 locations, each with
    what its entries are and the names looked for."""
    found = []
    for place in provider.places:
        if place.name == homes.RULES:
            found.append((place, RULE, tuple(V1_RULES)))
        elif place.name == homes.AGENTS and provider.name == homes.CLAUDE_CODE:
            found.append((place, AGENT, (V1_AGENT,)))
        elif place.name in (homes.SKILLS, homes.OLD_SKILLS):
            found.append((place, SKILL, tuple(sorted({*V1_SKILLS, *PROCESS_SKILLS} - homes.OWN_SETUP_SKILLS))))
    return found


@dataclass
class Survey:
    """Every v1 leftover of the installed providers' homes, and every v1
    location, by its folded path."""

    found: list[Found]
    locations: dict[str, tuple[str, str, homes.Standing]]   # what, name, the place's standing
    standing: Callable[[Path], homes.Standing] | None = None

    def at(self, path: Path | str) -> Found | None:
        ident = fold(path)
        for one in self.found:
            if fold(one.path) == ident:
                return one
        return None


def survey(found_homes: homes.Homes, record: Any, standing: Callable[[Path], homes.Standing],
           skills: Any = ()) -> Survey:
    """Look at every v1 location; see the module. Reads, and never writes.
    ``standing`` says whose a place is; ``record`` is the install record:
    what it lists as setup's own is not a leftover."""
    table = known()
    roots = found_homes.roots()
    removed = sorted(
        paths.fold_key(key) for key, entry in record.entries.items() if entry.get("kind") == "removed-file"
    )

    def emptied(directory: Path) -> bool:
        key = roots.key(directory)
        if key is None:
            return False
        below = paths.fold_key(key) + "/"
        return any(one.startswith(below) for one in removed)

    leftovers: list[Found] = []
    locations: dict[str, tuple[str, str, homes.Standing]] = {}
    for provider in found_homes.installed():
        for place, what, names in _places(provider):
            whose = standing(place.path)
            if whose.kind in (homes.HANDLED, homes.UNKNOWN):
                continue  # another name for a place already looked at, or one that cannot be
            base = {"provider": provider.name, "place": place.name, "standing": whose}
            if what == SKILL:
                try:
                    present = [entry for entry in paths.entries(place.path)]
                except SetupError:
                    present = []
                around = clone_around(place.path, skills, found_homes.clone) if present else None
                if around is not None:
                    # ``git clone <url> <the skills directory>``, or a link
                    # from the place into a clone: all of it is the clone.
                    real = Path(os.path.realpath(place.path))
                    if paths.same(real, paths.absolute(place.path)):
                        says = "a git clone: the skills directory itself is one, and so is every skill in it"
                    else:
                        whose = "the clone setup runs from" if paths.inside(real, os.path.realpath(found_homes.clone)) \
                            else "a clone"
                        says = (
                            f"the skills directory leads into {whose} ({around}): every entry in it is the clone's "
                            "own, and setup writes nothing there"
                        )
                    leftovers.append(Found(
                        **base, path=place.path, what=CLONE, name=place.path.name, entry=fsio.DIRECTORY, state=CLONE,
                        says=says,
                    ))
                    continue
                for entry in present:
                    if entry.name in names or entry.name in homes.OWN_SETUP_SKILLS or fsio.is_credentials(entry):
                        continue
                    if entry.name.startswith("."):
                        continue  # not a skill of anyone's installing: Codex keeps its own in .system
                    try:
                        if fsio.look(entry).kind != fsio.DIRECTORY:
                            continue
                    except SetupError:
                        continue
                    if _git(entry) or _is_clone(entry, skills):
                        leftovers.append(Found(
                            **base, path=entry, what=CLONE, name=entry.name, entry=fsio.DIRECTORY, state=CLONE,
                            says="a git clone, in a directory the provider reads skills from",
                        ))
            for name in names:
                path = place.path / name
                locations[fold(path)] = (what, name, whose)
                key = roots.key(path)
                listed = record.get(key) if key is not None else None
                if listed is not None and not str(listed.get("kind", "")).startswith("removed-"):
                    continue  # setup's own: a link it made, a file it wrote
                try:
                    seen = fsio.look(path)
                except SetupError:
                    continue
                one = {**base, "path": path, "what": what, "name": name}
                if seen.kind == fsio.LINK:
                    leftovers.append(_link(one, path, what, name, seen, table, skills, found_homes.clone))
                elif what == SKILL and seen.kind == fsio.DIRECTORY:
                    leftovers.append(_skill_directory(one, path, name, table, skills, emptied))
                elif what != SKILL and seen.kind == fsio.FILE:
                    leftovers.append(_file(one, path, what, name, table))
    return Survey(leftovers, locations, standing)


def _file(base: dict[str, Any], path: Path, what: str, name: str, table: Known) -> Found:
    named = _named(what, name)
    found = Found(**base, entry=fsio.FILE, state=EDITED, says="")
    try:
        digest = fsio.sha256(fsio.read_bytes(path))
    except SetupError as exc:
        found.blocked = exc.lines[0]
        found.says = f"a file where {named} would be, which cannot be read"
        return found
    found.files = [(path, digest)]
    if table.matches(_sources(what, name), digest):
        found.state, found.says = KNOWN, f"a copy of {named}, a known committed version"
    else:
        found.says = f"a copy of {named} that matches no committed version: edited by hand, or not from this repository"
    return found


# --- The instructions files -------------------------------------------------------

def _read(path: Path) -> bytes | None:
    """The bytes of a file, through a link; None where no file is."""
    try:
        seen = fsio.look(path)
        if seen.kind == fsio.FILE:
            return fsio.read_bytes(path)
        if seen.kind == fsio.LINK and os.path.isfile(path):
            return fsio.read_bytes(Path(os.path.realpath(path)))
    except SetupError:
        return None
    return None


def import_lines(data: bytes) -> tuple[list[str], list[tuple[int, str]]]:
    """The import lines of ``IMPORT_LINES`` that ``data`` holds as whole
    lines, and every other line (its number and text) that still imports
    one of the two rules: outside a fenced block and outside a code span,
    where Claude Code reads an ``@path`` as an import."""
    try:
        text = blocks.split_bom(data)[1].decode("utf-8")
    except UnicodeDecodeError:
        return [], []
    exact: list[str] = []
    others: list[tuple[int, str]] = []
    fenced = False
    for number, raw in enumerate(text.split("\n"), 1):
        line = raw[:-1] if raw.endswith("\r") else raw
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if line in IMPORT_LINES:
            if line not in exact:
                exact.append(line)
            continue
        if fenced:
            continue
        for wanted in IMPORT_LINES:
            at = line.find(wanted)
            rest = line[at + len(wanted):at + len(wanted) + 1] if at >= 0 else ""
            if at >= 0 and line[:at].count("`") % 2 == 0 and not (rest.isalnum() or rest in ("-", "_", "/")):
                others.append((number, line.strip()))
                break
    return exact, others


def _instructions(provider: homes.Provider) -> Path | None:
    for place in provider.places:
        if place.name == homes.INSTRUCTIONS:
            return place.path
    return None


# --- The part of render ------------------------------------------------------------

def configure(parser: Any) -> None:
    parser.add_argument(
        MIGRATE_OPTION,
        action="store_true",
        help="remove what an earlier (v1) install left in the homes: the two @rules import lines of CLAUDE.md, "
        "the v1 rule copies, the loose skill copies and the sprint-coder agent, each only when it is a known "
        "committed version or a v1 link, after a backup; and add a pointer to the two skills. See "
        "\"Migrating v1\" below",
    )
    parser.add_argument(
        STALE_OPTION,
        action="append",
        default=[],
        metavar="PATH",
        help=f"with {MIGRATE_OPTION}: also remove the v1 copy or link at PATH, which migration keeps because it "
        "matches no committed version, after a backup. Only a path the dry run names; any other path is "
        "refused. May be given more than once",
    )


def _state(run: Any) -> dict[str, Any]:
    """What this module keeps on a run: the survey, what the plan clears,
    and the report."""
    kept = getattr(run, "v1", None)
    if kept is None:
        kept = {"survey": None, "cleared": {}, "report": None, "left": 0, "planned": False}
        run.v1 = kept
    return kept


def survey_of(run: Any) -> Survey:
    """The survey of a run's homes, made once."""
    state = _state(run)
    if state["survey"] is None:
        state["survey"] = survey(run.homes, run.record, run.standing, run.sources.skills)
    return state["survey"]


def cleared(run: Any, path: Path) -> str | None:
    """What this run's plan removes at ``path``, in words, or None. The
    removals are planned here if they were not yet, so they come before
    the link the caller is about to ask for."""
    fill(run)
    return _state(run)["cleared"].get(fold(path))


def conflict(run: Any, path: Path) -> str | None:
    """The line for a conflict at ``path`` when a v1 leftover is there:
    what it is and the command that deals with it. None for anything
    else."""
    try:
        found = survey_of(run).at(path)
        if found is None:
            above = survey_of(run).at(path.parent)
            if above is not None and above.state == CLONE:
                return (
                    f"{path}: {above.says}; setup does not link into a clone and removes nothing in one. Point "
                    f"{above.path} at a directory of its own, or remove the link"
                )
    except SetupError:
        return None
    if found is None:
        return None
    if found.state == KNOWN:
        return (
            f"{path}: {found.says}, which an earlier (v1) install left and setup did not make; "
            f"`render {MIGRATE_OPTION}` removes it and links here (`--dry-run` shows the plan first)"
        )
    if found.blocked is not None or found.state == CLONE:
        return f"{path}: {found.says}; setup does not remove it, it is yours to move away"
    return (
        f"{path}: {found.says}; setup did not make it, and migration keeps it until you decide: "
        f"`{stale_flag(path)}` removes it after a backup"
    )


def left(run: Any) -> int:
    """How many v1 items this run kept that an option would remove."""
    return _state(run)["left"]


def report(run: Any) -> dict[str, Any] | None:
    return _state(run)["report"]


def _remove(run: Any, found: Found) -> None:
    """Add the removal of one leftover to the plan: files (each backed
    up), links as links, then the directories it leaves empty."""
    plan = run.plan
    if found.entry == fsio.LINK:
        plan.remove_link(found.path, expect_target=found.target)
        return
    for path, digest in found.files:
        plan.remove_file(path, expect_sha256=digest)
    for path, target in found.links:
        plan.remove_link(path, expect_target=target)
    for directory in found.directories:
        plan.remove_directory(directory, users=True)


def _needs_follow(run: Any, standing: homes.Standing) -> bool:
    return standing.through_link and not run.follow


def fill(run: Any) -> None:
    """The part ``migrate`` of ``render``; see the module. Nothing without
    ``--migrate-v1``. It plans once: the first call does, whether it is the
    part's own or ``cleared``'s for the first link of a run."""
    state = _state(run)
    if state["planned"]:
        return
    state["planned"] = True
    asked = [text for text in (run.option("remove_stale", None) or []) if isinstance(text, str)]
    if not run.option("migrate_v1", False):
        if asked:
            run.fail(f"{STALE_OPTION} is part of the v1 migration: give {MIGRATE_OPTION} with it")
        return
    try:
        found = survey_of(run)
    except SetupError as exc:
        run.fail(*exc.lines)
        return
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    def item(path: Path, status: str, says: str, **more: Any) -> None:
        items.append({"path": str(path), "status": status, "says": says, **more})

    # --- --remove-stale: only a v1 location, and only what migration keeps.
    stale: set[str] = set()
    for text in asked:
        try:
            # An empty value would name the working directory.
            path = paths.absolute(Path(locations.path_argument(text, STALE_OPTION)).expanduser())
        except SetupError as exc:
            run.fail(*exc.lines)
            continue
        except (RuntimeError, KeyError, ValueError):
            run.fail(f"{STALE_OPTION} {text}: not a path")
            continue
        ident = fold(path)
        one = found.at(path)
        where = found.locations.get(ident)
        if one is not None and one.state == CLONE:
            run.fail(f"{STALE_OPTION} {path}: {one.says}; setup never removes a clone, it is yours to move away")
        elif where is None and one is None:
            run.fail(
                f"{STALE_OPTION} {path}: not a place a v1 install used in a home of this run. The option removes "
                f"only a v1 copy or link that `render {MIGRATE_OPTION} --dry-run` names; it removes nothing else"
            )
        elif not (one.standing if one is not None else where[2]).writes:
            whose = one.standing if one is not None else where[2]
            run.fail(f"{STALE_OPTION} {path}: {whose.describe()}; run the migration on that side")
        elif one is not None and one.blocked is not None:
            run.fail(f"{STALE_OPTION} {path}: setup cannot remove it ({one.blocked}); it is yours to remove")
        elif one is None and os.path.lexists(path):
            key = run.roots.key(path)
            own = key is not None and run.record.get(key) is not None
            if own:
                # The same command a second time: what the option named is
                # gone, and setup's own entry is in its place.
                run.notes.append(
                    f"{STALE_OPTION} {path}: nothing to remove; setup's own entry is there, which the option does "
                    "not remove"
                )
            else:
                run.fail(
                    f"{STALE_OPTION} {path}: what is there is not a copy or a link a v1 install left; it is yours "
                    "to move away"
                )
        else:
            stale.add(ident)  # a kept one; or a known one, or nothing there: nothing more to do for it

    # --- The instructions files.
    for provider in run.homes.installed():
        path = _instructions(provider)
        if path is None:
            continue
        standing = run.standing(path)
        what = f"{provider.name} instructions"
        if standing.kind == homes.UNKNOWN:
            run.fail(f"{path}: {standing.describe()}")
        elif standing.kind == homes.HANDLED:
            item(path, SKIPPED, standing.describe(), what=what)
        elif not standing.writes:
            item(path, SKIPPED, standing.describe(), what=what)
        elif _needs_follow(run, standing):
            state["left"] += 1
            item(path, NEEDS_FLAG, f"{standing.describe()}; give --follow-config-symlinks to edit it there", what=what)
        else:
            _edit_instructions(run, provider, path, item, what)

    # --- The copies, the links and the clones.
    rules_removed = False
    for one in found.found:
        more = {"what": one.what, "name": one.name, "provider": one.provider, "place": one.place}
        if not one.mine:
            item(one.path, SKIPPED, f"{one.says}; {one.standing.describe()}", **more)
        elif one.state == CLONE:
            item(one.path, NEVER, f"{one.says}; setup never removes a clone, it is yours to move away", **more)
        elif _needs_follow(run, one.standing):
            state["left"] += 1
            item(one.path, NEEDS_FLAG,
                 f"{one.says}; {one.standing.describe()}; give --follow-config-symlinks to remove it there", **more)
        elif one.state == KNOWN or (fold(one.path) in stale and one.blocked is None):
            forced = one.state != KNOWN
            how = "removed as a link, its target untouched" if one.entry == fsio.LINK else "removed after a backup"
            if forced:
                how += f", because {STALE_OPTION} names it"
            _remove(run, one)
            state["cleared"][fold(one.path)] = one.says
            rules_removed = rules_removed or one.rule
            item(one.path, REMOVE, f"{one.says}; {how}", **more)
        elif one.blocked is not None:
            item(one.path, KEPT, f"{one.says}; it is yours to remove", **more)
        else:
            state["left"] += 1
            item(one.path, KEPT, f"{one.says}; kept. To remove it after a backup: {stale_flag(one.path)}",
                 flag=f"{STALE_OPTION} {quoted(one.path)}", **more)
    if rules_removed:
        warnings.append(DANGLING)
    state["report"] = {"items": items, "warnings": warnings}


def _edit_instructions(run: Any, provider: homes.Provider, path: Path, item: Callable[..., None], what: str) -> None:
    data = _read(path)
    removed: list[str] = []
    if provider.name == homes.CLAUDE_CODE and data is not None:
        removed, _ = import_lines(data)
    key = run.roots.key(path)
    listed = run.record.get(key) if key is not None else None
    wrote = ((listed or {}).get("blocks") or {}).get(BLOCK_NAME) if (listed or {}).get("kind") == "text" else None
    says: list[str] = []
    block_status = "add"
    try:
        there = None if data is None else blocks.get(data, blocks.MARKDOWN, BLOCK_NAME)
        wanted = blocks.render(blocks.MARKDOWN, BLOCK_NAME, POINTER, blocks.eol_of(blocks.split_bom(data or b"")[1]))
    except blocks.Refusal:
        there, wanted = None, b""  # the plan refuses the file, and says why
    if there is not None:
        if there == wanted:
            block_status = "same"
        elif (not isinstance(wrote, dict) or fsio.sha256(there) != wrote.get("sha256")) and not run.overwrite:
            # Edited since setup wrote it, or never recorded as setup's:
            # either way what is between the markers is not setup's text.
            block_status = "edited" if isinstance(wrote, dict) else "foreign"
        else:
            block_status = "update"
    if removed:
        run.plan.remove_lines(path, removed)
        says.append(f"remove the {'line' if len(removed) == 1 else 'lines'} {' and '.join(removed)}")
    if block_status not in ("edited", "foreign"):
        # A block the record does not hold, with other text in it, is
        # written only on request: the plan refuses it unless told.
        asked = {}
        if block_status == "update" and run.overwrite:
            asked = {"replace": fileops.EDITED if isinstance(wrote, dict) else fileops.ANY}
        run.plan.edit_block(path, POINTER, name=BLOCK_NAME, place=fileops.END, **asked)
    if block_status == "edited":
        says.append(
            f"the pointer block {BLOCK_NAME} was edited by hand since setup wrote it, and is kept; "
            "--overwrite-edited writes it again"
        )
    elif block_status == "foreign":
        says.append(
            f"markers of the pointer block {BLOCK_NAME} are in the file with other text between them than setup "
            "writes, and the install record does not hold the block: it is kept as it is; --overwrite-edited "
            "backs the file up and writes the block"
        )
    elif block_status == "same":
        says.append(f"the pointer block {BLOCK_NAME} is there")
    else:
        where = ", in a new file" if data is None else " at the end"
        says.append(f"{'add' if block_status == 'add' else 'write again'} the pointer block {BLOCK_NAME}{where}")
    changed = bool(removed) or block_status in ("add", "update")
    if block_status in ("foreign", "edited"):
        _state(run)["left"] += 1   # kept, and an option would write it: exit code 3
    status = EDIT if changed else KEPT if block_status in ("foreign", "edited") else UP_TO_DATE
    item(path, status, "; ".join(says), what=what, provider=provider.name)


_WORDS = {
    REMOVE: "remove", EDIT: "edit", UP_TO_DATE: "up to date", KEPT: "kept", NEVER: "never removed",
    SKIPPED: "skipped", NEEDS_FLAG: "skipped, needs --follow-config-symlinks",
}


def lines(found: dict[str, Any] | None) -> list[str]:
    """The report of the migration as text; nothing where it was not asked."""
    if found is None:
        return []
    shown = ["v1 migration:"]
    shown.extend(f"  {one['path']}: {_WORDS[one['status']]}: {one['says']}" for one in found["items"])
    if not found["items"]:
        shown.append("  nothing of a v1 install was found")
    shown.extend(f"warning: {text}" for text in found["warnings"])
    return shown


def summary(found: dict[str, Any] | None) -> str:
    """What the migration adds to the one line that sums a run up."""
    if found is None:
        return ""
    counts = {status: sum(1 for one in found["items"] if one["status"] == status) for status in _WORDS}
    said = []
    if counts[REMOVE]:
        said.append(f"{counts[REMOVE]} removed")
    if counts[EDIT]:
        said.append(f"{counts[EDIT]} edited")
    if counts[KEPT]:
        said.append(f"{counts[KEPT]} kept")
    if counts[NEVER]:
        said.append(f"{counts[NEVER]} never removed")
    if counts[SKIPPED] or counts[NEEDS_FLAG]:
        said.append(f"{counts[SKIPPED] + counts[NEEDS_FLAG]} skipped")
    return "; v1: " + (", ".join(said) if said else "nothing found")


# --- doctor -----------------------------------------------------------------------

def _doctor_survey(context: Any) -> Survey:
    def make() -> Survey:
        sorter = homes.Classifier(context.homes)
        asked: dict[str, homes.Standing] = {}

        def standing(path: Path) -> homes.Standing:
            ident = fold(path)
            if ident not in asked:
                asked[ident] = sorter.standing(path)
            return asked[ident]

        try:
            skills = context.sources.skills
        except SetupError:
            skills = ()
        return survey(context.homes, context.record, standing, skills)
    return context._once("v1", make)


def leftover_paths(context: Any) -> set[str]:
    """The folded paths that hold a v1 leftover: the check ``missing``
    leaves a conflict there to the check ``v1``."""
    try:
        return {fold(one.path) for one in _doctor_survey(context).found}
    except SetupError:
        return set()


def findings(context: Any) -> list[tuple[str, str, str]]:
    """The check ``v1`` (R6.11): each v1 import line, copy, link and clone
    that remains, as (severity, detail, subject). What this side can change
    is an error with the command that deals with it; what the other side
    owns is read where it can be and is info."""
    found = _doctor_survey(context)
    said: list[tuple[str, str, str]] = []
    for provider in context.homes.installed():
        if provider.name != homes.CLAUDE_CODE:
            continue
        path = _instructions(provider)
        data = None if path is None else _read(path)
        if path is None or data is None:
            continue
        standing = found.standing(path) if found.standing is not None else homes.Classifier(context.homes).standing(path)
        exact, others = import_lines(data)
        theirs = not standing.writes and standing.side is not None
        for line in exact:
            if theirs:
                said.append((INFO, f"{path}: imports a v1 rule with the line {line}; the file is the {standing.side} "
                                   f"side's to migrate: run `render {MIGRATE_OPTION}` there", str(path)))
            else:
                more = " --follow-config-symlinks" if standing.through_link else ""
                said.append((ERROR, f"{path}: imports a v1 rule with the line {line}; `render {MIGRATE_OPTION}{more}` "
                                    "removes the line and adds a pointer to the skills", str(path)))
        for number, line in others:
            whose = f" (the {standing.side} side's file)" if theirs else ""
            said.append((INFO if theirs else ERROR,
                         f"{path}: line {number} still imports a v1 rule ({line}) and is not exactly the line setup "
                         f"removes; remove it yourself{whose}", str(path)))
    for one in found.found:
        subject = str(one.path)
        if not one.mine:
            side = one.standing.side or "other"
            said.append((INFO, f"{one.path}: {one.says}; the {side} side's to migrate: run "
                               f"`render {MIGRATE_OPTION}` there", subject))
        elif one.state == CLONE:
            said.append((ERROR, f"{one.path}: {one.says}; setup never removes a clone: remove it yourself, or move "
                                "it out of the skills directory", subject))
        elif one.blocked is not None:
            said.append((ERROR, f"{one.path}: {one.says}; remove it yourself", subject))
        elif one.state == KNOWN:
            more = " --follow-config-symlinks" if one.standing.through_link else ""
            said.append((ERROR, f"{one.path}: {one.says}; `render {MIGRATE_OPTION}{more}` removes it"
                                + (", as a link" if one.entry == fsio.LINK else " after a backup"), subject))
        else:
            said.append((ERROR, f"{one.path}: {one.says}; migration keeps it until you decide: "
                                f"`{stale_flag(one.path)}` removes it after a backup", subject))
    return said
