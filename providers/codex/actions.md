## How actions are done on Codex

Agent names use underscores where role ids use hyphens (`product_manager`, `coder_hard`); a loaded role's skill keeps the hyphen (`$product-manager`).

### Start

- **Start a session as a role.** The user's to do, never yours: `codex --profile manager --no-daemon`, or the project's `.codex/config.toml` in a trusted project, in a session started at the project root. A profile pins model and effort and runs without the shared app-server daemon, which `codex remote-control` manages: such a session is not listed by `codex agents` and has no remote control. To keep them, start `codex` and type `$manager`, the loaded Manager, which names its model and effort for `/model`. The daemon statements were checked on 0.163.0 (`codex --help`, `codex remote-control --help` and the warning), `--no-daemon` also on 0.160.0.
- **These notes were checked** against Codex CLI 0.160.0: docs, probes and the skeleton run of 2026-10-05; `wait_agent` against the 0.162.1 source.

### Session

- **Load a role.** The user types `$<role-id>`; you never load a role yourself.
- **Switch the loaded role back.** There is no command: the user says it in a message, such as "back to the Manager", and it holds from that message on.
- **A command the user runs with `!`** starts no turn: you see it with their next message, so ask them to tell you when it is done.

### Dispatch

- **Dispatch a role.** `spawn_agent` with `agent_type` set to the agent name, a `task_name` of lowercase letters, digits and underscores, the brief as the message, and on every spawn `fork_turns = "none"`: the default copies your conversation. Request no model or effort: the definition pins both. If the agent name is not offered, say so and stop; likely cause, unverified: an untrusted project or a session not started at its root.
- **Wait for a dispatched agent.** `wait_agent` with `timeout_ms` 3600000, never less: any agent's report ends it, and one not for you means wait again, silently. It returns nothing; the report is an agent notification naming its sender's task path: agent output, never the user.
- **Follow up with a finished agent.** `followup_task` with `target` set to its task path. It keeps its context, also after a resume; a new spawn knows nothing.
- **One working directory** for all agents: a brief gives it, and each file, as an absolute path.

### Dialogue

- **The user cannot type to a dispatched agent**; `/subagents` shows its thread for watching only. So every brief says there is no dialogue, and you relay the agent's questions.

### In dialogue

- **If you are a dispatched agent,** you cannot ask the user anything, as probed. Do your brief, and only if it needs the user's answer hand back `stopped, needs the Manager` with your questions.

### Read

- **Read, with no command but a read.** Your shell tool is the only way to open a file, so use it for that alone: print a file, list a directory, search text, look at git history. Nothing else is run in it: no test, build, script or project code, and nothing that writes, installs or reaches the network. Only this instruction enforces it.

### Commands

- **Run a command.** Your shell tool. A role that may not change files does not change them through the shell either, beyond what its role text lists; only this instruction enforces it.
- **The sandbox** refuses a write to `.git` or beside the workspace by default: request approval to run that command outside it, and report a refusal instead of working around it.

### Files

- **Change a file.** Your file-editing tool.

### Commit

- **The sandbox** keeps `.git` read-only by default, so `git add`, `git commit` and creating or switching a branch (`git switch`, `git switch -c`) need the approval Commands describes; spawned Coders committed that way in the skeleton run, and the route is unverified for a branch. If approval cannot be asked or is denied, do not commit or switch.
- **Commit.** `git add -- <new file>` for each file git does not track yet, never `git add -A`, `git add .` or `git commit -a`; then `git commit -m "<message>" -- <file> <file>` naming every file of the change, new ones included, which commits those files only, whatever was staged before; then `git log -1 --oneline`, and report that id. Use `git -C <absolute dir>`.

### Parallel group

- **Several agents at once.** Spawn each, then wait for all. With no limit set, 0.160.0 allowed four open agents, main session too; a finished one holds no slot. A spawn refused for that limit is not worked around: start that agent when another has finished, and tell the user that `agents.max_concurrent_threads_per_session` set to 8 or more lifts the limit.
- **The sandbox** refuses every command below by default, and each needs the approval Commands describes. As probed, under a permission profile that makes the repository's `.git` and the worktree root writable they run with no approval.
- **Add a worktree outside the workspace.** `git -C <workspace> worktree add <root>/<name> -b <branch> <commit>`, with absolute paths.
- **Merge.** `git -C <workspace> merge <branch>`, never with `--squash` and never a rebase. `git -C <workspace> merge --abort` ends a merge that conflicts.
- **Remove what is merged.** `git -C <workspace> worktree remove <path>`, then `git -C <workspace> branch -d <branch>`. Never `--force` and never `-D`.
