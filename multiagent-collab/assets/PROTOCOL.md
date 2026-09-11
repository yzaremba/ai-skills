# Codex-Claude Baton Protocol

Version: 1.0  
Status: effective for a chat root after operator acceptance of this content hash  
Default chat root: `~/workspace/chat/`  
Default skills root: `~/workspace/skills/`  
Canonical skill: `<skills-root>/multiagent-collab/`

## 1. Roles

- Each task has one owner (`codex` or `claude`); the other agent is reviewer.
- Only the owner side may change the designated repo worktree. The reviewer side
  gives feedback only and runs tests in a disposable copy when writes are possible.
- Subagents inherit their parent's role and limits; the parent remains accountable.
- The operator starts/stops agents and watchers, approves scope and completion, may
  intervene at any time, and alone closes a task.
- Platform safety and repo instructions still apply. Changes to `AGENTS.md`,
  `CLAUDE.md`, `.agents/`, `.codex/`, `.claude/`, or `.claude-*` are blocking unless
  explicitly in scope. The reviewer reads them from the approved base, not the
  owner's modified worktree.
- Installing user-level links, instructions, or hooks under `~/.codex/` or
  `~/.claude/` requires an approved task naming the files.

## 2. Task files

```text
<chat-root>/
├── PROTOCOL.md
├── _archive/INDEX.md
└── <task-id>/
    ├── TASK.md       # contract; immutable after approval
    ├── BATON.md      # who acts next
    ├── LOG.md        # append-only handoff history
    ├── reviews/      # optional detail
    └── artifacts/    # optional deliverables
```

Task IDs use `YYYYMMDD-NNN-short-slug`; `_` names are infrastructure. Task files
must not contain secrets. Agents normally read only `TASK.md`, `BATON.md`, and the
latest relevant `LOG.md` entry; older detail is loaded only when needed.
Load `PROTOCOL.md` once per session and reload it only when its hash changes.

`TASK.md` states owner/reviewer, repo/worktree/base, objective, scope/non-goals,
permissions, acceptance checks, completion condition, review limit, and cleanup
mode. Before operator approval, only bounded read-only scoping is allowed.

The shared implementation lives at `<skills-root>/multiagent-collab/`.
Personal discovery symlinks expose it at `~/.codex/skills/multiagent-collab/` and
`~/.claude/skills/multiagent-collab/`. Keep only a short trigger/pointer in the
user-level `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md`; project instruction files
need no change. A watcher wake explicitly invokes the skill, so the full workflow is
loaded only when needed.

The skill ships one idempotent setup utility for `codex`, `claude`, or `both`. It
configures `<chat-root>` (default `~/workspace/chat/`), discovery symlinks, managed instruction blocks,
and session hooks without hardcoded user paths or silent overwrites. It supports
dry-run, doctor/check, and uninstall; preserves unrelated configuration; backs up
edits; and leaves required hook trust decisions to the user. Uninstall removes only
managed integration files and never deletes tasks or archives.

## 3. Baton

Only the baton holder takes the next task turn. The operator and an emergency safety
stop are exceptions. A non-holder may observe but cannot advance work or edit task
artifacts.

```yaml
task: 20260910-001-example
seq: 4
holder: codex|claude|operator|none
status: active|blocked|done
round: 2
revision: <commit-or-content-hash|null>
verdict: PASS|CHANGES_REQUIRED|BLOCKED|none
owner_ready: true|false
reviewer_ready: true|false
ask: <one to three lines describing the next action>
updated_at: <ISO-8601 timestamp with offset>
```

To pass the baton, the holder:

1. atomically creates `<task>/.baton.lock` with `mkdir` and writes holder and time
   inside; a lock older than five minutes may be broken, with the break noted in LOG
2. re-reads `BATON.md` under the lock; if `seq` changed, removes the lock and aborts
3. appends a compact LOG entry with current `seq`, result/evidence, risks, and ask
4. writes `.BATON.md.tmp` with `seq + 1`, atomically renames it over `BATON.md`, and
   removes the lock

The log is audit history; the baton is current state. A crash before rename leaves
the same holder, who may retry; the retry states that it supersedes any incomplete
LOG entry with the current sequence. Ministerial operator relays use the same lock.
A change after review starts creates a new revision and clears both readiness flags.

An agent passing the baton to `operator` notifies the operator through its live
session immediately; changing the file alone is not notification.

## 4. Start and approval

1. The initiator becomes owner, drafts `TASK.md`, initializes `LOG.md`, and passes
   the baton to the reviewer for contract review.
2. The reviewer returns it with changes or acceptance.
3. After acceptance, the owner shows the operator the contract hash plus scope,
   permissions, and completion condition, then records the response verbatim.
4. Approval returns the baton to the owner for implementation.

A narrow later amendment may be stated as an exact semantic delta. The owner records
before/after hashes; the reviewer confirms only that delta changed.

Operator instructions arrive through either active agent. That agent may perform the
ministerial act of recording the instruction and updating the baton exactly as
directed even when it is not holder. `STOP` sets `holder: operator` immediately.
The working agent rechecks the baton before every repo mutation or external effect.

## 5. Work and review

1. The owner works only in the declared worktree and records verification.
2. The owner freezes a revision, sets `owner_ready: true`, and passes to reviewer.
3. The reviewer checks that revision, acceptance criteria, regressions, safety, and
   evidence without modifying the repo.
4. `CHANGES_REQUIRED` clears readiness and returns the baton to owner with actionable
   findings. Unresolved disagreement after one evidence-based rebuttal goes to the
   operator.
5. `PASS` sets `reviewer_ready: true` for that revision and returns the baton to
   owner. The owner confirms its readiness still holds and passes to the operator.

Default maximum is five review rounds. It is a circuit breaker, not a quality goal;
the operator may extend it. Prefer a local checkpoint commit when authorized;
otherwise use a reproducible content/diff hash. Review is invalid if the revision
changes while the reviewer holds the baton.

## 6. Signoff

A task is ready only when owner and reviewer recorded readiness for the same
revision, the reviewer recorded PASS, checks passed or were waived, no blocker
remains, and `holder: operator`. Neither agent may close it.

Commit, push, merge, deploy, promotion, live-system operation, and destructive
actions require explicit scope; task completion does not imply them.

## 7. Watchers

The operator starts each agent session. Global session hooks are inert until the
operator opts that session in using the skill's
bind command or launcher. Exactly one session per agent owns
`<chat-root>/_runtime/<agent>/binding` (session, process, project, time). Later
sessions never steal it; moving it requires explicit rebind. Session end releases
only its own binding. A binding is live only while its process exists and watcher
heartbeat is recent; doctor and inert hooks report a dead binding, which still
requires explicit rebind rather than automatic theft.

The bound watcher polls `<chat-root>/*/BATON.md`. When `holder` is its agent and
`seq` is newer than its recorded sequence, it validates the task and wakes that
session. Codex runs the poller outside the tool sandbox and uses `codex queue`.
Claude uses a hook-started poller through its available session messaging transport,
with an explicitly armed in-session Monitor as fallback. Setup doctor/check must
prove and report the active wake path for each binding; unverified means not ready.
Startup scanning covers downtime without an operator task heads-up.

Watcher state lives under `<chat-root>/_runtime/<agent>/`, never in a task. Queue success
records notification, not task completion. If a baton does not move within the
TASK.md timeout (default 60 minutes), the non-holder agent's bound watcher notifies
the operator once for that sequence. When the operator holds the baton, the owner's
watcher notifies, with reviewer fallback if the owner binding is dead. No watcher
takes over. Malformed tasks are ignored and reported.

Before unattended repo writes, test both directions, duplicate notification,
watcher restart, stopped-watcher recovery, stale notification, and permission
boundaries. Tests explicitly cover a session killed without SessionEnd and stale
notification while the owner watcher is dead. Watchers are session-scoped unless
the operator installs a service.

## 8. Close and cleanup

`TASK.md` selects `keep-live` or default `archive-and-remove`. After operator
`CLOSE`, the owner gets one cleanup turn:

1. write the final log entry, set status `done`, holder `none`, and verify
   `.baton.lock` is absent before continuing
2. write `MANIFEST.sha256` in the task directory, covering every other task file
3. create `_archive/.<task-id>.tar.gz.tmp` containing the task directory
4. test-list and test-extract it, verify the manifest, then rename it to
   `_archive/<task-id>.tar.gz`
5. append task, owner, result, close time, revision, archive path, and archive hash
   to `_archive/INDEX.md`
6. only then remove the live task directory and its watcher state

Failure leaves the live task intact and marks cleanup blocked. The archive is the
recovery path. Worktree/branch cleanup follows repo rules and separate permission.

## 9. Protocol changes

Except while an already-open task is itself amending the protocol, every amendment
is a new task. The owner writes a candidate under that task's `artifacts/`; the
active protocol remains unchanged while both agents iterate. After both are ready,
the owner presents the operator with the concise diff, rationale, risks, and hash.
Only operator acceptance authorizes installation. Replacement also requires the
recorded base-protocol hash to remain current. Existing tasks keep their pinned
version unless the operator migrates them.

Keep this file short; implementation detail belongs in helpers or task artifacts.
