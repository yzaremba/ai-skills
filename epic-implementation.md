---
paths:
  - docs/EPIC*-*.md
  - docs/EPIC-INDEX.md
---

# EPIC Workflow (multi-sprint efforts)

When the user asks to brainstorm, plan, or run an **epic** — a large effort spanning several sprints toward one outcome — follow this flow. Work proceeds in **stages with explicit gates** (Backlog → EPIC THOUGHTS → EPIC PRD → EPIC ROADMAP → sprints); do not skip ahead without confirmation at each gate.

This rule sits **above** the sprint workflow in `prd-implementation.md`. An epic is a *container + roadmap*, not a bigger PRD: capture the vision and success criteria once, then decompose the work into ordinary sprints. Each sprint runs the full `prd-implementation.md` flow (THOUGHTS → PRD → PLAN → TASKS), tagged with its parent epic. **Keep the epic layer thin** — granular how/checklist lives in each sprint's PLAN/TASKS and is never duplicated here.

## Hierarchy at a glance

| Level | Artifacts | Granularity |
|-------|-----------|-------------|
| **Epic** (this rule) | `EPICXX-THOUGHTS` / `PRD` / `ROADMAP` | one outcome, many sprints |
| Sprint (`prd-implementation.md`) | `SPRINTXX-THOUGHTS` / `PRD` / `PLAN` / `TASKS` | one feature, ~one sprint |
| Task | `- [ ]` line in a sprint's TASKS | one work item |

## Epic numbering (`docs/EPIC-INDEX.md`)

- **`docs/EPIC-INDEX.md` is the preferred source** for which two-digit epic number `NN` to use next. Read it before creating a new epic set. It is **separate** from `docs/SPRINT-INDEX.md`.
- If the index is missing, outdated, or contradicts filenames, **reconcile**: set **Latest assigned epic `NN`** to the maximum `NN` in any `EPICNN-*` file under `docs/` and `docs/DONE/`, then use `NN + 1` (two digits) for a brand-new epic. Update the index after creating the first file of a new epic.
- If absent, create it when starting or tidying epic docs.
- **Sprints keep their own global numbering** via `docs/SPRINT-INDEX.md`. An epic does **not** renumber sprints — it *claims* sprint numbers as its roadmap sprints are created (recorded in the ROADMAP). A sprint belongs to **at most one** epic.
- **Slugs are the durable cross-reference; sprint numbers are late-bound.** Inside an epic, planned sprints are identified by **slug**, never by a pre-assigned number. A sprint's global two-digit number is assigned **only when the sprint is actually created** (`SPRINT-INDEX.md` max+1) and written into its ROADMAP row at that moment — until then the row's `Sprint` cell is `TBD`. This is deliberate: a number written before the sprint exists is **not** reserved, so a parallel sprint or epic would grab it via the same max+1 rule and silently invalidate the reference. A slug, by contrast, is recorded in the ROADMAP the moment the sprint is planned, so it *is* a real reservation.

## File naming

All files for one epic use:

`docs/EPICXX-<TYPE>-<Description>.md`

- **EPICXX** — two-digit epic number (`01`, `02`, …) from EPIC-INDEX.
- **TYPE** — one of `THOUGHTS`, `PRD`, `ROADMAP` (uppercase).
- **Description** — short kebab-case slug; **same slug** for all three files; matches the **Slug** line in EPIC THOUGHTS.

Examples: `docs/EPIC01-THOUGHTS-payments-platform.md`, `docs/EPIC01-ROADMAP-payments-platform.md`.

### Slug uniqueness

Because slugs are the durable cross-reference (above), they must not be ambiguous — but the scope that's **enforced** is local, not global:

- **Enforced (hard rule):** a sprint slug is unique **within its epic** (the ROADMAP's `Slug` column) and **within its sprint set** (per `prd-implementation.md`). Both are *local* checks — you only inspect rows/files you already have open, no repo-wide scan. Within-epic uniqueness is what makes `Depends on`-by-slug unambiguous; that's all the resolution mechanism needs.
- **Convention (not enforced):** keep slugs distinct across the whole repo by **domain-qualifying generic names** — `payments-dashboard`, not bare `dashboard`; `billing-data-model`, not bare `data-model`. Filenames already disambiguate by sprint number (`SPRINT07-…-dashboard.md` ≠ `SPRINT21-…-dashboard.md`), so duplicates never collide on disk — this is purely for human discoverability in the flat `docs/`.
- **Carve-out:** only when you must use a genuinely generic slug, do a quick `docs/*-<slug>.md` scan first. Distinctive, domain-qualified slugs don't need it.

## Stage E0 — Promote from BACKLOG

- Epic-scale ideas live in the shared `docs/BACKLOG.md` (the same backlog the sprint workflow uses — there is no separate epic backlog).
- **Starting an epic:** the user picks one or more backlog items that together form a multi-sprint theme. Those items seed `EPICXX-THOUGHTS-<slug>.md`. **Delete** the plucked items from `BACKLOG.md` in the same change — traceability lives in the new THOUGHTS file, which should quote or paraphrase the original idea.
- **Gate:** Do not start an epic without an explicit signal that the effort is **epic-sized** (multi-sprint). If it fits one sprint, use `prd-implementation.md` instead.

## Stage E1 — EPIC THOUGHTS (brainstorm)

- The user may create `EPICXX-THOUGHTS-<Description>.md` themselves or ask you to. Put these lines at the **top** (before freeform notes), then a blank line:
  - `Epic: NN` (match the filename)
  - `Slug: <kebab-case-slug>` (must match the `<Description>` segment in all three filenames)
- Content below is **intentionally unstructured**: the problem, rough scope, candidate sprints, sequencing hunches, open questions, risks.
- **Gate:** Before writing the PRD, **confirm** the brainstorm is ready to become a charter. Stay here if more brainstorming is wanted.

## Stage E2 — EPIC PRD (charter)

After confirmation, create `EPICXX-PRD-<Description>.md` from THOUGHTS (and verbal direction). Cross-link THOUGHTS ↔ PRD in headers. The charter stays **high-altitude** — sections:

- **Vision / problem** — why this epic exists and the outcome it drives.
- **Success criteria** — measurable; this is the epic's **definition of done** (how you know the whole effort is complete).
- **In scope** — the major capabilities/features included.
- **Non-goals** — explicit out-of-scope items, to limit creep across the whole effort.
- **Risks / assumptions / dependencies** — for a multi-sprint effort these matter; note cross-sprint ordering constraints.
- **Rough sequencing** — narrative of the intended phasing, referring to sprints by **slug / feature name, not number** (numbers aren't assigned until each sprint is created, so a number written here would go stale). The detailed sprint table belongs in the ROADMAP, not here.

The user reviews and edits until satisfied. **Gate:** Do **not** create the ROADMAP until the user signals the charter is final (e.g. "charter is good" / "generate the roadmap").

## Stage E3 — EPIC ROADMAP (decompose into sprints)

- **Explore the codebase** before decomposing so the sprint breakdown references real areas and dependencies.
- Create `EPICXX-ROADMAP-<Description>.md`. Cross-link THOUGHTS, PRD, ROADMAP in the header.
- The ROADMAP is the epic's **living tracker** — it replaces PLAN+TASKS at this altitude. Update it as sprints are created and land.

### ROADMAP file structure

- **Header**: title, links to THOUGHTS + PRD, **Epic status** (see vocab below), last-updated date.
- **Sprint table** — one row per constituent sprint:

```markdown
| Sprint | Slug | Feature | Status | Depends on | Docs |
|--------|------|---------|--------|-----------|------|
| 07 | data-model | Core schema | Done | — | [docs](SPRINT07-PRD-data-model.md) |
| 08 | ingest-api | Ingestion API | In progress | data-model | [docs](SPRINT08-PRD-ingest-api.md) |
| TBD | dashboard | Read UI | Planned | ingest-api | — |
```

- **Sprint** — the global two-digit sprint number, filled in **only once the sprint is created** (`SPRINT-INDEX.md` max+1); `TBD` while the row is still `Planned`. Never pre-assign — see "Slugs are the durable cross-reference" under Epic numbering.
- **Slug** — the sprint's kebab-case slug, chosen when the row is planned and **reused verbatim** as the `<Description>` when the sprint is created. This is the row's stable identity across renumbering.
- **Feature** — *optional* column; use only when one deliverable spans more than one sprint (group those rows). Drop the column if it's one feature per sprint.
- **Status** — `Planned` / `In progress` / `Done` / `Skipped`.
- **Depends on** — **slugs** (not numbers) of sprints that must land first. Slugs are stable; numbers may still be `TBD`, and a number could be reassigned out from under the reference.
- **Docs** — link to the sprint set once it exists; `—` while still planned.
- **Sequencing & dependencies**: a short narrative below the table if the dependency graph isn't obvious from the column.

### The seam — handing off to the sprint workflow

When the user starts one of the roadmap's sprints:

1. Create the `SPRINTXX-*` set per `prd-implementation.md`, taking `XX` from `docs/SPRINT-INDEX.md` (global numbering) and **reusing the ROADMAP row's slug verbatim** as the `<Description>`. This is the moment the number is assigned — not before.
2. Add `Epic: NN` to that sprint's **THOUGHTS header** (alongside `Sprint:` / `Slug:`) — the up-link.
3. Fill the now-assigned sprint number + Docs link into the ROADMAP row, and flip its **Status** as the sprint moves (`Planned → In progress → Done`).

From there the sprint runs entirely under `prd-implementation.md`. This rule does **not** duplicate that flow.

### ROADMAP maintenance

- **Rows stay short** — only `Status` and `Docs` change over time; don't append narrative to a row. Per-sprint detail lives in that sprint's docs; cross-sprint context goes in the PRD or a `> Note YYYY-MM-DD: …` annotation under the table.
- **Scope changes**: adding a sprint = add a row (+ note); cutting one = set `Status: Skipped` with a one-line reason — don't delete the row (traceability).
- **"Last updated" hygiene**: `**Last updated:** YYYY-MM-DD — <≤2-line summary of this rev>`. No running history — git log carries that. Same rule for THOUGHTS/PRD headers.

## Epic status vocab (ROADMAP header)

- **Proposed** — charter/roadmap drafted, no sprint started.
- **Active** — at least one sprint in progress.
- **On hold** — paused; note why.
- **Done** — all rows `Done`/`Skipped` and success criteria met.
- **Abandoned** — dropped; note why.

## Traceability (both directions)

- **Up**: every sprint belonging to an epic carries `Epic: NN` in its THOUGHTS header.
- **Down**: the ROADMAP table lists every sprint with its status + docs link.
- That pairing is enough — do **not** introduce per-epic subfolders; the flat `docs/` layout keeps the existing globs and tooling working.

## Completion and archiving

When **every ROADMAP row** is resolved (`Done` or `Skipped`) and the PRD's success criteria are met:

1. **Offer** to move the epic set (THOUGHTS, PRD, ROADMAP) to `docs/DONE/`.
2. After the user agrees, move them and add a row to the **Epics** table in `docs/DONE/README.md`. Constituent sprints archive on their own schedule per `prd-implementation.md`; update the ROADMAP's Docs links to wherever each sprint set now lives (e.g. `../DONE/`).
3. Ensure `docs/EPIC-INDEX.md` still reflects the highest epic `NN` in use.

### `docs/DONE/README.md` — Epics table

Add alongside the existing sprint table (create the file if missing):

```markdown
## Completed epics

| Epic | Name | THOUGHTS | PRD | Roadmap | Sprints | Completed |
|------|------|----------|-----|---------|---------|-----------|
| 01 | Short name | [THOUGHTS](EPIC01-THOUGHTS-slug.md) | [PRD](EPIC01-PRD-slug.md) | [ROADMAP](EPIC01-ROADMAP-slug.md) | 07–09 | YYYY-MM-DD |
```

## Example (EPIC THOUGHTS header + ROADMAP row + sprint up-link)

EPIC THOUGHTS header:

```markdown
Epic: 01
Slug: payments-platform

Rough idea: replace the bolt-on billing with a first-class payments service…
```

ROADMAP row:

```markdown
| 07 | data-model | Core schema | Done | — | [docs](SPRINT07-PRD-data-model.md) |
```

Sprint THOUGHTS header (the up-link, per `prd-implementation.md`):

```markdown
Sprint: 07
Slug: data-model
Epic: 01
```
