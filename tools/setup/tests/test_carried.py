"""Tests for what the Codex profile carries that is not setup's: whatever
Codex or the user added after setup's part, such as the ``projects`` table
Codex writes into it when the user answers "trust this project?", or its
``[notice]`` flags (``carried``).

Run from the repository root:
    python -B -m unittest discover -s tools/setup/tests

Every home is a scratch directory, rendered from the fixture clone of
``test_entry``, whose starting role is ``lead``; its profile is
``.codex/lead.config.toml``. What Codex adds is written the way Codex
0.162.1 wrote it: a table appended after the rest of the file.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
import unittest
from unittest import mock

import support
from test_doctor import DoctorCase
from test_entry import PROFILE
from wfsetup import carried, doctor, entry, fileops, homes, manifest, render
from wfsetup.errors import SetupError

KEY = "home:" + PROFILE
SETUP_KEYS = ["model", "model_reasoning_effort", "developer_instructions"]

# One answer, as Codex appends it.
TRUST_ONE = b'\n[projects."/srv/work/alpha"]\ntrust_level = "trusted"\n'
# Several, with Windows paths: a literal key with backslashes and a drive
# letter, a basic key with escaped backslashes, a space and quotes.
TRUST_MANY = (
    b'\n[projects."/srv/work/alpha"]\ntrust_level = "trusted"\n'
    b"\n[projects.'C:\\work\\beta']\ntrust_level = \"trusted\"\n"
    b'\n[projects."D:\\\\work\\\\gamma \\"q\\" d"]\ntrust_level = "untrusted"\n'
)
MANY_KEYS = {"/srv/work/alpha", "C:\\work\\beta", 'D:\\work\\gamma "q" d'}
# Other state of Codex's interface, kept in the same layer.
NOTICE = b"\n[notice]\nhide_full_access_warning = true\n"
COMMENTS = b"\n# a note of mine\n# and another\n"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parsed(data: bytes) -> dict:
    return tomllib.loads(data.decode("utf-8"))


def projects(data: bytes) -> dict:
    return parsed(data)["projects"]


class CarriedFunctionsCase(unittest.TestCase):
    OWN = b'# Generated.\n\nmodel = "m"\ndeveloper_instructions = """\n[projects.x]\nnot a table\n"""\n'

    def test_the_keys_setup_writes_are_those_of_a_profile(self) -> None:
        self.assertEqual(carried.SETUP_KEYS, entry.BLOCK_KEYS)
        self.assertTrue(entry.PROFILE_SCHEME.startswith(carried.PROFILE_INPUTS))

    def test_split_carries_whatever_follows_setups_part(self) -> None:
        own = digest(self.OWN)
        self.assertEqual(carried.split(self.OWN, own), b"")
        for tail in (TRUST_MANY, b"\n\n", TRUST_ONE + NOTICE, COMMENTS, b'approval_policy = "never"\n' + TRUST_ONE,
                     TRUST_ONE + b"\n[features]\nfast = true\n", b"projects = 1\n",
                     TRUST_ONE + b'model = "inside the projects table"\n'):
            with self.subTest(tail=tail):
                self.assertEqual(carried.split(self.OWN + tail, own), tail)

    def test_split_refuses_a_change_of_setups_part_and_a_key_of_setups(self) -> None:
        own = digest(self.OWN)
        self.assertIsNone(carried.split(self.OWN.replace(b'"m"', b'"n"') + TRUST_ONE, own))
        self.assertIsNone(carried.split(self.OWN + b'model = "mine"\n' + TRUST_ONE, own))
        self.assertIsNone(carried.split(self.OWN + b'model_reasoning_effort = "high"\n', own))
        self.assertIsNone(carried.split(self.OWN + b"[projects\n", own))
        self.assertIsNone(carried.split(self.OWN + TRUST_ONE, None))

    def test_the_hash_of_setups_part_of_an_older_record_is_the_files(self) -> None:
        old = {"kind": "file", "sha256": "a" * 64, "inputs": "render:codex-profile:5:" + "b" * 64}
        self.assertEqual(carried.own_hash(old), "a" * 64)
        self.assertEqual(carried.own_hash({**old, carried.OWN_KEY: "c" * 64}), "c" * 64)
        other = {**old, "inputs": "render:loaded-role:6:" + "b" * 64}
        self.assertIsNone(carried.own_hash(other))
        self.assertIsNone(carried.own_hash({**other, carried.OWN_KEY: "c" * 64}))
        self.assertIsNone(carried.own_hash({**old, "kind": "text"}))

    def test_the_hash_of_setups_part_is_held_by_a_profiles_entry_alone(self) -> None:
        entry_ = {"kind": "file", "sha256": "a" * 64, "inputs": "render:codex-profile:5:" + "d" * 64,
                  "original": None}
        name = "home:.codex/lead.config.toml"
        self.assertIsNone(manifest.entry_fault(name, {**entry_, carried.OWN_KEY: "b" * 64}))
        for bad in ("b" * 63, 7, None):
            self.assertEqual(manifest.entry_fault(name, {**entry_, carried.OWN_KEY: bad}),
                             "the hash of setup's own part is not a hash")
        other = {**entry_, "inputs": "render:loaded-role:6:" + "d" * 64, carried.OWN_KEY: "b" * 64}
        self.assertIn("only a Codex profile's entry", manifest.entry_fault(name, other))

    def test_a_file_setups_part_is_not_in(self) -> None:
        self.assertTrue(carried.no_setup_key(TRUST_MANY))
        self.assertTrue(carried.no_setup_key(COMMENTS + NOTICE))
        self.assertFalse(carried.no_setup_key(b"\n \n"))
        self.assertFalse(carried.no_setup_key(b'model = "m"\n' + TRUST_ONE))
        self.assertFalse(carried.no_setup_key(b"[notice\n"))

    def test_the_keys_of_an_edited_file_read_and_written_anew_read_back_unchanged(self) -> None:
        own = self.OWN.decode("utf-8")
        text, why = carried.extracted(b'model = "mine"\napproval_policy = "never"\n' + TRUST_MANY + NOTICE, own)
        self.assertIsNone(why)
        found = parsed(text.encode("utf-8"))
        self.assertEqual(found, {"approval_policy": "never", "projects": projects(TRUST_MANY),
                                 "notice": {"hide_full_access_warning": True}})
        self.assertEqual(set(found["projects"]), MANY_KEYS)
        self.assertEqual(carried.extracted(b'model = "mine"\n', own), ("", None))
        text, why = carried.extracted(b"model = \n", own)
        self.assertEqual(text, "")
        self.assertIn("not valid TOML", why)
        with self.assertRaises(SetupError):
            carried.extracted(b'[projects."/a"]\nwhen = 1979-05-27\n', own)

    def test_line_ends_become_lf_and_the_rest_stays(self) -> None:
        crlf = (TRUST_MANY + COMMENTS + NOTICE).replace(b"\n", b"\r\n")
        text = carried.tail_text(crlf)
        self.assertEqual(text.encode("utf-8"), TRUST_MANY + COMMENTS + NOTICE)
        self.assertEqual(carried.tail_text(TRUST_MANY), TRUST_MANY.decode("utf-8"))
        self.assertEqual(carried.tail_text(b"\n \n"), "")

    def test_join_checks_the_result(self) -> None:
        own = self.OWN.decode("utf-8")
        whole = carried.join(own, (TRUST_MANY + NOTICE).decode("utf-8"))
        self.assertEqual(whole.encode("utf-8"), self.OWN + TRUST_MANY + NOTICE)
        self.assertEqual(carried.join(own, ""), own)
        with self.assertRaises(SetupError):
            carried.join(own, 'model = "mine"\n')
        with self.assertRaises(SetupError):
            carried.join(own.rstrip("\n"), TRUST_ONE.decode("utf-8"))
        with self.assertRaises(SetupError):
            carried.join(own, "[notice\n")


class CarryCase(DoctorCase):
    """A rendered home whose profile Codex has written into."""

    def setUp(self) -> None:
        super().setUp()
        self.ok()
        self.file = self.home / PROFILE
        self.generated = self.file.read_bytes()

    # --- Helpers -------------------------------------------------------------

    def add(self, tail: bytes) -> bytes:
        self.file.write_bytes(self.file.read_bytes() + tail)
        return self.file.read_bytes()

    def change_source(self) -> None:
        role = self.clone / "roles" / "lead" / "ROLE.md"
        role.write_bytes(role.read_bytes() + b"\nOne more line.\n")

    def profile_item(self, report: dict) -> dict:
        for provider in report["providers"]:
            for place in provider["places"]:
                for item in place["items"]:
                    if item["key"] == KEY:
                        return item
        self.fail(f"no item for {KEY}")

    def assertClean(self) -> None:
        for check in ("hand-edits", "drift"):
            code, findings = self.only(check)
            self.assertEqual(code, 0, findings)
            self.assertQuiet(findings)

    def assertSetupsPart(self, data: bytes, tail: bytes) -> bytes:
        """``data`` is setup's text as generated now, then ``tail``."""
        self.assertTrue(data.endswith(tail), data)
        head = data[:len(data) - len(tail)]
        self.assertEqual(list(parsed(head)), SETUP_KEYS)
        record = self.entries()[KEY]
        self.assertEqual(record[carried.OWN_KEY], digest(head))
        self.assertEqual(record["sha256"], digest(data))
        return head

    def uninstall(self, code: int = 0) -> dict:
        with mock.patch.object(homes.Host, "current", classmethod(lambda cls: self.host)):
            got, out, err = support.run("uninstall", "--json", "--home", str(self.home))
        self.assertEqual((got, err), (code, ""), out)
        return json.loads(out)

    # --- Render --------------------------------------------------------------

    def test_the_record_holds_the_hash_of_setups_part(self) -> None:
        self.assertSetupsPart(self.generated, b"")

    def test_one_trust_entry_is_carried_over_when_the_profile_is_written_again(self) -> None:
        self.add(TRUST_ONE)
        self.assertClean()
        self.change_source()
        code, report, err = self.report()
        self.assertEqual((code, err), (0, ""))
        item = self.profile_item(report)
        self.assertEqual(item["status"], render.UPDATE)
        self.assertIn("what Codex or you added after setup's part kept", item["says"])
        data = self.file.read_bytes()
        head = self.assertSetupsPart(data, TRUST_ONE)
        self.assertIn(b"One more line.", head)
        self.assertNotEqual(head, self.generated)
        self.assertEqual(projects(data), projects(TRUST_ONE))
        self.assertClean()
        code, report, _ = self.report()
        self.assertEqual((code, report["plan"]), (0, []))
        self.assertEqual(self.profile_item(report)["status"], render.UP_TO_DATE)

    def test_several_entries_with_windows_paths_are_carried_over_exactly(self) -> None:
        self.add(TRUST_MANY)
        self.assertClean()
        self.change_source()
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(self.profile_item(report)["status"], render.UPDATE)
        data = self.file.read_bytes()
        self.assertSetupsPart(data, TRUST_MANY)
        self.assertEqual(set(projects(data)), MANY_KEYS)
        self.assertEqual(projects(data), projects(TRUST_MANY))
        self.assertClean()

    def test_codexs_notice_flags_comments_and_keys_of_yours_are_carried_too(self) -> None:
        for tail in (TRUST_ONE + NOTICE, COMMENTS, b'my_own = "x"\n' + TRUST_ONE + NOTICE):
            with self.subTest(tail=tail):
                self.file.unlink()
                self.ok()
                self.add(tail)
                self.assertClean()
                self.change_source()
                code, report, _ = self.report()
                self.assertEqual((code, self.profile_item(report)["status"]), (0, render.UPDATE))
                self.assertSetupsPart(self.file.read_bytes(), tail)
                self.assertClean()

    def test_codexs_own_keys_are_carried_without_a_word(self) -> None:
        self.add(TRUST_ONE + NOTICE)
        self.change_source()
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertNotIn("besides what Codex writes there", self.profile_item(report)["says"])
        code, findings = self.only("hand-edits")
        self.assertEqual([found for found in findings if found["severity"] != doctor.OK], [])

    def test_any_other_key_is_carried_and_named(self) -> None:
        self.add(b'\nmy_own = "x"\nsandbox_mode = "workspace-write"\n' + TRUST_ONE)
        self.change_source()
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        says = self.profile_item(report)["says"]
        self.assertIn("besides what Codex writes there it holds my_own, sandbox_mode", says)
        self.assertIn("(sandbox_mode changes what a session may do; see doctor)", says)
        code, findings = self.only("hand-edits")
        self.assertFinding(findings, doctor.INFO, KEY, "my_own", "Codex does not write there itself")
        detail = self.assertFinding(findings, doctor.WARNING, KEY, "sandbox_mode is set after setup's part")
        self.assertIn("older sandbox settings", detail)
        self.assertIn("ignores the permission profile", detail)
        self.assertNotIn("edited by hand", " ".join(found["detail"] for found in findings))

    def test_each_risky_key_is_a_warning(self) -> None:
        self.assertEqual(set(carried.RISKS), {
            "sandbox_mode", "approval_policy", "default_permissions", "permissions", "model_provider",
            "model_providers", "model_instructions_file", "profile", "profiles", "mcp_servers",
        })
        self.add(b'\napproval_policy = "never"\nmodel_provider = "other"\n\n[mcp_servers.x]\ncommand = "y"\n')
        code, findings = self.only("hand-edits")
        for name in ("approval_policy", "model_provider", "mcp_servers"):
            self.assertFinding(findings, doctor.WARNING, KEY, f"{name} is set after setup's part", carried.RISKS[name])

    def test_codex_settings_says_what_the_profile_sets(self) -> None:
        self.add(b'\nsandbox_mode = "workspace-write"\ndefault_permissions = "mine"\n' + TRUST_ONE)
        code, findings = self.only("codex-settings")
        self.assertFinding(findings, doctor.INFO, KEY, 'sets sandbox_mode = "workspace-write" after setup\'s part')
        self.assertFinding(findings, doctor.INFO, KEY, 'sets default_permissions = "mine" after setup\'s part')
        unset = [found["detail"] for found in findings if found["detail"].startswith("sandbox_mode: unset")]
        self.assertTrue(all("unset in config.toml" in line for line in unset), unset)

    def test_a_file_of_yours_with_keys_codex_does_not_write_is_not_taken_up(self) -> None:
        self.add(b'\nmy_own = "x"\n' + TRUST_ONE)
        report = self.uninstall()
        self.assertEqual([item["key"] for item in report["left"]], [KEY])
        left = self.file.read_bytes()
        code, out, err = self.render()
        self.assertEqual(code, 2, out)
        self.assertIn("a file is there, and setup did not write it", err)
        self.assertEqual(self.file.read_bytes(), left)

    def test_an_addition_codex_makes_after_a_render_is_no_edit_either(self) -> None:
        self.add(TRUST_ONE)
        self.change_source()
        self.ok()
        more = b'\n[projects."/srv/work/delta"]\ntrust_level = "trusted"\n' + NOTICE
        self.add(more)
        self.assertClean()
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        self.assertEqual(self.profile_item(report)["status"], render.UP_TO_DATE)
        self.assertSetupsPart(self.file.read_bytes(), TRUST_ONE + more)

    def test_an_older_record_without_the_hash_of_setups_part(self) -> None:
        record = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        del record["entries"][KEY][carried.OWN_KEY]
        self.manifest_file.write_bytes(json.dumps(record).encode("utf-8"))
        self.add(TRUST_ONE)
        self.assertClean()
        self.change_source()
        code, report, _ = self.report()
        self.assertEqual((code, self.profile_item(report)["status"]), (0, render.UPDATE))
        self.assertSetupsPart(self.file.read_bytes(), TRUST_ONE)

    def test_a_change_of_setups_part_or_one_of_its_keys_set_again_is_a_hand_edit(self) -> None:
        for edited in (
            self.generated.replace(b'model = "gpt-6.1-sol"', b'model = "my-own"') + TRUST_ONE,
            self.generated + b'model = "my-own"\n' + TRUST_ONE,
            self.generated + b'model_reasoning_effort = "high"\n',
            TRUST_MANY.lstrip(b"\n"),   # setup's part taken out
        ):
            with self.subTest(edited=edited[-60:]):
                self.file.write_bytes(edited)
                self.change_source()
                code, report, _ = self.report()
                self.assertEqual(code, render.EXIT_NEEDS_FLAG)
                item = self.profile_item(report)
                self.assertEqual(item["status"], render.EDITED)
                self.assertIn("edited by hand since setup wrote it, and kept", item["says"])
                self.assertEqual(self.file.read_bytes(), edited)
                code, findings = self.only("hand-edits")
                self.assertFinding(findings, doctor.WARNING, KEY, "edited by hand")

    def test_overwrite_edited_keeps_every_key_that_is_not_setups_and_backs_the_file_up(self) -> None:
        for edited, rest in (
            (self.generated.replace(b'model = "gpt-6.1-sol"', b'model = "my-own"') + TRUST_MANY,
             {"projects": projects(TRUST_MANY)}),
            (self.generated.replace(b'model = "gpt-6.1-sol"', b'model = "my-own"') + b'my_own = "x"\n'
             + TRUST_MANY + NOTICE,
             {"my_own": "x", "projects": projects(TRUST_MANY),
              "notice": {"hide_full_access_warning": True}}),
        ):
            with self.subTest(edited=edited[-60:]):
                self.file.write_bytes(edited)
                code, report, err = self.report("--overwrite-edited")
                self.assertEqual((code, err), (0, ""))
                item = self.profile_item(report)
                self.assertEqual(item["status"], render.REPLACE)
                self.assertIn("its keys that are not setup's kept", item["says"])
                data = self.file.read_bytes()
                found = parsed(data)
                self.assertEqual(found["model"], "gpt-6.1-sol")
                self.assertEqual({key: found[key] for key in found if key not in SETUP_KEYS}, rest)
                self.assertTrue(data.startswith(self.generated))
                record = json.loads(self.manifest_file.read_text(encoding="utf-8"))
                self.assertIn(digest(edited), [backup.get("sha256") for backup in record["backups"]])
                self.assertEqual(record["entries"][KEY][carried.OWN_KEY], digest(self.generated))
                self.assertClean()
                code, report, _ = self.report()
                self.assertEqual((code, report["plan"]), (0, []))

    def test_a_change_between_reading_and_writing_is_a_conflict(self) -> None:
        self.add(TRUST_ONE)
        plan = fileops.Plan(self.all_roots())
        text = self.generated.decode("utf-8")
        plan.write_file(self.file, text, inputs=self.entries()[KEY]["inputs"], own_sha256=digest(self.generated),
                        made_from=digest(self.generated))
        messages = [problem.message for problem in plan.check()]
        self.assertTrue(any("changed since setup read it" in line for line in messages), messages)

    # --- Taking it out -------------------------------------------------------

    def test_no_roles_leaves_what_was_added_and_a_later_render_takes_it_up(self) -> None:
        self.add(TRUST_MANY + NOTICE)
        code, report, err = self.report("--no-roles")
        self.assertEqual((code, err), (0, ""))
        stale = [item for item in report["stale"] if item["key"] == KEY]
        self.assertEqual([item["status"] for item in stale], [render.RELEASE])
        self.assertIn("left holding what Codex or you added after setup's part", stale[0]["says"])
        self.assertEqual(report["counts"]["file_release"], 1)
        self.assertIn("1 left as yours with setup's part taken out", report["summary"])
        self.assertEqual(self.file.read_bytes(), (TRUST_MANY + NOTICE).lstrip(b"\n"))
        self.assertNotIn(KEY, self.entries())
        code, report, _ = self.report()
        self.assertEqual(code, 0)
        item = self.profile_item(report)
        self.assertEqual(item["status"], render.CREATE)
        self.assertIn("write before what the file there holds", item["says"])
        data = self.file.read_bytes()
        self.assertTrue(data.startswith(self.generated))
        self.assertEqual(data, self.generated + TRUST_MANY + NOTICE)
        self.assertClean()

    def test_uninstall_takes_setups_part_out_and_leaves_the_rest(self) -> None:
        self.add(TRUST_MANY + COMMENTS)
        report = self.uninstall()
        self.assertEqual([item["key"] for item in report["left"]], [KEY])
        self.assertIn("setup's part was taken out", report["left"][0]["why"])
        self.assertEqual(report["kept"], [])
        self.assertFalse(any(KEY in line for line in report["restored"]), report["restored"])
        self.assertIn("1 left as yours", report["summary"])
        self.assertNotIn("restored", report["summary"].split(";")[0].replace("0 restored", ""))
        self.assertEqual(self.file.read_bytes(), (TRUST_MANY + COMMENTS).lstrip(b"\n"))
        self.assertFalse(self.manifest_file.exists())
        # Installed again, the file is taken up with what it holds; and taken back again.
        code, report, _ = self.report()
        self.assertEqual((code, self.profile_item(report)["status"]), (0, render.CREATE))
        self.assertEqual(self.file.read_bytes(), self.generated + TRUST_MANY + COMMENTS)
        self.assertClean()
        report = self.uninstall()
        self.assertEqual([item["key"] for item in report["left"]], [KEY])
        self.assertEqual(self.file.read_bytes(), (TRUST_MANY + COMMENTS).lstrip(b"\n"))

    def test_uninstall_leaves_a_profile_whose_owner_took_setups_part_out(self) -> None:
        self.file.write_bytes(TRUST_ONE.lstrip(b"\n"))
        report = self.uninstall()
        self.assertEqual([item["key"] for item in report["left"]], [KEY])
        self.assertEqual(self.file.read_bytes(), TRUST_ONE.lstrip(b"\n"))

    def test_uninstall_removes_a_profile_that_holds_nothing_else(self) -> None:
        report = self.uninstall()
        self.assertEqual(report["left"], [])
        self.assertNothingAt(self.file)

    def test_uninstall_keeps_a_profile_edited_by_hand_whole(self) -> None:
        edited = self.add(b'model = "mine"\n' + TRUST_ONE)
        report = self.uninstall(code=3)
        self.assertEqual([item["key"] for item in report["kept"]], [KEY])
        self.assertEqual(self.file.read_bytes(), edited)


if __name__ == "__main__":
    unittest.main()
