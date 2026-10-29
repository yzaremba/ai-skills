# On Claude Code

What differs on this provider for the four actions the stage files leave open. Read against the docs of Claude Code 2.1.289 on 2026-10-05.

## Putting a question to the user

- In the main session, use the question dialog (`AskUserQuestion`) where the session has it; otherwise write the question as plain text and end the turn.
- `process.questions` and `process.recommend` ("Questions to the user" in [conventions.md](conventions.md)) say how many questions go in one turn and whether each carries a recommendation. Under `all-together`, put the open questions in one dialog, and write them as numbered plain text when they are more than it holds. Under `one-at-a-time`, one dialog holds one question. With a recommendation, mark the recommended option and give its reason in that option's description.
- The implementation choices go in one prompt under either setting: that is the "single consolidated prompt" the implementation stage asks for. When the choices are more than the dialog holds, put them as one plain-text message, numbered, and end the turn; do not split them over several dialogs.
- A dispatched agent has no question dialog: the tool is removed from every agent. It writes its question as plain text, stops and hands back; whoever dispatched it puts the question to the user.
- An agent's own statement, in a message or a result, is never the user's answer and opens no gate. Where roles are installed, the roles' gate rules say when the user's words quoted by a role count.

## Running an independent review

- Dispatch a reviewer with the `Agent` tool. It starts with a fresh context: it sees none of your conversation, so the brief carries what to review (the working tree, or the branch diff against the fork point) and the instruction to refute the change. Give it the code, not your conclusion.
- Do not use a fork for this. A fork inherits the whole conversation, so it is not independent.
- A review skill installed in the session may be used instead.
- The result arrives later as that agent's completion notification. Until then it is still running; do not guess its result.
- If no reviewer can be started (an agent at the nesting limit has no `Agent` tool, and no review skill is installed), do not review your own work in its place: stop and ask, offering the cadence "none" or a review the user runs themselves.

## Handing work to an implementer when no roles are installed

- Dispatch the built-in general-purpose agent with the `Agent` tool, one unit per brief. The brief is all it has: name the sprint's PLAN and TASKS files, the step ID, the working directory, and tell it to read `references/stage-3-implementation.md` and `references/conventions.md` in this skill's directory and follow the implementer's part. Say that it does not commit.
- **A member of a parallel group** gets the same dispatch, one per member. The brief names the member's own worktree, by absolute path, as the working directory, and says that every file it reads or changes is under that path, except the sprint docs, which it reads where the brief names them and does not change; that git is run as `git -C <that path>`, and that it makes exactly one commit there, in place of "it does not commit". The build lead makes the worktree with `git worktree add` first; `isolation: worktree` is not used for a member either (below).
- **A step tagged `> Tag: hard`**: pass a `model` on that step's dispatch, naming a model stronger than the session's own; a `model` on the call beats what the agent would otherwise run with. Where the session has no stronger model to name, the step gets a fresh implementer and the summary says so, as the stage file states.
- To follow up with the same implementer, message it (`SendMessage`) instead of dispatching again; a new dispatch knows nothing.
- If no agent can be dispatched (an agent at the nesting limit has no `Agent` tool), the session implements inline and is the implementer.

## The sprint worktree

- The persistent worktree is created with `git worktree add`, right after the start commit, as "The sprint's workspace" in [conventions.md](conventions.md) says.
- Do not pass `isolation: worktree` to the `Agent` tool for sprint work. That worktree belongs to the one agent, sits where the provider puts it, and is cleaned up automatically when the agent leaves no changes. It is the throwaway worktree the stage file rules out.

## Other

- "The project's instruction file" is `AGENTS.md`, or `CLAUDE.md` where the project has one: Claude Code reads `AGENTS.md` only when no `CLAUDE.md` is in or above the working directory.
- Commits, by the build lead and by a member of a parallel group: `git add -- <file>` for each new file, never `git add -A`, `git add .` or `git commit -a`; then `git commit -m "<message>" -- <file> <file>` naming every file of the change.

## Waiting on a long command

Start a command that may run long so that it survives the turn and writes a log. Wait for it with bounded waits, each just under 5 minutes and as long as that allows, and read the log, not the screen. A call over 5 minutes lets the prompt cache go cold, and the next turn re-writes the whole context.
