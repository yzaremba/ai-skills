"""A project's git directory, read from the disk: where its exclude file is.

How a command uses it

    found = gitrepo.find(project)
    found.info        # the real path of <common dir>/info, or None
    found.exclude     # found.info / "exclude", or None
    found.note        # why there is no list, or None

Setup lists what it makes in a project in the repository's exclude file,
``info/exclude`` in its common git directory (R6.3): git reads it in every
worktree of the repository, and nobody commits it. This module only reads:
it runs no ``git`` program and changes nothing (``fsio`` does the writing).

Where the common directory is
    ``DIR/.git`` a directory: it is the common directory (the main
    worktree). A ``DIR/.git`` file, ``gitdir: <path>``, is a linked
    worktree's, and it is followed only when it is git's own pair:

    - ``<path>`` (relative to ``DIR``) is a directory this side of the
      machine can read; a path the other side wrote is not;
    - its ``commondir`` file names (relative to ``<path>``) the common
      directory;
    - its ``gitdir`` file names this project's ``.git`` file back.

    So a checkout's ``.git`` file cannot point setup at a directory of its
    choosing. The common directory holds ``HEAD``, ``objects`` and ``refs``,
    and an ``info`` directory (``git init`` makes it). Anything else (no
    ``.git``, a gitfile with no ``commondir``, as a submodule's or a
    separate git directory's is, a back-pointer that names another
    checkout) gives no list, and a note that says why.

The anchor
    ``info`` is given by its real path: the record's root ``git-info``
    (``Roots.git_info``), whose one path is ``git-info:exclude``. A link in
    the way cannot move it.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import fsio, paths
from .errors import SetupError

GIT = ".git"
INFO = "info"
EXCLUDE = "exclude"
_GITFILE_PREFIX = "gitdir:"
_LIMIT = 4096   # a gitfile, a commondir or a gitdir file is one line


@dataclass(frozen=True)
class Found:
    """Where a project's exclude file is, or why there is none."""

    info: Path | None
    note: str | None = None

    @property
    def exclude(self) -> Path | None:
        return None if self.info is None else self.info / EXCLUDE


def _none(project: Path, why: str) -> Found:
    return Found(None, f"{project}: {why}; setup lists nothing in an exclude file there")


def _line(path: Path) -> str | None:
    """The one line of a small file of git's, or None where it is no file
    or cannot be read."""
    try:
        if not fsio.is_file(path) or os.path.getsize(path) > _LIMIT:
            return None
        text = fsio.read_bytes(path).decode("utf-8")
    except (SetupError, OSError, UnicodeDecodeError):
        return None
    text = text.strip()
    return text if text and "\n" not in text and "\0" not in text else None


def _under(base: Path, text: str) -> Path:
    """``text`` as git reads a path in one of its files: relative to ``base``."""
    return Path(os.path.join(base, text))


def _real(path: Path) -> Path:
    return Path(fsio.clean_target(os.path.realpath(path)))


def _is_directory(path: Path) -> bool:
    try:
        return os.path.isdir(path)
    except (OSError, ValueError):
        return False


def _common(directory: Path) -> bool:
    """Whether ``directory`` is a repository's common git directory."""
    return fsio.is_file(directory / "HEAD") and _is_directory(directory / "objects") and _is_directory(directory / "refs")


def _same(one: Path, other: Path) -> bool:
    try:
        return os.path.samefile(one, other)
    except (OSError, ValueError):
        return False


def find(project: Path) -> Found:
    """Where the exclude file of the repository at ``project`` is; see the
    module. ``project`` is the top of a worktree: a directory below one
    has no ``.git`` of its own and gets no list."""
    dotgit = Path(project) / GIT
    try:
        os.stat(dotgit)
    except (FileNotFoundError, NotADirectoryError):
        return _none(project, "not a git repository's top (no .git)")
    except (OSError, ValueError) as exc:
        return _none(project, f"its .git cannot be read ({paths.reason(exc)})")
    if os.path.isdir(dotgit):
        common = _real(dotgit)
    elif fsio.is_file(dotgit):
        line = _line(dotgit)
        if line is None or not line.startswith(_GITFILE_PREFIX):
            return _none(project, "its .git file does not name a git directory")
        gitdir = _under(Path(project), line[len(_GITFILE_PREFIX):].strip())
        if not _is_directory(gitdir):
            return _none(project, f"its .git file names {gitdir}, which this side of the machine cannot read")
        shared = _line(gitdir / "commondir")
        if shared is None:
            return _none(project, f"its .git file names {gitdir}, which is not a linked worktree's (no commondir)")
        back = _line(gitdir / "gitdir")
        if back is None or not _same(_under(gitdir, back), dotgit):
            return _none(project, f"{gitdir} does not name this project's .git file back")
        common = _real(_under(gitdir, shared))
    else:
        return _none(project, "its .git is neither a directory nor a file")
    if not _common(common):
        return _none(project, f"{common} is not a git directory (no HEAD, objects and refs)")
    info = common / INFO
    if not _is_directory(info):
        return _none(project, f"{common} has no {INFO} directory")
    return Found(_real(info))


GIT_TIMEOUT = 30.0


def tracked(project: Path, relative: str) -> bool | None:
    """Whether git tracks the file ``relative`` (R6.4) of the repository at
    ``project``: ``git -C DIR ls-files --error-unmatch -- FILE``, which
    only reads. Exit 0 is tracked, 1 not tracked. Any other exit counts as
    not tracked where neither the project nor a directory above it has a
    ``.git`` (no repository at all); where one does, git failed for another reason (dubious ownership, say) and the
    answer is None, like where ``git`` could not be started or did not answer
    in time: the caller does not know."""
    try:
        done = subprocess.run(
            ["git", "-C", os.fspath(project), "ls-files", "--error-unmatch", "--", relative],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            timeout=GIT_TIMEOUT,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if done.returncode in (0, 1):
        return done.returncode == 0
    here = Path(os.path.abspath(project))
    return None if any(os.path.lexists(d / GIT) for d in (here, *here.parents)) else False
