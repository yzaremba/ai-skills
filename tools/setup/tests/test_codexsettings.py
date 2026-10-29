"""Tests for the Codex settings: ``render --apply-codex-settings`` and the
check ``codex-settings`` of ``doctor``.

Run from the repository root:
    python -m unittest discover -s tools/setup/tests

Every home is a scratch directory and no provider is started: the user's
Codex ``config.toml`` is a file a test writes into the scratch Codex home.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
import unittest
from pathlib import Path

from fileops_support import POSIX, SYMLINKS
from test_doctor import SECRET, DoctorCase
from test_render import tree
from wfsetup import blocks, codexsettings, doctor, fileops, fsio, homes, render

APPLY = "--apply-codex-settings"
REMOVE = "--remove-codex-settings"
DEFAULT = "--default-codex-permissions"
ROOT = "--worktree-root"
KEY = "max_concurrent_threads_per_session"
LIMIT = f"agents.{KEY}"

# What the user's file holds, and what becomes of the limit beside it.
COMBINATIONS = {
    "an empty file": ("", codexsettings.TABLE),
    "unrelated keys and a table": ('model = "x"\n\n[features]\nfast = true\n', codexsettings.TABLE),
    "a last line without an ending": ("[features]\nfast = true", codexsettings.TABLE),
    "agents sub-tables only": ('[agents.reviewer]\ndescription = "r"\n', codexsettings.TABLE),
    "a dotted agents key in another table": ('[x]\nagents.y = 1\n', codexsettings.TABLE),
    "a permissions table of the user's": ('[permissions.other]\nextends = ":workspace"\n', codexsettings.TABLE),
    "a top-level dotted agents key": ("agents.enabled = true\n\n[features]\nx = 1\n", codexsettings.DOTTED),
    "a top-level dotted agents sub-key": ('agents.reviewer.description = "r"\n', codexsettings.DOTTED),
    "an agents table without the key": ("[agents]\nenabled = true\n", codexsettings.CANNOT),
    "an agents table and a sub-table": (
        '[agents]\nenabled = true\n\n[agents.reviewer]\ndescription = "r"\n', codexsettings.CANNOT),
    "a sub-table and then the agents table": (
        '[agents.reviewer]\ndescription = "r"\n\n[agents]\nenabled = true\n', codexsettings.CANNOT),
    "an inline agents table": ("agents = { enabled = true }\n", codexsettings.CANNOT),
    "an array of agents tables": ("[[agents]]\na = 1\n", codexsettings.CANNOT),
    "agents as a plain value": ("agents = 3\n", codexsettings.CANNOT),
    "the key in an agents table, lower": (f"[agents]\n{KEY} = 4\n", codexsettings.USER_SET),
    "the key in an agents table, equal": (f"[agents]\n{KEY} = 8\n", codexsettings.USER_SET),
    "the key in an agents table, higher": (f"[agents]\n{KEY} = 12\n", codexsettings.USER_SET),
    "the key as a dotted key": (f"{LIMIT} = 4\n", codexsettings.USER_SET),
    "the key in an inline table": (f"agents = {{ {KEY} = 9 }}\n", codexsettings.USER_SET),
    "the legacy alias": ("[agents]\nmax_threads = 4\n", codexsettings.ALIAS),
}
USER_VALUE = {"lower": 4, "equal": 8, "higher": 12, "dotted key": 4, "inline table": 9}

WAIT = "features.multi_agent_v2"
MIN, DEF, MAX = "min_wait_timeout_ms", "default_wait_timeout_ms", "max_wait_timeout_ms"
FLOOR = {MIN: 300000, DEF: 3600000}
# A file that holds the floor already, so that the end block has nothing of it to write.
FLOORED = f"[{WAIT}]\n{MIN} = 300000\n{DEF} = 3600000\n"

# What the user's file holds, and what becomes of the wait floor beside it: the status, the user's values
# as the output gives them, and the lines it prints to add.
WAIT_COMBINATIONS = {
    "nothing": ("", codexsettings.TABLE, None, None),
    "a features table": ("[features]\nfast = true\n", codexsettings.TABLE, None, None),
    "top-level dotted features keys": ("features.fast = true\n\n[x]\ny = 1\n", codexsettings.TABLE, None, None),
    "another features sub-table": ("[features.other]\na = 1\n", codexsettings.TABLE, None, None),
    "a dotted key in the features table": ("[features]\nother.a = 1\n", codexsettings.TABLE, None, None),
    "the table with the switch only": (
        f"[{WAIT}]\nenabled = true\n", codexsettings.USER_SET, "none of the wait keys",
        f"{MIN} = 300000; {DEF} = 3600000"),
    "the table with both keys": (
        FLOORED, codexsettings.USER_SET, f"{MIN} = 300000, {DEF} = 3600000", None),
    "the table with every key, the floor higher": (
        f"[{WAIT}]\n{MIN} = 600000\n{DEF} = 3600000\n{MAX} = 3600000\n", codexsettings.USER_SET,
        f"{MIN} = 600000, {DEF} = 3600000, {MAX} = 3600000", None),
    "the table with a low floor": (
        f"[{WAIT}]\n{MIN} = 60000\n", codexsettings.USER_SET, f"{MIN} = 60000", f"{DEF} = 3600000"),
    "the table with a max of its own": (
        f"[{WAIT}]\n{MIN} = 300000\n{MAX} = 1800000\n", codexsettings.USER_SET,
        f"{MIN} = 300000, {MAX} = 1800000", f"{DEF} = 1800000"),
    "top-level dotted keys": (
        f"{WAIT}.{MIN} = 400000\n", codexsettings.USER_SET, f"{MIN} = 400000", f"{DEF} = 3600000"),
    "a dotted wait key in the features table": (
        f"[features]\nmulti_agent_v2.{DEF} = 3600000\n", codexsettings.USER_SET, f"{DEF} = 3600000",
        f"{MIN} = 300000"),
    "an inline table": (
        f"features = {{ multi_agent_v2 = {{ {MIN} = 300000 }} }}\n", codexsettings.USER_SET, f"{MIN} = 300000",
        f"{DEF} = 3600000"),
    "a sub-table of it": (f"[{WAIT}.sub]\na = 1\n", codexsettings.USER_SET, "none of the wait keys",
                          f"{MIN} = 300000; {DEF} = 3600000"),
    "the switch in the features table": ("[features]\nmulti_agent_v2 = true\n", codexsettings.SWITCH, None, None),
    "the switch as a dotted key": (f"{WAIT} = false\n", codexsettings.SWITCH, None, None),
    "an inline features table": ("features = { fast = true }\n", codexsettings.CANNOT, None, None),
    "features as a plain value": ("features = 3\n", codexsettings.CANNOT, None, None),
    "an array of features tables": ("[[features]]\na = 1\n", codexsettings.CANNOT, None, None),
}

# The checks that read what this step writes. A whole run of doctor would also hold these tests to every
# other check of the registry.
MINE = ("--only", "codex-settings", "--only", "hand-edits", "--only", "drift", "--only", "missing")


class SettingsCase(DoctorCase):
    """Both providers installed by their scratch homes; ``config`` is the
    user's Codex configuration. Every run asks for no role definition:
    these tests are about one file."""

    def setUp(self) -> None:
        super().setUp()
        self.config = self.codex / "config.toml"
        self.key = "home:.codex/config.toml"

    def user(self, text: str | bytes) -> bytes:
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        self.config.write_bytes(data)
        return data

    def go(self, *argv: str, host: homes.Host | None = None) -> tuple[int, str, str]:
        return self.render("--no-roles", *argv, host=host)

    def apply(self, *argv: str, code: int = 0) -> str:
        """``render --apply-codex-settings``, which must end with ``code``."""
        got, out, err = self.go(APPLY, *argv)
        self.assertEqual(got, code, out + err)
        return " ".join((out + err).split())

    def as_json(self, *argv: str) -> dict:
        code, out, err = self.go("--json", *argv)
        return json.loads(out)

    def statuses(self, report: dict) -> dict[str, str]:
        for provider in report["providers"]:
            if provider["name"] == "codex":
                for place in provider["places"]:
                    if place["name"] == "config":
                        return {item["name"]: item["status"] for item in place["items"]}
        return {}

    def loaded(self) -> dict:
        return tomllib.loads(self.config.read_bytes().decode("utf-8-sig"))

    def limit(self):
        agents = self.loaded().get("agents")
        return agents.get(KEY) if isinstance(agents, dict) else None

    def block(self, name: str = codexsettings.BLOCK) -> bytes | None:
        return blocks.get(self.config.read_bytes(), blocks.TOML, name)

    def recorded(self) -> dict:
        if not self.manifest_file.exists():
            return {}
        entry = json.loads(self.manifest_file.read_text(encoding="utf-8"))["entries"].get(self.key) or {}
        return entry.get("blocks") or {}

    def settings(self, *argv: str) -> list[dict]:
        code, findings = self.only("codex-settings", *argv)
        self.assertEqual(code, 0)
        return findings

    def without_blocks(self) -> bytes:
        """The file's bytes once setup's blocks are taken out."""
        data = self.config.read_bytes()
        for name in codexsettings.BLOCK_NAMES:
            dropped = blocks.drop(data, blocks.TOML, name)
            data = data if dropped is None else dropped
        return data


class LimitCase(SettingsCase):
    def test_no_file_gets_a_file_that_holds_only_the_block(self) -> None:
        out = self.apply()
        data = self.config.read_bytes()
        self.assertEqual(data, self.block())
        self.assertTrue(data.startswith(b"# workflow-setup:start codex-settings\n"))
        self.assertTrue(data.endswith(b"# workflow-setup:end codex-settings\n"))
        self.assertNotIn(b"\r", data)
        self.assertEqual(self.limit(), 8)
        self.assertIn(f"{LIMIT}: set to 8 in setup's block at the end of the file", out)
        self.assertIn("1 block of Codex settings written", out)
        self.assertEqual(list(self.recorded()), [codexsettings.BLOCK])

    def test_an_empty_file(self) -> None:
        self.user("")
        self.apply()
        self.assertEqual(self.limit(), 8)
        self.assertEqual(self.config.read_bytes(), self.block())

    def test_the_bytes_outside_the_block_are_kept_and_crlf_is_the_blocks_too(self) -> None:
        original = self.user(b'\xef\xbb\xbf# Mine.\r\nmodel = "x"\r\n\r\n[features]\r\nfast = true\r\n')
        self.apply()
        data = self.config.read_bytes()
        self.assertTrue(data.startswith(original + b"\r\n# workflow-setup:start codex-settings\r\n"))
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        self.assertEqual(self.limit(), 8)
        self.assertEqual(self.loaded()["features"], {"fast": True, "multi_agent_v2": FLOOR})
        self.assertEqual(self.loaded()["model"], "x")

    def test_every_combination_of_what_the_file_holds(self) -> None:
        for name, (text, expected) in COMBINATIONS.items():
            with self.subTest(name):
                if self.manifest_file.exists():
                    self.go(REMOVE)
                original = self.user(text)
                before = tomllib.loads(text)
                facts = codexsettings.analyse(original)
                self.assertEqual(codexsettings.decide(facts, codexsettings.Want()).limit, expected)
                out = self.apply()
                data = self.config.read_bytes()
                after = self.loaded()  # the result is valid TOML
                self.assertEqual(self.without_blocks(), original)
                for key, value in before.items():
                    if key not in ("agents", "permissions"):
                        got = after[key]
                        if key == "features":  # beside the wait floor setup writes
                            got = {name: one for name, one in got.items() if name != "multi_agent_v2"}
                        self.assertEqual(got, value)
                if expected == codexsettings.TABLE:
                    self.assertEqual(self.limit(), 8)
                    self.assertTrue(data.startswith(original))
                    self.assertIn(b"[agents]\n" + KEY.encode() + b" = 8\n", self.block())
                    self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
                elif expected == codexsettings.DOTTED:
                    self.assertEqual(self.limit(), 8)
                    self.assertTrue(data.startswith(b"# workflow-setup:start codex-settings-top\n"))
                    self.assertIn(f"{LIMIT} = 8\n".encode(), self.block(codexsettings.TOP_BLOCK))
                    self.assertNotIn(b"[agents]", self.block())
                    self.assertIn("as a dotted key in setup's block at the head of the file", out)
                else:
                    # Nothing is written for the limit, whatever else is.
                    self.assertNotIn(KEY.encode(), self.block() or b"")
                    self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
                    self.assertEqual(after.get("agents"), before.get("agents"))
                if expected == codexsettings.CANNOT:
                    self.assertIn(f"{LIMIT}: not written", out)
                    self.assertIn(f"Add this line to your [agents] table: {KEY} = 8", out)
                elif expected == codexsettings.ALIAS:
                    self.assertIn("agents.max_threads, the legacy alias", out)
                    self.assertIn("its value is not read", out)
                elif expected == codexsettings.USER_SET:
                    value = next(number for word, number in USER_VALUE.items() if word in name)
                    self.assertEqual(self.limit(), value)
                    self.assertIn(f"{LIMIT}: your file sets it to {value}, so setup writes nothing for it", out)
                    self.assertIn("that is enough" if value >= 8 else "raising it is yours to do", out)
                # A second run writes nothing.
                home = tree(self.home)
                again = self.apply()
                self.assertIn("nothing was written", again)
                self.assertEqual(tree(self.home), home)
                # Taking it out gives the file's bytes back.
                self.go(REMOVE)
                self.assertEqual(self.config.read_bytes(), original)

    def test_the_combinations_hold_what_tomllib_says(self) -> None:
        """The table of the module, asked of the parser itself."""
        table, dotted = codexsettings.limit_table(), codexsettings.limit_dotted()
        want = {("agents", KEY): 8}
        for name, (text, expected) in COMBINATIONS.items():
            with self.subTest(name):
                at_end = codexsettings._valid(text, [], table, want)
                at_head = codexsettings._valid(text, dotted, [], want)
                if expected == codexsettings.TABLE:
                    self.assertTrue(at_end)
                elif expected == codexsettings.DOTTED:
                    self.assertEqual((at_end, at_head), (False, True))
                elif expected == codexsettings.CANNOT:
                    self.assertEqual((at_end, at_head), (False, False))
        # The table form is never valid where the dotted form is not.
        for text, _ in COMBINATIONS.values():
            if codexsettings._valid(text, [], table, want):
                self.assertTrue(codexsettings._valid(text, dotted, [], want))


class WaitCase(SettingsCase):
    def floor(self):
        found = self.loaded().get("features")
        return found.get("multi_agent_v2") if isinstance(found, dict) else None

    def test_no_file_gets_the_floor_in_the_end_block(self) -> None:
        out = self.apply()
        self.assertEqual(self.floor(), FLOOR)
        self.assertIn(f"[{WAIT}]\n{MIN} = 300000\n{DEF} = 3600000\n".encode(), self.block())
        self.assertNotIn(MAX.encode(), self.block())
        self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
        self.assertIn(f"{WAIT}.{MIN}: set to 300000, with {DEF} = 3600000, in setup's block at the end of the "
                      "file", out)

    def test_every_combination_of_what_the_file_holds(self) -> None:
        for name, (text, expected, values, add) in WAIT_COMBINATIONS.items():
            with self.subTest(name):
                if self.manifest_file.exists():
                    self.go(REMOVE)
                original = self.user(text)
                before = tomllib.loads(text)
                facts = codexsettings.analyse(original)
                self.assertEqual(codexsettings.decide(facts, codexsettings.Want()).wait, expected)
                out = self.apply()
                self.assertEqual(self.without_blocks(), original)
                after = self.loaded()  # valid TOML
                self.assertEqual(self.limit(), 8)
                if expected == codexsettings.TABLE:
                    self.assertEqual(self.floor(), FLOOR)
                    self.assertTrue(self.config.read_bytes().startswith(original))
                    self.assertIn(f"{WAIT}.{MIN}: set to 300000", out)
                else:
                    # Nothing of the floor is written, whatever else is, and the user's own stays as it was.
                    self.assertNotIn(b"multi_agent_v2", self.block() or b"")
                    self.assertEqual(after.get("features"), before.get("features"))
                if expected == codexsettings.USER_SET:
                    self.assertIn(f"{WAIT}: your file defines it, outside setup's block, so setup writes nothing", out)
                    self.assertIn(f"it sets {values};", out)
                    low = codexsettings.analyse(original).outside[f"{WAIT}.{MIN}"]
                    if low is codexsettings.UNSET:
                        self.assertIn("the floor is Codex's own 10000 ms", out)
                    elif low >= 300000:
                        self.assertIn("the floor is met", out)
                    else:
                        self.assertIn(f"needs {MIN} of 300000 or more, and raising it is yours to do", out)
                    if add is None:
                        self.assertNotIn("Add to that table", out)
                    else:
                        self.assertIn(f"Add to that table, in the form your file gives it: {add}", out)
                    self.assertNotIn("Codex refuses", out)
                elif expected == codexsettings.SWITCH:
                    self.assertIn(f"Your file sets {WAIT} itself, to a value that is not a table", out)
                    self.assertIn(f"with enabled = <the switch you had> and these lines: {MIN} = 300000; "
                                  f"{DEF} = 3600000", out)
                elif expected == codexsettings.CANNOT:
                    self.assertIn(f"{WAIT}.{MIN}: not written. Your file defines `features` in a form", out)
                    self.assertIn(f"these lines: {MIN} = 300000; {DEF} = 3600000", out)
                # A second run writes nothing.
                home = tree(self.home)
                again = self.apply()
                self.assertIn("nothing was written", again)
                self.assertEqual(tree(self.home), home)
                # Taking it out gives the file's bytes back.
                self.go(REMOVE)
                self.assertEqual(self.config.read_bytes(), original)

    def test_the_combinations_hold_what_tomllib_says(self) -> None:
        """The table of the module, asked of the parser itself: the end form
        where nothing is at the path, and no head form that would do better."""
        want = {("features", "multi_agent_v2", MIN): 300000, ("features", "multi_agent_v2", DEF): 3600000}
        dotted = [f"{WAIT}.{MIN} = 300000", f"{WAIT}.{DEF} = 3600000"]
        for name, (text, expected, _, _) in WAIT_COMBINATIONS.items():
            with self.subTest(name):
                at_end = codexsettings._valid(text, [], codexsettings.wait_table(), want)
                at_head = codexsettings._valid(text, dotted, [], want)
                if expected == codexsettings.TABLE:
                    self.assertTrue(at_end)
                elif expected == codexsettings.CANNOT:
                    self.assertEqual((at_end, at_head), (False, False))
                elif expected == codexsettings.SWITCH:
                    self.assertEqual((at_end, at_head), (False, False))
                if codexsettings.analyse(text.encode()).wait is codexsettings.UNSET and at_head:
                    self.assertTrue(at_end)

    def test_an_order_codex_refuses_is_said(self) -> None:
        for text, words in (
            (f"[{WAIT}]\n{MIN} = 300000\n{DEF} = 60000\n",
             "As it is, Codex refuses a config unless min_wait_timeout_ms <= default_wait_timeout_ms <= "
             "max_wait_timeout_ms, and these are min_wait_timeout_ms 300000, default_wait_timeout_ms 60000, "
             "max_wait_timeout_ms 3600000 (Codex's own)"),
            (f"[{WAIT}]\n{MAX} = 120000\n",
             f"Add to that table, in the form your file gives it: {MIN} = 300000; {DEF} = 120000. With those "
             "lines, Codex refuses a config unless"),
        ):
            with self.subTest(text):
                self.go(REMOVE)
                original = self.user(text)
                out = self.apply()
                self.assertIn(words, out)
                self.assertEqual(self.without_blocks(), original)
                self.assertNotIn(b"multi_agent_v2", self.block())

    def test_a_hand_edited_floor_is_kept_and_reported(self) -> None:
        self.user('model = "x"\n')
        self.apply()
        edited = self.config.read_bytes().replace(f"{MIN} = 300000".encode(), f"{MIN} = 1000".encode())
        self.config.write_bytes(edited)
        code, out, err = self.go(APPLY)
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        self.assertEqual(self.config.read_bytes(), edited)
        self.assertIn("codex-settings: kept: edited by hand since setup wrote it", out)
        findings = self.settings()
        self.assertFinding(findings, doctor.WARNING, f"{WAIT}.{MIN} = 1000: below 300000")
        self.assertFinding(findings, doctor.INFO, "setup's block codex-settings: in the file, and changed by hand")
        code, edits = self.only("hand-edits")
        self.assertFinding(edits, doctor.WARNING, "config.toml: block codex-settings", "changed by hand")
        code, out, err = self.go(REMOVE)
        self.assertEqual(self.config.read_bytes(), edited)
        code, out, err = self.go(APPLY, "--overwrite-edited")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.floor(), FLOOR)

    def test_every_key_whose_value_is_printed_is_one_doctor_names(self) -> None:
        self.assertLessEqual(set(codexsettings.KEYS), set(doctor.CODEX_KEYS))

    def test_removal_takes_the_floor_out_with_the_block(self) -> None:
        original = self.user("[features]\nfast = true\n")
        self.apply()
        self.assertEqual(self.floor(), FLOOR)
        code, out, err = self.go(REMOVE)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.recorded(), {})


class ProfileCase(SettingsCase):
    def profile(self) -> dict | None:
        return (self.loaded().get("permissions") or {}).get("workflow")

    def test_with_sandbox_mode_set_no_permissions_table_is_written_and_the_profile_is_printed(self) -> None:
        original = self.user('# Mine.\nsandbox_mode = "workspace-write"\n\n[sandbox_workspace_write]\nnetwork_access = true\n')
        code, out, err = self.go(APPLY, DEFAULT, ROOT, str(self.root / "trees"))
        self.assertEqual((code, err), (0, ""))
        data = self.config.read_bytes()
        self.assertTrue(data.startswith(original))
        self.assertEqual(self.without_blocks(), original)
        self.assertNotIn("permissions", self.loaded())
        self.assertNotIn("default_permissions", self.loaded())
        self.assertNotIn(b"permissions", self.block())
        self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
        self.assertEqual(self.loaded()["sandbox_mode"], "workspace-write")
        self.assertEqual(self.limit(), 8)
        flat = " ".join(out.split())
        self.assertIn('permission profile: not written. Your file sets sandbox_mode = "workspace-write"', flat)
        self.assertIn("Setup never changes or removes sandbox_mode", flat)
        self.assertIn("go through command-by-command approval", flat)
        self.assertIn("default_permissions: not set, for the same reason", flat)
        lines = out.splitlines()
        self.assertIn("note:     [permissions.workflow]", lines)
        self.assertIn('note:     extends = ":workspace"', lines)
        self.assertIn('note:     [permissions.workflow.filesystem.":workspace_roots"]', lines)
        self.assertIn('note:     ".git" = "write"', lines)
        self.assertIn("to use it you would, yourself: remove sandbox_mode", flat)
        # The printed profile is the one that would be written.
        printed = "\n".join(line[len("note:     "):] for line in lines if line.startswith("note:     "))
        self.assertNotIn("note: ", lines)
        self.assertEqual(tomllib.loads(printed)["permissions"]["workflow"],
                         codexsettings.profile_data(os.path.normpath(str(self.root / "trees"))))

    def test_sandbox_mode_and_the_limit_set_leave_nothing_to_write(self) -> None:
        original = self.user(f'sandbox_mode = "read-only"\n\n[agents]\n{KEY} = 8\n\n{FLOORED}')
        before = tree(self.home)
        report = self.as_json(APPLY)
        self.assertEqual(self.statuses(report), {codexsettings.BLOCK: render.UP_TO_DATE})
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.recorded(), {})
        self.assertFalse(any("config.toml" in line for line in report["plan"]))
        self.assertEqual(tree(self.home)[".codex/config.toml"], before[".codex/config.toml"])

    def test_without_the_option_or_a_default_of_the_users_the_profile_is_only_printed(self) -> None:
        original = self.user('model = "x"\n')
        code, out, err = self.go(APPLY)
        self.assertEqual((code, err), (0, ""))
        flat = " ".join(out.split())
        self.assertTrue(self.config.read_bytes().startswith(original))
        self.assertNotIn("permissions", self.loaded())
        self.assertNotIn("default_permissions", self.loaded())
        self.assertNotIn(b"permissions", self.block())
        self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
        # The limit and the floor are written all the same.
        self.assertEqual(self.limit(), 8)
        self.assertEqual(self.loaded()["features"]["multi_agent_v2"], FLOOR)
        self.assertIn("permission profile: not written. Codex (0.163.0) refuses to load a config that defines a "
                      "[permissions] profile and sets no default_permissions while sandbox_mode is unset, and after "
                      "this run your file would set none: --default-codex-permissions was not given", flat)
        self.assertIn("to use it: run render --apply-codex-settings --default-codex-permissions, which writes it "
                      "and selects it", flat)
        self.assertIn("permission profiles are beta in Codex", flat)
        self.assertIn("no worktree root is in the profile", flat)
        lines = out.splitlines()
        printed = "\n".join(line[len("note:     "):] for line in lines if line.startswith("note:     "))
        self.assertEqual(tomllib.loads(printed)["permissions"]["workflow"], codexsettings.profile_data(None))
        # A second run writes nothing.
        home = tree(self.home)
        self.assertIn("nothing was written", self.apply())
        self.assertEqual(tree(self.home), home)

    def test_a_default_of_the_users_gets_the_profile_written_and_not_selected(self) -> None:
        for value in (":workspace", ":read-only", "mine"):
            with self.subTest(value):
                self.go(REMOVE)
                original = self.user(f'default_permissions = "{value}"\n')
                out = self.apply()
                self.assertEqual(self.without_blocks(), original)
                self.assertEqual(self.profile(), codexsettings.profile_data(None))
                self.assertEqual(self.loaded()["default_permissions"], value)
                self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
                self.assertIn("permission profile: `workflow` defined in setup's block at the end of the file", out)
                self.assertIn(f'default_permissions: your file sets it to "{value}"; setup leaves it alone. The '
                              "profile is written and not selected", out)
                home = tree(self.home)
                self.assertIn("nothing was written", self.apply())
                self.assertEqual(tree(self.home), home)

    def test_an_earlier_block_with_the_profile_and_no_default_fails_doctor_and_goes_with_a_run(self) -> None:
        # An earlier run beside the user's own default; the user then took that default out.
        self.user('default_permissions = ":workspace"\nmodel = "x"\n')
        self.apply()
        self.config.write_bytes(self.config.read_bytes().replace(b'default_permissions = ":workspace"\n', b""))
        self.assertEqual(self.profile(), codexsettings.profile_data(None))
        self.assertNotIn("default_permissions", self.loaded())
        code, findings = self.only("codex-settings")
        self.assertEqual(code, 1)
        self.assertFinding(findings, doctor.ERROR, "setup's block codex-settings defines the permission profile "
                           "`workflow` and the file sets no default_permissions", "so Codex will not start",
                           "render --apply-codex-settings --default-codex-permissions",
                           "render --remove-codex-settings")
        self.assertFinding(findings, doctor.OK, "setup's block codex-settings: in the file, as setup wrote it")
        # The fix by the option keeps the profile and selects it.
        self.apply(DEFAULT)
        self.assertEqual(self.profile(), codexsettings.profile_data(None))
        self.assertEqual(self.loaded()["default_permissions"], "workflow")
        self.assertEqual(self.only("codex-settings")[0], 0)
        # A run without it takes the profile out, and says so.
        out = self.apply()
        self.assertNotIn("permissions", self.loaded())
        self.assertNotIn("default_permissions", self.loaded())
        self.assertEqual(self.limit(), 8)
        self.assertIn("this run was given no --default-codex-permissions, so default_permissions is taken out", out)
        # The same from the old block itself, as an earlier setup left it.
        self.go(REMOVE)
        self.user('default_permissions = ":workspace"\nmodel = "x"\n')
        self.apply()
        self.config.write_bytes(self.config.read_bytes().replace(b'default_permissions = ":workspace"\n', b""))
        out = self.apply()
        self.assertIn("codex-settings: update: ", out)
        self.assertIn("the permission profile `workflow` is taken out, because --default-codex-permissions was not "
                      "given to this run and your file sets no default_permissions", out)
        self.assertIn("the earlier block defined the permission profile `workflow`", out)
        self.assertNotIn("permissions", self.loaded())
        self.assertEqual(self.loaded()["features"]["multi_agent_v2"], FLOOR)
        self.assertEqual(self.only("codex-settings")[0], 0)
        home = tree(self.home)
        self.assertIn("nothing was written", self.apply())
        self.assertEqual(tree(self.home), home)
        # The fix by removal.
        self.go(REMOVE)
        self.user('default_permissions = ":workspace"\nmodel = "x"\n')
        self.apply()
        self.config.write_bytes(self.config.read_bytes().replace(b'default_permissions = ":workspace"\n', b""))
        self.go(REMOVE)
        self.assertEqual(self.config.read_bytes(), b'model = "x"\n')
        self.assertEqual(self.only("codex-settings")[0], 0)

    def test_with_sandbox_mode_an_earlier_profile_is_no_failure(self) -> None:
        self.user('default_permissions = ":workspace"\n')
        self.apply()
        self.config.write_bytes(self.config.read_bytes().replace(b'default_permissions = ":workspace"\n',
                                                                 b'sandbox_mode = "workspace-write"\n'))
        code, findings = self.only("codex-settings")
        self.assertEqual(code, 0)
        self.assertFalse(any(found["severity"] == doctor.ERROR for found in findings))

    def test_the_default_flag_selects_it_in_a_block_at_the_head(self) -> None:
        original = self.user('model = "x"\n\n[features]\nfast = true\n')
        out = self.apply(DEFAULT)
        data = self.config.read_bytes()
        self.assertTrue(data.startswith(b"# workflow-setup:start codex-settings-top\n"))
        self.assertEqual(self.without_blocks(), original)
        self.assertEqual(self.loaded()["default_permissions"], "workflow")
        self.assertEqual(self.loaded()["features"], {"fast": True, "multi_agent_v2": FLOOR})
        self.assertEqual(self.profile(), codexsettings.profile_data(None))
        self.assertEqual(sorted(self.recorded()), [codexsettings.BLOCK, codexsettings.TOP_BLOCK])
        self.assertIn('default_permissions: set to "workflow" in setup\'s block at the head of the file', out)
        self.assertIn("2 blocks of Codex settings written", out)
        # Without the flag the selection goes again, and the run says so.
        out = self.apply()
        self.assertNotIn("default_permissions", self.loaded())
        self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
        self.assertIn("this run was given no --default-codex-permissions, so default_permissions is taken out", out)
        self.assertEqual(self.without_blocks(), original)

    def test_a_default_the_user_set_is_reported_and_not_changed(self) -> None:
        original = self.user('default_permissions = ":read-only"\n')
        out = self.apply(DEFAULT)
        self.assertEqual(self.loaded()["default_permissions"], ":read-only")
        self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
        self.assertEqual(self.without_blocks(), original)
        self.assertEqual(self.profile(), codexsettings.profile_data(None))
        self.assertIn('default_permissions: your file sets it to ":read-only", so setup writes nothing for it', out)
        self.assertIn("to select the profile, set it to \"workflow\" yourself", out)
        out = self.apply()
        self.assertIn('default_permissions: your file sets it to ":read-only"; setup leaves it alone', out)

    def test_a_profile_of_that_name_the_user_defined_is_left_alone(self) -> None:
        for text in ('[permissions.workflow]\nextends = ":read-only"\n',
                     "[permissions.workflow.network]\nenabled = true\n"):
            with self.subTest(text):
                self.go(REMOVE)
                original = self.user(text)
                theirs = tomllib.loads(text)["permissions"]
                out = self.apply(DEFAULT)
                self.assertEqual(self.loaded()["permissions"], theirs)
                self.assertNotIn("default_permissions", self.loaded())
                self.assertEqual(self.without_blocks(), original)
                self.assertIn("Your file already defines a profile named `workflow`", out)
                self.assertIn("default_permissions: not set: setup selects only the profile it wrote", out)
                self.assertEqual(self.limit(), 8)

    def test_other_permission_tables_of_the_users_stay_beside_the_profile(self) -> None:
        for text in ('[permissions.other]\nextends = ":workspace"\n', "[permissions]\n",
                     'permissions.other.extends = ":workspace"\n'):
            with self.subTest(text):
                self.go(REMOVE)
                self.user(text)
                self.apply(DEFAULT)
                found = self.loaded()["permissions"]
                self.assertEqual(found["workflow"], codexsettings.profile_data(None))
                self.assertEqual({key: value for key, value in found.items() if key != "workflow"},
                                 tomllib.loads(text)["permissions"])

    def test_a_permissions_value_that_takes_no_table_is_reported(self) -> None:
        original = self.user("permissions = 3\n")
        out = self.apply(DEFAULT)
        self.assertEqual(self.without_blocks(), original)
        self.assertEqual(self.loaded()["permissions"], 3)
        self.assertIn("permission profile: not written. Your file defines `permissions` in a form", out)

    def test_the_block_names_no_path_of_this_machine_unless_the_user_gave_one(self) -> None:
        self.apply(DEFAULT)
        raw = self.config.read_bytes().decode("utf-8")
        for machine in (str(self.root), self.root.as_posix(), self.root.name, str(Path.home())):
            self.assertNotIn(machine, raw)


class WorktreeRootCase(SettingsCase):
    def written(self) -> list[str]:
        files = self.loaded()["permissions"]["workflow"]["filesystem"]
        return [key for key in files if key != ":workspace_roots"]

    def test_a_path_with_spaces_is_written_as_given_and_read_back(self) -> None:
        trees = self.root / "my work trees"
        trees.mkdir()
        out = self.apply(DEFAULT, ROOT, str(trees))
        self.assertEqual(self.written(), [str(trees)])
        files = self.loaded()["permissions"]["workflow"]["filesystem"]
        self.assertEqual(files, {str(trees): "write", ":workspace_roots": {".git": "write"}})
        self.assertIn(f"and the worktree root {trees}", out)
        self.assertIn(b"is the worktree root you gave with --worktree-root: your input", self.block())
        self.assertNotIn("is not a directory on this machine yet", out)
        # The path is the user's content in the user's file, and nowhere else.
        record = self.manifest_file.read_text(encoding="utf-8")
        for machine in (str(self.root), self.root.as_posix(), self.root.name, "my work trees"):
            self.assertNotIn(machine, record)

    def test_an_absolute_path_is_normalised_and_one_that_is_missing_is_said(self) -> None:
        trees = self.root / "trees"
        out = self.apply(DEFAULT, ROOT, str(trees) + os.sep + "." + os.sep)
        self.assertEqual(self.written(), [str(trees)])
        self.assertIn(f"the worktree root {trees} is not a directory on this machine yet", out)

    def test_a_home_path_is_kept_as_written(self) -> None:
        for given, written in (("~/work trees", "~/work trees"), ("~/a//b/", "~/a/b")):
            with self.subTest(given):
                self.apply(DEFAULT, ROOT, given)
                self.assertEqual(self.written(), [written])
        self.assertEqual(codexsettings.worktree_root("~\\trees"), "~/trees")

    def test_a_relative_path_another_users_home_and_an_empty_one_are_refused(self) -> None:
        original = self.user('model = "x"\n')
        before = tree(self.root)
        top = Path(self.root).anchor   # the root of the file system, with its drive on Windows
        for given, why in (("trees", "not an absolute path"), ("./trees", "not an absolute path"),
                           ("~other/trees", "another user's home"), ("~/../x", "a path with .. in it"),
                           ("", "no directory was given"),
                           # The review's cases, which were written into the profile:
                           (top, "the root of the file system"),
                           (os.path.join(top, "a", "..", ".."), "the root of the file system"),
                           ("~", "the home directory itself"), ("~/", "the home directory itself"),
                           ("~/.", "the home directory itself"),
                           (os.path.join(top, "a") + "\u2028b", "a control character or a line break"),
                           (os.path.join(top, "a") + "\u0085b", "a control character or a line break")):
            with self.subTest(given):
                for more in ((), ("--dry-run",)):
                    code, out, err = self.go(APPLY, ROOT, given, *more)
                    self.assertEqual(code, 2, out)
                    self.assertIn(f"error: --worktree-root", err)
                    self.assertIn(why, err)
                    self.assertEqual(len(err.strip().splitlines()), 1, err)
                    self.assertEqual(tree(self.root), before)
        self.assertEqual(self.config.read_bytes(), original)

    def test_a_root_given_while_sandbox_mode_is_set_is_only_printed(self) -> None:
        self.user('sandbox_mode = "workspace-write"\n')
        trees = self.root / "trees"
        code, out, err = self.go(APPLY, ROOT, str(trees))
        self.assertEqual(code, 0)
        self.assertNotIn("trees", self.config.read_bytes().decode("utf-8"))
        self.assertIn(f"note:     {json.dumps(str(trees))} = \"write\"", out.splitlines())

    def test_a_run_without_the_option_takes_the_root_out_and_says_so(self) -> None:
        trees = self.root / "trees"
        self.apply(DEFAULT, ROOT, str(trees))
        out = self.apply(DEFAULT)
        self.assertEqual(self.written(), [])
        self.assertIn(f"the earlier block held the worktree root {trees}, and this run was given no --worktree-root", out)

    def test_the_options_that_go_with_apply_are_refused_without_it(self) -> None:
        before = tree(self.root)
        for argv, why in (((ROOT, str(self.root)), "--worktree-root: goes with --apply-codex-settings"),
                          ((DEFAULT,), "--default-codex-permissions: goes with --apply-codex-settings"),
                          ((APPLY, REMOVE), "--apply-codex-settings and --remove-codex-settings: one or the other")):
            code, out, err = self.go(*argv)
            self.assertEqual(code, 2)
            self.assertIn(why, err)
            self.assertEqual(tree(self.root), before)


class StayCase(SettingsCase):
    def test_a_dry_run_writes_nothing_and_says_what_it_would(self) -> None:
        self.user('model = "x"\n')
        before = tree(self.root)
        code, out, err = self.go(APPLY, DEFAULT, "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(tree(self.root), before)
        self.assertIn("write 2 blocks of Codex settings and remove 0", out.splitlines()[-1])
        self.assertIn("    codex-settings: create: write, at the end of the file", out.splitlines())
        self.assertIn("    codex-settings-top: create: write, at the head of the file", out.splitlines())

    def test_a_second_run_with_the_same_options_writes_nothing(self) -> None:
        self.user('model = "x"\n')
        trees = self.root / "trees"
        self.apply(DEFAULT, ROOT, str(trees))
        before = tree(self.root)
        report = self.as_json(APPLY, DEFAULT, ROOT, str(trees))
        self.assertEqual((report["exit_code"], report["plan"], report["changed"]), (0, [], False))
        self.assertEqual(self.statuses(report), {codexsettings.BLOCK: render.UP_TO_DATE,
                                              codexsettings.TOP_BLOCK: render.UP_TO_DATE})
        self.assertEqual(tree(self.root), before)

    def test_the_file_is_backed_up_before_it_is_changed(self) -> None:
        original = self.user('model = "x"\n')
        self.apply()
        backups = [path for path in (self.home / ".agents" / "workflow-setup" / "backups").rglob("config.toml")]
        self.assertEqual([path.read_bytes() for path in backups], [original])

    def test_a_later_render_without_the_option_leaves_the_blocks(self) -> None:
        self.user('model = "x"\n')
        self.apply(DEFAULT)
        data, listed = self.config.read_bytes(), self.recorded()
        for argv in ((), ("--dry-run",)):
            report = self.as_json(*argv)
            self.assertEqual((report["exit_code"], report["plan"], report["stale"]), (0, [], []))
        code, out, err = self.render()  # with the roles, too: every part and the sweep
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("home:.codex/config.toml", out.split("plan:")[1])
        self.assertEqual(self.config.read_bytes(), data)
        self.assertEqual(self.recorded(), listed)

    def test_removal_gives_the_earlier_bytes_back(self) -> None:
        for original in (b'model = "x"\r\n\r\n[features]\r\nfast = true\r\n', b"[features]\nfast = true", b""):
            with self.subTest(original):
                self.user(original)
                self.apply(DEFAULT)
                self.assertNotEqual(self.config.read_bytes(), original)
                code, out, err = self.go(REMOVE)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(self.config.read_bytes(), original)
                self.assertEqual(self.recorded(), {})
                self.assertIn("0 blocks of Codex settings written, 2 removed", out.splitlines()[-1])

    def test_removal_removes_a_file_setup_created(self) -> None:
        self.apply()
        self.assertTrue(self.config.exists())
        self.go(REMOVE)
        self.assertFalse(self.config.exists())
        self.assertTrue(self.codex.is_dir())

    def test_removal_with_nothing_written_says_so(self) -> None:
        original = self.user('model = "x"\n')
        code, out, err = self.go(REMOVE)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("the record lists no block of setup's", out)
        self.assertEqual(self.config.read_bytes(), original)

    def test_an_edited_block_is_kept_until_it_is_overwritten_on_request(self) -> None:
        self.user('model = "x"\n')
        self.apply()
        edited = self.config.read_bytes().replace(f"{KEY} = 8".encode(), f"{KEY} = 3".encode())
        self.config.write_bytes(edited)
        code, out, err = self.go(APPLY)
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        self.assertEqual(self.config.read_bytes(), edited)
        self.assertIn("codex-settings: kept: edited by hand since setup wrote it", out)
        # Taking it out keeps it as well: it is the user's now.
        code, out, err = self.go(REMOVE)
        self.assertEqual(self.config.read_bytes(), edited)
        self.assertIn("edited since setup wrote it; kept", out)
        code, out, err = self.go(APPLY, "--overwrite-edited")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.limit(), 8)

    def test_a_block_removed_by_hand_is_taken_out_of_the_record_by_the_next_render(self) -> None:
        original = self.user('model = "x"\n')
        self.apply()
        self.config.write_bytes(original)
        findings = self.settings()
        self.assertFinding(findings, doctor.INFO, "the record lists it and it is no longer in the file")
        code, report = self.doctor("--only", "missing")
        self.assertEqual(report["counts"]["error"], 0, report)
        code, out, err = self.go()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.recorded(), {})

    def test_the_reversal_restores_the_home_byte_for_byte(self) -> None:
        self.user(b'# Mine.\r\nmodel = "x"\r\n\r\n[features]\r\nfast = true\r\n')
        before = tree(self.home)
        self.apply(DEFAULT, ROOT, str(self.root / "my trees"))
        self.apply(ROOT, "~/trees")
        self.assertEqual(self.render()[0], 0)
        self.assertNotEqual(tree(self.home), before)
        where = self.roots()
        result = fileops.plan_reversal(where).apply()
        self.assertEqual(result.kept, [])
        self.assertTrue(fileops.remove_state(where))
        self.assertEqual(tree(self.home), before)

    def test_the_reversal_removes_a_file_setup_created(self) -> None:
        before = tree(self.home)
        self.apply(DEFAULT)
        where = self.roots()
        fileops.plan_reversal(where).apply()
        self.assertTrue(fileops.remove_state(where))
        self.assertEqual(tree(self.home), before)

    def test_codex_not_installed_writes_nothing(self) -> None:
        import shutil
        shutil.rmtree(self.codex)
        before = tree(self.home)
        code, out, err = self.go(APPLY, "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("codex settings: Codex is not installed; nothing is written for it", out)
        self.assertEqual(tree(self.home), before)


class RefusedCase(SettingsCase):
    def assertRefused(self, data: bytes, *words: str) -> None:
        self.user(data)
        before = tree(self.root)
        for argv in ((APPLY,), (APPLY, "--dry-run"), (APPLY, "--json"), (REMOVE,)):
            code, out, err = self.go(*argv)
            self.assertEqual(code, 2, out)
            self.assertEqual(tree(self.root), before)
            for word in words:
                self.assertIn(word, err)
            self.assertNotIn(SECRET, out + err)
            self.assertNotIn("sk-doctor", out + err)
        # A render that was not asked about the file is not stopped by it.
        code, out, err = self.go()
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn(SECRET, out)
        self.assertEqual(self.config.read_bytes(), data)

    def test_a_file_that_does_not_parse_is_refused_by_the_place_of_the_fault(self) -> None:
        self.assertRefused(
            f'api_key = "{SECRET}"\ntoken = {SECRET}\n'.encode(),
            "config.toml: is not valid TOML (line 2, column", "setup writes nothing into a Codex config it cannot read",
        )

    def test_a_table_defined_twice_is_refused_without_its_names(self) -> None:
        self.assertRefused(
            f'["{SECRET}"]\nx = 1\n\n["{SECRET}"]\ny = "{SECRET}"\n'.encode(),
            "config.toml: is not valid TOML (line 4, column",
        )

    def test_a_file_that_is_not_text_is_refused(self) -> None:
        self.assertRefused(b"\xff\xfe" + SECRET.encode(), "config.toml: is not UTF-8 text")

    def test_markers_that_cannot_be_read_are_refused(self) -> None:
        self.assertRefused(
            f'api_key = "{SECRET}"\n# workflow-setup:start codex-settings\n'.encode(),
            "setup's markers in it cannot be read: line 2",
        )

    def test_a_directory_in_the_files_place_is_a_conflict(self) -> None:
        self.config.mkdir()
        code, out, err = self.go(APPLY)
        self.assertEqual(code, 2)
        self.assertIn("a directory is there, where the Codex config file would be", err)

    def test_the_planted_secret_is_in_no_output_of_a_run_that_writes(self) -> None:
        self.user(
            f'model = "{SECRET}-model"\napi_key = "{SECRET}"\n\n[agents]\ntoken = "{SECRET}"\n\n'
            f'[mcp_servers.one.env]\nTOKEN = "{SECRET}"\n\n[permissions.other]\ndescription = "{SECRET}"\n'
        )
        for argv in ((APPLY, "--dry-run"), (APPLY, "--json", "--dry-run"), (APPLY, DEFAULT), (APPLY,), (REMOVE,)):
            code, out, err = self.go(*argv)
            self.assertEqual((code, err), (0, ""))
            self.assertNotIn(SECRET, out)
            self.assertNotIn("sk-doctor", out)
        self.assertNotIn(SECRET, self.manifest_file.read_text(encoding="utf-8"))


@unittest.skipUnless(SYMLINKS, "this system does not let the user make a symlink to a file")
class LinkedCase(SettingsCase):
    def test_a_link_out_of_the_home_is_skipped_with_and_without_the_flag(self) -> None:
        elsewhere = self.root / "dotfiles" / "codex.toml"
        elsewhere.parent.mkdir()
        elsewhere.write_bytes(b'model = "x"\n')
        os.symlink(str(elsewhere), self.config)
        for argv in ((APPLY,), (APPLY, "--dry-run"), (APPLY, "--follow-config-symlinks", "--dry-run"),
                     (APPLY, "--follow-config-symlinks"), (APPLY, "--default-codex-permissions", "--follow-config-symlinks"),
                     (REMOVE, "--follow-config-symlinks"), (REMOVE,)):
            with self.subTest(argv=argv):
                code, out, err = self.go(*argv)
                # No option makes a run write there, so the code asks for none.
                self.assertEqual((code, err), (0, ""), out)
                self.assertEqual(elsewhere.read_bytes(), b'model = "x"\n')
                self.assertEqual(os.listdir(elsewhere.parent), ["codex.toml"])
                self.assertEqual(fsio.read_link(self.config), str(elsewhere))
                self.assertIn(f"codex-settings: skipped: a link to {elsewhere}, which leads out of the directories this "
                              "run may write to: skipped, whatever the options", out)
                self.assertNotIn("needs --follow-config-symlinks", out)
        self.assertNotIn("config.toml", self.manifest_file.read_text(encoding="utf-8"))

    def test_a_link_on_this_side_needs_the_flag(self) -> None:
        elsewhere = self.home / "dotfiles" / "codex.toml"   # in the home, where a run may write
        elsewhere.parent.mkdir()
        elsewhere.write_bytes(b'model = "x"\n')
        os.symlink(str(elsewhere), self.config)
        code, out, err = self.go(APPLY)
        self.assertEqual((code, err), (render.EXIT_NEEDS_FLAG, ""))
        self.assertEqual(elsewhere.read_bytes(), b'model = "x"\n')
        self.assertIn("codex-settings: skipped, needs --follow-config-symlinks: shared, on this side: a link to", out)
        code, out, err = self.go(APPLY, "--follow-config-symlinks")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(fsio.look(self.config).kind, fsio.LINK)
        self.assertTrue(elsewhere.read_bytes().startswith(b'model = "x"\n\n# workflow-setup:start codex-settings\n'))
        self.assertEqual(self.limit(), 8)
        report = self.as_json(APPLY, "--follow-config-symlinks")
        self.assertEqual((report["exit_code"], report["plan"]), (0, []))
        code, out, err = self.go(REMOVE, "--follow-config-symlinks")
        self.assertEqual(code, 0)
        self.assertEqual(elsewhere.read_bytes(), b'model = "x"\n')

    @unittest.skipUnless(POSIX, "the view from WSL is rebuilt from symlinks on a POSIX file system")
    def test_a_link_to_the_other_side_is_skipped_and_reported(self) -> None:
        drive = self.root / "drive"
        theirs = drive / "Users" / "someone" / ".codex" / "config.toml"
        theirs.parent.mkdir(parents=True)
        theirs.write_bytes(b'sandbox_mode = "workspace-write"\n')
        os.symlink(str(theirs), self.config)
        wsl = homes.Host(homes.WSL, {"PATH": ""}, (str(drive),))
        before = tree(drive)
        for more in ((), ("--follow-config-symlinks",)):
            code, out, err = self.go(APPLY, *more, host=wsl)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(tree(drive), before)
            self.assertIn("codex-settings: skipped: other side (windows): a link to", out)
        code, findings = self.only("codex-settings", host=wsl)
        self.assertFinding(findings, doctor.INFO, "would skip the file", "the windows side's")
        self.assertFinding(findings, doctor.INFO, 'sandbox_mode = "workspace-write"')


class DoctorReportCase(SettingsCase):
    def would(self, findings: list[dict], *words: str) -> str:
        return self.assertFinding(findings, doctor.INFO, "render --apply-codex-settings would now:", *words)

    def test_no_file(self) -> None:
        findings = self.settings()
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, f"{LIMIT}: unset", "needs 8 or more")
        self.assertFinding(findings, doctor.INFO, "setup has written no block into the file")
        self.would(findings, f"{LIMIT}: set to 8 in setup's block at the end of the file")
        self.would(findings, "permission profile: not written", "--default-codex-permissions was not given")
        self.assertFinding(findings, doctor.INFO, "would print the permission profile `workflow` as text")
        self.assertFalse(self.config.exists())
        self.assertFalse(self.manifest_file.exists())

    def test_the_limit_too_low_enough_and_out_of_reach(self) -> None:
        self.user(f"[agents]\n{KEY} = 6\n")
        findings = self.settings()
        self.assertFinding(findings, doctor.WARNING, f"{LIMIT} = 6: below 8")
        self.would(findings, "your file sets it to 6", "raising it is yours to do")
        self.user(f"[agents]\n{KEY} = 9\n")
        findings = self.settings()
        self.assertQuiet(findings)
        self.would(findings, "your file sets it to 9", "that is enough")
        self.user("[agents]\nenabled = true\n")
        findings = self.settings()
        self.would(findings, f"{LIMIT}: not written", f"Add this line to your [agents] table: {KEY} = 8")
        self.user("agents.enabled = true\n")
        self.would(self.settings(), "as a dotted key in setup's block at the head of the file")

    def test_the_wait_floor_unset_written_low_and_out_of_order(self) -> None:
        findings = self.settings()
        self.assertFinding(findings, doctor.INFO, f"{WAIT}.{MIN}: unset", "Codex's own floor of 10000 ms",
                           "needs 300000 or more")
        self.would(findings, f"{WAIT}.{MIN}: set to 300000, with {DEF} = 3600000, in setup's block")
        self.apply()
        findings = self.settings()
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.OK, f"{WAIT}.{MIN} = 300000")
        self.assertFinding(findings, doctor.INFO, f"{WAIT}.{DEF} = 3600000")
        self.assertFalse(any(MAX in found["detail"] for found in findings))
        self.assertFinding(findings, doctor.INFO, "would change nothing")
        self.go(REMOVE)
        self.user(f"[{WAIT}]\n{MIN} = 60000\n")
        findings = self.settings()
        self.assertFinding(findings, doctor.WARNING, f"{WAIT}.{MIN} = 60000: below 300000")
        self.would(findings, f"{WAIT}: your file defines it", "raising it is yours to do",
                   f"Add to that table, in the form your file gives it: {DEF} = 3600000")
        self.user(f"[{WAIT}]\n{MIN} = 300000\n")
        findings = self.settings()
        self.assertFinding(findings, doctor.OK, f"{WAIT}.{MIN} = 300000")
        self.assertFinding(findings, doctor.WARNING, f"{WAIT}: Codex refuses a config unless",
                           "default_wait_timeout_ms 30000 (Codex's own)")
        self.would(findings, "the floor is met", f"Add to that table, in the form your file gives it: {DEF} = 3600000")
        self.user(f'[{WAIT}]\n{MIN} = "long"\n')
        self.assertFinding(self.settings(), doctor.WARNING, f"{WAIT}.{MIN} = \"long\": not a whole number")
        self.user("[features]\nmulti_agent_v2 = true\n")
        findings = self.settings()
        self.assertFinding(findings, doctor.INFO, f"{WAIT}.{MIN}: unset")
        self.would(findings, f"Your file sets {WAIT} itself, to a value that is not a table")

    def test_no_value_under_the_wait_table_but_its_keys_is_printed(self) -> None:
        self.user(f'[{WAIT}]\n{MIN} = 300000\n\n[{WAIT}.sub]\ntoken = "{SECRET}"\n')
        for argv in (("--json",), ()):
            code, out, err = self.run_doctor(*MINE, *argv)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("300000", out)
            self.assertNotIn(SECRET, out)
        code, out, err = self.go(APPLY)
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn(SECRET, out)

    def test_sandbox_mode_set(self) -> None:
        self.user('sandbox_mode = "workspace-write"\n')
        findings = self.settings()
        self.assertQuiet(findings)
        self.would(findings, "permission profile: not written", "Setup never changes or removes sandbox_mode",
                   "git commands that write under .git", "go through command-by-command approval")
        self.assertFinding(findings, doctor.INFO, "would print the permission profile `workflow` as text")
        self.assertFinding(findings, doctor.INFO, "gate G4", "is not proved", "--codex-probe")
        self.assertFalse(any("G4 probe, step" in found["detail"] for found in findings))

    def test_sandbox_mode_unset_and_default_permissions_set_or_not(self) -> None:
        self.user('model = "x"\n')
        findings = self.settings()
        self.would(findings, "permission profile: not written. Codex (0.163.0) refuses to load")
        self.assertFalse(any("gate G4" in found["detail"] for found in findings))
        self.user('default_permissions = ":workspace"\n')
        findings = self.settings()
        self.assertFinding(findings, doctor.INFO, 'default_permissions = ":workspace"')
        self.would(findings, "permission profile: `workflow` defined in setup's block")
        self.would(findings, 'default_permissions: your file sets it to ":workspace"; setup leaves it alone',
                   "written and not selected")
        self.assertFalse(any("would print the permission profile" in found["detail"] for found in findings))

    def test_the_blocks_present_and_as_written(self) -> None:
        self.user('model = "x"\n')
        self.apply(DEFAULT, ROOT, "~/trees")
        data = self.config.read_bytes()
        findings = self.settings()
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.OK, f"{LIMIT} = 8")
        self.assertFinding(findings, doctor.OK, "setup's block codex-settings: in the file, as setup wrote it")
        self.assertFinding(findings, doctor.OK, "setup's block codex-settings-top: in the file, as setup wrote it")
        self.assertFinding(findings, doctor.INFO, 'default_permissions = "workflow"')
        asked = "render --apply-codex-settings --worktree-root <the same directory> --default-codex-permissions"
        self.assertFinding(findings, doctor.INFO, f"{asked} would change nothing: setup's blocks hold what that run writes")
        self.assertFalse(any("would now" in found["detail"] for found in findings))
        self.assertEqual(self.config.read_bytes(), data)
        code, report = self.doctor(*MINE)
        self.assertEqual((report["counts"]["error"], report["counts"]["warning"]), (0, 0), report)
        # The same on a file with CRLF line endings.
        self.go(REMOVE)
        self.user(b'model = "x"\r\n')
        self.apply()
        self.assertFinding(self.settings(), doctor.INFO, "would change nothing")

    def test_the_blocks_present_and_no_longer_what_a_run_would_write(self) -> None:
        self.user('model = "x"\n')
        self.apply(DEFAULT)
        self.config.write_bytes(self.config.read_bytes().replace(b'model = "x"', b'sandbox_mode = "read-only"'))
        findings = self.settings()
        self.assertFinding(findings, doctor.OK, "setup's block codex-settings: in the file, as setup wrote it")
        self.assertFinding(findings, doctor.INFO, "--default-codex-permissions would now: permission profile: not written")
        self.assertFinding(findings, doctor.INFO, 'default_permissions = "workflow"', "not used while sandbox_mode is set")
        # The run then takes the profile and its selection out again, and keeps the limit.
        self.apply()
        self.assertNotIn("permissions", self.loaded())
        self.assertNotIn("default_permissions", self.loaded())
        self.assertEqual(self.limit(), 8)
        self.assertEqual(self.loaded()["sandbox_mode"], "read-only")

    def test_a_block_edited_by_hand(self) -> None:
        self.user('model = "x"\n')
        self.apply()
        self.config.write_bytes(self.config.read_bytes().replace(f"{KEY} = 8".encode(), f"{KEY} = 3".encode()))
        findings = self.settings()
        self.assertFinding(findings, doctor.WARNING, f"{LIMIT} = 3: below 8")
        self.assertFinding(findings, doctor.INFO, "setup's block codex-settings: in the file, and changed by hand")
        code, edits = self.only("hand-edits")
        self.assertFinding(edits, doctor.WARNING, "config.toml: block codex-settings", "changed by hand")

    def test_a_block_the_record_does_not_list(self) -> None:
        self.apply()
        os.remove(self.manifest_file)
        findings = self.settings()
        self.assertFinding(findings, doctor.INFO, "in the file, and the record does not list it")

    def test_no_other_value_of_the_file_is_printed(self) -> None:
        self.user(
            f'model = "{SECRET}-model"\nsandbox_mode = "read-only"\napi_key = "{SECRET}"\n\n'
            f'[agents]\nmax_threads = 2\ntoken = "{SECRET}"\n\n'
            f'[mcp_servers.one.env]\nTOKEN = "{SECRET}"\n\n[permissions.workflow]\ndescription = "{SECRET}"\n'
        )
        for argv in (("--json",), (), ("--codex-probe",), ("--json", "--codex-probe")):
            code, out, err = self.run_doctor(*MINE, *argv)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("read-only", out)
            self.assertIn("agents.max_threads, the legacy alias", out)
            self.assertNotIn(SECRET, out)
            self.assertNotIn("sk-doctor", out)

    def test_a_broken_file_names_only_the_fault(self) -> None:
        self.user(f'api_key = "{SECRET}"\nsandbox_mode = {SECRET}\n')
        code, out, err = self.run_doctor("--only", "codex-settings", "--codex-probe")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("is not valid TOML (line 2, column", out)
        self.assertNotIn(SECRET, out)
        self.user(f'api_key = "{SECRET}"\n# workflow-setup:end codex-settings\n')
        code, out, err = self.run_doctor("--only", "codex-settings")
        self.assertIn("warning: ", out)
        self.assertIn("setup's markers in it cannot be read: line 2", out)
        self.assertNotIn(SECRET, out)

    def test_doctor_writes_nothing(self) -> None:
        self.user('sandbox_mode = "workspace-write"\n')
        self.apply()
        before = tree(self.root)
        self.run_doctor(*MINE, "--codex-probe")
        self.run_doctor(*MINE, "--json")
        self.assertEqual(tree(self.root), before)


# The Manager's model and effort in the head block (R2.1 to R2.3 of sprint 03).
SOL = '"gpt-6.1-sol"'
PINNED = f'model = {SOL}, model_reasoning_effort = "medium"'
USERS = 'model = "gpt-6-luna"\nmodel_reasoning_effort = "high"\n\n[features]\nfast = true\n'


class PinCase(SettingsCase):
    """A Manager loaded on both providers, deep tier and medium effort:
    on Codex gpt-6.1-sol at medium. These runs render the roles."""

    def setUp(self) -> None:
        super().setUp()
        self.source(self.clone, "manager", tier="deep", load="true")

    def go(self, *argv: str, host: homes.Host | None = None) -> tuple[int, str, str]:
        return self.render(*argv, host=host)

    def pin(self) -> tuple:
        loaded = self.loaded()
        return loaded.get("model"), loaded.get("model_reasoning_effort")

    def line(self, number: int) -> str:
        return self.config.read_bytes().decode("utf-8").split("\n")[number - 1]

    def test_written_into_a_file_with_no_head_block_and_read_back(self) -> None:
        original = self.user('approval_policy = "never"\n\n[features]\nfast = true\n\n[agents.reviewer]\ndescription = "r"\n')
        out = self.apply()
        self.assertTrue(self.config.read_bytes().startswith(b"# workflow-setup:start codex-settings-top\n"))
        self.assertEqual(self.pin(), ("gpt-6.1-sol", "medium"))
        self.assertEqual(self.loaded()["features"], {"fast": True, "multi_agent_v2": FLOOR})
        self.assertEqual(self.loaded()["agents"], {"reviewer": {"description": "r"}, KEY: 8})
        self.assertEqual(self.without_blocks(), original)
        top = self.block(codexsettings.TOP_BLOCK).decode("utf-8")
        self.assertIn("# Pins the Manager's model and effort: every plain `codex` session in this home starts on "
                      f"them.\nmodel = {SOL}\nmodel_reasoning_effort = \"medium\"\n", top)
        self.assertIn(f"model: the Manager's {PINNED}, set in setup's block at the head of the file: every plain "
                      "codex session in this home starts on them", out)
        findings = self.settings()
        self.assertQuiet(findings)
        self.assertFinding(findings, doctor.INFO, "would change nothing")
        self.assertEqual(self.statuses(self.as_json(APPLY)), {
            codexsettings.BLOCK: render.UP_TO_DATE, codexsettings.TOP_BLOCK: render.UP_TO_DATE,
        })

    def test_written_beside_a_head_block_of_the_others(self) -> None:
        original = self.user('model_provider = "x"\nagents.enabled = true\n\n[permissions.other]\nextends = ":workspace"\n')
        self.apply(DEFAULT)
        self.assertEqual(self.pin(), ("gpt-6.1-sol", "medium"))
        self.assertEqual(self.loaded()["default_permissions"], "workflow")
        self.assertEqual(self.loaded()["agents"], {"enabled": True, KEY: 8})
        self.assertEqual(self.without_blocks(), original)
        top = self.block(codexsettings.TOP_BLOCK).decode("utf-8")
        self.assertLess(top.index("model = "), top.index("default_permissions = "))
        self.assertLess(top.index("model = "), top.index(f"{LIMIT} = 8"))
        self.assertQuiet(self.settings())

    def test_the_users_own_keys_at_the_top_are_left_and_quoted(self) -> None:
        # The Windows home: lines 1 and 2 set both keys.
        original = self.user(USERS)
        out = self.apply()
        self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
        self.assertEqual(self.pin(), ("gpt-6-luna", "high"))
        self.assertEqual(self.without_blocks(), original)
        self.assertIn(
            "model: the Manager's model is not pinned. Your file sets model and model_reasoning_effort outside "
            "setup's blocks, and a key given twice is not valid TOML, so setup writes neither. Delete these "
            'lines yourself and run render --apply-codex-settings again: line 1: model = "gpt-6-luna"; line 2: '
            f'model_reasoning_effort = "high". Until they are gone the Manager\'s {PINNED.replace(", ", " and ")} are not pinned', out)
        findings = self.settings()
        detail = self.assertFinding(findings, doctor.WARNING, "the Manager's model is not pinned",
                                    'line 1: model = "gpt-6-luna"', 'line 2: model_reasoning_effort = "high"')
        self.assertEqual(len([found for found in findings if found["detail"] == detail]), 1)
        self.assertFalse(any("would now: model:" in found["detail"] for found in findings))
        # With a head block written above them, the numbers are those of the file the run leaves.
        out = self.apply(DEFAULT)
        self.assertIsNotNone(self.block(codexsettings.TOP_BLOCK))
        numbers = [int(word) for word in re.findall(r"line (\d+): model", out)]
        self.assertEqual(len(numbers), 2, out)
        self.assertEqual(self.line(numbers[0]), 'model = "gpt-6-luna"')
        self.assertEqual(self.line(numbers[1]), 'model_reasoning_effort = "high"')
        self.assertFinding(self.settings(), doctor.WARNING, f"line {numbers[0]}: model", f"line {numbers[1]}: model")
        self.assertEqual(self.pin(), ("gpt-6-luna", "high"))

    def test_a_line_inside_a_multi_line_value_ends_no_scan_for_the_users_keys(self) -> None:
        # Line 2 starts with "[" and line 4 with "model", both inside the array; line 7 is the user's key.
        self.user('notify = [\n  ["a", "]"],\n  """\nmodel = "no"\n""",\n]\nmodel = "gpt-6-luna"\n\n[x]\ny = 1\n')
        out = self.apply()
        self.assertIn('Delete this line yourself and run render --apply-codex-settings again: line 7: '
                      'model = "gpt-6-luna"', out)
        self.assertFinding(self.settings(), doctor.WARNING, 'line 7: model = "gpt-6-luna"')
        # An inline table over several lines (TOML 1.1) is a value too.
        self.assertEqual(codexsettings.key_lines(b'a = {\n  [b] = 1,\n  model = "no"\n}\nmodel = "x"\n'), {"model": 5})

    def test_the_numbers_are_those_of_the_file_a_dry_run_or_a_kept_block_leaves(self) -> None:
        self.user(USERS)
        # A dry run writes no head block above the user's lines: they keep their numbers.
        code, out, err = self.go(APPLY, DEFAULT, "--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertIn('line 1: model = "gpt-6-luna"; line 2: model_reasoning_effort = "high"', " ".join(out.split()))
        self.assertEqual(self.config.read_bytes().decode("utf-8"), USERS)
        # A head block edited by hand is kept as it is, and the numbers count its lines as they are.
        self.apply(DEFAULT)
        data = self.config.read_bytes()
        self.config.write_bytes(data.replace(b"# workflow-setup:start codex-settings-top\n",
                                             b"# workflow-setup:start codex-settings-top\n# mine\n# mine too\n", 1))
        edited = self.config.read_bytes()
        code, out, err = self.go(APPLY, DEFAULT)
        self.assertEqual(code, render.EXIT_NEEDS_FLAG, out + err)
        self.assertEqual(self.config.read_bytes(), edited)
        numbers = [int(word) for word in re.findall(r"line (\d+): model", out)]
        self.assertEqual(len(numbers), 2, out)
        self.assertEqual(self.line(numbers[0]), 'model = "gpt-6-luna"')
        self.assertEqual(self.line(numbers[1]), 'model_reasoning_effort = "high"')
        self.assertFinding(self.settings(), doctor.WARNING, f"line {numbers[0]}: model", f"line {numbers[1]}: model")

    def test_a_run_stopped_on_an_error_numbers_the_lines_where_they_still_are(self) -> None:
        self.user(USERS)
        # A file of the user's where a skill's link goes: the run stops, and no head block is written.
        self.keep(self.claude_skills / "alpha" / "SKILL.md")
        code, out, err = self.go(APPLY, DEFAULT)
        self.assertEqual(code, render.EXIT_ERROR, out + err)
        self.assertEqual(self.config.read_bytes().decode("utf-8"), USERS)
        self.assertIn('line 1: model = "gpt-6-luna"; line 2: model_reasoning_effort = "high"',
                      " ".join((out + err).split()))

    def test_before_any_block_doctor_says_what_a_run_would_leave(self) -> None:
        self.user(USERS)
        findings = self.settings()
        self.assertFinding(findings, doctor.INFO, "would now: model: the Manager's model is not pinned",
                           'line 1: model = "gpt-6-luna"')
        self.assertFalse(any("not pinned" in detail for detail in self.details(findings, doctor.WARNING)))

    def test_one_key_of_the_users_stops_both_and_no_comment_of_the_line_is_printed(self) -> None:
        original = self.user(f'# mine\nmodel_reasoning_effort = "high"  # {SECRET}\n')
        out = self.apply()
        self.assertEqual(self.pin(), (None, "high"))
        self.assertEqual(self.without_blocks(), original)
        self.assertIn("model_reasoning_effort is yours, setup pins the model and the effort together, and a key "
                      "given twice is not valid TOML, so setup writes neither", out)
        self.assertNotIn("second top-level", out)
        self.assertIn('Delete this line yourself and run render --apply-codex-settings again: line 2: '
                      'model_reasoning_effort = "high". Until it is gone', out)
        self.assertNotIn(SECRET, out)
        for argv in ((), ("--json",)):
            code, report, err = self.run_doctor(*MINE, *argv)
            self.assertNotIn(SECRET, report + err)

    def test_no_manager_writes_none_and_takes_them_out_of_an_earlier_block(self) -> None:
        original = self.user("[features]\nfast = true\n")
        self.apply()
        self.assertEqual(self.pin(), ("gpt-6.1-sol", "medium"))
        self.write(self.user_file, "[roles]\nenabled = false\n")
        detail = self.assertFinding(self.settings(), doctor.WARNING, f"setup's block codex-settings-top pins {PINNED}",
                                    "the Manager is not installed for Codex as a loadable role now")
        self.assertIn("render --apply-codex-settings takes model and model_reasoning_effort out", detail)
        out = self.apply()
        self.assertEqual(self.pin(), (None, None))
        self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
        self.assertEqual(self.without_blocks(), original)
        self.assertIn(f"the earlier block pinned the Manager's {PINNED}, and in this run the Manager is not "
                      "installed for Codex as a loadable role", out)
        self.assertQuiet(self.settings())
        # A Manager whose entry.load is false is none to pin either, and --no-roles asks for none.
        self.user_file.unlink()
        self.apply()
        self.assertEqual(self.pin(), ("gpt-6.1-sol", "medium"))
        self.assertIn("taken out", self.apply("--no-roles"))
        self.assertEqual(self.pin(), (None, None))
        self.source(self.clone, "manager", tier="deep", load="false")
        self.apply()
        self.assertEqual(self.pin(), (None, None))

    def test_a_changed_effort_is_a_doctor_warning_until_the_next_run(self) -> None:
        self.user("")
        self.apply()
        self.write(self.user_file, '[roles.manager]\neffort = "high"\n')
        findings = self.settings()
        self.assertFinding(findings, doctor.WARNING, f"setup's block codex-settings-top pins {PINNED}",
                           f'the Manager now resolves to model = {SOL}, model_reasoning_effort = "high"',
                           "render --apply-codex-settings writes the Manager's current ones")
        self.assertFinding(findings, doctor.INFO, "would now: model: the Manager's", '"high"')
        self.apply()
        self.assertEqual(self.pin(), ("gpt-6.1-sol", "high"))
        self.assertQuiet(self.settings())

    def test_a_pin_changed_in_the_block_by_hand_is_the_hand_edit_report(self) -> None:
        # What Codex's /model does where the key is: it changes it in place.
        self.user("")
        self.apply()
        self.config.write_bytes(self.config.read_bytes().replace(b'"medium"', b'"xhigh"'))
        self.assertEqual(self.pin(), ("gpt-6.1-sol", "xhigh"))
        findings = self.settings()
        self.assertFinding(findings, doctor.INFO, "setup's block codex-settings-top: in the file, and changed by hand")
        self.assertFalse(any("pins" in detail for detail in self.details(findings, doctor.WARNING)))
        code, edits = self.only("hand-edits")
        self.assertFinding(edits, doctor.WARNING, "config.toml: block codex-settings-top", "changed by hand")

    def test_removal_takes_them_out_with_the_block(self) -> None:
        original = self.user('approval_policy = "never"\n')
        self.apply()
        self.assertEqual(self.pin(), ("gpt-6.1-sol", "medium"))
        code, out, err = self.go(REMOVE)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.recorded(), {})

    def test_the_pin_keys_are_keys_doctor_may_print(self) -> None:
        self.assertLessEqual(set(codexsettings.PIN_KEYS), set(doctor.CODEX_KEYS))
        self.assertLessEqual(set(codexsettings.PIN_KEYS), set(codexsettings.KEYS))


class ProbeCase(SettingsCase):
    def steps(self) -> list[str]:
        findings = self.settings("--codex-probe")
        return [found["detail"] for found in findings if found["detail"].startswith("G4 probe")]

    def test_the_steps_for_a_writable_sandbox_mode(self) -> None:
        self.user('sandbox_mode = "workspace-write"\n')
        steps = self.steps()
        text = "\n".join(steps)
        self.assertIn("doctor starts none", steps[0])
        self.assertIn('sandbox_mode = "workspace-write"', steps[0])
        self.assertIn("codex -c \"default_permissions=':read-only'\"", text)
        self.assertIn("git init; git commit --allow-empty -m first", text)
        self.assertIn("Create an empty file named g4-probe.txt in this directory", text)
        self.assertIn("outcome A: the file is created without a question: the override was ignored", text)
        self.assertIn("outcome B: Codex asks for approval, or the sandbox refuses the write: the override was "
                      "honoured", text)
        self.assertIn("Run `git commit --allow-empty -m probe`", text)
        self.assertEqual(steps, codexsettings.probe_lines("workspace-write"))

    def test_the_steps_for_a_read_only_sandbox_mode_use_the_opposite_profile(self) -> None:
        self.user('sandbox_mode = "read-only"\n')
        text = "\n".join(self.steps())
        self.assertIn("codex -c \"default_permissions=':workspace'\"", text)
        self.assertIn("outcome A: Codex asks for approval, or the sandbox refuses the write: the override was "
                      "ignored", text)

    def test_without_sandbox_mode_the_probe_does_not_apply(self) -> None:
        self.user('model = "x"\n')
        self.assertEqual(len(self.steps()), 1)
        self.assertIn("does not apply here", self.steps()[0])

    def test_each_step_is_one_line_and_help_names_the_options(self) -> None:
        for line in codexsettings.probe_lines("workspace-write"):
            self.assertNotIn("\n", line)
        code, out, err = self.run_doctor("--help")
        self.assertIn("--codex-probe", out)
        code, out, err = self.go("--help")
        for option in (APPLY, REMOVE, DEFAULT, ROOT):
            self.assertIn(option, out)


if __name__ == "__main__":
    unittest.main()
