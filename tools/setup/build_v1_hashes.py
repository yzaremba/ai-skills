#!/usr/bin/env python3
"""Build ``v1-known-hashes.json``: the hash of every committed version of
the v1 files, which ``render --migrate-v1`` removes a copy of on its own.

    python tools/setup/build_v1_hashes.py [--through REV] [--v1 REV] [--check]

A developer's tool, run from a clone with its history. It is the one place
in this package that runs git: ``git rev-parse``, ``git rev-list``,
``git ls-tree`` and ``git cat-file``, each from a fixed argument list,
without a shell, only reading, and with a time limit (``GIT_TIMEOUT``
seconds a command). Like the setup tool, it writes no bytecode: a run
leaves no ``__pycache__`` in the clone. It refuses a clone on a Windows drive
seen from WSL (under ``/mnt/<drive>/``): no WSL git runs there. The setup
tool itself never runs it; it reads the JSON file, which is committed.

What is hashed
    Every version, in every commit that ``--through`` (default ``HEAD``)
    reaches, of the v1 rule files and the v1 agent:
        prd-implementation.md, epic-implementation.md,
        avoid-bash-injection-heuristics.md (its v1 path) and
        rules/avoid-bash-injection-heuristics/avoid-bash-injection-heuristics.md
        (where it is now), agents/sprint-coder.md
    Every version, in every commit that ``--v1`` (default the tag ``v1.0``)
    reaches, of every file of the v1 skills: self-reflection, usage-cost,
    json-tools, csv-tools. The skills stop at v1: what a later commit made
    of a skill is not a v1 file, and a copy of it is not a v1 leftover that
    setup may remove on its own.

    Each version is hashed as committed, with LF line endings and with
    CRLF line endings: a checkout with ``core.autocrlf`` gave the second. A
    file with a NUL byte is hashed as committed only. A link in a tree is
    not a file and is left out.

The file
    {"schema_version": 1, "about": ..., "v1": <commit>, "built_from": <commit>,
     "files": {"<repository path>": ["<sha256>", ...]}}
    ``v1`` and ``built_from`` are the commits ``--v1`` and ``--through``
    named, so the same file is built again from them at any later commit
    (``--check`` does that and compares). No path of this machine is in it.

Exit code 0; with ``--check`` 1 when the file is not what the history gives;
2 on an error.
"""
from __future__ import annotations

# Outside the choke point, on purpose. Everything the setup tool changes on a
# disk passes ``wfsetup.fsio.admit``, which never admits a place inside the
# clone. This script does the opposite by design: its one output,
# ``v1-known-hashes.json``, is a committed file of the clone, and it reads
# the clone's history with git. So it writes that one file directly
# (``OUTPUT.write_bytes`` in ``main``) and uses nothing of ``fsio``. It is a
# developer's script: no command of ``workflow_setup.py`` imports or starts
# it, and it imports nothing of the package that changes a disk. The test
# that scans the syntax trees for disk-changing calls
# (``test_choke.SyntaxTreeTests``) names this file as the one exception and
# checks that the exception is exactly that one write.

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Before the package is imported, because importing is what writes it: the
# clone is changed only by ``git pull``, and holds no ``__pycache__`` of a run.
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "v1-known-hashes.json"
REPOSITORY = HERE.parents[1]

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from wfsetup import migrate  # noqa: E402

SCHEMA = 1
V1_TAG = "v1.0"
# How long one git command may take, in seconds. Read when it is started.
GIT_TIMEOUT = 120.0
ABOUT = (
    "The SHA-256 of every committed version of the v1 rule files, the v1 agent and the files of the v1 skills, "
    "each as committed, with LF and with CRLF line endings. Built by tools/setup/build_v1_hashes.py from the "
    "commits named here; not edited by hand."
)

# Every version through ``--through``.
RULE_PATHS = (
    *migrate.PROCESS_RULES, migrate.BASH_RULE, migrate.BASH_RULE_NOW, migrate.V1_AGENT_SOURCE,
)
# Every version through ``--v1``.
SKILL_DIRECTORIES = migrate.V1_SKILLS

_DRIVE = re.compile(r"/mnt/[A-Za-z](/|$)")
_COMMIT = re.compile(r"[0-9a-f]{40,64}")


class BuildError(Exception):
    pass


def refuse_windows_drive(repository: Path) -> None:
    """No WSL git against a clone on a Windows drive."""
    real = os.path.realpath(repository)
    from wfsetup import homes
    host = homes.Host.current()
    if _DRIVE.match(real.replace("\\", "/")) or (host.side == homes.WSL and host.foreign(real)):
        raise BuildError(
            f"{real}: on a Windows drive seen from WSL; git is not run there. Build the file in a clone inside "
            "WSL, or with the Windows git from Windows"
        )


def git(repository: Path, *arguments: str) -> bytes:
    """One read-only git command, from a fixed argument list."""
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    try:
        done = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, env=environment,
            timeout=GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise BuildError(f"git {' '.join(arguments[:2])} did not finish within {GIT_TIMEOUT:g} seconds") from None
    except OSError as exc:
        raise BuildError(f"git cannot be started: {exc.strerror or exc}") from None
    if done.returncode != 0:
        said = " ".join(done.stderr.decode("utf-8", "replace").split())
        raise BuildError(f"git {' '.join(arguments[:2])} failed: {said or done.returncode}")
    return done.stdout


def has_history(repository: Path, *revisions: str) -> bool:
    """Whether ``repository`` is a git working tree that has each of
    ``revisions`` as a commit. False, and never an error, where it is not:
    an exported tree, a shallow clone, no git."""
    try:
        refuse_windows_drive(repository)
        for revision in revisions:
            git(repository, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")
    except BuildError:
        return False
    return True


def commit_of(repository: Path, revision: str) -> str:
    text = git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii", "replace").strip()
    if not _COMMIT.fullmatch(text):
        raise BuildError(f"{revision}: git did not name a commit")
    return text


def blobs(repository: Path, tip: str, names: tuple[str, ...]) -> set[tuple[str, str]]:
    """Every (path, blob) below ``names`` in every commit ``tip`` reaches."""
    found: set[tuple[str, str]] = set()
    for commit in git(repository, "rev-list", tip).decode("ascii").split():
        listing = git(repository, "ls-tree", "-r", "-z", commit, "--", *names)
        for line in listing.split(b"\0"):
            if not line:
                continue
            head, _, path = line.partition(b"\t")
            mode, kind, blob = head.decode("ascii").split()
            if kind == "blob" and mode != "120000":
                found.add((path.decode("utf-8"), blob))
    return found


def forms(data: bytes) -> set[str]:
    """The hashes a copy of ``data`` may have on disk; see the module."""
    def digest(one: bytes) -> str:
        return hashlib.sha256(one).hexdigest()

    if b"\0" in data:
        return {digest(data)}
    unix = data.replace(b"\r\n", b"\n")
    return {digest(data), digest(unix), digest(unix.replace(b"\n", b"\r\n"))}


def build(repository: Path = REPOSITORY, v1: str = V1_TAG, through: str = "HEAD") -> dict:
    """The content of the hash file, from the history of ``repository``."""
    refuse_windows_drive(repository)
    v1_commit, through_commit = commit_of(repository, v1), commit_of(repository, through)
    wanted = blobs(repository, through_commit, RULE_PATHS)
    wanted |= blobs(repository, v1_commit, tuple(f"{name}/" for name in SKILL_DIRECTORIES))
    contents: dict[str, bytes] = {}
    files: dict[str, set[str]] = {}
    for path, blob in sorted(wanted):
        if blob not in contents:
            contents[blob] = git(repository, "cat-file", "blob", blob)
        files.setdefault(path, set()).update(forms(contents[blob]))
    return {
        "schema_version": SCHEMA,
        "about": ABOUT,
        "v1": v1_commit,
        "built_from": through_commit,
        "files": {path: sorted(files[path]) for path in sorted(files)},
    }


def to_bytes(found: dict) -> bytes:
    return (json.dumps(found, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build tools/setup/v1-known-hashes.json from the git history.")
    parser.add_argument("--through", default="HEAD", metavar="REV",
                        help="the commit whose history gives the rule and agent versions (default HEAD)")
    parser.add_argument("--v1", default=V1_TAG, metavar="REV",
                        help=f"the commit whose history gives the skill versions (default {V1_TAG})")
    parser.add_argument("--check", action="store_true",
                        help="write nothing: build from the commits the file names, and compare")
    args = parser.parse_args(argv)
    try:
        if args.check:
            held = json.loads(OUTPUT.read_bytes().decode("utf-8"))
            again = build(REPOSITORY, held["v1"], held["built_from"])
            same = to_bytes(again) == OUTPUT.read_bytes()
            print(f"{OUTPUT.name}: {'as the history gives it' if same else 'NOT what the history gives'}")
            return 0 if same else 1
        found = build(REPOSITORY, args.v1, args.through)
        OUTPUT.write_bytes(to_bytes(found))
        count = sum(len(hashes) for hashes in found["files"].values())
        print(f"{OUTPUT.name}: {len(found['files'])} files, {count} hashes; v1 {found['v1'][:12]}, "
              f"built from {found['built_from'][:12]}")
        return 0
    except (BuildError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
