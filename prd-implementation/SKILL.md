---
name: prd-implementation
description: Staged sprint process with explicit gates, from backlog through THOUGHTS, PRD, PLAN and TASKS to implementation and archiving. Use when the user asks to start, brainstorm, plan or implement a sprint, to write or finalize a PRD, to work through sprint steps such as P1.2, to close, merge or archive a sprint, to abandon or supersede a sprint, to add a backlog item, or to defer work or check, resolve, re-date or drop deferred items; and whenever a sprint doc is read, created, renamed or edited - SPRINTNN-THOUGHTS-slug.md, SPRINTNN-PRD-slug.md, SPRINTNN-PLAN-slug.md, SPRINTNN-TASKS-slug.md, SPRINTNN-STATE-slug.md, HOTFIX-STATE-slug.md, SPRINT-INDEX.md, BACKLOG.md, BACKLOG/BN-slug.md, BACKLOG-BN-slug.md, DEFERRED.md, DEFERRED-context.md or DONE/README.md.
compatibility: claude-code, codex
---

# PRD Implementation Workflow (sprint docs)

When the user asks to brainstorm, plan, or implement a sprint, follow this flow. Work proceeds in **stages with explicit gates**; do not skip ahead without confirmation at each gate.

```text
Backlog -> THOUGHTS -> PRD -> PLAN + TASKS -> Implementation -> Completion
```

A sprint may stand alone or belong to a larger multi-sprint **epic** (the `epic-implementation` skill). When it does, tag its THOUGHTS header with `Epic: NN`. That line is the only coupling; the rest of this flow is unchanged.

The sprint delivers the user's stated outcome and nothing beyond it: "The outcome, and nothing beyond it" in [references/conventions.md](references/conventions.md) holds in every stage.

## Read before you act

- **Before acting in a stage, read that stage's file** from the table below, in full. This file is only the map: the rules are in the stage files, and they are worded to stop mistakes that keep recurring. Do not act on a stage from memory of an earlier read in another session.
- **Before creating, renaming or editing any sprint doc, read [references/conventions.md](references/conventions.md).** It holds the sprint docs directory, sprint numbering and the index, file naming, which docs are linked and which only named, where each doc is written, the task lifecycle, TASKS-line discipline, the format limits, "Last updated" hygiene, that no doc records an approval, and how questions are put to the user. They apply in every stage.
- When a gate opens, read the next stage's file before doing anything in it.
- **Picking up a sprint that is being implemented, read its STATE file first** (`SPRINTNN-STATE-slug.md`), then compare it with git as [references/state.md](references/state.md) says. A mismatch goes to the user; it is never resolved silently.

## Stages and their files

All files are in `references/` in this skill's directory.

| Stage | Read | When |
|-------|------|------|
| All stages | [conventions.md](references/conventions.md) | Before creating, renaming or editing any sprint doc |
| 0. Backlog | [stage-0-backlog.md](references/stage-0-backlog.md) | An idea, bug or wish is captured outside a sprint; `BACKLOG.md` is read or edited; a sprint is about to start |
| 0. Backlog | [backlog-conversion.md](references/backlog-conversion.md) | The user agrees to convert a `BACKLOG.md` in the old form, or to move item documents out of their earlier place |
| 1. THOUGHTS | [stage-1-thoughts.md](references/stage-1-thoughts.md) | Starting or brainstorming a sprint |
| 2. PRD | [stage-2-prd.md](references/stage-2-prd.md) | The user confirms THOUGHTS are ready to become requirements |
| 3. PLAN + TASKS | [stage-3-plan-tasks.md](references/stage-3-plan-tasks.md) | The user says the PRD is final, e.g. "PRD is good" or "generate PLAN and TASKS" |
| 3. Implementation | [stage-3-implementation.md](references/stage-3-implementation.md) | The user asks to implement a sprint, a phase or a step, e.g. "implement" or "do P1.2" |
| 3. Implementation | [state.md](references/state.md) | Picking up a sprint in progress, or a hotfix with a `HOTFIX-STATE-*.md`; before a step starts, after it closes, before any stop |
| Completion | [completion.md](references/completion.md) | No TASKS checkbox is open, or the user asks to close, merge or archive a sprint; lessons are proposed at any close |
| Abandon, supersede | [abandon.md](references/abandon.md) | A sprint will not finish, at any stage: the user drops it or replaces it with another |
| Deferred items | [deferred.md](references/deferred.md) | A sprint's only open steps wait on time or an outside event; the user defers work outside a sprint; `DEFERRED.md` is read or edited; deferred items or the format limits are checked, with `scripts/check.py` |
| Deferred items | [deferred-conversion.md](references/deferred-conversion.md) | The user agrees to convert a `DEFERRED.md` in the old form |

## Gates

Each gate needs the user's explicit signal, and no sprint doc records it. An agent's own statement, and your own judgment that a doc looks ready, do not open a gate. A change to a document's substance after its gate opened is a new change, put to the user; a status line, a "Last updated" line or a link is not substance. Where roles are installed, the roles' gate rules say when the user's words said to a role, or quoted by one, count. A question put at a gate follows the settings below.

| Before | The user must have |
|--------|--------------------|
| Starting a sprint (the THOUGHTS file) | Said which backlog items to pluck, or that the theme comes from outside the backlog. This also authorizes the one local commit of the changes that belong to starting it, listed in [conventions.md](references/conventions.md): only those files, committed by name, and no other commit |
| Writing the PRD | Confirmed that THOUGHTS are ready to turn into requirements |
| Creating PLAN or TASKS | Said the PRD is final enough to proceed |
| Writing any code | Given the word to implement, with the implementation choices. That word is the gate. The summary of the choices is printed before any code, and the session proceeds without waiting for a reply: the summary is the user's chance to stop it |
| Each later commit | Before implementation: said so, for that commit. During implementation: chosen a commit cadence other than "don't commit". The cadence authorizes the build lead's commits on the sprint's branch and the one commit of each member of a parallel group |
| Closing a sprint as code-complete; abandoning or superseding a sprint; resolving, re-dating or dropping a deferred item | Decided it. Each is put to them; none is settled for them |
| Closing a sprint: the Ready commit, the merge to the default branch, the full suite there, the removal of the merged worktree and branch, the archive change and its commit | Said to close it, finished or, as decided above, code-complete. That one word covers the whole close, which stops only on trouble: a merge conflict, a failing suite, a removal that needs force |
| Any push; removing unmerged work | Authorized that action. Each is a separate decision, and neither the commit cadence nor the word to close covers it |
| Writing a lesson, to the project memory or as a change to the process | Approved that lesson |

## Who does what

The text speaks of three parts, and names no agent:

- **The build lead** runs a sprint's implementation: resolves the choices with the user, hands each unit to the implementer, runs the independent review, commits, and keeps STATE.
- **The implementer** writes the code for a step, verifies it, and moves its TASKS checkbox. The implementer does not commit, with one exception: as a member of a parallel group it makes exactly one commit, in its own worktree.
- **An independent review** is an adversarial pass over the code just written, by a reviewer who did not write it.

One session may be all three, and the process works that way. When the parts are separate sessions, each keeps to its own part.

A move, rename or deletion of a whole file by the `git mv`, `git rm`, `mv` or `rm` a stage file gives, with creating the folder it names, needs no judgement: on the user's word, a session other than the one that keeps the doc may run it. A doc's text, and any step that needs judgement, stays with whoever keeps the doc.

## Provider differences

The stage files describe actions and name no tool. How a question is put to the user, how an independent review is run, and how work reaches an implementer differ by provider: read [references/claude-code.md](references/claude-code.md) on Claude Code or [references/codex.md](references/codex.md) on Codex, once, before the first of those actions.

## Settings

The process reads four settings, all in the `process` group:

- `process.docs_dir` — **the sprint docs directory**, which is what the stage files call it: a path relative to the project root, `docs/` by default.
- `process.questions` — `all-together` (default) or `one-at-a-time`: how open questions are put to the user.
- `process.recommend` — `true` (default): each question comes with a recommendation; `false`: the options only; `accept`: a clear choice is taken for the user and listed at the next stop.
- `process.density` — `brief` (default) or `full`: how much a question and a report say.

Read them with `python scripts/settings.py process --project <project root>`, the script being in this skill's directory. The project root is the main working tree of the project's repository, never a sprint's or a group member's worktree. [references/conventions.md](references/conventions.md) says what each means.
