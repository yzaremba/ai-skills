from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
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
        self.original_settings = (json.dumps(self.existing_hook, indent=2) + "\n").encode("utf-8")
        (self.home / ".claude" / "settings.json").write_bytes(self.original_settings)
        self.discovery_patcher = mock.patch.object(
            mc, "probe_codex_discovery", side_effect=self.fake_discovery_probe,
        )
        self.discovery_mock = self.discovery_patcher.start()
        self.hook_trust_patcher = mock.patch.object(
            mc,
            "probe_codex_hook_trust",
            return_value={
                "available": True,
                "ok": True,
                "detail": "sessionStart=trusted, sessionEnd=trusted",
            },
        )
        self.hook_trust_mock = self.hook_trust_patcher.start()

    def tearDown(self):
        self.hook_trust_patcher.stop()
        self.discovery_patcher.stop()
        self.temp.cleanup()

    def fake_discovery_probe(self, home, skill_root, **_kwargs):
        entries = []
        current, legacy_links = mc.skill_link_paths(Path(home), "codex")
        for index, link in enumerate((*legacy_links, current)):
            if link.is_symlink() and mc.symlink_target(link) == skill_root:
                entries.append({
                    "root_id": f"r{index}",
                    "root_path": str(link.parent.resolve()),
                    "skill_file": str(skill_root / "SKILL.md"),
                    "canonical": True,
                })
                break
        return {"available": True, "entries": entries, "roots": {}, "warnings": []}

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

    def install_legacy_link_fixture(self):
        skill_root = SCRIPT.parents[1].resolve()
        legacy = self.home / ".codex/skills/multiagent-collab"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.symlink_to(skill_root, target_is_directory=True)
        runtime = self.chat / "_runtime"
        runtime.mkdir(parents=True)
        (runtime / "install.json").write_bytes(mc.json_bytes({
            "skill_root": str(skill_root),
            "chat_root": str(self.chat),
            "agents": ["codex"],
            "created_config": [],
            "original_config": {},
        }))
        return legacy

    def test_setup_both_is_idempotent_and_preserves_existing_settings(self):
        mc.setup(self.args("setup"))
        skill_root = SCRIPT.parents[1].resolve()
        self.assertEqual((self.home / ".agents/skills/multiagent-collab").resolve(), skill_root)
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
        install_data = json.loads((self.chat / "_runtime/install.json").read_text())
        self.assertEqual(
            set(install_data["created_config"]),
            {
                str(self.home / ".codex/AGENTS.md"),
                str(self.home / ".codex/hooks.json"),
            },
        )
        self.assertEqual(
            set(install_data["managed_links"]),
            {
                str(self.home / ".agents/skills/multiagent-collab"),
                str(self.home / ".claude/skills/multiagent-collab"),
            },
        )
        self.assertEqual(install_data["codex_discovery"]["phase"], "official")
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

    def test_managed_legacy_link_migrates_after_dual_and_post_probes(self):
        legacy = self.install_legacy_link_fixture()
        mc.setup(self.args("setup", agent="codex"))
        official = self.home / ".agents/skills/multiagent-collab"
        self.assertEqual(official.resolve(), SCRIPT.parents[1].resolve())
        self.assertFalse(legacy.exists())
        self.assertEqual(self.discovery_mock.call_count, 2)
        metadata = json.loads((self.chat / "_runtime/install.json").read_text())
        self.assertIn(str(official), metadata["managed_links"])
        self.assertNotIn(str(legacy), metadata["managed_links"])
        self.assertEqual(metadata["codex_discovery"]["phase"], "official")
        migration = metadata["codex_discovery"]["migration"]
        self.assertTrue(
            mc.probe_has_root_entry(migration["dual"], legacy.parent, SCRIPT.parents[1].resolve())
        )
        self.assertTrue(
            mc.probe_has_root_entry(migration["post"], official.parent, SCRIPT.parents[1].resolve())
        )
        mc.setup(self.args("setup", agent="codex"))
        repeated = json.loads((self.chat / "_runtime/install.json").read_text())
        self.assertEqual(repeated["codex_discovery"]["migration"], migration)

    def test_unavailable_probe_warns_and_never_removes_legacy_link(self):
        legacy = self.install_legacy_link_fixture()
        unavailable = {
            "available": False, "entries": [], "roots": {},
            "warnings": ["codex not found"],
        }
        output = io.StringIO()
        with mock.patch.object(mc, "probe_codex_discovery", return_value=unavailable), contextlib.redirect_stdout(output):
            mc.setup(self.args("setup", agent="codex"))
        official = self.home / ".agents/skills/multiagent-collab"
        self.assertTrue(official.is_symlink())
        self.assertTrue(legacy.is_symlink())
        self.assertIn("probe unavailable", output.getvalue())
        metadata = json.loads((self.chat / "_runtime/install.json").read_text())
        self.assertEqual(metadata["codex_discovery"]["phase"], "dual")

    def test_dual_probe_fault_rolls_back_new_link_before_legacy_removal(self):
        legacy = self.install_legacy_link_fixture()

        def multiple_targets(home, skill_root, **kwargs):
            result = self.fake_discovery_probe(home, skill_root, **kwargs)
            result["entries"].append({
                "root_id": "stale",
                "root_path": str(Path(home) / ".agents/skills"),
                "skill_file": str(Path(home) / "stale/multiagent-collab/SKILL.md"),
                "canonical": False,
            })
            return result

        with mock.patch.object(mc, "probe_codex_discovery", side_effect=multiple_targets):
            with self.assertRaisesRegex(mc.UserError, "before legacy removal"):
                mc.setup(self.args("setup", agent="codex"))
        self.assertTrue(legacy.is_symlink())
        self.assertFalse((self.home / ".agents/skills/multiagent-collab").exists())
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())

    def test_failed_post_removal_probe_restores_legacy_and_reports_failure(self):
        legacy = self.install_legacy_link_fixture()
        calls = 0

        def fail_post(home, skill_root, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                return {"available": True, "entries": [], "roots": {}, "warnings": []}
            return self.fake_discovery_probe(home, skill_root, **kwargs)

        with mock.patch.object(mc, "probe_codex_discovery", side_effect=fail_post):
            with self.assertRaisesRegex(mc.UserError, "migration failed; legacy link restored") as raised:
                mc.setup(self.args("setup", agent="codex"))
        official = self.home / ".agents/skills/multiagent-collab"
        self.assertFalse(official.exists())
        self.assertTrue(legacy.is_symlink())
        self.assertIn(str(official), str(raised.exception))
        self.assertIn(str(legacy), str(raised.exception))
        self.assertEqual(calls, 3)

    def test_unavailable_post_probe_warns_and_retains_both_links(self):
        legacy = self.install_legacy_link_fixture()
        calls = 0

        def unavailable_post(home, skill_root, **kwargs):
            nonlocal calls
            calls += 1
            if calls >= 2:
                return {
                    "available": False,
                    "entries": [],
                    "roots": {},
                    "warnings": ["codex not found"],
                }
            return self.fake_discovery_probe(home, skill_root, **kwargs)

        output = io.StringIO()
        with mock.patch.object(mc, "probe_codex_discovery", side_effect=unavailable_post), contextlib.redirect_stdout(output):
            mc.setup(self.args("setup", agent="codex"))
        official = self.home / ".agents/skills/multiagent-collab"
        self.assertTrue(official.is_symlink())
        self.assertTrue(legacy.is_symlink())
        self.assertIn("migration failed; legacy link restored", output.getvalue())
        metadata = json.loads((self.chat / "_runtime/install.json").read_text())
        self.assertEqual(metadata["codex_discovery"]["phase"], "post-removal-failed")
        self.assertEqual(set(metadata["managed_links"]), {str(official), str(legacy)})
        self.assertEqual(calls, 3)

    def test_unmanaged_legacy_link_blocks_before_new_link_creation(self):
        skill_root = SCRIPT.parents[1].resolve()
        legacy = self.home / ".codex/skills/multiagent-collab"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.symlink_to(skill_root, target_is_directory=True)
        with self.assertRaisesRegex(mc.UserError, "not recorded as managed"):
            mc.setup(self.args("setup", agent="codex"))
        self.assertFalse((self.home / ".agents").exists())
        self.assertTrue(legacy.is_symlink())

    def test_fresh_discovery_failure_rolls_back_only_managed_entry(self):
        invalid = {"available": True, "entries": [], "roots": {}, "warnings": []}
        with mock.patch.object(mc, "probe_codex_discovery", return_value=invalid):
            with self.assertRaisesRegex(mc.UserError, "documented discovery verification failed"):
                mc.setup(self.args("setup", agent="codex"))
        self.assertFalse((self.home / ".agents/skills/multiagent-collab").exists())
        self.assertTrue((self.home / ".agents/skills").is_dir())
        self.assertFalse(self.chat.exists())
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())

    def test_dry_run_writes_nothing(self):
        mc.setup(self.args("setup", dry_run=True))
        self.assertFalse(self.chat.exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".agents").exists())

    def test_uninstall_preserves_chat_data_and_existing_hooks(self):
        mc.setup(self.args("setup"))
        (self.chat / "task-data").mkdir()
        (self.chat / "task-data/result.txt").write_text("keep", encoding="utf-8")
        mc.uninstall(self.args("uninstall"))
        self.assertFalse((self.home / ".agents/skills/multiagent-collab").exists())
        self.assertFalse((self.home / ".claude/skills/multiagent-collab").exists())
        self.assertTrue((self.home / ".agents/skills").is_dir())
        self.assertTrue((self.home / ".agents").is_dir())
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())
        self.assertFalse((self.home / ".codex/hooks.json").exists())
        self.assertTrue((self.chat / "PROTOCOL.md").is_file())
        self.assertEqual((self.chat / "task-data/result.txt").read_text(), "keep")
        claude = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(claude["hooks"]["Stop"], self.existing_hook["hooks"]["Stop"])
        self.assertNotIn("SessionStart", claude["hooks"])
        self.assertEqual((self.home / ".claude/settings.json").read_bytes(), self.original_settings)
        install_data = json.loads((self.chat / "_runtime/install.json").read_text())
        self.assertEqual(install_data["created_config"], [])
        self.assertEqual(install_data["managed_links"], [])

    def test_uninstall_does_not_trust_links_from_mismatched_install_metadata(self):
        mc.setup(self.args("setup", agent="codex"))
        official = self.home / ".agents/skills/multiagent-collab"
        metadata_path = self.chat / "_runtime/install.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["skill_root"] = str(self.root / "different-skill-root")
        metadata_path.write_bytes(mc.json_bytes(metadata))
        mc.uninstall(self.args("uninstall", agent="codex"))
        self.assertTrue(official.is_symlink())
        self.assertEqual(official.resolve(), SCRIPT.parents[1].resolve())

    def test_doctor_reports_managed_legacy_link_with_deduplicated_discovery(self):
        mc.setup(self.args("setup", agent="codex"))
        skill_root = SCRIPT.parents[1].resolve()
        legacy = self.home / ".codex/skills/multiagent-collab"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.symlink_to(skill_root, target_is_directory=True)
        metadata_path = self.chat / "_runtime/install.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["managed_links"].append(str(legacy))
        metadata_path.write_bytes(mc.json_bytes(metadata))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = mc.doctor(Args(
                home=str(self.home), chat_root=str(self.chat), agent="codex",
                json=True, require_binding=False,
            ))
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        checks = {item["name"]: item for item in report["checks"]}
        self.assertEqual(checks["codex_legacy_skill_link"]["severity"], "warning")
        self.assertTrue(checks["codex_discovery"]["ok"])
        self.assertIn(str(legacy.parent), checks["codex_discovery"]["detail"])

    def test_doctor_fails_multiple_discovery_targets_with_actionable_paths(self):
        mc.setup(self.args("setup", agent="codex"))
        official = self.home / ".agents/skills/multiagent-collab"
        legacy = self.home / ".codex/skills/multiagent-collab"
        duplicate = {
            "available": True,
            "entries": [
                {
                    "root_path": str(official.parent),
                    "skill_file": str(SCRIPT.parents[1] / "SKILL.md"),
                    "canonical": True,
                },
                {
                    "root_path": str(legacy.parent),
                    "skill_file": str(self.home / "stale/SKILL.md"),
                    "canonical": False,
                },
            ],
            "roots": {},
            "warnings": [],
        }
        output = io.StringIO()
        with mock.patch.object(mc, "probe_codex_discovery", return_value=duplicate), contextlib.redirect_stdout(output):
            result = mc.doctor(Args(
                home=str(self.home), chat_root=str(self.chat), agent="codex",
                json=True, require_binding=False,
            ))
        self.assertEqual(result, 1)
        check = {
            item["name"]: item for item in json.loads(output.getvalue())["checks"]
        }["codex_discovery"]
        self.assertIn("multiple discovery targets", check["detail"])
        self.assertIn(str(official), check["detail"])
        self.assertIn(str(legacy), check["detail"])
        self.assertIn(str(self.home / "stale/SKILL.md"), check["detail"])

    def test_doctor_treats_unavailable_probe_as_warning(self):
        mc.setup(self.args("setup", agent="codex"))
        unavailable = {
            "available": False, "entries": [], "roots": {},
            "warnings": ["codex not found"],
        }
        output = io.StringIO()
        with mock.patch.object(mc, "probe_codex_discovery", return_value=unavailable), contextlib.redirect_stdout(output):
            result = mc.doctor(Args(
                home=str(self.home), chat_root=str(self.chat), agent="codex",
                json=True, require_binding=False,
            ))
        self.assertEqual(result, 0)
        checks = {item["name"]: item for item in json.loads(output.getvalue())["checks"]}
        self.assertEqual(checks["codex_discovery"]["severity"], "warning")
        self.assertIn("no verified migration claim", checks["codex_discovery"]["detail"])

    def test_doctor_fails_missing_link_and_missing_discovery(self):
        mc.setup(self.args("setup", agent="codex"))
        (self.home / ".agents/skills/multiagent-collab").unlink()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = mc.doctor(Args(
                home=str(self.home), chat_root=str(self.chat), agent="codex",
                json=True, require_binding=False,
            ))
        self.assertEqual(result, 1)
        checks = {item["name"]: item for item in json.loads(output.getvalue())["checks"]}
        self.assertFalse(checks["codex_skill_link"]["ok"])
        self.assertFalse(checks["codex_discovery"]["ok"])

    def test_doctor_uses_injected_hook_trust_probe_without_starting_child(self):
        mc.setup(self.args("setup", agent="codex"))
        output = io.StringIO()
        with (
            mock.patch.object(
                mc.subprocess,
                "Popen",
                side_effect=AssertionError("doctor test started a real app-server child"),
            ),
            contextlib.redirect_stdout(output),
        ):
            result = mc.doctor(Args(
                home=str(self.home), chat_root=str(self.chat), agent="codex",
                json=True, require_binding=False,
            ))
        self.assertEqual(result, 0)
        checks = {item["name"]: item for item in json.loads(output.getvalue())["checks"]}
        self.assertTrue(checks["codex_hook_trust"]["ok"])
        self.hook_trust_mock.assert_called_once_with(
            self.home.resolve(), SCRIPT.parents[1].resolve(), cwd=Path.cwd(),
        )

    def test_uninstall_preserves_preexisting_codex_config_exactly(self):
        codex = self.home / ".codex"
        codex.mkdir()
        agents_before = b"# Personal Codex instructions\n"
        hooks_before = mc.json_bytes({
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "/bin/true"}]}],
            },
            "personal": True,
        })
        (codex / "AGENTS.md").write_bytes(agents_before)
        (codex / "hooks.json").write_bytes(hooks_before)
        mc.setup(self.args("setup", agent="codex"))
        metadata = json.loads((self.chat / "_runtime/install.json").read_text())
        self.assertEqual(metadata["created_config"], [])
        mc.uninstall(self.args("uninstall", agent="codex"))
        self.assertEqual((codex / "AGENTS.md").read_bytes(), agents_before)
        self.assertEqual((codex / "hooks.json").read_bytes(), hooks_before)

    def test_uninstall_preserves_untracked_empty_hooks_file(self):
        codex = self.home / ".codex"
        codex.mkdir()
        hooks = codex / "hooks.json"
        hooks.write_bytes(b"{}\n")
        mc.setup(self.args("setup", agent="codex"))
        metadata = json.loads((self.chat / "_runtime/install.json").read_text())
        self.assertNotIn(str(hooks), metadata["created_config"])
        mc.uninstall(self.args("uninstall", agent="codex"))
        self.assertTrue(hooks.is_file())
        self.assertEqual(hooks.read_bytes(), b"{}\n")

    def test_uninstall_keeps_user_edits_to_created_codex_config(self):
        mc.setup(self.args("setup", agent="codex"))
        agents = self.home / ".codex/AGENTS.md"
        agents.write_text(agents.read_text() + "\n# Added by user\n", encoding="utf-8")
        hooks_path = self.home / ".codex/hooks.json"
        hooks = json.loads(hooks_path.read_text())
        hooks["hooks"]["Stop"] = [
            {"hooks": [{"type": "command", "command": "/bin/true"}]}
        ]
        hooks_path.write_bytes(mc.json_bytes(hooks))
        mc.uninstall(self.args("uninstall", agent="codex"))
        self.assertTrue(agents.is_file())
        self.assertEqual(agents.read_text(), "# Added by user\n")
        self.assertTrue(hooks_path.is_file())
        remaining = json.loads(hooks_path.read_text())
        self.assertEqual(remaining["hooks"]["Stop"], hooks["hooks"]["Stop"])
        self.assertNotIn("SessionStart", remaining["hooks"])
        self.assertNotIn("SessionEnd", remaining["hooks"])

    def test_preexisting_agents_edit_prevents_backup_restore(self):
        codex = self.home / ".codex"
        codex.mkdir()
        agents = codex / "AGENTS.md"
        agents.write_text("# Original instructions\n", encoding="utf-8")
        mc.setup(self.args("setup", agent="codex"))
        agents.write_text(
            agents.read_text() + "\n# Added after install\n",
            encoding="utf-8",
        )
        mc.uninstall(self.args("uninstall", agent="codex"))
        result = agents.read_text()
        self.assertIn("# Original instructions", result)
        self.assertIn("# Added after install", result)
        self.assertNotIn(mc.MANAGED_START, result)

    def test_preexisting_hooks_edit_prevents_backup_restore(self):
        codex = self.home / ".codex"
        codex.mkdir()
        hooks_path = codex / "hooks.json"
        hooks_path.write_bytes(mc.json_bytes({"personal": "before"}))
        mc.setup(self.args("setup", agent="codex"))
        hooks = json.loads(hooks_path.read_text())
        hooks["added_after_install"] = "keep"
        hooks_path.write_bytes(mc.json_bytes(hooks))
        mc.uninstall(self.args("uninstall", agent="codex"))
        result = json.loads(hooks_path.read_text())
        self.assertEqual(result["personal"], "before")
        self.assertEqual(result["added_after_install"], "keep")
        self.assertNotIn("SessionStart", result.get("hooks", {}))
        self.assertNotIn("SessionEnd", result.get("hooks", {}))

    def test_original_config_backup_digest_is_checked(self):
        codex = self.home / ".codex"
        codex.mkdir()
        hooks_path = codex / "hooks.json"
        hooks_path.write_bytes(b"{}\n")
        mc.setup(self.args("setup", agent="codex"))
        metadata = json.loads((self.chat / "_runtime/install.json").read_text())
        record = metadata["original_config"][str(hooks_path)]
        Path(record["backup"]).write_bytes(b'{"tampered": true}\n')
        with self.assertRaisesRegex(mc.UserError, "missing or corrupt"):
            mc.original_config_bytes(metadata, hooks_path, self.chat)

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

    def test_refuses_config_under_symlinked_parent(self):
        settings = self.home / ".claude/settings.json"
        settings.unlink()
        (self.home / ".claude").rmdir()
        real = self.root / "real-claude"
        real.mkdir()
        (real / "settings.json").write_bytes(self.original_settings)
        (self.home / ".claude").symlink_to(real, target_is_directory=True)
        with self.assertRaises(mc.UserError):
            mc.setup(self.args("setup", agent="claude"))
        self.assertEqual((real / "settings.json").read_bytes(), self.original_settings)

    def test_refuses_discovery_link_under_symlinked_shared_parent(self):
        shared = self.root / "shared-agent-data"
        shared.mkdir()
        (self.home / ".agents").symlink_to(shared, target_is_directory=True)
        with self.assertRaisesRegex(mc.UserError, "symlinked parent"):
            mc.setup(self.args("setup", agent="codex"))
        self.assertFalse((shared / "skills/multiagent-collab").exists())
        self.assertFalse(self.chat.exists())

    def test_preflight_conflict_leaves_no_partial_install(self):
        conflict = self.home / ".claude/skills/multiagent-collab"
        conflict.mkdir(parents=True)
        (conflict / "unmanaged").write_text("keep", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.setup(self.args("setup"))
        self.assertFalse(self.chat.exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".agents").exists())
        self.assertEqual((conflict / "unmanaged").read_text(), "keep")


class CodexHookTrustTests(unittest.TestCase):
    class FakeStdin:
        def __init__(self, process):
            self.process = process
            self.buffer = ""

        def write(self, data):
            self.buffer += data
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                if line:
                    self.process.handle(json.loads(line))
            return len(data)

        def flush(self):
            return None

        def close(self):
            return None

    class FakeProcess:
        def __init__(self, mode, codex_home, hooks_result):
            read_fd, write_fd = os.pipe()
            self.stdout = os.fdopen(read_fd, "r", encoding="utf-8")
            self.writer = os.fdopen(write_fd, "w", encoding="utf-8")
            self.stderr = io.StringIO("")
            self.stdin = CodexHookTrustTests.FakeStdin(self)
            self.mode = mode
            self.codex_home = codex_home
            self.hooks_result = hooks_result
            self.received = []
            self.initialized = False
            self.returncode = None
            self.terminated = False
            self.killed = False

        def emit(self, payload):
            self.writer.write(json.dumps(payload) + "\n")
            self.writer.flush()

        def finish(self, returncode=0):
            if not self.writer.closed:
                self.writer.close()
            self.returncode = returncode

        def handle(self, message):
            self.received.append(message)
            method = message.get("method")
            if method == "initialize":
                capabilities = message.get("params", {}).get("capabilities", {})
                if capabilities.get("experimentalApi") is not True:
                    self.finish()
                    return
                if self.mode == "initialize-timeout":
                    return
                self.emit({
                    "id": message["id"],
                    "result": {"codexHome": self.codex_home},
                })
            elif method == "initialized":
                self.initialized = True
            elif method == "hooks/list":
                if not self.initialized:
                    self.finish()
                elif self.mode == "no-response":
                    self.finish()
                elif self.mode == "timeout":
                    return
                elif self.mode == "unsupported":
                    self.emit({
                        "id": message["id"],
                        "error": {"code": -32601, "message": "Method not found"},
                    })
                elif self.mode == "malformed":
                    self.writer.write("not-json\n")
                    self.writer.flush()
                    self.finish()
                else:
                    self.emit({"id": message["id"], "result": self.hooks_result})

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.finish(-15)

        def kill(self):
            self.killed = True
            self.finish(-9)

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("fake codex", timeout)
            return self.returncode

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.cwd = self.root / "project"
        self.cwd.mkdir(parents=True)
        self.skill_root = SCRIPT.parents[1].resolve()
        self.codex_home = self.home / ".codex"
        self.hooks_path = self.codex_home / "hooks.json"

    def tearDown(self):
        self.temp.cleanup()

    def hook(self, event, status="trusted", enabled=True, **updates):
        value = {
            "source": "user",
            "sourcePath": str(self.hooks_path),
            "command": f"python3 {SCRIPT.resolve()} hook --agent codex",
            "eventName": event,
            "enabled": enabled,
            "trustStatus": status,
        }
        value.update(updates)
        return value

    def hooks_result(self, hooks, errors=None, warnings=None):
        return {
            "data": [{
                "cwd": str(self.cwd),
                "hooks": hooks,
                "errors": errors or [],
                "warnings": warnings or [],
            }],
        }

    def evaluate(self, hooks, **entry_updates):
        result = self.hooks_result(hooks)
        result["data"][0].update(entry_updates)
        return mc.evaluate_codex_hook_trust(
            self.home,
            self.skill_root,
            self.cwd,
            str(self.codex_home),
            result,
        )

    def test_trusted_and_managed_pair_reports_ok_and_ignores_project_hook(self):
        result = self.evaluate([
            self.hook("sessionStart", "trusted"),
            self.hook("sessionEnd", "managed"),
            self.hook(
                "sessionStart", "untrusted", source="project",
                sourcePath=str(self.cwd / ".codex/hooks.json"),
            ),
        ])
        self.assertTrue(result["available"])
        self.assertTrue(result["ok"])
        self.assertIn("sessionStart=trusted", result["detail"])
        self.assertIn("sessionEnd=managed", result["detail"])

    def test_zero_one_and_disabled_matches_are_incomplete_not_unavailable(self):
        cases = (
            ([], ("sessionStart (missing)", "sessionEnd (missing)")),
            ([self.hook("sessionStart")], ("sessionEnd (missing)",)),
            (
                [self.hook("sessionStart"), self.hook("sessionEnd", enabled=False)],
                ("sessionEnd (disabled)",),
            ),
        )
        for hooks, expected in cases:
            with self.subTest(expected=expected):
                result = self.evaluate(hooks)
                self.assertTrue(result["available"])
                self.assertFalse(result["ok"])
                for phrase in expected:
                    self.assertIn(phrase, result["detail"])

    def test_untrusted_and_modified_hooks_are_actionable(self):
        for status in ("untrusted", "modified"):
            with self.subTest(status=status):
                result = self.evaluate([
                    self.hook("sessionStart", status),
                    self.hook("sessionEnd"),
                ])
                self.assertTrue(result["available"])
                self.assertFalse(result["ok"])
                self.assertIn(f"sessionStart={status}", result["detail"])
                self.assertIn("/hooks", result["detail"])

    def test_codex_home_mismatch_is_unverifiable_before_hook_matching(self):
        other_home = self.root / "other-codex-home"
        result = mc.evaluate_codex_hook_trust(
            self.home, self.skill_root, self.cwd, str(other_home), self.hooks_result([]),
        )
        self.assertFalse(result["available"])
        self.assertFalse(result["ok"])
        self.assertIn(str(self.codex_home), result["detail"])
        self.assertIn(str(other_home), result["detail"])
        self.assertNotIn("missing or disabled hooks", result["detail"])

    def test_relevant_error_is_unverifiable_but_unrelated_warning_is_not(self):
        error = {"path": str(self.hooks_path), "message": "invalid hook config"}
        result = self.evaluate(
            [self.hook("sessionStart"), self.hook("sessionEnd")], errors=[error],
        )
        self.assertFalse(result["available"])
        self.assertIn("invalid hook config", result["detail"])

        unrelated = self.evaluate(
            [self.hook("sessionStart"), self.hook("sessionEnd")],
            warnings=["project hook warning"],
        )
        self.assertTrue(unrelated["ok"])
        self.assertNotIn("project hook warning", unrelated["detail"])

    def test_malformed_or_partial_result_is_unverifiable(self):
        for result in (
            None,
            {},
            {"data": [{"cwd": str(self.cwd), "hooks": []}]},
        ):
            with self.subTest(result=result):
                evaluated = mc.evaluate_codex_hook_trust(
                    self.home,
                    self.skill_root,
                    self.cwd,
                    str(self.codex_home),
                    result,
                )
                self.assertFalse(evaluated["available"])

        unknown = self.evaluate([
            self.hook("sessionStart", "future-status"),
            self.hook("sessionEnd"),
        ])
        self.assertFalse(unknown["available"])

    def fake_process(self, mode="success"):
        hooks = [self.hook("sessionStart"), self.hook("sessionEnd")]
        return self.FakeProcess(
            mode,
            str(self.codex_home),
            self.hooks_result(hooks),
        )

    def test_probe_uses_experimental_ordered_protocol_and_terminates_child(self):
        process = self.fake_process()
        with mock.patch.object(mc.subprocess, "Popen", return_value=process) as popen:
            result = mc.probe_codex_hook_trust(
                self.home, self.skill_root, cwd=self.cwd,
            )
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            [message["method"] for message in process.received],
            ["initialize", "initialized", "hooks/list"],
        )
        self.assertIs(
            process.received[0]["params"]["capabilities"]["experimentalApi"],
            True,
        )
        self.assertTrue(process.terminated)
        command = popen.call_args.args[0]
        self.assertEqual(command, ["codex", "app-server", "--stdio"])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.cwd))

    def test_probe_reports_unavailable_unsupported_malformed_and_no_response(self):
        missing = FileNotFoundError("codex")
        with mock.patch.object(mc.subprocess, "Popen", side_effect=missing):
            unavailable = mc.probe_codex_hook_trust(
                self.home, self.skill_root, cwd=self.cwd,
            )
        self.assertFalse(unavailable["available"])
        self.assertIn("FileNotFoundError", unavailable["detail"])

        for mode, phrase in (
            ("unsupported", "unsupported"),
            ("malformed", "malformed app-server JSON"),
            ("no-response", "no response for request id 2"),
        ):
            with self.subTest(mode=mode):
                process = self.fake_process(mode)
                with mock.patch.object(mc.subprocess, "Popen", return_value=process):
                    result = mc.probe_codex_hook_trust(
                        self.home, self.skill_root, cwd=self.cwd,
                    )
                self.assertFalse(result["available"])
                self.assertIn(phrase, result["detail"])

    def test_probe_timeout_uses_one_short_total_budget_and_terminates_child(self):
        process = self.fake_process("timeout")
        started = time.monotonic()
        with (
            mock.patch.object(mc.subprocess, "Popen", return_value=process),
            mock.patch.object(mc, "CODEX_HOOK_PROBE_TIMEOUT_SECONDS", 0.08),
            mock.patch.object(mc, "CODEX_HOOK_PROBE_CLEANUP_RESERVE_SECONDS", 0.02),
        ):
            result = mc.probe_codex_hook_trust(
                self.home, self.skill_root, cwd=self.cwd,
            )
        elapsed = time.monotonic() - started
        self.assertFalse(result["available"])
        self.assertIn("timed out", result["detail"])
        self.assertLess(elapsed, 0.5)
        self.assertTrue(process.terminated or process.killed)


@unittest.skipUnless(shutil.which("codex"), "codex CLI is not available")
class CodexDiscoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.skill_root = SCRIPT.parents[1].resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_real_prompt_input_captures_legacy_dual_and_post_states(self):
        official, legacy_links = mc.skill_link_paths(self.home, "codex")
        legacy = legacy_links[0]
        legacy.parent.mkdir(parents=True)
        legacy.symlink_to(self.skill_root, target_is_directory=True)
        first = mc.probe_codex_discovery(self.home, self.skill_root)
        self.assertTrue(first["available"], first)
        self.assertEqual(len(first["entries"]), 1)
        self.assertTrue(mc.probe_has_root_entry(first, legacy.parent, self.skill_root))

        official.parent.mkdir(parents=True)
        official.symlink_to(self.skill_root, target_is_directory=True)
        dual = mc.probe_codex_discovery(self.home, self.skill_root)
        self.assertTrue(dual["available"], dual)
        self.assertEqual(len(dual["entries"]), 1)
        self.assertTrue(all(entry["canonical"] for entry in dual["entries"]))
        self.assertTrue(mc.probe_has_root_entry(dual, legacy.parent, self.skill_root))

        legacy.unlink()
        post = mc.probe_codex_discovery(self.home, self.skill_root)
        self.assertTrue(post["available"], post)
        self.assertEqual(len(post["entries"]), 1)
        self.assertTrue(mc.probe_has_root_entry(post, official.parent, self.skill_root))

    def test_real_setup_migrates_an_installed_1_0_fixture(self):
        official, legacy_links = mc.skill_link_paths(self.home, "codex")
        legacy = legacy_links[0]
        legacy.parent.mkdir(parents=True)
        legacy.symlink_to(self.skill_root, target_is_directory=True)
        chat = Path(self.temp.name) / "chat"
        runtime = chat / "_runtime"
        runtime.mkdir(parents=True)
        candidate = (self.skill_root / "assets/PROTOCOL.md").read_text(encoding="utf-8")
        baseline = candidate.replace("Version: 1.1", "Version: 1.0", 1)
        baseline = baseline.replace(
            "under `~/.agents/`,\n  `~/.codex/`, or `~/.claude/`",
            "under `~/.codex/` or\n  `~/.claude/`",
            1,
        )
        baseline = baseline.replace(
            "~/.agents/skills/multiagent-collab/",
            "~/.codex/skills/multiagent-collab/",
            1,
        )
        (chat / "PROTOCOL.md").write_text(baseline, encoding="utf-8")
        (runtime / "install.json").write_bytes(mc.json_bytes({
            "skill_root": str(self.skill_root),
            "chat_root": str(chat),
            "protocol_version": "1.0",
            "protocol_sha256": mc.sha256_bytes(baseline.encode("utf-8")),
            "agents": ["codex"],
            "created_config": [],
            "original_config": {},
        }))

        mc.setup(Args(
            agent="codex",
            home=str(self.home),
            chat_root=str(chat),
            dry_run=False,
            follow_config_symlinks=False,
            upgrade_protocol_from=mc.sha256_bytes(baseline.encode("utf-8")),
        ))

        self.assertTrue(official.is_symlink())
        self.assertEqual(official.resolve(), self.skill_root)
        self.assertFalse(legacy.exists())
        metadata = json.loads((runtime / "install.json").read_text())
        self.assertEqual(metadata["managed_links"], [str(official)])
        self.assertEqual(metadata["codex_discovery"]["phase"], "official")
        self.assertEqual(len(metadata["codex_discovery"]["entries"]), 1)
        self.assertTrue(
            mc.probe_has_root_entry(
                metadata["codex_discovery"], official.parent, self.skill_root,
            )
        )
        migration = metadata["codex_discovery"]["migration"]
        self.assertEqual(len(migration["dual"]["entries"]), 1)
        self.assertTrue(
            mc.probe_has_root_entry(migration["dual"], legacy.parent, self.skill_root)
        )
        self.assertTrue(
            mc.probe_has_root_entry(migration["post"], official.parent, self.skill_root)
        )
        self.assertEqual(
            (chat / "PROTOCOL.md").read_bytes(),
            (self.skill_root / "assets/PROTOCOL.md").read_bytes(),
        )


class DocumentationTests(unittest.TestCase):
    def test_protocol_1_1_candidate_is_exact_declared_delta(self):
        candidate = (SCRIPT.parents[1] / "assets/PROTOCOL.md").read_text(encoding="utf-8")
        self.assertEqual(candidate.count("Version: 1.1"), 1)
        self.assertEqual(candidate.count("~/.agents/skills/multiagent-collab/"), 1)
        self.assertEqual(candidate.count("under `~/.agents/`,"), 1)
        baseline = candidate.replace("Version: 1.1", "Version: 1.0", 1)
        baseline = baseline.replace(
            "under `~/.agents/`,\n  `~/.codex/`, or `~/.claude/`",
            "under `~/.codex/` or\n  `~/.claude/`",
            1,
        )
        baseline = baseline.replace(
            "~/.agents/skills/multiagent-collab/",
            "~/.codex/skills/multiagent-collab/",
            1,
        )
        self.assertEqual(
            mc.sha256_bytes(baseline.encode("utf-8")),
            "5f9204f1dc9299a78f8f125cf2787f612a69efa67d9eb71c5a7ce4254e6f2027",
        )

    def test_multiagent_readme_commands_parse_and_shell_blocks_are_valid(self):
        readme = (SCRIPT.parents[2] / "README.md").read_text(encoding="utf-8")
        section = readme.split("### `multiagent-collab` for Codex and Claude", 1)[1]
        section = section.split("### Skills", 1)[0]
        blocks = re.findall(r"```bash\n(.*?)```", section, re.DOTALL)
        self.assertGreaterEqual(len(blocks), 4)
        syntax = subprocess.run(
            ["bash", "-n"], input="\n".join(blocks), text=True,
            capture_output=True, check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        parsed = 0
        allowed = ("git ", "cd ", "sha256sum ")
        for block in blocks:
            for raw in block.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("python3 multiagent-collab/scripts/multiagent_collab.py "):
                    words = shlex.split(line)
                    argv = ["0" * 64 if word == "APPROVED_CURRENT_SHA256" else word for word in words[2:]]
                    mc.build_parser().parse_args(argv)
                    parsed += 1
                else:
                    self.assertTrue(line.startswith(allowed), line)
        self.assertEqual(parsed, 7)
        for phrase in (
            "codex-cli 0.154.0", "/hooks", "tail -n 0 -F", "`release`",
            "`bind`", "does not start agents", "claims or removes",
        ):
            self.assertIn(phrase, section)


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

    def test_task_init_pins_roles_and_rejects_owner_mismatch(self):
        baton = mc.parse_baton(self.chat / self.task_id / "BATON.md")
        self.assertEqual(
            (baton["owner"], baton["reviewer"], baton["task_sha256"]),
            ("codex", "claude", "pending"),
        )
        other = self.root / "other-task.md"
        other.write_text("# Task\n\nOwner: Claude\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.task_init(
                Args(
                    chat_root=str(self.chat), task_id="20260911-002-owner-mismatch",
                    owner="codex", task_file=str(other),
                )
            )
        self.assertFalse((self.chat / "20260911-002-owner-mismatch").exists())

    def test_unpinned_legacy_task_requires_hash_checked_operator_migration(self):
        task = self.chat / self.task_id
        baton_path = task / "BATON.md"
        unpinned = "\n".join(
            line for line in baton_path.read_text().splitlines()
            if not line.startswith(("owner:", "reviewer:", "task_sha256:"))
        ) + "\n"
        mc.atomic_text(baton_path, unpinned)
        turn = self.root / "turn.md"
        turn.write_text("Result: no implicit migration.\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                    expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                    round=None, revision=None, verdict="PASS", owner_ready="keep",
                    reviewer_ready="true", ask="Continue.", ministerial=False,
                )
            )
        mc.atomic_text(baton_path, unpinned.replace("holder: claude", "holder: operator"))
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "migrate and approve"\n', encoding="utf-8")
        task_hash = mc.sha256_file(task / "TASK.md")
        with self.assertRaises(mc.UserError):
            mc.operator_relay(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                    expected_seq=1, action="ruling", next_holder="codex",
                    log_file=str(quote), ask="Continue.", break_stale_lock=False,
                    task_sha256=None,
                )
            )
        mc.operator_relay(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                expected_seq=1, action="approve", next_holder="codex",
                log_file=str(quote), ask="Implement.", break_stale_lock=False,
                task_sha256=task_hash,
            )
        )
        migrated = mc.parse_baton(baton_path)
        self.assertEqual(
            (migrated["owner"], migrated["reviewer"], migrated["task_sha256"]),
            ("codex", "claude", task_hash),
        )

    def test_role_pin_and_approved_task_hash_reject_contract_tampering(self):
        task = self.chat / self.task_id
        turn = self.root / "turn.md"
        turn.write_text("Result: attempted transition.\n", encoding="utf-8")
        original = (task / "TASK.md").read_text()
        (task / "TASK.md").write_text(original.replace("Owner: Codex", "Owner: Claude"), encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                    expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                    round=None, revision=None, verdict="PASS", owner_ready="keep",
                    reviewer_ready="true", ask="No.", ministerial=False,
                )
            )
        (task / "TASK.md").write_text(original, encoding="utf-8")
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "operator"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "approved"\n', encoding="utf-8")
        mc.operator_relay(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                expected_seq=1, action="approve", next_holder="codex",
                log_file=str(quote), ask="Implement.", break_stale_lock=False,
                task_sha256=mc.sha256_file(task / "TASK.md"),
            )
        )
        approved = mc.parse_baton(task / "BATON.md")
        self.assertEqual(approved["task_sha256"], mc.sha256_file(task / "TASK.md"))
        (task / "TASK.md").write_text(original + "\nChanged without approval.\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                    expected_seq=2, next_holder="claude", log_file=str(turn), status=None,
                    round=1, revision="sha256:new", verdict=None, owner_ready="true",
                    reviewer_ready="keep", ask="Review.", ministerial=False,
                )
            )

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

    def test_parser_rejects_duplicate_fields(self):
        baton_path = self.chat / self.task_id / "BATON.md"
        baton_path.write_text(baton_path.read_text() + "holder: operator\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.parse_baton(baton_path)

    def test_parser_rejects_incomplete_or_invalid_contract_pins(self):
        baton_path = self.chat / self.task_id / "BATON.md"
        original = mc.parse_baton(baton_path)
        complete = mc.dump_baton(original)
        cases = (
            complete.replace("reviewer: claude\n", ""),
            complete.replace("reviewer: claude", "reviewer: codex"),
            complete.replace("task_sha256: pending", "task_sha256: not-a-hash"),
        )
        for text in cases:
            with self.subTest(text=text[:80]):
                mc.atomic_text(baton_path, text)
                with self.assertRaises(mc.UserError):
                    mc.parse_baton(baton_path)

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

    def test_owner_cannot_set_verdict_or_use_ministerial_bypass(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "codex"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        turn = self.root / "turn.md"
        turn.write_text("Result: bypass rejected.\n", encoding="utf-8")
        for ministerial, verdict in ((False, "PASS"), (True, None)):
            with self.subTest(ministerial=ministerial, verdict=verdict):
                with self.assertRaises(mc.UserError):
                    mc.baton_pass(
                        Args(
                            chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                            expected_seq=1, next_holder="claude", log_file=str(turn), status=None,
                            round=None, revision=None, verdict=verdict, owner_ready="keep",
                            reviewer_ready="keep", ask="No.", ministerial=ministerial,
                        )
                    )

    def test_pass_to_operator_requires_recorded_reason(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "codex"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        turn = self.root / "turn.md"
        turn.write_text("Result: operator review.\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                    expected_seq=1, next_holder="operator", log_file=str(turn), status=None,
                    round=None, revision=None, verdict=None, owner_ready="keep",
                    reviewer_ready="keep", ask="Review.", ministerial=False,
                )
            )
        accepted = Args(
            chat_root=str(self.chat), task_id=self.task_id, agent="codex",
            expected_seq=1, next_holder="operator", log_file=str(turn), status=None,
            round=None, revision=None, verdict=None, owner_ready="keep",
            reviewer_ready="keep", ask="Review.", ministerial=False,
            operator_reason="contract",
        )
        mc.baton_pass(accepted)
        baton = mc.parse_baton(task / "BATON.md")
        self.assertEqual(baton["ask"], "[contract] Review.")
        self.assertIn("to operator (contract)", (task / "LOG.md").read_text())
        baton["holder"] = "claude"
        baton["seq"] = 1
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
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

    def test_blocked_clears_both_readiness_flags(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["owner_ready"] = True
        baton["reviewer_ready"] = True
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        turn = self.root / "turn.md"
        turn.write_text("Result: blocked.\n", encoding="utf-8")
        mc.baton_pass(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                expected_seq=1, next_holder="operator", log_file=str(turn), status="blocked",
                round=1, revision=None, verdict="BLOCKED", owner_ready="keep",
                reviewer_ready="keep", ask="Rule.", ministerial=False,
                operator_reason="blocked",
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
        baton["task_sha256"] = mc.sha256_file(task / "TASK.md")
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
        args.agent = "claude"
        with self.assertRaises(mc.UserError):
            mc.signoff(args)
        args.agent = "codex"
        baton["reviewer_ready"] = True
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        mc.signoff(args)
        baton = mc.parse_baton(task / "BATON.md")
        self.assertEqual(baton["holder"], "operator")
        self.assertEqual(baton["ask"], "[signoff] Review and close.")
        self.assertIn("to operator (signoff)", (task / "LOG.md").read_text())

    def test_signoff_cannot_reactivate_blocked_or_done_task(self):
        task = self.chat / self.task_id
        turn = self.root / "turn.md"
        turn.write_text("Result: invalid signoff.\n", encoding="utf-8")
        args = Args(
            chat_root=str(self.chat), task_id=self.task_id, agent="codex",
            expected_seq=1, log_file=str(turn), ask="Close.",
            break_stale_lock=False,
        )
        for status in ("blocked", "done"):
            with self.subTest(status=status):
                baton = mc.parse_baton(task / "BATON.md")
                baton.update(
                    holder="codex", status=status, verdict="PASS",
                    owner_ready=True, reviewer_ready=True,
                    task_sha256=mc.sha256_file(task / "TASK.md"),
                )
                mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
                before = (task / "BATON.md").read_bytes()
                with self.assertRaises(mc.UserError):
                    mc.signoff(args)
                self.assertEqual((task / "BATON.md").read_bytes(), before)

    def test_signoff_passes_no_status_override_to_baton_gate(self):
        args = Args(
            chat_root=str(self.chat), task_id=self.task_id, agent="codex",
            expected_seq=1, log_file=str(self.root / "turn.md"), ask="Close.",
            break_stale_lock=False,
        )
        with mock.patch.object(mc, "baton_pass", return_value=0) as baton_pass:
            self.assertEqual(mc.signoff(args), 0)
        baton_pass.assert_called_once_with(args)
        self.assertIsNone(args.status)

    def test_signoff_rejects_nonowner_and_each_missing_review_gate(self):
        task = self.chat / self.task_id
        turn = self.root / "turn.md"
        turn.write_text("Result: invalid signoff.\n", encoding="utf-8")
        cases = (
            ("nonowner", {"holder": "claude", "agent": "claude"}),
            ("no pass", {"verdict": "none"}),
            ("owner unready", {"owner_ready": False}),
            ("reviewer unready", {"reviewer_ready": False}),
            ("unapproved contract", {"task_sha256": "pending"}),
        )
        for label, changes in cases:
            with self.subTest(label=label):
                baton = mc.parse_baton(task / "BATON.md")
                baton.update(
                    holder="codex", status="active", verdict="PASS",
                    owner_ready=True, reviewer_ready=True,
                    task_sha256=mc.sha256_file(task / "TASK.md"),
                )
                values = dict(changes)
                agent = values.pop("agent", "codex")
                baton.update(values)
                mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
                with self.assertRaises(mc.UserError):
                    mc.signoff(
                        Args(
                            chat_root=str(self.chat), task_id=self.task_id,
                            agent=agent, expected_seq=1, log_file=str(turn),
                            ask="Close.", break_stale_lock=False,
                        )
                    )

    def test_closed_or_blocked_task_cannot_be_reopened_by_normal_pass(self):
        task = self.chat / self.task_id
        turn = self.root / "turn.md"
        turn.write_text("Result: invalid reopen.\n", encoding="utf-8")
        for current_status in ("blocked", "done"):
            with self.subTest(current_status=current_status):
                baton = mc.parse_baton(task / "BATON.md")
                baton.update(holder="codex", status=current_status)
                mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
                with self.assertRaises(mc.UserError):
                    mc.baton_pass(
                        Args(
                            chat_root=str(self.chat), task_id=self.task_id,
                            agent="codex", expected_seq=1, next_holder="claude",
                            log_file=str(turn), status="active", round=None,
                            revision=None, verdict=None, owner_ready="keep",
                            reviewer_ready="keep", ask="Reopen.", ministerial=False,
                        )
                    )

    def test_normal_pass_cannot_set_done_or_none_independently(self):
        task = self.chat / self.task_id
        turn = self.root / "turn.md"
        turn.write_text("Result: invalid completion.\n", encoding="utf-8")
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "codex"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        for status, next_holder in (("done", "claude"), ("active", "none")):
            with self.subTest(status=status, next_holder=next_holder):
                with self.assertRaises(mc.UserError):
                    mc.baton_pass(
                        Args(
                            chat_root=str(self.chat), task_id=self.task_id,
                            agent="codex", expected_seq=1, next_holder=next_holder,
                            log_file=str(turn), status=status, round=None,
                            revision=None, verdict=None, owner_ready="keep",
                            reviewer_ready="keep", ask="Complete.", ministerial=False,
                        )
                    )

    def test_operator_relay_approve_returns_baton_to_owner(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton.update(
            holder="operator", verdict="PASS",
            owner_ready=True, reviewer_ready=True,
        )
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        words = self.root / "operator.md"
        words.write_text('Operator response: "approved"\n', encoding="utf-8")
        mc.operator_relay(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                expected_seq=1, action="approve", next_holder="codex",
                log_file=str(words), ask="Implement.", break_stale_lock=False,
                task_sha256=mc.sha256_file(task / "TASK.md"),
            )
        )
        baton = mc.parse_baton(task / "BATON.md")
        self.assertEqual((baton["seq"], baton["holder"]), (2, "codex"))
        self.assertEqual(baton["task_sha256"], mc.sha256_file(task / "TASK.md"))
        self.assertEqual((baton["verdict"], baton["owner_ready"], baton["reviewer_ready"]), ("none", False, False))
        self.assertIn("operator approve via codex", (task / "LOG.md").read_text())
        self.assertIn(f"task_sha256={baton['task_sha256']}", (task / "LOG.md").read_text())

    def test_operator_approval_hash_is_compare_and_swap(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "operator"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "approved shown hash"\n', encoding="utf-8")
        presented = mc.sha256_file(task / "TASK.md")
        base = dict(
            chat_root=str(self.chat), task_id=self.task_id, agent="codex",
            expected_seq=1, action="approve", next_holder="codex",
            log_file=str(quote), ask="Implement.", break_stale_lock=False,
        )
        for candidate in (None, "0" * 64, presented.upper(), f" {presented}", f"{presented} "):
            with self.subTest(candidate=candidate):
                with self.assertRaises(mc.UserError):
                    mc.operator_relay(Args(**base, task_sha256=candidate))
        (task / "TASK.md").write_text(
            (task / "TASK.md").read_text() + "\nChanged after presentation.\n",
            encoding="utf-8",
        )
        with self.assertRaises(mc.UserError):
            mc.operator_relay(Args(**base, task_sha256=presented))
        current = mc.sha256_file(task / "TASK.md")
        mc.operator_relay(Args(**base, task_sha256=current))
        approved = mc.parse_baton(task / "BATON.md")
        self.assertEqual(approved["task_sha256"], current)

    def test_operator_amend_hash_is_compare_and_swap(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        old_hash = mc.sha256_file(task / "TASK.md")
        baton.update(holder="operator", task_sha256=old_hash)
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        (task / "TASK.md").write_text(
            (task / "TASK.md").read_text() + "\nProposed amendment.\n",
            encoding="utf-8",
        )
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "amend"\n', encoding="utf-8")
        base = dict(
            chat_root=str(self.chat), task_id=self.task_id, agent="claude",
            expected_seq=1, action="amend", next_holder="codex",
            log_file=str(quote), ask="Review amendment.", break_stale_lock=False,
        )
        for candidate in (None, old_hash):
            with self.subTest(candidate=candidate):
                with self.assertRaises(mc.UserError):
                    mc.operator_relay(Args(**base, task_sha256=candidate))
        amended_hash = mc.sha256_file(task / "TASK.md")
        mc.operator_relay(Args(**base, task_sha256=amended_hash))
        self.assertEqual(mc.parse_baton(task / "BATON.md")["task_sha256"], amended_hash)

    def test_pending_contract_cannot_reach_signoff_or_close(self):
        task = self.chat / self.task_id
        turn = self.root / "turn.md"
        turn.write_text("Result: ready.\n", encoding="utf-8")
        baton = mc.parse_baton(task / "BATON.md")
        baton.update(
            holder="codex", status="active", verdict="PASS",
            owner_ready=True, reviewer_ready=True,
        )
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        with self.assertRaises(mc.UserError):
            mc.signoff(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id,
                    agent="codex", expected_seq=1, log_file=str(turn),
                    ask="Close.", break_stale_lock=False,
                )
            )
        baton["holder"] = "operator"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "CLOSE"\n', encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.operator_relay(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id,
                    agent="claude", expected_seq=1, action="close",
                    next_holder="codex", log_file=str(quote), ask="Archive.",
                    break_stale_lock=False, task_sha256=None,
                )
            )

    def test_operator_relay_requires_nonempty_verbatim_quote(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "operator"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        before_baton = (task / "BATON.md").read_bytes()
        before_log = (task / "LOG.md").read_bytes()
        quote = self.root / "operator.md"
        quote.write_text(" \n\t\n", encoding="utf-8")
        args = Args(
            chat_root=str(self.chat), task_id=self.task_id, agent="claude",
            expected_seq=1, action="approve", next_holder="codex",
            log_file=str(quote), ask="Implement.", break_stale_lock=False,
            task_sha256=mc.sha256_file(task / "TASK.md"),
        )
        with self.assertRaises(mc.UserError):
            mc.operator_relay(args)
        self.assertEqual((task / "BATON.md").read_bytes(), before_baton)
        self.assertEqual((task / "LOG.md").read_bytes(), before_log)
        quote.write_bytes(b"\xff")
        with self.assertRaises(mc.UserError):
            mc.operator_relay(args)
        self.assertEqual((task / "BATON.md").read_bytes(), before_baton)
        self.assertEqual((task / "LOG.md").read_bytes(), before_log)
        exact = b'Operator response: "approved exactly"  \r\nSecond line.\n'
        quote.write_bytes(exact)
        mc.operator_relay(args)
        self.assertTrue((task / "LOG.md").read_bytes().endswith(exact))

    def test_operator_quote_preserves_trailing_spaces_without_newline(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "operator"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        quote = self.root / "operator.md"
        exact = b'Operator response: "approved"   '
        quote.write_bytes(exact)
        mc.operator_relay(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                expected_seq=1, action="approve", next_holder="codex",
                log_file=str(quote), ask="Implement.", break_stale_lock=False,
                task_sha256=mc.sha256_file(task / "TASK.md"),
            )
        )
        self.assertTrue((task / "LOG.md").read_bytes().endswith(exact + b"\n"))

    def test_operator_amend_and_ruling_invalidate_review_state(self):
        task = self.chat / self.task_id
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "amend"\n', encoding="utf-8")
        for action, next_holder in (("amend", "codex"), ("ruling", "claude")):
            with self.subTest(action=action):
                baton = mc.parse_baton(task / "BATON.md")
                baton.update(
                    holder="operator", verdict="PASS", owner_ready=True,
                    reviewer_ready=True,
                )
                if action == "amend":
                    (task / "TASK.md").write_text(
                        (task / "TASK.md").read_text() + "\nApproved delta.\n",
                        encoding="utf-8",
                    )
                mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
                mc.operator_relay(
                    Args(
                        chat_root=str(self.chat), task_id=self.task_id,
                        agent="codex", expected_seq=baton["seq"], action=action,
                        next_holder=next_holder, log_file=str(quote), ask="Continue.",
                        break_stale_lock=False,
                        task_sha256=(mc.sha256_file(task / "TASK.md") if action == "amend" else None),
                    )
                )
                changed = mc.parse_baton(task / "BATON.md")
                self.assertEqual(
                    (changed["verdict"], changed["owner_ready"], changed["reviewer_ready"]),
                    ("none", False, False),
                )
                if action == "amend":
                    self.assertEqual(changed["task_sha256"], mc.sha256_file(task / "TASK.md"))

    def test_operator_stop_does_not_require_task_owner_parsing(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton.update(verdict="PASS", owner_ready=True, reviewer_ready=True)
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        (task / "TASK.md").unlink()
        words = self.root / "operator.md"
        words.write_text('Operator response: "stop"\n', encoding="utf-8")
        mc.operator_relay(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                expected_seq=1, action="stop", next_holder="operator",
                log_file=str(words), ask="Stopped.", break_stale_lock=False,
            )
        )
        baton = mc.parse_baton(task / "BATON.md")
        self.assertEqual((baton["holder"], baton["status"], baton["verdict"]), ("operator", "blocked", "BLOCKED"))
        self.assertEqual((baton["owner_ready"], baton["reviewer_ready"]), (False, False))

    def test_operator_relay_transition_guards(self):
        task = self.chat / self.task_id
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "directed action"\n', encoding="utf-8")

        def relay(action, next_holder):
            return mc.operator_relay(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                    expected_seq=1, action=action, next_holder=next_holder,
                    log_file=str(quote), ask="Act.", break_stale_lock=False,
                    task_sha256=(
                        mc.sha256_file(task / "TASK.md")
                        if action in {"approve", "amend"} else None
                    ),
                )
            )

        with self.assertRaises(mc.UserError):
            relay("approve", "codex")
        with self.assertRaises(mc.UserError):
            relay("stop", "codex")
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "operator"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        with self.assertRaises(mc.UserError):
            mc.operator_relay(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id,
                    agent="codex", expected_seq=99, action="approve",
                    next_holder="codex", log_file=str(quote), ask="Act.",
                    break_stale_lock=False,
                )
            )
        for action, next_holder in (
            ("approve", "claude"),
            ("close", "claude"),
            ("amend", "operator"),
            ("ruling", "operator"),
            ("unknown", "codex"),
        ):
            with self.subTest(action=action, next_holder=next_holder):
                with self.assertRaises(mc.UserError):
                    relay(action, next_holder)
        self.assertEqual(mc.parse_baton(task / "BATON.md")["seq"], 1)

    def test_operator_relay_respects_baton_lock(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "operator"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        lock = task / ".baton.lock"
        lock.mkdir()
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "approved"\n', encoding="utf-8")
        before_baton = (task / "BATON.md").read_bytes()
        before_log = (task / "LOG.md").read_bytes()
        with self.assertRaises(mc.UserError):
            mc.operator_relay(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id,
                    agent="codex", expected_seq=1, action="approve",
                    next_holder="codex", log_file=str(quote), ask="Implement.",
                    task_sha256=mc.sha256_file(task / "TASK.md"),
                    break_stale_lock=False,
                )
            )
        self.assertEqual((task / "BATON.md").read_bytes(), before_baton)
        self.assertEqual((task / "LOG.md").read_bytes(), before_log)
        self.assertTrue(lock.is_dir())

    def test_operator_relay_sequence_check_isolated(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "operator"
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "approved"\n', encoding="utf-8")
        before = (task / "BATON.md").read_bytes()
        with self.assertRaisesRegex(mc.UserError, "sequence changed"):
            mc.operator_relay(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id,
                    agent="codex", expected_seq=99, action="approve",
                    next_holder="codex", log_file=str(quote), ask="Implement.",
                    task_sha256=mc.sha256_file(task / "TASK.md"),
                    break_stale_lock=False,
                )
            )
        self.assertEqual((task / "BATON.md").read_bytes(), before)

    def test_operator_close_nonowner_target_check_isolated(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton.update(
            holder="operator", task_sha256=mc.sha256_file(task / "TASK.md"),
            verdict="PASS", owner_ready=True, reviewer_ready=True,
        )
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "CLOSE"\n', encoding="utf-8")
        with self.assertRaisesRegex(mc.UserError, "cleanup turn to the task owner"):
            mc.operator_relay(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id,
                    agent="claude", expected_seq=1, action="close",
                    next_holder="claude", log_file=str(quote), ask="Archive.",
                    break_stale_lock=False, task_sha256=None,
                )
            )

    def test_operator_close_requires_each_review_gate(self):
        task = self.chat / self.task_id
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "CLOSE"\n', encoding="utf-8")
        cases = (
            ("no pass", {"verdict": "none"}),
            ("owner unready", {"owner_ready": False}),
            ("reviewer unready", {"reviewer_ready": False}),
        )
        for label, changes in cases:
            with self.subTest(label=label):
                baton = mc.parse_baton(task / "BATON.md")
                baton.update(
                    holder="operator", status="active", verdict="PASS",
                    owner_ready=True, reviewer_ready=True,
                    task_sha256=mc.sha256_file(task / "TASK.md"),
                )
                baton.update(changes)
                mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
                with self.assertRaises(mc.UserError):
                    mc.operator_relay(
                        Args(
                            chat_root=str(self.chat), task_id=self.task_id,
                            agent="claude", expected_seq=1, action="close",
                            next_holder="codex", log_file=str(quote), ask="Archive.",
                            break_stale_lock=False,
                        )
                    )

    def test_operator_ruling_and_close_reject_unapproved_task_drift(self):
        task = self.chat / self.task_id
        approved_hash = mc.sha256_file(task / "TASK.md")
        (task / "TASK.md").write_text(
            (task / "TASK.md").read_text() + "\nUnapproved scope.\n",
            encoding="utf-8",
        )
        quote = self.root / "operator.md"
        quote.write_text('Operator response: "continue"\n', encoding="utf-8")
        for action, next_holder in (("ruling", "codex"), ("close", "codex")):
            with self.subTest(action=action):
                baton = mc.parse_baton(task / "BATON.md")
                baton.update(
                    holder="operator", task_sha256=approved_hash,
                    verdict="PASS", owner_ready=True, reviewer_ready=True,
                )
                mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
                with self.assertRaises(mc.UserError):
                    mc.operator_relay(
                        Args(
                            chat_root=str(self.chat), task_id=self.task_id,
                            agent="claude", expected_seq=1, action=action,
                            next_holder=next_holder, log_file=str(quote), ask="Continue.",
                            break_stale_lock=False, task_sha256=None,
                        )
                    )

    def test_close_requires_operator_relay_and_both_readiness(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton.update(
            holder="operator", verdict="PASS", owner_ready=True,
            reviewer_ready=True, task_sha256=mc.sha256_file(task / "TASK.md"),
        )
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        words = self.root / "operator.md"
        words.write_text('Operator response: "CLOSE"\n', encoding="utf-8")
        mc.operator_relay(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                expected_seq=1, action="close", next_holder="codex",
                log_file=str(words), ask="Archive.", break_stale_lock=False,
            )
        )
        closed = mc.parse_baton(task / "BATON.md")
        self.assertEqual((closed["holder"], closed["status"]), ("codex", "done"))
        turn = self.root / "turn.md"
        turn.write_text("Result: bypass.\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.baton_pass(
                Args(
                    chat_root=str(self.chat), task_id=self.task_id, agent="codex",
                    expected_seq=2, next_holder="none", log_file=str(turn), status="done",
                    round=None, revision=None, verdict=None, owner_ready="keep",
                    reviewer_ready="keep", ask="Done.", ministerial=False,
                )
            )

    def test_revision_change_clears_stale_pass_verdict(self):
        task = self.chat / self.task_id
        baton = mc.parse_baton(task / "BATON.md")
        baton.update(holder="claude", verdict="PASS", owner_ready=True, reviewer_ready=True)
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        turn = self.root / "turn.md"
        turn.write_text("Result: review new revision.\n", encoding="utf-8")
        mc.baton_pass(
            Args(
                chat_root=str(self.chat), task_id=self.task_id, agent="claude",
                expected_seq=1, next_holder="codex", log_file=str(turn), status=None,
                round=2, revision="new-revision", verdict=None, owner_ready="keep",
                reviewer_ready="true", ask="Confirm.", ministerial=False,
            )
        )
        changed = mc.parse_baton(task / "BATON.md")
        self.assertEqual(changed["verdict"], "none")
        self.assertFalse(changed["owner_ready"])


class WatcherAndArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.chat = self.root / "chat"
        self.chat.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_task(self, task_id="20260911-002-watch-test", holder="codex", status="active", ready=False):
        task = self.chat / task_id
        task.mkdir()
        (task / "TASK.md").write_text("# Task\n\nOwner: Codex\n", encoding="utf-8")
        (task / "LOG.md").write_text("# Log\n", encoding="utf-8")
        baton = {
            "task": task_id, "owner": "codex", "reviewer": "claude",
            "task_sha256": mc.sha256_file(task / "TASK.md"),
            "seq": 1, "holder": holder, "status": status,
            "round": 0, "revision": "sha256:test", "verdict": "PASS" if ready else "none",
            "owner_ready": ready, "reviewer_ready": ready, "ask": "Act.",
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

    def test_task_commands_refuse_symlinked_task_directory(self):
        real = self.root / "real-task"
        real.mkdir()
        (self.chat / "20260911-099-symlink-task").symlink_to(real, target_is_directory=True)
        with self.assertRaises(mc.UserError):
            mc.status(
                Args(
                    chat_root=str(self.chat), task_id="20260911-099-symlink-task",
                    json=False,
                )
            )

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

    def test_watcher_rejects_task_contract_hash_drift(self):
        task = self.make_task()
        (task / "TASK.md").write_text(
            (task / "TASK.md").read_text() + "\nUnapproved scope.\n",
            encoding="utf-8",
        )
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {
            "agent": "codex", "session_id": "s",
            "wake_mode": "monitor-file", "wake_verified": True,
        }
        state = {
            "session_id": "s", "notified": {}, "attempts": {},
            "failed": [], "unverified": [], "stale": [],
        }
        self.assertTrue(mc.scan_once(self.chat, binding, state))
        self.assertNotIn(task.name, state["notified"])
        self.assertIn("operator-approved contract hash", (runtime / "monitor.inbox").read_text())
        self.assertIn("operator-approved contract hash", (runtime / "alerts.log").read_text())

    def test_malformed_alert_is_logged_and_surfaced_once_per_fingerprint(self):
        task = self.make_task(holder="claude")
        original_task = (task / "TASK.md").read_text()
        (task / "TASK.md").write_text(original_task + "\nDrift one.\n", encoding="utf-8")
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {
            "agent": "codex", "session_id": "s",
            "wake_mode": "command", "wake_verified": True,
        }
        state = {
            "session_id": "s", "notified": {}, "attempts": {},
            "failed": [], "unverified": [], "stale": [],
        }
        with mock.patch.object(mc, "wake", return_value=True) as wake:
            self.assertTrue(mc.scan_once(self.chat, binding, state))
            for _ in range(99):
                self.assertFalse(mc.scan_once(self.chat, binding, state))
        alerts = (runtime / "alerts.log").read_text()
        self.assertEqual(alerts.count("ignored malformed task"), 1)
        self.assertEqual(wake.call_count, 1)
        self.assertEqual(state["malformed"].keys(), {task.name})
        self.assertEqual(state["malformed_surfaced"].keys(), {task.name})

        (task / "TASK.md").write_text(original_task + "\nDrift two.\n", encoding="utf-8")
        with mock.patch.object(mc, "wake", return_value=True) as changed_wake:
            self.assertTrue(mc.scan_once(self.chat, binding, state))
        self.assertEqual((runtime / "alerts.log").read_text().count("ignored malformed task"), 2)
        changed_wake.assert_called_once()

        (task / "TASK.md").write_text(original_task, encoding="utf-8")
        self.assertTrue(mc.scan_once(self.chat, binding, state))
        self.assertEqual(state["malformed"], {})
        self.assertEqual(state["malformed_surfaced"], {})
        (task / "TASK.md").write_text(original_task + "\nDrift two.\n", encoding="utf-8")
        with mock.patch.object(mc, "wake", return_value=True):
            self.assertTrue(mc.scan_once(self.chat, binding, state))
        self.assertEqual((runtime / "alerts.log").read_text().count("ignored malformed task"), 3)

    def test_unverified_malformed_alert_surfaces_after_wake_verification(self):
        task = self.make_task(holder="claude")
        (task / "TASK.md").write_text(
            (task / "TASK.md").read_text() + "\nDrift.\n",
            encoding="utf-8",
        )
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {
            "agent": "codex", "session_id": "s",
            "wake_mode": "command", "wake_verified": False,
        }
        state = {
            "session_id": "s", "notified": {}, "attempts": {},
            "failed": [], "unverified": [], "stale": [],
        }
        self.assertTrue(mc.scan_once(self.chat, binding, state))
        self.assertEqual((runtime / "alerts.log").read_text().count("ignored malformed task"), 1)
        self.assertEqual(state["malformed_surfaced"], {})
        binding["wake_verified"] = True
        with mock.patch.object(mc, "wake", return_value=True) as wake:
            self.assertTrue(mc.scan_once(self.chat, binding, state))
        wake.assert_called_once()
        self.assertIn(task.name, state["malformed_surfaced"])
        self.assertEqual((runtime / "alerts.log").read_text().count("ignored malformed task"), 1)

    def test_removed_malformed_task_clears_dedupe_and_retry_state(self):
        task = self.make_task(holder="claude")
        (task / "TASK.md").write_text("# Task\n\nOwner: Claude\n", encoding="utf-8")
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {
            "agent": "codex", "session_id": "s",
            "wake_mode": "command", "wake_verified": True,
        }
        state = {
            "session_id": "s", "notified": {}, "attempts": {},
            "failed": [], "unverified": [], "stale": [],
        }
        with mock.patch.object(mc, "wake", return_value=False):
            mc.scan_once(self.chat, binding, state)
        self.assertIn(task.name, state["malformed"])
        attempt_key = next(
            key for key in state["attempts"]
            if key.startswith(f"malformed:{task.name}:")
        )
        state["failed"] = [attempt_key]
        original_rmtree = mc.shutil.rmtree
        original_rmtree(task)
        self.assertTrue(mc.scan_once(self.chat, binding, state))
        self.assertNotIn(task.name, state["malformed"])
        self.assertFalse(any(key.startswith(f"malformed:{task.name}:") for key in state["attempts"]))
        self.assertNotIn(attempt_key, state["failed"])

    def test_wake_failures_are_bounded_and_alert_once(self):
        self.make_task()
        runtime = self.chat / "_runtime/codex"
        runtime.mkdir(parents=True)
        binding = {"agent": "codex", "session_id": "s", "wake_mode": "command", "wake_verified": True}
        state = {"session_id": "s", "notified": {}, "attempts": {}, "failed": [], "unverified": [], "stale": []}
        with mock.patch.object(mc, "wake", return_value=False) as wake:
            for _ in range(12):
                key = "task:20260911-002-watch-test:1"
                if key in state["attempts"]:
                    state["attempts"][key]["next_at"] = 0
                mc.scan_once(self.chat, binding, state)
        self.assertEqual(wake.call_count, 12)
        self.assertEqual((runtime / "alerts.log").read_text().count("wake failed after"), 1)
        with mock.patch.object(mc, "wake", return_value=True) as recovered:
            self.assertFalse(mc.scan_once(self.chat, binding, state))
            recovered.assert_not_called()
            state["attempts"]["task:20260911-002-watch-test:1"]["next_at"] = 0
            mc.scan_once(self.chat, binding, state)
            recovered.assert_called_once()
            self.assertIn("transport has recovered", recovered.call_args.args[2])
        self.assertEqual(state["notified"]["20260911-002-watch-test"], 1)
        self.assertEqual((runtime / "alerts.log").read_text().count("wake failed after"), 1)

    def test_terminal_wake_failure_retries_at_recovery_deadline(self):
        runtime = self.chat / "_runtime/codex"
        binding = {
            "agent": "codex", "session_id": "s",
            "wake_mode": "command", "wake_verified": True,
        }
        state = {
            "session_id": "s", "notified": {}, "attempts": {},
            "failed": [], "unverified": [], "stale": [],
        }
        key = "task:20260911-002-watch-test:1"
        with mock.patch.object(mc.time, "time", return_value=100.0), mock.patch.object(mc, "wake", return_value=False) as failed_wake:
            for _ in range(3):
                if key in state["attempts"]:
                    state["attempts"][key]["next_at"] = 0
                self.assertFalse(mc.attempt_wake(binding, runtime, state, key, "deliver"))
        self.assertEqual(failed_wake.call_count, 3)
        self.assertIn(key, state["failed"])
        self.assertEqual(state["attempts"][key]["next_at"], 400.0)
        with mock.patch.object(mc.time, "time", return_value=399.0), mock.patch.object(mc, "wake", return_value=True) as too_early:
            self.assertFalse(mc.attempt_wake(binding, runtime, state, key, "deliver"))
        too_early.assert_not_called()
        with mock.patch.object(mc.time, "time", return_value=400.0), mock.patch.object(mc, "wake", return_value=True) as recovered:
            self.assertTrue(mc.attempt_wake(binding, runtime, state, key, "deliver"))
        recovered.assert_called_once()
        self.assertIn("transport has recovered", recovered.call_args.args[2])
        self.assertNotIn(key, state["attempts"])

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
        task = self.make_task(holder="codex", status="done", ready=True)
        mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, agent="codex", expected_seq=1))
        archive = self.chat / "_archive" / f"{task.name}.tar.gz"
        self.assertTrue(archive.is_file())
        self.assertFalse(task.exists())
        with tarfile.open(archive, "r:gz") as handle:
            names = handle.getnames()
        self.assertIn(f"{task.name}/MANIFEST.sha256", names)
        self.assertFalse(any(".baton.lock" in name for name in names))
        index = (self.chat / "_archive/INDEX.md").read_text()
        self.assertIn("owner codex", index)
        self.assertIn("result PASS", index)

    def test_archive_requires_done_state_and_holds_lock_through_removal(self):
        task = self.make_task()
        with self.assertRaises(mc.UserError):
            mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, agent="codex", expected_seq=1))
        self.assertTrue(task.exists())
        baton = mc.parse_baton(task / "BATON.md")
        baton["holder"] = "codex"
        baton["status"] = "done"
        baton["verdict"] = "PASS"
        baton["owner_ready"] = True
        baton["reviewer_ready"] = True
        mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
        original_rmtree = mc.shutil.rmtree

        def checked_rmtree(path, *args, **kwargs):
            if Path(path) == task:
                self.assertTrue((task / ".baton.lock").is_dir())
            return original_rmtree(path, *args, **kwargs)

        with mock.patch.object(mc.shutil, "rmtree", side_effect=checked_rmtree):
            mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, agent="codex", expected_seq=1))

    def test_archive_rejects_each_missing_cleanup_gate(self):
        task = self.make_task(holder="codex", status="done", ready=True)
        original = mc.parse_baton(task / "BATON.md")
        cases = (
            ("wrong agent", {"agent": "claude"}),
            ("wrong holder", {"holder": "claude"}),
            ("not done", {"status": "active"}),
            ("no pass", {"verdict": "none"}),
            ("owner unready", {"owner_ready": False}),
            ("reviewer unready", {"reviewer_ready": False}),
            ("unapproved contract", {"task_sha256": "pending"}),
        )
        for label, changes in cases:
            with self.subTest(label=label):
                baton = dict(original)
                agent = changes.pop("agent", "codex")
                baton.update(changes)
                mc.atomic_text(task / "BATON.md", mc.dump_baton(baton))
                with self.assertRaises(mc.UserError):
                    mc.archive_task(
                        Args(
                            chat_root=str(self.chat), task_id=task.name,
                            agent=agent, expected_seq=1,
                        )
                    )
                self.assertTrue(task.exists())
                self.assertFalse((self.chat / "_archive" / f"{task.name}.tar.gz").exists())
        mc.atomic_text(task / "BATON.md", mc.dump_baton(original))
        with self.assertRaises(mc.UserError):
            mc.archive_task(
                Args(
                    chat_root=str(self.chat), task_id=task.name,
                    agent="codex", expected_seq=99,
                )
            )
        (task / "TASK.md").write_text("# Task\n\nOwner: Claude\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.archive_task(
                Args(
                    chat_root=str(self.chat), task_id=task.name,
                    agent="codex", expected_seq=1,
                )
            )
        (task / "TASK.md").write_text(
            "# Task\n\nOwner: Codex\n\nUnapproved scope.\n",
            encoding="utf-8",
        )
        with self.assertRaises(mc.UserError):
            mc.archive_task(
                Args(
                    chat_root=str(self.chat), task_id=task.name,
                    agent="codex", expected_seq=1,
                )
            )

    def test_archive_calls_manifest_verifier_and_failure_preserves_task(self):
        task = self.make_task(holder="codex", status="done", ready=True)
        with mock.patch.object(mc, "verify_manifest", side_effect=mc.UserError("corrupt")) as verify:
            with self.assertRaises(mc.UserError):
                mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, agent="codex", expected_seq=1))
        verify.assert_called_once()
        self.assertTrue(task.exists())
        baton = mc.parse_baton(task / "BATON.md")
        self.assertEqual(baton["status"], "blocked")

    def test_manifest_verifier_rejects_changed_content(self):
        task = self.make_task(holder="codex", status="done", ready=True)
        mc.atomic_text(task / "MANIFEST.sha256", mc.manifest_text(mc.manifest_entries(task)))
        (task / "LOG.md").write_text("changed after manifest\n", encoding="utf-8")
        with self.assertRaises(mc.UserError):
            mc.verify_manifest(task)

    def test_archive_refuses_existing_baton_lock(self):
        task = self.make_task(holder="codex", status="done", ready=True)
        (task / ".baton.lock").mkdir()
        with self.assertRaises(mc.UserError):
            mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, agent="codex", expected_seq=1))
        self.assertTrue(task.exists())

    def test_archive_rechecks_sequence_before_removal(self):
        task = self.make_task(holder="codex", status="done", ready=True)
        original_parse = mc.parse_baton
        calls = 0

        def changed_on_final(path):
            nonlocal calls
            calls += 1
            baton = original_parse(path)
            if calls == 2:
                baton["seq"] += 1
            return baton

        with mock.patch.object(mc, "parse_baton", side_effect=changed_on_final):
            with self.assertRaises(mc.UserError):
                mc.archive_task(Args(chat_root=str(self.chat), task_id=task.name, agent="codex", expected_seq=1))
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

    def test_explicit_same_session_rebind_resets_delivery_state(self):
        binding_path, _, _ = mc.binding_paths(self.chat, "codex")
        binding_path.parent.mkdir(parents=True)
        mc.atomic_write(
            binding_path,
            mc.json_bytes({
                "agent": "codex", "session_id": "session-a", "pid": 0,
                "chat_root": str(self.chat), "wake_mode": "codex-queue",
            }),
        )
        state_path = binding_path.parent / "watch-state.json"
        mc.atomic_write(state_path, mc.json_bytes({"session_id": "session-a", "notified": {"task": 9}}))
        with mock.patch.object(mc, "spawn_watcher", return_value=4243):
            mc.bind(self.args(), rebind=True)
        state = json.loads(state_path.read_text())
        self.assertEqual(state["session_id"], "session-a")
        self.assertEqual(state["notified"], {})
        with mock.patch.object(mc, "binding_live", return_value=True):
            with self.assertRaises(mc.UserError):
                mc.bind(self.args("session-b"), rebind=False)
        self.assertEqual(json.loads(binding_path.read_text())["session_id"], "session-a")

    def test_release_then_bind_replaces_live_same_session_watcher(self):
        binding_path, heartbeat, _ = mc.binding_paths(self.chat, "codex")
        binding_path.parent.mkdir(parents=True)
        original = mc.binding_record(self.args(), 111)
        mc.atomic_write(binding_path, mc.json_bytes(original), 0o600)
        heartbeat.write_text("live\n", encoding="utf-8")
        with mock.patch.object(mc, "binding_live", return_value=True), mock.patch.object(mc, "spawn_watcher") as spawn:
            mc.bind(self.args(), rebind=True)
        spawn.assert_not_called()
        self.assertEqual(json.loads(binding_path.read_text())["pid"], 111)

        with mock.patch.object(mc, "watcher_pid_matches", return_value=False):
            mc.stop_binding(self.chat, "codex", "session-a", force=False)
        self.assertFalse(binding_path.exists())
        with mock.patch.object(mc, "spawn_watcher", return_value=222):
            mc.bind(self.args(), rebind=False)
        replacement = json.loads(binding_path.read_text())
        self.assertEqual(replacement["pid"], 222)
        self.assertEqual(replacement["session_id"], "session-a")

    def test_unrelated_session_end_does_not_release_binding(self):
        binding_path, heartbeat, _ = mc.binding_paths(self.chat, "codex")
        binding_path.parent.mkdir(parents=True)
        mc.atomic_write(binding_path, mc.json_bytes({"session_id": "owner", "pid": 0}), 0o600)
        payload = io.StringIO(json.dumps({"session_id": "other"}))
        with mock.patch.object(mc.sys, "stdin", payload), mock.patch.object(mc, "stop_binding") as stop:
            mc.hook(Args(chat_root=str(self.chat), agent="codex", event="session-end"))
        stop.assert_not_called()
        self.assertTrue(binding_path.exists())

    def test_release_clears_delivery_state(self):
        binding_path, heartbeat, _ = mc.binding_paths(self.chat, "claude")
        binding_path.parent.mkdir(parents=True)
        mc.atomic_write(binding_path, mc.json_bytes({"session_id": "s", "pid": 0}))
        for name in ("heartbeat", "monitor.inbox", "wake-challenge.json", "watch-state.json"):
            (binding_path.parent / name).write_text("state\n", encoding="utf-8")
        mc.stop_binding(self.chat, "claude", "s", force=False)
        for name in ("binding.json", "heartbeat", "monitor.inbox", "wake-challenge.json", "watch-state.json"):
            self.assertFalse((binding_path.parent / name).exists())

    def test_inert_session_reports_dead_binding(self):
        binding_path, _, _ = mc.binding_paths(self.chat, "codex")
        binding_path.parent.mkdir(parents=True)
        mc.atomic_write(
            binding_path,
            mc.json_bytes({
                "agent": "codex", "session_id": "dead-owner", "pid": 999999,
                "chat_root": str(self.chat), "wake_mode": "codex-queue",
            }),
        )
        output = io.StringIO()
        payload = io.StringIO(json.dumps({"session_id": "new-session"}))
        with mock.patch.object(mc.sys, "stdin", payload), contextlib.redirect_stdout(output):
            mc.hook(Args(chat_root=str(self.chat), agent="codex", event="session-start"))
        rendered = json.loads(output.getvalue())
        self.assertIn("explicit rebind", rendered["hookSpecificOutput"]["additionalContext"])

    def test_inert_session_reports_other_live_binding(self):
        binding_path, heartbeat, _ = mc.binding_paths(self.chat, "codex")
        binding_path.parent.mkdir(parents=True)
        mc.atomic_write(
            binding_path,
            mc.json_bytes({
                "agent": "codex", "session_id": "owner-session", "pid": 123,
                "chat_root": str(self.chat), "wake_mode": "codex-queue",
            }),
        )
        heartbeat.write_text("live\n", encoding="utf-8")
        output = io.StringIO()
        payload = io.StringIO(json.dumps({"session_id": "other-session"}))
        with mock.patch.object(mc.sys, "stdin", payload), mock.patch.object(mc, "binding_live", return_value=True), contextlib.redirect_stdout(output):
            mc.hook(Args(chat_root=str(self.chat), agent="codex", event="session-start"))
        rendered = json.loads(output.getvalue())
        context = rendered["hookSpecificOutput"]["additionalContext"]
        self.assertIn("another live session", context)
        self.assertIn("owner-session", context)

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
        stdout = io.StringIO()
        with mock.patch.object(mc, "binding_live", return_value=True), mock.patch.object(mc.secrets, "token_hex", return_value="nonce"), mock.patch.object(mc, "wake", return_value=True) as transport, contextlib.redirect_stdout(stdout):
            self.assertEqual(mc.probe_wake(args), 0)
            self.assertEqual(
                stdout.getvalue(),
                "wake probe sent; nonce is available only through the wake transport\n",
            )
            challenge_text = (binding_path.parent / "wake-challenge.json").read_text()
            self.assertNotIn('"nonce":', challenge_text)
            self.assertNotIn("nonce\"", challenge_text)
            self.assertIn("nonce nonce.", transport.call_args.args[2])
            state_path = binding_path.parent / "watch-state.json"
            mc.atomic_write(
                state_path,
                mc.json_bytes({
                    "session_id": "s", "notified": {"task": 3},
                    "attempts": {"task:task:3": {"count": 2, "next_at": 1}},
                    "failed": ["task:task:3"], "unverified": ["task:task:3"],
                    "stale": [],
                }),
            )
            with self.assertRaises(mc.UserError):
                mc.verify_wake(Args(chat_root=str(self.chat), agent="claude", session_id="s", nonce="wrong"))
            self.assertEqual(mc.verify_wake(Args(chat_root=str(self.chat), agent="claude", session_id="s", nonce="nonce")), 0)
            with self.assertRaises(mc.UserError):
                mc.verify_wake(Args(chat_root=str(self.chat), agent="claude", session_id="s", nonce="nonce"))
        verified = json.loads(binding_path.read_text())
        self.assertTrue(verified["wake_verified"])
        self.assertFalse((binding_path.parent / "wake-challenge.json").exists())
        reset = json.loads((binding_path.parent / "watch-state.json").read_text())
        self.assertEqual(reset["notified"], {})
        self.assertEqual(reset["attempts"], {})

    def test_wake_verification_rejects_expired_or_dead_challenge(self):
        binding_path, heartbeat, _ = mc.binding_paths(self.chat, "claude")
        binding_path.parent.mkdir(parents=True)
        binding = {
            "agent": "claude", "session_id": "s", "pid": 123,
            "chat_root": str(self.chat), "wake_mode": "monitor-file",
            "wake_verified": False,
        }
        mc.atomic_write(binding_path, mc.json_bytes(binding))
        heartbeat.write_text("live\n", encoding="utf-8")
        challenge = {
            "session_id": "s", "nonce_sha256": mc.sha256_bytes(b"nonce"),
            "expires_at": time.time() - 1,
        }
        mc.atomic_write(binding_path.parent / "wake-challenge.json", mc.json_bytes(challenge))
        with mock.patch.object(mc, "binding_live", return_value=True):
            with self.assertRaises(mc.UserError):
                mc.verify_wake(Args(chat_root=str(self.chat), agent="claude", session_id="s", nonce="nonce"))
        challenge["session_id"] = "another-session"
        challenge["expires_at"] = time.time() + 60
        mc.atomic_write(binding_path.parent / "wake-challenge.json", mc.json_bytes(challenge))
        with mock.patch.object(mc, "binding_live", return_value=True):
            with self.assertRaises(mc.UserError):
                mc.verify_wake(Args(chat_root=str(self.chat), agent="claude", session_id="s", nonce="nonce"))
        challenge["session_id"] = "s"
        challenge["expires_at"] = time.time() + 60
        mc.atomic_write(binding_path.parent / "wake-challenge.json", mc.json_bytes(challenge))
        with mock.patch.object(mc, "binding_live", return_value=False):
            with self.assertRaises(mc.UserError):
                mc.verify_wake(Args(chat_root=str(self.chat), agent="claude", session_id="s", nonce="nonce"))

    def test_subprocess_wake_timeout_is_failure(self):
        binding = {"session_id": "s", "wake_mode": "codex-queue"}
        with mock.patch.object(mc.subprocess, "run", side_effect=mc.subprocess.TimeoutExpired("codex", 10)):
            self.assertFalse(mc.wake(binding, self.chat, "message"))
        command_binding = {
            "session_id": "s", "wake_mode": "command",
            "wake_command": ["wake", "{message}"],
        }
        with mock.patch.object(mc.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(mc.wake(command_binding, self.chat, "message"))
        self.assertEqual(run.call_args.kwargs["timeout"], mc.WAKE_TIMEOUT_SECONDS)

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

    def test_watcher_identity_includes_exact_chat_root(self):
        command = (
            b"python3\0/tmp/multiagent_collab.py\0watch\0--chat-root\0/tmp/chat-one\0"
            b"--agent\0codex\0--session-id\0session\0"
        )
        with mock.patch.object(mc, "pid_alive", return_value=True), mock.patch.object(mc.Path, "exists", return_value=True), mock.patch.object(mc.Path, "read_bytes", return_value=command):
            self.assertTrue(mc.watcher_pid_matches(10, "codex", "session", "/tmp/chat-one"))
            self.assertFalse(mc.watcher_pid_matches(10, "codex", "session", "/tmp/chat-two"))
            self.assertFalse(mc.watcher_pid_matches(10, "codex", "sess", "/tmp/chat-one"))
            self.assertFalse(mc.watcher_pid_matches(10, "code", "session", "/tmp/chat-one"))
            self.assertFalse(mc.watcher_pid_matches(10, "codex", "session", "/tmp/chat"))


if __name__ == "__main__":
    unittest.main()
