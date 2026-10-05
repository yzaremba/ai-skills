"""The clone, the user home and the project of a run.

Every command that reads or writes outside the clone takes its places from
a ``Locations`` value, so a test points all of them at scratch directories.
"""
from __future__ import annotations

import argparse
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
    run is about no project; ``clone`` is the repository the tool runs from."""

    home: Path
    project: Path | None = None
    clone: Path = CLONE

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
        "An empty DIR is refused",
    )
    parser.add_argument(
        "--home",
        metavar="DIR",
        help="use DIR in place of the user's home directory (for tests and trial runs). "
        "An empty DIR is refused; it is never taken to mean the real home",
    )


def from_args(args: argparse.Namespace) -> Locations:
    """The locations the command line named. A directory given must exist.

    An option given with an empty value is refused and never read as "not
    given": a caller whose scratch-home variable came out empty must not end
    up working on the real home.
    """
    home = _own_home() if args.home is None else _directory(args.home, "--home")
    project = None if args.project is None else _directory(args.project, "--project")
    # The clone is read here and not left to the dataclass default, so that
    # a test can stand a scratch clone in its place.
    return Locations(home=home, project=project, clone=CLONE)


def _own_home() -> Path:
    try:
        return Path.home()
    except (RuntimeError, KeyError, OSError):
        raise SetupError("the user's home directory cannot be found; name one with --home DIR") from None


def _directory(text: str, option: str) -> Path:
    if not text.strip():
        raise SetupError(f"{option}: an empty value is not a directory; name one, or leave the option out")
    try:
        path = Path(text).expanduser()
    except (RuntimeError, KeyError):
        raise SetupError(f"{option}: {text}: the home directory of that user cannot be found") from None
    if paths.kind(path) != paths.DIRECTORY:
        raise SetupError(f"{option}: {text}: not a directory")
    return path
