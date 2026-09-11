---
name: multiagent-collab
description: Coordinate an owner and an adversarial reviewer across Codex and Claude using a shared filesystem baton. Use when the user requests paired-agent implementation/review, asks one agent to harden the other's work, or a multiagent-collab watcher assigns this agent the baton. Do not use for ordinary solo work or same-runtime subagents.
---

# Multi-agent collaboration

Use the configured chat root (`MULTIAGENT_COLLAB_CHAT_ROOT`, default
`~/workspace/chat`). Load its `PROTOCOL.md` once per session and reload only when its
hash changes.

For a baton notification, read the task's `TASK.md`, `BATON.md`, and latest relevant
`LOG.md` entry. Act only when `holder` names this agent and the sequence is current.
The task owner and its subagents alone may modify the declared repository worktree;
the reviewer side gives feedback only.

Use `scripts/multiagent_collab.py` for deterministic setup, baton, binding, watcher,
doctor, and archive operations. Run `--help` for commands. Read
[references/commands.md](references/commands.md) only when installing, operating, or
debugging the runtime.

## Task workflow

- The initiating agent drafts the task contract and passes the baton to the other
  agent for contract review.
- Do not implement until the reviewer accepts the contract and the operator approves
  its scope, permissions, and completion condition.
- Freeze an exact revision before review. Any owner change invalidates prior review
  and readiness.
- A task reaches operator signoff only after both agents record readiness for the
  same revision and the reviewer records PASS.
- Installation, commits, merges, pushes, deployments, live operations, and cleanup
  require whatever authorization the task contract specifies; baton possession does
  not broaden authority.

When blocked or when the baton reaches the operator, notify the operator through the
live session. Silence or an unavailable watcher is not approval.
