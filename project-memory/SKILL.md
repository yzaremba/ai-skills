---
name: project-memory
description: Lessons a project keeps for later sessions - an index of one line per lesson in the project's AGENTS.md, one file per lesson in the memory directory, and a git-ignored local folder for private or machine-specific lessons. Use when a lesson is proposed, approved, written, corrected, consolidated or removed, when a sprint's close proposes lessons, when the user asks to remember or record something for the project, to list or tidy the project's lessons, or says the lesson index is at its limit; and whenever the lesson index block of AGENTS.md or a file in the memory directory is created or edited.
compatibility: claude-code, codex
---

# Project memory

A project keeps what it learned as **lessons**, so that a later session, on either provider, does not learn it again. A lesson is a fact about this project that is in no other file: a trap, a check that would have caught a bug, a correction the user had to make twice.

```text
Propose -> the user approves -> Write -> Correct or Remove
```

**Nothing is written without the user's approval**, lesson by lesson. That holds for a new lesson, a correction, a consolidation and a removal, in the shared memory and in the local folder alike.

## The three places

| Place | Holds | Committed |
|-------|-------|-----------|
| The index: a marked block in the project's `AGENTS.md`, in the project root | One line per lesson. Both providers load it in every session | Yes |
| The memory directory | One file per lesson: what, why, when it applies, which roles | Yes |
| `local/` in the memory directory | Private or machine-specific lessons, with an index file of their own that one fixed line of the index points at | No: git-ignored |

## Read before you act

All files are in `references/` in this skill's directory.

| Read | When |
|------|------|
| [format.md](references/format.md) | Before creating or editing the index block, a lesson file, or anything in `local/` |
| [lifecycle.md](references/lifecycle.md) | Before proposing, writing, correcting, consolidating or removing a lesson; it says what is worth recording and what is not |
| [loading.md](references/loading.md) | When the index is first created in a project, when the project has or gains a `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` or `AGENTS.override.md`, and when a session does not know a lesson the index holds |

## Using the memory

- **The index is read with `AGENTS.md`.** A line says when its lesson applies. Before work a line applies to, read that lesson's file.
- **Both providers must load that `AGENTS.md`.** One of them stops reading it directly once the project has a `CLAUDE.md`, and on the other an `AGENTS.override.md` replaces it: [loading.md](references/loading.md) says when, and the two remedies.
- **The fixed last line of the index names the local index file.** Read that file when it exists, and its lessons in the same way.
- **A lesson that is wrong or stale is not worked around silently.** Say so, and propose its correction or removal as [lifecycle.md](references/lifecycle.md) says.

## The limit

The index holds at most **50 lines** of at most **150 characters** each. At 50 lines, a lesson is consolidated with another or retired before one is added. The check command of the `prd-implementation` skill reports an index over either limit.

## Settings

The skill reads one setting:

- `memory.dir` — **the memory directory**: a path relative to the project root and inside the project, `docs/memory` by default. With any other value, stop and report it ([format.md](references/format.md)).

Read it with `python scripts/settings.py memory --project <project root>`, the script being in this skill's directory. The project root is the main working tree of the project's repository, never a worktree made for a sprint.
