# Runtime commands

Run commands from the canonical skill directory:

```text
python3 scripts/multiagent_collab.py <command> [options]
```

All commands accept `--chat-root`; the default is
`MULTIAGENT_COLLAB_CHAT_ROOT` or `~/workspace/chat`.

## Installation

```text
setup --agent codex|claude|both [--home PATH] [--dry-run]
doctor --agent codex|claude|both [--home PATH] [--json]
uninstall --agent codex|claude|both [--home PATH] [--dry-run]
```

Setup installs discovery links, managed global guidance, hooks, and the packaged
protocol. It refuses unmanaged conflicts and symlinked config files by default.
Use `--follow-config-symlinks` only with explicit approval for the resolved targets.
Protocol replacement additionally requires `--upgrade-protocol-from <sha256>`.

## Tasks and baton

```text
task-init --task-id ID --owner codex|claude --task-file PATH
status --task-id ID [--json]
pass --task-id ID --agent codex|claude --expected-seq N \
  --next-holder codex|claude|operator|none --log-file PATH [baton fields]
archive --task-id ID --expected-seq N
```

`pass` takes the shared `.baton.lock`, rechecks the sequence, appends the supplied
log entry, and atomically replaces the baton. Never edit the baton by hand during an
agent pass.

## Session binding and watchers

```text
bind --agent codex|claude --session-id ID --project PATH [wake options]
rebind --agent codex|claude --session-id ID --project PATH [wake options]
release --agent codex|claude --session-id ID
watch --agent codex|claude --session-id ID
hook --agent codex|claude --event session-start|session-end
```

Only one live binding per agent is allowed. Dead bindings are reported and require
explicit `rebind`; they are never stolen automatically. `doctor` reports protocol,
hook, skill-link, binding, heartbeat, and wake-path state.
