"""The few things setup does to a file system, each failing in one line.

Everything setup changes on a disk goes through this module: one atomic
write, one way to make and remove a link, one way to look at a path without
following it. Nothing here decides what to write; that is ``fileops``.

The choke point (``admit``)
    Every function here that changes the disk (creates, replaces, removes,
    renames, links, unlinks, makes or removes a directory, changes
    permission bits) first hands the entry it is about to change to
    ``admit``, and no other module of the package calls a function of
    ``os``, ``shutil``, ``tempfile`` or ``pathlib`` that changes the disk
    (a test reads every module's syntax tree for that). ``admit`` refuses:

    - a credentials name (``.credentials.json``, ``auth.json``; any letter
      case, and the spellings Windows opens as the same file);
    - a path with a ``..`` in it: the system and the text would not agree
      on where that is;
    - a place inside the clone the tool runs from (``RUNNING_CLONE``), or
      inside any other directory the run bars (the clone a test stands in
      its place, a project for a change of the home, the home's state for
      a change of a project);
    - a place outside every root the run was given. A change is made under
      ``with confined(roots, barred):``; with no such block, nothing is
      changed at all.

    "Inside" is asked of the real place: the real path of the directory the
    entry is in (every link followed, the entry itself not: making or
    removing a link changes the directory it is in), and of each directory
    above it, compared with ``os.path.samestat`` against the root or the
    barred directory. So letter case on a file system that ignores it, a
    second path to the same directory and a link anywhere in the chain
    cannot make an inside place look outside. A directory that cannot be
    looked at while this is decided means "refused", never "not inside".

    The blocks are a thread's own, and a block inside a block only
    narrows: a change is made where every block the thread has open
    allows it. A thread that opened none changes nothing.

What the guard does not hold against
    ``admit`` decides on the disk as it is at that instant, and the change
    is a second call to the system, by the same path. So the guards hold
    against the disk as the run finds it, and not against another program
    that changes the same directories during the run: one that replaces a
    directory by a link in the instant between the two calls can make the
    change land where the link leads. Closing that would take every
    change being made relative to an open directory (``dir_fd``), which
    this module does not do. What it does do, because it costs nothing: a
    temporary file that was just created is looked at again through its
    open descriptor, and the directory it was made in is compared with
    the one that was there before; if the directory is another one now,
    or the name no longer leads to that file, the write fails, and the
    file is removed where its name still leads to a place the run may
    change; where it leads out of the bounds by then, nothing is changed
    there, a removal neither, and the error names the place. Permission
    bits are never set
    through a link: on the open descriptor of a file setup just made, and
    elsewhere only after a look that refuses a link.

Credentials: besides ``admit``, the functions that open a file for reading
(``read_bytes``) refuse a credentials name too. ``look`` only asks what kind
of entry is at a path; it opens nothing.

Temporary names
    A file or directory setup is still building is called
    ``.wfsetup-<8 hex digits>.tmp``, a directory ``.wfsetup-<4 hex
    digits>.tmp`` (``is_temporary``), beside the place it is renamed to. A
    failure removes it; a killed process leaves it. Only the call that
    made a temporary removes it: a name that is taken is never cleared to
    make room, another name is tried, and where the names of a run are
    fixed (below) the change is refused in one line. Inside
    ``with named_temporaries(token):`` every such name is the one the token
    gives (``temporary_names``): ``fileops`` saves the token in the install
    record before the first of them is made, so the next run removes
    exactly those and nothing that merely looks like one.

For the crash tests only
    With the environment variable ``WFSETUP_TEST_STOP_AFTER`` set to a
    number N, the process ends itself (``os._exit``, code
    ``STOP_EXIT_CODE``: no handler and no ``finally`` runs, as after a
    kill) right after its N-th change to the disk. The variable is read
    once, when this module is loaded; without it the counter does nothing.
    Nothing in the tool sets it, and no command passes it on: the tests
    alone start a command with it.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from . import paths
from .errors import SetupError

ABSENT = "absent"
FILE = "file"
DIRECTORY = "directory"
LINK = "link"
OTHER = "other"  # a FIFO, a socket, a device

CREDENTIAL_NAMES = frozenset({".credentials.json", "auth.json"})

# What a temporary file of ``atomic_write`` is called: beside its target, so
# that the replace is a rename within one directory.
TEMP_PREFIX = ".wfsetup-"
TEMP_SUFFIX = ".tmp"
TEMP_PATTERN = ".wfsetup-*.tmp"  # the same, as an ignore file writes it
_TEMP_NAME = re.compile(r"\.wfsetup-[0-9a-f]{4}(?:[0-9a-f]{4})?\.tmp")
_TOKEN = re.compile(r"[0-9a-f]{8}")

# The permission bits of a backup and of the directories that hold backups,
# where the system has such bits: a backup is a full copy of a user's file.
PRIVATE_FILE = 0o600
PRIVATE_DIRECTORY = 0o700

# The clone the tool runs from: this file is <clone>/tools/setup/wfsetup/fsio.py.
RUNNING_CLONE = Path(__file__).resolve().parents[3]


def is_temporary(name: str) -> bool:
    """Whether ``name`` is a name setup gives what it is still building."""
    return _TEMP_NAME.fullmatch(name if paths.CASE_SENSITIVE else name.lower()) is not None


def new_token() -> str:
    """A token for the temporary names of one run; see the module."""
    return os.urandom(4).hex()


def temporary_names(token: str) -> tuple[str, str]:
    """The names of a temporary file and of a temporary directory of the
    run ``token``."""
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise SetupError(f"{token!r}: not a token for a run's temporary names")
    return f"{TEMP_PREFIX}{token}{TEMP_SUFFIX}", f"{TEMP_PREFIX}{token[:4]}{TEMP_SUFFIX}"


_NAMED: list[str] = []


@contextlib.contextmanager
def named_temporaries(token: str) -> Iterator[None]:
    """Give every temporary made in the block the name ``token`` gives."""
    temporary_names(token)
    _NAMED.append(token)
    try:
        yield
    finally:
        _NAMED.pop()


def _temporary_name(directory: Path | str, short: bool = False) -> str:
    """A temporary name in ``directory``. ``short`` gives four hex digits
    in place of eight, for a directory that other names are made below:
    Windows allows a directory's path fewer characters than a file's."""
    if _NAMED:
        return os.path.join(directory, temporary_names(_NAMED[-1])[1 if short else 0])
    return os.path.join(directory, f"{TEMP_PREFIX}{os.urandom(2 if short else 4).hex()}{TEMP_SUFFIX}")


class CredentialsRefused(SetupError):
    """A credentials file was named. Setup never touches one."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path}: a credentials file; setup never opens, copies or writes one")
        self.path = Path(path)


def is_credentials(path: Path | str) -> bool:
    """Whether ``path`` is called like a credentials file. Windows takes a
    name with dots or spaces after it for the same file, and a name with a
    ``:`` after it for a stream of that file."""
    name = os.path.basename(os.fspath(path))
    if os.name == "nt" or ":" in name:
        name = name.split(":", 1)[0]
    return name.rstrip(" .").lower() in CREDENTIAL_NAMES


def guard(path: Path | str) -> None:
    if is_credentials(path):
        raise CredentialsRefused(Path(path))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- Where a run may change the disk ---------------------------------------------

class Refused(SetupError):
    """``admit`` refused a place: nothing was changed there."""


@dataclass(frozen=True)
class _Mark:
    """A directory as ``admit`` compares it: its real path and what the
    system says of it. ``found`` is None for one that is not there, which
    nothing can be inside. ``fault`` says why it could not be looked at."""

    path: str
    real: str
    found: os.stat_result | None
    fault: str | None = None


def _mark(path: Path | str) -> _Mark:
    text = os.path.abspath(os.fspath(path))
    try:
        real = clean_target(os.path.realpath(text))
        return _Mark(text, real, os.stat(real))
    except (FileNotFoundError, NotADirectoryError):
        return _Mark(text, text, None)
    except (OSError, ValueError) as exc:
        return _Mark(text, text, None, paths.reason(exc))


def _same_directory(found: os.stat_result, real: str, mark: _Mark) -> bool:
    if mark.found is None:
        return False
    if found.st_ino and mark.found.st_ino:
        return os.path.samestat(found, mark.found)
    # A file system that numbers nothing: the real paths are what is left.
    return paths.same(real, mark.real)


@dataclass(frozen=True)
class Bounds:
    """Where the changes of a block may be made; see the module."""

    roots: tuple[_Mark, ...]
    barred: tuple[_Mark, ...]


class _Open(threading.local):
    """The ``confined`` blocks that are open, outermost first: each thread
    has its own, so a thread that opened none changes nothing under the
    bounds of another."""

    def __init__(self) -> None:
        self.levels: list[Bounds] = []

    def __len__(self) -> int:
        return len(self.levels)


_BOUNDS = _Open()
# Used where no ``confined`` block is open. None in the tool: a change
# outside a block is refused. The tests give their scratch area here.
_BASE: Bounds | None = None
_RUNNING: list[_Mark] = []


def _running_clone() -> _Mark:
    if not _RUNNING:
        _RUNNING.append(_mark(RUNNING_CLONE))
    return _RUNNING[0]


def bounds(roots: Iterable[Path | str], barred: Iterable[Path | str] = ()) -> Bounds:
    return Bounds(tuple(_mark(root) for root in roots), tuple(_mark(one) for one in barred))


@contextlib.contextmanager
def confined(roots: Iterable[Path | str], barred: Iterable[Path | str] = ()) -> Iterator[None]:
    """Let the block change the disk below ``roots`` and nowhere else, and
    nowhere inside ``barred`` or the clone the tool runs from. A block
    inside a block can only narrow: a change is made where every open
    block allows it, so an inner block never reaches a place the outer one
    does not. The blocks are those of the thread that opened them."""
    levels = _BOUNDS.levels
    levels.append(bounds(roots, barred))
    try:
        yield
    finally:
        levels.pop()


def _place(path: str) -> tuple[str, list[tuple[str, os.stat_result]]]:
    """The real place of a change at ``path``, and each directory from the
    one the entry is in up to the top, as far as it exists, with what the
    system says of it. What cannot be looked at is an ``OSError``."""
    parent, name = os.path.split(path)
    real = clean_target(os.path.realpath(parent)) if parent else os.getcwd()
    above: list[tuple[str, os.stat_result]] = []
    probe = real
    while True:
        try:
            above.append((probe, os.stat(probe)))
        except (FileNotFoundError, NotADirectoryError):
            pass  # not made yet: what counts is the directory it will be made in
        higher = os.path.dirname(probe)
        if higher == probe:
            break
        probe = higher
    return os.path.join(real, name), above


def admit(path: Path | str) -> str:
    """The one guard: refuse a change at ``path`` unless it may be made
    there (see the module), and return the path as the change is to be
    asked of the system. ``Refused``, and ``CredentialsRefused`` for a
    credentials name; both are a ``SetupError`` of one line."""
    text = os.fspath(path)
    if is_credentials(text):
        raise CredentialsRefused(Path(text))
    if "\0" in text or ".." in Path(text).parts:
        raise Refused(f"{text}: a path with '..' in it; setup changes nothing there")
    text = os.path.abspath(text)
    # Every block this thread has open, or the base where it has none.
    levels = list(_BOUNDS.levels) or ([] if _BASE is None else [_BASE])
    if not levels:
        raise Refused(f"{text}: this run was given no place to write; nothing was changed")
    try:
        place, above = _place(text)
    except (OSError, ValueError) as exc:
        raise Refused(f"{text}: where it really is cannot be told ({paths.reason(exc)}); nothing was changed") from None
    barred = [_running_clone(), *[mark for limits in levels for mark in limits.barred]]
    for mark in [*barred, *[mark for limits in levels for mark in limits.roots]]:
        if mark.fault is not None:
            raise Refused(
                f"{text}: {mark.path} cannot be looked at ({mark.fault}), so setup cannot tell whether this place "
                "is inside it; nothing was changed"
            )
    for mark in barred:
        if paths.inside(place, mark.real) or any(_same_directory(found, real, mark) for real, found in above):
            what = "the clone" if mark is barred[0] else f"{mark.path}"
            raise Refused(
                f"{text}: its real place, {place}, is inside {what}, which setup never writes to; nothing was "
                "changed there"
            )
    for limits in levels:
        if not any(_same_directory(found, real, mark) for mark in limits.roots for real, found in above):
            raise Refused(
                f"{text}: its real place, {place}, is outside the directories this run may write to; nothing was "
                "changed there"
            )
    return text


def admits(path: Path | str) -> str | None:
    """Why ``admit`` would refuse ``path`` under the bounds now in force,
    or None. Nothing is changed and nothing is raised."""
    try:
        admit(path)
    except SetupError as exc:
        return exc.lines[0]
    return None


# --- The changes -----------------------------------------------------------------
#
# Each change to the disk is one call of one of the functions below, and
# they are the only place a changing function of ``os`` is called. Each
# asks ``admit`` first.

STOP_VARIABLE = "WFSETUP_TEST_STOP_AFTER"
STOP_EXIT_CODE = 77


def _stop_after() -> int | None:
    text = os.environ.get(STOP_VARIABLE, "")
    return int(text) if text.isdigit() and int(text) > 0 else None


_STOP_AFTER = _stop_after()
_CHANGES = [0]


def _changed() -> None:
    """One change to the disk was made. See "For the crash tests only"."""
    if _STOP_AFTER is None:
        return
    _CHANGES[0] += 1
    if _CHANGES[0] >= _STOP_AFTER:
        os._exit(STOP_EXIT_CODE)


def _mkdir(path: Path | str, mode: int | None = None) -> None:
    where = admit(path)
    try:
        if mode is None:
            os.mkdir(where)
        else:
            os.mkdir(where, mode)
    finally:
        _changed()


def _rmdir(path: Path | str) -> None:
    where = admit(path)
    try:
        os.rmdir(where)
    finally:
        _changed()


def _unlink(path: Path | str) -> None:
    where = admit(path)
    try:
        os.unlink(where)
    finally:
        _changed()


def _chmod(path: Path | str, mode: int, handle: int | None = None) -> None:
    """Give the entry at ``path`` the permission bits ``mode``, and never
    what a link there leads to. With ``handle``, the open descriptor of
    that very file, the bits are set through it where the system can
    (``os.fchmod``): no name is looked up again. Otherwise the entry is
    looked at first, and a link is refused: ``os.chmod`` would follow it."""
    where = admit(path)
    try:
        if handle is not None and hasattr(os, "fchmod") and os.name == "posix":
            os.fchmod(handle, mode)
            return
        if _is_link(os.lstat(where)):
            raise OSError(f"{where}: is a link; setup sets no permission bits through one")
        os.chmod(where, mode)
    finally:
        _changed()


def _replace_entry(source: Path | str, path: Path | str) -> None:
    where, what = admit(path), admit(source)
    try:
        os.replace(what, where)
    finally:
        _changed()


def _rename_entry(source: Path | str, path: Path | str) -> None:
    where, what = admit(path), admit(source)
    try:
        os.rename(what, where)
    finally:
        _changed()


def _hard_link(source: Path | str, path: Path | str) -> None:
    where, what = admit(path), admit(source)
    try:
        os.link(what, where)
    finally:
        _changed()


def _symlink(target: str, path: Path | str, directory: bool) -> None:
    guard(target)
    where = admit(path)
    try:
        os.symlink(target, where, target_is_directory=directory)
    finally:
        _changed()


def _create(path: Path | str, mode: int) -> int:
    """A new file, which must not be there, open for writing."""
    where = admit(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(where, flags, mode)
    finally:
        _changed()


def _create_junction(target: str, link: Path, use_mklink: bool = False) -> None:
    """The one call that makes a junction; see ``make_junction``."""
    guard(target)
    where = admit(link)
    try:
        create = None
        if not use_mklink:
            try:
                import _winapi  # CPython on Windows
                create = getattr(_winapi, "CreateJunction", None)
            except ImportError:
                create = None
        if create is not None:
            create(target, where)
        else:
            _mklink(target, Path(where))
    finally:
        _changed()


def scratch_file() -> Any:
    """An unnamed file for what a program that setup starts prints: in the
    system's temporary directory, gone when it is closed. It is the one
    thing setup writes outside the roots of a run, and it is never inside
    the clone: a temporary directory that lies there is refused."""
    import tempfile

    try:
        directory = tempfile.gettempdir()
        clone = _running_clone()
        _, above = _place(os.path.join(os.path.abspath(directory), "x"))
    except (OSError, ValueError) as exc:
        raise Refused(f"the system's temporary directory cannot be used: {paths.reason(exc)}") from None
    if clone.fault is not None or any(_same_directory(found, real, clone) for real, found in above):
        raise Refused(
            f"{directory}: the system's temporary directory is inside the clone, which setup never writes to; "
            "point TMPDIR (TEMP on Windows) elsewhere"
        )
    return tempfile.TemporaryFile()


def null_output() -> int:
    """The null device, open for writing: nothing on a disk is changed."""
    return os.open(os.devnull, os.O_WRONLY)


# --- Looking ------------------------------------------------------------------

@dataclass(frozen=True)
class Seen:
    """What is at a path, the link itself and not what it leads to."""

    kind: str
    mode: int | None = None      # permission bits of a file
    target: str | None = None    # a link's own text
    directory: bool = False      # a link that leads to a directory
    junction: bool = False       # a link that is a Windows junction
    links: int = 1               # a file's hard links: its names, this one included


def _is_link(found: os.stat_result) -> bool:
    if stat.S_ISLNK(found.st_mode):
        return True
    # A Windows directory junction is not a symlink to Python, and is one
    # to setup: writing below it writes somewhere else.
    tag = getattr(found, "st_reparse_tag", 0)
    return bool(tag) and tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)


def look(path: Path) -> Seen:
    """What is at ``path``, without following a link and without opening
    anything. What cannot be looked at is a ``SetupError``."""
    try:
        found = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return Seen(ABSENT)
    except (OSError, ValueError) as exc:
        raise SetupError(f"{path}: cannot be read: {paths.reason(exc)}") from None
    if _is_link(found):
        return Seen(
            LINK, target=read_link(path), directory=os.path.isdir(path),
            junction=not stat.S_ISLNK(found.st_mode),
        )
    if stat.S_ISREG(found.st_mode):
        return Seen(FILE, mode=stat.S_IMODE(found.st_mode), links=max(int(found.st_nlink or 1), 1))
    if stat.S_ISDIR(found.st_mode):
        return Seen(DIRECTORY)
    return Seen(OTHER)


def is_file(path: Path | str) -> bool:
    """Whether ``path`` is a file, or a link that leads to one. Nothing is
    opened: a FIFO is not a file, and asking does not wait for its writer."""
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


def read_bytes(path: Path) -> bytes:
    """The bytes of the file at ``path``, or of the file a link there leads
    to. Anything else that can be opened (a FIFO, a device) is refused
    before it is opened: reading one would wait for ever."""
    guard(path)
    try:
        try:
            found = os.stat(path)
        except (OSError, ValueError):
            found = None  # not to be looked at: opening it says why, and waits for nothing
        if found is not None and not stat.S_ISREG(found.st_mode):
            raise SetupError(f"{path}: cannot be read: it is not a file")
        return Path(path).read_bytes()
    except (OSError, ValueError) as exc:
        raise SetupError(f"{path}: cannot be read: {paths.reason(exc)}") from None


def names(directory: Path | str) -> list[str]:
    """What ``directory`` holds, by name, sorted. A ``SetupError`` where it
    cannot be listed."""
    try:
        return sorted(os.listdir(directory))
    except (OSError, ValueError) as exc:
        raise SetupError(f"{directory}: cannot be read: {paths.reason(exc)}") from None


# --- Links --------------------------------------------------------------------

def clean_target(text: str) -> str:
    """A link's text without the prefix Windows puts before a long path."""
    for prefix in ("\\\\?\\UNC\\", "\\\\?\\", "\\??\\"):
        if text.startswith(prefix):
            rest = text[len(prefix):]
            return "\\\\" + rest if "UNC" in prefix else rest
    return text


def read_link(path: Path) -> str:
    try:
        return clean_target(os.readlink(path))
    except (OSError, ValueError) as exc:
        raise SetupError(f"{path}: the link cannot be read: {paths.reason(exc)}") from None


def same_target(one: str, other: str) -> bool:
    """Whether two link texts name the same place, letter case aside where
    the system ignores it."""
    def norm(text: str) -> str:
        return paths.fold(os.path.normpath(paths.long_form(clean_target(text))))
    return norm(one) == norm(other)


def is_junction(path: Path | str) -> bool:
    """Whether ``path`` is a Windows directory junction. ``os.path.isjunction``
    is there from Python 3.12; the reparse tag says the same on 3.11. Never
    true on a system that has no junctions."""
    asked = getattr(os.path, "isjunction", None)
    if asked is not None:
        try:
            return bool(asked(path))
        except (OSError, ValueError):
            return False
    try:
        found = os.lstat(path)
    except (OSError, ValueError):
        return False
    tag = getattr(found, "st_reparse_tag", 0)
    return bool(tag) and tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)


def make_link(target: str, link: Path, directory: bool, junction: bool | None = None) -> None:
    """Make ``link`` lead to ``target``.

    On Linux a symlink. On Windows a link to a directory is a junction,
    always, for a link setup makes (``junction`` None): a symlink there
    needs Developer Mode or Administrator, a junction needs neither, and
    one form per system means the same run gives the same link with or
    without the privilege. A link to a file on Windows can only be a
    symlink, and fails without the privilege; setup links directories only.

    ``junction`` True or False asks for that form: a link of the user's
    that setup removed is put back as what it was.
    """
    guard(link)
    guard(target)
    if junction is None:
        junction = os.name == "nt" and directory
    if junction:
        make_junction(target, link)
        return
    try:
        _symlink(target, link, directory)
    except (OSError, NotImplementedError) as exc:
        raise SetupError(f"{link}: the link cannot be created: {paths.reason(exc)}") from None


def local_drive_path(text: str) -> bool:
    """``X:\\...``: absolute, on a drive letter, and no UNC or device path.
    A junction can lead nowhere else."""
    text = clean_target(text)
    return len(text) >= 3 and text[0].isalpha() and text[1] == ":" and text[2] in "\\/"


def make_junction(target: str, link: Path, *, use_mklink: bool = False) -> None:
    """Make the directory junction ``link`` to the directory ``target``
    (Windows only).

    ``_winapi.CreateJunction`` does it inside this process: nothing is
    started and no command line is parsed. It is an undocumented module of
    CPython, there on Windows since 3.5. Where it is missing (another
    Python, a later CPython), and with ``use_mklink``, the junction is made
    by ``mklink /J``, a built-in of ``cmd.exe``; see ``_mklink``.

    What is made is read back: a junction that does not lead to ``target``
    is removed again and reported. Nothing is left at ``link`` on failure.
    """
    guard(link)
    guard(target)
    link = Path(link)
    if os.name != "nt":
        raise SetupError(f"{link}: a junction can be made on Windows only")
    target = clean_target(os.fspath(target))
    if not local_drive_path(target):
        raise SetupError(
            f"{link}: the link cannot be created: a junction leads only to a directory on a local "
            f"drive, and {target} is not one"
        )
    if not os.path.isdir(target):
        raise SetupError(f"{link}: the link cannot be created: {target} is not a directory")
    if os.path.lexists(link):
        raise SetupError(f"{link}: the link cannot be created: something is there")
    try:
        _create_junction(target, link, use_mklink)
        if not (_is_link(os.lstat(link)) and same_target(os.readlink(link), target)):
            raise OSError("what was made is not a junction to the target")
    except (OSError, ValueError) as exc:
        _discard_failed_junction(link)
        raise SetupError(f"{link}: the link cannot be created: {paths.reason(exc)}") from None


def _discard_failed_junction(link: Path) -> None:
    """Take away what a failed creation left at ``link``: a junction, or
    the empty directory that was to become one. ``os.rmdir`` removes a
    junction itself and refuses a directory that holds anything, so nothing
    a junction leads to can be lost here."""
    try:
        _rmdir(link)
    except (OSError, SetupError):
        pass


# What ``cmd.exe`` reads as its own syntax, inside quotes or not. A path
# holding one is not handed to it.
_CMD_SPECIAL = frozenset('&|<>^%!"()\r\n')

# How long ``mklink`` may take, in seconds. It makes one directory entry; a
# child that has not ended by then is stopped and the junction reported as
# not made (what it left, if anything, is removed by ``make_junction``).
MKLINK_TIMEOUT = 30.0


def _mklink(target: str, link: Path) -> None:
    """``mklink /J`` through ``cmd.exe``, for a Python without
    ``_winapi.CreateJunction``.

    ``mklink`` is not a program, so ``cmd.exe`` has to run it, and
    ``cmd.exe`` parses its command line itself. The process is started
    from a fixed argument list (no ``shell=True``), ``cmd.exe`` is taken
    from the system directory and not from ``PATH``, and a path that holds
    a character ``cmd.exe`` gives a meaning to is refused, not escaped.
    """
    import subprocess

    for text in (target, os.fspath(link)):
        if _CMD_SPECIAL & set(text):
            raise OSError(f"{text}: holds a character cmd.exe reads as syntax; the junction was not made")
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or ""
    program = os.path.join(system_root, "System32", "cmd.exe")
    if not system_root or not os.path.isfile(program):
        raise OSError("cmd.exe was not found in the system directory")
    try:
        done = subprocess.run(
            [program, "/d", "/c", "mklink", "/J", os.fspath(link), target],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False,
            timeout=MKLINK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise OSError(f"mklink did not end within {MKLINK_TIMEOUT:g} seconds; the junction was not made") from None
    if done.returncode != 0:
        said = " ".join(done.stderr.decode("utf-8", "replace").split())
        raise OSError(said or f"mklink ended with code {done.returncode}")


def remove_link(link: Path) -> None:
    """Remove the link itself; what it leads to is never touched.

    Only two calls are used, and neither can reach the target: ``os.unlink``
    removes a symlink (and, on a current Windows Python, a junction), and
    ``os.rmdir`` removes a junction or a directory symlink itself and
    refuses a real directory that holds anything. What is at ``link`` is
    looked at first: anything that is not a link is refused.
    """
    guard(link)
    try:
        if not _is_link(os.lstat(link)):
            raise SetupError(f"{link}: the link cannot be removed: it is not a link")
        try:
            _unlink(link)
        except (PermissionError, IsADirectoryError):
            # A junction, or a link to a directory on an older Windows.
            if not _is_link(os.lstat(link)):
                raise
            _rmdir(link)
    except OSError as exc:
        raise SetupError(f"{link}: the link cannot be removed: {paths.reason(exc)}") from None


# --- Directories and files ----------------------------------------------------

def make_directory(path: Path, mode: int | None = None) -> None:
    """Make one directory. ``mode`` is the permission bits it is to have
    where the system has them; without it, what this process gives a new
    directory."""
    if mode is not None and os.name == "posix":
        if mode == PRIVATE_DIRECTORY:
            _make_private_directory(path)
        else:
            # With bits of its own it is made under a temporary name, given
            # the bits and renamed: a kill never leaves it with other bits.
            publish_directory(path, lambda directory: None, mode)
        return
    try:
        _mkdir(path)
    except OSError as exc:
        raise SetupError(f"{path}: the directory cannot be created: {paths.reason(exc)}") from None


def _make_private_directory(path: Path) -> None:
    """A directory its owner alone can enter, made in one call: the system
    makes it with these bits or with fewer, never with more, so a kill
    leaves no directory that others can read."""
    try:
        _mkdir(path, PRIVATE_DIRECTORY)
        if stat.S_IMODE(os.lstat(path).st_mode) != PRIVATE_DIRECTORY:
            _chmod(path, PRIVATE_DIRECTORY)
    except OSError as exc:
        raise SetupError(f"{path}: the directory cannot be created: {paths.reason(exc)}") from None


def own_directory_mode(path: Path) -> int | None:
    """The permission bits of the directory ``path`` where they are not
    the ones this process gives a new directory, so that a directory made
    again gets them back. None where they are the same, where the
    directory cannot be looked at, and on a system without such bits."""
    if os.name != "posix":
        return None
    try:
        mode = stat.S_IMODE(os.lstat(path).st_mode)
    except OSError:
        return None
    mask = os.umask(0)
    os.umask(mask)
    return None if mode == 0o777 & ~mask else mode


def remove_directory(path: Path) -> None:
    try:
        _rmdir(path)
    except OSError as exc:
        raise SetupError(f"{path}: the directory cannot be removed: {paths.reason(exc)}") from None


def remove_file(path: Path) -> None:
    guard(path)
    try:
        _unlink(path)
    except PermissionError as exc:
        raise SetupError(
            f"{path}: cannot be removed: {paths.reason(exc)} (read-only, or open in another program?)"
        ) from None
    except OSError as exc:
        raise SetupError(f"{path}: cannot be removed: {paths.reason(exc)}") from None


def remove_own_file(path: Path) -> bool:
    """Remove a file of setup's own (its lock, a claim on one), trying
    again for a moment where Windows refuses while another program has it
    open. True when it is gone, by this call or already; False when the
    system would not let it go."""
    for wait in (*REPLACE_WAITS, None):
        try:
            _unlink(path)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if wait is None:
                return False
            time.sleep(wait)
        except (OSError, SetupError):
            return False
    return False


def default_mode() -> int:
    """The permission bits a new file gets from this process."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


# How long a refused rename is tried again, in seconds, one wait per try.
#
# On Windows a file cannot be renamed over while another program holds it
# open without sharing that: a virus scanner or the search indexer reading a
# file setup wrote a moment ago, an editor, a provider reading its settings.
# The refusal is a ``PermissionError`` that is gone a moment later, and a
# run writes its record many times in a row, so the first of these would
# otherwise end a run half way. The waits add up to under a second; a file
# that is really read-only or held open is then reported as before. POSIX
# renames over an open file, so nothing is tried twice there.
REPLACE_WAITS: tuple[float, ...] = (0.02, 0.05, 0.1, 0.2, 0.4) if os.name == "nt" else ()


def _replace(temporary: str, path: Path) -> None:
    for wait in REPLACE_WAITS:
        try:
            _replace_entry(temporary, path)
            return
        except PermissionError:
            time.sleep(wait)
    _replace_entry(temporary, path)


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    """Put ``data`` at ``path``: all of it or none of it.

    The bytes go to a temporary file in the same directory, are flushed and
    synced, and the file is then renamed over ``path``. A reader sees the
    old file or the new one, never a part. ``mode`` is the permission bits
    of the result; without it an existing file keeps its own and a new one
    gets the process default. When anything fails the temporary file is
    removed and ``path`` is as it was.

    The directory must exist. A hard link to the old file keeps the old
    bytes: the name is given to a new file.
    """
    admit(path)
    path = Path(path)
    if mode is None:
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except OSError:
            mode = default_mode()
    temporary = None
    try:
        temporary = _write_temporary(path.parent, data, mode)
        _replace(temporary, path)
        temporary = None
    except PermissionError as exc:
        raise SetupError(
            f"{path}: cannot be written: {paths.reason(exc)} (read-only, or open in another program?)"
        ) from None
    except OSError as exc:
        raise SetupError(f"{path}: cannot be written: {paths.reason(exc)}") from None
    finally:
        if temporary is not None:
            _discard(temporary)
    _sync_directory(path.parent)


def _taken(name: str) -> SetupError:
    """Something is at a temporary name this run was about to use, and
    this run did not put it there: it is not removed."""
    return SetupError(
        f"{name}: something is there under the temporary name of this run, and setup did not make it; nothing "
        "was changed there. Move it away and run again"
    )


def _directory_now(directory: Path | str) -> os.stat_result | None:
    try:
        return os.stat(directory)
    except (OSError, ValueError):
        return None


def _still_there(directory: Path | str, before: os.stat_result | None, name: str, handle: int) -> bool:
    """Whether the file just made under ``name``, open as ``handle``, is
    in the directory that was there when the change was admitted: the
    directory is the same one, and the name still leads to this file.
    Where the system numbers nothing there is nothing to compare."""
    if before is not None:  # else it could not be looked at before: nothing to compare
        try:
            after = os.stat(directory)
        except (OSError, ValueError):
            return False
        if before.st_ino and after.st_ino and not os.path.samestat(before, after):
            return False
    return _leads_to(name, handle)


def _leads_to(name: str, handle: int) -> bool:
    """Whether ``name`` leads, now, to the file that is open as
    ``handle``. Both are asked through an open file, which every system
    numbers the same way (a look by name and one by handle need not agree
    on Windows). Nothing is written: the name is opened for reading."""
    try:
        if not stat.S_ISREG(os.lstat(name).st_mode):
            return False  # a link, or a FIFO that opening would wait on: not the file that was made
        with open(name, "rb") as probe:
            return os.path.sameopenfile(probe.fileno(), handle)
    except (OSError, ValueError):
        return False


def _write_temporary(directory: Path | str, data: bytes, mode: int | None = None) -> str:
    """A new temporary file in ``directory`` that holds ``data``, synced,
    with the permission bits ``mode`` (without it, its owner's alone). It
    is the caller's to rename or to remove. If the bytes cannot all be
    written, nothing is left.

    A name that is taken is never cleared: another name is tried, and
    where the run's names are fixed (``named_temporaries``) the write is
    refused in one line. Only a file this call made is removed by it."""
    for attempt in range(50):
        name = _temporary_name(directory)
        if os.path.lexists(name):
            if _NAMED or attempt == 49:
                raise _taken(name)
            continue
        before = _directory_now(directory)
        try:
            handle = _create(name, PRIVATE_FILE)
        except FileExistsError:
            # Made by another in this instant: not this call's to remove.
            if _NAMED or attempt == 49:
                raise _taken(name) from None
            continue
        except Exception:
            raise  # refused: nothing was made
        except BaseException:
            # An interrupt in the instant the file was made. Nothing was
            # at the name a moment ago, so what is there now is this call's.
            _discard(name)
            raise
        mine = True  # what is at the name is the file this call made
        try:
            with os.fdopen(handle, "wb") as stream:
                # The cheap second look; see "What the guard does not
                # hold against" in the module.
                if not _still_there(directory, before, name, stream.fileno()):
                    # The file is removed below only where the name still
                    # leads to it, and to a place this run may change.
                    # Where the name leads to something else by now, that
                    # is not this call's to remove; and where it leads out
                    # of the roots, no change is made there, a removal
                    # neither: the place is named instead.
                    mine = _leads_to(name, stream.fileno())
                    led = clean_target(os.path.realpath(directory))
                    raise SetupError(
                        f"{name}: the directory changed while setup was writing into it (another program moved or "
                        f"replaced it); setup stopped there. If a file of that name is left in {led}, it is setup's "
                        "temporary file: remove it"
                    )
                if mode is not None and hasattr(os, "fchmod") and os.name == "posix":
                    _chmod(name, mode, stream.fileno())
                stream.write(data)
                stream.flush()
                try:
                    os.fsync(stream.fileno())
                except OSError:
                    pass  # a file system that cannot sync still gets the rename
            if mode is not None and not (hasattr(os, "fchmod") and os.name == "posix"):
                _chmod(name, mode)
        except BaseException:
            if mine:
                _discard(name)
            raise
        return name
    raise FileExistsError(f"no free temporary name in {directory}")  # not reached


def _discard(temporary: str) -> None:
    """Remove a temporary file that was not put in place, if it can be."""
    try:
        if not is_temporary(os.path.basename(temporary)):
            return
        found = os.lstat(temporary)
        if not stat.S_ISREG(found.st_mode):
            return
        if os.name == "nt" and not found.st_mode & stat.S_IWRITE:
            _chmod(temporary, PRIVATE_FILE)  # Windows removes no read-only file
        _unlink(temporary)
    except (OSError, SetupError):
        pass


def discard_temporary(path: Path | str) -> bool:
    """Remove what a killed run left at the temporary name ``path``: a
    file, or a directory that holds nothing. Anything else stays. True
    when nothing is there any more."""
    try:
        found = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except (OSError, ValueError):
        return False
    if not is_temporary(os.path.basename(os.fspath(path))) or _is_link(found):
        return False
    try:
        if stat.S_ISDIR(found.st_mode):
            _rmdir(path)
        elif stat.S_ISREG(found.st_mode):
            _discard(os.fspath(path))
        return not os.path.lexists(path)
    except (OSError, SetupError):
        return False


def write_new(path: Path, data: bytes) -> bool:
    """Make the file ``path`` holding ``data``, only if nothing is there.
    False, and nothing changed, when something is.

    The file appears whole or not at all: it is written under a temporary
    name and given its own name by a hard link, which the system refuses
    when the name is taken. Where a file system has no hard links, Windows
    renames (its rename refuses a name that is taken) and any other system
    creates the name exclusively and then writes, so there, for a moment,
    the file can be seen empty.
    """
    admit(path)
    path = Path(path)
    temporary = None
    try:
        for attempt in range(6):
            temporary = _write_temporary(path.parent, data)
            try:
                _hard_link(temporary, path)
                return True
            except FileExistsError:
                return False
            except FileNotFoundError:
                # The temporary was taken away by a run that cleaned up
                # the directory in this instant: written again, and linked
                # again. The file is never made in any way that could
                # show it half written because of that.
                if os.path.lexists(path):
                    return False
                if os.path.lexists(temporary) or attempt == 5:
                    raise
                temporary = None
                continue
            except (OSError, NotImplementedError, AttributeError):
                if os.path.lexists(path):
                    return False
                break  # a file system without hard links
        if temporary is None or not os.path.lexists(temporary):
            temporary = _write_temporary(path.parent, data)
        if os.name == "nt":
            try:
                _rename_entry(temporary, path)
            except FileExistsError:
                return False
            temporary = None
            return True
        try:
            handle = _create(path, PRIVATE_FILE)
        except FileExistsError:
            return False
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        return True
    except OSError as exc:
        raise SetupError(f"{path}: cannot be written: {paths.reason(exc)}") from None
    finally:
        if temporary is not None:
            _discard(temporary)


class AlreadyThere(SetupError):
    """``publish_directory`` found something at the place it was to fill."""


def publish_directory(path: Path, fill: Callable[[Path], None], mode: int | None = None) -> None:
    """Make the directory ``path`` with what ``fill`` puts into it, so that
    it is never seen without it: a directory is made beside it under a
    temporary name, ``fill`` is called with that directory, and it is then
    renamed to ``path``. A killed process leaves ``path`` absent, or there
    and complete. ``AlreadyThere`` when something is at ``path``, by then;
    on any failure nothing is left.

    One gap is the system's: POSIX renames over an empty directory, so one
    that another program makes at ``path`` in the instant between the look
    and the rename is replaced by this one.
    """
    path = Path(path)
    admit(path)
    # The temporary directory, once it is this call's: only then is it
    # this call's to remove. A name that is taken is never cleared.
    temporary: Path | None = None
    try:
        for attempt in range(20):
            candidate = Path(_temporary_name(path.parent, short=True))
            if os.path.lexists(candidate):
                if _NAMED or attempt == 19:
                    raise _taken(os.fspath(candidate))
                continue
            temporary = candidate  # said before it is made: an interrupt may come in the instant after
            try:
                _mkdir(candidate)
                break
            except FileExistsError:
                temporary = None  # made by another in this instant
                if _NAMED or attempt == 19:
                    raise _taken(os.fspath(candidate)) from None
            except OSError as exc:
                temporary = None  # refused: nothing was made
                raise SetupError(f"{path}: the directory cannot be created: {paths.reason(exc)}") from None
            except SetupError:
                temporary = None
                raise
        assert temporary is not None
        if mode is not None and os.name == "posix":
            _chmod(temporary, mode)
        fill(temporary)
        if os.path.lexists(path):
            raise AlreadyThere(f"{path}: the directory cannot be created: something is there")
        try:
            _rename(os.fspath(temporary), path)
        except FileExistsError:
            raise AlreadyThere(f"{path}: the directory cannot be created: something is there") from None
        except OSError as exc:
            if os.path.lexists(path):
                raise AlreadyThere(f"{path}: the directory cannot be created: something is there") from None
            raise SetupError(f"{path}: the directory cannot be created: {paths.reason(exc)}") from None
    except BaseException:
        if temporary is not None:
            try:
                remove_tree(temporary)
            except SetupError:
                pass
        raise
    _sync_directory(path.parent)


def _rename(temporary: str, path: Path) -> None:
    for wait in REPLACE_WAITS:
        try:
            _rename_entry(temporary, path)
            return
        except FileExistsError:
            raise
        except PermissionError:
            time.sleep(wait)
    _rename_entry(temporary, path)


def make_directories(path: Path, mode: int | None = None) -> list[Path]:
    """Make ``path`` and the directories above it that are missing, each
    with ``mode`` where the system has such bits. Returns the ones made,
    outermost first."""
    path = Path(path)
    missing: list[Path] = []
    probe = path
    while not os.path.lexists(probe):
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    made: list[Path] = []
    for directory in reversed(missing):
        try:
            if mode is not None and os.name == "posix":
                # Made with these bits or with fewer, never with more.
                _mkdir(directory, mode)
                if stat.S_IMODE(os.lstat(directory).st_mode) != mode:
                    _chmod(directory, mode)
            else:
                _mkdir(directory)
        except FileExistsError:
            continue
        except OSError as exc:
            raise SetupError(f"{directory}: the directory cannot be created: {paths.reason(exc)}") from None
        made.append(directory)
    return made


def make_private(directory: Path) -> None:
    """Give a directory of setup's own the permission bits of one that
    holds backups, where the system has such bits. Never a link."""
    if os.name != "posix":
        return
    try:
        found = os.lstat(directory)
        if stat.S_ISDIR(found.st_mode) and stat.S_IMODE(found.st_mode) != PRIVATE_DIRECTORY:
            _chmod(directory, PRIVATE_DIRECTORY)
    except (OSError, SetupError):
        pass


def remove_tree(path: Path) -> None:
    """Remove the directory ``path`` and everything in it: only ever one
    this process made a moment ago, under a temporary name. A link, at
    ``path`` or below it, is removed as a link and never followed. Nothing
    is done where nothing is. A credentials file is never in such a tree:
    one is refused, and the tree stays."""
    path = Path(path)
    try:
        found = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return
    except (OSError, ValueError) as exc:
        raise SetupError(f"{path}: cannot be removed: {paths.reason(exc)}") from None
    try:
        if _is_link(found) or not stat.S_ISDIR(found.st_mode):
            guard(path)
            if _is_link(found):
                remove_link(path)
            else:
                _unlink(path)
            return
        for name in os.listdir(path):
            remove_tree(path / name)
        _rmdir(path)
    except OSError as exc:
        raise SetupError(f"{exc.filename or path}: cannot be removed: {paths.reason(exc)}") from None


def remove_if_empty(path: Path) -> bool:
    """Remove the directory ``path`` if it is one and holds nothing."""
    try:
        if _is_link(os.lstat(path)):
            return False
        _rmdir(path)
    except (OSError, ValueError, SetupError):
        return False
    return True


def temporaries(directory: Path | str) -> list[Path]:
    """What ``directory`` holds under a temporary name of setup's: files and
    directories, never a link. Empty where the directory cannot be listed."""
    try:
        found_names = sorted(os.listdir(directory))
    except (OSError, ValueError):
        return []
    found: list[Path] = []
    for name in found_names:
        if not is_temporary(name):
            continue
        path = Path(directory) / name
        try:
            status = os.lstat(path)
        except (OSError, ValueError):
            continue
        if not _is_link(status) and (stat.S_ISREG(status.st_mode) or stat.S_ISDIR(status.st_mode)):
            found.append(path)
    return found


def _sync_directory(directory: Path) -> None:
    """Make the rename itself durable, where a directory can be opened."""
    if os.name != "posix":
        return
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)
