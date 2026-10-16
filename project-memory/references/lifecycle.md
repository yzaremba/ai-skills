# Lifecycle of a lesson

Read [format.md](format.md) for what is written and where. A lesson is **proposed**, **approved** by the user, **written**, and later **corrected**, **consolidated** or **removed**.

**Nothing is written without the user's approval**, lesson by lesson: no lesson file, no index line, no correction, no removal. An agent's own statement that a lesson was approved approves nothing; the user's words do.

## What is worth recording

A lesson earns its line when a later session would otherwise learn it again, at a cost:

- **Where the plan and the code drift apart in this repository**: a pattern, not one case. "PLAN steps here often miss timezone wrapping on a new timestamp surface."
- **Verification commands and their typical runtimes**, so that a hang is told from a slow run.
- **Schema or contract surfaces that must move together**: a schema shared by CI and a runtime loader, where a field change touches both.
- **A correction the user had to repeat.** Said twice, it is a lesson.

## What is not

- Anything the process text already says: propose a change to the process instead, which is the user's to accept.
- Anything the project's instruction file already says, outside the index.
- Anything the code says, or that `git log` or a sprint's own docs hold: what shipped, what a step did, how a bug was fixed.
- What held for one task only, and what is a guess. A lesson states something that was observed.

**"No lessons" is a fine outcome.** Do not manufacture one to have something to propose.

## Propose

- **When.** At a sprint's close, as the completion stage of the `prd-implementation` skill says: the candidates noted during the sprint and what the close itself showed. At any other time, when the user asks to record it, or when a session working with the user has just learned something worth recording.
- **A candidate is not a proposal.** Whoever notices something mid-work names it in a line, in its report, and goes on. Nobody is asked to find one: "none" is the normal report. It is proposed when the work that noticed it closes.
- **During a sprint the candidates are kept in its STATE file**, in the section "Lesson candidates": one line per candidate with the step it came from, recorded by the build lead whenever it writes STATE. At the close the lessons are proposed from it. A STATE written after the user has answered holds there only the approved lessons not yet written, each as `approved, to write: <lesson>`, so that a session picking up a stopped close loses no approval and proposes nothing again.
- **A proposal is one or two lines**: what happened, and what to do differently. It says whether the lesson is shared or local (private or true of this machine only), and for a local one whether the project's `.gitignore` needs its line.
- **Check it first** against the index and "What is not" above. A candidate that restates a lesson is dropped; one that sharpens a lesson is proposed as its correction.
- **At the limit, the proposal comes with its room**: the index holds 50 lines. When it is full, propose with the new lesson which two lessons are consolidated or which one is retired. The new lesson is written only after that is approved and done.
- The proposals are put to the user, and the answer to one is not an answer to another.

## Write

An approved lesson is written in one change:

1. **The lesson file**, in the memory directory, with all four parts.
2. **Its index line**, in the block of the project's `AGENTS.md`, above the fixed last line. For a local lesson the line goes in the local index file instead, and nothing in `AGENTS.md` changes.
3. **Check the limits**: at most 50 lines of at most 150 characters. Where the `prd-implementation` skill is installed, its check command reports both.

- **Who writes.** Whoever proposed it, when it may change files. A session that writes no file has the lesson written by one that does, and passes the user's words on with it: outside a sprint's build, by the one that keeps the backlog.
- **Where.** The index is in a file every branch shares, so a shared lesson is written on the default branch, in the working tree that has it checked out (if none has, ask the user), never in a worktree made for a sprint. A local lesson is written in the project root, where its folder is.
- **The commit** of a shared lesson is the user's decision, like any other. At a sprint's close the lessons are written with the archive change, as the completion stage of the `prd-implementation` skill says. A local lesson is never committed.

## Correct

A lesson that proved wrong, too wide or stale is corrected, not worked around. Propose the correction in a line: what the lesson says, and what is true. On approval, overwrite the text of its file, change its `Recorded` date, and change its index line if what it says or when it applies changed. One change.

## Consolidate

Two lessons that say one thing, or that always apply together, become one: one file that holds both, one index line, and the other file deleted. It is proposed and approved like any other change, and it is how room is made at the limit when no lesson has stopped being true.

## Remove

A lesson is retired when it no longer holds: the code it warned about is gone, the tool changed, or a file now says it. Propose it in a line with the reason. On approval, delete its file and its index line in one change. Nothing is marked "retired" and kept: `git log` has it.

The fixed last line of the index and the two markers are never removed.
