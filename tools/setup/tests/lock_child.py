"""A child process of the lock tests: one run that writes, or one that
holds the lock, in the world at ROOT (see ``crash_support.World``).

    lock_child.py hold ROOT READY RELEASE   take the lock, make the file
                                            READY, wait for RELEASE
    lock_child.py die ROOT                  take the lock and end without
                                            giving it back
    lock_child.py write ROOT NAME START     wait for the file START, then
                                            apply a plan of NAME's own

``write`` ends as the command line does: 0, or 2 with one ``error:`` line
for each line of the refusal.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

from crash_support import World  # noqa: E402
from wfsetup import fileops, fsio, lock  # noqa: E402
from wfsetup.errors import EXIT_ERROR, SetupError  # noqa: E402

FILES = 6


def wait_for(path: Path, seconds: float = 60.0) -> None:
    end = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() > end:
            raise SystemExit(f"{path}: never appeared")
        time.sleep(0.002)


def plan_of(world: World, name: str) -> fileops.Plan:
    """What the run ``name`` writes: files of its own, a directory, and
    its own block in a file every run edits."""
    plan = world.plan()
    for index in range(FILES):
        plan.write_file(world.home / "gen" / f"{name}-{index}.md", f"by {name}\n", inputs=name)
    plan.create_directory(world.home / "made" / name)
    plan.edit_block(world.home / ".claude" / "CLAUDE.md", f"by {name}\n", name=name)
    return plan


def main(argv: list[str]) -> int:
    what, world = argv[0], World(Path(argv[1]), prefix=(argv[2] if len(argv) > 2 else "H").upper())
    if what == "hold":
        with lock.held(world.roots):
            Path(argv[2]).write_bytes(b"")
            wait_for(Path(argv[3]))
        return 0
    if what == "die":
        with lock.held(world.roots):
            sys.stdout.flush()
            os._exit(9)
    name = argv[2]
    real = fsio.atomic_write

    def slowly(path, data, mode=None):
        time.sleep(0.004)  # long enough for the runs to overlap
        return real(path, data, mode)

    fsio.atomic_write = slowly
    wait_for(Path(argv[3]))
    try:
        plan_of(world, name).apply()
    except SetupError as exc:
        for line in exc.lines:
            print(f"error: {line}", file=sys.stderr)
        return EXIT_ERROR
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
