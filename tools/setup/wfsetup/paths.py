"""What is at a path, asked so that no answer is a traceback.

``pathlib``'s ``exists`` and ``is_dir`` raise ``PermissionError`` for a path
inside a directory that cannot be searched, and take a link whose target is
gone for a path that is not there. ``os.path.lexists`` does not follow the
link, but answers False for every failure, a refused permission among them.
``kind`` uses the same ``lstat`` and tells the cases apart: what cannot be
looked at, and a link that leads nowhere, are each a ``SetupError`` naming
the path.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from .errors import SetupError

ABSENT = "absent"
FILE = "file"
DIRECTORY = "directory"
OTHER = "other"  # a FIFO, a socket, a device


# A link made inside WSL on a Windows drive, to an absolute path, is kept by
# Windows as a file with this reparse tag (IO_REPARSE_TAG_LX_SYMLINK). To a
# Windows program it is a file that cannot be opened, and no link it can
# read; a path below it cannot be looked at. Windows says "Invalid argument"
# or "The file cannot be accessed by the system", which names no cause.
WSL_LINK_TAG = 0xA000001D


def is_wsl_link(path: Path | str) -> bool:
    """Whether ``path`` is a link made in WSL that Windows cannot follow.
    Never true on a system other than Windows."""
    try:
        return getattr(os.lstat(path), "st_reparse_tag", 0) == WSL_LINK_TAG
    except (OSError, ValueError):
        return False


def _wsl_link_above(file: object) -> str | None:
    """The path itself, or the directory above it, that is such a link."""
    if os.name != "nt" or not isinstance(file, (str, os.PathLike)):
        return None
    path = Path(os.fspath(file))
    for candidate in (path, *path.parents):
        if is_wsl_link(candidate):
            return "it" if candidate == path else str(candidate)
    return None


def reason(exc: BaseException) -> str:
    """Why the system refused, in its own words and on one line. Where the
    file it refused is, or lies below, a link made in WSL, that is said: the
    system's own words do not."""
    text = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
    text = " ".join(text.split())
    link = _wsl_link_above(getattr(exc, "filename", None)) if isinstance(exc, OSError) else None
    if link is not None:
        text += f" ({link} is a link made in WSL, which Windows cannot follow)"
    return text


# --- Comparing ----------------------------------------------------------------
#
# Windows ignores letter case in a path and Linux does not. Every comparison
# of two paths, of a path with a root, of two link texts and of two keys of
# the install record goes through the functions below, so the rule is in one
# place: letter case counts on POSIX and does not on Windows.
#
# Windows also has two spellings of one name: ``C:\Users\SOMEON~1`` is the
# 8.3 short form of ``C:\Users\Someone Else``, and ``%TEMP%`` often arrives
# in it. No folding of letters makes the two equal. ``long_form`` asks the
# system for the long spelling of the part of a path that exists; a path a
# command is given is put through it once, where it comes in (``absolute``),
# and so is a link's text when two are compared. A link is not followed for
# it: the path keeps its own names, only spelled out.

CASE_SENSITIVE = os.name != "nt"


def fold(path: Path | str) -> str:
    """``path`` in the form two paths are compared in: as it is on POSIX,
    in lower case and with one kind of separator on Windows."""
    return os.path.normcase(os.fspath(path))


def fold_key(key: str) -> str:
    """A key of the install record (``home:.claude/skills``) in the form
    two keys are compared in."""
    return key if CASE_SENSITIVE else key.lower()


def same(one: Path | str, other: Path | str) -> bool:
    """Whether two paths are the same text to this system."""
    return fold(one) == fold(other)


def inside(path: Path | str, base: Path | str) -> bool:
    """Whether ``path`` is ``base`` or lies below it, by the text alone."""
    one, other = fold(path), fold(base).rstrip("\\/" if os.name == "nt" else "/")
    return one == other or one.startswith(other + os.sep)


def _long_name(text: str) -> str | None:
    """The long spelling of a path that exists (Windows only), else None."""
    try:
        import ctypes

        ask = ctypes.windll.kernel32.GetLongPathNameW
        ask.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        ask.restype = ctypes.c_uint32
        size = 512
        while True:
            buffer = ctypes.create_unicode_buffer(size)
            need = ask(text, buffer, size)
            if need == 0:
                return None  # not there, or not to be looked at
            if need < size:
                return buffer.value
            size = need + 1
    except (ImportError, AttributeError, OSError, ValueError):
        return None


def long_form(path: Path | str) -> str:
    """``path`` with every 8.3 short name of its existing part spelled out
    (``SOMEON~1`` as ``Someone Else``). The text itself where nothing is
    short, where the system cannot say, and on a system without such names.
    No link is followed and nothing is opened."""
    text = os.fspath(path)
    if os.name != "nt" or "~" not in text:
        return text
    head = text
    while "~" in head:
        found = _long_name(head)
        if found is not None:
            return found + text[len(head):]   # what is not there keeps its own spelling
        parent = os.path.dirname(head)
        if not parent or parent == head:
            break
        head = parent
    return text


def absolute(path: Path | str) -> Path:
    """``path`` made absolute, as a command takes a path it was given: no
    link followed, ``..`` taken out, and on Windows short names spelled out."""
    return Path(long_form(os.path.abspath(os.fspath(path))))


def kind(path: Path) -> str:
    """``ABSENT``, ``FILE``, ``DIRECTORY`` or ``OTHER``; a link counts as
    what it leads to.

    Nothing is opened, so a FIFO does not block. A path under something that
    is not a directory is absent, as it is on Windows; a caller that minds
    looks at the parent first.
    """
    try:
        found = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return ABSENT
    except (OSError, ValueError) as exc:
        raise SetupError(f"{path}: cannot be read: {reason(exc)}") from None
    if stat.S_ISLNK(found.st_mode):
        try:
            found = os.stat(path)
        except PermissionError as exc:
            raise SetupError(f"{path}: cannot be read: {reason(exc)}") from None
        except (OSError, ValueError):
            # The target is gone, or the link leads back to itself.
            raise SetupError(f"link target missing: {path}") from None
    if stat.S_ISREG(found.st_mode):
        return FILE
    if stat.S_ISDIR(found.st_mode):
        return DIRECTORY
    return OTHER


def entries(directory: Path) -> list[Path]:
    """What ``directory`` holds, by name. Empty when it is not there or is
    not a directory; a ``SetupError`` when it cannot be listed."""
    if kind(directory) != DIRECTORY:
        return []
    try:
        return sorted(directory.iterdir())
    except OSError as exc:
        raise SetupError(f"{directory}: cannot be read: {reason(exc)}") from None
