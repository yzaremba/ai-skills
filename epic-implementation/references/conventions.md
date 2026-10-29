# Conventions for epic docs

These hold in every stage. Read this file before creating, renaming or editing any epic doc.

## The epic docs directory

Every epic doc is in **the epic docs directory**, which is the sprint docs directory: the same directory the sprint docs are in. It is the setting `process.docs_dir`: a path relative to the project root, `docs/` by default, which may lead outside the project's repository. Read it before the first epic doc is touched in a session:

```text
python scripts/settings.py process --project <project root>
```

`scripts/settings.py` is in this skill's directory; run it by its path, with the Python the session has. The project is only the directory named with `--project`, never the working directory. The same run gives `process.questions`, `process.recommend` and `process.density` (see "Questions to the user" below).

- **The project root is the main working tree of the project's repository**, never a sprint's or a group member's worktree: the first entry of `git worktree list`. Name it with `--project` from wherever the session works. The project's own settings files are there and may be absent from a worktree, and `process.docs_dir` resolves against it.
- **If the script exits with an error, stop and report it**: a settings file is wrong, and the defaults would hide that. The defaults (`docs`, `all-together`, `true`, `brief`) are used only when no Python 3.11 or later can start the script; say so then.

File names below are written without a directory. Each is in the epic docs directory, and `DONE/` is the archive directory inside it.

## Hierarchy at a glance

| Level | Artifacts | Granularity |
|-------|-----------|-------------|
| **Epic** (this skill) | `EPICXX-THOUGHTS` / `PRD` / `ROADMAP` | one outcome, many sprints |
| Sprint (the `prd-implementation` skill) | `SPRINTXX-THOUGHTS` / `PRD` / `PLAN` / `TASKS` / `STATE` | one feature, ~one sprint |
| Task | `- [ ]` line in a sprint's TASKS | one work item |

## Epic numbering (`EPIC-INDEX.md`)

- **`EPIC-INDEX.md` is the preferred source** for which two-digit epic number `NN` to use next. Read it before creating a new epic set. It is **separate** from `SPRINT-INDEX.md`.
- **The index is a pointer, not a historical log** — same rule (and same recurring drift) as SPRINT-INDEX, see "Sprint numbering" in the conventions of the `prd-implementation` skill. It carries the latest assigned `NN` and nothing else; assigning a number overwrites that value. No per-epic descriptions, no "what `NN` was" history.
- If the index is missing, outdated, or contradicts filenames, **reconcile**: set **Latest assigned epic `NN`** to the maximum `NN` in any `EPICNN-*` file in the epic docs directory and its `DONE/`, then use `NN + 1` (two digits) for a brand-new epic. Update the index after creating the first file of a new epic.
- If absent, create it when starting or tidying epic docs, in the form "Sprint numbering" gives there for the sprint index: the title `# Epic index`, the line ``Latest assigned epic `NN`: `03` `` and the same guard.
- **Sprints keep their own global numbering** via `SPRINT-INDEX.md`. An epic does **not** renumber sprints — it *claims* sprint numbers as its roadmap sprints are created (recorded in the ROADMAP). A sprint belongs to **at most one** epic.
- **Slugs are the durable cross-reference; sprint numbers are late-bound.** Inside an epic, planned sprints are identified by **slug**, never by a pre-assigned number. A sprint's global two-digit number is assigned **only when the sprint is actually created** (`SPRINT-INDEX.md` max+1) and written into its ROADMAP row at that moment — until then the row's `Sprint` cell is `TBD`. This is deliberate: a number written before the sprint exists is **not** reserved, so a parallel sprint or epic would grab it via the same max+1 rule and silently invalidate the reference. A slug, by contrast, is recorded in the ROADMAP the moment the sprint is planned, so it *is* a real reservation.

## File naming

All files for one epic use:

`EPICXX-<TYPE>-<Description>.md`, in the epic docs directory

- **EPICXX** — two-digit epic number (`01`, `02`, …) from EPIC-INDEX.
- **TYPE** — one of `THOUGHTS`, `PRD`, `ROADMAP` (uppercase).
- **Description** — short kebab-case slug; **same slug** for all three files; matches the **Slug** line in EPIC THOUGHTS.

Examples, with the default directory: `docs/EPIC01-THOUGHTS-payments-platform.md`, `docs/EPIC01-ROADMAP-payments-platform.md`.

### Slug uniqueness

Because slugs are the durable cross-reference (above), they must not be ambiguous — but the scope that's **enforced** is local, not global:

- **Enforced (hard rule):** a sprint slug is unique **within its epic** (the ROADMAP's `Slug` column) and **within its sprint set** (per the `prd-implementation` skill). Both are *local* checks — you only inspect rows/files you already have open, no repo-wide scan. Within-epic uniqueness is what makes `Depends on`-by-slug unambiguous; that's all the resolution mechanism needs.
- **Convention (not enforced):** keep slugs distinct across the whole repo by **domain-qualifying generic names** — `payments-dashboard`, not bare `dashboard`; `billing-data-model`, not bare `data-model`. Filenames already disambiguate by sprint number (`SPRINT07-…-dashboard.md` ≠ `SPRINT21-…-dashboard.md`), so duplicates never collide on disk — this is purely for human discoverability in the flat epic docs directory.
- **Carve-out:** only when you must use a genuinely generic slug, do a quick `*-<slug>.md` scan of the epic docs directory first. Distinctive, domain-qualified slugs don't need it.

## Links and names

Files carry the names of artifacts, not paths to them. An epic's own docs sit together and move together: the epic's close moves THOUGHTS, PRD and ROADMAP into `DONE/` as one, and each of its sprints moves its own set there on its own schedule. A link between two docs of one set survives a move; any other relative link breaks when either side moves. **A file that is not archived together with its target names it and never links it.**

- **An epic doc links only within its own set**: the THOUGHTS, PRD and ROADMAP of the same epic, by bare file name.
- **Any other doc is named, never linked**: by its file name in backticks, as in `` `SPRINT83-PLAN-macro-rates-ingest.md` ``. That holds for a sprint's doc, another epic's doc, a backlog item document, the shared files and the project's other docs. A name survives the archive and is found by searching; a path does not. Anything else, such as code, is a path in backticks from the project root, never a link.
- **Files that are never archived with an epic name its docs too**: `BACKLOG.md` item text, the item documents in `BACKLOG/`, `DEFERRED.md`, `DEFERRED-context.md` and the lessons of the project memory name an epic's or a sprint's doc and do not link it.
- **The one exception is the ROADMAP's Docs column**: a link to each sprint's THOUGHTS file, which the sprint's close points into `DONE/` ("ROADMAP maintenance" below) and the epic's close makes relative to the ROADMAP's own new place ([completion.md](completion.md)). The rows of `DONE/README.md`, the item links of `BACKLOG.md` and the indexes, where they link, are shared files and keep their links as well.
- **Sprint docs follow the same rule** (the conventions of the `prd-implementation` skill, "Links and names"): a sprint names its epic's docs and never links them; its up-link is the number in `Epic: NN`. So closing a sprint or an epic updates no link in another doc but the Docs column.
- A URL and an anchor in the same file are not relative links, and stay links.

## ROADMAP maintenance

The ROADMAP's structure, and the steps for starting one of its sprints, are in [stage-e3-roadmap.md](stage-e3-roadmap.md).

- **Rows stay short** — only `Status` and `Docs` change over time; don't append narrative to a row. Per-sprint detail lives in that sprint's docs; cross-sprint context goes in the PRD or a `> Note YYYY-MM-DD: …` annotation under the table.
- **Scope changes**: adding a sprint = add a row (+ note); cutting one = set `Status: Skipped` with a one-line reason — don't delete the row (traceability).
- **A sprint's close sets its row**, on the default branch, in the change that archives the sprint (the `prd-implementation` skill describes that change):
  - **Finished**: `Done`.
  - **Closed as code-complete**: `Done` as well. Its code has landed, and the sprints that depend on it may start. What still waits is in `DEFERRED.md` and in the sprint's archive row; it is never written in the roadmap row.
  - **Abandoned or superseded**: `Skipped` with a one-line reason, like a cut sprint under "Scope changes". The row stays, and a sprint that supersedes it gets a row of its own.
  - The Docs link, which points at the sprint's THOUGHTS file from the sprint's start, follows the sprint set into `DONE/`.
- **"Last updated" hygiene**: `**Last updated:** YYYY-MM-DD — <≤2-line summary of this rev>`. No running history — git log carries that. Same rule for THOUGHTS/PRD headers.
- **No epic doc records an approval or a review**: no "approved", "awaits approval" or "prepared for review" in THOUGHTS, the charter or the ROADMAP. A gate passes by the user's word, not by the file. The epic status and a row's Status say where the work stands, never a gate.

## Epic status vocab (ROADMAP header)

- **Proposed** — charter/roadmap drafted, no sprint started.
- **Active** — at least one sprint in progress.
- **On hold** — paused; note why.
- **Done** — all rows `Done`/`Skipped` and success criteria met.
- **Abandoned** — dropped; note why.

## Traceability (both directions)

- **Up**: every sprint belonging to an epic carries `Epic: NN` in its THOUGHTS header: a number, not a link ("Links and names" above).
- **Down**: the ROADMAP table lists every sprint with its status + docs link, the link pointing at the sprint's THOUGHTS file.
- That pairing is enough — do **not** introduce per-epic subfolders; the flat layout of the epic docs directory keeps the existing globs and tooling working.

## Where each doc is written

An epic has no worktree of its own. Its docs are shared between its sprints, so they are written where every sprint can see them.

| Doc | Written on |
|-----|------------|
| EPIC THOUGHTS, the EPIC PRD (charter) and the epic index (`EPIC-INDEX.md`) | The default branch |
| The ROADMAP, the backlog (`BACKLOG.md`) with its item documents (`BACKLOG/B<n>-<slug>.md`) and the archive index (`DONE/README.md`) | The default branch only, at any time, also while a sprint is active |
| A sprint's own docs | Where the `prd-implementation` skill says: the first THOUGHTS file on the default branch, everything later in the sprint's worktree or branch, which is made right after the sprint's start commit |

- **The ROADMAP is never changed in a sprint worktree.** The copy there is a stale one. A row's sprint number, its Docs link and each change of its Status are made in the working tree that has the default branch checked out; if none has, ask the user.
- **Commits.** When a roadmap sprint is started, its ROADMAP row goes into the one local commit that starting a sprint authorizes (the `prd-implementation` skill describes it). Every other commit of an epic doc, and every push, is a separate decision of the user. The index bump of a new epic takes its number for other sessions only once it is committed, so ask for that commit when the first file of the epic is written.
- **Docs in a separate repository.** When the epic docs directory is in another repository than the code, every epic doc is committed on that repository's default branch. When the directory is in no git repository at all, nothing is committed and the branch rules do not apply to the docs.

## Questions to the user

Whenever this process puts open questions to the user — at a gate, with the material findings of the critical pass over a charter, when the decomposition needs a decision — three settings say how. They come from the same run of `scripts/settings.py` as the epic docs directory.

- **`process.questions`** — `all-together` (the default): put every open question in one message, numbered, so the user can answer them in one reply. `one-at-a-time`: put one question, wait for the answer, then put the next; a later question may be dropped or changed by an earlier answer. That holds for open questions in every form: the same message does not list the others, as bullets or in prose, and does not give your leaning on each. At most it says how many remain. The one exception is a list the user asked for.
- **`process.recommend`** — `true` (the default): give your recommendation with each question, and its reason in a line. `false`: give the options without one. `accept`: as "`accept`" below says.
- **`process.density`** — `brief` (the default) or `full`. `full` is the process's text as it stands. Under `brief`, what the user reads at a gate, in a summary or in a relayed report is the question with its options and recommendation, the result, and the paths: it does not say why the gate exists or what the process says, and does not recap what the user has already seen. When the user asks "why?", the explanation comes back for that answer. `brief` keeps what the roles require the user to see: the gate statement (which words are taken as the approval, the gate they pass, what it starts), each recommendation's one-line reason, a cost with what it buys, "stop here" and "cut to what the outcome needs". Hand-backs and briefs, which agents read, keep their form under either value.
- **`accept`** (a value of `process.recommend`): a question whose choice is **clear** is not asked; the recommendation is taken and the work goes on. A choice is clear when one option is recommended and no other option buys something the recommended one costs. The questions still asked carry a recommendation.
  - **Never taken without asking, under any value**: anything the process or a role's limits reserve to the user's word, every gate included, and the implementation choices belong to the gate of implementation. Examples, not a closed list: a push, merge to trunk, tag or deploy; a history rewrite; starting a sprint or an epic; a commit the cadence does not cover; a scope increase, and a spec gap's PLAN amendment; removing work or a requirement; a lesson; writing, re-dating, resolving or dropping a deferred item; a third review round; writing a settings key.
  - **Each decision taken so is listed**, one line each, at the next stop or gate, so the user can reverse it. A dispatched role that puts questions (the Product Manager, the Architect) lists its own in its hand-back, and the Manager relays them. The Implementation Manager puts no question to the user: its questions come to the Manager, which applies `accept` to them.
  - **A decision taken under `accept` is labelled as such** wherever it is relayed: in a hand-back, a brief or a message to the user. It is never quoted as the user's word, and it authorizes nothing.
- **A value stated in the session**: a value of `process.density`, `process.recommend` or `process.questions` that the user states in a session holds for the rest of that session and wins over the files; a new session starts from the files.
  - **The Manager carries it in every brief it writes**, so a dispatched role keeps it.
  - **"Keep it"**: when the user says to keep it, the Manager writes that one key of the `process` group into the project's `.agents/workflow.local.toml`, or into `~/.agents/workflow.toml` when the user names that file, and nothing else of a settings file.
  - **Precedence**, highest first: a value stated in the current session, then the settings files.
- How a question physically reaches the user differs by provider: the provider notes of the `prd-implementation` skill say how.
