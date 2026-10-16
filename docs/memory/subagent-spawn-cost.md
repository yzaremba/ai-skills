# A subagent spawn costs a fixed context; prefer a follow-up for small work

**Recorded:** 2026-10-16, sprint 01
**Roles:** all (anyone who dispatches an agent, and whoever writes role text)

## What

On Claude Code every dispatched agent starts at about 40K tokens before it does anything: the shared system prompt and tools (cached), plus its role definition, the user's rules, the skills list and the brief, written fresh on each spawn. For a small task, follow up with an agent that already holds the context, or let the dispatching role do a one-command step itself where its rules allow, instead of spawning a fresh one.

## Why

In sample sprint B the Manager spawned a fresh Implementation Manager three times just to commit files another role had written; each spawn cost about 41K tokens for a few tool calls, and a second spawn of the same role rewrote the 18K part instead of reading it from cache. Decision U moved such commits to the Manager and the archive change to a follow-up for this reason.

## When it applies

Writing or changing role text that dispatches agents (`roles/`, `providers/*/actions.md`), designing a close or a hand-off, and any session deciding whether to spawn an agent for a step of a few commands.
