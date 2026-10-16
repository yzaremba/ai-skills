# Stage E3 — EPIC ROADMAP (decompose into sprints)

Read [conventions.md](conventions.md) before creating or editing the file. This stage starts only after the user has signalled that the charter is final. It stays open for the life of the epic: the ROADMAP changes as sprints are created and land.

- **Explore the codebase** before decomposing so the sprint breakdown references real areas and dependencies.
- Create `EPICXX-ROADMAP-<Description>.md`. Cross-link THOUGHTS, PRD, ROADMAP in the header. Apart from the Docs column below, any other doc the ROADMAP refers to is named by its file name in backticks, never linked ("Links and names" in [conventions.md](conventions.md)). It is written, and later changed, only on the default branch (see "Where each doc is written" in [conventions.md](conventions.md)).
- The ROADMAP is the epic's **living tracker** — it replaces PLAN+TASKS at this altitude. Update it as sprints are created and land.

## ROADMAP file structure

- **Header**: title, links to THOUGHTS + PRD, **Epic status** (see "Epic status vocab" in [conventions.md](conventions.md)), last-updated date.
- **Sprint table** — one row per constituent sprint:

```markdown
| Sprint | Slug | Feature | Status | Depends on | Docs |
|--------|------|---------|--------|-----------|------|
| 07 | data-model | Core schema | Done | — | [docs](DONE/SPRINT07-THOUGHTS-data-model.md) |
| 08 | ingest-api | Ingestion API | In progress | data-model | [docs](SPRINT08-THOUGHTS-ingest-api.md) |
| TBD | dashboard | Read UI | Planned | ingest-api | — |
```

- **Sprint** — the global two-digit sprint number, filled in **only once the sprint is created** (`SPRINT-INDEX.md` max+1); `TBD` while the row is still `Planned`. Never pre-assign — see "Slugs are the durable cross-reference" under Epic numbering in [conventions.md](conventions.md).
- **Slug** — the sprint's kebab-case slug, chosen when the row is planned and **reused verbatim** as the `<Description>` when the sprint is created. This is the row's stable identity across renumbering.
- **Feature** — *optional* column; use only when one deliverable spans more than one sprint (group those rows). Drop the column if it's one feature per sprint.
- **Status** — `Planned` / `In progress` / `Done` / `Skipped`.
- **Depends on** — **slugs** (not numbers) of sprints that must land first. Slugs are stable; numbers may still be `TBD`, and a number could be reassigned out from under the reference.
- **Docs** — link to the sprint set once it exists; `—` while still planned. The link's target is the sprint's THOUGHTS file: it is on the default branch from the sprint's start commit, while the PRD is in the sprint's worktree until the merge. When the set is archived the link follows it into `DONE/`.
- **Sequencing & dependencies**: a short narrative below the table if the dependency graph isn't obvious from the column.

ROADMAP maintenance (rows stay short, scope changes, "Last updated" hygiene) is in [conventions.md](conventions.md). It applies from the first row written here: a row carries only slug / feature / dependency / status, never narrative.

## The seam — handing off to the sprint workflow

When the user starts one of the roadmap's sprints:

1. Create the `SPRINTXX-*` set per the `prd-implementation` skill, taking `XX` from `SPRINT-INDEX.md` (global numbering) and **reusing the ROADMAP row's slug verbatim** as the `<Description>`. This is the moment the number is assigned — not before.
2. Add `Epic: NN` to that sprint's **THOUGHTS header** (alongside `Sprint:` / `Slug:`) — the up-link, a number and not a link: the sprint's docs name the epic's docs and never link them ("Links and names" in [conventions.md](conventions.md)).
3. Fill the now-assigned sprint number + Docs link into the ROADMAP row, the link pointing at the sprint's THOUGHTS file, and flip its **Status** as the sprint moves (`Planned → In progress → Done`). Each of these edits is made on the default branch, never in the sprint's worktree; the first, with the status `In progress`, goes into the sprint's start commit. What the row becomes when the sprint closes, also as code-complete or abandoned, is under "ROADMAP maintenance" in [conventions.md](conventions.md).

From there the sprint runs entirely under the `prd-implementation` skill. This skill does **not** duplicate that flow.

## Example (ROADMAP row + sprint up-link)

ROADMAP row:

```markdown
| 07 | data-model | Core schema | Done | — | [docs](DONE/SPRINT07-THOUGHTS-data-model.md) |
```

Sprint THOUGHTS header (the up-link, per the `prd-implementation` skill):

```markdown
Sprint: 07
Slug: data-model
Epic: 01
```

Next: [completion.md](completion.md), when every ROADMAP row is `Done` or `Skipped`.
