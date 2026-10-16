"""The clone, the user home and the project of a run.

Every command that reads or writes outside the clone takes its places from
a ``Locations`` value, so a test points all of them at scratch directories.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .errors import SetupError

# This file is <clone>/tools/setup/wfsetup/locations.py. The path is made
# real first, so a link to the tool does not change where the clone is.
CLONE = Path(__file__).resolve().parents[3]

SETTINGS_DIR = ".agents"
SETTINGS_FILE = "workflow.toml"
LOCAL_SETTINGS_FILE = "workflow.local.toml"


@dataclass(frozen=True)
class Locations:
    """``home`` is the user's home directory; ``project`` is None when the
    run is about no project; ``clone`` is the repository the tool runs from.

    ``real_home`` is True only when ``home`` is the user's own home, taken
    because no ``--home`` was given. Anything else is a scratch home: the
    providers' environment variables are not read for it and the clone need
    not be shared (see ``homes``). False is the default, so that a value
    built by hand, in a test, is never taken for the real home."""

    home: Path
    project: Path | None = None
    clone: Path = CLONE
    real_home: bool = False

    @property
    def defaults_file(self) -> Path:
        return self.clone / "tools" / "setup" / "defaults.toml"

    @property
    def providers_dir(self) -> Path:
        return self.clone / "providers"

    @property
    def roles_dir(self) -> Path:
        return self.clone / "roles"

    @property
    def user_file(self) -> Path:
        return self.home / SETTINGS_DIR / SETTINGS_FILE

    @property
    def project_file(self) -> Path | None:
        return None if self.project is None else self.project / SETTINGS_DIR / SETTINGS_FILE

    @property
    def local_file(self) -> Path | None:
        return None if self.project is None else self.project / SETTINGS_DIR / LOCAL_SETTINGS_FILE


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add ``--project`` and ``--home``, which mean the same in every command."""
    parser.add_argument(
        "--project",
        metavar="DIR",
        help="the project whose settings files are read: DIR/.agents/workflow.toml and "
        "DIR/.agents/workflow.local.toml. The project is only ever this directory; it is "
        "not taken from the working directory. Without --project no project file is read. "
        "An empty DIR is refused. A command that writes (init, render, uninstall) also refuses "
        "the home directory itself, a directory that holds the home or the clone, and the clone setup "
        "runs from or a directory inside it",
    )
    parser.add_argument(
        "--home",
        metavar="DIR",
        help="use DIR in place of the user's home directory (for tests and trial runs). "
        "The providers' homes are then DIR/.claude and DIR/.codex, with DIR/.agents beside "
        "them, and the environment variables CLAUDE_CONFIG_DIR and CODEX_HOME are ignored. "
        "An empty DIR is refused, and never taken to mean the real home; so is the clone setup "
        "runs from, or a directory inside it",
    )


def from_args(args: argparse.Namespace, writes: bool = True) -> Locations:
    """The locations the command line named. A directory given must exist.

    An option given with an empty value is refused and never read as "not
    given": a caller whose scratch-home variable came out empty must not end
    up working on the real home.

    Refused as well, since setup writes nothing inside the clone it runs
    from and keeps a home's record apart from a project's: a home that is
    the clone or lies inside it, and, for a command that writes, a project
    that is the home, or that is the clone or lies inside it.

    ``writes`` is False only for a command that changes nothing in a
    project (``show``, ``validate``, ``homes``, ``doctor``). Such a command
    may be given the clone as its project: the repository is worked on like
    any project, and a session in it asks ``show`` for its settings.
    """
    home = _own_home() if args.home is None else _directory(args.home, "--home")
    project = None if args.project is None else _directory(args.project, "--project")
    # The clone is read here and not left to the dataclass default, so that
    # a test can stand a scratch clone in its place.
    clone = CLONE
    if args.home is not None and _within(home, clone):
        raise SetupError(
            f"--home: {args.home}: {_where(home, clone)} the clone setup runs from ({clone}); setup writes nothing "
            "inside the clone. Name a directory outside it"
        )
    if project is not None:
        if writes and _within(project, clone):
            raise SetupError(
                f"--project: {args.project}: {_where(project, clone)} the clone setup runs from ({clone}); setup "
                "writes nothing inside the clone, so it cannot be set up as a project. Name a directory outside it"
            )
        if writes and _real(project) == _real(home):
            raise SetupError(
                f"--project: {args.project}: is the home directory itself; a project is a directory of its own, "
                "with its own settings and its own install record"
            )
        if writes:
            # A project's record changes the project and nothing else. It
            # could not, if the home or the clone lay inside the project.
            for what, other in (("the home directory", home), ("the clone setup runs from", clone)):
                if _within(other, project):
                    raise SetupError(
                        f"--project: {args.project}: holds {what} ({other}); a project is a directory of its own, "
                        "and setup changes nothing of a home or of the clone through a project. Name the project "
                        "itself"
                    )
    return Locations(home=home, project=project, clone=clone, real_home=args.home is None)


def _real(path: Path) -> str:
    """The path every link is followed for, in the form paths are compared in."""
    return paths.fold(os.path.realpath(paths.absolute(path)))


def _within(path: Path, base: Path) -> bool:
    """Whether ``path`` is ``base`` or lies below it, by its text or by
    where its links lead."""
    return paths.inside(paths.absolute(path), paths.absolute(base)) or paths.inside(_real(path), _real(base))


def _where(path: Path, base: Path) -> str:
    return "is" if _real(path) == _real(base) or paths.same(paths.absolute(path), paths.absolute(base)) else "lies inside"


# What no path argument may hold: the C0 controls and DEL, the C1 controls
# (NEL among them) and the line and paragraph separators. A line break in a
# path splits every message that names it over two lines.
def control_character(text: str) -> bool:
    """Whether ``text`` holds a control character or a line separator."""
    return any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F or char in "  " for char in text)


def path_argument(text: str, option: str) -> str:
    """``text``, the value of the path option ``option``, or a
    ``SetupError`` of one line: an empty value is no path (and would mean
    the working directory), and one with a control character is refused
    unprinted."""
    if not isinstance(text, str) or not text.strip():
        raise SetupError(f"{option}: an empty value is not a path; name one, or leave the option out")
    if control_character(text):
        raise SetupError(f"{option}: the value holds a control character or a line break; no path of setup's has one")
    return text


def _own_home() -> Path:
    try:
        return Path.home()
    except (RuntimeError, KeyError, OSError):
        raise SetupError("the user's home directory cannot be found; name one with --home DIR") from None


def _directory(text: str, option: str) -> Path:
    if not text.strip():
        raise SetupError(f"{option}: an empty value is not a directory; name one, or leave the option out")
    path_argument(text, option)
    try:
        path = Path(text).expanduser()
    except (RuntimeError, KeyError):
        raise SetupError(f"{option}: {text}: the home directory of that user cannot be found") from None
    if paths.kind(path) != paths.DIRECTORY:
        raise SetupError(f"{option}: {text}: not a directory")
    # Spelled out where Windows gave a short name (``SOMEON~1``): the path
    # is compared with others by its text. It stays relative if it was.
    return Path(paths.long_form(path))
