"""One run that writes at a time: the lock of a state directory.

How ``fileops`` uses it

    with lock.held(roots) as mine:        # LockHeld when another run has it
        ...                                # read the record again, then write
        mine.created                       # the state directories to record
        mine.notes                         # what to tell the user
    with lock.held(roots, project=True):  # the same, for the project's state

Two runs that write to one place at the same moment would each save its own
copy of the record, and the later save would drop what the other had
listed. So every run that writes takes a lock first, for as long as it
writes. There is one lock for the user level of a home and one for each
project, each in the state directory it guards, beside the record and the
backups: a run that writes to a project takes the project's lock, and the
home's only if it writes to the home too. So a project that two homes use
(the two sides of one machine) is written by one run at a time whichever
home it runs from. A run that only reads (a dry run, ``doctor``, ``show``)
takes no lock: a record is replaced by one rename, so a reader sees the old
one or the new one, never a part.

The file
    ``<root>/.agents/workflow-setup/lock``, one line of JSON: the process id
    of the run, when that process started (as the system counts it), the
    system it runs on, the command, the time and a random token.

The place
    Before anything is made or read, the state directory's place is
    checked: neither ``.agents`` nor the state directory is a link (unless
    following links was asked for), and the real place of the lock file is
    inside the root it belongs to and outside the clone (``fsio.admit``).
    A state directory that leads elsewhere is refused in one line, and
    nothing is written through it.

Taking it
    The file is written under a temporary name and given its own name by a
    hard link, which the system refuses if the name is taken
    (``fsio.write_new``; the same as an exclusive create, with the content
    already in the file). There is no waiting: a run that finds the lock
    taken ends at once with one line that names the holder, and the exit
    code of every refusal, 2 (``errors.EXIT_ERROR``). It has changed
    nothing.

The directories
    The state directory is setup's own by its name. ``.agents`` above it is
    not: the user, a provider and setup all keep things there. Where
    ``.agents`` is missing, setup first makes an empty directory beside it,
    the marker ``.wfsetup-new.tmp``, then ``.agents``, then the state
    directory. The marker says "setup made the ``.agents`` beside me, and
    no record says so yet". It is removed once a record lists ``.agents``
    as created, or once ``.agents`` is gone again. A run that is killed in
    between leaves the marker, and the next run reads it: so a killed run
    never leaves a directory nobody answers for. The marker is trusted for
    one thing only, removing ``.agents`` when it is empty. Nothing else on
    disk is believed about who made a directory: a lock file does not say.

Giving it back
    The file is removed, if it still holds this run's bytes. Where no
    record is in the state directory, the directory answers for nothing:
    it is removed if it is empty, and ``.agents`` after it if the marker
    is there and nothing else is in it. A directory that holds anything
    stays.

A lock nobody gave back (the stale lock)
    A run that was killed leaves its lock. The next run clears it by itself
    only when the process that took it is PROVABLY not running, which needs
    all of this:

    - The lock was taken on this very system: the same platform and the
      same host name; on Linux also the same boot (``boot_id``) and the
      same process-id namespace. A project on a Windows drive that WSL
      also uses, a home on a network share, a container: a process id from
      over there says nothing here, so such a lock is never cleared from
      here.
    - And either no process has that id now, or the process that has it
      started at another moment than the one the lock recorded (the id was
      given out again).

    In every other case the lock stays and the run ends with a line that
    says why setup cannot tell and what to do: check that no setup is
    running on any system that uses this home or project, then remove the
    file it names. When in doubt the lock is not cleared.

    Clearing never removes or renames "whatever is at the lock's path" on
    the strength of an earlier look: between the look and the removal
    another run may have cleared the stale lock and taken its own, and that
    live lock would go. Instead:

    1. The run claims the right to clear: it creates, exclusively, the
       file ``lock.clear-<token of the stale lock>`` beside the lock,
       holding its own line. Only one run can create it.
    2. Only then it reads the lock again, and removes it only if it holds,
       byte for byte, the stale lock it judged. No other run may remove
       that lock (it would need the same claim), and no new lock can
       appear at the path while the stale one is there, so the file that
       is removed is the stale one.
    3. It removes its claim and tries to take the lock like any other run.

    A run that finds a claim it did not make ends with the one-line "held"
    error. If the run that made the claim was itself killed (provably
    gone, by the same test), its right passes on the same way: by an
    exclusive claim named after that run's token. A claim that is left
    over, on a lock that is no longer there, is removed by the next run
    that holds the lock, and only while it holds it.

    A lock path that holds something else (a directory, a FIFO, a link) or
    a lock file that cannot be read is an error of one line that names the
    file and says to remove it.

Within one process the lock is re-entrant: ``held`` inside ``held`` for the
same state directory is the same lock, given back by the outermost.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any, Iterator

from . import fsio, paths
from .errors import SetupError
from .manifest import MANIFEST_NAME

LOCK_NAME = "lock"
CLAIM_PREFIX = "lock.clear-"
# The marker beside ``.agents``; see "The directories". It reads like a
# temporary of setup's to an ignore file (``fsio.TEMP_PATTERN``) and is none
# to ``fsio.is_temporary``: nothing removes it by its looks.
MARKER_NAME = ".wfsetup-new.tmp"
SCHEMA_VERSION = 1

RUNNING = "running"
GONE = "gone"
UNKNOWN = "unknown"

# How often taking the lock starts over when another run changed the state
# directory under it (made it, removed it, cleared a stale lock first).
_TRIES = 8
# How many claims of runs that are gone one run follows; see the module.
_CHAIN = 4
_TOKEN = re.compile(r"[0-9a-f]{16}")

# The locks this process holds, by the folded path of the lock file.
_HELD: dict[str, "Lock"] = {}


class LockHeld(SetupError):
    """Another run holds the lock, or may: nothing was changed."""


# --- Who holds it ---------------------------------------------------------------

def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            return stream.read().strip() or None
    except (OSError, ValueError):
        return None


def identity() -> dict[str, Any]:
    """What a process id means on: the platform and the host, and on Linux
    the boot and the process-id namespace. A part that cannot be read is
    None, and a lock whose identity has such a part is never cleared."""
    try:
        host = socket.gethostname() or None
    except (OSError, ValueError):
        host = None
    found: dict[str, Any] = {"system": sys.platform, "host": host}
    if sys.platform.startswith("linux"):
        found["boot"] = _read_text("/proc/sys/kernel/random/boot_id")
        try:
            found["pidns"] = os.readlink("/proc/self/ns/pid") or None
        except (OSError, ValueError, AttributeError):
            found["pidns"] = None
    return found


def _windows_process(pid: int) -> tuple[bool | None, str | None]:
    """Whether a process has the id, and when it was created."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        query_limited_information, still_active = 0x1000, 259
        handle = kernel.OpenProcess(query_limited_information, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:      # ERROR_INVALID_PARAMETER: no process has this id
                return False, None
            if error == 5:       # ERROR_ACCESS_DENIED: one has, and is not ours to ask
                return True, None
            return None, None
        try:
            code = wintypes.DWORD()
            if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != still_active:
                return False, None   # ended; the id lives on only while a handle is open
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *[ctypes.byref(item) for item in times]):
                return True, None
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return True, str(created)
        finally:
            kernel.CloseHandle(handle)
    except (ImportError, AttributeError, OSError, ValueError):
        return None, None


def _posix_exists(pid: int) -> bool | None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, OverflowError):
        return None
    return True


def _linux_start(pid: int) -> str | None:
    """The start of process ``pid`` in clock ticks since the boot: field 22
    of ``/proc/<pid>/stat``. The name, field 2, may hold spaces and
    brackets, so the fields are counted from the last ``)``."""
    text = _read_text(f"/proc/{pid}/stat")
    if text is None or ")" not in text:
        return None
    fields = text.rsplit(")", 1)[1].split()
    return fields[19] if len(fields) > 19 and fields[19].isdigit() else None


def process(pid: int) -> tuple[bool | None, str | None]:
    """Whether a process has the id ``pid`` on this system (None when that
    cannot be told), and a token for the moment it started (None where the
    system gives none)."""
    if os.name == "nt":
        return _windows_process(pid)
    exists = _posix_exists(pid)
    start = _linux_start(pid) if exists and sys.platform.startswith("linux") else None
    return exists, start


def verdict(holder: dict[str, Any] | None) -> tuple[str, str]:
    """``RUNNING``, ``GONE`` or ``UNKNOWN`` for the run a lock names, and
    for ``UNKNOWN`` why it cannot be told. ``GONE`` is only said when it is
    proven; see the module."""
    if not isinstance(holder, dict):
        return UNKNOWN, "the lock file does not say who took it"
    theirs, mine = holder.get("identity"), identity()
    if not isinstance(theirs, dict):
        return UNKNOWN, "the lock file does not say on which system it was taken"
    names = ["system", "host", "boot", "pidns"]
    for name in [*names, *sorted((set(mine) | set(theirs)) - set(names))]:
        if name not in mine and name not in theirs:
            continue
        if mine.get(name) is None or theirs.get(name) is None:
            return UNKNOWN, f"this system or the lock does not say its {name}"
        if mine[name] != theirs[name]:
            if name == "boot":
                return UNKNOWN, "it was taken before this system was started, or on another system of the same name"
            return UNKNOWN, f"it was taken on another system ({name} {theirs[name]}, here {mine[name]})"
    pid = holder.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return UNKNOWN, "the lock file names no process"
    if pid == os.getpid():
        return RUNNING, ""
    exists, start = process(pid)
    if exists is None:
        return UNKNOWN, f"this system does not say whether process {pid} is running"
    if not exists:
        return GONE, ""
    recorded = holder.get("start")
    if isinstance(recorded, str) and start is not None and recorded != start:
        return GONE, ""  # the id was given to another process since
    return RUNNING, ""


# --- The lock -------------------------------------------------------------------

def lock_file(roots: Any, project: bool = False) -> Path:
    return roots.state_dir_of(project) / LOCK_NAME


def _token_of(holder: dict[str, Any] | None) -> str | None:
    token = holder.get("token") if isinstance(holder, dict) else None
    return token if isinstance(token, str) and _TOKEN.fullmatch(token) else None


def read(path: Path) -> tuple[bytes | None, dict[str, Any] | None]:
    """The bytes of a lock file (or of a claim on one) and what they say;
    (None, None) where nothing is there, and no dictionary where the bytes
    are not a lock's. What is there and cannot be read as a file is a
    ``SetupError`` of one line that names it and says what to do."""
    path = Path(path)
    for wait in (*fsio.REPLACE_WAITS, None):
        try:
            seen = fsio.look(path)
            if seen.kind == fsio.ABSENT:
                return None, None
            if seen.kind != fsio.FILE:
                what = {fsio.DIRECTORY: "a directory", fsio.LINK: f"a link (to {seen.target})"}.get(
                    seen.kind, "neither a file nor a directory (a FIFO, a socket or a device)"
                )
                raise SetupError(
                    f"{path}: is {what}, not a lock file of setup's; nothing was changed. Remove it and run again"
                )
            raw = path.read_bytes()
            break
        except (FileNotFoundError, NotADirectoryError):
            return None, None
        except PermissionError as exc:
            # On Windows a file that is being removed, or written, refuses
            # for a moment; a file that stays unreadable is said to be.
            if wait is None:
                raise SetupError(
                    f"{path}: the lock file cannot be read ({paths.reason(exc)}); nothing was changed. If no setup "
                    "is running, remove that file and run again"
                ) from None
            time.sleep(wait)
        except (OSError, ValueError) as exc:
            raise SetupError(
                f"{path}: the lock file cannot be read ({paths.reason(exc)}); nothing was changed. If no setup is "
                "running, remove that file and run again"
            ) from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return raw, None
    return raw, data if isinstance(data, dict) else None


def describe(holder: dict[str, Any] | None) -> str:
    """Who took a lock, for a message."""
    if not isinstance(holder, dict):
        return "a run the lock file does not name"
    theirs = holder.get("identity") if isinstance(holder.get("identity"), dict) else {}
    parts = [f"process {holder.get('pid')}"]
    if theirs.get("host"):
        parts.append(f"on {theirs['host']}")
    if isinstance(holder.get("time"), str):
        parts.append(f"since {holder['time']}")
    if isinstance(holder.get("command"), str) and holder["command"]:
        parts.append(f"running {holder['command']}")
    return " ".join(" ".join(str(part).split()) for part in parts)[:300]


_AGENTS = "agents"   # ``<root>/.agents``
_STATE = "state"     # ``<root>/.agents/workflow-setup``


class Lock:
    """The lock of one state directory, held. ``created`` names the state
    directories (``lock.AGENTS``, ``lock.STATE``) that no record lists yet
    and that are setup's to list, or to take away again; see the module.
    ``notes`` is what the user is told about a stale lock that was
    cleared."""

    def __init__(self, roots: Any, project: bool = False, follow: bool = False) -> None:
        self.roots = roots
        self.project = project
        self.follow = follow
        self.state = roots.state_dir_of(project)
        self.agents = self.state.parent
        self.marker = self.agents.parent / MARKER_NAME
        self.file = self.state / LOCK_NAME
        self.manifest = self.state / MANIFEST_NAME
        self.created: set[str] = set()
        self.notes: list[str] = []
        self.depth = 1
        self.taken = False
        self._made = False  # this process made a directory on the way to the lock
        self._made_agents = False  # and ``.agents`` among them
        self._given = False  # the lock is being given back: its file is, or is about to be, removed
        self._recorded = False  # a record was in the state directory at that moment
        self._token = os.urandom(8).hex()
        self._bytes = b""

    @property
    def whose(self) -> str:
        return "project" if self.project else "home"

    def directory(self, name: str) -> Path:
        return self.agents if name == _AGENTS else self.state

    def created_paths(self) -> list[Path]:
        return [self.directory(name) for name in (_AGENTS, _STATE) if name in self.created]

    def confined(self) -> Any:
        return fsio.confined(*self.roots.confinement(self.project))

    def _payload(self) -> bytes:
        if not self._bytes:
            _, start = process(os.getpid())
            command = " ".join(
                os.path.basename(part) if index == 0 else part for index, part in enumerate(sys.argv[:2])
            )
            data = {
                "schema_version": SCHEMA_VERSION,
                "pid": os.getpid(),
                "start": start,
                "identity": identity(),
                "command": command[:120],
                "time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "token": self._token,
            }
            self._bytes = (json.dumps(data, ensure_ascii=True) + "\n").encode("utf-8")
        return self._bytes

    # --- The place ----------------------------------------------------------------

    def check_place(self) -> None:
        """Before anything is made or read: the state directory is where
        setup may keep its state. Not under a link (unless following was
        asked for), not something else than a directory, and its real
        place inside this root and outside the clone (``fsio.admit``)."""
        for directory in (self.agents, self.state):
            seen = fsio.look(directory)
            if seen.kind == fsio.ABSENT:
                break
            if seen.kind == fsio.LINK and not self.follow:
                raise SetupError(
                    f"{directory}: is a link (to {seen.target}); setup keeps its state there and does not write "
                    "through a link unless --follow-config-symlinks is given"
                )
            # Judged by the one look: a directory that another run takes
            # away in this instant was a directory.
            if seen.kind not in (fsio.DIRECTORY, fsio.LINK) or (seen.kind == fsio.LINK and not seen.directory):
                raise SetupError(f"{directory}: is there and is not a directory; setup keeps its state there")
        refused = fsio.admits(self.file)
        if refused is not None:
            raise SetupError(refused)

    def _make_state(self) -> None:
        """Make the state directory where it is missing. ``.agents`` is a
        name setup shares with others, so before setup makes it, it says
        so with the marker beside it; see the module."""
        if os.path.isdir(self.state):
            return
        if not os.path.lexists(self.agents):
            self._mkdir(self.marker)
            if self._mkdir(self.agents):
                self._made_agents = True
        self._mkdir(self.state)

    def _mkdir(self, path: Path) -> bool:
        """Make one directory; True when this run made it, False when
        another run did in this instant."""
        self._made = True  # said before it is made: an interrupt may come in between
        try:
            fsio.make_directory(path)
            return True
        except SetupError:
            if fsio.look(path).kind != fsio.DIRECTORY:
                raise  # not made by another run in this instant: a real refusal
            return False

    def _mark_own(self) -> None:
        """This very process made ``.agents``: the marker says so, also
        where a run that was giving its lock back at that instant took the
        marker away for an ``.agents`` it had just removed."""
        if self._made_agents and fsio.look(self.agents).kind == fsio.DIRECTORY:
            try:
                self._mkdir(self.marker)
            except SetupError:
                pass

    def give_up(self) -> None:
        """The lock was not taken. What this run made on the way (the
        directories, empty) goes again, as when a lock is given back."""
        if not self._made or self.taken:
            return

        def vacate() -> None:
            with self.confined():
                if not os.path.lexists(self.manifest):
                    self._mark_own()
                    self._vacate()

        stopped: KeyboardInterrupt | None = None
        try:
            try:
                vacate()
            except KeyboardInterrupt as exc:
                stopped = exc
                vacate()
        except SetupError:
            pass
        if stopped is not None:
            raise stopped

    # --- Taking -------------------------------------------------------------------

    def take(self) -> None:
        with self.confined():
            self.check_place()
            refused: SetupError | None = None
            for _ in range(_TRIES):
                try:
                    self._make_state()
                    if fsio.write_new(self.file, self._payload()):
                        self._taken()
                        return
                    refused = None
                except SetupError as exc:
                    # A run that held the lock and saved no record takes the
                    # empty directories away when it gives the lock back: a
                    # directory that went in that instant is a race lost, and
                    # this run starts over. A refusal that stays (a home that
                    # cannot be written) is reported as what it is, below.
                    refused = exc
                    continue
                raw, holder = read(self.file)
                if raw is None:
                    continue  # given back in this instant: try again
                state_of, why = verdict(holder)
                if state_of == GONE and _token_of(holder) is None:
                    state_of, why = UNKNOWN, "the lock file holds no token of the run that took it"
                if state_of == GONE:
                    try:
                        self._clear(raw, holder)
                    except LockHeld:
                        raise
                    except SetupError as exc:
                        refused = exc  # the directory went under the claim: a race lost, as above
                    continue  # cleared, by this run or by a faster one: try again
                if state_of == RUNNING:
                    raise LockHeld(
                        f"{self.file}: another setup run is writing to this {self.whose} ({describe(holder)}); "
                        "nothing was changed. Wait for it to end and run again"
                    )
                raise LockHeld(
                    f"{self.file}: a setup run took this lock ({describe(holder)}) and did not give it back, and "
                    f"setup cannot tell whether it is still running: {why}. Nothing was changed. Once no setup run "
                    f"is using this {self.whose}, on any system that uses it, remove that file and run again"
                )
            if refused is not None:
                raise refused
            raise LockHeld(
                f"{self.file}: another setup run holds the lock of this {self.whose}, or is taking it; nothing was "
                "changed. Run again"
            )

    def _taken(self) -> None:
        """This run holds the lock. What no record lists yet is setup's to
        list: the state directory when it holds no record, and ``.agents``
        when the marker beside it says setup made it."""
        self.taken = True
        self._mark_own()
        self._collect()
        if not os.path.lexists(self.manifest):
            self.created.add(_STATE)
        if fsio.look(self.marker).kind == fsio.DIRECTORY and fsio.look(self.agents).kind == fsio.DIRECTORY:
            self.created.add(_AGENTS)

    def _clear(self, raw: bytes, holder: dict[str, Any] | None) -> None:
        """Take away the stale lock whose bytes are ``raw``; see "A lock
        nobody gave back" in the module. Returns when the lock is gone, by
        this run or by another; ``LockHeld`` when another run is at it."""
        busy = LockHeld(
            f"{self.file}: another setup run is clearing a stale lock of this {self.whose}; nothing was changed. "
            "Run again"
        )
        mine: Path | None = None
        token = _token_of(holder)
        behind: list[Path] = []  # claims of runs that are gone, which this run's claim stands for
        try:
            for _ in range(_CHAIN):
                if token is None:
                    raise busy
                claim = self.state / f"{CLAIM_PREFIX}{token}"
                if fsio.write_new(claim, self._payload()):
                    mine = claim
                    break
                claimed, claimant = read(claim)
                if claimed is None or claimed == self._payload():
                    raise busy
                if verdict(claimant)[0] != GONE:
                    raise busy
                # The run that claimed is gone too: the right it had goes
                # to whoever claims its claim, in the same way.
                behind.append(claim)
                token = _token_of(claimant)
            else:
                raise busy
            # The claim is this run's alone. Only now is the lock read
            # again, and removed only if it is still the one that was judged.
            again, _ = read(self.file)
            if again is not None and again == raw:
                if not fsio.remove_own_file(self.file):
                    raise LockHeld(
                        f"{self.file}: a stale lock ({describe(holder)}) cannot be removed; nothing was changed. "
                        "Remove that file and run again"
                    )
                self.notes.append(
                    f"cleared the lock of a setup run that ended without giving it back ({describe(holder)}): "
                    "that process is no longer running"
                )
                for claim in behind:
                    fsio.remove_own_file(claim)
        finally:
            if mine is not None:
                fsio.remove_own_file(mine)

    def _collect(self) -> None:
        """Remove, while this run holds the lock, what killed runs left in
        the state directory itself: pieces of a lock under a temporary
        name, and claims on a lock that is no longer there. Nothing in the
        backups, and nothing anywhere else."""
        try:
            found = fsio.names(self.state)
        except SetupError:
            return
        for name in found:
            path = self.state / name
            if fsio.look(path).kind != fsio.FILE:
                continue
            if fsio.is_temporary(name):
                fsio.discard_temporary(path)
            elif name.startswith(CLAIM_PREFIX):
                fsio.remove_own_file(path)

    # --- While it is held ---------------------------------------------------------

    def recorded(self) -> None:
        """Say that a record now lists the state directories: the marker
        has nothing more to say."""
        with self.confined():
            fsio.remove_if_empty(self.marker)

    def mark_agents(self) -> None:
        """Say, before the record that says so is removed, that ``.agents``
        was made by setup: the marker beside it."""
        with self.confined():
            self._mkdir(self.marker)

    def settle_marker(self) -> None:
        """No state directory is here. Where a killed run left the marker,
        the ``.agents`` beside it goes if it is empty, and the marker."""
        try:
            with self.confined():
                self.check_place()
                if fsio.look(self.marker).kind == fsio.DIRECTORY:
                    self._vacate()
        except SetupError:
            pass

    # --- Giving back --------------------------------------------------------------

    def release(self) -> None:
        """Give the lock back. An interrupt in the middle is no reason to
        leave a piece of it behind: the rest is done first, and the
        interrupt is raised again after."""
        if not self.taken:
            return
        stopped: KeyboardInterrupt | None = None
        try:
            try:
                self._give_back()
            except KeyboardInterrupt as exc:
                stopped = exc
                self._give_back()
        except SetupError:
            pass
        finally:
            self.taken = False
        if stopped is not None:
            raise stopped

    def _give_back(self) -> None:
        with self.confined():
            raw, _ = read(self.file)
            mine = raw is not None and raw == self._bytes
            if not mine and not self._given:
                return  # not this run's any more: nothing here is this run's to remove
            if not self._given:
                self._collect()
                self._recorded = os.path.lexists(self.manifest)
                if self._recorded:
                    fsio.remove_if_empty(self.marker)
                self._given = True  # said before the removal: an interrupt may come right after it
            if mine:
                fsio.remove_own_file(self.file)
            if not self._recorded:
                self._vacate()

    def interrupted(self) -> None:
        """Taking the lock was cut short. Where the lock file is there
        with this run's own bytes, this run holds it, and gives it back
        like any lock it holds."""
        if self.taken:
            return
        try:
            with self.confined():
                raw, _ = read(self.file)
                self.taken = raw is not None and bool(self._bytes) and raw == self._bytes
        except SetupError:
            pass

    def _vacate(self) -> None:
        """No record is here: an empty state directory answers for
        nothing and goes, and with it ``.agents`` where the marker says
        setup made it and nothing else is in it."""
        fsio.remove_if_empty(self.state)
        if fsio.look(self.marker).kind != fsio.DIRECTORY:
            return
        if fsio.look(self.state).kind == fsio.ABSENT:
            fsio.remove_if_empty(self.agents)
        if fsio.look(self.agents).kind == fsio.ABSENT or fsio.look(self.state).kind == fsio.ABSENT:
            # Gone, or holding something of the user's and so the user's.
            fsio.remove_if_empty(self.marker)


AGENTS = _AGENTS
STATE = _STATE


@contextlib.contextmanager
def held(roots: Any, *, project: bool = False, create: bool = True, follow: bool = False) -> Iterator[Lock | None]:
    """Hold the lock of the user level of ``roots``, or with ``project``
    of its project, for the block. ``LockHeld`` when another run has it.
    Without ``create``, a place with no state directory is not locked and
    gets none: there is nothing to guard there, and the block gets None."""
    key = paths.fold(lock_file(roots, project))
    mine = _HELD.get(key)
    if mine is not None:
        mine.depth += 1
        try:
            yield mine
        finally:
            mine.depth -= 1
        return
    mine = Lock(roots, project, follow)
    if not create and not os.path.isdir(mine.state):
        # Nothing to guard. A state directory that is a link is a
        # directory here, and is refused when the lock is taken.
        yield None
        return
    try:
        mine.take()
    except BaseException as exc:
        # Stopped half way (an interrupt, a refusal): what was made of the
        # lock is taken back, as far as it is this run's.
        mine.interrupted()
        mine.release()
        mine.give_up()
        if isinstance(exc, OSError):
            raise SetupError(f"{mine.file}: the lock cannot be taken: {paths.reason(exc)}") from None
        raise
    _HELD[key] = mine
    try:
        yield mine
    finally:
        _HELD.pop(key, None)
        mine.release()


def holder(roots: Any, project: bool = False) -> tuple[dict[str, Any] | None, str, str] | None:
    """For a command that only reads (``doctor``): who holds the lock of
    this home (or project), the verdict on that run and, for ``UNKNOWN``,
    why. None when no lock is there. Nothing is changed."""
    try:
        raw, said = read(lock_file(roots, project))
    except SetupError as exc:
        return None, UNKNOWN, exc.lines[0]
    if raw is None:
        return None
    state_of, why = verdict(said)
    return said, state_of, why


def leftovers(roots: Any, project: bool = False) -> list[Path]:
    """What a killed run left of a lock, for a command that only reads:
    the marker beside ``.agents``, pieces of a lock and claims on one in
    the state directory. Nothing is changed."""
    state = roots.state_dir_of(project)
    found: list[Path] = []
    marker = state.parent.parent / MARKER_NAME
    try:
        if fsio.look(marker).kind != fsio.ABSENT:
            found.append(marker)
        for name in fsio.names(state) if fsio.look(state).kind == fsio.DIRECTORY else []:
            # A piece of a lock is a file: only that is removed by the run
            # that takes the lock (``_collect``). Anything else of such a
            # name is not setup's, and is not said to be.
            if (fsio.is_temporary(name) or name.startswith(CLAIM_PREFIX)) and fsio.look(state / name).kind == fsio.FILE:
                found.append(state / name)
    except SetupError:
        pass
    return found
