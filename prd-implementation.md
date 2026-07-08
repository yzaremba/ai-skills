---
paths:
  - docs/SPRINT*-*.md
  - docs/SPRINT-INDEX.md
---

# PRD Implementation Workflow (Sprint docs)

When the user asks to brainstorm, plan, or implement a sprint, follow this flow. Work proceeds in **stages with explicit gates** (Backlog → THOUGHTS → PRD → PLAN + TASKS → Implementation); do not skip ahead without confirmation at each gate.

A sprint may stand alone or belong to a larger multi-sprint **epic** (see `epic-implementation.md`). When it does, tag its THOUGHTS header with `Epic: NN` (below) — that line is the only coupling; the rest of this flow is unchanged.

## Sprint numbering (`docs/SPRINT-INDEX.md`)

- **`docs/SPRINT-INDEX.md` is the preferred source** for which two-digit sprint number `NN` to use next. Read it before creating a new sprint set.
- If the index is missing, outdated, or contradicts filenames, **reconcile**: set **Latest assigned sprint `NN`** to the maximum `NN` appearing in any `SPRINTNN-*` file under `docs/` and `docs/DONE/`, then use `NN + 1` (two digits) for a **brand-new** sprint. After creating the first file of a new sprint, update the index.
- If the index is absent, create it when starting or tidying sprint docs.

## File naming

All related files for one sprint feature use this pattern:

`docs/SPRINTXX-<TYPE>-<Description>.md`

- **SPRINTXX** — two-digit sprint number (`01`, `02`, …). Take `NN` from **SPRINT-INDEX** (see above); only fall back to scanning `docs/` and `docs/DONE/` if needed.
- **TYPE** — one of: `THOUGHTS`, `PRD`, `PLAN`, `TASKS` (uppercase as shown).
- **Description** — short kebab-case slug; **use the same slug** for every file in the set so they group together (e.g. `mobile-layout`). It should match the **Slug** line in THOUGHTS (normalize casing to kebab-case). Prefer **domain-qualified** slugs over generic ones (`mobile-layout`, not bare `layout`) so they stay distinct across the flat `docs/` — not enforced globally, but it avoids ambiguous `*-<slug>.md` families. For sprints that belong to an epic, the slug must be unique **within that epic's ROADMAP** (see `epic-implementation.md`).

Examples: `docs/SPRINT01-THOUGHTS-mobile-layout.md`, `docs/SPRINT01-PRD-mobile-layout.md`.

Legacy files matching `docs/PRD-*.md` without a sprint prefix may still exist; prefer the sprint pattern for new work.

## Stage 0 — BACKLOG (`docs/BACKLOG.md`)

- `docs/BACKLOG.md` is a persistent, free-form **dumping ground** for ideas, bug reports, and wishlist items captured outside any active sprint. It is **not** sprint-scoped.
- Content is **intentionally unstructured**: bullets, one-liners, half-thoughts. Optional grouping under headers (e.g. `## Bugs`, `## Features`, `## UX`) is fine but not required — do not impose structure the user did not ask for.
- Create the file if it does not exist the first time an item needs to be added.
- **Starting a new sprint:** the user picks one or more items from `BACKLOG.md` that form a coherent theme. Those items seed the new `SPRINTXX-THOUGHTS-<slug>.md` (Stage 1). **Delete** the plucked items from `BACKLOG.md` in the same change — traceability lives in the new THOUGHTS file, which should quote or paraphrase the original idea.
- Items not yet picked up stay in `BACKLOG.md` indefinitely. No expiry — keep it lightweight. Priority tagging is optional; when used, prefix the bullet with `**[HIGH]** / **[MED]** / **[LOW]**`. Older un-tagged entries are grandfathered.
- **Gate:** Do not start a sprint (THOUGHTS file) without an explicit user signal about which backlog items to pluck, or explicit direction that the sprint theme comes from outside the backlog.

## Stage 1 — THOUGHTS (brainstorm)

- THOUGHTS for a new sprint typically starts by plucking items from `docs/BACKLOG.md` (Stage 0). The plucked items should be **deleted from the backlog** as part of the same change that creates this file.
- The user may create `SPRINTXX-THOUGHTS-<Description>.md` themselves or ask you to create it.
- Put these lines at the **top** of the file (before freeform notes), then a blank line:
  - `Sprint: NN` (match the filename’s sprint)
  - `Slug: <kebab-case-slug>` (must match the `<Description>` segment in all four filenames)
  - `Epic: NN` *(optional)* — include only when this sprint belongs to a multi-sprint epic; this is the up-link to `epic-implementation.md`. Omit for standalone sprints.
- Content below is **intentionally unstructured**: bullets, questions, rough ideas, unordered notes. No need for full sections or IDs.
- **Gate:** Before writing a PRD, **confirm with the user** that THOUGHTS are ready to turn into requirements. If they want more brainstorming, stay in this stage.

## Stage 2 — PRD

- After confirmation, create `SPRINTXX-PRD-<Description>.md` from THOUGHTS (and any verbal direction). Cross-link THOUGHTS and PRD in headers.
- **Promote, don't copy — trim THOUGHTS as the PRD absorbs the meat.** Moving to a PRD is a *migration*: the substance — requirements, intended behavior, rationale, and any implementation thinking — goes **into** the PRD. In the same change, edit the THOUGHTS file down to only its **defining points** (the core problem, the decisive ideas/constraints that shaped the sprint, key questions that framed it). Strip implementation detail and anything the PRD now captures better. THOUGHTS should end up a short, high-signal record of *why this sprint exists and what defines it* — not a parallel spec that duplicates or drifts from the PRD.
- Include a **Non-goals** section (short bullet list): explicit **out of scope** items to limit scope creep before PLAN/TASKS. Keep it concrete (what we are *not* doing in this sprint).
- **Critical pass (default).** Once the draft exists, **take a critical pass over it by default** (no need to ask first) — testing each requirement for **efficacy** (does it actually move the sprint's goal?), **consistency** (no internal contradictions; aligns with THOUGHTS), and **need** (genuinely required vs. scope creep). **Fold minutia automatically** (wording, redundant or overlapping bullets, tightening, obvious small gaps) and **bubble up the material findings** — questionable or unneeded requirements, conflicts, missing pieces, things worth cutting — to the user for a decision rather than changing them silently. This is a quality check on the PRD itself, distinct from the user's own review below; skip it only if the user explicitly opts out.
- The user reviews and edits the PRD until they are satisfied.
- **Gate:** Do **not** create PLAN or TASKS until the user explicitly signals the PRD is final enough to proceed (e.g. “PRD is good” / “generate PLAN and TASKS”).

## Stage 3 — PLAN, TASKS, and Implementation

- **Explore the codebase** before writing the plan so steps reference real paths and patterns.
- Create `SPRINTXX-PLAN-<Description>.md` and `SPRINTXX-TASKS-<Description>.md`.
- Cross-link **PRD, PLAN, and TASKS** in each file’s header (and link back to THOUGHTS where useful for traceability).

### PLAN file structure

- **Header**: title, links to THOUGHTS, PRD, TASKS, status, last-updated date
- **Phases**: logical groups (e.g. data, logic, API, UI)
- **Steps**: unique IDs `P<phase>.<step>` where `<phase>` and `<step>` are **integers** (e.g. `P1.1`, `P3.4`). Do **not** use letters or words for `<phase>` (no `PA.1`, `PWATCHDOG.1`) — phases can still be *named* conceptually in the heading (e.g. "Phase 2 — API"), but the ID is always numeric.
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
- New steps discovered during implementation: add to **both** PLAN and TASKS with the next ID in that phase; bump PLAN “Last updated”
- After bug fixes on completed steps: add `> Bug fix YYYY-MM-DD: …` on the PLAN step; if the PRD requirement changed, update the PRD header/date

### TASKS-line discipline

- **TASKS lines stay at the original "short description" forever.** Do not append shipping detail, bug-fix notes, deviation context, or shakedown observations on `[ ]→[~]→[x]` transitions. The bracket character is the only thing that changes. New TASKS lines are *also* short — do not duplicate PLAN-step bodies onto the line.
- **Implementation context belongs on the PLAN step**, via `> Landed YYYY-MM-DD: <≤2-line note>` (same blockquote convention as the existing `> Bug fix YYYY-MM-DD: …` annotation). Use it when something genuinely diverged from plan, surfaced a follow-up, or shipped a notable detail. Cap each at 2 lines; later annotations replace earlier ones rather than accumulate.
- **Sprint closure with residuals**: when closing a sprint that still has open `[ ]` tasks, annotate each affected PLAN step with `> Audit YYYY-MM-DD: <verdict>: <≤2-line evidence>` (same blockquote family as `> Bug fix` / `> Landed`). Verdicts: `PARTIAL`, `NOT DONE`, `MOSTLY WIRED`, etc.; cite file:line for evidence. The matching TASKS line flips to `[x] ~~strikethrough~~ (skipped: moved to BACKLOG / <other reason>)`.
- **Beyond PLAN annotations, git log is the chronological record.** Don't introduce a parallel narrative file unless a genuine cross-step gap surfaces — and even then, prefer fixing it in the relevant PLAN step. Project-specific files (e.g. `docs/RESEARCH-LOG.md`) have their own scoped purposes; do not co-opt them for build/ops chronology.
- Rule of thumb: if you're tempted to write more than ~150 chars on a TASKS line, you're writing PLAN content — put it there.

### "Last updated" hygiene

- Format: `**Last updated:** YYYY-MM-DD — <≤2-line summary of what changed in *this* rev>`. Nothing more.
- **Do not append running history** — no "Earlier:" cascades, no concatenated prior-rev paragraphs. Each rev replaces the prior summary; git log carries the history.
- If a prior rev's context is genuinely load-bearing for understanding the current state, it belongs in the relevant PLAN step's body or a `> Bug fix YYYY-MM-DD: …` annotation, not the header.
- Same rule applies to PLAN, TASKS, and PRD header dates.

### Implementation (executing the sprint)

When the user asks to **implement** a sprint — write code against an existing PLAN/TASKS set — resolve the choices below (ask interactively only for what the user didn't already state; prefer a *single consolidated* prompt over separate round-trips), then **print a summary** and proceed. This is the implementation half of Stage 3; it honors the **task lifecycle** and **TASKS-line discipline** above.

1. **Target** — if no specific task/phase was named, ask: (a) next implementable task, (b) next implementable phase, (c) all remaining phases. *Implementable* = the next not-done item whose `> Depends on:` prerequisites are all `[x]`; skip done/skipped items.
2. **Workspace** — if the user wasn't explicit, ask: (a) a new git worktree, (b) in place where the repo currently sits (current branch, or master/main). For (a), the orchestrator creates a **persistent** worktree on a new branch (`git worktree add ../sprint-NN-slug -b <branch>`), points the implementer at that path, and commits there — **not** the Agent tool's throwaway `isolation: worktree`, which auto-cleans and would discard the work. For (b) on the default branch, branch first before any commit.
3. **Adversarial pass** — an *independent, adversarial* review of the just-written code that actively tries to break it (hunt bugs, gaps, missed edge cases), distinct from the implementer's own self-verify. If unstated, ask: (a) after each phase *(recommended)*, (b) after each task, (c) at completion, (d) none. Run the adversarial pass whatever way fits — an adversarial review skill or a reviewer agent prompted to refute the change — and for a pass that runs after commits have already landed, scope it to the branch diff (vs the fork point), not just the uncommitted working tree.
4. **Commit cadence** — if unstated, ask: (a) after each phase *(recommended)*, (b) after each task, (c) at completion, (d) don't commit. The chosen cadence **is** the user's commit authorization.
5. **Implementer** — default to the **`sprint-coder` agent** unless the user says otherwise (e.g. implement inline yourself).
6. **Summary first** — before any code, print the resolved choices: target (expanded to the concrete ordered list of steps/phases in scope), workspace, adversarial-pass cadence, commit cadence, implementer. This print is the final go-ahead checkpoint.

Then loop over the in-scope units:

- **Per unit** the implementer flips the TASKS line `[ ] → [~]`, implements + self-verifies, closes `[~] → [x]`. The **orchestrator (main session)** then runs the adversarial pass and/or commits whenever their cadence fires on that boundary — `sprint-coder` is barred from committing, so commits are always the orchestrator's.
- **Adversarial before commit** — when both fire on the same boundary, run the pass and **land its fixes before committing** so commits stay clean; when the pass runs less often than commits, its fixes simply arrive as follow-up commits.
- **Commit message prefix** — lead every sprint commit with its sprint-qualified ID: `S<sprint>P<phase>` (e.g. `S12P3`) for a phase-boundary commit, `S<sprint>P<phase>.<step>` (e.g. `S12P3.4`) for a task-boundary commit. Same `P<phase>.<step>` as the PLAN/TASKS ID, with the sprint number prepended — a bare `P3.4` doesn't say which sprint it's from.
- **Stay observable** — under "all remaining phases," emit a brief progress checkpoint at each phase boundary (what landed, what's next).
- **Stop on trouble — ask, don't guess.** If a unit can't be completed, a dependency isn't actually `[x]`, or the adversarial pass finds a blocking issue, **pause and put a clear, specific question to the user** — state the problem and offer concrete resolution options (e.g. fix now / skip and continue / amend PLAN / abort) — so their choice drives the resolution and execution can resume. Never silently route around it or press on, even under "all remaining phases."

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

Commit message (task-boundary, this is sprint 2): `S2P2.3 — Add getTradesByPosition() to MariaDbTradeRepositoryApi`. A phase-boundary commit covering all of Phase 2 would instead lead with `S2P2`.
