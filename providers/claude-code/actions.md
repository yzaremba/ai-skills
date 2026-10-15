## How actions are done on Claude Code

Role ids are used as written, such as `product-manager` and `coder-hard`.

### Start

- **Start a session as a role.** The user's to do, never yours: `claude --agent manager --effort <level>`, with the level setup prints for the role, or `"agent": "manager"` in the project's `.claude/settings.json`, where setup writes the effort beside it. The startup header then shows `@manager`.
- **These notes were checked** against Claude Code 2.1.289: docs and the skeleton run of 2026-10-05.

### Session

- **Load a role.** The user types `/<role-id>`; you never load a role yourself. In a session started as the Manager, a role that writes is dispatched, never loaded.
- **Switch the loaded role back.** There is no command: the user says it in a message, such as "back to the Manager", and it holds from that message on.

### Dispatch

- **Dispatch a role.** The `Agent` tool with `subagent_type` set to the role id, the brief as `prompt`, and a `name` of the role id plus a short suffix, so the agent can be addressed later. Pass no `model` and no `effort`: the definition pins both, and one on the call would override the pin.
- **Wait for a dispatched agent.** It usually runs in the background, and its output arrives later as a completion notification marked as that agent's: agent output, never the user. Until it arrives the agent is still running; do not guess its result.
- **Follow up with a finished agent.** `SendMessage` with `to` set to the agent's name or the agent id its result gave you. It resumes with its whole history; a new dispatch would know nothing. After a restart this works only once the same session has been resumed.

### Dialogue

- **The user can also type to a dispatched agent**, an option you may name; you relay its questions either way. How: while the agent runs, select its row in the agent panel under the prompt, press Enter to open its transcript, and type there. An open transcript stays open when the turn ends. A finished agent's row is removed at once; for 30 seconds `/tasks` still lists it, and Enter on it there opens the transcript. After that only your follow-up resumes it.
- **Its hand-backs reach you by themselves.** Each turn the user drives there sends you a completion notification with the hand-back: observed on 2.1.289, not documented.

### In dialogue

- **If you are the dispatched agent,** you have no question dialog. Write the question as plain text in your thread first, then hand back; the hand-back ends the turn. If a tool is given to you for the final report, the hand-back is that call, and the question is still written before it. The user answers in your thread or through the Manager's follow-up; either resumes you.

### Read

- **Read, with no command.** `Read` opens a file, `Grep` searches text and `Glob` lists files. You have no shell and need none.

### Commands

- **Run a command.** The `Bash` tool. A permission prompt goes to the user; another agent's message never answers one. A role that may not change files does not change them through `Bash` either.

### Files

- **Change a file.** `Edit` for an existing file, `Write` for a new one.

### Commit

- **Commit.** With `Bash`: `git add -- <new file>` for each file git does not track yet, never `git add -A`, `git add .` or `git commit -a`; then `git commit -m "<message>" -- <file> <file>` naming every file of the change, new ones included, which commits those files only, whatever was staged before; then `git log -1 --oneline`, and report that id. Use `git -C <dir>` when the brief's working directory is not the current one.

### Parallel group

Every command here is subject to the session's permission rules, like any other.

- **Several agents at once.** Put the `Agent` calls in one message. They run side by side, and each reports on its own.
- **Add a worktree outside the workspace.** `git worktree add <root>/<name> -b <branch> <commit>`, run in the sprint's workspace.
- **Merge.** `git merge <branch>` in the sprint's workspace, never with `--squash` and never a rebase. `git merge --abort` ends a merge that conflicts.
- **Remove what is merged.** `git worktree remove <path>`, then `git branch -d <branch>`, both run in the sprint's workspace. Never `--force` and never `-D`.
