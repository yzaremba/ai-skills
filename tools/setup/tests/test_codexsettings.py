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
        self.assertEqual(self.loaded()["features"], {"fast": True})
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
                        self.assertEqual(after[key], value)
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
        original = self.user(f'sandbox_mode = "read-only"\n\n[agents]\n{KEY} = 8\n')
        before = tree(self.home)
        report = self.as_json(APPLY)
        self.assertEqual(self.statuses(report), {codexsettings.BLOCK: render.UP_TO_DATE})
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.recorded(), {})
        self.assertFalse(any("config.toml" in line for line in report["plan"]))
        self.assertEqual(tree(self.home)[".codex/config.toml"], before[".codex/config.toml"])

    def test_without_sandbox_mode_the_profile_is_defined_and_not_selected(self) -> None:
        original = self.user('model = "x"\n')
        out = self.apply()
        self.assertTrue(self.config.read_bytes().startswith(original))
        self.assertEqual(self.profile(), codexsettings.profile_data(None))
        self.assertEqual(self.profile()["extends"], ":workspace")
        self.assertEqual(self.profile()["filesystem"], {":workspace_roots": {".git": "write"}})
        self.assertNotIn("default_permissions", self.loaded())
        self.assertIsNone(self.block(codexsettings.TOP_BLOCK))
        self.assertIn("permission profile: `workflow` defined in setup's block at the end of the file", out)
        self.assertIn("the profile is not selected: start Codex with codex -c \"default_permissions='workflow'\"", out)
        self.assertIn("permission profiles are beta in Codex", out)
        self.assertIn("no worktree root is in the profile", out)
        self.assertIn("a session started inside a linked git worktree", out)

    def test_the_default_flag_selects_it_in_a_block_at_the_head(self) -> None:
        original = self.user('model = "x"\n\n[features]\nfast = true\n')
        out = self.apply(DEFAULT)
        data = self.config.read_bytes()
        self.assertTrue(data.startswith(b"# workflow-setup:start codex-settings-top\n"))
        self.assertEqual(self.without_blocks(), original)
        self.assertEqual(self.loaded()["default_permissions"], "workflow")
        self.assertEqual(self.loaded()["features"], {"fast": True})
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
                self.apply()
                found = self.loaded()["permissions"]
                self.assertEqual(found["workflow"], codexsettings.profile_data(None))
                self.assertEqual({key: value for key, value in found.items() if key != "workflow"},
                                 tomllib.loads(text)["permissions"])

    def test_a_permissions_value_that_takes_no_table_is_reported(self) -> None:
        original = self.user("permissions = 3\n")
        out = self.apply()
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
        out = self.apply(ROOT, str(trees))
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
        out = self.apply(ROOT, str(trees) + os.sep + "." + os.sep)
        self.assertEqual(self.written(), [str(trees)])
        self.assertIn(f"the worktree root {trees} is not a directory on this machine yet", out)

    def test_a_home_path_is_kept_as_written(self) -> None:
        for given, written in (("~/work trees", "~/work trees"), ("~/a//b/", "~/a/b")):
            with self.subTest(given):
                self.apply(ROOT, given)
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
        self.apply(ROOT, str(trees))
        out = self.apply()
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
        self.would(findings, "permission profile: `workflow` defined in setup's block")
        self.would(findings, "the profile is not selected")
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
        self.would(findings, "the profile is not selected")
        self.assertFalse(any("gate G4" in found["detail"] for found in findings))
        self.user('default_permissions = ":workspace"\n')
        findings = self.settings()
        self.assertFinding(findings, doctor.INFO, 'default_permissions = ":workspace"')
        self.would(findings, 'default_permissions: your file sets it to ":workspace"; setup leaves it alone')

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
