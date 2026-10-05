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


def reason(exc: BaseException) -> str:
    """Why the system refused, in its own words and on one line."""
    text = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
    return " ".join(text.split())


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
