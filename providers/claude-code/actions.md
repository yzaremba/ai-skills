## How actions are done on Claude Code

Role ids are used as written, e.g. `product-manager`.

### Start

- **Start a session as a role.** The user's to do, never yours: `claude --agent manager --effort <level>`, with the level setup prints for the role, or `"agent": "manager"` in the project's `.claude/settings.json`, where setup writes the effort beside it.
- **Checked** against Claude Code 2.1.289 (docs, skeleton run 2026-10-05).

### Session

- **Load a role.** The user types `/<role-id>`; you never load a role yourself.
- **Compact.** At a phase boundary the Manager asks the user for the `/context` figure and, past about 60% of the model's context window, to run `/compact`.
- **Switch the loaded role back.** The user says it in a message, such as "back to the Manager"; it holds from then on.

### Dispatch

- **Dispatch a role.** The `Agent` tool with `subagent_type` set to the role id, the brief as `prompt`, and a `name` of the role id plus a short suffix, so the agent can be addressed later. Pass no `model` and no `effort`: the definition pins both.
- **Wait for a dispatched agent.** Its output arrives later as a completion notification marked as that agent's: agent output, never the user. Until then it is running; do not guess its result.
- **Follow up with a finished agent.** `SendMessage` with `to` set to the agent's name or the agent id its result gave you. It resumes with its whole history; after a restart only once the same session is resumed. A five-minute-cache role (the Investigator, a Coder, the Code Reviewer): only within 5 minutes of its report; else a fresh one.

### Dialogue

- **The user can also type to a dispatched agent**, an option you may name; you relay its questions either way. How: select its row in the agent panel under the prompt while it runs, or in `/tasks` for 30 seconds after it finishes, and press Enter to open its transcript; type there. An open transcript stays open when the turn ends; after those 30 seconds only your follow-up resumes a closed one.
- **Its hand-backs reach you by themselves**: each turn the user drives there sends you the hand-back as a completion notification (observed on 2.1.289, undocumented).

### In dialogue

- **If you are the dispatched agent,** you have no question dialog. Write the question as plain text in your thread first, then hand back. If a tool is given for the final report, the hand-back is that call; write the question before it. The user answers in your thread or through the Manager's follow-up; either resumes you.

### Read

- **Read, with no command.** `Read` opens a file, `Grep` searches text and `Glob` lists files.

### Commands

- **Run a command.** The `Bash` tool. A permission prompt goes to the user; another agent's message never answers one. A role that may not change files does not change them through `Bash` either, beyond what its role text lists.
- **Wait on a long job**: each wait just under 5 minutes, the cache's life; read the log.

### Files

- **Change a file.** `Edit` for an existing file, `Write` for a new one.

### Commit

- **Commit.** With `Bash`: `git add -- <new file>` for each file git does not track yet, never `git add -A`, `git add .` or `git commit -a`; then `git commit -m "<message>" -- <file> <file>` naming every file of the change, new ones included, which commits those files only, whatever was staged before; then `git log -1 --oneline`, and report that id. Use `git -C <dir>` when the brief's working directory is not the current one.

### Parallel group

Every command here is subject to the session's permission rules, like any other.

- **Several agents at once.** Put the `Agent` calls in one message. They run side by side, and each reports on its own.
- **Add a worktree.** The root is outside the repository or a git-ignored directory inside it. `git worktree add <root>/<name> -b <branch> <commit>`, run in the sprint's workspace.
- **Merge.** `git merge <branch>` in the sprint's workspace, never with `--squash` and never a rebase. `git merge --abort` ends a merge that conflicts.
- **Remove what is merged.** `git worktree remove <path>`, then `git branch -d <branch>`, both run in the sprint's workspace. Never `--force` and never `-D`.

### Prompt cache

- **Checked 2026-10-20 on Claude Code 2.1.304** (the sub-agents page, the prompt-caching page, the costs page, the API caching page): no change to the 2026-10-12 reading. A dispatched agent's cache lasts five minutes, also on a subscription, unless its definition says `experimental: cacheTtl: 1h` (`cache = "long"` in a role's profile writes it). `subagentPromptCacheTtl` (setting) and CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL (variable) override the definition, FORCE_PROMPT_CACHING_5M=1 overrides both, and ENABLE_PROMPT_CACHING_1H=1 ranks below the definition. The definition's `1h` is ignored while the subscription draws on usage credits. A one-hour write costs 2x the base input price, a five-minute write 1.25x.
- **Long cache** (`cache = "long"`): product-manager, architect, implementation-manager, plan-reviewer, idea-reviewer, the roles that wait for an answer. **Five minutes:** the Coders, the Code Reviewer, the Investigator. In sprint 87, twelve Coder re-writes of about 240K tokens cost about 3.6M weighted tokens; a one-hour cache on all 37 Coders would have cost about 9.9M more in write surcharge. So for Coders and reviewers the remedy is the five-minute rule (Dispatch and Commands above), not the setting.
- **Consequence for the long-cache roles:** the cache lives an hour, so the Manager follows up with a waiting Implementation Manager under an hour, and after an hour or more dispatches a fresh one (`roles/manager/ROLE.md`, "Prefer a follow-up").
