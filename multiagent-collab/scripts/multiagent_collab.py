#!/usr/bin/env python3
"""Dependency-free runtime and installer for the multiagent-collab skill."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Iterable


SKILL_NAME = "multiagent-collab"
DEFAULT_CHAT_ROOT = "~/workspace/chat"
MANAGED_START = "<!-- multiagent-collab:start -->"
MANAGED_END = "<!-- multiagent-collab:end -->"
TASK_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{3}-[a-z0-9][a-z0-9-]*$")
AGENTS = ("codex", "claude")
WAKE_TIMEOUT_SECONDS = 10
WAKE_BACKOFF_SECONDS = (0, 5, 30)
WAKE_RECOVERY_INTERVAL_SECONDS = 300


class UserError(RuntimeError):
    pass


def expand(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temp, flags, mode or 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_text(path: Path, text: str, mode: int | None = None) -> None:
    atomic_write(path, text.encode("utf-8"), mode)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserError(f"invalid JSON at {path}: {exc}") from exc


def selected_agents(value: str) -> tuple[str, ...]:
    if value == "both":
        return AGENTS
    if value not in AGENTS:
        raise UserError(f"unknown agent: {value}")
    return (value,)


def validate_task_id(task_id: str) -> None:
    if not TASK_ID_RE.fullmatch(task_id):
        raise UserError(f"invalid task id: {task_id}")


def config_target(path: Path, follow_symlinks: bool) -> Path:
    has_symlink = path.is_symlink() or any(parent.is_symlink() for parent in path.parents)
    if not has_symlink:
        return path
    if not follow_symlinks:
        raise UserError(f"refusing config through a symlink without explicit approval: {path}")
    return path.resolve(strict=False)


def symlink_target(link: Path) -> Path:
    raw = Path(os.readlink(link))
    return expand(raw if raw.is_absolute() else link.parent / raw)


class FileOps:
    def __init__(self, *, dry_run: bool, chat_root: Path, follow_symlinks: bool):
        self.dry_run = dry_run
        self.chat_root = chat_root
        self.follow_symlinks = follow_symlinks
        self.actions: list[str] = []
        stamp = dt.datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z")
        self.backup_root = chat_root / "_backups" / stamp
        self.backups: list[dict[str, str]] = []
        self._backed_up: set[Path] = set()
        self.created_config: set[str] = set()

    def note(self, action: str) -> None:
        self.actions.append(action)

    def mkdir(self, path: Path) -> None:
        if path.is_dir():
            return
        self.note(f"mkdir {path}")
        if not self.dry_run:
            path.mkdir(parents=True, exist_ok=True)

    def backup(self, path: Path) -> None:
        if path in self._backed_up or not path.exists() or path.is_symlink():
            return
        self._backed_up.add(path)
        relative = Path(str(path).lstrip("/"))
        destination = self.backup_root / "files" / relative
        record = {
            "source": str(path),
            "backup": str(destination),
            "sha256": sha256_file(path),
        }
        self.backups.append(record)
        self.note(f"backup {path} -> {destination}")
        if not self.dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination, follow_symlinks=False)

    def write(self, path: Path, data: bytes, *, config: bool = False, mode: int | None = None) -> None:
        target = config_target(path, self.follow_symlinks) if config else path
        if target.exists() and not target.is_symlink() and target.read_bytes() == data:
            return
        if config:
            if not target.exists():
                self.created_config.add(str(target))
            self.backup(target)
        self.note(f"write {target}")
        if not self.dry_run:
            atomic_write(target, data, mode)

    def remove_file(self, path: Path, *, config: bool = False) -> None:
        target = config_target(path, self.follow_symlinks) if config else path
        if not target.exists():
            return
        if target.is_dir():
            raise UserError(f"refusing to remove directory as file: {target}")
        if config:
            self.backup(target)
        self.note(f"unlink {target}")
        if not self.dry_run:
            target.unlink()

    def symlink(self, target: Path, link: Path) -> None:
        if link.is_symlink() and symlink_target(link) == target:
            return
        if link.exists() or link.is_symlink():
            raise UserError(f"unmanaged path already exists: {link}")
        self.note(f"symlink {link} -> {target}")
        if not self.dry_run:
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, link, target_is_directory=True)

    def unlink_managed(self, target: Path, link: Path) -> None:
        if not link.exists() and not link.is_symlink():
            return
        if not link.is_symlink() or symlink_target(link) != target:
            raise UserError(f"refusing to remove unmanaged path: {link}")
        self.note(f"unlink {link}")
        if not self.dry_run:
            link.unlink()

    def finish(self) -> None:
        if not self.backups:
            return
        manifest = self.backup_root / "manifest.json"
        self.note(f"write {manifest}")
        if not self.dry_run:
            atomic_write(
                manifest,
                json_bytes({"backups": self.backups, "created_config": sorted(self.created_config)}),
                0o600,
            )


def managed_guidance(chat_root: Path) -> str:
    return (
        f"{MANAGED_START}\n"
        "When the user requests Codex-Claude paired work, or an automated baton "
        "notification assigns this agent, invoke $multiagent-collab.\n"
        f"Default shared chat root: {chat_root}\n"
        f"{MANAGED_END}"
    )


def put_managed_block(original: str, block: str) -> str:
    start = original.find(MANAGED_START)
    end = original.find(MANAGED_END)
    if (start < 0) != (end < 0):
        raise UserError("incomplete multiagent-collab managed block")
    if start >= 0:
        end += len(MANAGED_END)
        updated = original[:start] + block + original[end:]
    else:
        prefix = original.rstrip()
        updated = f"{prefix}\n\n{block}" if prefix else block
    return updated.rstrip() + "\n"


def remove_managed_block(original: str) -> str:
    start = original.find(MANAGED_START)
    end = original.find(MANAGED_END)
    if start < 0 and end < 0:
        return original
    if start < 0 or end < 0:
        raise UserError("incomplete multiagent-collab managed block")
    end += len(MANAGED_END)
    return (original[:start] + original[end:]).strip() + ("\n" if original[:start] + original[end:] else "")


def hook_command(skill_root: Path, chat_root: Path, agent: str, event: str) -> str:
    script = skill_root / "scripts" / "multiagent_collab.py"
    words = [
        "python3",
        str(script),
        "hook",
        "--chat-root",
        str(chat_root),
        "--agent",
        agent,
        "--event",
        event,
    ]
    return " ".join(shlex.quote(word) for word in words)


def hook_group(skill_root: Path, chat_root: Path, agent: str, event: str) -> dict[str, Any]:
    group: dict[str, Any] = {
        "hooks": [
            {
                "type": "command",
                "command": hook_command(skill_root, chat_root, agent, event),
                "timeout": 5 if event == "session-start" else 3,
            }
        ]
    }
    if event == "session-start":
        group["matcher"] = "startup|resume"
    return group


def is_managed_hook(group: Any, agent: str) -> bool:
    if not isinstance(group, dict):
        return False
    for handler in group.get("hooks", []):
        command = handler.get("command", "") if isinstance(handler, dict) else ""
        if "multiagent_collab.py" in command and f"--agent {agent}" in command:
            return True
    return False


def merge_hooks(data: dict[str, Any], skill_root: Path, chat_root: Path, agent: str) -> dict[str, Any]:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise UserError("hooks must be a JSON object")
    for event_name, event_arg in (("SessionStart", "session-start"), ("SessionEnd", "session-end")):
        groups = hooks.setdefault(event_name, [])
        if not isinstance(groups, list):
            raise UserError(f"hooks.{event_name} must be a list")
        desired = hook_group(skill_root, chat_root, agent, event_arg)
        managed = [index for index, group in enumerate(groups) if is_managed_hook(group, agent)]
        if len(managed) > 1:
            raise UserError(f"multiple managed {event_name} hook groups")
        if managed:
            groups[managed[0]] = desired
        else:
            groups.append(desired)
    return data


def remove_hooks(data: dict[str, Any], agent: str) -> dict[str, Any]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event_name in ("SessionStart", "SessionEnd"):
        groups = hooks.get(event_name)
        if isinstance(groups, list):
            hooks[event_name] = [group for group in groups if not is_managed_hook(group, agent)]
            if not hooks[event_name]:
                del hooks[event_name]
    return data


def protocol_version(data: bytes) -> str:
    match = re.search(rb"^Version:\s*([^\r\n]+)", data, re.MULTILINE)
    return match.group(1).decode("utf-8").strip() if match else "unknown"


def install_protocol(ops: FileOps, asset: Path, chat_root: Path, expected: str | None) -> None:
    source = asset.read_bytes()
    destination = chat_root / "PROTOCOL.md"
    if destination.is_symlink():
        raise UserError(f"refusing symlinked installed protocol: {destination}")
    if not destination.exists():
        ops.write(destination, source)
        return
    current = destination.read_bytes()
    if current == source:
        return
    current_hash = sha256_bytes(current)
    if expected != current_hash:
        raise UserError(
            f"protocol drift at {destination}: current {current_hash}; "
            "pass --upgrade-protocol-from with that exact hash after approval"
        )
    prior = chat_root / "_protocols" / f"{protocol_version(current)}-{current_hash}.md"
    ops.write(prior, current)
    ops.backup(destination)
    ops.write(destination, source)


def preflight_setup(
    home: Path, chat_root: Path, skill_root: Path, asset: Path,
    agents: tuple[str, ...], follow_symlinks: bool, expected_protocol: str | None,
) -> None:
    destination = chat_root / "PROTOCOL.md"
    if destination.is_symlink():
        raise UserError(f"refusing symlinked installed protocol: {destination}")
    if destination.exists() and destination.read_bytes() != asset.read_bytes():
        current_hash = sha256_file(destination)
        if expected_protocol != current_hash:
            raise UserError(f"protocol drift at {destination}: current {current_hash}")
    for agent in agents:
        link = home / f".{agent}" / "skills" / SKILL_NAME
        if (link.exists() or link.is_symlink()) and not (link.is_symlink() and symlink_target(link) == skill_root):
            raise UserError(f"unmanaged path already exists: {link}")
        if agent == "codex":
            agents_md = home / ".codex" / "AGENTS.md"
            agents_target = config_target(agents_md, follow_symlinks)
            original = agents_target.read_text(encoding="utf-8") if agents_target.exists() else ""
            put_managed_block(original, managed_guidance(chat_root))
            hooks_path = home / ".codex" / "hooks.json"
            default_hooks: dict[str, Any] = {"description": "User-level Codex hooks.", "hooks": {}}
        else:
            hooks_path = home / ".claude" / "settings.json"
            default_hooks = {}
        hooks_target = config_target(hooks_path, follow_symlinks)
        merge_hooks(load_json(hooks_target, default_hooks), skill_root, chat_root, agent)


def setup(args: argparse.Namespace) -> int:
    home = expand(args.home)
    chat_root = expand(args.chat_root)
    skill_root = expand(Path(__file__).parent.parent)
    asset = skill_root / "assets" / "PROTOCOL.md"
    if not asset.is_file():
        raise UserError(f"missing packaged protocol: {asset}")
    agents = selected_agents(args.agent)
    preflight_setup(
        home, chat_root, skill_root, asset, agents,
        args.follow_config_symlinks, args.upgrade_protocol_from,
    )
    ops = FileOps(dry_run=args.dry_run, chat_root=chat_root, follow_symlinks=args.follow_config_symlinks)
    for directory in (chat_root, chat_root / "_archive", chat_root / "_runtime"):
        ops.mkdir(directory)
    install_protocol(ops, asset, chat_root, args.upgrade_protocol_from)
    index = chat_root / "_archive" / "INDEX.md"
    if not index.exists():
        ops.write(index, b"# Archived tasks\n")

    for agent in agents:
        link = home / f".{agent}" / "skills" / SKILL_NAME
        ops.symlink(skill_root, link)
        if agent == "codex":
            agents_md = home / ".codex" / "AGENTS.md"
            agents_target = config_target(agents_md, args.follow_config_symlinks)
            original = agents_target.read_text(encoding="utf-8") if agents_target.exists() else ""
            updated = put_managed_block(original, managed_guidance(chat_root))
            ops.write(agents_md, updated.encode("utf-8"), config=True)
            hooks_path = home / ".codex" / "hooks.json"
        else:
            hooks_path = home / ".claude" / "settings.json"
        hooks_target = config_target(hooks_path, args.follow_config_symlinks)
        default_hooks = {"description": "User-level Codex hooks.", "hooks": {}} if agent == "codex" else {}
        hooks_data = load_json(hooks_target, default_hooks)
        merged = merge_hooks(hooks_data, skill_root, chat_root, agent)
        ops.write(hooks_path, json_bytes(merged), config=True)

    metadata_path = chat_root / "_runtime" / "install.json"
    metadata = load_json(metadata_path, {})
    installed = set(metadata.get("agents", []))
    installed.update(agents)
    created_config = set(metadata.get("created_config", []))
    created_config.update(ops.created_config)
    metadata = {
        "skill_root": str(skill_root),
        "chat_root": str(chat_root),
        "protocol_version": protocol_version(asset.read_bytes()),
        "protocol_sha256": sha256_file(asset),
        "agents": sorted(installed),
        "created_config": sorted(created_config),
    }
    ops.write(metadata_path, json_bytes(metadata), mode=0o600)
    ops.finish()
    for action in ops.actions:
        print(action)
    return 0


def uninstall(args: argparse.Namespace) -> int:
    home = expand(args.home)
    chat_root = expand(args.chat_root)
    skill_root = expand(Path(__file__).parent.parent)
    agents = selected_agents(args.agent)
    ops = FileOps(dry_run=args.dry_run, chat_root=chat_root, follow_symlinks=args.follow_config_symlinks)
    metadata_path = chat_root / "_runtime" / "install.json"
    metadata = load_json(metadata_path, {}) if metadata_path.exists() else {}
    created_config = set(metadata.get("created_config", []))
    for agent in agents:
        ops.unlink_managed(skill_root, home / f".{agent}" / "skills" / SKILL_NAME)
        if agent == "codex":
            agents_md = home / ".codex" / "AGENTS.md"
            agents_target = config_target(agents_md, args.follow_config_symlinks)
            if agents_target.exists():
                updated = remove_managed_block(agents_target.read_text(encoding="utf-8"))
                if str(agents_target) in created_config and not updated.strip():
                    ops.remove_file(agents_md, config=True)
                else:
                    ops.write(agents_md, updated.encode("utf-8"), config=True)
            hooks_path = home / ".codex" / "hooks.json"
        else:
            hooks_path = home / ".claude" / "settings.json"
        if hooks_path.exists():
            hooks_target = config_target(hooks_path, args.follow_config_symlinks)
            data = remove_hooks(load_json(hooks_target, {}), agent)
            empty_managed = data in ({}, {"hooks": {}}, {"description": "User-level Codex hooks.", "hooks": {}})
            if str(hooks_target) in created_config and empty_managed:
                ops.remove_file(hooks_path, config=True)
            else:
                ops.write(hooks_path, json_bytes(data), config=True)
    if metadata_path.exists():
        metadata["agents"] = [agent for agent in metadata.get("agents", []) if agent not in agents]
        removed_prefixes = tuple(str(home / f".{agent}") for agent in agents)
        metadata["created_config"] = [path for path in metadata.get("created_config", []) if not path.startswith(removed_prefixes)]
        ops.write(metadata_path, json_bytes(metadata), mode=0o600)
    ops.finish()
    for action in ops.actions:
        print(action)
    return 0


def parse_baton(path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            raise UserError(f"invalid baton line in {path}: {raw!r}")
        key, value = raw.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in values:
            raise UserError(f"duplicate baton field: {key}")
        if key in {"seq", "round"}:
            try:
                values[key] = int(value)
            except ValueError as exc:
                raise UserError(f"invalid integer for {key}: {value!r}") from exc
        elif key in {"owner_ready", "reviewer_ready"}:
            if value not in {"true", "false"}:
                raise UserError(f"invalid boolean for {key}")
            values[key] = value == "true"
        else:
            values[key] = value
    required = {"task", "seq", "holder", "status", "round", "revision", "verdict", "owner_ready", "reviewer_ready", "ask", "updated_at"}
    missing = required - values.keys()
    if missing:
        raise UserError(f"baton missing fields: {sorted(missing)}")
    validate_task_id(str(values["task"]))
    if values["seq"] < 0 or values["round"] < 0:
        raise UserError("baton sequence and round must be non-negative")
    if values["holder"] not in {*AGENTS, "operator", "none"}:
        raise UserError(f"invalid baton holder: {values['holder']}")
    if values["status"] not in {"active", "blocked", "done"}:
        raise UserError(f"invalid baton status: {values['status']}")
    if values["verdict"] not in {"PASS", "CHANGES_REQUIRED", "BLOCKED", "none"}:
        raise UserError(f"invalid baton verdict: {values['verdict']}")
    pinned = {"owner", "reviewer", "task_sha256"}
    present = pinned & values.keys()
    if present and present != pinned:
        raise UserError(f"baton has incomplete contract pins: {sorted(present)}")
    if present:
        if values["owner"] not in AGENTS or values["reviewer"] not in AGENTS:
            raise UserError("invalid pinned task roles")
        if values["owner"] == values["reviewer"]:
            raise UserError("pinned owner and reviewer must differ")
        task_hash = str(values["task_sha256"])
        if task_hash != "pending" and not re.fullmatch(r"[0-9a-f]{64}", task_hash):
            raise UserError("invalid pinned TASK.md hash")
    return values


def baton_scalar(value: Any, key: str) -> str:
    raw = str(value)
    separators = {"\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"}
    if any(character in separators or ord(character) < 32 or 127 <= ord(character) <= 159 for character in raw):
        raise UserError(f"control or line-separator character in baton field {key}")
    return raw.strip()


def dump_baton(values: dict[str, Any]) -> str:
    order = ["task"]
    pinned = {"owner", "reviewer", "task_sha256"}
    present = pinned & values.keys()
    if present and present != pinned:
        raise UserError("cannot render incomplete contract pins")
    if present:
        order.extend(("owner", "reviewer", "task_sha256"))
    order.extend(("seq", "holder", "status", "round", "revision", "verdict", "owner_ready", "reviewer_ready", "ask", "updated_at"))
    lines = []
    for key in order:
        value = values[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = baton_scalar(value, key)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines) + "\n"


def task_path(chat_root: Path, task_id: str) -> Path:
    validate_task_id(task_id)
    path = chat_root / task_id
    if path.parent != chat_root:
        raise UserError("task escapes chat root")
    if path.is_symlink():
        raise UserError(f"refusing symlinked task directory: {path}")
    return path


def task_init(args: argparse.Namespace) -> int:
    chat_root = expand(args.chat_root)
    target = task_path(chat_root, args.task_id)
    if target.exists():
        raise UserError(f"task already exists: {target}")
    task_source = expand(args.task_file)
    task_data = task_source.read_bytes()
    if task_owner(task_source) != args.owner:
        raise UserError(f"task contract Owner must match --owner {args.owner}")
    reviewer = "claude" if args.owner == "codex" else "codex"
    target.mkdir(parents=True)
    try:
        atomic_write(target / "TASK.md", task_data)
        log = (
            "# Task Log\n\n"
            f"## Seq 0 — {args.owner} to {reviewer}\n\n"
            f"Time: {now_iso()}\n\n"
            "Result: task contract drafted; implementation not started.\n\n"
            "Ask: adversarially review the contract and return changes or acceptance.\n"
        )
        atomic_text(target / "LOG.md", log)
        baton = {
            "task": args.task_id,
            "owner": args.owner,
            "reviewer": reviewer,
            "task_sha256": "pending",
            "seq": 1,
            "holder": reviewer,
            "status": "active",
            "round": 0,
            "revision": f"sha256:{sha256_bytes(task_data)}",
            "verdict": "none",
            "owner_ready": False,
            "reviewer_ready": False,
            "ask": "Review the task contract; return changes or acceptance.",
            "updated_at": now_iso(),
        }
        atomic_text(target / "BATON.md", dump_baton(baton))
        (target / "reviews").mkdir()
        (target / "artifacts").mkdir()
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    print(target)
    return 0


def bool_choice(value: str, current: bool) -> bool:
    if value == "keep":
        return current
    return value == "true"


def contract_roles(
    target: Path, baton: dict[str, Any], *, allow_task_hash_change: bool = False,
    allow_unpinned: bool = False,
) -> tuple[str, str]:
    """Return pinned roles and reject TASK.md drift after approval.

    An unpinned legacy baton can be migrated only by an operator approve/amend
    relay carrying an exact current TASK.md hash.
    """
    task_md = target / "TASK.md"
    current_owner = task_owner(task_md)
    if current_owner not in AGENTS:
        raise UserError("TASK.md must name Owner: Codex or Owner: Claude")
    pinned = {"owner", "reviewer", "task_sha256"}
    present = pinned & baton.keys()
    if not present:
        if not allow_unpinned:
            raise UserError("task contract is unpinned; operator approve or amend is required")
        baton["owner"] = current_owner
        baton["reviewer"] = "claude" if current_owner == "codex" else "codex"
        baton["task_sha256"] = "pending"
    elif present != pinned:
        raise UserError("baton has incomplete contract pins")
    owner = str(baton["owner"])
    reviewer = str(baton["reviewer"])
    if owner not in AGENTS or reviewer not in AGENTS or owner == reviewer:
        raise UserError("invalid pinned task roles")
    if current_owner != owner:
        raise UserError("TASK.md owner differs from the pinned owner")
    pinned_hash = str(baton["task_sha256"])
    current_hash = sha256_file(task_md)
    if pinned_hash != "pending" and current_hash != pinned_hash and not allow_task_hash_change:
        raise UserError("TASK.md differs from the operator-approved contract hash")
    return owner, reviewer


def acquire_baton_lock(lock: Path, agent: str, break_stale: bool) -> str | None:
    broken: str | None = None
    try:
        lock.mkdir()
    except FileExistsError as exc:
        age = time.time() - lock.stat().st_mtime
        if not break_stale or age <= 300:
            raise UserError(f"baton locked ({age:.0f}s old): {lock}") from exc
        prior_holder = (lock / "holder").read_text(encoding="utf-8").strip() if (lock / "holder").exists() else "unknown"
        broken = f"Broke stale baton lock held by {prior_holder}, age {age:.0f}s."
        shutil.rmtree(lock)
        lock.mkdir()
    atomic_text(lock / "holder", agent + "\n")
    atomic_text(lock / "acquired_at", now_iso() + "\n")
    return broken


def baton_pass(args: argparse.Namespace) -> int:
    chat_root = expand(args.chat_root)
    target = task_path(chat_root, args.task_id)
    baton_path = target / "BATON.md"
    log_path = target / "LOG.md"
    lock = target / ".baton.lock"
    broken = acquire_baton_lock(lock, args.agent, getattr(args, "break_stale_lock", False))
    try:
        baton = parse_baton(baton_path)
        if baton["seq"] != args.expected_seq:
            raise UserError(f"sequence changed: expected {args.expected_seq}, found {baton['seq']}")
        if baton["holder"] != args.agent:
            raise UserError(f"baton held by {baton['holder']}, not {args.agent}")
        owner, reviewer = contract_roles(target, baton)
        owner_ready_arg = getattr(args, "owner_ready", "keep")
        reviewer_ready_arg = getattr(args, "reviewer_ready", "keep")
        verdict_arg = getattr(args, "verdict", None)
        operator_reason = getattr(args, "operator_reason", None)
        if getattr(args, "ministerial", False):
            raise UserError("use operator-relay for operator-directed baton changes")
        if args.agent == owner and reviewer_ready_arg != "keep":
            raise UserError("owner cannot set reviewer readiness")
        if args.agent == reviewer and owner_ready_arg != "keep":
            raise UserError("reviewer cannot set owner readiness")
        if verdict_arg not in {None, "none"} and args.agent != reviewer:
            raise UserError("only reviewer may set a review verdict")
        if baton["status"] == "done":
            raise UserError("a closed task cannot leave the owner's cleanup turn")
        if baton["status"] == "blocked" and args.status == "active":
            raise UserError("only an operator relay may reactivate a blocked task")
        if args.status == "done" or args.next_holder == "none":
            raise UserError("only operator CLOSE and archive may complete a task")
        if args.next_holder == "operator" and operator_reason not in {"contract", "blocked", "signoff"}:
            raise UserError("pass to operator requires --operator-reason")
        old_revision = baton["revision"]
        if args.revision is not None:
            baton["revision"] = args.revision
        if baton["revision"] != old_revision:
            baton["owner_ready"] = False
            baton["reviewer_ready"] = False
            baton["verdict"] = "none"
        if verdict_arg in {"CHANGES_REQUIRED", "BLOCKED"}:
            baton["owner_ready"] = False
            baton["reviewer_ready"] = False
        baton.update(
            seq=baton["seq"] + 1,
            holder=args.next_holder,
            status=args.status or baton["status"],
            round=args.round if args.round is not None else baton["round"],
            verdict=verdict_arg or baton["verdict"],
            ask=args.ask,
            updated_at=now_iso(),
        )
        baton["owner_ready"] = bool_choice(owner_ready_arg, baton["owner_ready"])
        baton["reviewer_ready"] = bool_choice(reviewer_ready_arg, baton["reviewer_ready"])
        if operator_reason == "signoff":
            if args.agent != owner:
                raise UserError("only owner may present signoff")
            if baton["status"] != "active":
                raise UserError("signoff requires an active task")
            if baton["task_sha256"] == "pending":
                raise UserError("signoff requires an operator-approved TASK.md hash")
            if baton["verdict"] != "PASS" or not baton["owner_ready"] or not baton["reviewer_ready"]:
                raise UserError("signoff requires PASS and both readiness flags")
        if args.next_holder == "operator":
            baton["ask"] = f"[{operator_reason}] {args.ask}"
        baton_text = dump_baton(baton)
        turn = expand(args.log_file).read_text(encoding="utf-8").rstrip()
        existing = log_path.read_text(encoding="utf-8").rstrip()
        reason = f" ({operator_reason})" if args.next_holder == "operator" else ""
        heading = f"## Seq {baton['seq'] - 1} — {args.agent} to {args.next_holder}{reason}"
        if heading in existing:
            turn = f"Supersedes an incomplete prior LOG entry for this sequence.\n\n{turn}"
        if broken:
            turn = f"{broken}\n\n{turn}"
        atomic_text(log_path, f"{existing}\n\n{heading}\n\n{turn}\n")
        atomic_text(baton_path, baton_text)
    finally:
        shutil.rmtree(lock, ignore_errors=True)
    print(f"{args.task_id}: seq {baton['seq']} holder {baton['holder']}")
    return 0


def signoff(args: argparse.Namespace) -> int:
    args.next_holder = "operator"
    args.status = None
    args.round = None
    args.revision = None
    args.verdict = None
    args.owner_ready = "keep"
    args.reviewer_ready = "keep"
    args.ministerial = False
    args.operator_reason = "signoff"
    return baton_pass(args)


def operator_relay(args: argparse.Namespace) -> int:
    chat_root = expand(args.chat_root)
    target = task_path(chat_root, args.task_id)
    baton_path = target / "BATON.md"
    log_path = target / "LOG.md"
    lock = target / ".baton.lock"
    acquire_baton_lock(lock, f"operator-via-{args.agent}", args.break_stale_lock)
    try:
        baton = parse_baton(baton_path)
        if baton["seq"] != args.expected_seq:
            raise UserError(f"sequence changed: expected {args.expected_seq}, found {baton['seq']}")
        if args.action != "stop" and baton["holder"] != "operator":
            raise UserError(f"operator relay {args.action} requires holder operator")
        operator_data = expand(args.log_file).read_bytes()
        try:
            operator_words = operator_data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UserError("operator quote must be valid UTF-8") from exc
        if not operator_words.strip():
            raise UserError("operator relay requires a non-empty verbatim operator quote")
        task_sha256 = getattr(args, "task_sha256", None)
        if args.action in {"approve", "amend"}:
            if not isinstance(task_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", task_sha256):
                raise UserError(f"operator {args.action} requires --task-sha256")
            if task_sha256 != sha256_file(target / "TASK.md"):
                raise UserError("TASK.md changed after the hash presented to the operator")
        elif task_sha256 is not None:
            raise UserError("--task-sha256 is valid only for operator approve or amend")
        owner = None
        if args.action != "stop":
            owner, _ = contract_roles(
                target, baton,
                allow_task_hash_change=args.action == "amend",
                allow_unpinned=args.action in {"approve", "amend"},
            )
        if args.action == "stop":
            if args.next_holder != "operator":
                raise UserError("STOP must leave baton with operator")
            baton["status"] = "blocked"
            baton["verdict"] = "BLOCKED"
            baton["owner_ready"] = False
            baton["reviewer_ready"] = False
        elif args.action == "close":
            if owner not in AGENTS or args.next_holder != owner:
                raise UserError("CLOSE must give the cleanup turn to the task owner")
            if baton["task_sha256"] == "pending":
                raise UserError("CLOSE requires an operator-approved TASK.md hash")
            if baton["verdict"] != "PASS" or not baton["owner_ready"] or not baton["reviewer_ready"]:
                raise UserError("CLOSE requires PASS and both readiness flags")
            baton["status"] = "done"
        elif args.action == "approve":
            if owner not in AGENTS or args.next_holder != owner:
                raise UserError("approval must return baton to the task owner")
            baton["status"] = "active"
            baton["task_sha256"] = task_sha256
            baton["verdict"] = "none"
            baton["owner_ready"] = False
            baton["reviewer_ready"] = False
        elif args.action in {"amend", "ruling"}:
            if args.next_holder not in AGENTS:
                raise UserError(f"{args.action} must assign an agent")
            baton["status"] = "active"
            if args.action == "amend":
                baton["task_sha256"] = task_sha256
            baton["verdict"] = "none"
            baton["owner_ready"] = False
            baton["reviewer_ready"] = False
        else:
            raise UserError(f"unsupported operator relay action: {args.action}")
        baton["seq"] += 1
        baton["holder"] = args.next_holder
        baton["ask"] = args.ask
        baton["updated_at"] = now_iso()
        baton_text = dump_baton(baton)
        existing = log_path.read_text(encoding="utf-8").rstrip()
        approved_hash = f" task_sha256={task_sha256}" if task_sha256 is not None else ""
        heading = (
            f"## Seq {baton['seq'] - 1} — operator {args.action} via {args.agent} "
            f"to {args.next_holder}{approved_hash}"
        )
        entry = f"{existing}\n\n{heading}\n\n".encode("utf-8") + operator_data
        if not entry.endswith(b"\n"):
            entry += b"\n"
        atomic_write(log_path, entry)
        atomic_text(baton_path, baton_text)
    finally:
        shutil.rmtree(lock, ignore_errors=True)
    print(f"{args.task_id}: seq {baton['seq']} holder {baton['holder']} action {args.action}")
    return 0


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def binding_paths(chat_root: Path, agent: str) -> tuple[Path, Path, Path]:
    runtime = chat_root / "_runtime" / agent
    return runtime / "binding.json", runtime / "heartbeat", runtime / "watch.log"


def binding_live(binding: dict[str, Any], heartbeat: Path, max_age: float = 15.0) -> bool:
    if not watcher_pid_matches(
        int(binding.get("pid", 0)),
        str(binding.get("agent", "")),
        str(binding.get("session_id", "")),
        str(binding.get("chat_root", "")),
    ) or not heartbeat.exists():
        return False
    return time.time() - heartbeat.stat().st_mtime <= max_age


def watcher_pid_matches(pid: int, agent: str, session_id: str, chat_root: str = "") -> bool:
    if not pid_alive(pid):
        return False
    command_path = Path("/proc") / str(pid) / "cmdline"
    if not command_path.exists():
        return False
    try:
        command = [
            item.decode("utf-8", "replace")
            for item in command_path.read_bytes().split(b"\0")
            if item
        ]
    except OSError:
        return False

    def exact_option(name: str, expected: str) -> bool:
        return any(
            item == name and index + 1 < len(command) and command[index + 1] == expected
            for index, item in enumerate(command)
        )

    return (
        any(Path(item).name == "multiagent_collab.py" for item in command)
        and "watch" in command
        and exact_option("--agent", agent)
        and exact_option("--session-id", session_id)
        and (not chat_root or exact_option("--chat-root", str(expand(chat_root))))
    )


def stop_binding(chat_root: Path, agent: str, session_id: str | None, *, force: bool) -> None:
    binding_path, heartbeat, _ = binding_paths(chat_root, agent)
    if not binding_path.exists():
        return
    binding = load_json(binding_path, {})
    if not force and binding.get("session_id") != session_id:
        raise UserError(f"binding owned by session {binding.get('session_id')}")
    pid = int(binding.get("pid", 0))
    if watcher_pid_matches(
        pid,
        agent,
        str(binding.get("session_id", "")),
        str(binding.get("chat_root", "")),
    ):
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not pid_alive(pid):
                break
            time.sleep(0.05)
    binding_path.unlink(missing_ok=True)
    heartbeat.unlink(missing_ok=True)
    (binding_path.parent / "wake-challenge.json").unlink(missing_ok=True)
    (binding_path.parent / "monitor.inbox").unlink(missing_ok=True)
    (binding_path.parent / "watch-state.json").unlink(missing_ok=True)


def binding_record(args: argparse.Namespace, pid: int) -> dict[str, Any]:
    command = json.loads(args.wake_command_json) if args.wake_command_json else None
    if command is not None and (not isinstance(command, list) or not all(isinstance(item, str) for item in command)):
        raise UserError("--wake-command-json must be a JSON string array")
    return {
        "agent": args.agent,
        "session_id": args.session_id,
        "pid": pid,
        "project": str(expand(args.project)),
        "chat_root": str(expand(args.chat_root)),
        "created_at": now_iso(),
        "wake_mode": args.wake_mode or ("codex-queue" if args.agent == "codex" else "monitor-file"),
        "wake_command": command,
        "wake_verified": False,
    }


def spawn_watcher(chat_root: Path, binding: dict[str, Any]) -> int:
    _, _, log_path = binding_paths(chat_root, binding["agent"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "watch",
        "--chat-root",
        str(chat_root),
        "--agent",
        binding["agent"],
        "--session-id",
        binding["session_id"],
    ]
    with log_path.open("ab") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    return process.pid


def bind(args: argparse.Namespace, *, rebind: bool) -> int:
    chat_root = expand(args.chat_root)
    binding_path, heartbeat, _ = binding_paths(chat_root, args.agent)
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    lock = binding_path.parent / ".binding.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise UserError(f"binding operation already active: {lock}") from exc
    try:
        if binding_path.exists():
            current = load_json(binding_path, {})
            if current.get("session_id") == args.session_id and binding_live(current, heartbeat):
                print("already bound")
                return 0
            if not rebind:
                state = "live" if binding_live(current, heartbeat) else "dead"
                raise UserError(f"{args.agent} binding is {state}; explicit rebind required")
            stop_binding(chat_root, args.agent, None, force=True)
        pending = binding_record(args, 0)
        fresh_state = {"session_id": args.session_id, "notified": {}, "attempts": {}, "failed": [], "unverified": [], "stale": []}
        atomic_write(binding_path.parent / "watch-state.json", json_bytes(fresh_state), 0o600)
        atomic_write(binding_path, json_bytes(pending), 0o600)
        pid = spawn_watcher(chat_root, pending)
        pending["pid"] = pid
        atomic_write(binding_path, json_bytes(pending), 0o600)
        print(f"bound {args.agent} session {args.session_id} watcher pid {pid}")
        if pending["wake_mode"] == "monitor-file":
            print(f"arm a persistent monitor on {binding_path.parent / 'monitor.inbox'}, then run probe-wake")
    finally:
        shutil.rmtree(lock, ignore_errors=True)
    return 0


def wake(binding: dict[str, Any], runtime: Path, message: str) -> bool:
    mode = binding.get("wake_mode")
    if mode == "codex-queue":
        command = ["codex", "queue", "--thread", binding["session_id"], "--message", message]
        try:
            result = subprocess.run(
                command, check=False, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=WAKE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
    if mode == "command":
        template = binding.get("wake_command")
        if not isinstance(template, list):
            return False
        command = [part.replace("{message}", message).replace("{session_id}", binding["session_id"]) for part in template]
        try:
            return subprocess.run(command, check=False, timeout=WAKE_TIMEOUT_SECONDS).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    if mode == "monitor-file":
        inbox = runtime / "monitor.inbox"
        with inbox.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"time": now_iso(), "message": message}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True
    return False


def task_owner(task_md: Path) -> str | None:
    match = re.search(
        r"^\s*(?:\*\*)?Owner:(?:\*\*)?\s*(?:\*\*)?(Codex|Claude)(?:\*\*)?\s*$",
        task_md.read_text(encoding="utf-8"),
        re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


def append_alert(runtime: Path, message: str) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "alerts.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{now_iso()} {message}\n")


def attempt_wake(
    binding: dict[str, Any], runtime: Path, state: dict[str, Any],
    key: str, message: str,
) -> bool:
    attempts = state.setdefault("attempts", {})
    record = attempts.setdefault(key, {"count": 0, "next_at": 0.0})
    if time.time() < record["next_at"]:
        return False
    record["count"] += 1
    if not binding.get("wake_verified"):
        succeeded = False
    else:
        recovery = "Previous wake attempts failed; transport has recovered. " if key in state.get("failed", []) else ""
        succeeded = wake(binding, runtime, recovery + message)
    if succeeded:
        attempts.pop(key, None)
        return True
    if record["count"] >= len(WAKE_BACKOFF_SECONDS):
        failed = state.setdefault("failed", [])
        if key not in failed:
            failed.append(key)
            append_alert(runtime, f"wake failed after {record['count']} attempts: {key}")
        record["count"] = 0
        record["next_at"] = time.time() + WAKE_RECOVERY_INTERVAL_SECONDS
    else:
        record["next_at"] = time.time() + WAKE_BACKOFF_SECONDS[record["count"]]
    return False


def scan_task(
    chat_root: Path, target: Path, binding: dict[str, Any], state: dict[str, Any]
) -> bool:
    agent = binding["agent"]
    runtime = chat_root / "_runtime" / agent
    baton_path = target / "BATON.md"
    if target.is_symlink():
        raise UserError(f"refusing symlinked task directory: {target}")
    if not baton_path.is_file():
        return False
    baton = parse_baton(baton_path)
    owner, _ = contract_roles(target, baton)
    key = target.name
    changed = False
    try:
        updated = dt.datetime.fromisoformat(str(baton["updated_at"]))
        if updated.utcoffset() is None:
            raise UserError("baton updated_at must include an offset")
        age = (dt.datetime.now().astimezone() - updated).total_seconds()
    except (ValueError, TypeError) as exc:
        raise UserError(f"invalid baton updated_at: {baton['updated_at']!r}") from exc
    if baton["holder"] == agent and int(state.get("notified", {}).get(key, -1)) < baton["seq"]:
        message = (
            f"Follow the multiagent-collab skill. Baton seq {baton['seq']} for task {target.name} "
            f"is assigned to {agent}. Read {baton_path}, {target / 'TASK.md'}, and the latest "
            f"relevant entry in {target / 'LOG.md'}. Ask: {baton['ask']}"
        )
        attempt_key = f"task:{key}:{baton['seq']}"
        if not binding.get("wake_verified"):
            unverified = state.setdefault("unverified", [])
            if attempt_key not in unverified:
                unverified.append(attempt_key)
                append_alert(runtime, f"wake path unverified; task not delivered: {attempt_key}")
                changed = True
        else:
            before = json.dumps(state, sort_keys=True)
            if attempt_wake(binding, runtime, state, attempt_key, message):
                state.setdefault("notified", {})[key] = baton["seq"]
                if attempt_key in state.get("failed", []):
                    state["failed"].remove(attempt_key)
            changed = before != json.dumps(state, sort_keys=True)
    stale_key = f"{key}:{baton['seq']}"
    should_alert = baton["holder"] in AGENTS and baton["holder"] != agent
    if baton["holder"] == "operator":
        should_alert = owner == agent
        if not should_alert and owner in AGENTS:
            owner_binding, owner_heartbeat, _ = binding_paths(chat_root, owner)
            other = load_json(owner_binding, {}) if owner_binding.exists() else {}
            should_alert = not binding_live(other, owner_heartbeat)
    if age >= 3600 and should_alert and stale_key not in state.get("stale", []):
        alert = f"multiagent-collab task {key} baton seq {baton['seq']} is stale; notify the operator."
        attempt_key = f"stale:{stale_key}"
        before = json.dumps(state, sort_keys=True)
        if attempt_wake(binding, runtime, state, attempt_key, alert):
            state.setdefault("stale", []).append(stale_key)
        changed = changed or before != json.dumps(state, sort_keys=True)
    return changed


def scan_once(chat_root: Path, binding: dict[str, Any], state: dict[str, Any]) -> bool:
    agent = binding["agent"]
    runtime = chat_root / "_runtime" / agent
    changed = False
    if state.get("session_id") != binding.get("session_id"):
        state.clear()
        state.update({"session_id": binding.get("session_id"), "notified": {}, "attempts": {}, "failed": [], "unverified": [], "stale": []})
        changed = True
    for target in sorted(chat_root.iterdir() if chat_root.exists() else []):
        if not target.is_dir() or target.name.startswith("_") or not TASK_ID_RE.fullmatch(target.name):
            continue
        try:
            changed = scan_task(chat_root, target, binding, state) or changed
        except Exception as exc:
            append_alert(runtime, f"ignored malformed task {target.name}: {type(exc).__name__}: {exc}")
    return changed


def watch(args: argparse.Namespace) -> int:
    chat_root = expand(args.chat_root)
    binding_path, heartbeat, _ = binding_paths(chat_root, args.agent)
    runtime = binding_path.parent
    state_path = runtime / "watch-state.json"
    stopping = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        binding = load_json(binding_path, {})
        if binding.get("session_id") != args.session_id:
            return 0
        registered_pid = int(binding.get("pid", 0))
        if registered_pid == 0:
            binding["pid"] = os.getpid()
            atomic_write(binding_path, json_bytes(binding), 0o600)
        elif registered_pid != os.getpid():
            return 0
        atomic_text(heartbeat, now_iso() + "\n", 0o600)
        state = load_json(state_path, {"notified": {}, "stale": []})
        if scan_once(chat_root, binding, state):
            atomic_write(state_path, json_bytes(state), 0o600)
        time.sleep(2)
    return 0


def hook(args: argparse.Namespace) -> int:
    payload = json.load(sys.stdin)
    session_id = str(payload.get("session_id", ""))
    chat_root = expand(args.chat_root)
    binding_path, heartbeat, _ = binding_paths(chat_root, args.agent)
    if args.event == "session-end":
        if binding_path.exists() and load_json(binding_path, {}).get("session_id") == session_id:
            stop_binding(chat_root, args.agent, session_id, force=False)
        return 0
    if not binding_path.exists():
        return 0
    binding = load_json(binding_path, {})
    live = binding_live(binding, heartbeat)
    if not live:
        context = "multiagent-collab binding is stale; run an explicit rebind."
    elif binding.get("session_id") != session_id:
        context = f"multiagent-collab is bound to another live session: {binding.get('session_id')}"
    elif args.agent == "claude" and binding.get("wake_mode") == "monitor-file":
        monitor = binding_path.parent / "monitor.inbox"
        context = (
            f"Arm a persistent monitor on `tail -n 0 -F {monitor}` for multiagent-collab, "
            "then run probe-wake and echo the received nonce with verify-wake."
        )
    else:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    return 0


def verify_wake(args: argparse.Namespace) -> int:
    chat_root = expand(args.chat_root)
    binding_path, heartbeat, _ = binding_paths(chat_root, args.agent)
    binding = load_json(binding_path, {})
    if binding.get("session_id") != args.session_id:
        raise UserError("session does not own binding")
    if not binding_live(binding, heartbeat):
        raise UserError("binding is not live")
    challenge_path = binding_path.parent / "wake-challenge.json"
    challenge = load_json(challenge_path, {})
    if challenge.get("session_id") != args.session_id or challenge.get("nonce_sha256") != sha256_bytes(args.nonce.encode("utf-8")):
        raise UserError("wake verification nonce mismatch")
    if time.time() > float(challenge.get("expires_at", 0)):
        raise UserError("wake verification nonce expired")
    binding["wake_verified"] = True
    binding["verified_at"] = now_iso()
    binding["verified_nonce_sha256"] = sha256_bytes(args.nonce.encode("utf-8"))
    atomic_write(binding_path, json_bytes(binding), 0o600)
    challenge_path.unlink(missing_ok=True)
    state_path = binding_path.parent / "watch-state.json"
    state = load_json(state_path, {}) if state_path.exists() else {}
    if state.get("session_id") == args.session_id:
        state["notified"] = {}
        state["attempts"] = {}
        state["failed"] = []
        state["unverified"] = []
        atomic_write(state_path, json_bytes(state), 0o600)
    return 0


def probe_wake(args: argparse.Namespace) -> int:
    chat_root = expand(args.chat_root)
    binding_path, heartbeat, _ = binding_paths(chat_root, args.agent)
    binding = load_json(binding_path, {})
    if binding.get("session_id") != args.session_id or not binding_live(binding, heartbeat):
        raise UserError("probe requires this live bound session")
    nonce = secrets.token_hex(16)
    challenge_path = binding_path.parent / "wake-challenge.json"
    challenge = {
        "session_id": args.session_id,
        "nonce_sha256": sha256_bytes(nonce.encode("utf-8")),
        "expires_at": time.time() + 120,
    }
    binding["wake_verified"] = False
    atomic_write(binding_path, json_bytes(binding), 0o600)
    atomic_write(challenge_path, json_bytes(challenge), 0o600)
    script = Path(__file__).resolve()
    echo_command = " ".join(
        shlex.quote(word)
        for word in (
            "python3", str(script), "verify-wake", "--chat-root", str(chat_root),
            "--agent", args.agent, "--session-id", args.session_id, "--nonce", nonce,
        )
    )
    if not wake(binding, binding_path.parent, f"multiagent-collab wake probe nonce {nonce}. Run: {echo_command}"):
        challenge_path.unlink(missing_ok=True)
        raise UserError("wake probe transport failed")
    print("wake probe sent; nonce is available only through the wake transport")
    return 0


def doctor(args: argparse.Namespace) -> int:
    home = expand(args.home)
    chat_root = expand(args.chat_root)
    skill_root = expand(Path(__file__).parent.parent)
    asset = skill_root / "assets" / "PROTOCOL.md"
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str, severity: str = "error") -> None:
        checks.append({"name": name, "ok": ok, "severity": severity, "detail": detail})

    installed = chat_root / "PROTOCOL.md"
    check("packaged_protocol", asset.is_file(), str(asset))
    check("installed_protocol", installed.is_file(), str(installed))
    if asset.is_file() and installed.is_file():
        check("protocol_hash", sha256_file(asset) == sha256_file(installed), f"packaged={sha256_file(asset)} installed={sha256_file(installed)}")
    for agent in selected_agents(args.agent):
        link = home / f".{agent}" / "skills" / SKILL_NAME
        check(f"{agent}_skill_link", link.is_symlink() and symlink_target(link) == skill_root, str(link))
        hooks_path = home / (".codex/hooks.json" if agent == "codex" else ".claude/settings.json")
        hooks = load_json(hooks_path, {}) if hooks_path.exists() else {}
        groups = hooks.get("hooks", {}) if isinstance(hooks, dict) else {}
        has_hooks = all(any(is_managed_hook(group, agent) for group in groups.get(event, [])) for event in ("SessionStart", "SessionEnd")) if isinstance(groups, dict) else False
        check(f"{agent}_hooks", has_hooks, str(hooks_path))
        binding_path, heartbeat, _ = binding_paths(chat_root, agent)
        binding = load_json(binding_path, {}) if binding_path.exists() else {}
        live = binding_live(binding, heartbeat)
        check(f"{agent}_binding", live, f"session={binding.get('session_id')} pid={binding.get('pid')}", "error" if args.require_binding else "warning")
        verified = live and bool(binding.get("wake_verified"))
        check(f"{agent}_wake", verified, f"mode={binding.get('wake_mode')}", "error" if args.require_binding else "warning")
    if "codex" in selected_agents(args.agent):
        agents_md = home / ".codex" / "AGENTS.md"
        present = agents_md.exists() and MANAGED_START in agents_md.read_text(encoding="utf-8")
        check("codex_guidance", present, str(agents_md))
        check("codex_hook_trust", False, "verify non-managed hook hash with /hooks", "warning")
    failed = [item for item in checks if not item["ok"] and item["severity"] == "error"]
    if args.json:
        print(json.dumps({"ok": not failed, "checks": checks}, indent=2))
    else:
        for item in checks:
            state = "OK" if item["ok"] else item["severity"].upper()
            print(f"{state:7} {item['name']}: {item['detail']}")
    return 1 if failed else 0


def manifest_entries(task: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for path in sorted(task.rglob("*")):
        if path.name == "MANIFEST.sha256" or ".baton.lock" in path.parts:
            continue
        if path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir()):
            raise UserError(f"archive rejects non-regular path: {path}")
        if path.is_file():
            entries.append((sha256_file(path), path.relative_to(task).as_posix()))
    return entries


def manifest_text(entries: Iterable[tuple[str, str]]) -> str:
    return "".join(f"{digest}  {name}\n" for digest, name in entries)


def verify_manifest(task: Path) -> None:
    manifest = task / "MANIFEST.sha256"
    expected: list[tuple[str, str]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        expected.append((digest, name))
    actual = manifest_entries(task)
    if expected != actual:
        raise UserError("archive manifest verification failed")


def task_summary(task_md: Path) -> tuple[str, str]:
    text = task_md.read_text(encoding="utf-8")
    title_match = re.search(r"^# Task:\s*(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else task_md.parent.name
    owner = task_owner(task_md) or "unknown"
    return title.replace("|", "-"), owner


def archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if ".baton.lock" in Path(info.name).parts:
        return None
    return info


def archive_task(args: argparse.Namespace) -> int:
    chat_root = expand(args.chat_root)
    task = task_path(chat_root, args.task_id)
    lock = task / ".baton.lock"
    archive_dir = chat_root / "_archive"
    final = archive_dir / f"{args.task_id}.tar.gz"
    temp = archive_dir / f".{args.task_id}.tar.gz.tmp"
    started = False
    acquire_baton_lock(lock, "archive", False)
    try:
        baton = parse_baton(task / "BATON.md")
        if baton["seq"] != args.expected_seq:
            raise UserError("archive sequence changed")
        owner, _ = contract_roles(task, baton)
        if (
            baton["status"] != "done"
            or owner not in AGENTS
            or baton["holder"] != owner
            or args.agent != owner
            or baton["task_sha256"] == "pending"
            or baton["verdict"] != "PASS"
            or not baton["owner_ready"]
            or not baton["reviewer_ready"]
        ):
            raise UserError("archive requires operator CLOSE and the owner's cleanup turn")
        started = True
        existing_log = (task / "LOG.md").read_text(encoding="utf-8").rstrip()
        heading = f"## Seq {baton['seq']} — {owner} cleanup to none"
        atomic_text(task / "LOG.md", f"{existing_log}\n\n{heading}\n\nArchive-and-remove cleanup started after operator CLOSE.\n")
        baton["seq"] += 1
        baton["holder"] = "none"
        baton["ask"] = "Task closed and archived."
        baton["updated_at"] = now_iso()
        atomic_text(task / "BATON.md", dump_baton(baton))
        atomic_text(task / "MANIFEST.sha256", manifest_text(manifest_entries(task)))
        archive_dir.mkdir(parents=True, exist_ok=True)
        if final.exists():
            raise UserError(f"archive already exists for {args.task_id}")
        temp.unlink(missing_ok=True)
        with tarfile.open(temp, "w:gz") as archive:
            archive.add(task, arcname=args.task_id, recursive=True, filter=archive_filter)
        with tempfile.TemporaryDirectory(prefix="multiagent-collab-verify-") as directory:
            with tarfile.open(temp, "r:gz") as archive:
                archive.extractall(directory, filter="data")
            verify_manifest(Path(directory) / args.task_id)
        os.replace(temp, final)
        index = archive_dir / "INDEX.md"
        original = index.read_text(encoding="utf-8").rstrip() if index.exists() else "# Archived tasks"
        title, owner = task_summary(task / "TASK.md")
        row = (
            f"- {args.task_id} | {title} | owner {owner} | result {baton['verdict']} | "
            f"closed {now_iso()} | revision {baton['revision']} | {final} | sha256 {sha256_file(final)}"
        )
        atomic_text(index, original + "\n" + row + "\n")
        current = parse_baton(task / "BATON.md")
        if current["seq"] != args.expected_seq + 1 or current["holder"] != "none":
            raise UserError("archive sequence changed before removal")
        shutil.rmtree(task)
        for agent in AGENTS:
            state = chat_root / "_runtime" / agent / "watch-state.json"
            if state.exists():
                data = load_json(state, {})
                data.get("notified", {}).pop(args.task_id, None)
                data["stale"] = [key for key in data.get("stale", []) if not key.startswith(args.task_id + ":")]
                atomic_write(state, json_bytes(data), 0o600)
        print(final)
        return 0
    except Exception:
        temp.unlink(missing_ok=True)
        if started and task.exists():
            try:
                failed = parse_baton(task / "BATON.md")
                failed["status"] = "blocked"
                failed["holder"] = task_owner(task / "TASK.md") or "operator"
                failed["verdict"] = "BLOCKED"
                failed["owner_ready"] = False
                failed["reviewer_ready"] = False
                failed["ask"] = "Archive cleanup failed; inspect evidence and obtain operator direction."
                failed["updated_at"] = now_iso()
                atomic_text(task / "BATON.md", dump_baton(failed))
            except Exception:
                pass
        raise
    finally:
        if lock.exists():
            shutil.rmtree(lock, ignore_errors=True)


def status(args: argparse.Namespace) -> int:
    baton = parse_baton(task_path(expand(args.chat_root), args.task_id) / "BATON.md")
    if args.json:
        print(json.dumps(baton, indent=2))
    else:
        print(f"{args.task_id}: seq={baton['seq']} holder={baton['holder']} status={baton['status']} ask={baton['ask']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--chat-root", default=os.environ.get("MULTIAGENT_COLLAB_CHAT_ROOT", DEFAULT_CHAT_ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("setup", "uninstall"):
        item = sub.add_parser(name, parents=[common])
        item.add_argument("--agent", choices=("codex", "claude", "both"), default="both")
        item.add_argument("--home", default="~")
        item.add_argument("--dry-run", action="store_true")
        item.add_argument("--follow-config-symlinks", action="store_true")
        if name == "setup":
            item.add_argument("--upgrade-protocol-from")
            item.set_defaults(func=setup)
        else:
            item.set_defaults(func=uninstall)

    item = sub.add_parser("doctor", aliases=["check"], parents=[common])
    item.add_argument("--agent", choices=("codex", "claude", "both"), default="both")
    item.add_argument("--home", default="~")
    item.add_argument("--json", action="store_true")
    item.add_argument("--require-binding", action="store_true")
    item.set_defaults(func=doctor)

    item = sub.add_parser("task-init", parents=[common])
    item.add_argument("--task-id", required=True)
    item.add_argument("--owner", choices=AGENTS, required=True)
    item.add_argument("--task-file", required=True)
    item.set_defaults(func=task_init)

    item = sub.add_parser("pass", parents=[common])
    item.add_argument("--task-id", required=True)
    item.add_argument("--agent", choices=AGENTS, required=True)
    item.add_argument("--expected-seq", type=int, required=True)
    item.add_argument("--next-holder", choices=(*AGENTS, "operator", "none"), required=True)
    item.add_argument("--log-file", required=True)
    item.add_argument("--status", choices=("active", "blocked", "done"))
    item.add_argument("--round", type=int)
    item.add_argument("--revision")
    item.add_argument("--verdict", choices=("PASS", "CHANGES_REQUIRED", "BLOCKED", "none"))
    item.add_argument("--owner-ready", choices=("keep", "true", "false"), default="keep")
    item.add_argument("--reviewer-ready", choices=("keep", "true", "false"), default="keep")
    item.add_argument("--ask", required=True)
    item.add_argument("--break-stale-lock", action="store_true")
    item.add_argument("--operator-reason", choices=("contract", "blocked", "signoff"))
    item.set_defaults(func=baton_pass)

    item = sub.add_parser("signoff", parents=[common])
    item.add_argument("--task-id", required=True)
    item.add_argument("--agent", choices=AGENTS, required=True)
    item.add_argument("--expected-seq", type=int, required=True)
    item.add_argument("--log-file", required=True)
    item.add_argument("--ask", default="Review and close this completed task.")
    item.add_argument("--break-stale-lock", action="store_true")
    item.set_defaults(func=signoff)

    item = sub.add_parser("operator-relay", parents=[common])
    item.add_argument("--task-id", required=True)
    item.add_argument("--agent", choices=AGENTS, required=True)
    item.add_argument("--expected-seq", type=int, required=True)
    item.add_argument("--action", choices=("approve", "stop", "ruling", "amend", "close"), required=True)
    item.add_argument("--next-holder", choices=(*AGENTS, "operator"), required=True)
    item.add_argument("--task-sha256")
    item.add_argument("--log-file", required=True)
    item.add_argument("--ask", required=True)
    item.add_argument("--break-stale-lock", action="store_true")
    item.set_defaults(func=operator_relay)

    for name in ("bind", "rebind"):
        item = sub.add_parser(name, parents=[common])
        item.add_argument("--agent", choices=AGENTS, required=True)
        item.add_argument("--session-id", required=True)
        item.add_argument("--project", required=True)
        item.add_argument("--wake-mode", choices=("codex-queue", "command", "monitor-file"))
        item.add_argument("--wake-command-json")
        item.set_defaults(func=(lambda args, mode=name == "rebind": bind(args, rebind=mode)))

    item = sub.add_parser("release", parents=[common])
    item.add_argument("--agent", choices=AGENTS, required=True)
    item.add_argument("--session-id", required=True)
    item.set_defaults(func=lambda args: (stop_binding(expand(args.chat_root), args.agent, args.session_id, force=False) or 0))

    item = sub.add_parser("watch", parents=[common])
    item.add_argument("--agent", choices=AGENTS, required=True)
    item.add_argument("--session-id", required=True)
    item.set_defaults(func=watch)

    for name, function in (("probe-wake", probe_wake), ("verify-wake", verify_wake)):
        item = sub.add_parser(name, parents=[common])
        item.add_argument("--agent", choices=AGENTS, required=True)
        item.add_argument("--session-id", required=True)
        if name == "verify-wake":
            item.add_argument("--nonce", required=True)
        item.set_defaults(func=function)

    item = sub.add_parser("hook", parents=[common])
    item.add_argument("--agent", choices=AGENTS, required=True)
    item.add_argument("--event", choices=("session-start", "session-end"), required=True)
    item.set_defaults(func=hook)

    item = sub.add_parser("status", parents=[common])
    item.add_argument("--task-id", required=True)
    item.add_argument("--json", action="store_true")
    item.set_defaults(func=status)

    item = sub.add_parser("archive", parents=[common])
    item.add_argument("--task-id", required=True)
    item.add_argument("--agent", choices=AGENTS, required=True)
    item.add_argument("--expected-seq", type=int, required=True)
    item.set_defaults(func=archive_task)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
