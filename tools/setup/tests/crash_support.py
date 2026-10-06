"""Shared by the crash, lock and record tests: a counter on every change
setup makes to the disk, scratch worlds whose runs can be repeated in a
child process, and a snapshot that takes a junction for the link it is.

Everything ``fileops``, ``manifest`` and ``lock`` change on disk is one call
of a function of ``os`` made in ``fsio`` (see ``fsio``: no other module of
the package changes the disk). ``Disk`` stands in for ``os`` in that module
and counts those calls; it can stop a run before, or after, the n-th of them:

    kill       the process is gone: this call and every later one raise,
               so no ``finally`` and no handler changes the disk any more.
    interrupt  one ``KeyboardInterrupt`` at that point; handlers and
               ``finally`` blocks run as they do after Ctrl-C.
    exit       ``os._exit``: for a child process, a kill that is one.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from unittest import mock

import support  # noqa: F401  (puts the package on the path)
from wfsetup import fileops, fsio, lock
from wfsetup.manifest import Roots

KILL, INTERRUPT, EXIT = "kill", "interrupt", "exit"
EXIT_CODE = 77  # of a child that was stopped by ``EXIT``

_CHANGES = ("mkdir", "rmdir", "unlink", "replace", "rename", "link", "symlink", "chmod")


class Killed(BaseException):
    """Stands in for the process being killed: nothing catches it."""


class Disk:
    """Counts the changes to the disk; see the module."""

    def __init__(self, stop_at: int | None = None, mode: str = KILL, after: bool = False) -> None:
        self.stop_at, self.mode, self.after = stop_at, mode, after
        self.count = 0
        self.fired = False
        self.dead = False
        self.calls: list[str] = []
        self._patches: list[Any] = []

    # --- The stand-in for ``os`` -------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        real = getattr(os, name)
        if name in _CHANGES:
            return lambda *args, **options: self._change(name, real, args, options)
        if name == "open":
            return self._open
        if name == "fsync":
            return lambda handle: None  # a test does not wait for the disk
        return real

    def _open(self, path: Any, flags: int, *args: Any, **options: Any) -> int:
        if flags & os.O_CREAT:
            return self._change("create", os.open, (path, flags, *args), options)
        return os.open(path, flags, *args, **options)

    def _junction(self, target: str, link: Path, use_mklink: bool = False) -> None:
        self._change("junction", _REAL_JUNCTION, (target, link, use_mklink), {})

    def _change(self, name: str, real: Callable[..., Any], args: tuple, options: dict) -> Any:
        if self.dead:
            raise Killed()
        self.count += 1
        self.calls.append(f"{name} {args[-1] if name in ('replace', 'rename', 'link', 'symlink') else args[0]}")
        mine = self.count == self.stop_at
        if mine and not self.after:
            self._stop()
        result = None
        try:
            result = real(*args, **options)
        finally:
            if mine and self.after:
                if name == "create" and isinstance(result, int):
                    os.close(result)  # a process that is stopped holds no file open
                self._stop()  # stopped there whether the system made the change or refused it
        return result

    def _stop(self) -> None:
        self.fired = True
        if self.mode == EXIT:
            os._exit(EXIT_CODE)
        if self.mode == INTERRUPT:
            raise KeyboardInterrupt()
        self.dead = True
        raise Killed()

    def __enter__(self) -> "Disk":
        self._patches = [
            mock.patch.object(fsio, "os", self),
            mock.patch.object(fsio, "_create_junction", self._junction),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        # What a killed run held in this process is gone with it.
        lock._HELD.clear()


_REAL_JUNCTION = fsio._create_junction


def stopped(run: Callable[[], Any], disk: Disk) -> bool:
    """Run under ``disk``; True when the run was stopped by it."""
    with disk:
        try:
            run()
        except (Killed, KeyboardInterrupt):
            return True
    return False


# --- A process that is gone -------------------------------------------------------

_GONE: list[int] = []


def gone_pid() -> int:
    """The id of a process that has ended: a child that was waited for."""
    if not _GONE:
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        _GONE.append(child.pid)
    return _GONE[0]


def orphan(roots: Roots) -> None:
    """Make every lock this process left under ``roots`` the lock of a
    process that is gone: what the kill of a real process leaves. In both
    state directories, the home's and the project's: the lock, a piece of
    one under a temporary name, a claim on a stale one. The start recorded
    is one no process has, so an id given out again is seen too."""
    for project in roots.scopes():
        state = roots.state_dir_of(project)
        if fsio.look(state).kind != fsio.DIRECTORY:
            continue
        claims = [state / name for name in sorted(os.listdir(state)) if name.startswith(lock.CLAIM_PREFIX)]
        for path in [state / lock.LOCK_NAME, *fsio.temporaries(state), *claims]:
            if fsio.look(path).kind != fsio.FILE:
                continue
            raw, said = lock.read(path)
            if said is None or said.get("pid") != os.getpid():
                continue
            said["pid"], said["start"] = gone_pid(), "0"
            path.write_bytes((json.dumps(said) + "\n").encode("utf-8"))


# --- A tree ---------------------------------------------------------------------

def tree(root: Path, skip: tuple[Path, ...] = ()) -> dict[str, tuple]:
    """Every path below ``root``: a link (a junction too) with its text, a
    directory with its permission bits, a file with its bytes and bits."""
    found: dict[str, tuple] = {}
    stack = [root]
    while stack:
        directory = stack.pop()
        for name in sorted(os.listdir(directory)):
            path = directory / name
            if any(path == other for other in skip):
                continue
            relative = path.relative_to(root).as_posix()
            seen = fsio.look(path)
            if seen.kind == fsio.LINK:
                found[relative] = ("link", seen.target)
            elif seen.kind == fsio.DIRECTORY:
                found[relative] = ("directory", stat.S_IMODE(os.lstat(path).st_mode))
                stack.append(path)
            else:
                found[relative] = ("file", path.read_bytes(), seen.mode)
    return found


def differences(one: dict[str, tuple], other: dict[str, tuple]) -> list[str]:
    """The paths that differ between two trees, for a failure message."""
    lines = []
    for name in sorted(set(one) | set(other)):
        if one.get(name) != other.get(name):
            was, now = one.get(name), other.get(name)
            lines.append(f"{name}: {None if was is None else was[0]} -> {None if now is None else now[0]}")
    return lines


def clear(path: Path) -> None:
    """Remove a scratch tree, links and read-only files included."""
    seen = fsio.look(path)
    if seen.kind == fsio.ABSENT:
        return
    if seen.kind == fsio.LINK:
        fsio.remove_link(path)
        return
    if seen.kind != fsio.DIRECTORY:
        os.chmod(path, 0o600)
        os.unlink(path)
        return
    os.chmod(path, 0o700)
    for name in os.listdir(path):
        clear(path / name)
    os.rmdir(path)


# --- Worlds -----------------------------------------------------------------------

class World:
    """A scratch home, project and clone below ``root``, the files a user
    has in them, and the runs of the scenarios. The same code builds the
    same world in a test and in a child process."""

    CLAUDE_MD = b"# Mine\r\n@rules/prd-implementation.md\r\nkeep this\r\n"
    AGENTS_MD = b"<!-- other-tool:start -->\nnot setup's\n<!-- other-tool:end -->\nno final newline"
    CONFIG_TOML = b'model = "x"\nnotes = """\n# workflow-setup:start codex-settings\n"""\n\n[agents]\nmax_threads = 2\n'
    SETTINGS = b'{\n    "permissions": {"allow": ["a", "b"]},\n    "theme": "dark"\n}'
    IGNORE = b"node_modules/\n*.log"

    def __init__(self, root: Path, prefix: str = "T") -> None:
        self.root = Path(root)
        self.home, self.project, self.clone = self.root / "home", self.root / "project", self.root / "clone"
        self.roots = Roots(self.home, self.project, self.clone)
        self.prefix, self.runs = prefix, 0

    def stamp(self) -> str:
        self.runs += 1
        return f"20260101T{self.prefix}{self.runs:05d}Z"

    def plan(self, **options: Any) -> fileops.Plan:
        return fileops.Plan(self.roots, stamp=self.stamp(), **options)

    def put(self, path: Path, data: bytes | str, mode: int | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        if mode is not None and os.name == "posix":
            os.chmod(path, mode)
        return path

    def reset(self) -> None:
        """Everything below the root gone, and the user's files there."""
        self.root.mkdir(parents=True, exist_ok=True)
        for name in os.listdir(self.root):
            clear(self.root / name)
        for directory in (self.home, self.project, self.clone / "json-tools", self.clone / "csv-tools",
                          self.clone / "old-skill", self.home / "elsewhere"):
            directory.mkdir(parents=True)
        self.put(self.clone / "json-tools" / "SKILL.md", "the clone's own\n")
        claude, codex = self.home / ".claude", self.home / ".codex"
        self.put(claude / "CLAUDE.md", self.CLAUDE_MD, 0o640)
        self.put(codex / "AGENTS.md", self.AGENTS_MD, 0o444)
        self.put(codex / "config.toml", self.CONFIG_TOML, 0o600)
        self.put(claude / "rules" / "prd-implementation.md", "v1 rule\n")
        # A copy of a v1 skill, with files of the user's own in it.
        skill = claude / "skills" / "json-tools"
        self.put(skill / "SKILL.md", "the user's copy, edited\n", 0o600)
        self.put(skill / "scripts" / "run.py", "print(1)\n", 0o755)
        self.put(skill / "notes" / "deep" / "mine.md", "IRREPLACEABLE NOTES\n")
        if os.name == "posix":
            os.chmod(skill, 0o750)
        # A link of the user's where setup will put its own.
        fsio.make_link(str(self.clone / "old-skill"), claude / "skills" / "csv-tools", True)
        fsio.make_link(str(self.home / "elsewhere"), claude / "skills" / "users-own", True)
        self.put(self.project / ".claude" / "settings.json", self.SETTINGS)
        self.put(self.project / ".gitignore", self.IGNORE)
        self.put(self.project / "src" / "main.py", "print(1)\n")

    # --- The runs ---------------------------------------------------------------

    def render(self) -> fileops.Plan:
        """A plain render of the home: directories, generated files, links,
        blocks in the user's files."""
        home, plan = self.home, self.plan()
        plan.create_directory(home / ".claude" / "commands" / "deep")
        plan.write_file(home / ".claude" / "agents" / "coder.md", "generated\n", inputs="digest-1")
        plan.write_file(home / ".codex" / "agents" / "coder.toml", 'name = "coder"\n', inputs="digest-2")
        plan.write_file(home / ".agents" / "workflow.toml", "schema_version = 1\n", replace=fileops.ANY)
        plan.create_link(home / ".agents" / "skills" / "json-tools", self.clone / "json-tools")
        plan.edit_block(home / ".claude" / "CLAUDE.md", "Sprint work follows the two skills.\n")
        plan.edit_block(home / ".codex" / "AGENTS.md", "Sprint work follows the two skills.\n")
        plan.edit_block(home / ".codex" / "config.toml", "top = 1\n", name="codex-settings", place=fileops.HEAD)
        return plan

    def migrate(self) -> fileops.Plan:
        """A render that migrates v1: the user's copy of a skill, file by
        file, and then its directory, replaced by setup's link; the user's
        link replaced by setup's; a v1 rule file and its import line
        removed. Like the command, it plans from what is on disk now."""
        home, plan = self.home, self.render()
        skills = home / ".claude" / "skills"
        copy = skills / "json-tools"
        if fsio.look(copy).kind == fsio.DIRECTORY:
            below: list[Path] = []
            for directory, names, files in os.walk(copy):
                below.extend(Path(directory) / name for name in names)
                for name in files:
                    plan.remove_file(Path(directory) / name)
            for directory in sorted(below, key=lambda path: -len(path.parts)):
                plan.remove_directory(directory, users=True)
            plan.remove_directory(copy, users=True)
        plan.create_link(copy, self.clone / "json-tools")
        old = skills / "csv-tools"
        seen = fsio.look(old)
        if seen.kind == fsio.LINK and not fsio.same_target(seen.target or "", str(self.clone / "csv-tools")):
            plan.remove_link(old)
        plan.create_link(old, self.clone / "csv-tools")
        plan.remove_file(home / ".claude" / "rules" / "prd-implementation.md")
        plan.remove_lines(home / ".claude" / "CLAUDE.md", ["@rules/prd-implementation.md"])
        return plan

    def project_render(self) -> fileops.Plan:
        """A render for a project: the home's part, a key in the project's
        settings, generated files there, its ignore block."""
        plan = self.render()
        plan.edit_json(self.project / ".claude" / "settings.json", set={"agent": "manager"})
        plan.write_file(self.project / ".claude" / "agents" / "manager.md", "generated\n", inputs="digest-3")
        plan.edit_block(self.project / ".codex" / "config.toml", 'model = "m"\n', place=fileops.HEAD)
        plan.ignore(add=[".claude/agents/manager.md"])
        return plan

    def everything(self) -> fileops.Plan:
        """The migration and the project in one run."""
        plan = self.migrate()
        plan.edit_json(self.project / ".claude" / "settings.json", set={"agent": "manager"})
        plan.write_file(self.project / ".claude" / "agents" / "manager.md", "generated\n", inputs="digest-3")
        plan.ignore(add=[".claude/agents/manager.md"])
        return plan

    def uninstall(self) -> list[tuple[str, str]]:
        """The whole way back, as ``uninstall --project`` and then
        ``uninstall`` do it. Returns what was kept."""
        kept: list[tuple[str, str]] = []
        for project in (True, False):
            plan = fileops.plan_reversal(self.roots, project=project, stamp=self.stamp())
            kept += plan.apply().kept
            fileops.remove_state(self.roots, project=project)
        return kept

    def run(self, name: str) -> Any:
        """One run of the scenario ``name``, to its end."""
        if name == "uninstall":
            return self.uninstall()
        return getattr(self, name)().apply()


def child_main(argv: list[str]) -> int:
    """``crash_support.py ROOT SCENARIO STOP_AT [PREFIX]``: one run of a
    scenario in the world at ROOT, ended by ``os._exit`` before its
    STOP_AT-th change to the disk (0: not at all)."""
    root, name, stop_at = Path(argv[0]), argv[1], int(argv[2])
    world = World(root, argv[3] if len(argv) > 3 else "C")
    with Disk(stop_at or None, EXIT):
        world.run(name)
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.exit(child_main(sys.argv[1:]))
