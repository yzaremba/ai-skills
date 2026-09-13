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
doctor --agent codex|claude|both [--home PATH] [--json] [--require-binding]
uninstall --agent codex|claude|both [--home PATH] [--dry-run]
```

Setup installs discovery links, managed global guidance, hooks, and the packaged
protocol. It refuses unmanaged conflicts and symlinked config files by default.
Use `--follow-config-symlinks` only with explicit approval for the resolved targets.
Protocol replacement additionally requires `--upgrade-protocol-from <sha256>`.

Codex discovery uses the documented `~/.agents/skills/multiagent-collab` link;
Claude uses `~/.claude/skills/multiagent-collab`. A managed legacy Codex link under
`~/.codex/skills` is migrated only after offline `codex debug prompt-input` probes
verify the dual and post-removal states. On the verified 0.154.0 baseline, two
links to the same resolved skill target render as one legacy-rooted entry; multiple
entries indicate different resolved targets and stop migration. If the probe is
unavailable, setup warns, retains both links, and never claims verified migration.
Doctor reports both filesystem and actual Codex discovery state. Shared `.agents`
parent directories are never removed.

After installing or upgrading, restart each agent so it gets a new discovery and
hook snapshot. In Codex, review/trust the exact user hook with `/hooks`. Opt each
session in with `bind`, prove delivery with `probe-wake`/`verify-wake`, then require:

```text
doctor --agent both --require-binding
```

Doctor asks Codex's app server for the current user-hook trust status. Trusted hooks
report OK; changed, disabled, or missing hooks remain actionable warnings. If the
installed Codex cannot provide a trustworthy answer, doctor reports that status as
unavailable rather than claiming the hooks are untrusted.

`rebind` replaces a dead or differently owned binding. It is a no-op for an already
live binding owned by the same session. After a runtime-script upgrade, use
`release` and then `bind` for both agents so the watcher processes load the new code.

## Tasks and baton

```text
task-init --task-id ID --owner codex|claude --task-file PATH
status --task-id ID [--json]
pass --task-id ID --agent codex|claude --expected-seq N \
  --next-holder codex|claude|operator|none --log-file PATH [baton fields]
signoff --task-id ID --agent OWNER --expected-seq N --log-file PATH
operator-relay --task-id ID --agent RELAY --expected-seq N \
  --action approve|stop|ruling|amend|close --next-holder HOLDER --log-file PATH \
  [--task-sha256 SHA256]
archive --task-id ID --agent OWNER --expected-seq N
```

`pass` takes the shared `.baton.lock`, rechecks the sequence, appends the supplied
log entry, and atomically replaces the baton. Never edit the baton by hand during an
agent pass. `task-init` pins the owner/reviewer roles; operator approval pins the
approved `TASK.md` hash. Later role or unapproved contract drift is rejected.
`operator-relay --log-file` must name a non-empty file containing the operator's
verbatim instruction; the helper preserves that text in `LOG.md`. Approve and amend
also require the exact current `--task-sha256` shown to the operator.
An unpinned legacy baton is inert until one of those hash-checked operator relays
establishes its role and contract pins.

## Session binding and watchers

```text
bind --agent codex|claude --session-id ID --project PATH [wake options]
rebind --agent codex|claude --session-id ID --project PATH [wake options]
release --agent codex|claude --session-id ID
watch --agent codex|claude --session-id ID
probe-wake --agent codex|claude --session-id ID
verify-wake --agent codex|claude --session-id ID --nonce NONCE
hook --agent codex|claude --event session-start|session-end
```

Only one live binding per agent is allowed. Dead bindings are reported and require
explicit `rebind`; they are never stolen automatically. `doctor` reports protocol,
hook, skill-link, binding, heartbeat, and nonce-verified wake-path state. Claude's
monitor-file fallback must be explicitly armed before `probe-wake`.
