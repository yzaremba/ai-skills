# Conventions for sprint docs

These hold in every stage. Read this file before creating, renaming or editing any sprint doc.

## The sprint docs directory

Every sprint doc is in **the sprint docs directory**. It is the setting `process.docs_dir`: a path relative to the project root, `docs/` by default, which may lead outside the project's repository. Read it before the first sprint doc is touched in a session:

```text
python scripts/settings.py process --project <project root>
```

`scripts/settings.py` is in this skill's directory; run it by its path, with the Python the session has. The project is only the directory named with `--project`, never the working directory. The same run gives `process.questions` and `process.recommend` (see "Questions to the user" below).

- **The project root is the main working tree of the project's repository**, never a sprint's or a group member's worktree: the first entry of `git worktree list`. Name it with `--project` from wherever the session works. The project's own settings files are there and may be absent from a worktree, and `process.docs_dir` resolves against it.
- **In a sprint's worktree** the sprint's own docs are at that same path inside the worktree, when the directory is inside the repository. A directory outside the repository is one place, the same from every worktree.
- **If the script exits with an error, stop and report it**: a settings file is wrong, and the defaults would hide that. The defaults (`docs`, `one-at-a-time`, `true`) are used only when no Python 3.11 or later can start the script; say so then.

File names below are written without a directory. Each is in the sprint docs directory, and `DONE/` is the archive directory inside it.

## Sprint numbering (`SPRINT-INDEX.md`)

- **`SPRINT-INDEX.md` is the preferred source** for which two-digit sprint number `NN` to use next. Read it before creating a new sprint set.
- **The index is a pointer, not a historical log.** It carries exactly one fact — the latest assigned `NN` — plus the update rules. Assigning a new number **overwrites that value**; it never appends. Do **not** add per-sprint descriptions, slugs, scope summaries, "what `NN` was" history, or a derived "next sprint = `NN+1`" field (a second copy of the same fact drifts from the first). Filenames already map `NN` → slug, each sprint's own docs carry its scope, `DONE/README.md` lists completed work, and `git log` carries the chronology — an index entry is a fourth copy that outlives and contradicts all three.
- This is a **recurring drift**: sessions keep appending a line about the sprint they just opened. If you find accumulated history here, **delete it in the same change** as whatever else you are doing to the file — do not preserve it "for context" and do not migrate it elsewhere; it is already recorded.
- If the index is missing, outdated, or contradicts filenames, **reconcile**: set **Latest assigned sprint `NN`** to the maximum `NN` appearing in any `SPRINTNN-*` file in the sprint docs directory and its `DONE/`, then use `NN + 1` (two digits) for a **brand-new** sprint. After creating the first file of a new sprint, update the index.
- If the index is absent, create it when starting or tidying sprint docs.
- **The whole file is this**, with the number in place of `07`. An index that holds the same one fact in another layout, such as a table, is left in its layout: only the number is overwritten.

```markdown
# Sprint index

Latest assigned sprint `NN`: `07`

> **A pointer, not a log.** This file carries one fact, the latest assigned `NN`. Assigning a number overwrites the value above and appends nothing: no per-sprint descriptions, slugs or history.
```

## File naming

All related files for one sprint feature use this pattern:

`SPRINTXX-<TYPE>-<Description>.md`, in the sprint docs directory

- **SPRINTXX** — two-digit sprint number (`01`, `02`, …). Take `NN` from **SPRINT-INDEX** (see above); only fall back to scanning the sprint docs directory and its `DONE/` if needed.
- **TYPE** — one of: `THOUGHTS`, `PRD`, `PLAN`, `TASKS`, `STATE` (uppercase as shown). `STATE` exists only while the sprint is being implemented; its content and rules are in [state.md](state.md).
- **Description** — short kebab-case slug; **use the same slug** for every file in the set so they group together (e.g. `mobile-layout`). It should match the **Slug** line in THOUGHTS (normalize casing to kebab-case). Prefer **domain-qualified** slugs over generic ones (`mobile-layout`, not bare `layout`) so they stay distinct across the flat sprint docs directory — not enforced globally, but it avoids ambiguous `*-<slug>.md` families. For sprints that belong to an epic, the slug must be unique **within that epic's ROADMAP** (see the `epic-implementation` skill).

Examples, with the default directory: `docs/SPRINT01-THOUGHTS-mobile-layout.md`, `docs/SPRINT01-PRD-mobile-layout.md`.

Legacy files matching `PRD-*.md` without a sprint prefix may still exist; prefer the sprint pattern for new work.

## Links and names

Files carry the names of artifacts, not paths to them. A sprint's own docs sit together and move together: the close moves the set into `DONE/` as one, so a link between two of them survives that move. Any other relative link breaks when either side moves. **A file that is not archived together with its target names it and never links it.**

- **A sprint doc links only within its own set**: the THOUGHTS, PRD, PLAN, TASKS and STATE of the same sprint, by bare file name, as in `[PRD](SPRINT07-PRD-mobile-layout.md)`.
- **Any other doc is named, never linked**: by its file name in backticks, as in `` `SPRINT83-PLAN-macro-rates-ingest.md` ``. That holds for another sprint's doc, active or archived; an epic doc; a backlog item document, which is deleted when its item is plucked; the shared files (`BACKLOG.md`, `DEFERRED.md`, `SPRINT-INDEX.md`, `DONE/README.md`); and the project's other docs, in the sprint docs directory or outside it. A name survives the archive and is found by searching; a path does not. A name that says nothing on its own, `README.md` or `index.md`, is given with its path from the project root, as in `` `docs/DONE/README.md` ``.
- **Anything else outside the set, such as code, data or an image, is a path in backticks** from the project root, as in `` `src/ingest/sharadar.py` ``, never a link.
- **Files that are never archived with a sprint name its docs too**: `BACKLOG.md` item text, the item documents in `BACKLOG/`, `DEFERRED.md`, `DEFERRED-context.md` and the lessons of the project memory name a sprint's or an epic's doc and do not link it.
- **Closing a sprint updates no link in another doc.** A doc that names an archived doc stays right as it is.
- **The exceptions are shared files, which keep their links**: the epic roadmap's Docs column, which the close points into `DONE/` ([completion.md](completion.md)); the rows of `DONE/README.md`, in the same folder as the archived files; the item links of `BACKLOG.md`, into `BACKLOG/`, which is never archived; and the indexes, where they link.
- A URL and an anchor in the same file are not relative links, and stay links.

The check command reports these links in an active sprint's THOUGHTS, PRD, PLAN, TASKS or STATE, in the sprint docs directory and in the sprint's worktree:
- a link to a doc of another sprint (`link-other-sprint`);
- a link to an epic doc (`link-epic-doc`);
- any other relative link out of the set (`link-outside-set`).

Each comes with the name or the path to write in its place. In `BACKLOG.md`, the item documents and `DEFERRED-context.md` it reports links to sprint and epic docs; the item links of `BACKLOG.md` stay. It leaves out the archive: a doc in `DONE/` is not rewritten.

**Whoever next works on a sprint fixes the check's violations in that sprint's docs**, in the sprint's workspace (its worktree or branch) and never in the default branch's copy, each doc by its owner: the Product Manager for THOUGHTS and PRD, the build lead for PLAN, TASKS and STATE. That holds for a sprint still in design, with only THOUGHTS or a PRD, as for one being built ([stage-3-implementation.md](stage-3-implementation.md), "Picking up a sprint in progress").

## Where each doc is written

| Doc | Written on | Commit |
|-----|------------|--------|
| The start of a sprint: its first THOUGHTS file and the index bump, with the other changes that belong to starting it: the plucked backlog items, the deleted item documents of those items and, for a sprint of an epic, its roadmap row | The default branch | One local commit, which starting the sprint authorizes |
| Everything later for that sprint: later THOUGHTS edits, more brainstorming included, then PRD, PLAN, TASKS, STATE | The sprint's worktree, or the sprint's branch when it works in place | Each a separate decision of the user; during implementation the commit cadence is that decision, and at the close the word to close |
| Files shared between sprints: the backlog (`BACKLOG.md`) with its item documents (`BACKLOG/B<n>-<slug>.md`), the deferred file (`DEFERRED.md`) with the context file its conversion makes (`DEFERRED-context.md`), the epic roadmap, the archive index (`DONE/README.md`), the sprint index | The default branch only, at any time, also while a sprint is active | Each a separate decision of the user |

- **Starting a sprint authorizes exactly that one local commit.** It holds the changes in the table's first row and nothing else: commit only those files, by name. It is made in the working tree that has the default branch checked out; if none has, ask the user. Pushing it, and every later commit, stay separate decisions.
- **The sprint's worktree or branch is made right after the start commit**, as "The sprint's workspace" below says, and all further work on the sprint's own docs happens there. A session picking the sprint up finds it with `git worktree list` and `git branch --list 'sprint/*'`, or in the check command's report ([deferred.md](deferred.md)), which names each sprint branch, where it is checked out and which of its docs are there.
- **A shared file is never changed in a sprint worktree.** The copy there is a stale one. Make the change in the working tree that has the default branch checked out; if none has, ask the user.
- **At close the sprint's own docs come to the default branch.** The close's merge brings them, and the archive change (the move to `DONE/`, the STATE deletion, the rows in the shared files) is then made on the default branch, not in the sprint's worktree: [completion.md](completion.md). An abandoned sprint's docs reach `DONE/` without a merge: [abandon.md](abandon.md).
- **Sprint docs in a separate repository.** When the sprint docs directory is in another repository than the code, every sprint doc, the shared files included, is committed on that repository's default branch, and the worktree rule above does not apply to docs: no workspace is made for them after the start commit. The code still gets its worktree or branch, chosen and made with the implementation choices ([stage-3-implementation.md](stage-3-implementation.md)), and STATE records it. When the directory is in no git repository at all, nothing of the docs is committed and the branch rules do not apply to them.

### The sprint's workspace

Right after the start commit, whoever started the sprint makes its workspace. The question is put once, here, unless the user has already said: (a) a new git worktree, (b) a branch in place, in the working tree where the repository sits. The implementation choices later state the answer instead of asking again.

- **(a) A new worktree**: a **persistent** worktree on a new branch, `git worktree add <root>/<repo>-sprint-NN-slug -b sprint/NN-slug` — **not** a throwaway worktree made for one dispatched session, which auto-cleans and would discard the work. Resolve `<root>` first-match-wins: a path the user named → a worktree root named in project guidance (the project's instruction file, or its own docs) → the parent of an existing sprint worktree in `git worktree list` → `..`. Never place it **inside** the repo's working tree unless gitignored — the repo's own globs, linters, and test runners would sweep it up.
- **(b) In place**: `git switch -c sprint/NN-slug`, before any further change. No working tree then has the default branch checked out, so a change to a shared file is put to the user first, as the rule above says.
- Making a worktree or a branch is not a commit and needs no further authorization; removing one is covered in [completion.md](completion.md).

## Task lifecycle

- **Not started**: `- [ ]`
- **In progress**: `- [~]`
- **Done**: `- [x]`
- **Skipped**: `- [x] ~~**P2.5** — …~~ (skipped: reason)`
- New steps discovered during implementation: add to **both** PLAN and TASKS with the next ID in that phase; bump PLAN "Last updated"
- After bug fixes on completed steps: add `> Bug fix YYYY-MM-DD: …` on the PLAN step; if the PRD requirement changed, update the PRD header/date

## TASKS-line discipline

- **TASKS lines stay at the original "short description" forever.** Do not append shipping detail, bug-fix notes, deviation context, or shakedown observations on `[ ]→[~]→[x]` transitions. The bracket character is the only thing that changes; a `**[hard]**` after the ID ([stage-3-plan-tasks.md](stage-3-plan-tasks.md), "TASKS file structure") stays, on a skipped line too. New TASKS lines are *also* short — do not duplicate PLAN-step bodies onto the line.
- **Implementation context belongs on the PLAN step**, via `> Landed YYYY-MM-DD: <note>` (same blockquote convention as the existing `> Bug fix YYYY-MM-DD: …` annotation). Use it when something genuinely diverged from plan, surfaced a follow-up, or shipped a notable detail. An annotation is one line of at most 300 characters ("Format limits" below); a later annotation replaces the earlier one of the same kind on that step rather than accumulating.
- **Sprint closure with residuals**: when closing a sprint that still has open `[ ]` tasks, annotate each affected PLAN step with `> Audit YYYY-MM-DD: <verdict>: <evidence>`, one line within the same limit (same blockquote family as `> Bug fix` / `> Landed`). Verdicts: `PARTIAL`, `NOT DONE`, `MOSTLY WIRED`, etc.; cite file:line for evidence. The matching TASKS line flips to `[x] ~~strikethrough~~ (skipped: moved to BACKLOG as B<n> / <other reason>)`, naming the backlog item the residual became ([stage-0-backlog.md](stage-0-backlog.md)).
- **An open step that only waits** on elapsed time or an outside event is closed the same way, with fixed words: the verdict is `DEFERRED`, the evidence starts with the number of its item in `DEFERRED.md`, and the TASKS reason is exactly `deferred as D<n>`. A sprint whose only open steps are of this kind closes as code-complete: [deferred.md](deferred.md).
- **Beyond PLAN annotations, git log is the chronological record.** Don't introduce a parallel narrative file unless a genuine cross-step gap surfaces — and even then, prefer fixing it in the relevant PLAN step. Project-specific files (e.g. a `RESEARCH-LOG.md`) have their own scoped purposes; do not co-opt them for build/ops chronology.
- **A TASKS line is at most 150 characters** ("Format limits" below). If you need more, you're writing PLAN content — put it there.

## Format limits

These limits are exact, so that they can be checked mechanically.

| Line | Limit |
|------|-------|
| An annotation on a PLAN step: a line of a PLAN file (`SPRINTXX-PLAN-…`) that starts with `> Landed `, `> Bug fix ` or `> Audit ` | One line of at most 300 characters |
| A TASKS line: a line of a TASKS file (`SPRINTXX-TASKS-…`) that starts with `- [ ]`, `- [~]` or `- [x]` | At most 150 characters |
| A backlog item: a line of `BACKLOG.md` that starts with `- ` | One line of at most 300 characters |
| A line of a deferred item in `DEFERRED.md`: its heading or one of its field lines | One line of at most 300 characters |

- **Every limit is inclusive**: a line of exactly 300, or exactly 150, characters is within its limit; one more is over.
- **What is counted** is the Unicode characters (code points) of the whole line as written, without the line's newline. Everything on the line counts: the leading `> ` or `- [ ] `, the date, markup such as `**`, backticks and `~~`, and a link's brackets and target as well as its text. On a TASKS line the `**[hard]**` tag counts, and on a skipped one the strikethrough and the `(skipped: …)` reason too; on a backlog item the number, the priority tag and the link to its document count.
- **A carriage return at the end of a line is not counted.** A file checked out with CRLF line endings measures the same as with LF.
- **One line means one line.** An annotation is never continued: a line directly after it that starts with `>` and is not itself an annotation or a mark (`> Depends on:`, `> Parallel:`, `> Tag:`) is a second line, and a violation. A backlog item and a field of a deferred item are never continued either: [stage-0-backlog.md](stage-0-backlog.md) and [deferred.md](deferred.md) say which lines those two files may hold, and any other line in them is a violation.
- **What does not fit goes elsewhere**: for an annotation, in the commit message; for a TASKS line, on the PLAN step; for a backlog item, in the item's document.
- **A step holds at most one annotation of each kind.** A new `> Landed`, `> Bug fix` or `> Audit` replaces the earlier one of that kind; two of one kind on a step is a violation. For this count a step runs from its heading, a heading line whose text starts with the step's ID (`### P2.3 — …`), to the next heading line of any level.
- **A TASKS line's tag agrees with its PLAN step.** The only tag of a TASKS line is `**[hard]**`, once, directly after the step ID and followed by a space; any other bold bracketed tag on the line, `**[light]**` included, is a violation. Where the PLAN of the same sprint is beside the TASKS file, a line without `**[hard]**` whose step carries `> Tag: hard`, and a line with it whose step does not, are violations. A line whose ID the PLAN does not hold is not compared.
- **Lines inside a fenced code block are neither counted nor checked** in a PLAN or TASKS file: an example of an annotation or of a TASKS line is not one. A block opens at a line that starts, after at most three spaces, with three or more backticks or three or more tildes. It closes only at a line of the same character, at least as many of them as the opening line has, with nothing after them but white space; or at the end of the file. A shorter fence inside a longer one is therefore content of the block. `BACKLOG.md` and `DEFERRED.md` hold no code block; a fence there is a line that has no place in the file.
- **The archive is not checked.** The limits apply to the sprint docs directory itself, not to `DONE/`: an archived PLAN or TASKS is not rewritten to fit.
- Marks, the step's body and the header's "Last updated" line are not annotations and have no exact limit.

**The check command checks these limits.** It is `scripts/check.py` in this skill's directory, and it reports each line over its limit and each violation named above; it changes nothing. [deferred.md](deferred.md), "The check command", says how it is run.

## "Last updated" hygiene

- Format: `**Last updated:** YYYY-MM-DD — <≤2-line summary of what changed in *this* rev>`. Nothing more. "Two lines" here is a judgment of rendered length, not one of the exact limits above.
- **Do not append running history** — no "Earlier:" cascades, no concatenated prior-rev paragraphs. Each rev replaces the prior summary; git log carries the history.
- If a prior rev's context is genuinely load-bearing for understanding the current state, it belongs in the relevant PLAN step's body or a `> Bug fix YYYY-MM-DD: …` annotation, not the header.
- Same rule applies to PLAN, TASKS, and PRD header dates.

## No approval in a doc

THOUGHTS, PRD, PLAN and TASKS never record an approval or a review: no "approved", "awaits approval", "prepared for review" or the like, in a header, a "Last updated" line or anywhere else. A gate passes by the user's word, not by the file. Their only status lines are the PLAN header's ([stage-3-plan-tasks.md](stage-3-plan-tasks.md)) and an abandoned sprint's ([abandon.md](abandon.md)); the PRD has none. STATE, which says where the work stands, is not covered by this.

## Questions to the user

Whenever this process puts open questions to the user — at a gate, with the material findings of a critical pass, when a stage needs a decision, when stopping on trouble — two settings say how. They come from the same run of `scripts/settings.py` as the sprint docs directory.

- **`process.questions`** — `one-at-a-time` (the default): put one question, wait for the answer, then put the next; a later question may be dropped or changed by an earlier answer. That holds for open questions in every form: the same message does not list the others, as bullets or in prose, and does not give your leaning on each. At most it says how many remain. The one exception is a list the user asked for. `all-together`: put every open question in one message, numbered, so the user can answer them in one reply.
- **`process.recommend`** — `true` (the default): give your recommendation with each question, and its reason in a line. `false`: give the options without one.
- **The implementation choices are one question, not several.** [stage-3-implementation.md](stage-3-implementation.md) asks for a single consolidated prompt that holds every choice the user has not yet stated. That stays so under either value of `process.questions`: do not split it into one prompt per choice. `process.recommend` applies to it: when `false`, leave out the *(recommended)* marks.
- **The lessons and backlog finds of a close are one list.** [completion.md](completion.md) puts them in one message under either value of `process.questions`. `process.recommend` applies to each.
- How a question physically reaches the user differs by provider: [claude-code.md](claude-code.md) or [codex.md](codex.md).
