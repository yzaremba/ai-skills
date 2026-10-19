"""What ``doctor`` checks: a registry of checks over one read-only context.

How the command uses it

    for check in doctor.CHECKS: check.add_arguments(parser)    # a check's own option
    context = doctor.Context(where, args)
    chosen, left_out = doctor.select(args, only=args.only, skip=args.skip)
    report = doctor.report(context, doctor.run(context, chosen), left_out)
    doctor.report_lines(report)                                # or the report as JSON
    report["exit_code"]

A check
    ``Check(name, run, fine, default=True, switch=None, configure=None)``.
    ``run(context)`` returns findings and writes nothing. A finding has a
    severity (``error``, ``warning``, ``info``, ``ok``), a detail line and,
    where it is about one thing, that thing as ``subject``. A check that
    returns no finding is fine, and ``fine`` is its one ``ok`` line. A check
    that cannot be made (a provider that is not installed, a home never
    rendered) says so as ``info``. One that raises is reported as an
    ``error`` finding of its own name, and the checks after it still run.

    ``default`` is whether the check runs when nothing asks for it.
    ``switch`` names an option of the command (the attribute of its parsed
    arguments) that turns a default check off (``--no-versions``) or a
    non-default one on; ``configure(parser)`` adds that option. ``--only``
    names the checks to run and ``--skip`` those to leave out.

Adding a check
    Write ``def check_<what>(context) -> list[Finding]`` and add one
    ``Check(...)`` line to ``CHECKS``. The command is not edited: it takes
    its options, its choices and its order from ``CHECKS``. A step that
    extends a check replaces that check's function in its line (``codex
    settings``: ``codex_settings`` gives the values read, for a function
    that wraps it).

The context
    Built once and shared: the locations, the homes, and, each made when a
    check first asks and then kept, the install record, the result of
    source validation, the profiles the settings resolve to, the provider
    dictionaries, the effective settings, and ``probe``.

The probe
    ``probe`` is ``render``'s own planning, asked what it would do now and
    never run: a ``render.Run`` filled by ``render.PARTS`` and swept, whose
    plan is thrown away. Each item says what ``render`` found at one path
    (create, up to date, update, edited, conflict, skipped) and each stale
    item what it would remove, so the checks compare "what should be there"
    with "what is there" by the rules of ``render`` and not by a second
    copy of them. It also keeps the inputs digest ``render`` would record
    for each generated file, which is what drift is told by. It is None
    while the sources have problems: ``render`` does not plan from those.

Severities, where the step left the choice
    missing   Something the record lists that is gone from disk is an
              error: what the user holds as installed is not there. What
              ``render`` would create and the record does not list is a
              warning once the home (or the project) has a record: the
              clone gained it since the last ``render``, as after a pull.
              On a home with no record at all it is one ``info`` line
              (nothing was rendered yet), and so are the generated files
              on a home whose record holds none (rendered with
              ``--no-roles``). The roles turned off by the setting
              ``roles.enabled`` are one ``info`` line: the probe, like
              ``render``, then asks for none of them. Something in the
              way that setup did not make is an error: ``render`` stops
              on it. Where that is
              what a v1 install left, the check ``v1`` says it and this
              one does not: one thing is reported once.
    v1        Every v1 import line, copy, link and clone that remains in a
              home this side can change is an error (R6.11), with the
              command that deals with it. What the other side owns is read
              where it can be and is ``info``: that side migrates it. See
              ``migrate``.
    collaboration skill
              Its doctor's own severities are kept: a check it fails as an
              error is an error here, a warning a warning. That it could
              not be started, did not finish, or printed what cannot be
              read is a warning: this tool then knows nothing about that
              skill, which is not a fault of the install.

Setup itself writes nothing here: no state directory, no record, no file of
a home, a project or the clone. Programs are started, each with a fixed
argument list, no shell, a timeout and the environment of
``homes.child_environment``: a provider's list command (``modellist``),
``<program> --version``, the offline commands of ``discovery``, and the
collaboration skill's own doctor, with this interpreter. A provider's
program may write state of its own into its own home when it starts (Codex
0.160.0 wrote its databases, an installation id and its bundled skills
under ``skills/.system``); for a scratch home that is the scratch home.
``STARTERS`` names the checks that start one and the option that leaves
each out, and ``report_lines`` says which of them ran. What a provider
writes for itself is no finding of any check: the names looked for are
setup's own, and an entry whose name starts with a dot is not looked at.

Credentials files are never opened. From the user's Codex ``config.toml``
only the keys of ``CODEX_KEYS`` are looked at, and only their values are
printed; a file that does not parse is reported by where the fault is, not
by what the line holds. From a Claude Code ``settings.json`` only the one
key of ``instructions`` is looked at.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from . import blocks, carried, definitions, dictionary, entry, fileops, fsio, homes, jsonkeys, modellist, paths
from . import profiles, render, settings, validate
from . import discovery
from . import codexsettings
from . import instructions
from . import migrate
from .errors import SetupError
from .locations import Locations

REPORT_SCHEMA_VERSION = 1

ERROR = "error"
WARNING = "warning"
INFO = "info"
OK = "ok"
SEVERITIES = (ERROR, WARNING, INFO, OK)

# How long a started program may take, in seconds. Read when it is started.
VERSION_TIMEOUT = 20.0
COLLAB_TIMEOUT = 180.0

# The collaboration skill (R1.2): where its doctor is, and what it calls
# the providers.
COLLAB_SKILL = "multiagent-collab"
COLLAB_SCRIPT = ("scripts", "multiagent_collab.py")
COLLAB_AGENTS = {homes.CLAUDE_CODE: "claude", homes.CODEX: "codex"}

# The Codex settings of R6.7, by their key in ``config.toml``.
THREADS_KEY = "agents.max_concurrent_threads_per_session"
SANDBOX_KEY = "sandbox_mode"
PERMISSIONS_KEY = "default_permissions"
# The size at which Codex stops adding instruction files (R7.4); the check
# ``instruction-files`` reads it.
DOC_BYTES_KEY = "project_doc_max_bytes"
# The wait floor of ``wait_agent`` and its companions (``codexsettings``).
WAIT_MIN_KEY, WAIT_DEFAULT_KEY, WAIT_MAX_KEY = codexsettings.WAIT_KEYS
CODEX_KEYS = (THREADS_KEY, SANDBOX_KEY, PERMISSIONS_KEY, DOC_BYTES_KEY, *codexsettings.WAIT_KEYS)
# The Manager's session is the primary thread, which the limit does not
# count; below it run an Implementation Manager, three Coders and a
# reviewer, with room for a second reviewer and a specialist.
THREADS_NEEDED = 8
UNSET = object()

# What does not work below a provider's oldest supported version.
BELOW_OLDEST = {
    homes.CLAUDE_CODE: "below it some Claude Code sessions do not read a repository's AGENTS.md",
}

# Where a provider looks for skills in a project.
PROJECT_SKILLS = {homes.CLAUDE_CODE: (".claude", "skills"), homes.CODEX: (".agents", "skills")}

# The checks that start a program, each with the option that leaves it out.
STARTERS = {
    "models": "--no-model-list",
    "versions": "--no-versions",
    "discovery": "--skip discovery",
    "collaboration-skill": "--no-collab",
}

# What makes a directory look like a clone of this repository, without git.
CLONE_MARKS = (("tools", "setup", "workflow_setup.py"), ("roles",))
_CLONE_DEPTH = 8


# --- Findings and checks ---------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    severity: str
    detail: str
    subject: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"severity": self.severity, "detail": self.detail, "subject": self.subject}


def error(detail: str, subject: Any = None) -> Finding:
    return Finding(ERROR, detail, None if subject is None else str(subject))


def warning(detail: str, subject: Any = None) -> Finding:
    return Finding(WARNING, detail, None if subject is None else str(subject))


def info(detail: str, subject: Any = None) -> Finding:
    return Finding(INFO, detail, None if subject is None else str(subject))


def fine(detail: str, subject: Any = None) -> Finding:
    return Finding(OK, detail, None if subject is None else str(subject))


@dataclass(frozen=True)
class Check:
    """One check; see the module."""

    name: str
    run: Callable[["Context"], Iterable[Finding]]
    fine: str
    default: bool = True
    switch: str | None = None
    configure: Callable[[Any], None] | None = None

    def add_arguments(self, parser: Any) -> None:
        if self.configure is not None:
            self.configure(parser)


@dataclass(frozen=True)
class Outcome:
    """What one check found. ``severity`` is the worst of its findings."""

    name: str
    findings: tuple[Finding, ...]

    @property
    def severity(self) -> str:
        return min((found.severity for found in self.findings), key=SEVERITIES.index)


# --- The context -----------------------------------------------------------------

class Probe(render.Run):
    """``render``'s planning, kept and never run; see the module."""

    def __init__(self, found: homes.Homes, sources: validate.Report) -> None:
        # Through links: a place that is a link on this side is looked at
        # where it leads, as ``render --follow-config-symlinks`` writes it.
        super().__init__(found, sources, None, follow=True)
        self.inputs: dict[str, str] = {}

    def file(self, provider: Any, place: Any, name: str, text: str, inputs: str, detail: Any = None,
             carry: bool = False) -> render.Item:
        item = super().file(provider, place, name, text, inputs, detail, carry)
        if item.key is not None:
            self.inputs[item.key] = inputs
        return item


class Context:
    """What the checks share; see the module. Each part is made once. One
    that cannot be made raises the same error for every check that asks."""

    def __init__(self, where: Locations, options: Any = None, host: homes.Host | None = None) -> None:
        self.where = where
        self.options = options
        self.homes = homes.resolve(where, host)
        self.environ = self.homes.host.environ
        # What every program a check starts is given: for a scratch home
        # it points the provider at that home, never at the real one.
        self.child_environ = homes.child_environment(self.homes)
        self.roots = self.homes.roots()
        self._made: dict[str, tuple[bool, Any]] = {}

    def option(self, name: str, default: Any = None) -> Any:
        return getattr(self.options, name, default)

    def _once(self, name: str, make: Callable[[], Any]) -> Any:
        if name not in self._made:
            try:
                self._made[name] = (True, make())
            except Exception as exc:  # kept, so that each check says the same
                self._made[name] = (False, exc)
        made, value = self._made[name]
        if not made:
            raise value
        return value

    @property
    def user_level(self) -> Locations:
        return definitions.user_level(self.where)

    @property
    def record(self) -> Any:
        return self._once("record", lambda: fileops.read_record(self.roots))

    @property
    def sources(self) -> validate.Report:
        return self._once("sources", lambda: validate.check(self.where))

    @property
    def resolution(self) -> profiles.Resolution:
        return self._once("resolution", lambda: profiles.resolution(self.where))

    @property
    def dictionaries(self) -> dict[str, dictionary.Dictionary]:
        return self._once("dictionaries", lambda: dictionary.load_all(self.where))

    @property
    def provider_settings(self) -> dict[str, settings.Entry]:
        return self._once("provider_settings", lambda: settings.resolve(self.where, ("providers",)))

    @property
    def probe(self) -> Probe | None:
        return self._once("probe", self._probe)

    def _probe(self) -> Probe | None:
        if not self.sources.ok:
            return None
        probe = Probe(self.homes, self.sources)
        for part in render.PARTS:
            part.fill(probe)
        probe.sweep()
        probe.finish()
        return probe

    def installed(self) -> list[homes.Provider]:
        return self.homes.installed()

    def rendered(self) -> bool:
        """Whether any run of setup left a record for the home."""
        return bool(self.record.home.on_disk)

    def whose(self, path: Path) -> str:
        """A note for a path that the other side owns, else nothing."""
        side = self.homes.host.other_side(path)
        return "" if side is None else f" (the {side} side's; read from here, never written)"


NOT_PLANNED = "not checked: the clone's sources have problems (see the check `sources`), and render plans from valid sources only"
NEVER_RENDERED = "nothing to check: no run of setup has written to this home yet; `render` installs"


_inside = paths.inside


def _generated(found: dict[str, Any]) -> bool:
    return found.get("kind") == "file" and str(found.get("inputs") or "").startswith(render.GENERATED_PREFIX)


def _item_subject(item: render.Item) -> str:
    base = item.key or str(item.path)
    if item.kind == render.KEY:
        return f"{base}: key {item.name}"
    if item.kind == render.BLOCK:
        return f"{base}: block {item.name or '(unnamed)'}"
    return base


# --- What the record lists, beside the disk --------------------------------------

GONE = "gone"
EDITED = "edited"
UNREADABLE = "unreadable"


@dataclass(frozen=True)
class Fact:
    """One thing the record lists that is not on disk as setup left it."""

    state: str
    key: str                  # the record's key of the file
    part: str | None          # "key <name>" or "block <name>" inside a user-owned file
    detail: str
    generated: bool = False   # a file ``render`` generates

    @property
    def subject(self) -> str:
        return self.key if self.part is None else f"{self.key}: {self.part}"

    @property
    def ident(self) -> tuple[str, str | None]:
        return (paths.fold_key(self.key), self.part)


def _block_part(name: str) -> str:
    return f"block {name or '(unnamed)'}"


def survey(context: Context) -> list[Fact]:
    """Every file, block and key the record lists, compared with the disk.
    Links are the business of ``check_links``."""
    return context._once("survey", lambda: _survey(context))


def _survey(context: Context) -> list[Fact]:
    record = context.record
    facts: list[Fact] = []
    for key, found in sorted(record.entries.items()):
        kind = found.get("kind")
        if kind not in ("file", "text", "json"):
            continue
        generated = _generated(found)
        try:
            path = record.path(key)
            if fsio.is_credentials(path):
                continue
            seen = fsio.look(path)
            data = None
            if seen.kind == fsio.FILE:
                data = fsio.read_bytes(path)
            elif seen.kind == fsio.LINK and os.path.isfile(path):
                data = fsio.read_bytes(Path(os.path.realpath(path)))  # written through a link
        except SetupError as exc:
            facts.append(Fact(UNREADABLE, key, None, exc.lines[0], generated))
            continue
        there = "nothing" if seen.kind == fsio.ABSENT else f"a {seen.kind}"
        if kind == "file":
            if seen.kind == fsio.ABSENT:
                facts.append(Fact(GONE, key, None, "the file setup wrote is gone", generated))
            elif data is None:
                facts.append(Fact(EDITED, key, None, f"no longer a file: {there} is there", generated))
            elif generated and fsio.sha256(data) != found.get("sha256") and not carried.unchanged(data, found):
                # What Codex or the user added to the Codex profile after
                # setup's part is no edit: ``carried``.
                facts.append(Fact(EDITED, key, None, "edited by hand since setup wrote it", generated))
            continue
        if kind == "text":
            listed = found.get("blocks") or {}
            syntax = found.get("syntax") or blocks.syntax_for(path.name) or blocks.TOML
            for name, known in listed.items():
                part = _block_part(name)
                if data is None:
                    facts.append(Fact(GONE, key, part, f"the file is gone ({there} is there), and setup's block with it"))
                    continue
                try:
                    block = blocks.get(data, syntax, name)
                except blocks.Refusal as exc:
                    facts.append(Fact(UNREADABLE, key, part, f"the file's markers cannot be read: {exc}"))
                    break
                wrote = known.get("sha256") if isinstance(known, dict) else known
                if block is None:
                    facts.append(Fact(GONE, key, part, "setup's block is no longer in the file"))
                elif not blocks.as_written(data, block, wrote):
                    how = (
                        "render writes setup's entries into it again and keeps the rest"
                        if syntax == blocks.GITIGNORE else
                        f"render keeps it and reports it, and `render {render.OVERWRITE_OPTION}` backs the file up "
                        "and writes the block again"
                    )
                    facts.append(Fact(EDITED, key, part, f"changed by hand since setup wrote it; {how}"))
            continue
        listed = found.get("keys") or {}
        if not listed:
            continue
        current: dict[str, Any] | None = None
        if data is not None:
            try:
                current = jsonkeys.parse(data)[1]
            except jsonkeys.Refusal as exc:
                facts.append(Fact(UNREADABLE, key, None, f"the file {exc}, so setup's keys in it cannot be checked"))
                continue
        for name, known in listed.items():
            part = f"key {name}"
            wrote = known.get("value") if isinstance(known, dict) else None
            shown = json.dumps(wrote, ensure_ascii=False)
            if current is None:
                facts.append(Fact(GONE, key, part, f"the file is gone ({there} is there), and the key setup set with it"))
            elif name not in current:
                facts.append(Fact(GONE, key, part, f"the key setup set ({shown}) is no longer in the file"))
            elif not jsonkeys.same(current[name], wrote):
                facts.append(Fact(
                    EDITED, key, part,
                    f"changed by hand since setup set it to {shown}; render keeps it and reports it, and "
                    f"`render {render.OVERWRITE_OPTION}` sets it again",
                ))
    return facts


def _forgotten(probe: Probe | None) -> set[tuple[str, str | None]]:
    """What the record lists, is gone, and ``render`` would no longer make:
    it takes the entry out of the record, and nothing is missing."""
    found: set[tuple[str, str | None]] = set()
    for item in ([] if probe is None else probe.stale):
        if item.status != render.FORGET or item.key is None:
            continue
        part = None
        if item.kind == render.KEY:
            part = f"key {item.name}"
        elif item.kind == render.BLOCK:
            part = _block_part(item.name)
        found.add((paths.fold_key(item.key), part))
    return found


# --- The checks ------------------------------------------------------------------

def check_sources(context: Context) -> list[Finding]:
    """The clone's sources, by ``validate``; role sizes as info."""
    report = context.sources
    findings = [error(problem.text(), problem.file) for problem in report.problems]
    if report.role_sizes:
        from . import roles
        sizes = ", ".join(f"{name} {size:,}" for name, size in report.role_sizes.items())
        findings.append(info(f"role texts, in bytes of {roles.TEXT_LIMIT:,} allowed: {sizes}"))
    if not report.problems:
        findings.insert(0, fine(f"{context.where.clone}: the sources have no problem ({len(report.skills)} skills)"))
    return findings


def check_drift(context: Context) -> list[Finding]:
    """A generated file whose recorded inputs are not today's; a project's
    key or block that ``render`` would write again; what it would remove."""
    record = context.record
    if not record.home.on_disk and not (record.project is not None and record.project.on_disk):
        return [info(NEVER_RENDERED)]
    probe = context.probe
    if probe is None:
        return [info(NOT_PLANNED)]
    again = "the sources or settings it was made from changed since it was written; run render"
    findings = []
    for key, wanted in sorted(probe.inputs.items()):
        found = record.get(key)
        if found is not None and _generated(found) and found.get("inputs") != wanted:
            findings.append(warning(f"{key}: {again}", key))
    for item in probe.items:
        if item.kind in (render.KEY, render.BLOCK) and item.status == render.UPDATE:
            table = "keys" if item.kind == render.KEY else "blocks"
            if probe._recorded(item.key, "json" if item.kind == render.KEY else "text", table, item.name) is not None:
                subject = _item_subject(item)
                findings.append(warning(f"{subject}: {again}", subject))
    for item in probe.stale:
        subject = _item_subject(item)
        if item.status in (render.REMOVE, render.RELEASE):
            findings.append(warning(f"{subject}: {item.says}; run render", subject))
        elif item.status == render.KEPT:
            findings.append(warning(f"{subject}: {item.says}", subject))
    return findings


def check_hand_edits(context: Context) -> list[Finding]:
    """A generated file, a block or a key that is not as setup wrote it."""
    if not context.record.entries:
        return [info(NEVER_RENDERED)]
    findings = []
    for fact in survey(context):
        if fact.state == EDITED:
            detail = fact.detail
            if fact.part is None and fact.generated and "edited by hand" in detail:
                detail += (
                    f"; render keeps it and reports it, and `render {render.OVERWRITE_OPTION}` backs it up and "
                    "replaces it"
                )
            findings.append(warning(f"{fact.subject}: {detail}", fact.subject))
        elif fact.state == UNREADABLE:
            findings.append(warning(f"{fact.subject}: {fact.detail}", fact.subject))
    # What follows setup's part of a Codex profile is no edit; a key there
    # that Codex does not write itself is named, and a risky one warned of.
    for key, _, keys in carried.parts(context.record):
        extra = carried.named(keys)
        for name in extra:
            if name in carried.RISKS:
                findings.append(warning(
                    f"{key}: {name} is set after setup's part: {carried.RISKS[name]}. render keeps it; remove it "
                    "from the file if the role should run as setup wrote it", key,
                ))
        plain = [name for name in extra if name not in carried.RISKS]
        if plain:
            findings.append(info(
                f"{key}: after setup's part it also holds {', '.join(plain)}, which Codex does not write there "
                "itself; render keeps it as yours", key,
            ))
    return findings


def check_missing(context: Context) -> list[Finding]:
    """What the record lists and is gone; what ``render`` would create and
    is not there; what is in the way. See the module for the severities."""
    record = context.record
    probe = context.probe
    forgotten = _forgotten(probe)
    findings = []
    for fact in survey(context):
        if fact.state != GONE:
            continue
        if fact.ident in forgotten:
            findings.append(info(
                f"{fact.subject}: {fact.detail}, and render would no longer make it; the next render takes it "
                "out of the record", fact.subject,
            ))
        elif fact.part is None and not fact.generated:
            findings.append(warning(f"{fact.subject}: {fact.detail}", fact.subject))
        else:
            findings.append(error(f"{fact.subject}: {fact.detail}; run render to have it written again", fact.subject))
    if probe is None:
        return findings + [info(NOT_PLANNED)]

    findings.extend(error(f"render cannot plan the install: {line}") for line in probe.errors)
    # The roles turned off by the setting: said, since nothing of them is
    # then missing. Off by the option is no fact of the install (the probe
    # is given no option).
    home_roles, project_roles = render.roles_report(probe._roles)
    for line in (render.roles_line(home_roles), render.project_roles_line(project_roles)):
        if line is not None:
            findings.append(info(
                f"{line}; render removes what an earlier run generated, unless it was edited by hand"
            ))
    if home_roles is not None and not home_roles["enabled"]:
        # What a project got is not in this home's record, and no check of
        # a home sees it: said once, for every project rendered with roles.
        findings.append(info(render.PROJECTS_LEFT[0].upper() + render.PROJECTS_LEFT[1:]))
    home_rendered = bool(record.home.on_disk)
    project_rendered = record.project is not None and bool(record.project.on_disk)
    home_generated = any(
        _generated(found) and key.partition(":")[0] != fileops.PROJECT for key, found in record.entries.items()
    )
    waiting: dict[str, list[str]] = {"home": [], "roles": [], "project": []}
    skipped: dict[tuple[str | None, str | None], tuple[str, list[str]]] = {}
    v1 = migrate.leftover_paths(context)
    for item in probe.items:
        subject = _item_subject(item)
        if item.status == render.CONFLICT and migrate.fold(item.path) in v1:
            continue  # what a v1 install left: the check `v1` says it, once
        if item.status == render.CONFLICT:
            says = item.says if item.says.startswith(str(item.path)) else f"{item.path}: {item.says}"
            findings.append(error(f"{says}; render stops on it and writes nothing", subject))
        elif item.status == render.ERROR:
            findings.append(error(item.says, subject))
        elif item.status == render.NEEDS_FLAG:
            findings.append(warning(f"{subject}: {item.says}", subject))
        elif item.status == render.EDITED and item.kind in (render.KEY, render.BLOCK, codexsettings.KIND) and \
                probe._recorded(item.key, "json" if item.kind == render.KEY else "text",
                                "keys" if item.kind == render.KEY else "blocks", item.name) is None:
            # Not in the record, so the check `hand-edits` does not see it.
            findings.append(warning(f"{subject}: {item.says}", subject))
        elif item.status == render.SKIPPED and item.whole_place:
            skipped.setdefault((item.provider, item.place), (item.says, []))[1].append(item.name)
        elif item.status == render.CREATE:
            if item.kind in (render.LINK, render.FILE):
                listed = item.key is not None and record.get(item.key) is not None
            else:
                table, kind = ("keys", "json") if item.kind == render.KEY else ("blocks", "text")
                listed = probe._recorded(item.key, kind, table, item.name) is not None
            if listed:
                continue  # the record lists it and it is gone: said above, or by the check `links`
            if item.project:
                group = None if project_rendered else "project"
            elif not home_rendered:
                group = "home"
            elif item.kind == render.FILE and not home_generated:
                group = "roles"
            else:
                group = None
            if group is not None:
                waiting[group].append(subject)
            else:
                findings.append(warning(
                    f"{subject}: not installed: render would create it, and the record does not list it (the "
                    "clone or the settings gained it since the last render); run render", subject,
                ))
    for (provider, place), (says, names) in skipped.items():
        findings.append(info(
            f"{provider} {place}: {says}; not checked from this side: {', '.join(names)}"
        ))
    if waiting["home"]:
        findings.append(info(
            f"not rendered yet: no run of setup has written to this home; render would create "
            f"{len(waiting['home'])} links and files"
        ))
    if waiting["roles"]:
        findings.append(info(
            f"no role definition or entry point is installed: the record holds no generated file (the home was "
            f"rendered with {render.NO_ROLES_OPTION}); render would write {len(waiting['roles'])} files"
        ))
    if waiting["project"]:
        findings.append(info(
            f"not rendered in the project yet: `render --project` would write {len(waiting['project'])} things "
            f"there ({', '.join(waiting['project'])})"
        ))
    return findings


def check_links(context: Context) -> list[Finding]:
    """Each link the record lists: there, a link, pointing where setup
    pointed it, to something that exists, inside the clone."""
    record = context.record
    links = sorted((key, found) for key, found in record.entries.items() if found.get("kind") == "link")
    if not links:
        return [info(NEVER_RENDERED if not context.rendered() else "the record lists no link")]
    forgotten = _forgotten(context.probe)
    clone = os.path.realpath(context.homes.clone)
    findings = []
    for key, found in links:
        try:
            path = record.path(key)
            recorded = context.roots.target_text(found["target"])
            seen = fsio.look(path)
        except SetupError as exc:
            findings.append(error(f"{key}: {exc.lines[0]}", key))
            continue
        except (KeyError, TypeError):
            findings.append(error(f"{key}: the record's entry for this link cannot be read", key))
            continue
        if seen.kind == fsio.ABSENT:
            if (paths.fold_key(key), None) in forgotten:
                findings.append(info(f"{key}: the link is gone, and render would no longer make it", key))
            else:
                findings.append(error(f"{key}: the link is missing; setup made it a link to {recorded}. Run render", key))
            continue
        if seen.kind != fsio.LINK:
            findings.append(error(f"{key}: no longer a link: a {seen.kind} is there; setup made it a link to {recorded}", key))
            continue
        real = os.path.realpath(path)
        if not fsio.same_target(seen.target or "", recorded):
            outside = "" if _inside(real, clone) else ", outside the clone"
            findings.append(error(
                f"{key}: the link now leads to {seen.target}{outside}; setup made it a link to {recorded}, and it "
                "was changed since", key,
            ))
        elif not os.path.exists(real):
            findings.append(error(
                f"{key}: the link's target does not exist: {seen.target} (a moved or removed clone?); run render "
                "from the clone in use", key,
            ))
        elif not _inside(real, clone):
            findings.append(error(f"{key}: the link resolves to {real}, outside the clone {clone}", key))
    return findings


def _is_skill(path: Path) -> bool:
    try:
        return os.path.isfile(path / validate.SKILL_FILE)
    except (OSError, ValueError):
        return False


def check_duplicate_skills(context: Context) -> list[Finding]:
    """A skill name setup installs that also exists in another skill
    location of the same provider."""
    try:
        # A loaded role is a skill setup installs only while the home's
        # roles are on (``roles.enabled``).
        enabled = render.home_roles_setting(context.where)
        loaded = entry.loaded_roles(context.user_level) if enabled is None or enabled.value is not False else []
    except SetupError:
        loaded = []  # the check `sources` or `profiles` says why
    project = context.homes.project
    findings = []
    looked = 0
    for provider in context.installed():
        if not any(place.name == homes.SKILLS for place in provider.places):
            continue
        install = provider.place(homes.SKILLS).path
        names = sorted({
            name for name, skill in context.sources.skills.items()
            if provider.name in skill.providers and not skill.own_setup
        } | set(loaded))
        others: list[tuple[Path, str]] = []
        if any(place.name == homes.OLD_SKILLS for place in provider.places):
            others.append((provider.place(homes.OLD_SKILLS).path, "the deprecated skills directory, which Codex still reads"))
        if project is not None and provider.name in PROJECT_SKILLS:
            others.append((project.joinpath(*PROJECT_SKILLS[provider.name]), "the project's skills directory"))
        consequence = (
            "Codex does not merge two skills of one name and lists both"
            if provider.name == homes.CODEX else "two skills of one name are offered"
        )
        for directory, what in others:
            if paths.same(os.path.realpath(directory), os.path.realpath(install)):
                continue  # one directory under two names
            looked += 1
            for name in names:
                if _is_skill(directory / name):
                    findings.append(warning(
                        f"{provider.name}: the skill {name} is in two places: {install / name}, where setup "
                        f"installs it, and {directory / name}, in {what}{context.whose(directory)}; {consequence}",
                        directory / name,
                    ))
    if not findings and not looked:
        return [info("no other skill location to look in")]
    return findings


def looks_like_clone(directory: Path) -> bool:
    """Whether ``directory`` holds what a clone of this repository holds;
    see ``CLONE_MARKS``. Nothing is opened and git is not asked."""
    try:
        return os.path.isfile(directory.joinpath(*CLONE_MARKS[0])) and os.path.isdir(directory.joinpath(*CLONE_MARKS[1]))
    except (OSError, ValueError):
        return False


def clone_above(real: Path) -> Path | None:
    """The nearest directory, from ``real`` upward, that looks like a clone."""
    for candidate in [real, *real.parents][:_CLONE_DEPTH]:
        if looks_like_clone(candidate):
            return candidate
    return None


def holds_clone(directory: Path, skills: Iterable[str] = ()) -> bool:
    """Whether a directory is a clone of this repository by what it holds:
    the marks of ``looks_like_clone``, or a ``.git`` entry beside one of
    the clone's skills (a clone from before the setup tool). The check
    ``other-clones`` and the v1 migration share the rule."""
    return looks_like_clone(directory) or (
        os.path.lexists(directory / ".git") and any(_is_skill(directory / name) for name in skills)
    )


def check_v1(context: Context) -> list[Finding]:
    """What a v1 install left (R6.11): see ``migrate.findings``."""
    return [Finding(severity, detail, subject) for severity, detail, subject in migrate.findings(context)]


def check_other_clones(context: Context) -> list[Finding]:
    """Links, in the skills and rules places or in the record, that lead
    into another clone of this repository; a clone inside a skills place."""
    clone = Path(os.path.realpath(context.homes.clone))
    candidates: dict[str, Path] = {}
    directories = [
        place.path for provider in context.homes.providers for place in provider.places
        if place.name in (homes.SKILLS, homes.OLD_SKILLS, homes.RULES)
    ]
    if context.homes.project is not None:
        directories += [context.homes.project.joinpath(*parts) for parts in PROJECT_SKILLS.values()]
    for directory in directories:
        try:
            names = paths.entries(directory)
        except SetupError:
            continue
        for item in names:
            # A dot entry is not a skill or a rule of anyone's installing:
            # Codex keeps its bundled skills in ``skills/.system``.
            if not fsio.is_credentials(item) and not item.name.startswith("."):
                candidates.setdefault(paths.fold(item), item)
    for key, found in context.record.entries.items():
        if found.get("kind") == "link":
            try:
                item = context.record.path(key)
            except SetupError:
                continue
            candidates.setdefault(paths.fold(item), item)

    skills = set(context.sources.skills)
    findings = []
    for item in candidates.values():
        try:
            seen = fsio.look(item)
        except SetupError:
            continue
        real = Path(os.path.realpath(item))
        if seen.kind == fsio.LINK:
            if _inside(real, clone):
                continue
            other = clone_above(real)
            if other is None:
                continue
            if item.name in homes.OWN_SETUP_SKILLS:
                findings.append(info(
                    f"{item}: the collaboration skill runs from another clone, {other}{context.whose(other)}. That "
                    "is as intended where it is the development clone (it has a setup of its own)", item,
                ))
            else:
                findings.append(warning(
                    f"{item}: a link into another clone of this repository, {other}{context.whose(other)}; this "
                    f"run's clone is {clone}. Every home links to one clone", item,
                ))
        elif seen.kind == fsio.DIRECTORY and item.name not in homes.OWN_SETUP_SKILLS:
            if holds_clone(item, skills) and not _inside(real, clone) and not _inside(clone, real):
                findings.append(warning(
                    f"{item}: another clone of this repository, inside a directory the provider reads skills "
                    "from; setup never removes a clone, it is yours to move away", item,
                ))
    return findings


def check_clone(context: Context) -> list[Finding]:
    """Whether both sides of the machine can read the clone (R6.9). Allowed
    by the setting ``setup.allow_unshared_clone``, a clone only this side
    reads is info: decided once, it is no longer a thing to look at on every
    run. Allowed by the option alone, it is a warning, as before. A setting
    that allows it where it is not needed is said as info."""
    found = homes.clone_standing(context.homes)
    allowance = homes.clone_allowance(context.where, bool(context.option("allow_unshared_clone", False)))
    unneeded = []
    if allowance.by == homes.BY_SETTING and allowance.setting is not None:
        said = "not used here, where the question is not asked" if found.shared is None else \
            "not needed for this clone"
        unneeded = [info(
            f"{homes.UNSHARED_KEY} = true in {allowance.setting.file} ({allowance.setting.layer} layer): {said}; it "
            "allows a clone only this side reads, on every run of render and doctor"
        )]
    if found.shared is None:
        return [info(f"{found.real}: {found.why}"), *unneeded]
    if found.shared:
        return [fine(f"{found.real}: {found.why}"), *unneeded]
    line = (
        f"{found.real}: the clone setup runs from is {found.why}. Every home, on Windows and in WSL, links to one "
        "clone that both can read"
    )
    if allowance.by == homes.BY_SETTING:
        return [info(f"{line}; {allowance.describe()}: this side installs from its own clone", found.real)]
    if allowance.by == homes.BY_OPTION:
        return [warning(f"{line}; {allowance.describe()}", found.real)]
    return [error(
        f"{line}: clone the repository to a directory on a Windows drive and run setup from there, or give "
        f"{homes.UNSHARED_OPTION} to accept this clone for this side alone for one run, or set "
        f"{homes.UNSHARED_KEY} = true in ~/.agents/workflow.toml (`init {homes.UNSHARED_OPTION}`) for every run",
        found.real,
    )]


def mapping_in_effect(context: Context, provider: str) -> dict[str, str]:
    """The provider's mapping as the settings resolve it, by the keys
    ``modellist.mapping_of`` uses: ``tiers.<tier>``, ``role_models.<id>``."""
    prefix = f"providers.{provider}."
    found = {}
    for key, value in context.provider_settings.items():
        if key.startswith(prefix):
            table, _, name = key[len(prefix):].partition(".")
            if table in ("tiers", "role_models") and isinstance(value.value, str) and value.value:
                found[f"{table}.{name}"] = value.value
    return found


def check_models(context: Context) -> list[Finding]:
    """Each installed provider's own model list beside its mapping (G11)."""
    findings = []
    for provider in context.homes.providers:
        name = provider.name
        if not provider.installed:
            findings.append(info(f"{name}: not installed; nothing to check"))
            continue
        known = context.dictionaries.get(name)
        if known is None:
            findings.append(info(f"{name}: the clone has no dictionary for it; nothing to check"))
            continue
        if known.model_list.command is None:
            findings.append(info(f"{name}: {modellist.read(known, context.environ).describe()}"))
            continue
        if provider.program_file is None:
            findings.append(info(
                f"{name}: the program `{provider.program}` is not on PATH, so its list is not read; the "
                "dictionary alone is used"
            ))
            continue
        mapping = mapping_in_effect(context, name)
        reading, found = modellist.check(known, context.child_environ, mapping=mapping,
                                         program_file=provider.program_file)
        if found is None:
            findings.append(warning(f"{name}: {reading.describe()}"))
            continue
        before = len(findings)
        show = json.dumps
        mapped = set(mapping.values())
        for key, model in found.missing_mapped:
            findings.append(error(
                f"{name}: {key} = {show(model)}: the model is not in the provider's list; map the key to a listed "
                "model (`init`, or the settings file)", key,
            ))
        for key, model in found.hidden_mapped:
            findings.append(warning(f"{name}: {key} = {show(model)}: the list holds the model as a hidden entry", key))
        for difference in found.effort_differences:
            line = (
                f"{name}: {difference.model}: the dictionary has the efforts "
                f"{', '.join(difference.dictionary) or 'none'}; the list has {', '.join(difference.listed) or 'none'}"
            )
            findings.append(warning(f"{line}; a mapped model", difference.model) if difference.model in mapped
                            else info(line, difference.model))
        checked = modellist.effective(known, reading)
        try:
            resolved = context.resolution.profiles
        except SetupError:
            resolved = ()  # the check `profiles` says why
        for profile in resolved:
            if profile.provider == name and profile.effort is not None \
                    and checked.accepts(profile.model, profile.effort) is False:
                findings.append(error(
                    f"{name}: the definition {profile.definition} resolves to the model {profile.model} with the "
                    f"effort {profile.effort}, which the provider's list does not give that model", profile.definition,
                ))
        problems = len(findings) > before
        other = [
            line for line in modellist.compare(known, reading, {}).lines()
            if not any(line.startswith(f"{difference.model}: the dictionary has the efforts")
                       for difference in found.effort_differences)
        ]
        findings.extend(info(f"{name}: {line} (the dictionary may be stale)") for line in other)
        if reading.source == modellist.OFFLINE:
            findings.append(info(f"{name}: {reading.describe()}"))
        elif not problems:
            findings.append(fine(f"{name}: {reading.describe()}; every mapped model is offered"))
    return findings


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = list(dictionary.parse_version(text))
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def check_versions(context: Context) -> list[Finding]:
    """Each installed provider's version beside its dictionary (G3)."""
    findings = []
    for provider in context.homes.providers:
        name = provider.name
        if not provider.installed:
            findings.append(info(f"{name}: not installed; nothing to check"))
            continue
        known = context.dictionaries.get(name)
        if known is None:
            findings.append(info(f"{name}: the clone has no dictionary for it; nothing to compare a version with"))
            continue
        if provider.program_file is None:
            findings.append(info(f"{name}: the program `{provider.program}` is not on PATH, so its version is not read"))
            continue
        asked = f"`{provider.program} --version`"
        try:
            code, out, said = modellist.run_program(
                (provider.program_file, "--version"), context.child_environ, VERSION_TIMEOUT
            )
        except modellist.ProgramFailed as exc:
            findings.append(warning(f"{name}: the version cannot be read: {asked} {exc}"))
            continue
        if code != 0:
            findings.append(warning(
                f"{name}: the version cannot be read: {asked} exited with code {code}" + (f": {said}" if said else "")
            ))
            continue
        version = dictionary.find_version(out)
        if version is None:
            findings.append(warning(f"{name}: the version cannot be read: {asked} printed no version"))
            continue
        mine = _version_tuple(version)
        oldest = known.oldest_supported_version
        if mine > _version_tuple(known.checked_on_version):
            findings.append(warning(
                f"{name}: version {version} is newer than {known.checked_on_version}, the version the dictionary "
                f"was checked on ({known.checked_on_date}); the dictionary may be stale", name,
            ))
        elif oldest is not None and mine < _version_tuple(oldest):
            what = BELOW_OLDEST.get(name, "below it the framework was not checked")
            findings.append(warning(
                f"{name}: version {version} is older than {oldest}, the oldest supported; {what}. Update {provider.program}",
                name,
            ))
        else:
            findings.append(fine(f"{name}: version {version} (the dictionary was checked on {known.checked_on_version})"))
    return findings


@dataclass(frozen=True)
class CodexSettings:
    """The keys of ``CODEX_KEYS`` as the user's Codex ``config.toml`` has
    them. ``values`` holds ``UNSET`` for a key that is not set. ``fault`` is
    why the file could not be read; ``present`` is whether there is a file."""

    path: Path
    present: bool
    values: dict[str, Any]
    fault: str | None = None


_TOML_PLACE = re.compile(r"\(at (line \d+, column \d+|end of document)\)")


def codex_settings(context: Context) -> CodexSettings | None:
    """Read the keys of ``CODEX_KEYS`` (the three of R6.7 and the size
    limit of the check ``instruction-files``) and nothing else; None when Codex is
    not installed. No other key is kept, and a fault names only its place."""
    provider = context.homes.provider(homes.CODEX)
    if not provider.installed:
        return None
    path = provider.place(homes.CONFIG).path
    unset = {key: UNSET for key in CODEX_KEYS}
    try:
        seen = fsio.look(path)
        if seen.kind == fsio.ABSENT:
            return CodexSettings(path, False, unset)
        # Anything but a regular file, a FIFO among them, is never opened.
        if seen.kind not in (fsio.FILE, fsio.LINK) or (seen.kind == fsio.LINK and not os.path.isfile(path)):
            return CodexSettings(path, True, unset, "is not a file that can be read")
        data = fsio.read_bytes(Path(os.path.realpath(path)) if seen.kind == fsio.LINK else path)
    except SetupError as exc:
        return CodexSettings(path, True, unset, exc.lines[0].removeprefix(f"{path}: "))
    try:
        parsed = tomllib.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return CodexSettings(path, True, unset, "is not UTF-8 text")
    except (tomllib.TOMLDecodeError, RecursionError) as exc:
        place = _TOML_PLACE.search(str(exc))
        return CodexSettings(path, True, unset, "is not valid TOML" + (f" ({place.group(1)})" if place else ""))
    values = {}
    for key in CODEX_KEYS:
        value: Any = parsed
        for part in key.split("."):
            value = value.get(part, UNSET) if isinstance(value, dict) else UNSET
        values[key] = value
    return CodexSettings(path, True, values)


def _plain(value: Any) -> str | None:
    """A scalar as it is shown; None for anything that is not one."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = "".join(char if char.isprintable() else " " for char in value)
        return json.dumps(text if len(text) <= 80 else text[:80] + "...", ensure_ascii=False)
    return None


def check_codex_settings(context: Context) -> list[Finding]:
    """The Codex settings the framework needs (R6.7), reported and never
    changed. P5.10 extends this."""
    found = codex_settings(context)
    if found is None:
        return [info("codex: not installed; nothing to check")]
    whose = context.whose(found.path)
    if found.fault is not None:
        return [warning(f"{found.path}{whose}: {found.fault}; the Codex settings cannot be read", found.path)]
    findings = []
    if not found.present:
        findings.append(info(f"{found.path}: no such file; every key below is unset"))

    def shown(key: str) -> str:
        value = found.values[key]
        return _plain(value) or f"set to a {type(value).__name__}, which is not a value this key takes"

    threads = found.values[THREADS_KEY]
    need = (
        f"the framework needs {THREADS_NEEDED} or more: the limit counts spawned threads and not the primary one, "
        "and under the Manager run an Implementation Manager, three Coders and a reviewer"
    )
    if threads is UNSET:
        findings.append(info(f"{THREADS_KEY}: unset, so Codex chooses the default; {need}", THREADS_KEY))
    elif isinstance(threads, bool) or not isinstance(threads, int):
        findings.append(warning(f"{THREADS_KEY} = {shown(THREADS_KEY)}: not a whole number; {need}", THREADS_KEY))
    elif threads < THREADS_NEEDED:
        findings.append(warning(f"{THREADS_KEY} = {threads}: below {THREADS_NEEDED}; {need}", THREADS_KEY))
    else:
        findings.append(fine(f"{THREADS_KEY} = {threads}", THREADS_KEY))

    findings.extend(_wait_findings(found.values, shown))

    sandbox, permissions = found.values[SANDBOX_KEY], found.values[PERMISSIONS_KEY]
    # Setup's own profile files may carry either key after setup's part
    # (``carried``): a session started with the profile then has it.
    try:
        profiles_found = carried.parts(context.record)
    except SetupError:
        profiles_found = []
    for key_name in (SANDBOX_KEY, PERMISSIONS_KEY):
        for subject, _, keys in profiles_found:
            if key_name in keys:
                value = _plain(keys[key_name]) or f"a {type(keys[key_name]).__name__}"
                findings.append(info(
                    f"{subject} sets {key_name} = {value} after setup's part: a session started with that profile "
                    f"has it, whatever {found.path.name} says", key_name,
                ))
    if sandbox is UNSET:
        findings.append(info(f"{SANDBOX_KEY}: unset in {found.path.name}", SANDBOX_KEY))
    else:
        findings.append(info(
            f"{SANDBOX_KEY} = {shown(SANDBOX_KEY)}: while this key is set in any loaded config, Codex uses the older "
            f"sandbox settings instead of {PERMISSIONS_KEY}, so a permission profile has no effect; setup never "
            "changes or removes the key", SANDBOX_KEY,
        ))
    if permissions is UNSET:
        findings.append(info(f"{PERMISSIONS_KEY}: unset in {found.path.name}", PERMISSIONS_KEY))
    else:
        ignored = "" if sandbox is UNSET else f"; not used while {SANDBOX_KEY} is set"
        findings.append(info(f"{PERMISSIONS_KEY} = {shown(PERMISSIONS_KEY)}{ignored}", PERMISSIONS_KEY))
    if whose:
        findings.append(info(f"{found.path}:{whose}"))
    return findings


def _wait_findings(values: dict[str, Any], shown: Callable[[str], str]) -> list[Finding]:
    """The wait floor of ``wait_agent``: the minimum graded, the default and
    the maximum as info where they are set, and an order Codex refuses."""
    needed = codexsettings.WAIT_MIN_NEEDED
    need = (
        f"the framework needs {needed} or more: a wait_agent with a short timeout wakes its caller, and each "
        "wake-up reads the caller's whole context again"
    )
    low = values[WAIT_MIN_KEY]
    findings = []
    if low is UNSET:
        findings.append(info(
            f"{WAIT_MIN_KEY}: unset, so Codex's own floor of {codexsettings.WAIT_CODEX[codexsettings.WAIT_MIN]} ms "
            f"applies; {need}", WAIT_MIN_KEY,
        ))
    elif isinstance(low, bool) or not isinstance(low, int):
        findings.append(warning(f"{WAIT_MIN_KEY} = {shown(WAIT_MIN_KEY)}: not a whole number; {need}", WAIT_MIN_KEY))
    elif low < needed:
        findings.append(warning(f"{WAIT_MIN_KEY} = {low}: below {needed}; {need}", WAIT_MIN_KEY))
    else:
        findings.append(fine(f"{WAIT_MIN_KEY} = {low}", WAIT_MIN_KEY))
    for key in (WAIT_DEFAULT_KEY, WAIT_MAX_KEY):
        if values[key] is not UNSET:
            findings.append(info(f"{key} = {shown(key)}", key))
    # A key left out takes Codex's own value (``UNSET`` here is not the module's).
    order = codexsettings.wait_order({
        key.rsplit(".", 1)[1]: values[key] for key in codexsettings.WAIT_KEYS if values[key] is not UNSET
    })
    if order:
        findings.append(warning(f"{codexsettings.WAIT_TABLE}: {order}", codexsettings.WAIT_TABLE))
    return findings


def check_profiles(context: Context) -> list[Finding]:
    """The resolver's notes as warnings, and its faults as errors."""
    try:
        found = context.resolution
    except SetupError as exc:
        return [error(line) for line in exc.lines]
    findings = [warning(note) for note in found.notes]
    return findings or [fine(f"{len(found.profiles)} profiles resolve, and every setting matches something")]


def check_interrupted_run(context: Context) -> list[Finding]:
    """An earlier run that stopped between its record and its changes."""
    record = context.record
    findings: list[Finding] = []
    if record.recovered or record.dropped:
        made = f": {', '.join(record.recovered_paths)}" if record.recovered_paths else ""
        left = f": {', '.join(record.dropped_paths)}" if record.dropped_paths else ""
        findings.append(warning(
            f"an earlier run of setup was interrupted: {record.recovered} of its changes were made and are taken as "
            f"installed{made}; {record.dropped} were not made and are dropped{left}. Nothing is unrecorded; the next "
            "render completes the record and makes what is missing"
        ))
    roots = context.roots
    found = fileops.leftovers(roots)

    def named(paths_found: list[Any]) -> str:
        shown = ", ".join(str(path) for path in paths_found[:5])
        return shown + (f" and {len(paths_found) - 5} more" if len(paths_found) > 5 else "")

    if found.temporaries:
        findings.append(warning(
            f"an interrupted run left {len(found.temporaries)} temporary files that its record lists "
            f"({named(found.temporaries)}); the next run that writes removes them"
        ))
    if found.lock:
        findings.append(warning(
            f"an interrupted run left pieces of its start or of its lock ({named(found.lock)}); the next run that "
            "writes, or `uninstall`, removes them"
        ))
    if found.unlisted:
        findings.append(warning(
            f"{len(found.unlisted)} backups are under a state directory and no record lists them "
            f"({named(found.unlisted)}); setup removes none of them by itself. Look at them, then "
            "`uninstall --discard-backups` (with --project DIR for a project's) removes them"
        ))
    if found.lookalikes:
        findings.append(info(
            f"{len(found.lookalikes)} entries are named like a temporary file of setup's and no record lists them "
            f"({named(found.lookalikes)}); setup leaves them alone, they are yours"
        ))
    for project in roots.scopes():
        held = fileops.lock.holder(roots, project)
        if held is None:
            continue
        said, state_of, why = held
        where = fileops.lock.lock_file(roots, project)
        if state_of == fileops.lock.RUNNING:
            findings.append(info(f"a setup run is writing right now ({fileops.lock.describe(said)}): {where}"))
        elif state_of == fileops.lock.GONE:
            findings.append(warning(
                f"{where}: the lock of a setup run that ended without giving it back "
                f"({fileops.lock.describe(said)}); the next run that writes clears it"
            ))
        else:
            findings.append(warning(
                f"{where}: a lock that setup cannot judge ({why}); once no setup run is using this "
                f"{'project' if project else 'home'}, remove that file"
            ))
    return findings


def loaded_skill_warning(one: entry.Made) -> str:
    """What is said of a loaded role's skill that is over its provider's
    limit (``skills.compaction_tokens`` in the provider's dictionary)."""
    size = f"{one.provider}: the loaded role {one.role} is about {one.tokens:,} tokens ({one.size:,} bytes)"
    why = (
        f"after a compaction {one.provider_name} keeps the first {one.limit_tokens:,} tokens of an invoked "
        "skill, so its end is likely to be cut: the role's binding rows and the action notes"
    )
    return (
        f"{size}; {why}. The shipped roles are within it with the shipped settings, so a setting of yours "
        "made this one longer (a longer model name, or a provider home moved by a variable); shorten the "
        "role's text if you changed it"
    )


def check_loaded_skill_size(context: Context) -> list[Finding]:
    """A loaded role whose skill, made with the user's settings, is over
    the limit ``validate`` holds the shipped roles to, on a provider whose
    dictionary has one; on a provider with none, the sizes as info."""
    if not context.sources.ok:
        return [info(NOT_PLANNED)]
    enabled = render.home_roles_setting(context.where)
    if enabled is not None and enabled.value is False:
        return [info(
            f"{render.ROLES_KEY} = false in {enabled.file} ({enabled.layer} layer): no role is installed as a skill; "
            "nothing to measure"
        )]
    names = [provider.name for provider in context.installed() if provider.name in definitions.PROVIDERS]
    made = [one for one in entry.skills(context.user_level, names, context.homes)
            if one.name.endswith(entry.SKILL_FILE)]
    if not made:
        return [info("no role is loaded as a skill")]
    if context.rendered():
        # A home that was rendered is judged by what is installed in it: a
        # role whose skill is not there (``render --no-roles``) is cut by
        # nothing.
        places = {
            provider.name: provider.place(homes.SKILLS).path
            for provider in context.installed()
            if any(place.name == homes.SKILLS for place in provider.places)
        }
        made = [one for one in made if one.provider in places and fsio.is_file(places[one.provider] / one.name)]
        if not made:
            return [info("no role is installed as a skill in this home (rendered with --no-roles); nothing to measure")]
    findings: list[Finding] = []
    # One finding per provider: warnings for each skill over its provider's
    # limit, or one line that none is; and where the provider documents no
    # cut, no limit, and its sizes are said.
    for provider in dict.fromkeys(one.provider for one in made):
        mine = [one for one in made if one.provider == provider]
        limit = mine[0].limit_tokens
        if limit is None:
            sizes = ", ".join(f"{one.role} about {one.tokens:,} tokens ({one.size:,} bytes)" for one in mine)
            findings.append(info(f"{provider}: no limit on a loaded role's skill (its dictionary names no "
                                 f"skills.compaction_tokens); {sizes}"))
            continue
        over = [warning(loaded_skill_warning(one), one.role) for one in mine if one.over_limit]
        findings.extend(over or [fine(f"{provider}: {len(mine)} loaded-role skills, none estimated over "
                                      f"{limit:,} tokens")])
    return findings


def collab_installs(context: Context) -> tuple[dict[str, tuple[Path, list[str]]], list[Path]]:
    """Where the collaboration skill is installed: by the real path of its
    doctor's script, the script as the link gives it and the providers
    (in that skill's names) whose skills place has the link; and the places
    looked in."""
    found: dict[str, tuple[Path, list[str]]] = {}
    looked = []
    for provider in context.homes.providers:
        if provider.name not in COLLAB_AGENTS or not any(place.name == homes.SKILLS for place in provider.places):
            continue
        link = provider.place(homes.SKILLS).path / COLLAB_SKILL
        looked.append(link)
        script = link.joinpath(*COLLAB_SCRIPT)
        if os.path.isfile(script):
            ident = paths.fold(os.path.realpath(script))
            found.setdefault(ident, (script, []))[1].append(COLLAB_AGENTS[provider.name])
    return found, looked


def check_collaboration_skill(context: Context) -> list[Finding]:
    """The collaboration skill's own doctor, started and reported (R1.2)."""
    installs, looked = collab_installs(context)
    if not installs:
        return [info(
            f"not installed: no {COLLAB_SKILL} skill at {' or '.join(str(link) for link in looked)}; that skill has "
            "a setup of its own"
        )]
    findings = []
    for script, agents in installs.values():
        agent = "both" if len(agents) > 1 else agents[0]
        argv = (sys.executable, "-B", str(script), "doctor", "--agent", agent, "--home", str(context.homes.home), "--json")
        asked = f"its doctor ({script}, --agent {agent})"
        try:
            code, out, said = modellist.run_program(argv, context.child_environ, COLLAB_TIMEOUT)
        except modellist.ProgramFailed as exc:
            findings.append(warning(f"{asked} {exc}; nothing is known about the skill's state", script))
            continue
        try:
            answer = json.loads(out)
            checks = answer["checks"]
            if not isinstance(checks, list) or not all(isinstance(item, dict) for item in checks):
                raise ValueError
        except (ValueError, KeyError, TypeError, RecursionError):
            findings.append(warning(
                f"{asked} exited with code {code} and printed what is not its JSON report"
                + (f": {said}" if said else "") + "; nothing is known about the skill's state", script,
            ))
            continue
        bad = [item for item in checks if item.get("ok") is not True]
        for item in bad:
            make = error if item.get("severity") == ERROR else warning
            findings.append(make(f"{item.get('name')}: {item.get('detail')}", item.get("name")))
        failed = sum(1 for item in bad if item.get("severity") == ERROR)
        if answer.get("ok") is not True and not failed:
            findings.append(error(f"{asked} reports a failure (exit code {code}) and names no failed check", script))
        elif failed:
            findings.append(info(f"{asked}: {failed} of {len(checks)} checks failed, {len(bad) - failed} warn"))
        elif bad:
            findings.append(info(f"{asked}: no check failed, {len(bad)} of {len(checks)} warn"))
        else:
            findings.append(fine(f"{asked}: all {len(checks)} checks pass"))
    return findings


# --- The registry ----------------------------------------------------------------

def _switch(option: str, text: str) -> Callable[[Any], None]:
    def configure(parser: Any) -> None:
        parser.add_argument(option, action="store_true", help=text)
    return configure


CHECKS: tuple[Check, ...] = (
    Check("sources", check_sources, "the clone's sources have no problem"),
    Check("drift", check_drift, "every generated file was made from the sources and settings as they are now"),
    Check("hand-edits", check_hand_edits, "every generated file, block and key is as setup wrote it"),
    Check("missing", check_missing, "everything the record lists is there, and render would create nothing"),
    Check("links", check_links, "every recorded link is there and leads into the clone"),
    Check("duplicate-skills", check_duplicate_skills, "no skill setup installs is in a second skill location"),
    Check("other-clones", check_other_clones, "no link leads into another clone of this repository"),
    Check("v1", check_v1, "no import line, copy or link of a v1 install remains"),
    Check("clone", check_clone, "the clone can be read by both sides"),
    Check("models", check_models, "every mapped model is in its provider's list", switch="no_model_list",
          configure=_switch("--no-model-list", "do not start a provider's list command; the check `models` is left out")),
    Check("versions", check_versions, "every provider is a version the dictionaries were checked on", switch="no_versions",
          configure=_switch("--no-versions", "do not start `<program> --version`; the check `versions` is left out")),
    Check("codex-settings", codexsettings.check, "the Codex settings are as the framework needs",
          configure=codexsettings.configure_check),
    Check("profiles", check_profiles, "every profile resolves"),
    Check("interrupted-run", check_interrupted_run, "no run of setup was interrupted"),
    Check("loaded-skill-size", check_loaded_skill_size, "no loaded role is over the compaction limit"),
    Check(instructions.NAME, instructions.check, "both providers load the project's AGENTS.md"),
    Check("discovery", discovery.check_discovery, "each provider lists what setup installed", configure=discovery.configure),
    Check("collaboration-skill", check_collaboration_skill, "the collaboration skill's doctor reports no problem",
          switch="no_collab",
          configure=_switch("--no-collab", "do not start the collaboration skill's own doctor; that check is left out")),
)


def names() -> list[str]:
    return [check.name for check in CHECKS]


def select(options: Any = None, only: Iterable[str] = (), skip: Iterable[str] = ()) -> tuple[list[Check], list[str]]:
    """The checks to run, in the registry's order, and the names left out.
    A name that is no check is a ``SetupError``."""
    only, skip = list(only or ()), list(skip or ())
    known = names()
    unknown = [name for name in [*only, *skip] if name not in known]
    if unknown:
        raise SetupError(*[f"{name}: not a check; the checks are: {', '.join(known)}" for name in dict.fromkeys(unknown)])
    chosen, left = [], []
    for check in CHECKS:
        switched = bool(check.switch and getattr(options, check.switch, False))
        if only:
            wanted = check.name in only and not (check.default and switched)
        else:
            wanted = check.default != switched
        if wanted and check.name not in skip:
            chosen.append(check)
        else:
            left.append(check.name)
    return chosen, left


def run(context: Context, checks: Iterable[Check]) -> list[Outcome]:
    """Run each check. One that raises becomes an error finding of its own
    name; the others still run."""
    outcomes = []
    for check in checks:
        try:
            findings = list(check.run(context))
        except SetupError as exc:
            findings = [error(f"the check {check.name} could not be made: {line}") for line in exc.lines]
        except Exception as exc:  # a fault of the check itself: reported, never a traceback
            why = " ".join(f"{type(exc).__name__}: {exc}".split())
            findings = [error(f"the check {check.name} failed: {why}")]
        outcomes.append(Outcome(check.name, tuple(findings or [fine(check.fine)])))
    return outcomes


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def report(context: Context, outcomes: list[Outcome], left_out: Iterable[str] = ()) -> dict[str, Any]:
    """What was found, as plain data: what ``--json`` prints."""
    counts = {severity: 0 for severity in SEVERITIES}
    for outcome in outcomes:
        for found in outcome.findings:
            counts[found.severity] += 1
    found = context.homes
    summary = (
        f"{_plural(counts[ERROR], 'error')}, {_plural(counts[WARNING], 'warning')}, {counts[INFO]} info, "
        f"{counts[OK]} ok, in {_plural(len(outcomes), 'check')}"
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "side": found.host.side,
        "home": str(found.home),
        "clone": str(found.clone),
        "project": None if found.project is None else str(found.project),
        "checks": [
            {"name": outcome.name, "severity": outcome.severity,
             "findings": [one.as_json() for one in outcome.findings]}
            for outcome in outcomes
        ],
        "not_run": list(left_out),
        "starts_programs": [outcome.name for outcome in outcomes if outcome.name in STARTERS],
        "saves_probe": context.option("save_probe") if "discovery" in [outcome.name for outcome in outcomes] else None,
        "counts": counts,
        "summary": summary,
        "exit_code": 1 if counts[ERROR] else 0,
    }


def report_lines(found: dict[str, Any]) -> list[str]:
    """The report as text: the findings by check, then one line of counts."""
    started = list(found.get("starts_programs") or [])
    # The one thing doctor writes, and only where it was asked for.
    writes = "writes nothing" if not found.get("saves_probe") else (
        f"writes nothing but the probe output asked for, into {found['saves_probe']}"
    )
    if started:
        banner = (
            f"doctor: setup itself {writes}. The {'check' if len(started) == 1 else 'checks'} "
            f"{', '.join(started)} {'starts a program' if len(started) == 1 else 'start programs'} of the "
            "providers, which may write state of their own into their own home; left out with "
            f"{', '.join(STARTERS[name] for name in started)}"
        )
    else:
        banner = f"doctor: setup itself {writes}, and this run starts no program of a provider"
    lines = [
        banner,
        f"clone: {found['clone']}",
        f"home: {found['home']}",
    ]
    if found["project"] is not None:
        lines.append(f"project: {found['project']}")
    for check in found["checks"]:
        lines.append("")
        lines.append(f"{check['name']}: {check['severity']}")
        lines.extend(f"  {one['severity']}: {one['detail']}" for one in check["findings"])
    if found["not_run"]:
        lines.append("")
        lines.append(f"not run: {', '.join(found['not_run'])}")
    lines.append("")
    lines.append(f"summary: {found['summary']}")
    return lines
