# Stage 3 — PLAN and TASKS

Read [conventions.md](conventions.md) before creating the files. This stage starts only after the user has explicitly signalled that the PRD is final enough to proceed. Executing the plan is the second half of this stage: [stage-3-implementation.md](stage-3-implementation.md).

- **Explore the codebase** before writing the plan so steps reference real paths and patterns.
- Create `SPRINTXX-PLAN-<Description>.md` and `SPRINTXX-TASKS-<Description>.md`, in the sprint's worktree or branch, where the PRD was written.
- Cross-link **PRD, PLAN, and TASKS** in each file's header (and link back to THOUGHTS where useful for traceability).

## PLAN file structure

- **Header**: title, links to THOUGHTS, PRD, TASKS, status, last-updated date. The status line is `**Status:** In progress` from the first draft until the close sets it ([completion.md](completion.md), "Integration", step 1; [abandon.md](abandon.md)); a close that goes back to the build sets it back to `In progress`. No approval is written in it: a gate passes by the user's word, not by the file. A change of status does not bump `Last updated:`.
- **Phases**: logical groups (e.g. data, logic, API, UI)
- **Steps**: unique IDs `P<phase>.<step>` where `<phase>` and `<step>` are **integers** (e.g. `P1.1`, `P3.4`). Do **not** use letters or words for `<phase>` (no `PA.1`, `PWATCHDOG.1`) — phases can still be *named* conceptually in the heading (e.g. "Phase 2 — API"), but the ID is always numeric.
- **Step content**: what to do, files to touch, snippets or SQL if helpful, edge cases; use `> Depends on: P1.2` when order matters
- **Marks**: `> Parallel: <letter>`, `> Tag: light` and `> Tag: hard`, optional, as "Marks on a step" below says
- **External-contract steps**: cite the primary source and verification date; pin applicable endpoint/version, auth, transfer/pagination, schema and failure behavior. Require provider-derived evidence—a safe smoke, authorized live probe, or verified current fixture—before readiness; hand-written fakes prove only local behavior. If unavailable, mark the gap and gate rollout.
- **Cross-cutting concerns**: transactions, errors, performance, etc.

## Marks on a step

A step may carry three optional marks besides `> Depends on:`. Each is a blockquote line of its own, directly under the step's heading. **A step with no mark is serial and gets a fresh implementer**: it runs alone, in order, with an implementer that has done no other step. How the marks are acted on is in [stage-3-implementation.md](stage-3-implementation.md).

- **`> Parallel: <letter>`** — one capital letter. Steps of one phase that carry the same letter are a **group** and may run at the same time.
  - A group holds steps of **one phase only**. The same letter in another phase is another group.
  - **At most three** of its steps run at a time. A larger group is allowed; its other steps wait their turn.
  - Marking a group is a **positive claim by the PLAN's author** that its steps touch separate files and do not depend on each other. Make it only after checking both. A missing mark costs speed; a wrong one costs a merge conflict and a step done twice.
- **`> Tag: light`** — the step may share an implementer with the light steps next to it. Such a **light run** is sequential, stays within one phase, holds about five steps at most, and ends at any failure or review finding.
- **`> Tag: hard`** — the step asks for the stronger implementer. `hard` is for concurrency, a schema or contract change, a migration or a money path, and for nothing else.

How they combine:

- **`> Depends on:` stays the only ordering relation**, and it holds whatever else a step carries. No step of a group depends on another step of the same group, directly or through other steps. A group starts when every dependency of every one of its steps is `[x]`, and a step that depends on a step of a group waits until the whole group has joined.
- **A step carries at most one `Tag`**: `light` or `hard`, never both.
- **A step may carry `Parallel` and a `Tag`.** `Parallel` with `hard`: that step of the group gets the stronger implementer. `Parallel` with `light`: each step of a running group has an implementer of its own, so `light` takes effect only when the group runs serially.
- The marks are in the PLAN. A TASKS line repeats one of them, `hard` ("TASKS file structure" below), and no other. The PLAN is the source: whoever adds or removes a step's `> Tag: hard` changes that step's TASKS line in the same change.

Example, headings and marks only: P2.2 and P2.3 are group A, P2.4 waits for the group, and P2.5 and P2.6 may share one implementer.

```markdown
### P2.2 — Add the `trade_notes` table and its migration

> Depends on: P2.1
> Parallel: A
> Tag: hard

### P2.3 — Add a notes panel to the trade screen

> Depends on: P2.1
> Parallel: A

### P2.4 — Load and save notes from the panel

> Depends on: P2.2, P2.3

### P2.5 — Add the notes strings to both locale files

> Tag: light

### P2.6 — Document the notes endpoint in the API reference

> Tag: light
```

## TASKS file structure

- **Header**: title, links to PLAN, PRD, THOUGHTS, last-updated date
- **Grouped by phase**, matching PLAN
- Each line: `- [ ] **P1.1** — short description` (bold ID matches PLAN), at most 150 characters
- A step that carries `> Tag: hard` shows it directly after the ID: `- [ ] **P1.1** **[hard]** — short description`. The tag counts toward the 150 characters. Every other step's line has no tag: `light` and `Parallel` are not shown.

The task lifecycle, TASKS-line discipline, the format limits and "Last updated" hygiene are in [conventions.md](conventions.md). They apply from the first line written here: a new TASKS line is short, and it stays that way.

## Example (PLAN step and TASKS line)

PLAN:

```markdown
### P2.3 — Add `getTradesByPosition()` to `MariaDbTradeRepositoryApi`

> Depends on: P2.1

In `trading_assistant_api/lib/src/repositories/mariadb_repositories.dart`:
- New method returning trades for a given accountId + symbol, ordered by trade_date ASC

### P2.4 — Add the `position_id` column to `trades` and its migration

> Depends on: P2.1
> Tag: hard
```

TASKS:

```markdown
- [ ] **P2.3** — Add `getTradesByPosition()` to `MariaDbTradeRepositoryApi`
- [ ] **P2.4** **[hard]** — Add the `position_id` column to `trades` and its migration
```

After done: `- [x] **P2.3** — …` and `- [x] **P2.4** **[hard]** — …`

Next: [stage-3-implementation.md](stage-3-implementation.md), when the user asks to implement.
