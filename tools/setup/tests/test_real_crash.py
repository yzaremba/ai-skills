"""The real commands, killed after every change they make to the disk.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests -p 'test_real_crash.py'

``test_crash`` stops a plan made by hand, inside this process. Here the
commands themselves are stopped: each is a child process of the tool's own
script, started with ``fsio.STOP_VARIABLE`` set to N, which ends itself
(``os._exit``, no handler and no ``finally``, as after a kill) right after
its N-th change to the disk. See ``real_crash_support`` for the clone the
children run from, the worlds, and the environment of a child.

The scenarios (``real_crash_support.SCENARIOS``), each on a home and a
project that already hold a user's files (a ``CLAUDE.md`` with the v1
import lines and no final line ending, a ``settings.json``, an
``AGENTS.md`` with another tool's block, a ``config.toml``, a project with
a ``.gitignore`` without a final line ending, a ``settings.json`` and a
``.codex/config.toml``; on POSIX with permission bits that are not the
usual ones):

    1  init --yes --user
    2  init --yes --project P --manager-default, and
       init --yes --user --rewrite-settings over a hand-written settings file
    3  render (with roles)
    4  render --migrate-v1 --remove-stale <a hand-edited v1 skill copy>, on a
       home with what "This machine (L1)" of the sprint's PLAN had: v1 rule
       copies, a whole v1 skill copy, a hand-edited one with the user's own
       files in it, a link of the user's to another copy, the old agent
       file, a copy in the Codex home's skills/
    5  the same with --follow-config-symlinks, where the home's skills
       directory is a link to a directory inside the same home
    6  render --project P, after init --project
    7  render --apply-codex-settings --worktree-root ~/wt
    8  uninstall --project P, after a full install
    9  uninstall, after a full install
    10 render, after Codex wrote into the Codex profile (trust answers and a
       flag of its interface) and a setting changed the profile's text
    11 uninstall, after Codex wrote into the profile: setup's part is taken
       out and what Codex added is left
    12 render, where an uninstall left what Codex added alone in the profile:
       setup's text is written before it
    13 render --no-roles, after Codex wrote into the profile

For a scenario and a point N: the starting tree is put back from a
template, the command is stopped after its N-th change, and then one of
three things follows: the same command again; ``uninstall`` (of the project,
then of the home); another writing command. Then always the whole way back:
``uninstall --project P`` and ``uninstall`` (with
``--follow-config-symlinks`` in scenario 5). What is held:

    - no command prints a traceback, the stopped one neither; every command
      after the stop ends with 0. No scenario has a point at which an entry
      is rightly kept, so 3 is a failure everywhere;
    - right after the stop, every path of the user's tree is as the scenario
      started with it, or as the completed command leaves it, or is kept by
      a record: a file with its bytes in a backup the record lists, a link
      or a directory that is being replaced (and is at that moment not
      there) by an entry or a pending change that names it, a link with its
      text. And, stricter for a file: wherever the bytes the user had are
      not in the file at that moment, they are in a listed backup, also
      when the completed command would have removed the file;
    - the same command, run again, leaves what it leaves when nothing stops
      it (setup's own state aside: a stamp and a token differ);
    - at the end the tree is the one before setup ever ran, exactly: every
      path, every link's text, every byte, on POSIX every permission bit;
      so no ``.wfsetup-*`` name, no directory setup made, no state directory.
      In scenarios 10 to 13 one more file is there: the profile, holding
      what Codex added and nothing else; and right after the stop what
      Codex added is in the profile or in a backup a record lists;
    - the clone the children ran from is as it was.

The other writing command
    ``render`` after a stopped ``init`` (of the project after a project's),
    ``init --yes --user`` after a stopped ``render`` (``init --project``
    after the migration of scenario 4: a run in the project while the home's
    is unfinished). On a home that holds v1 copies a plain ``render`` is
    rightly refused (exit 2, the copies are in its way), before the
    migration and again once a stopped ``uninstall`` has put some of them
    back; so after the stopped ``uninstall`` of scenario 9 the other command
    is the render that installed that home, ``render --migrate-v1
    --remove-stale ...``.

How much is run
    The points of a command are counted by narrowing on "does a run with N
    still stop"; every N up to the count is then run and must stop, and
    N + 1 must complete, with the exit code and the tree of a run that
    nothing stops.

    On Linux, by default, a sample that keeps the whole suite within a few
    minutes: "the same command" at every second point of every scenario
    (and the last two); "uninstall" and "another command" at every 15th
    point and at the first and last two. With the environment variable
    ``WFSETUP_TEST_FULL=1``: all three at every point of every scenario,
    which is the form to run after any change to the write path:

        WFSETUP_TEST_FULL=1 python -B -m unittest discover -s tools/setup/tests -p test_real_crash.py

    Under the Windows Python, by default: all three at every 7th point (and
    the last) of scenarios 1, 3, 6 and 9. With ``WFSETUP_TEST_FULL=1``: as on
    Linux. Scenario 5 is skipped where a symlink cannot be made.

    The points of a scenario run side by side in a few worker threads
    (``real_crash_support.WORKERS``), each with a world of its own; the
    children are processes. The default run starts about 2,500 of them and
    takes a few minutes; how many depends on the machine more than on the
    number of threads.
    ``WFSETUP_TEST_REPORT=FILE`` adds one JSON line per scenario to FILE:
    its counts and every failure with the output of each command.
"""
from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import support
from fileops_support import SYMLINKS
from real_crash_support import (
    FULL, SCENARIOS, WINDOWS, WINDOWS_SAMPLE, World, build, install, run_scenario, without_state,
)
from test_uninstall import UninstallCase, picture
from wfsetup import fsio


class RealCase(UninstallCase):
    """The fixture clone with the tool in it, and nothing in this process
    that a child could not see: the children read no patch."""

    def setUp(self) -> None:
        super().setUp()
        # Set for the tests themselves, it would end this process at the
        # first link a test makes.
        self.assertNotIn(fsio.STOP_VARIABLE, os.environ, "the stop is for a child of these tests, never for them")
        self.script = install(self)
        self.worlds = self.root / "worlds"
        self.worlds.mkdir()
        self.empty = self.worlds / "no-programs"
        self.empty.mkdir()


class StoppedCommands(RealCase):
    def stopped_everywhere(self, name: str) -> None:
        scenario = SCENARIOS[name]
        if WINDOWS and not FULL and name not in WINDOWS_SAMPLE:
            self.skipTest("under the Windows Python a sample of four scenarios is run; WFSETUP_TEST_FULL=1 runs all")
        if scenario.follow and not SYMLINKS:
            self.skipTest("a home's directory that is a symlink cannot be made here")
        clone = picture(self.clone)
        outcome = run_scenario(scenario, self.worlds, self.script, self.clone)
        self.assertEqual(picture(self.clone), clone, "a run changed the clone it ran from")
        self.assertGreater(outcome.total, 0, f"{name}: the command made no change at all")
        self.assertGreater(sum(outcome.triples.values()), 0)
        if outcome.failures:
            self.fail(outcome.summary())

    def test_1_init_user(self) -> None:
        self.stopped_everywhere("init-user")

    def test_2_init_project(self) -> None:
        self.stopped_everywhere("init-project")

    def test_2_init_rewrites_a_hand_written_settings_file(self) -> None:
        self.stopped_everywhere("init-rewrite")

    def test_3_render_with_roles(self) -> None:
        self.stopped_everywhere("render")

    def test_4_migration_with_a_stale_copy_on_a_home_like_l1(self) -> None:
        self.stopped_everywhere("migrate")

    def test_5_migration_through_a_linked_skills_directory(self) -> None:
        self.stopped_everywhere("migrate-follow")

    def test_6_render_of_a_project(self) -> None:
        self.stopped_everywhere("render-project")

    def test_7_render_with_the_codex_settings(self) -> None:
        self.stopped_everywhere("codex-settings")

    def test_8_uninstall_of_a_project(self) -> None:
        self.stopped_everywhere("uninstall-project")

    def test_9_uninstall(self) -> None:
        self.stopped_everywhere("uninstall")

    def test_10_render_after_codex_wrote_into_the_profile(self) -> None:
        self.stopped_everywhere("render-carry")

    def test_11_uninstall_after_codex_wrote_into_the_profile(self) -> None:
        self.stopped_everywhere("uninstall-carry")

    def test_12_render_over_what_an_uninstall_left_in_the_profile(self) -> None:
        self.stopped_everywhere("render-prepend")

    def test_13_no_roles_after_codex_wrote_into_the_profile(self) -> None:
        self.stopped_everywhere("no-roles-carry")

    def test_every_scenario_has_a_test(self) -> None:
        names = {
            line.split('"')[1] for line in Path(__file__).read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("self.stopped_everywhere(")
        }
        self.assertEqual(names, set(SCENARIOS))


class TheHook(RealCase):
    def test_without_the_variable_or_with_one_that_is_no_count_a_run_is_as_ever(self) -> None:
        """A whole install and the way back, five times: with no variable,
        and with values that are not a count of changes. Each run ends as
        the first does and leaves the same tree."""
        scenario = SCENARIOS["uninstall"]
        commands = (*scenario.prepare, *scenario.way_back())
        values = (None, "abc", "0", "-1", "")

        def install_and_back(number: int):
            world = World(self.worlds / f"inert-{number}", self.script, self.clone, scenario, self.empty)
            world.root.mkdir()
            world.world.mkdir()
            build(world.world, self.clone, scenario)
            before = world.picture()
            ran, trees = [], []
            for argv in commands:
                ran.append(world.run(argv, stop=values[number]))
                # Without the world's own path, which is in a link's text.
                trees.append({
                    path: tuple(part.replace(str(world.root), "") if isinstance(part, str) else part for part in what)
                    for path, what in without_state(world.picture()).items()
                })
            return ran, trees, before == world.picture()

        with ThreadPoolExecutor(max_workers=len(values)) as pool:
            seen = list(pool.map(install_and_back, range(len(values))))
        for value, (ran, trees, came_back) in zip(values, seen):
            with self.subTest(value=value):
                for one in ran:
                    self.assertFalse(one.traceback, one.said())
                    self.assertEqual(one.code, 0, one.said())
                self.assertTrue(came_back, "the tree at the end is not the tree at the start")
                self.assertEqual([(one.code, len(one.out.splitlines()), one.err) for one in ran],
                                 [(one.code, len(one.out.splitlines()), one.err) for one in seen[0][0]])
                self.assertEqual(trees, seen[0][1])

    def test_a_count_stops_the_run_with_the_code_of_the_hook(self) -> None:
        scenario = SCENARIOS["init-user"]
        world = World(self.worlds / "stops", self.script, self.clone, scenario, self.empty).make()
        world.restore()
        ran = world.run(scenario.command, stop=1)
        self.assertEqual((ran.code, ran.err), (fsio.STOP_EXIT_CODE, ""), ran.said())
        self.assertEqual(fsio.STOP_EXIT_CODE, 77)

    def test_only_fsio_names_the_variable(self) -> None:
        """Nothing in the tool sets the variable or passes it on: the one
        file that holds its name is ``fsio.py``."""
        name = fsio.STOP_VARIABLE
        self.assertEqual(name, "WFSETUP_TEST_STOP_AFTER")
        package = support.SETUP / "wfsetup"
        files = [support.SCRIPT, *(
            Path(directory) / file for directory, _, names in os.walk(package) for file in names
            if "__pycache__" not in Path(directory).parts
        )]
        self.assertGreater(len(files), 20)
        self.assertIn(package / "fsio.py", files)
        holders = sorted(
            file.relative_to(support.SETUP).as_posix() for file in files
            if name.encode("ascii") in file.read_bytes() or b"WFSETUP_TEST" in file.read_bytes()
        )
        self.assertEqual(holders, ["wfsetup/fsio.py"])
        # And there the environment is read, never written.
        text = (package / "fsio.py").read_text(encoding="utf-8")
        for writes in ("os.environ[", "putenv", "environ.setdefault", "environ.update"):
            self.assertNotIn(writes, text)


if __name__ == "__main__":
    unittest.main()
