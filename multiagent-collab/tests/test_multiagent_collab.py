from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "multiagent_collab.py"
SPEC = importlib.util.spec_from_file_location("multiagent_collab", SCRIPT)
assert SPEC and SPEC.loader
mc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mc)


class Args:
    def __init__(self, **values):
        self.__dict__.update(values)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.chat = self.root / "chat"
        (self.home / ".claude").mkdir(parents=True)
        self.existing_hook = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "/bin/true"}]}
                ]
            },
            "theme": "dark",
        }
        (self.home / ".claude" / "settings.json").write_text(
            json.dumps(self.existing_hook, indent=2) + "\n", encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()

    def args(self, command: str, **extra):
        values = {
            "agent": "both",
            "home": str(self.home),
            "chat_root": str(self.chat),
            "dry_run": False,
            "follow_config_symlinks": False,
            "upgrade_protocol_from": None,
        }
        values.update(extra)
        return Args(**values)

    def test_setup_both_is_idempotent_and_preserves_existing_settings(self):
        mc.setup(self.args("setup"))
        skill_root = SCRIPT.parents[1].resolve()
        self.assertEqual((self.home / ".codex/skills/multiagent-collab").resolve(), skill_root)
        self.assertEqual((self.home / ".claude/skills/multiagent-collab").resolve(), skill_root)
        self.assertEqual(
            mc.sha256_file(self.chat / "PROTOCOL.md"),
            mc.sha256_file(skill_root / "assets/PROTOCOL.md"),
        )
        self.assertIn(mc.MANAGED_START, (self.home / ".codex/AGENTS.md").read_text())
        claude = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(claude["theme"], "dark")
        self.assertEqual(claude["hooks"]["Stop"], self.existing_hook["hooks"]["Stop"])
        manifests = list((self.chat / "_backups").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        backup_data = json.loads(manifests[0].read_text())
        self.assertEqual(len(backup_data["backups"]), 1)
        self.assertEqual(backup_data["backups"][0]["source"], str(self.home / ".claude/settings.json"))
        first = {
            path: path.read_bytes()
            for path in (
                self.home / ".codex/AGENTS.md",
                self.home / ".codex/hooks.json",
                self.home / ".claude/settings.json",
                self.chat / "_runtime/install.json",
            )
        }
        mc.setup(self.args("setup"))
        self.assertEqual(first, {path: path.read_bytes() for path in first})

    def test_dry_run_writes_nothing(self):
        mc.setup(self.args("setup", dry_run=True))
        self.assertFalse(self.chat.exists())
        self.assertFalse((self.home / ".codex").exists())

    def test_uninstall_preserves_chat_data_and_existing_hooks(self):
        mc.setup(self.args("setup"))
        (self.chat / "task-data").mkdir()
        (self.chat / "task-data/result.txt").write_text("keep", encoding="utf-8")
        mc.uninstall(self.args("uninstall"))
        self.assertFalse((self.home / ".codex/skills/multiagent-collab").exists())
        self.assertFalse((self.home / ".claude/skills/multiagent-collab").exists())
        self.assertTrue((self.chat / "PROTOCOL.md").is_file())
        self.assertEqual((self.chat / "task-data/result.txt").read_text(), "keep")
        claude = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(claude["hooks"]["Stop"], self.existing_hook["hooks"]["Stop"])
        self.assertNotIn("SessionStart", claude["hooks"])

    def test_protocol_upgrade_is_compare_and_swap(self):
        mc.setup(self.args("setup", agent="codex"))
        installed = self.chat / "PROTOCOL.md"
        installed.write_text("local protocol\n", encoding="utf-8")
        current = mc.sha256_file(installed)
        with self.assertRaises(mc.UserError):
            mc.setup(self.args("setup", agent="codex"))
        mc.setup(self.args("setup", agent="codex", upgrade_protocol_from=current))
        self.assertEqual(installed.read_bytes(), (SCRIPT.parents[1] / "assets/PROTOCOL.md").read_bytes())
        prior = list((self.chat / "_protocols").glob(f"*-{current}.md"))
        self.assertEqual(len(prior), 1)
        self.assertEqual(prior[0].read_text(), "local protocol\n")

    def test_refuses_symlinked_config(self):
        target = self.root / "outside-settings.json"
        target.write_text("{}\n", encoding="utf-8")
        settings = self.home / ".claude/settings.json"
        settings.unlink()
        settings.symlink_to(target)
        with self.assertRaises(mc.UserError):
            mc.setup(self.args("setup", agent="claude"))
        self.assertEqual(target.read_text(), "{}\n")

    def test_preflight_conflict_leaves_no_partial_install(self):
        conflict = self.home / ".claude/skills/multiagent-collab"
        conflict.mkdir(parents=True)
        (conflict / "unmanaged").write_text("keep", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.setup(self.args("setup"))
        self.assertFalse(self.chat.exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual((conflict / "unmanaged").read_text(), "keep")


class BatonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.chat = self.root / "chat"
        self.task_file = self.root / "TASK.md"
        self.task_file.write_text("# Task\n\nOwner: Codex\n", encoding="utf-8")
        self.task_id = "20260911-001-test-task"
        mc.task_init(
            Args(
                chat_root=str(self.chat),
                task_id=self.task_id,
                owner="codex",
                task_file=str(self.task_file),
            )
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_pass_is_sequence_checked_and_atomic(self):
        task = self.chat / self.task_id
        before = (task / "LOG.md").read_bytes()
        turn = self.root / "turn.md"
        turn.write_text("Result: contract accepted.\n", encoding="utf-8")
        args = Args(
            chat_root=str(self.chat),
            task_id=self.task_id,
            agent="claude",
            expected_seq=99,
            next_holder="codex",
            log_file=str(turn),
            status=None,
            round=None,
            revision=None,
            verdict="PASS",
            owner_ready="keep",
            reviewer_ready="keep",
            ask="Present to operator.",
            ministerial=False,
        )
        with self.assertRaises(mc.UserError):
            mc.baton_pass(args)
        self.assertEqual((task / "LOG.md").read_bytes(), before)
        self.assertFalse((task / ".baton.lock").exists())
        args.expected_seq = 1
        mc.baton_pass(args)
        baton = mc.parse_baton(task / "BATON.md")
        self.assertEqual((baton["seq"], baton["holder"], baton["verdict"]), (2, "codex", "PASS"))

    def test_revision_change_clears_readiness(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["owner_ready"] = True
        baton["reviewer_ready"] = True
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        turn = self.root / "turn.md"
        turn.write_text("Result: changed.\n", encoding="utf-8")
        mc.baton_pass(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                round=None, revision="sha256:new", verdict="CHANGES_REQUIRED",
                owner_ready="keep", reviewer_ready="keep", ask="Revise.", ministerial=False,
            )
        )
        baton = mc.parse_baton(task / "BATON.md")
        self.assertFalse(baton["owner_ready"])
        self.assertFalse(baton["reviewer_ready"])

    def test_existing_lock_blocks_pass(self):
        task = self.chat / self.task_id
        (task / ".baton.lock").mkdir()
        turn = self.root / "turn.md"
        turn.write_text("Result: no.\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                    expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                    round=None, revision=None, verdict=None, owner_ready="keep",
                    reviewer_ready="keep", ask="No", ministerial=False,
                )
            )

    def test_explicitly_breaks_only_stale_lock_and_records_it(self):
        task = self.chat / self.task_id
        lock = task / ".baton.lock"
        lock.mkdir()
        (lock / "holder").write_text("dead-agent\n", encoding="utf-8")
        old = time.time() - 301
        os.utime(lock, (old, old))
        turn = self.root / "turn.md"
        turn.write_text("Result: resumed.\n", encoding="utf-8")
        mc.baton_pass(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                round=None, revision=None, verdict="PASS", owner_ready="keep",
                reviewer_ready="keep", ask="Continue.", ministerial=False,
                break_stale_lock=True,
            )
        )
        self.assertIn("Broke stale baton lock held by dead-agent", (task / "LOG.md").read_text())
        self.assertFalse(lock.exists())

    def test_subcommand_chat_root_is_not_overwritten(self):
        args = mc.build_parser().parse_args(
            ["status", "--chat-root", str(self.chat), "--task-id", self.task_id]
        )
        self.assertEqual(Path(args.chat_root), self.chat)

    def test_baton_rejects_every_line_separator_without_writing_log(self):
        task = self.chat / self.task_id
        turn = self.root / "turn.md"
        turn.write_text("Result: invalid ask rejected.\n", encoding="utf-8")
        separators = ["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
        for separator in separators:
            with self.subTest(separator=repr(separator)):
                before_log = (task / "LOG.md").read_bytes()
                before_baton = (task / "BATON.md").read_bytes()
                with self.assertRaises(mc.UserError):
                    mc.baton_pass(
                        Args(
                            chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                            expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                            round=None, revision=None, verdict="PASS", owner_ready="keep",
                            reviewer_ready="true", ask=f"safe{separator}holder: operator",
                            ministerial=False,
                        )
                    )
                self.assertEqual((task / "LOG.md").read_bytes(), before_log)
                self.assertEqual((task / "BATON.md").read_bytes(), before_baton)

    def test_roles_own_only_their_readiness_flag(self):
        task = self.chat / self.task_id
        turn = self.root / "turn.md"
        turn.write_text("Result: no.\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                    expected_seq=1, next_holder="claude", log_file=str(turn), status=None,
                    round=None, revision=None, verdict=None, owner_ready="true",
                    reviewer_ready="keep", ask="No.", ministerial=False,
                )
            )
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                    expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                    round=None, revision=None, verdict="PASS", owner_ready="true",
                    reviewer_ready="true", ask="No.", ministerial=False,
                )
            )
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "codex"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                    expected_seq=1, next_holder="claude", log_file=str(turn), status=None,
                    round=None, revision=None, verdict=None, owner_ready="true",
                    reviewer_ready="true", ask="No.", ministerial=False,
                )
            )

    def test_changes_required_clears_both_readiness_flags(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["owner_ready"] = True
        baton["reviewer_ready"] = True
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        turn = self.root / "turn.md"
        turn.write_text("Result: changes required.\n", encoding="utf-8")
        mc.baton_pass(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                round=1, revision=None, verdict="CHANGES_REQUIRED", owner_ready="keep",
                reviewer_ready="keep", ask="Fix.", ministerial=False,
            )
        )
        baton = mc.parse_baton(task / "BATON.md")
        self.assertFalse(baton["owner_ready"])
        self.assertFalse(baton["reviewer_ready"])

    def test_signoff_requires_owner_pass_and_both_readiness_flags(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "codex"
        baton["verdict"] = "PASS"
        baton["owner_ready"] = True
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        turn = self.root / "turn.md"
        turn.write_text("Result: signoff.\n", encoding="utf-8")
        args = Args(
            chat_root=str(self.chat), task_id=self.task_id, agent="codex",
            expected_seq=1, log_file=str(turn), ask="Review and close.",
            break_stale_lock=False,
        )
        with self.assertRaises(mc.UserError):
            mc.signoff(args)
        baton["reviewer_ready"] = True
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        mc.signoff(args)
        baton = mc.parse_baton(task / "BATON.md")
        self.assertEqual(baton["holder"], "operator")


class WatcherAndArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.chat = self.root / "chat"
        self.chat.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_task(self, task_id="20260911-002-watch-test", holder="codex", status="active"):
        task = self.chat / task_id
        task.mkdir()
        (task / "TASK.md").write_text("# Task\n\nOwner: Codex\n", encoding="utf-8")
        (task / "LOG.md").write_text("# Log\n", encoding="utf-8")
        baton = {
            "task": task_id, "seq": 1, "holder": holder, "status": status,
            "round": 0, "revision": "sha256:test", "verdict": "none",
            "owner_ready": False, "reviewer_ready": False, "ask": "Act.",
            "updated_at": mc.now_iso(),
        }
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        return task

    def test_scan_notifies_once_per_sequence(self):
        self.make_task()
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {"agent": "codex", "session_id": "s", "wake_mode": "monitor-file", "wake_verified": True}
        state = {"notified": {}, "stale": []}
        self.assertTrue(mc.scan_once(self.chat, binding, state))
        first = (runtime / "monitor.inbox").read_text()
        self.assertFalse(mc.scan_once(self.chat, binding, state))
        self.assertEqual((runtime / "monitor.inbox").read_text(), first)

    def test_malformed_tasks_are_reported_without_blocking_valid_task(self):
        self.make_task(task_id="20260911-003-valid-task")
        bad_seq = self.make_task(task_id="20260911-004-bad-seq")
        (bad_seq / "BATON.md").write_text((bad_seq / "BATON.md").read_text().replace("seq: 1", "seq: abc"), encoding="utf-8")
        bad_time = self.make_task(task_id="20260911-005-bad-time")
        bad_time_baton = mc.parse_baton(bad_time / "BATON.md")
        bad_time_baton["updated_at"] = "2026-09-11T10:00:00"
        mc.atomic_text(bad_time / "BATON.md", mc.dump_baton(bad_time_baton))
        missing_task = self.make_task(task_id="20260911-006-missing-task", holder="operator")
        (missing_task / "TASK.md").unlink()
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {"agent": "codex", "session_id": "s", "wake_mode": "monitor-file", "wake_verified": True}
        state = {"session_id": "s", "notified": {}, "attempts": {}, "failed": [], "unverified": [], "stale": []}
        mc.scan_once(self.chat, binding, state)
        self.assertEqual(state["notified"]["20260911-003-valid-task"], 1)
        alerts = (runtime / "alerts.log").read_text()
        self.assertIn("20260911-004-bad-seq", alerts)
        self.assertIn("20260911-005-bad-time", alerts)
        self.assertIn("20260911-006-missing-task", alerts)

    def test_wake_failures_are_bounded_and_alert_once(self):
        self.make_task()
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {"agent": "codex", "session_id": "s", "wake_mode": "command", "wake_verified": True}
        state = {"session_id": "s", "notified": {}, "attempts": {}, "failed": [], "unverified": [], "stale": []}
        with mock.patch.object(mc, "wake", return_value=False) as wake:
            for _ in range(6):
                key = "task:20260911-002-watch-test:1"
                if key in state["attempts"]:
                    state["attempts"][key]["next_at"] = 0
                mc.scan_once(self.chat, binding, state)
        self.assertEqual(wake.call_count, 3)
        self.assertEqual((runtime / "alerts.log").read_text().count("wake failed after"), 1)

    def test_rebind_session_gets_pending_sequence(self):
        self.make_task()
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {"agent": "codex", "session_id": "new", "wake_mode": "monitor-file", "wake_verified": True}
        state = {"session_id": "old", "notified": {"20260911-002-watch-test": 1}, "stale": []}
        mc.scan_once(self.chat, binding, state)
        self.assertEqual(state["session_id"], "new")
        self.assertEqual(state["notified"]["20260911-002-watch-test"], 1)
        self.assertTrue((runtime / "monitor.inbox").exists())

    def test_unverified_wake_never_marks_task_notified(self):
        self.make_task()
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {"agent": "codex", "session_id": "s", "wake_mode": "monitor-file", "wake_verified": False}
        state = {"session_id": "s", "notified": {}, "attempts": {}, "failed": [], "unverified": [], "stale": []}
        mc.scan_once(self.chat, binding, state)
        self.assertNotIn("20260911-002-watch-test", state["notified"])
        self.assertIn("wake path unverified", (runtime / "alerts.log").read_text())

    def test_operator_stale_falls_back_when_owner_unbound(self):
        task = self.make_task(holder="operator")
        baton = mc.parse_baton(task / "BATON.md")
        baton["updated_at"] = (dt.datetime.now().astimezone() - dt.timedelta(hours=2)).isoformat()
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        runtime = self.chat / "_runtime/claude"
        runtime.mkdir(parents=True)
        binding = {"agent": "claude", "session_id": "s", "wake_mode": "monitor-file", "wake_verified": True}
        state = {"notified": {}, "stale": []}
        self.assertTrue(mc.scan_once(self.chat, binding, state))
        first = (runtime / "monitor.inbox").read_text()
        self.assertIn("stale", first)
        self.assertFalse(mc.scan_once(self.chat, binding, state))
        self.assertEqual((runtime / "monitor.inbox").read_text(), first)

    def test_holder_does_not_send_stale_alert_about_itself(self):
        task = self.make_task(holder="claude")
        baton = mc.parse_baton(task / "BATON.md")
        baton["updated_at"] = (dt.datetime.now().astimezone() - dt.timedelta(hours=2)).isoformat()
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        runtime = self.chat / "_runtime/claude"
        runtime.mkdir(parents=True)
        binding = {"agent": "claude", "session_id": "s", "wake_mode": "monitor-file", "wake_verified": True}
        state = {"session_id": "s", "notified": {task.name: 1}, "attempts": {}, "failed": [], "unverified": [], "stale": []}
        self.assertFalse(mc.scan_once(self.chat, binding, state))
        self.assertFalse((runtime / "monitor.inbox").exists())

    def test_reviewer_does_not_alert_when_owner_binding_is_live(self):
        task = self.make_task(holder="operator")
        baton = mc.parse_baton(task / "BATON.md")
        baton["updated_at"] = (dt.datetime.now().astimezone() - dt.timedelta(hours=2)).isoformat()
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        owner_binding, _, _ = mc.binding_paths(self.chat, "codex")
        owner_binding.parent.mkdir(parents=True)
        mc.atomic_write(owner_binding, mc.json_bytes({"session_id": "owner"}))
        runtime = self.chat / "_runtime/claude"
        runtime.mkdir(parents=True)
        binding = {"agent": "claude", "session_id": "review", "wake_mode": "monitor-file", "wake_verified": True}
        state = {"session_id": "review", "notified": {}, "attempts": {}, "failed": [], "unverified": [], "stale": []}
        with mock.patch.object(mc, "binding_live", return_value=True):
            self.assertFalse(mc.scan_once(self.chat, binding, state))
        self.assertFalse((runtime / "monitor.inbox").exists())

    def test_archive_verifies_before_removal(self):
        task = self.make_task(holder="none", status="done")
        mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, expected_seq=1))
        archive = self.chat / "_archive" / f"{task.name}.tar.gz"
        self.assertTrue(archive.is_file())
        self.assertFalse(task.exists())
        with tarfile.open(archive, "r:gz") as handle:
            names = handle.getnames()
        self.assertIn(f"{task.name}/MANIFEST.sha256", names)
        index = (self.chat / "_archive/INDEX.md").read_text()
        self.assertIn("owner codex", index)
        self.assertIn("result none", index)

    def test_archive_requires_done_state_and_holds_lock_through_removal(self):
        task = self.make_task()
        with self.assertRaises(mc.UserError):
            mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, expected_seq=1))
        self.assertTrue(task.exists())
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "none"
        baton["status"] = "done"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        original_rmtree = mc.shutil.rmtree

        def checked_rmtree(path, *args, **kwargs):
            if Path(path) == task:
                self.assertTrue((task / ".baton.lock").is_dir())
            return original_rmtree(path, *args, **kwargs)

        with mock.patch.object(mc.shutil, "rmtree", side_effect=checked_rmtree):
            mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, expected_seq=1))

    def test_archive_calls_manifest_verifier_and_failure_preserves_task(self):
        task = self.make_task(holder="none", status="done")
        with mock.patch.object(mc, "verify_manifest", side_effect=mc.UserError("corrupt")) as verify:
            with self.assertRaises(mc.UserError):
                mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, expected_seq=1))
        verify.assert_called_once()
        self.assertTrue(task.exists())
        baton = mc.parse_baton(task / "BATON.md")
        self.assertEqual(baton["status"], "blocked")

    def test_manifest_verifier_rejects_changed_content(self):
        task = self.make_task(holder="none", status="done")
        mc.atomic_text(task / "MANIFEST.sha256", mc.manifest_text(mc.manifest_entries(task)))
        (task / "LOG.md").write_text("changed after manifest\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.verify_manifest(task)

    def test_archive_refuses_existing_baton_lock(self):
        task = self.make_task(holder="none", status="done")
        (task / ".baton.lock").mkdir()
        with self.assertRaises(mc.UserError):
            mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, expected_seq=1))
        self.assertTrue(task.exists())


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.chat = self.root / "chat"
        self.chat.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def args(self, session="session-a"):
        return Args(
            chat_root=str(self.chat), agent="codex", session_id=session,
            project=str(self.root), wake_mode="codex-queue", wake_command_json=None,
        )

    def test_live_binding_is_never_stolen(self):
        with mock.patch.object(mc, "spawn_watcher", return_value=4242):
            mc.bind(self.args(), rebind=False)
        binding_path, _, _ = mc.binding_paths(self.chat, "codex")
        self.assertEqual(json.loads(binding_path.read_text())["session_id"], "session-a")
        with mock.patch.object(mc, "binding_live", return_value=True):
            with self.assertRaises(mc.UserError):
                mc.bind(self.args("session-b"), rebind=False)
        self.assertEqual(json.loads(binding_path.read_text())["session_id"], "session-a")

    def test_unrelated_session_end_does_not_release_binding(self):
        binding_path, heartbeat, _ = mc.binding_paths(self.chat, "codex")
        binding_path.parent.mkdir(parents=True)
        mc.atomic_write(binding_path, mc.json_bytes({"session_id": "owner", "pid": 0}), 0o600)
        payload = io.StringIO(json.dumps({"session_id": "other"}))
        with mock.patch.object(mc.sys, "stdin", payload), mock.patch.object(mc, "stop_binding") as stop:
            mc.hook(Args(chat_root=str(self.chat), agent="codex", event="session-end"))
        stop.assert_not_called()
        self.assertTrue(binding_path.exists())

    def test_claude_session_start_outputs_monitor_instructions(self):
        binding_path, heartbeat, _ = mc.binding_paths(self.chat, "claude")
        binding_path.parent.mkdir(parents=True)
        binding = {
            "agent": "claude", "session_id": "claude-session", "pid": 123,
            "chat_root": str(self.chat), "wake_mode": "monitor-file",
        }
        mc.atomic_write(binding_path, mc.json_bytes(binding))
        heartbeat.write_text("live\n", encoding="utf-8")
        output = io.StringIO()
        payload = io.StringIO(json.dumps({"session_id": "claude-session"}))
        with mock.patch.object(mc.sys, "stdin", payload), mock.patch.object(mc, "binding_live", return_value=True), contextlib.redirect_stdout(output):
            mc.hook(Args(chat_root=str(self.chat), agent="claude", event="session-start"))
        rendered = json.loads(output.getvalue())
        context = rendered["hookSpecificOutput"]["additionalContext"]
        self.assertIn("tail -n 0 -F", context)
        self.assertIn("probe-wake", context)

    def test_wake_verification_requires_nonce_round_trip(self):
        binding_path, heartbeat, _ = mc.binding_paths(self.chat, "claude")
        binding_path.parent.mkdir(parents=True)
        binding = {
            "agent": "claude", "session_id": "s", "pid": 123,
            "chat_root": str(self.chat), "wake_mode": "monitor-file",
            "wake_verified": False,
        }
        mc.atomic_write(binding_path, mc.json_bytes(binding))
        heartbeat.write_text("live\n", encoding="utf-8")
        args = Args(chat_root=str(self.chat), agent="claude", session_id="s")
        with mock.patch.object(mc, "binding_live", return_value=True), mock.patch.object(mc.secrets, "token_hex", return_value="nonce"), mock.patch.object(mc, "wake", return_value=True):
            self.assertEqual(mc.probe_wake(args), 0)
            with self.assertRaises(mc.UserError):
                mc.verify_wake(Args(chat_root=str(self.chat), agent="claude", session_id="s", nonce="wrong"))
            self.assertEqual(mc.verify_wake(Args(chat_root=str(self.chat), agent="claude", session_id="s", nonce="nonce")), 0)
        verified = json.loads(binding_path.read_text())
        self.assertTrue(verified["wake_verified"])
        self.assertFalse((binding_path.parent / "wake-challenge.json").exists())

    def test_subprocess_wake_timeout_is_failure(self):
        binding = {"session_id": "s", "wake_mode": "codex-queue"}
        with mock.patch.object(mc.subprocess, "run", side_effect=mc.subprocess.TimeoutExpired("codex", 10)):
            self.assertFalse(mc.wake(binding, self.chat, "message"))

    def test_liveness_requires_expected_process_and_fresh_heartbeat(self):
        heartbeat = self.chat / "heartbeat"
        heartbeat.write_text("live\n", encoding="utf-8")
        binding = {
            "pid": os.getpid(), "agent": "codex", "session_id": "not-this-process",
            "chat_root": str(self.chat),
        }
        self.assertFalse(mc.binding_live(binding, heartbeat))
        with mock.patch.object(mc, "watcher_pid_matches", return_value=True):
            old = time.time() - 60
            os.utime(heartbeat, (old, old))
            self.assertFalse(mc.binding_live(binding, heartbeat))


if __name__ == "__main__":
    unittest.main()
