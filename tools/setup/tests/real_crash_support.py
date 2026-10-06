"""Shared by ``test_real_crash``: scratch worlds in which the real commands
are started as child processes, stopped after their N-th change to the disk,
and then carried on with.

The stop is ``fsio``'s own ("For the crash tests only" in that module): a
child started with ``fsio.STOP_VARIABLE`` set to N ends itself with
``fsio.STOP_EXIT_CODE`` right after its N-th change. Nothing else of the
tool is patched or stood in for: a child is

    [sys.executable, "-B", <clone>/tools/setup/workflow_setup.py, <command>, "--home", <scratch home>]

with ``PATH`` an empty directory, ``HOME`` (and ``USERPROFILE``) the scratch
home, standard input closed and a time limit.

The clone is the fixture clone of ``test_uninstall.UninstallCase`` with the
tool copied into it (``ScratchCase.install_tool``), the list of settings
keys beside it, and a ``v1-known-hashes.json`` made from the fixture texts
of ``test_migrate.V1``: the committed table lists versions of files that
are in the history only, so a child that reads it could be given no v1
copy without git. The code a child runs is the package's own, byte for
byte; it is compiled once into that scratch clone, because a child (started
with ``-B``) writes no bytecode and would compile the package every time.

A world is one directory that holds ``home`` and ``project``. ``build``
fills it with what a user had before setup ever ran; ``Worlds`` gives every
worker thread a world of its own, with a template of the state a scenario
starts from, so that the points of a scenario run side by side.
"""
from __future__ import annotations

import compileall
import json
import os
import queue
import shutil
import stat
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import support
from fileops_support import POSIX, SYMLINKS
from test_entry import USER_JSON, USER_TOML
from test_migrate import BUILDER, EDITED, OTHER_BLOCK, V1, v1
from test_uninstall import CONFIG_PLAIN, USER_SETTINGS, picture
from wfsetup import fsio, migrate

WINDOWS = os.name == "nt"
FULL = os.environ.get("WFSETUP_TEST_FULL", "") == "1"
# Where one JSON line per scenario (its counts and its failures) is added,
# when this is set: for whoever wants the numbers of a run.
REPORT = os.environ.get("WFSETUP_TEST_REPORT", "")
WORKERS = max(2, min(12, os.cpu_count() or 2))
TIMEOUT = 180.0

SAME, UNINSTALL, OTHER = "same command", "uninstall", "another command"
CONTINUATIONS = (SAME, UNINSTALL, OTHER)

STATE = ".agents/workflow-setup"

# No final line ending, and the two v1 import lines.
CLAUDE_MD = (
    b"# My instructions\n\nBe direct.\n\n@rules/prd-implementation.md\n@rules/epic-implementation.md\n\n"
    b"## Tone\n\n- Short answers."
)
AGENTS_MD = ("# Mine\n\nBe brief.\n\n" + OTHER_BLOCK).encode("utf-8")
IGNORE = b"node_modules/\n*.log"


# --- The scenarios ---------------------------------------------------------------

H, P = "{H}", "{P}"
STALE = ("--remove-stale", H + "/.claude/skills/json-tools")
INIT_USER = ("init", "--yes", "--user")
INIT_PROJECT = ("init", "--yes", "--project", P, "--manager-default")
MIGRATE = ("render", "--migrate-v1", *STALE)
CODEX = ("--apply-codex-settings", "--worktree-root", "~/wt")
FULL_INSTALL = (INIT_USER, MIGRATE, INIT_PROJECT, ("render", "--project", P, *CODEX))


@dataclass(frozen=True)
class Scenario:
    """One command to be stopped at every point.

    ``prepare`` is run to completion first, and what it leaves is the tree
    the scenario starts from. ``other`` is the different writing command
    of the third continuation. ``l1`` gives the home the v1 copies of the
    machine the migration was written for, ``settings`` a hand-written
    user settings file, ``follow`` a skills directory that is a link to a
    directory inside the same home (and ``--follow-config-symlinks`` on the
    way back)."""

    number: str
    name: str
    command: tuple[str, ...]
    other: tuple[str, ...]
    prepare: tuple[tuple[str, ...], ...] = ()
    l1: bool = False
    settings: bool = False
    follow: bool = False

    def way_back(self) -> tuple[tuple[str, ...], ...]:
        more = ("--follow-config-symlinks",) if self.follow else ()
        return (("uninstall", "--project", P, *more), ("uninstall", *more))


SCENARIOS = {one.name: one for one in (
    Scenario("1", "init-user", INIT_USER, other=("render",)),
    Scenario("2", "init-project", INIT_PROJECT, other=("render", "--project", P)),
    Scenario("2", "init-rewrite", (*INIT_USER, "--rewrite-settings", "--max-parallel-coders", "2"),
             other=("render",), settings=True),
    Scenario("3", "render", ("render",), other=INIT_USER),
    Scenario("4", "migrate", MIGRATE, other=INIT_PROJECT, prepare=(INIT_USER,), l1=True),
    Scenario("5", "migrate-follow", ("render", "--migrate-v1", "--follow-config-symlinks", *STALE),
             other=(*INIT_USER, "--follow-config-symlinks"), l1=True, follow=True),
    Scenario("6", "render-project", ("render", "--project", P), other=INIT_USER, prepare=(INIT_PROJECT,)),
    Scenario("7", "codex-settings", ("render", *CODEX), other=INIT_USER, prepare=(("render",),)),
    Scenario("8", "uninstall-project", ("uninstall", "--project", P), other=("render", "--project", P),
             prepare=FULL_INSTALL, l1=True),
    Scenario("9", "uninstall", ("uninstall",), other=MIGRATE, prepare=FULL_INSTALL, l1=True),
)}
# What a run under the Windows Python samples, unless it is a full one.
WINDOWS_SAMPLE = ("init-user", "render", "render-project", "uninstall")


def points_of(total: int, continuation: str, scenario: Scenario) -> list[int]:
    """The points of a command with ``total`` changes that a run stops at
    for ``continuation``; see the module text of ``test_real_crash``."""
    every = list(range(1, total + 1))
    if FULL:
        return every
    if WINDOWS:
        if scenario.name not in WINDOWS_SAMPLE:
            return []
        return sorted({*range(1, total + 1, 7), total} if total else set())
    if continuation == SAME:
        return [n for n in every if n % 2 == 1 or n > total - 2]
    return [n for n in every if n <= 2 or n > total - 2 or n % 15 == 0]


# --- Building --------------------------------------------------------------------

def put(path: Path, data: bytes | str, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    if mode is not None and POSIX:
        os.chmod(path, mode)
    return path


def link(target: Path | str, path: Path) -> None:
    """A link to a directory: a symlink, or a junction where a home has
    those."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        fsio.make_link(str(target), path, True)
    else:
        os.symlink(str(target), path)


def copy_of(directory: Path, skill: str, version: int = -1) -> Path:
    """A copy of a v1 skill, every file a committed version."""
    for path in V1:
        if path.startswith(skill + "/"):
            put(directory / path[len(skill) + 1:], v1(path, version if path.endswith("SKILL.md") else -1))
    return directory


def build(world: Path, clone: Path, scenario: Scenario) -> None:
    """What the user had before setup ever ran: a home with both
    providers' homes in it, and a project."""
    home, project = world / "home", world / "project"
    claude, codex = home / ".claude", home / ".codex"
    put(claude / "CLAUDE.md", CLAUDE_MD, 0o640)
    put(claude / "settings.json", b'{\n  "theme": "dark"\n}\n')
    put(claude / "commands" / "note.md", "A command of the user's.\n")
    put(codex / "AGENTS.md", AGENTS_MD, 0o444)
    put(codex / "config.toml", CONFIG_PLAIN, 0o600)
    put(codex / "skills" / ".system" / "note", "Codex's own.\n")
    skills = claude / "skills"
    if scenario.follow:
        real = home / "dotfiles" / "skills"
        real.mkdir(parents=True)
        os.symlink(str(real), skills, target_is_directory=True)
    else:
        real = skills
    put(real / "mine" / "SKILL.md", "---\nname: mine\n---\n\nA skill of the user's.\n")
    # The collaboration skill's link, made by its own setup.
    link(clone / "multiagent-collab", real / "multiagent-collab")
    if scenario.l1:
        rules = claude / "rules"
        put(rules / "prd-implementation.md", v1("prd-implementation.md", 0))
        put(rules / "epic-implementation.md", v1("epic-implementation.md"))
        put(rules / migrate.BASH_RULE, v1(migrate.BASH_RULE_NOW))
        put(rules / "my-own-rule.md", "Mine.\n", 0o600)
        put(claude / "agents" / "sprint-coder.md", v1(migrate.V1_AGENT_SOURCE))
        put(claude / "agents" / "mine.md", "---\nname: mine\n---\n\nAn agent of the user's.\n")
        # A v1 copy, every file a committed version.
        whole = copy_of(real / "usage-cost", "usage-cost")
        if POSIX:
            os.chmod(whole, 0o750)
            os.chmod(whole / "scripts", 0o700)
        # A v1 copy edited by hand, with files of the user's own in it:
        # what --remove-stale names.
        edited = copy_of(real / "json-tools", "json-tools")
        put(edited / "SKILL.md", EDITED, 0o600)
        put(edited / "notes" / "deep" / "mine.md", "What I changed, and why.\n")
        put(edited / "notes" / "todo", b"no line ending", 0o640)
        # A link of the user's to another copy, in the same home.
        link(copy_of(home / "old" / "self-reflection", "self-reflection", 0), real / "self-reflection")
        # The Codex home's own v1 copy, in the directory Codex read then.
        copy_of(codex / "skills" / "self-reflection", "self-reflection")
    if scenario.settings:
        put(home / ".agents" / "workflow.toml", USER_SETTINGS, 0o600)
    put(project / ".gitignore", IGNORE)
    put(project / ".claude" / "settings.json", USER_JSON)
    put(project / ".codex" / "config.toml", USER_TOML, 0o640)
    put(project / "src" / "main.py", "print('the project')\n")
    put(project / "run.sh", "#!/bin/sh\nexit 0\n", 0o755)


def install(case: support.ScratchCase) -> Path:
    """Make ``case``'s fixture clone one the tool runs from, and return the
    script: the package, the list of settings keys, and the fixture's own
    table of v1 hashes."""
    script = case.install_tool()
    shutil.copyfile(support.SETUP / "manifest-keys.json", script.parent / "manifest-keys.json")
    files = {
        path: sorted({digest for text in versions for digest in BUILDER.forms(text.encode("utf-8"))})
        for path, versions in V1.items()
    }
    table = {"schema_version": migrate.KNOWN_SCHEMA, "about": "The fixture texts of test_migrate.V1.", "files": files}
    (script.parent / migrate.KNOWN_FILE.name).write_bytes(BUILDER.to_bytes(table))
    # Compiled once, here: a child is started with -B and writes no bytecode,
    # so each of the thousands of them would compile the whole package again.
    compileall.compile_dir(str(script.parent / "wfsetup"), quiet=2)
    return script


# --- Copying a tree, links as links ------------------------------------------------

def copy_tree(source: Path, target: Path) -> None:
    """``source`` again at ``target``: a link (a junction too) as a link
    with the same text, a file with its bytes, and on POSIX the permission
    bits of both files and directories."""
    os.mkdir(target)
    for name in os.listdir(source):
        here, there = source / name, target / name
        seen = fsio.look(here)
        if seen.kind == fsio.LINK:
            if seen.junction:
                fsio.make_link(seen.target or "", there, True)
            else:
                os.symlink(os.readlink(here), there, target_is_directory=bool(seen.directory))
        elif seen.kind == fsio.DIRECTORY:
            copy_tree(here, there)
        else:
            shutil.copyfile(here, there)
            if POSIX:
                os.chmod(there, stat.S_IMODE(os.lstat(here).st_mode))
    if POSIX:
        os.chmod(target, stat.S_IMODE(os.lstat(source).st_mode))


def remove_tree(root: Path) -> None:
    """Remove ``root`` whatever the permission bits in it; a link in it is
    removed and not entered."""
    def again(function, path, _):
        os.chmod(os.path.dirname(path), 0o700)
        if not os.path.islink(path):
            os.chmod(path, 0o700)
        function(path)

    if not os.path.lexists(root):
        return
    if POSIX:
        for directory, names, _ in os.walk(root):
            os.chmod(directory, 0o700)
    if sys.version_info >= (3, 12):
        shutil.rmtree(root, onexc=again)
    else:
        shutil.rmtree(root, onerror=again)


def difference(before: dict, after: dict, limit: int = 30) -> list[str]:
    """The paths at which two pictures differ, one line each."""
    def short(what):
        if what is None:
            return "nothing"
        if what[0] == "file":
            data = what[1]
            return f"file {len(data)} bytes {fsio.sha256(data)[:12]} {data[:60]!r} mode {what[2] if what[2] is None else oct(what[2])}"
        if what[0] == "directory":
            return f"directory mode {what[1] if what[1] is None else oct(what[1])}"
        return " ".join(str(part) for part in what)

    lines = [
        f"{path}: {short(before.get(path))} -> {short(after.get(path))}"
        for path in sorted(set(before) | set(after)) if before.get(path) != after.get(path)
    ]
    return lines[:limit] + ([f"... and {len(lines) - limit} more"] if len(lines) > limit else [])


def named(said: object, key: str) -> list[str]:
    """Every text a piece of a record holds under ``key``, at any depth."""
    if isinstance(said, dict):
        own = [said[key]] if isinstance(said.get(key), str) else []
        return own + [found for value in said.values() for found in named(value, key)]
    if isinstance(said, list):
        return [found for value in said for found in named(value, key)]
    return []


def targets(said: object) -> list[str]:
    """Every ``target`` a piece of a record holds, at any depth."""
    return named(said, "target")


def without_state(found: dict) -> dict:
    """A picture without setup's own state: its record, its backups and
    its lock differ from run to run (a stamp, a token)."""
    return {path: what for path, what in found.items() if STATE not in path}


# --- Running ---------------------------------------------------------------------

@dataclass
class Ran:
    argv: list[str]
    code: int | None   # None: it did not end in time
    out: str
    err: str
    stop: int | None = None

    @property
    def traceback(self) -> bool:
        return "Traceback" in self.out or "Traceback" in self.err

    def said(self, limit: int = 1500) -> str:
        head = f"$ {' '.join(self.argv)}" + (f"   [stopped after change {self.stop}]" if self.stop else "")
        return "\n".join([head, f"exit code {self.code}", "stdout: " + self.out[-limit:], "stderr: " + self.err[-limit:]])


class HarnessError(Exception):
    """A world could not be brought to where a scenario starts."""


class World:
    """One worker's world for one scenario, and what is known of it."""

    def __init__(self, root: Path, script: Path, clone: Path, scenario: Scenario, empty: Path) -> None:
        self.root, self.script, self.clone, self.scenario, self.empty = root, script, clone, scenario, empty
        self.world, self.template = root / "world", root / "template"
        self.home, self.project = self.world / "home", self.world / "project"
        self.pristine: dict = {}    # before setup ever ran
        self.start: dict = {}       # after the scenario's preparation
        self.completed: dict = {}   # after the command, not stopped
        self.completed_code: int | None = None

    def expand(self, argv: tuple[str, ...]) -> list[str]:
        return [part.replace(H, str(self.home)).replace(P, str(self.project)) for part in argv]

    def run(self, argv: tuple[str, ...], stop: int | str | None = None) -> Ran:
        """One command as a process of its own, with the scratch home."""
        argv = [*self.expand(argv), "--home", str(self.home)]
        environment = {
            key: value for key, value in support.child_environment().items()
            if key not in (fsio.STOP_VARIABLE, "CLAUDE_CONFIG_DIR", "CODEX_HOME")
        }
        environment.update(PATH=str(self.empty), HOME=str(self.home))
        if WINDOWS:
            environment["USERPROFILE"] = str(self.home)
        if stop is not None:
            environment[fsio.STOP_VARIABLE] = str(stop)
        try:
            done = subprocess.run(
                [sys.executable, "-B", str(self.script), *argv], env=environment, cwd=str(self.root),
                stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired as late:
            return Ran(argv, None, (late.stdout or b"").decode("utf-8", "replace"),
                       (late.stderr or b"").decode("utf-8", "replace"), stop if isinstance(stop, int) else None)
        return Ran(argv, done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace"),
                   stop if isinstance(stop, int) else None)

    def restore(self) -> None:
        remove_tree(self.world)
        copy_tree(self.template, self.world)

    def picture(self) -> dict:
        return picture(self.world)

    def make(self) -> "World":
        """Build the world, prepare it, keep the template, and learn what
        the command leaves when nothing stops it."""
        self.root.mkdir(parents=True)
        self.world.mkdir()
        build(self.world, self.clone, self.scenario)
        self.pristine = self.picture()
        for argv in self.scenario.prepare:
            ran = self.run(argv)
            if ran.code != 0 or ran.traceback:
                raise HarnessError(f"{self.scenario.name}: the preparation did not end with 0\n{ran.said()}")
        self.start = self.picture()
        copy_tree(self.world, self.template)
        ran = self.run(self.scenario.command)
        if ran.code != 0 or ran.traceback:
            raise HarnessError(f"{self.scenario.name}: the command, not stopped, did not end with 0\n{ran.said()}")
        self.completed_code = ran.code
        self.completed = self.picture()
        return self

    def stops_at(self, n: int) -> bool:
        self.restore()
        return self.run(self.scenario.command, stop=n).code == fsio.STOP_EXIT_CODE

    # --- What a record lists -----------------------------------------------------

    def listed_backups(self) -> list[bytes]:
        """The bytes of every backup of a file that a record of this world
        names and that is on disk. Named anywhere in the record: while a
        run is under way a backup is in its pending change (and in the
        entry's ``original``), and in ``backups`` once the record is
        closed."""
        found: list[bytes] = []
        for root, anchor in ((self.home, "home"), (self.project, "project")):
            file = root / ".agents" / "workflow-setup" / "manifest.json"
            try:
                record = json.loads(file.read_bytes().decode("utf-8"))
            except (OSError, ValueError):
                continue
            for where in sorted(set(named(record, "backup"))):
                if not where.startswith(f"{anchor}:{STATE}/backups/"):
                    continue
                try:
                    found.append((root / where[len(anchor) + 1:]).read_bytes())
                except OSError:
                    continue
        return found

    # --- One point ---------------------------------------------------------------

    def point(self, n: int, continuation: str) -> "Failure | None":
        """Stop the command after its ``n``-th change, carry on with
        ``continuation``, go the whole way back, and say what is wrong."""
        scenario = self.scenario
        wrong: list[str] = []
        log: list[Ran] = []
        self.restore()
        killed = self.run(scenario.command, stop=n)
        log.append(killed)
        if killed.code != fsio.STOP_EXIT_CODE:
            return Failure(scenario.name, n, continuation, [f"the command was not stopped: exit code {killed.code}"], log)
        if killed.traceback:
            wrong.append("the stopped command printed a traceback")
        after = self.picture()
        wrong.extend(self.lost(after))

        if continuation == SAME:
            then = (scenario.command,)
        elif continuation == UNINSTALL:
            then = scenario.way_back()
        else:
            then = (scenario.other,)
        for argv in (*then, None, *scenario.way_back()):
            if argv is None:
                if continuation == SAME:
                    left = difference(without_state(self.completed), without_state(self.picture()))
                    if left:
                        wrong.append("the same command, run again, does not leave what it leaves when nothing "
                                     "stops it:\n    " + "\n    ".join(left))
                continue
            ran = self.run(argv)
            log.append(ran)
            if ran.traceback:
                wrong.append(f"{ran.argv[0]} printed a traceback")
            if ran.code != 0:
                wrong.append(f"{' '.join(ran.argv[:3])} ended with {ran.code}")
        final = self.picture()
        changed = difference(self.pristine, final)
        if changed:
            wrong.append("the tree at the end is not the tree before setup ever ran:\n    " + "\n    ".join(changed))
        for path in final:
            name = path.rsplit("/", 1)[-1]
            if name.startswith(fsio.TEMP_PREFIX):
                wrong.append(f"a temporary name is left: {path}")
            if path.endswith(STATE):
                wrong.append(f"a state directory is left: {path}")
        return Failure(scenario.name, n, continuation, wrong, log) if wrong else None

    def recorded(self) -> dict[str, list]:
        """Everything the records of this world say of a path (its entry,
        its pending change, its backups), by the path as a picture names
        it. A path is placed by the real directory it is in: with a linked
        skills directory a record names what a picture finds elsewhere."""
        found: dict[str, list] = {}
        for root, anchor in ((self.home, "home"), (self.project, "project")):
            try:
                record = json.loads((root / ".agents" / "workflow-setup" / "manifest.json").read_bytes().decode("utf-8"))
            except (OSError, ValueError):
                continue
            said = [
                *(record.get("entries") or {}).items(),
                *((item.get("path"), item) for item in [*(record.get("pending") or []), *(record.get("backups") or [])]),
            ]
            for key, what in said:
                if not isinstance(key, str) or not key.startswith(anchor + ":"):
                    continue
                path = root / key[len(anchor) + 1:]
                try:
                    real = Path(os.path.realpath(path.parent)) / path.name
                    found.setdefault(real.relative_to(self.world).as_posix(), []).append(what)
                except (OSError, ValueError):
                    continue
        return found

    def target_text(self, target: str) -> str:
        """A link's target as a record stores it, as the link's own text."""
        anchor, _, rest = target.partition(":")
        if anchor == "raw":
            return rest
        root = {"home": self.home, "project": self.project, "clone": self.clone}.get(anchor)
        return target if root is None else str(root / rest)

    def lost(self, after: dict) -> list[str]:
        """What a stopped run did to the user's tree that it may not. A
        path of the tree before setup ever ran must be as the scenario
        started with it, or as the completed command leaves it, or

        - a file: have its bytes in a backup a record lists;
        - a link or a directory that setup replaces by a link (or puts back
          in place of one), and that is at this moment not there: be named
          by a record, a link with its text, so that the next run puts it
          back. What a directory held is files, held by the lines above.
        """
        wrong: list[str] = []
        backups: list[bytes] | None = None
        recorded: dict[str, list] | None = None
        for path, was in self.pristine.items():
            now = after.get(path)
            if was[0] == "file" and (now is None or now[0] != "file" or now[1] != was[1]):
                # Stricter than the three cases below: wherever the bytes
                # the user had are not in the file now (setup edited it, or
                # removed it, in this run or in the preparation), a record
                # lists a backup that holds them.
                if backups is None:
                    backups = self.listed_backups()
                if was[1] not in backups:
                    wrong.append(f"right after the stop, the bytes a file of the user's had are neither in the "
                                 f"file nor in a backup a record lists: {path}")
                    continue
            if now == self.start.get(path) or now == self.completed.get(path):
                continue
            if was[0] == "file":
                if was[1] in (backups or ()):
                    continue
            elif now is None:
                if recorded is None:
                    recorded = self.recorded()
                said = recorded.get(path, [])
                if was[0] == "directory" and said:
                    continue
                if was[0] == "link" and any(
                    os.path.normcase(self.target_text(target)) == os.path.normcase(was[1]) for target in targets(said)
                ):
                    continue
            line = difference({path: self.start.get(path)}, {path: now})[0]
            wrong.append(f"right after the stop, a path of the user's is neither as it was, nor as the command "
                         f"leaves it, nor kept by a record (a file: in a backup it lists): {line}")
        return wrong


@dataclass
class Failure:
    scenario: str
    n: int
    continuation: str
    wrong: list[str]
    log: list[Ran] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join([
            f"--- {self.scenario}, stopped after change {self.n}, then {self.continuation} ---",
            *(f"  * {line}" for line in self.wrong), *(ran.said() for ran in self.log),
        ])

    def as_json(self) -> dict:
        return {
            "scenario": self.scenario, "n": self.n, "continuation": self.continuation, "wrong": self.wrong,
            "log": [{"argv": ran.argv, "code": ran.code, "stop": ran.stop, "out": ran.out[-3000:], "err": ran.err[-3000:]}
                    for ran in self.log],
        }


@dataclass
class Outcome:
    scenario: Scenario
    total: int = 0
    triples: dict[str, int] = field(default_factory=dict)
    failures: list[Failure] = field(default_factory=list)

    def summary(self) -> str:
        """Every failure in one line each, grouped, then the first few in
        full."""
        groups: dict[tuple[str, str], list[int]] = {}
        for failure in self.failures:
            for line in failure.wrong:
                groups.setdefault((failure.continuation, line.split("\n")[0][:160]), []).append(failure.n)
        lines = [f"{self.scenario.name}: {len(self.failures)} of {sum(self.triples.values())} runs failed "
                 f"({self.total} points; {self.triples})"]
        for (continuation, line), points in sorted(groups.items()):
            lines.append(f"  then {continuation}: {line}\n      at {sorted(set(points))}")
        return "\n".join([*lines, "", *(failure.text() for failure in self.failures[:3])])


def run_scenario(scenario: Scenario, root: Path, script: Path, clone: Path) -> Outcome:
    """Every point of ``scenario`` this run covers, in a pool of worker
    threads, each with a world of its own below ``root``."""
    empty = root / "no-programs"
    empty.mkdir(exist_ok=True)
    made = [0]
    guard = threading.Lock()
    free: "queue.SimpleQueue[World]" = queue.SimpleQueue()

    def new_world() -> World:
        with guard:
            made[0] += 1
            number = made[0]
        return World(root / f"{scenario.name}-{number}", script, clone, scenario, empty).make()

    def one(job: tuple[int, str]) -> Failure | None:
        try:
            world = free.get_nowait()
        except queue.Empty:
            world = new_world()
        try:
            return world.point(*job)
        except Exception as exc:  # noqa: BLE001  (a fault of the harness is a failure of the point, not a hang)
            return Failure(scenario.name, job[0], job[1], [f"the harness failed: {exc!r}"])
        finally:
            free.put(world)

    def stops(n: int) -> bool:
        try:
            world = free.get_nowait()
        except queue.Empty:
            world = new_world()
        try:
            return world.stops_at(n)
        finally:
            free.put(world)

    outcome = Outcome(scenario)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        # How many changes the command makes: the largest N at which a run
        # still stops. Narrowed a few N at a time; every N up to it is then
        # run by the points themselves, and N + 1 just below.
        low, high = 0, None   # the largest N known to stop, the smallest known not to
        while high is None:
            tried = [low + 2 ** power for power in range(WORKERS)]
            for n, did in zip(tried, list(pool.map(stops, tried))):
                if not did:
                    high = n
                    break
                low = n
        while high - low > 1:
            step = max(1, (high - low) // (WORKERS + 1))
            tried = list(range(low + step, high, step))[:WORKERS]
            for n, did in zip(tried, list(pool.map(stops, tried))):
                if not did:
                    high = n
                    break
                low = n
        outcome.total = total = low
        first = free.get()
        # One past the last point, the command completes as it does unstopped.
        first.restore()
        past = first.run(scenario.command, stop=total + 1)
        if past.code != first.completed_code or without_state(first.picture()) != without_state(first.completed):
            outcome.failures.append(Failure(scenario.name, total + 1, "nothing", [
                f"with the stop set one past the last change, the command ended with {past.code} or left another tree"
            ], [past]))
        free.put(first)
        jobs = [(n, continuation) for continuation in CONTINUATIONS for n in points_of(total, continuation, scenario)]
        for _, continuation in jobs:
            outcome.triples[continuation] = outcome.triples.get(continuation, 0) + 1
        outcome.failures.extend(found for found in pool.map(one, jobs) if found is not None)
    if REPORT:
        line = {"scenario": scenario.name, "points": total, "triples": outcome.triples,
                "failures": [failure.as_json() for failure in outcome.failures]}
        with guard, open(REPORT, "a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(line) + "\n")
    return outcome
