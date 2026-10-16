"""A child process of the lock race tests (``test_lock_race.py``): one
starter that takes the lock of a scratch home with the tool's own
``lock.held`` and says how that ended.

    lock_race_child.py HOME
        A worker that stays. It prints one line, ``ready``, and then answers
        each line of JSON on its input with one line of JSON on its output:

            {"at": T, "witness": DIR}

        wait (spinning, not sleeping) until the clock ``time.time()`` says
        T, then try to hold the lock of HOME. An empty line, or the end of
        the input, ends the worker.

    lock_race_child.py HOME once home|project [PROJECT] [WITNESS]
        One attempt, at once, at the lock of HOME or of PROJECT; one line of
        JSON, and the end.

While a starter holds the lock it makes the directory WITNESS (one call,
which the system refuses when the directory is there), stays for up to 3 ms,
and removes it. Two starters inside the lock at one moment cannot both make
it: the second reports ``"double": true``. That is the direct evidence the
parent asks for; the times are for a failure message only.

The answer:

    outcome   "held", "lockheld" (``lock.LockHeld``), "refused" (any other
              ``SetupError``) or "error" (anything else)
    lines     the lines of a ``SetupError``; text  what an exception said
    double    another starter was inside the lock at the same moment
    entered, left   ``time.time()`` inside the lock
    notes     what the lock had to tell (a stale lock that was cleared)
    created   the state directories the lock says are setup's to list

Nothing here depends on the system it runs on.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

sys.dont_write_bytecode = True

import support  # noqa: E402,F401  (the package on the path)
from wfsetup import lock  # noqa: E402
from wfsetup.errors import SetupError  # noqa: E402
from wfsetup.manifest import Roots  # noqa: E402

HOLD = 0.003  # the longest a starter stays inside the lock, in seconds


def attempt(roots: Roots, project: bool, witness: str | None) -> dict:
    """Try to hold the lock once, and say how it ended."""
    said: dict = {"pid": os.getpid(), "double": False}
    try:
        with lock.held(roots, project=project) as mine:
            said["entered"] = time.time()
            said["notes"] = list(mine.notes)
            said["created"] = sorted(mine.created)
            said["token"] = mine._token
            made = False
            if witness:
                try:
                    os.mkdir(witness)
                    made = True
                except FileExistsError:
                    said["double"] = True
            try:
                time.sleep(random.random() * HOLD)
            finally:
                if made:
                    try:
                        os.rmdir(witness)
                    except OSError as exc:
                        said["witness"] = f"{type(exc).__name__}: {exc}"
            said["left"] = time.time()
        said["outcome"] = "held"
    except lock.LockHeld as exc:
        said.update(outcome="lockheld", lines=list(exc.lines))
    except SetupError as exc:
        said.update(outcome="refused", lines=list(exc.lines))
    except BaseException as exc:  # noqa: BLE001  (whatever it is, the parent is told)
        said.update(outcome="error", text=f"{type(exc).__name__}: {exc}"[:600])
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
    return said


def say(said: dict) -> None:
    sys.stdout.write(json.dumps(said) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    home = argv[0]
    if len(argv) > 1 and argv[1] == "once":
        project = argv[2] == "project"
        roots = Roots(home, argv[3] if len(argv) > 3 and argv[3] else None)
        say(attempt(roots, project, argv[4] if len(argv) > 4 else None))
        return 0
    roots = Roots(home)
    sys.stdout.write("ready\n")
    sys.stdout.flush()
    for line in sys.stdin:
        if not line.strip():
            break
        asked = json.loads(line)
        while time.time() < asked["at"]:
            pass
        say(attempt(roots, False, asked.get("witness")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
