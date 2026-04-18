---
paths:
  - docs/SPRINT*-*.md
  - docs/SPRINT-INDEX.md
---

# PRD Implementation Workflow (Sprint docs)

When the user asks to brainstorm, plan, or implement sprint documentation, follow this flow. Work proceeds in **stages with explicit gates** (Backlog → THOUGHTS → PRD → PLAN + TASKS); do not skip ahead without confirmation at each gate.

## Sprint numbering (`docs/SPRINT-INDEX.md`)

- **`docs/SPRINT-INDEX.md` is the preferred source** for which two-digit sprint number `NN` to use next. Read it before creating a new sprint set.
- If the index is missing, outdated, or contradicts filenames, **reconcile**: set **Latest assigned sprint `NN`** to the maximum `NN` appearing in any `SPRINTNN-*` file under `docs/` and `docs/DONE/`, then use `NN + 1` (two digits) for a **brand-new** sprint. After creating the first file of a new sprint, update the index.
- If the index is absent, create it when starting or tidying sprint docs.

## File naming

All related files for one sprint feature use this pattern:

`docs/SPRINTXX-<TYPE>-<Description>.md`

- **SPRINTXX** — two-digit sprint number (`01`, `02`, …). Take `NN` from **SPRINT-INDEX** (see above); only fall back to scanning `docs/` and `docs/DONE/` if needed.
- **TYPE** — one of: `THOUGHTS`, `PRD`, `PLAN`, `TASKS` (uppercase as shown).
- **Description** — short kebab-case slug; **use the same slug** for every file in the set so they group together (e.g. `mobile-layout`). It should match the **Slug** line in THOUGHTS (normalize casing to kebab-case).

Examples: `docs/SPRINT01-THOUGHTS-mobile-layout.md`, `docs/SPRINT01-PRD-mobile-layout.md`.

Legacy files matching `docs/PRD-*.md` without a sprint prefix may still exist; prefer the sprint pattern for new work.

## Stage 0 — BACKLOG (`docs/BACKLOG.md`)

- `docs/BACKLOG.md` is a persistent, free-form **dumping ground** for ideas, bug reports, and wishlist items captured outside any active sprint. It is **not** sprint-scoped.
- Content is **intentionally unstructured**: bullets, one-liners, half-thoughts. Optional grouping under headers (e.g. `## Bugs`, `## Features`, `## UX`) is fine but not required — do not impose structure the user did not ask for.
- Create the file if it does not exist the first time an item needs to be added.
- **Starting a new sprint:** the user picks one or more items from `BACKLOG.md` that form a coherent theme. Those items seed the new `SPRINTXX-THOUGHTS-<slug>.md` (Stage 1). **Delete** the plucked items from `BACKLOG.md` in the same change — traceability lives in the new THOUGHTS file, which should quote or paraphrase the original idea.
- Items not yet picked up stay in `BACKLOG.md` indefinitely. No expiry, no priority field — keep it lightweight.
- **Gate:** Do not start a sprint (THOUGHTS file) without an explicit user signal about which backlog items to pluck, or explicit direction that the sprint theme comes from outside the backlog.

## Stage 1 — THOUGHTS (brainstorm)

- THOUGHTS for a new sprint typically starts by plucking items from `docs/BACKLOG.md` (Stage 0). The plucked items should be **deleted from the backlog** as part of the same change that creates this file.
- The user may create `SPRINTXX-THOUGHTS-<Description>.md` themselves or ask you to create it.
- Put these two lines at the **top** of the file (before freeform notes), then a blank line:
  - `Sprint: NN` (match the filename’s sprint)
  - `Slug: <kebab-case-slug>` (must match the `<Description>` segment in all four filenames)
- Content below is **intentionally unstructured**: bullets, questions, rough ideas, unordered notes. No need for full sections or IDs.
- **Gate:** Before writing a PRD, **confirm with the user** that THOUGHTS are ready to turn into requirements. If they want more brainstorming, stay in this stage.

## Stage 2 — PRD

- After confirmation, create `SPRINTXX-PRD-<Description>.md` from THOUGHTS (and any verbal direction). Cross-link THOUGHTS and PRD in headers.
- Include a **Non-goals** section (short bullet list): explicit **out of scope** items to limit scope creep before PLAN/TASKS. Keep it concrete (what we are *not* doing in this sprint).
- The user reviews and edits the PRD until they are satisfied.
- **Gate:** Do **not** create PLAN or TASKS until the user explicitly signals the PRD is final enough to proceed (e.g. “PRD is good” / “generate PLAN and TASKS”).

## Stage 3 — PLAN and TASKS

- **Explore the codebase** before writing the plan so steps reference real paths and patterns.
- Create `SPRINTXX-PLAN-<Description>.md` and `SPRINTXX-TASKS-<Description>.md`.
- Cross-link **PRD, PLAN, and TASKS** in each file’s header (and link back to THOUGHTS where useful for traceability).

### PLAN file structure

- **Header**: title, links to THOUGHTS, PRD, TASKS, status, last-updated date
- **Phases**: logical groups (e.g. data, logic, API, UI)
- **Steps**: unique IDs `P<phase>.<step>` (e.g. `P1.1`, `P3.4`)
- **Step content**: what to do, files to touch, snippets or SQL if helpful, edge cases; use `> Depends on: P1.2` when order matters
- **Cross-cutting concerns**: transactions, errors, performance, etc.

### TASKS file structure

- **Header**: title, links to PLAN, PRD, THOUGHTS, last-updated date
- **Grouped by phase**, matching PLAN
- Each line: `- [ ] **P1.1** — short description` (bold ID matches PLAN)

### Task lifecycle

- **Not started**: `- [ ]`
- **In progress**: `- [~]`
- **Done**: `- [x]`
- **Skipped**: `- [x] ~~**P2.5** — …~~ (skipped: reason)`
- New steps discovered during implementation: add to **both** PLAN and TASKS with the next ID in that phase; bump PLAN “Last Updated”
- After bug fixes on completed steps: add `> Bug fix YYYY-MM-DD: …` on the PLAN step; if the PRD requirement changed, update the PRD header/date

## Completion and archiving

When **all TASKS checkboxes** are resolved (no `- [ ]` or `- [~]`):

1. **Offer** to move the sprint set to `docs/DONE/`: THOUGHTS, PRD, PLAN, TASKS (same filenames).
2. After the user agrees, move those files and update `docs/DONE/README.md` with one row for the feature. Ensure **`docs/SPRINT-INDEX.md`** still reflects the highest `NN` in use (it should match the archived sprint unless newer sprints exist in `docs/`).

### `docs/DONE/README.md` format

Create the file if missing. Use a table that includes THOUGHTS:

```markdown
# Completed features (sprints)

| Sprint | Feature | THOUGHTS | PRD | Plan | Tasks | Completed |
|--------|---------|----------|-----|------|-------|-----------|
| 01 | Short name | [THOUGHTS](SPRINT01-THOUGHTS-slug.md) | [PRD](SPRINT01-PRD-slug.md) | [PLAN](SPRINT01-PLAN-slug.md) | [TASKS](SPRINT01-TASKS-slug.md) | YYYY-MM-DD |
```

## Example (PLAN step and TASKS line)

PLAN:

```markdown
### P2.3 — Add `getTradesByPosition()` to `MariaDbTradeRepositoryApi`

> Depends on: P2.1

In `trading_assistant_api/lib/src/repositories/mariadb_repositories.dart`:
- New method returning trades for a given accountId + symbol, ordered by trade_date ASC
```

TASKS:

```markdown
- [ ] **P2.3** — Add `getTradesByPosition()` to `MariaDbTradeRepositoryApi`
```

After done: `- [x] **P2.3** — …`
