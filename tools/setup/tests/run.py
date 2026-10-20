"""Run the setup tests in parallel processes. Standard library only.

    python -B tools/setup/tests/run.py                 every test, one process per CPU
    python -B tools/setup/tests/run.py -j 8 test_render test_entry
    python -B tools/setup/tests/run.py --by class      one unit per test class

Each unit, a test or with ``--by class`` a class, runs in a worker process of
its own, with its own scratch state, so the suite's wall time is that of its
slowest test. The summary is unittest's: each failure and error with its
traceback, then the counts and the wall time. Exit status 1 when a test
fails or errs, 0 otherwise. ``python -B -m unittest discover -s
tools/setup/tests`` still runs the same tests one after another.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import io
import os
import sys
import time
import traceback
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[2]


def _ready() -> None:
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    os.chdir(ROOT)


def _walk(suite: unittest.TestSuite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _walk(test)
        else:
            yield test


def _units(names: set[str], by: str) -> tuple[list[str], list[tuple[str, str]]]:
    _ready()
    suite = unittest.TestLoader().discover(str(TESTS), top_level_dir=str(TESTS))
    units: list[str] = []
    broken: list[tuple[str, str]] = []
    seen: set[str] = set()
    for test in _walk(suite):
        kind = type(test)
        if kind.__name__ == "_FailedTest":
            broken.append((test.id(), str(getattr(test, "_exception", "could not be loaded"))))
            continue
        if names and kind.__module__ not in names:
            continue
        unit = f"{kind.__module__}.{kind.__name__}"
        if by == "test":
            unit += f".{test._testMethodName}"
        if unit not in seen:
            seen.add(unit)
            units.append(unit)
    return units, broken


def _run(unit: str) -> tuple[str, int, list[tuple[str, str]], int, float]:
    _ready()
    start = time.perf_counter()
    try:
        suite = unittest.TestLoader().loadTestsFromName(unit)
    except Exception:
        return unit, 0, [(unit, traceback.format_exc())], 0, time.perf_counter() - start
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    problems = [(str(test), text) for test, text in result.failures + result.errors]
    return unit, result.testsRun, problems, len(result.skipped), time.perf_counter() - start


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the setup tests in parallel processes.")
    parser.add_argument("names", nargs="*", help="test modules to run, such as test_render; all of them by default")
    parser.add_argument("-j", type=int, default=os.cpu_count() or 4, help="worker processes (default: the CPUs)")
    parser.add_argument("--by", choices=("test", "class"), default="test", help="what one worker runs at a time")
    parser.add_argument("--slowest", type=int, default=0, help="print the N slowest units")
    args = parser.parse_args()
    units, problems = _units(set(args.names), args.by)
    unknown = set(args.names) - {unit.split(".")[0] for unit in units}
    if unknown:
        print("no such test module:", ", ".join(sorted(unknown)), file=sys.stderr)
        return 2
    start = time.perf_counter()
    ran = skipped = 0
    timings: list[tuple[float, str]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.j, initializer=_ready) as pool:
        for unit, count, bad, skips, seconds in pool.map(_run, units, chunksize=1):
            ran += count
            skipped += skips
            problems += bad
            timings.append((seconds, unit))
    for name, text in problems:
        print("=" * 70)
        print(name)
        print("-" * 70)
        print(text.rstrip())
    for seconds, unit in sorted(timings, reverse=True)[: args.slowest]:
        print(f"{seconds:7.1f}s  {unit}")
    wall = time.perf_counter() - start
    print(f"Ran {ran} tests in {wall:.1f}s across {args.j} processes")
    skipped_note = f" (skipped={skipped})" if skipped else ""
    print(("OK" if not problems else f"FAILED (problems={len(problems)})") + skipped_note)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
