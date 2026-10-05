---
name: epic-implementation
description: Staged process with explicit gates for an epic, a large effort spanning several sprints toward one outcome - from backlog through EPIC THOUGHTS and the EPIC PRD (charter) to the EPIC ROADMAP, its sprints and archiving. Use when the user asks to brainstorm, plan or run an epic or a multi-sprint effort, to write or finalize an epic charter, to decompose an epic into sprints, to start a sprint from a roadmap, or to close, abandon or archive an epic; and whenever an epic doc is read, created, renamed or edited - EPICNN-THOUGHTS-slug.md, EPICNN-PRD-slug.md, EPICNN-ROADMAP-slug.md or EPIC-INDEX.md.
compatibility: claude-code, codex
---

# EPIC Workflow (multi-sprint efforts)

When the user asks to brainstorm, plan, or run an **epic** — a large effort spanning several sprints toward one outcome — follow this flow. Work proceeds in **stages with explicit gates**; do not skip ahead without confirmation at each gate.

```text
Backlog -> EPIC THOUGHTS -> EPIC PRD (charter) -> EPIC ROADMAP -> sprints -> Completion
```

This skill sits **above** the sprint workflow, the `prd-implementation` skill. An epic is a *container + roadmap*, not a bigger PRD: capture the vision and success criteria once, then decompose the work into ordinary sprints. Each sprint runs the full `prd-implementation` flow (THOUGHTS → PRD → PLAN → TASKS → Implementation), tagged with its parent epic. **Keep the epic layer thin** — granular how/checklist lives in each sprint's PLAN/TASKS and is never duplicated here.

## Read before you act

- **Before acting in a stage, read that stage's file** from the table below, in full. This file is only the map: the rules are in the stage files, and they are worded to stop mistakes that keep recurring. Do not act on a stage from memory of an earlier read in another session.
- **Before creating, renaming or editing any epic doc, read [references/conventions.md](references/conventions.md).** It holds the epic docs directory, the hierarchy, epic numbering and the index, file naming, slug rules, ROADMAP maintenance, the epic status vocab, traceability, "Last updated" hygiene, where each doc is written and how questions are put to the user. They apply in every stage.
- When a gate opens, read the next stage's file before doing anything in it.
- A sprint of an epic is run with the `prd-implementation` skill. Read that skill before creating or editing a sprint doc; this one covers only the epic's own three docs and the ROADMAP row of each sprint.

## Stages and their files

All files are in `references/` in this skill's directory.

| Stage | Read | When |
|-------|------|------|
| All stages | [conventions.md](references/conventions.md) | Before creating, renaming or editing any epic doc |
| E0. Backlog | [stage-e0-backlog.md](references/stage-e0-backlog.md) | An epic-scale idea is captured; an epic is about to start |
| E1. EPIC THOUGHTS | [stage-e1-thoughts.md](references/stage-e1-thoughts.md) | Starting or brainstorming an epic |
| E2. EPIC PRD (charter) | [stage-e2-charter.md](references/stage-e2-charter.md) | The user confirms the brainstorm is ready to become a charter |
| E3. EPIC ROADMAP | [stage-e3-roadmap.md](references/stage-e3-roadmap.md) | The user says the charter is final, e.g. "charter is good" or "generate the roadmap"; and whenever a roadmap sprint is started, moves, is added or is cut |
| Completion | [completion.md](references/completion.md) | Every ROADMAP row is `Done` or `Skipped`, or the user asks to close, abandon or archive an epic |

## Gates

Each gate needs the user's explicit signal. An agent's own statement, and your own judgment that a doc looks ready, do not open a gate. Where roles are installed, the roles' gate rules say when the user's words quoted by a role count. A question put at a gate follows the settings below.

| Before | The user must have |
|--------|--------------------|
| Starting an epic (the EPIC THOUGHTS file) | Given an explicit signal that the effort is epic-sized (multi-sprint) |
| Writing the EPIC PRD (the charter) | Confirmed that the brainstorm is ready to become a charter |
| Creating the ROADMAP | Signalled that the charter is final |
| Creating a roadmap sprint's docs | Started that sprint; from there the gates of the `prd-implementation` skill apply |
| Abandoning an epic | Decided it. It is put to them; it is never settled for them |
| Moving the epic set to the archive | Agreed to the offer |

## Who does what

The text names no agent. An epic's stages are work on three docs, and whoever writes a doc follows its stage file; that includes the critical pass over a draft charter. The build lead, the implementer and an independent review belong to a sprint's implementation and are defined in the `prd-implementation` skill. One session may run a whole epic, and the process works that way.

## Provider differences

The stage files describe actions and name no tool, and nothing in them differs by provider, so this skill has no provider files. Where a question is put to the user or a review is run, the provider notes of the `prd-implementation` skill apply.

## Settings

The process reads three settings, all in the `process` group, the same ones the `prd-implementation` skill reads:

- `process.docs_dir` — **the epic docs directory**, which is what the stage files call it. It is the sprint docs directory: a path relative to the project root, `docs/` by default.
- `process.questions` — `one-at-a-time` (default) or `all-together`: how open questions are put to the user.
- `process.recommend` — `true` (default): each question comes with a recommendation.

Read them with `python scripts/settings.py process --project <project root>`, the script being in this skill's directory. The project root is the main working tree of the project's repository, never a sprint's or a group member's worktree. [references/conventions.md](references/conventions.md) says what each means.
