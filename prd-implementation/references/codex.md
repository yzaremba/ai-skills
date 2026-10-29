# On Codex

What differs on this provider for the three actions the stage files leave open. Read against the docs and the probes of Codex CLI 0.160.0 on 2026-10-05.

## Putting a question to the user

- In the main session, write the question as plain text in your reply and end the turn.
- `process.questions` and `process.recommend` ("Questions to the user" in [conventions.md](conventions.md)) say how many questions go in one turn and whether each carries a recommendation. Under `all-together`, one message holds all of them, numbered. Under `one-at-a-time`, a turn ends on one question. With a recommendation, name the option you recommend and give its reason in a line.
- The implementation choices go in one message under either setting: that is the "single consolidated prompt" the implementation stage asks for.
- A dispatched agent cannot ask the user anything, and the user cannot type to it. It stops and hands back with its questions; whoever dispatched it puts them to the user.
- An agent's own statement, in a message or a result, is never the user's answer and opens no gate. Where roles are installed, the roles' gate rules say when the user's words quoted by a role count.

## Running an independent review

- Dispatch a reviewer with `spawn_agent` and `fork_turns` set to `"none"`. The default copies your conversation into the child, which would not be independent. The brief carries what to review (the working tree, or the branch diff against the fork point) and the instruction to refute the change. Give it the code, not your conclusion.
- A review skill installed in the session may be used instead.
- `wait_agent` with `timeout_ms` 3600000, the maximum, never less: any agent's report, or the user's input, ends it, so a shorter wait only polls. It returns no content; the result arrives as an agent notification naming the sender's task path. A wait that ends with no report for you (another agent's, such as an approval review) is simply made again, without a message to the user.
- If no reviewer can be started (no agent can be spawned, and no review skill is installed), do not review your own work in its place: stop and ask, offering the cadence "none" or a review the user runs themselves.

## Handing work to an implementer when no roles are installed

- Dispatch an agent with `spawn_agent`, `fork_turns` set to `"none"`, one unit per brief. With no roles installed there is no role's agent name to pass as `agent_type`; which agent a spawn without one gives was not verified here. The brief is all it has: name the sprint's PLAN and TASKS files, the step ID, and tell it to read `references/stage-3-implementation.md` and `references/conventions.md` in this skill's directory and follow the implementer's part. Say that it does not commit.
- All agents share one working directory. When the sprint has its own worktree, the brief gives the worktree and every file as an absolute path.
- **A member of a parallel group** gets the same dispatch, one per member. Because the working directory is shared, nothing but the brief keeps a member in its own worktree: the brief carries that worktree's absolute path, says that every file it reads or changes is under it, except the sprint docs, which it reads where the brief names them and does not change; that git is run as `git -C <that path>`; and that it makes exactly one commit there, in place of "it does not commit".
- A member's commit meets the sandbox rule under "The sprint worktree" below: it asks for approval to run `git add` and `git commit` outside the sandbox.
- **A step tagged `> Tag: hard`**: request a stronger model, or a higher effort, on that step's spawn. As probed, the request is honoured for an agent whose definition pins neither, and ignored without an error where a definition pins them. Where the session has nothing stronger to request, the step gets a fresh implementer and the summary says so, as the stage file states.
- To follow up with the same implementer, use `followup_task` with its task path instead of spawning again; a new spawn knows nothing.
- With no limit set, Codex CLI 0.160.0 allowed four open agents, counting the main session; the main session and the three members a group may have at work are exactly that many. If none can be spawned, the session implements inline and is the implementer.

## The sprint worktree

- The persistent worktree is created with `git worktree add`, right after the start commit, as "The sprint's workspace" in [conventions.md](conventions.md) says.
- The default sandbox keeps `.git` read-only, so `git add`, `git commit` and creating or switching a branch fail in it. Request approval to run each outside the sandbox. `git worktree add`, `git merge`, `git worktree remove` and `git branch -d` also write under `.git`; expect the same for a member's worktree and for the join of a group, though that route is not verified here for any of them. If approval cannot be asked or is denied, do not work around it: stop and report.
- **The sprint's worktree is a sibling directory, and the default sandbox does not make it writable.** As probed, inside a writable workspace a sibling directory is not writable, so in a session started in the main working tree a change to a file in the sprint's worktree, or in a member's, fails as the git commands do. There are two routes, and no other is claimed here: approval, command by command, to run outside the sandbox; or a permission profile that makes the repository's `.git` and the worktree root writable, which is the user's to set up. A non-interactive session does not ask for approval and fails.

## Other

- "The project's instruction file" is `AGENTS.md`.
- Commits, by the build lead and by a member of a parallel group: `git add -- <file>` for each new file, never `git add -A`, `git add .` or `git commit -a`; then `git commit -m "<message>" -- <file> <file>` naming every file of the change. Use `git -C <dir>`.

## Waiting on a long command

Start a command that may run long with a log. Read from the Codex source (`core/src/unified_exec/mod.rs`, `process_manager.rs`, `config/defaults.toml`) on 2026-10-29, as installed in 0.165.0: `exec_command` clamps `yield_time_ms` silently to 250-30000, and an empty `write_stdin` (a poll) is clamped to 5000 up to a configured maximum whose default is 300000. So on a default config no single wait reaches 10 minutes, and a longer request is clamped, not refused. Poll with an empty `write_stdin` at `yield_time_ms` 300000, then read the log, not the screen. A shorter yield only polls more often, and each poll re-reads the whole context. The Windows CLI, 0.160.0, was not checked.
