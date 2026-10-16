"""The lock is never held by two runs at once, whatever is at its path.

The race (``RaceTests``)
    Twelve worker processes (``lock_race_child.py``) are started once and
    stay. In each round the parent prepares a scratch home, names a moment a
    few milliseconds ahead, and every worker tries, at that moment, to hold
    the home's lock with the tool's own ``lock.held``. The rounds go through
    these variants in turn:

    stale               a lock of a process that has ended, on this system
    stale+record        the same, beside a record
    stale+claim         the same, and the claim of a run that died clearing it
    stale+claim+record  the same, beside a record
    free                a state directory with no lock in it
    free+record         the same, with a record
    first-run           no ``.agents`` at all

    A worker inside the lock makes a witness directory (one call that the
    system refuses when the directory is there) and removes it before it
    leaves, so two workers inside at one moment are seen as such, not
    inferred from clocks. What must hold, each asserted by a test of its
    own so that one failure does not hide another:

    - no round has two holders;
    - every round has a holder (the lock is not lost);
    - no worker ends with anything but "held" or ``LockHeld``, and a
      ``LockHeld`` is one of the three lines a race can give;
    - a stale lock is not cleared by two runs, and no run says it cleared
      one where none was;
    - nothing is left: no lock, no claim, no temporary, and where no record
      was planted no state directory either (on a first run no ``.agents``
      and no marker).

    300 rounds by default; ``WFSETUP_TEST_FULL=1`` in the environment gives
    2,000 (a minute or two) and prints the counts of each variant.

One interleaving, forced (``InterleavingTests``)
    The order that let two runs hold the lock: starter A reads the stale
    lock and judges its process gone; starter B clears it and takes the
    lock; A goes on. Done in one process with two threads, A stopped at
    ``lock.verdict`` or ``lock.read``.

A state directory that goes while a starter is on its way to the lock
(``VacatedTests``), what else can be at the lock's path (``OddPathTests``),
and the project's lock (``ProjectTests``).

Run from the repository root:
    python -m unittest discover -s tools/setup/tests -p test_lock_race.py
"""
from __future__ import annotations

import collections
import json
import os
import queue
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import support
from wfsetup import fsio, lock
from wfsetup.errors import SetupError
from wfsetup.manifest import Roots

CHILD = support.TESTS / "lock_race_child.py"
FULL = os.environ.get("WFSETUP_TEST_FULL") == "1"
ROUNDS = 2000 if FULL else 300
STARTERS = 12
VARIANTS = ("stale", "stale+record", "stale+claim", "stale+claim+record", "free", "free+record", "first-run")
LEAD = 0.006     # how far ahead the common start is, in seconds
JITTER = 0.0004  # in every other round each worker starts up to this much later
PATIENCE = 120   # how long the parent waits for a worker's answer, in seconds
PROMPT = 20      # what "at once" may take on a slow machine, in seconds

RECORD = b'{"schema_version": 1, "entries": {}, "backups": []}\n'
STATE = (".agents", "workflow-setup")
# The three lines a starter that lost a race may get.
WRITING = "another setup run is writing to this"
CLEARING = "another setup run is clearing a stale lock of this"
TAKING = "another setup run holds the lock of this"
WHAT_TO_DO = r"(?i)\bremove (it|that file) and run again"


def ended_pid() -> int:
    """The id of a process that has ended: a child that was waited for."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def token() -> str:
    return os.urandom(8).hex()


def lock_bytes(pid: int, **changes: object) -> bytes:
    """What a lock file of a run with the id ``pid`` holds, on this system
    (``lock.Lock._payload``). Its start is one no process has."""
    said: dict = {
        "schema_version": lock.SCHEMA_VERSION, "pid": pid, "start": "0", "identity": lock.identity(),
        "command": "workflow_setup.py render", "time": "2026-01-01 00:00:00 UTC", "token": token(),
    }
    said.update(changes)
    return (json.dumps(said, ensure_ascii=True) + "\n").encode("utf-8")


def snapshot(root: Path) -> dict[str, tuple]:
    """Everything below ``root`` without opening what is not a file: a link
    with its text, a directory with its bits, a file with its bits, its
    bytes (None where they cannot be read), its number and its time."""
    found: dict[str, tuple] = {}
    for directory, directories, files in os.walk(root):
        for name in [*directories, *files]:
            path = os.path.join(directory, name)
            seen = os.lstat(path)
            relative = Path(path).relative_to(root).as_posix()
            if stat.S_ISLNK(seen.st_mode):
                found[relative] = ("link", os.readlink(path))
            elif stat.S_ISDIR(seen.st_mode):
                found[relative] = ("directory", stat.S_IMODE(seen.st_mode))
            elif stat.S_ISREG(seen.st_mode):
                try:
                    data: bytes | None = Path(path).read_bytes()
                except OSError:
                    data = None
                found[relative] = ("file", stat.S_IMODE(seen.st_mode), data, seen.st_ino, seen.st_mtime_ns)
            else:
                found[relative] = ("other", seen.st_mode, seen.st_ino)
    return found


def names_below(root: Path) -> set[str]:
    return set(snapshot(root))


def run_once(home: Path, scope: str = "home", project: Path | None = None, witness: Path | None = None) -> dict:
    """One attempt at a lock in a process of its own, with a limit: what it
    said, or ``{"outcome": "hang"}``."""
    argv = [sys.executable, "-B", str(CHILD), str(home), "once", scope, "" if project is None else str(project)]
    if witness is not None:
        argv.append(str(witness))
    try:
        done = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=PATIENCE,
            env=support.child_environment(), cwd=str(support.TESTS),
        )
    except subprocess.TimeoutExpired:
        return {"outcome": "hang"}
    out, err = done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")
    if done.returncode != 0 or err.strip() or not out.strip():
        return {"outcome": "error", "text": f"exit {done.returncode}: {err[-600:]}"}
    return json.loads(out.splitlines()[-1])


# --- The race ----------------------------------------------------------------

class Worker:
    """One starter that stays: its process, and a thread that passes on
    what it says (a pipe cannot be waited for with a limit on Windows)."""

    def __init__(self, index: int, home: Path, logs: Path, answers: "queue.Queue[tuple[int, str | None]]") -> None:
        self.index = index
        self.log = logs / f"worker-{index}.err"
        self.errors = open(self.log, "wb")
        self.process = subprocess.Popen(
            [sys.executable, "-B", str(CHILD), str(home)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
            env=support.child_environment(), cwd=str(support.TESTS),
        )
        self.thread = threading.Thread(target=self._listen, args=(answers,), daemon=True)
        self.thread.start()

    def _listen(self, answers: "queue.Queue[tuple[int, str | None]]") -> None:
        for raw in self.process.stdout:
            answers.put((self.index, raw.decode("utf-8", "replace").strip()))
        answers.put((self.index, None))  # it ended

    def ask(self, asked: dict) -> None:
        self.process.stdin.write((json.dumps(asked) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def end(self) -> str:
        """Let it go, and what it wrote to its error stream."""
        try:
            self.process.stdin.write(b"\n")
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.thread.join(timeout=10)
        self.process.stdout.close()
        self.errors.close()
        return self.log.read_bytes().decode("utf-8", "replace")


class Race:
    """The rounds, and what they showed. Run once for the class of tests."""

    def __init__(self, top: Path, rounds: int, starters: int = STARTERS) -> None:
        self.top = top
        self.rounds = rounds
        self.home = top / "home"
        self.state = self.home.joinpath(*STATE)
        self.file = self.state / lock.LOCK_NAME
        self.witness = top / "witness" / "inside"
        self.logs = top / "logs"
        for directory in (self.home, self.witness.parent, self.logs):
            directory.mkdir(parents=True)
        self.answers: "queue.Queue[tuple[int, str | None]]" = queue.Queue()
        self.workers: list[Worker] = []
        self.starters = starters
        self.random = random.Random(20261006)
        self.gone = [ended_pid(), ended_pid()]
        self.seconds = 0.0
        # What the tests assert on: one line of evidence for each failure.
        self.broken: list[str] = []      # the harness itself did not work
        self.doubles: list[str] = []
        self.lost: list[str] = []
        self.errors: list[str] = []
        self.odd_refusals: list[str] = []
        self.clearings: list[str] = []
        self.leftovers: list[str] = []
        self.counts: dict[str, collections.Counter] = {name: collections.Counter() for name in VARIANTS}

    # --- One round ---------------------------------------------------------------

    def plant(self, variant: str) -> set[str]:
        """Prepare the home for a round; the names that may be there after it."""
        parts = variant.split("+")
        if parts[0] == "first-run":
            return set()
        self.state.mkdir(parents=True)
        after = {".agents"}
        if "record" in parts:
            (self.state / "manifest.json").write_bytes(RECORD)
            after |= {"/".join(STATE), "/".join(STATE) + "/manifest.json"}
        if parts[0] == "stale":
            mine = token()
            if "claim" in parts:
                # A run that claimed the right to clear this lock, and died.
                (self.state / f"{lock.CLAIM_PREFIX}{mine}").write_bytes(lock_bytes(self.gone[1]))
            self.file.write_bytes(lock_bytes(self.gone[0], token=mine))
        return after

    def one(self, number: int, variant: str) -> bool:
        """Run a round and note what it showed. False when the workers no
        longer answer and no further round can be run."""
        where = f"round {number} ({variant})"
        after = self.plant(variant)
        jitter = JITTER if number % 2 else 0.0
        at = time.time() + LEAD
        for worker in self.workers:
            worker.ask({"at": at + self.random.random() * jitter, "witness": str(self.witness)})
        said: dict[int, dict] = {}
        while len(said) < len(self.workers):
            try:
                index, line = self.answers.get(timeout=PATIENCE)
            except queue.Empty:
                missing = sorted(set(range(len(self.workers))) - set(said))
                self.broken.append(f"{where}: workers {missing} gave no answer in {PATIENCE} s (a hang); the others: {self.brief(said)}")
                return False
            if line is None:
                self.broken.append(f"{where}: worker {index} ended; the others: {self.brief(said)}")
                return False
            try:
                said[index] = json.loads(line)
            except ValueError:
                self.broken.append(f"{where}: worker {index} said {line[:300]!r}")
                return False
        self.judge(where, variant, said, after)
        shutil.rmtree(self.home)
        self.home.mkdir()
        if os.path.lexists(self.witness):
            os.rmdir(self.witness)
        return True

    def brief(self, said: dict[int, dict]) -> str:
        """The outcomes of a round, for a failure message."""
        parts = []
        for index in sorted(said):
            one = said[index]
            text = one["outcome"]
            if one["outcome"] == "held":
                text += f"[{one.get('entered', 0):.6f}..{one.get('left', 0):.6f}{' DOUBLE' if one.get('double') else ''}]"
            elif one.get("lines"):
                text += f"[{self.words(one['lines'][0], 9)}]"
            elif one.get("text"):
                text += f"[{one['text'][:200]}]"
            parts.append(f"{index}:{text}")
        return "; ".join(parts)

    def words(self, line: str, count: int = 7) -> str:
        """The first words of a refusal, without the path it starts with."""
        prefix = f"{self.file}: "
        return " ".join((line[len(prefix):] if line.startswith(prefix) else line).split()[:count])

    def judge(self, where: str, variant: str, said: dict[int, dict], after: set[str]) -> None:
        counts = self.counts[variant]
        counts["rounds"] += 1
        holders = [one for one in said.values() if one["outcome"] == "held"]
        counts["holders"] += len(holders)
        counts[f"rounds with {min(len(holders), 3)}{'+' if len(holders) > 2 else ''} holder(s), one after another"] += 1
        # Two inside at one moment: the witness says so. The clocks are
        # counted and not asserted on: a clock that is set back in the
        # middle of a round would show two holders where there was one.
        spans = sorted((one["entered"], one["left"]) for one in holders)
        if any(later[0] < earlier[1] for earlier, later in zip(spans, spans[1:])):
            counts["rounds where the clocks overlap"] += 1
        if any(one.get("double") for one in said.values()) or os.path.lexists(self.witness):
            self.doubles.append(f"{where}: DOUBLE HOLDER: {self.brief(said)}")
        if not holders:
            self.lost.append(f"{where}: no run held the lock: {self.brief(said)}")
        cleared = 0
        for index, one in sorted(said.items()):
            if one.get("witness"):
                self.doubles.append(f"{where}: worker {index} could not remove its witness: {one['witness']}")
            if one["outcome"] == "held":
                cleared += sum("cleared the lock" in note for note in one.get("notes", []))
                # ``.agents`` is setup's to list only where setup made it.
                if lock.AGENTS in one.get("created", []) and variant != "first-run":
                    self.errors.append(f"{where}: worker {index} takes .agents for setup's: {one['created']}")
            elif one["outcome"] == "lockheld":
                lines = one.get("lines", [])
                kind = self.words(lines[0]) if lines else "(no line)"
                counts[f"LockHeld: {kind}"] += 1
                if len(lines) != 1 or not any(known in lines[0] for known in (WRITING, CLEARING, TAKING)):
                    self.odd_refusals.append(f"{where}: worker {index}: {lines}")
                elif "nothing was changed" not in lines[0] or not lines[0].startswith(f"{self.file}: "):
                    self.odd_refusals.append(f"{where}: worker {index}: {lines}")
            else:
                lines = one.get("lines") or [one.get("text", "")]
                counts[f"{one['outcome']}: {self.words(lines[0].replace(str(self.home), '<home>'), 12)}"] += 1
                self.errors.append(f"{where}: worker {index}: {one['outcome']}: {one.get('lines') or one.get('text')}")
        if variant.startswith("stale"):
            # The run that cleared the stale lock may lose the race for the
            # free one, and a run that is refused has nobody to tell: so a
            # holder that says it cleared the lock is seen in most rounds,
            # not in all, and two that say so are never seen.
            counts[f"rounds where {cleared} holder(s) cleared the stale lock"] += 1
            if cleared > 1:
                self.clearings.append(f"{where}: {cleared} runs say they cleared the stale lock: {self.brief(said)}")
        elif cleared:
            self.clearings.append(f"{where}: a run says it cleared a lock where none was: {self.brief(said)}")
        # What is left.
        left = names_below(self.home)
        if left != after:
            counts["rounds with something left"] += 1
            self.leftovers.append(
                f"{where}: left {sorted(left - after)}, missing {sorted(after - left)}: {self.brief(said)}"
            )
        elif "record" in variant.split("+") and (self.state / "manifest.json").read_bytes() != RECORD:
            self.leftovers.append(f"{where}: the record was changed")

    # --- All of them ---------------------------------------------------------------

    def run(self) -> None:
        started = time.monotonic()
        try:
            self.workers = [Worker(index, self.home, self.logs, self.answers) for index in range(self.starters)]
            ready = 0
            while ready < self.starters:
                try:
                    index, line = self.answers.get(timeout=PATIENCE)
                except queue.Empty:
                    self.broken.append("the workers did not start")
                    return
                if line != "ready":
                    self.broken.append(f"worker {index} did not start: {line!r}")
                    return
                ready += 1
            for number in range(self.rounds):
                if not self.one(number, VARIANTS[number % len(VARIANTS)]):
                    break
        finally:
            for worker in self.workers:
                text = worker.end()
                if text.strip():
                    self.errors.append(f"worker {worker.index} wrote to its error stream: {text[-800:]}")
            self.seconds = time.monotonic() - started

    def report(self) -> str:
        lines = [f"lock race: {sum(count['rounds'] for count in self.counts.values())} rounds, {self.starters} starters, {self.seconds:.1f} s"]
        for variant in VARIANTS:
            counts = self.counts[variant]
            rest = ", ".join(f"{name}: {counts[name]}" for name in sorted(counts) if name != "rounds")
            lines.append(f"  {variant}: {counts['rounds']} rounds; {rest}")
        for name in ("broken", "doubles", "lost", "errors", "odd_refusals", "clearings", "leftovers"):
            lines.append(f"  {name}: {len(getattr(self, name))}")
        return "\n".join(lines)


def evidence(found: list[str], rounds: int) -> str:
    return f"{len(found)} in {rounds} rounds, the first of them:\n" + "\n".join(found[:5])


class RaceTests(unittest.TestCase):
    race: Race

    @classmethod
    def setUpClass(cls) -> None:
        scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(scratch.cleanup)
        cls.race = Race(Path(scratch.name).resolve(), ROUNDS)
        cls.race.run()
        if FULL:
            print("\n" + cls.race.report(), file=sys.stderr)

    def test_the_rounds_were_run(self) -> None:
        self.assertEqual(self.race.broken, [])
        ran = {variant: counts["rounds"] for variant, counts in self.race.counts.items()}
        self.assertEqual(sum(ran.values()), ROUNDS)
        self.assertGreaterEqual(min(ran.values()), ROUNDS // len(VARIANTS))
        # The race is real: most starters are turned away.
        holders = sum(counts["holders"] for counts in self.race.counts.values())
        self.assertLess(holders, ROUNDS * STARTERS // 2)

    def test_no_two_runs_hold_the_lock_at_once(self) -> None:
        self.assertEqual(self.race.doubles, [], evidence(self.race.doubles, ROUNDS))

    def test_some_run_holds_the_lock_in_every_round(self) -> None:
        self.assertEqual(self.race.lost, [], evidence(self.race.lost, ROUNDS))

    def test_a_run_ends_holding_the_lock_or_refused_and_no_other_way(self) -> None:
        self.assertEqual(self.race.errors, [], evidence(self.race.errors, ROUNDS))

    def test_a_refusal_is_one_line_that_a_race_can_give(self) -> None:
        self.assertEqual(self.race.odd_refusals, [], evidence(self.race.odd_refusals, ROUNDS))

    def test_a_stale_lock_is_cleared_by_one_run_and_no_free_one_is(self) -> None:
        self.assertEqual(self.race.clearings, [], evidence(self.race.clearings, ROUNDS))

    def test_nothing_is_left_after_a_round(self) -> None:
        self.assertEqual(self.race.leftovers, [], evidence(self.race.leftovers, ROUNDS))


# --- In one process ------------------------------------------------------------

class HomeCase(unittest.TestCase):
    """A scratch home with a state directory, and beside it a place that is
    not in the home."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.top = Path(scratch.name).resolve()
        self.home = self.top / "home"
        self.state = self.home.joinpath(*STATE)
        self.state.mkdir(parents=True)
        self.file = self.state / lock.LOCK_NAME
        self.roots = Roots(self.home)
        self.addCleanup(lock._HELD.clear)

    def record(self) -> None:
        (self.state / "manifest.json").write_bytes(RECORD)

    def claims(self) -> list[str]:
        return sorted(name for name in os.listdir(self.state) if name.startswith(lock.CLAIM_PREFIX))

    def leavings(self) -> list[str]:
        """What a lock may leave in the state directory and must not."""
        return sorted(
            name for name in os.listdir(self.state)
            if name == lock.LOCK_NAME or name.startswith(lock.CLAIM_PREFIX) or name.startswith(fsio.TEMP_PREFIX)
        )


class Starter(threading.Thread):
    """A starter in a thread of its own: it holds the lock for as long as
    ``leave`` is not set, and keeps how it ended."""

    def __init__(self, roots: Roots) -> None:
        super().__init__(daemon=True)
        self.roots = roots
        self.inside = threading.Event()
        self.leave = threading.Event()
        self.ended: object = None
        self.notes: list[str] = []
        self.held_bytes: bytes | None = None

    def run(self) -> None:
        try:
            with lock.held(self.roots) as mine:
                self.notes = list(mine.notes)
                self.held_bytes = lock.lock_file(self.roots).read_bytes()
                self.inside.set()
                self.leave.wait(PATIENCE)
            self.ended = "held"
        except BaseException as exc:  # noqa: BLE001  (the test looks at it)
            self.ended = exc


class InterleavingTests(HomeCase):
    def setUp(self) -> None:
        super().setUp()
        self.record()
        self.stale = lock_bytes(ended_pid())
        self.file.write_bytes(self.stale)
        self.slow = Starter(self.roots)
        self.addCleanup(self._let_go)
        self.stopped = threading.Event()   # the slow starter is where the test wants it
        self.resume = threading.Event()

    def _let_go(self) -> None:
        self.resume.set()
        self.slow.leave.set()
        if self.slow.is_alive():
            self.slow.join(PATIENCE)

    def stop_after_the_verdict(self) -> mock._patch:
        """The slow starter stops once it has judged the stale lock."""
        real, judged = lock.verdict, []

        def verdict(holder):
            found = real(holder)
            if threading.current_thread() is self.slow and not self.stopped.is_set():
                judged.append(found[0])
                self.stopped.set()
                self.resume.wait(PATIENCE)
            return found

        self.judged = judged
        return mock.patch.object(lock, "verdict", verdict)

    def start_slow(self) -> None:
        self.slow.start()
        self.assertTrue(self.stopped.wait(PATIENCE), "the slow starter never got there")

    def finish_slow(self) -> None:
        self.resume.set()
        self.slow.join(PATIENCE)
        self.assertFalse(self.slow.is_alive(), "the slow starter did not end")

    def assert_refused_by_a_holder(self) -> None:
        self.assertIsInstance(self.slow.ended, lock.LockHeld, self.slow.ended)
        self.assertEqual(len(self.slow.ended.lines), 1)
        line = self.slow.ended.lines[0]
        self.assertTrue(line.startswith(f"{self.file}: "), line)
        self.assertIn(WRITING, line)
        self.assertIn("nothing was changed", line)

    def test_a_starter_that_judged_a_stale_lock_does_not_remove_the_lock_taken_since(self) -> None:
        """Finding 9: A judges the stale lock gone; B clears it and takes
        the lock; A goes on. A must not take B's lock away."""
        with self.stop_after_the_verdict():
            self.start_slow()
            self.assertEqual(self.judged, [lock.GONE])
            self.assertEqual(self.file.read_bytes(), self.stale)
            with lock.held(self.roots) as fast:
                self.assertTrue(any("cleared the lock" in note for note in fast.notes), fast.notes)
                live = self.file.read_bytes()
                number = os.stat(self.file).st_ino
                self.assertNotEqual(live, self.stale)
                self.finish_slow()
                self.assert_refused_by_a_holder()
                # B still holds it: the very file, with B's bytes.
                self.assertEqual(self.file.read_bytes(), live)
                self.assertEqual(os.stat(self.file).st_ino, number)
                self.assertEqual(live, fast._bytes)
                self.assertTrue(fast.taken)
                self.assertEqual(self.claims(), [])
            self.assertEqual(self.slow.notes, [])
        self.assertEqual(self.leavings(), [])
        self.assertEqual((self.state / "manifest.json").read_bytes(), RECORD)

    def test_nor_the_lock_of_a_third_run_after_the_second_gave_its_own_back(self) -> None:
        """A judges; B clears, takes and gives back; C takes; A goes on."""
        with self.stop_after_the_verdict():
            self.start_slow()
            with lock.held(self.roots) as second:
                self.assertTrue(any("cleared the lock" in note for note in second.notes))
            self.assertFalse(self.file.exists())
            with lock.held(self.roots) as third:
                self.assertEqual(third.notes, [])
                live = self.file.read_bytes()
                self.finish_slow()
                self.assert_refused_by_a_holder()
                self.assertEqual(self.file.read_bytes(), live)
                self.assertEqual(self.claims(), [])
        self.assertEqual(self.leavings(), [])

    def test_a_starter_that_judged_a_lock_cleared_since_takes_the_free_lock(self) -> None:
        """A judges; B clears, takes and gives back; A goes on, finds
        nothing to clear, and takes the lock as any run would."""
        with self.stop_after_the_verdict():
            self.start_slow()
            with lock.held(self.roots):
                pass
            self.resume.set()
            self.assertTrue(self.slow.inside.wait(PATIENCE), self.slow.ended)
            self.assertEqual(self.slow.notes, [])  # it cleared nothing, and says nothing
            self.assertEqual(self.file.read_bytes(), self.slow.held_bytes)
            self.assertEqual(self.claims(), [])
            self.slow.leave.set()
            self.slow.join(PATIENCE)
        self.assertEqual(self.slow.ended, "held")
        self.assertEqual(self.leavings(), [])

    def test_a_starter_that_finds_a_claim_it_did_not_make_backs_off(self) -> None:
        """A has claimed the right to clear and has not cleared yet; B
        comes. B is refused in one line and touches nothing; A goes on,
        clears, and takes the lock."""
        real, reads = lock.read, []

        def read(path):
            if threading.current_thread() is self.slow and Path(path) == self.file:
                reads.append(1)
                if len(reads) == 2:  # the look again, with the claim made
                    self.stopped.set()
                    self.resume.wait(PATIENCE)
            return real(path)

        with mock.patch.object(lock, "read", read):
            self.start_slow()
            claim = self.state / f"{lock.CLAIM_PREFIX}{json.loads(self.stale)['token']}"
            self.assertEqual(self.claims(), [claim.name])
            before = snapshot(self.top)
            started = time.monotonic()
            with self.assertRaises(lock.LockHeld) as caught:
                with lock.held(self.roots):
                    self.fail("two runs were let in")
            self.assertLess(time.monotonic() - started, PROMPT)
            self.assertEqual(len(caught.exception.lines), 1)
            line = caught.exception.lines[0]
            self.assertTrue(line.startswith(f"{self.file}: "), line)
            self.assertIn(CLEARING, line)
            self.assertIn("nothing was changed", line)
            self.assertIn("Run again", line)
            self.assertEqual(snapshot(self.top), before)  # the stale lock and the claim, as they were
            self.assertEqual(self.file.read_bytes(), self.stale)
            self.resume.set()
            self.assertTrue(self.slow.inside.wait(PATIENCE), self.slow.ended)
            self.assertTrue(any("cleared the lock" in note for note in self.slow.notes), self.slow.notes)
            self.assertEqual(self.file.read_bytes(), self.slow.held_bytes)
            self.assertEqual(self.claims(), [])
            self.slow.leave.set()
            self.slow.join(PATIENCE)
        self.assertEqual(self.slow.ended, "held")
        self.assertEqual(self.leavings(), [])


class VacatedTests(HomeCase):
    """A holder that saved no record takes the empty state directory away
    when it gives the lock back (and ``.agents`` where setup made it). A
    starter that is on its way to the lock at that moment finds the
    directory gone under it. That is a race it lost or may run again, not
    an error of the disk: it takes the lock on the next try, or is refused
    as ``LockHeld``. The race shows this in a round in a few hundred; here
    the moment is forced."""

    def test_the_state_directory_goes_and_comes_back_while_the_lock_is_written(self) -> None:
        real, calls = fsio.write_new, []

        def write_new(path, data):
            if Path(path) == self.file and not calls:
                calls.append(1)
                os.rmdir(self.state)  # the holder before gave back, and took the empty directory with it
                try:
                    return real(path, data)
                finally:
                    os.mkdir(self.state)  # and a third starter made it again
            return real(path, data)

        with mock.patch.object(fsio, "write_new", write_new):
            try:
                with lock.held(self.roots) as mine:
                    self.assertEqual(self.file.read_bytes(), mine._bytes)
            except lock.LockHeld:
                pass
        self.assertEqual(calls, [1])
        self.assertEqual(names_below(self.home), {".agents"})

    def test_agents_goes_while_the_state_directory_is_made(self) -> None:
        shutil.rmtree(self.home / ".agents")
        real, calls = lock.Lock._mkdir, []

        def make(mine, path):
            if Path(path) == self.state and not calls:
                calls.append(1)
                # The holder before gave back: ``.agents`` and the marker went.
                os.rmdir(self.home / ".agents")
                os.rmdir(self.home / lock.MARKER_NAME)
            return real(mine, path)

        with mock.patch.object(lock.Lock, "_mkdir", make):
            try:
                with lock.held(self.roots) as mine:
                    self.assertEqual(self.file.read_bytes(), mine._bytes)
                    self.assertEqual(mine.created, {lock.AGENTS, lock.STATE})
            except lock.LockHeld:
                pass
        self.assertEqual(calls, [1])
        self.assertEqual(names_below(self.home), set())


class OddPathTests(HomeCase):
    """Something else than a lock of a run on this system is at the lock's
    path. The run ends at once with one line that names the file and says
    what to do, and has changed nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.elsewhere = self.top / "elsewhere"
        self.elsewhere.mkdir()

    def refused(self, kind: type, *words: str, to_do: str = WHAT_TO_DO) -> str:
        """``lock.held`` ends with an error of exactly ``kind``; the line."""
        before = snapshot(self.top)
        started = time.monotonic()
        with self.assertRaises(SetupError) as caught:
            with lock.held(self.roots):
                self.fail("the lock was taken")
        self.assertLess(time.monotonic() - started, PROMPT)
        self.assertIs(type(caught.exception), kind, caught.exception)
        self.assertEqual(len(caught.exception.lines), 1, caught.exception.lines)
        line = caught.exception.lines[0]
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith(f"{self.file}: "), line)
        self.assertRegex(line, r"(?i)nothing was changed")
        self.assertRegex(line, to_do)
        for word in words:
            self.assertIn(word, line)
        self.assertEqual(snapshot(self.top), before)
        self.assertEqual(lock._HELD, {})
        return line

    def cannot_tell(self, raw: bytes, *words: str) -> None:
        """A lock that is not provably stale: it stays, byte for byte."""
        self.file.write_bytes(raw)
        self.refused(lock.LockHeld, "cannot tell", *words)
        self.assertEqual(self.file.read_bytes(), raw)

    def test_a_directory(self) -> None:
        self.file.mkdir()
        self.refused(SetupError, "is a directory, not a lock file of setup's")
        (self.file / "inside").write_bytes(b"x")
        self.refused(SetupError, "is a directory, not a lock file of setup's")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "this system has no FIFO")
    def test_a_fifo_is_not_opened(self) -> None:
        os.mkfifo(self.file)
        before = snapshot(self.top)
        said = run_once(self.home)  # in a process of its own: a FIFO that is opened waits for ever
        self.assertEqual(said["outcome"], "refused", said)
        self.assertEqual(len(said["lines"]), 1, said)
        line = said["lines"][0]
        self.assertTrue(line.startswith(f"{self.file}: "), line)
        self.assertIn("neither a file nor a directory", line)
        self.assertIn("not a lock file of setup's", line)
        self.assertIn("nothing was changed", line)
        self.assertRegex(line, WHAT_TO_DO)
        self.assertEqual(snapshot(self.top), before)
        # And in this process, which the first run showed does not wait.
        self.refused(SetupError, "neither a file nor a directory")

    @unittest.skipUnless(support.can_lock_directories(), "permission bits keep this process out of nothing")
    def test_a_file_nobody_may_read(self) -> None:
        self.file.write_bytes(lock_bytes(ended_pid()))
        os.chmod(self.file, 0)
        self.addCleanup(os.chmod, self.file, 0o600)
        self.refused(SetupError, "the lock file cannot be read")

    def link(self, target: Path) -> None:
        try:
            os.symlink(target, self.file)
        except (OSError, NotImplementedError, AttributeError) as exc:
            self.skipTest(f"no link can be made here: {exc}")

    def test_a_link_to_nothing(self) -> None:
        self.link(self.elsewhere / "nothing")
        self.refused(SetupError, "is a link (to ", "not a lock file of setup's")
        self.assertFalse(os.path.lexists(self.elsewhere / "nothing"))

    def test_a_link_to_a_file_elsewhere(self) -> None:
        # Even a lock that could be cleared is not looked at through a link.
        other = self.elsewhere / "lock"
        raw = lock_bytes(ended_pid())
        other.write_bytes(raw)
        self.link(other)
        self.refused(SetupError, "is a link (to ", "not a lock file of setup's")
        self.assertEqual(other.read_bytes(), raw)
        self.assertTrue(os.path.islink(self.file))

    def test_a_file_that_names_no_run(self) -> None:
        for name, raw in (
            ("empty", b""),
            ("200,000 brackets", b"[" * 200_000),
            ("a list", b'[{"pid": 1, "token": "0123456789abcdef"}]\n'),
            ("a number", b"7\n"),
            ("not text", b"\xff\xfe\x00{"),
        ):
            with self.subTest(name):
                self.cannot_tell(raw, "does not say who took it", "a run the lock file does not name")

    def test_a_lock_taken_on_another_system(self) -> None:
        mine = lock.identity()
        other = "linux" if sys.platform == "win32" else "win32"
        for name, identity, words in (
            ("host", {**mine, "host": "another-machine"}, "another system (host another-machine"),
            ("system", {**mine, "system": other}, f"another system (system {other}"),
            ("system only", {"system": other, "host": mine["host"]}, f"another system (system {other}"),
        ):
            with self.subTest(name):
                # The process is gone here, and that says nothing about there.
                self.cannot_tell(lock_bytes(ended_pid(), identity=identity), words, "on any system that uses it")

    def test_a_lock_that_names_process_1(self) -> None:
        exists, start = lock.process(1)
        if exists and start is not None:
            # Process 1 runs, and started when the lock says: it is the holder.
            raw = lock_bytes(1, start=start)
            self.file.write_bytes(raw)
            line = self.refused(lock.LockHeld, WRITING, "process 1 ", to_do="Wait for it to end and run again")
            self.assertNotIn("cannot tell", line)
            self.assertEqual(self.file.read_bytes(), raw)
            wrong = str(int(start) + 1)
        elif exists:
            # No start to compare: a process of that id runs, so the lock stays.
            raw = lock_bytes(1, start="1")
            self.file.write_bytes(raw)
            self.refused(lock.LockHeld, WRITING, "process 1 ", to_do="Wait for it to end and run again")
            self.assertEqual(self.file.read_bytes(), raw)
            return
        else:
            if exists is None:
                self.skipTest("this system does not say whether process 1 runs")
            wrong = "1"
        # The id with another start (or no such process): the run that took
        # the lock is gone, the lock is cleared, and that is said.
        self.record()
        self.file.write_bytes(lock_bytes(1, start=wrong))
        started = time.monotonic()
        with lock.held(self.roots) as mine:
            self.assertLess(time.monotonic() - started, PROMPT)
            self.assertEqual(len(mine.notes), 1, mine.notes)
            self.assertIn("cleared the lock", mine.notes[0])
            self.assertIn("process 1 ", mine.notes[0])
            self.assertEqual(self.file.read_bytes(), mine._bytes)
        self.assertEqual(names_below(self.home), {".agents", "/".join(STATE), "/".join(STATE) + "/manifest.json"})

    def test_a_list_of_directories_in_a_lock_is_not_believed(self) -> None:
        """The state directory is in a ``.agents`` of the user's own, with
        nothing else in it, and the stale lock says setup made both and
        more. The lock is cleared, the run saves no record: the state
        directory goes, as setup's by its name, and ``.agents`` stays."""
        outside = self.top / "x"
        outside.mkdir()
        self.assertEqual(os.listdir(self.home / ".agents"), ["workflow-setup"])
        self.file.write_bytes(lock_bytes(ended_pid(), created=["agents", "state", "/etc", "../../x"]))
        before = snapshot(self.top)
        with lock.held(self.roots) as mine:
            self.assertTrue(any("cleared the lock" in note for note in mine.notes), mine.notes)
            self.assertEqual(mine.created, {lock.STATE})
            self.assertEqual(mine.created_paths(), [self.state])
        self.assertTrue((self.home / ".agents").is_dir(), "the user's own .agents was removed")
        self.assertEqual(names_below(self.home), {".agents"})
        self.assertFalse(os.path.lexists(self.home / lock.MARKER_NAME))
        after = snapshot(self.top)
        self.assertEqual(
            {name: seen for name, seen in before.items() if not name.startswith("home/.agents/")}, after,
        )
        # The same with a record beside the lock: nothing goes at all.
        self.state.mkdir()
        self.record()
        self.file.write_bytes(lock_bytes(ended_pid(), created=["agents", "state", "/etc", "../../x"]))
        with lock.held(self.roots) as mine:
            self.assertEqual(mine.created, set())
        self.assertEqual(names_below(self.home), {".agents", "/".join(STATE), "/".join(STATE) + "/manifest.json"})
        self.assertTrue(outside.is_dir())


class ProjectTests(unittest.TestCase):
    """The same lock for a project, in the project's own state directory:
    it is another lock than the home's, and one lock for every home."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.top = Path(scratch.name).resolve()
        self.home, self.other_home, self.project = self.top / "home", self.top / "other-home", self.top / "project"
        for directory in (self.home, self.other_home, self.project):
            directory.mkdir()
        self.roots = Roots(self.home, self.project)
        self.home_lock = self.home.joinpath(*STATE, lock.LOCK_NAME)
        self.project_lock = self.project.joinpath(*STATE, lock.LOCK_NAME)
        self.witness = self.top / "witness"
        self.addCleanup(lock._HELD.clear)

    def test_where_the_two_locks_are(self) -> None:
        self.assertEqual(lock.lock_file(self.roots), self.home_lock)
        self.assertEqual(lock.lock_file(self.roots, True), self.project_lock)

    def test_the_homes_lock_does_not_hold_up_the_projects(self) -> None:
        with lock.held(self.roots) as mine:
            self.assertTrue(self.home_lock.is_file())
            self.assertFalse(os.path.lexists(self.project / ".agents"))
            # Another process, of the same home: the project's lock is free,
            # and the home's is not.
            said = run_once(self.home, "project", self.project)
            self.assertEqual(said["outcome"], "held", said)
            self.assertEqual(said["created"], [lock.AGENTS, lock.STATE])
            said = run_once(self.home, "home", self.project)
            self.assertEqual(said["outcome"], "lockheld", said)
            self.assertIn(f"{WRITING} home (process {os.getpid()} ", said["lines"][0])
            # And in this process the two are two locks, held together.
            with lock.held(self.roots, project=True) as other:
                self.assertIsNot(other, mine)
                self.assertTrue(other.project)
                self.assertTrue(self.project_lock.is_file())
                self.assertTrue(self.home_lock.is_file())
                self.assertNotEqual(self.project_lock.read_bytes(), self.home_lock.read_bytes())
            self.assertFalse(os.path.lexists(self.project_lock))
            self.assertEqual(self.home_lock.read_bytes(), mine._bytes)
        self.assertEqual(names_below(self.top), {"home", "other-home", "project"})

    def test_the_projects_lock_does_not_hold_up_the_homes(self) -> None:
        with lock.held(self.roots, project=True) as mine:
            self.assertTrue(self.project_lock.is_file())
            # A run that writes to a project only makes nothing in the home.
            self.assertEqual(os.listdir(self.home), [])
            said = run_once(self.home, "home", self.project)
            self.assertEqual(said["outcome"], "held", said)
            said = run_once(self.home, "project", self.project)
            self.assertEqual(said["outcome"], "lockheld", said)
            self.assertTrue(said["lines"][0].startswith(f"{self.project_lock}: "), said)
            self.assertIn(f"{WRITING} project (process {os.getpid()} ", said["lines"][0])
            with lock.held(self.roots) as other:
                self.assertIsNot(other, mine)
                self.assertTrue(self.home_lock.is_file())
            self.assertEqual(self.project_lock.read_bytes(), mine._bytes)
        self.assertEqual(names_below(self.top), {"home", "other-home", "project"})

    def test_two_homes_that_use_one_project_share_its_lock(self) -> None:
        with lock.held(self.roots, project=True) as mine:
            before = snapshot(self.top)
            said = run_once(self.other_home, "project", self.project, self.witness)
            self.assertEqual(said["outcome"], "lockheld", said)
            self.assertEqual(len(said["lines"]), 1)
            self.assertTrue(said["lines"][0].startswith(f"{self.project_lock}: "), said)
            self.assertIn(f"{WRITING} project (process {os.getpid()} ", said["lines"][0])
            self.assertIn("nothing was changed", said["lines"][0])
            self.assertEqual(snapshot(self.top), before)
            self.assertEqual(self.project_lock.read_bytes(), mine._bytes)
            # Its own home's lock is another matter.
            self.assertEqual(run_once(self.other_home, "home", self.project)["outcome"], "held")
        # Given back, it is the other home's to take; and the reverse.
        self.assertEqual(run_once(self.other_home, "project", self.project, self.witness)["outcome"], "held")
        with lock.held(Roots(self.other_home, self.project), project=True):
            said = run_once(self.home, "project", self.project, self.witness)
            self.assertEqual(said["outcome"], "lockheld", said)
            self.assertIn(f"{WRITING} project", said["lines"][0])
        self.assertEqual(names_below(self.top), {"home", "other-home", "project"})

    def test_two_homes_race_for_the_lock_of_one_project(self) -> None:
        """Starters from two homes at the lock of one project, started
        together again and again: never two inside."""
        rounds, each = (40, 3) if FULL else (10, 3)
        double, nobody, other = [], [], []
        for number in range(rounds):
            argv = [
                [sys.executable, "-B", str(CHILD), str(home), "once", "project", str(self.project), str(self.witness)]
                for home in (self.home, self.other_home) for _ in range(each)
            ]
            children = [
                subprocess.Popen(
                    one, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=support.child_environment(), cwd=str(support.TESTS),
                )
                for one in argv
            ]
            said = []
            for child in children:
                try:
                    out, err = child.communicate(timeout=PATIENCE)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.communicate()
                    other.append(f"round {number}: a starter did not end")
                    continue
                if child.returncode != 0 or err.strip():
                    other.append(f"round {number}: exit {child.returncode}: {err.decode('utf-8', 'replace')[-400:]}")
                    continue
                said.append(json.loads(out.decode("utf-8").splitlines()[-1]))
            outcomes = [one["outcome"] for one in said]
            if any(one.get("double") for one in said) or os.path.lexists(self.witness):
                double.append(f"round {number}: {outcomes}")
            if "held" not in outcomes:
                nobody.append(f"round {number}: {said}")
            other.extend(f"round {number}: {one}" for one in said if one["outcome"] not in ("held", "lockheld"))
            if names_below(self.top) != {"home", "other-home", "project"}:
                other.append(f"round {number}: left {sorted(names_below(self.top))}")
                for directory in (self.home, self.other_home, self.project):
                    shutil.rmtree(directory)
                    directory.mkdir()
        self.assertEqual(double, [])
        self.assertEqual(nobody, [])
        self.assertEqual(other, [])


if __name__ == "__main__":
    unittest.main()
