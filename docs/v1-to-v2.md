# From v1 to v2: where each rule went

For someone moving from the v1 process who wants to know where a rule went. v1 was
three loose files: the rules `prd-implementation.md` and `epic-implementation.md`, and
the agent `agents/sprint-coder.md`. v2 is two skills, [`prd-implementation/`][p-skill]
and [`epic-implementation/`][e-skill], each a short entry file with one reference file
per stage.

The v1 files are no longer in the tree. They are in git history at tag `v1.0`:
`git show v1.0:prd-implementation.md`. An `L` number below is a line of the file at
that tag.

How to read the tables:

- **v2 location** names the file and, in quotes, the section.
- **Status** is one of: `carried` (the same words, or the same words with more beside
  them, which the last section lists); `carried, reworded` and what changed;
  `changed by R<id>` and what changed; `dropped under R<id>` and why. The ids are
  requirements of the sprint that made v2.
- Two rewordings run through every file and are not repeated in each row. `docs/`
  became "the sprint docs directory", a setting whose default is `docs/` (R3.3). A
  reference to a v1 file became a reference to the skill by name (R3.1). A row that
  says "directory and names only" has no other change.

## `prd-implementation.md`

| v1 location | v2 location | Status |
|-------------|-------------|--------|
| Frontmatter `paths:` (L1-5) | [SKILL.md][p-skill], frontmatter `description` | changed by R3.1: a skill is loaded by its description, which names the same docs, not by path globs |
| Title and opening (L7-9) | [SKILL.md][p-skill], opening | carried, reworded: the stage chain is a diagram and ends in Completion |
| Epic coupling (L11) | [SKILL.md][p-skill], opening | carried, reworded: directory and names only |
| Sprint numbering (L13-19) | [conventions.md][p-conv], "Sprint numbering" | carried, reworded: directory and names only |
| File naming: pattern, number, examples, legacy files (L21-27, L31-33) | [conventions.md][p-conv], "File naming" | carried, reworded: directory and names only |
| File naming: TYPE (L28) | [conventions.md][p-conv], "File naming" | changed by R3.4: `STATE` is a fifth type |
| File naming: Description, the slug (L29) | [conventions.md][p-conv], "File naming" | carried, reworded: directory and names only |
| Stage 0: what the backlog is (L35-37) | [stage-0-backlog.md][p-s0], opening | changed by R3.13: still a dumping ground, no longer free-form |
| Stage 0: unstructured content, optional headers (L38) | [stage-0-backlog.md][p-s0], opening, "The file", "A longer idea" | changed by R3.13: an item is one numbered line; free-form thinking goes in the item's document. Headers stay optional |
| Stage 0: create the file when needed (L39) | [stage-0-backlog.md][p-s0], opening | carried |
| Stage 0: starting a sprint, pluck and delete (L40) | [stage-0-backlog.md][p-s0], opening | changed by R3.13: the item's document is deleted with it, and THOUGHTS names its number |
| Stage 0: no expiry, priority tags (L41) | [stage-0-backlog.md][p-s0], opening, "The file" | changed by R3.13: the tag comes after the item's number; an untagged item stays valid |
| Stage 0: gate (L42) | [stage-0-backlog.md][p-s0], opening; [SKILL.md][p-skill], "Gates" | carried |
| Stage 1: pluck from the backlog (L44-46) | [stage-1-thoughts.md][p-s1] | changed by R3.13: the item's document goes too, and its number is named |
| Stage 1: who creates the file, header lines (L47-51) | [stage-1-thoughts.md][p-s1] | changed by R3.9 and decision H: the stage also holds the index update, the one local commit of the start, and the making of the sprint's workspace right after it. The header lines are v1's, with "every filename of the set" for "all four filenames" (R3.4) |
| Stage 1: unstructured content, gate (L52-53) | [stage-1-thoughts.md][p-s1]; [SKILL.md][p-skill], "Gates" | carried |
| Stage 2: create the PRD, cross-link (L55-57) | [stage-2-prd.md][p-s2] | changed by R3.9: the PRD is written in the sprint's worktree or branch, not on the default branch |
| Stage 2: promote, don't copy; Non-goals (L58-59) | [stage-2-prd.md][p-s2] | carried |
| Stage 2: critical pass (L60) | [stage-2-prd.md][p-s2] | changed by R5.4: its findings are put to the user as the question settings say |
| Stage 2: external contracts, user review, gate (L61-63) | [stage-2-prd.md][p-s2]; [SKILL.md][p-skill], "Gates" | carried |
| Stage 3: explore, create PLAN and TASKS, cross-link (L65-69) | [stage-3-plan-tasks.md][p-s3p], opening | changed by R3.9: both are written in the sprint's worktree or branch |
| PLAN file structure (L71-78) | [stage-3-plan-tasks.md][p-s3p], "PLAN file structure" | carried |
| TASKS file structure (L80-84) | [stage-3-plan-tasks.md][p-s3p], "TASKS file structure" | changed by R3.12: a line is at most 150 characters; a step tagged `hard` shows `**[hard]**` after its ID |
| Task lifecycle (L86-93) | [conventions.md][p-conv], "Task lifecycle" | carried |
| TASKS-line discipline: lines stay short (L95-97) | [conventions.md][p-conv], "TASKS-line discipline" | carried |
| TASKS-line discipline: the `> Landed` annotation (L98) | [conventions.md][p-conv], "TASKS-line discipline", "Format limits" | changed by R3.12: one line of at most 300 characters, where v1 allowed two lines; a new one replaces the earlier one of its kind |
| TASKS-line discipline: closure with residuals (L99) | [conventions.md][p-conv], "TASKS-line discipline" | changed by R3.12 and R3.13: the `> Audit` evidence is one line; the skipped reason names the backlog item |
| TASKS-line discipline: git log is the record (L100) | [conventions.md][p-conv], "TASKS-line discipline" | carried, reworded: directory and names only |
| TASKS-line discipline: the ~150 characters rule of thumb (L101) | [conventions.md][p-conv], "TASKS-line discipline", "Format limits" | changed by R3.12: an exact limit of 150 |
| "Last updated" hygiene (L103-108) | [conventions.md][p-conv], "Last updated hygiene" | carried |
| Implementation: opening (L110-112) | [stage-3-implementation.md][p-s3i], opening, "Resolve the choices" | changed by R5.4: the single consolidated prompt stays one prompt under either question setting |
| Choice 1, target (L114) | [stage-3-implementation.md][p-s3i], "Resolve the choices" | changed by R3.5: a next implementable task that is a member of a parallel group means the whole group |
| Choice 2, workspace (L115) | [conventions.md][p-conv], "The sprint's workspace"; [stage-3-implementation.md][p-s3i], "Resolve the choices"; [claude-code.md][p-cc], "The sprint worktree" | changed by R3.9: the worktree or branch is made right after the start commit, where the question is put once; the implementation choice states it and asks only a sprint that has none. "Orchestrator" is the build lead; the provider's throwaway worktree is named in the provider note (R3.2) |
| Choice 3, adversarial pass (L116) | [stage-3-implementation.md][p-s3i], "Resolve the choices" | changed by R3.2: "a separate reviewer" for "a reviewer agent", and where no reviewer can be started the session stops and asks instead of reviewing its own work |
| Choice 4, commit cadence (L117) | [stage-3-implementation.md][p-s3i], "Resolve the choices" | changed by R3.5 and R3.10: the cadence also authorizes a parallel group's commits and the Ready commit of the close, and "don't commit" makes a group serial |
| Choice 5, implementer (L118) | [stage-3-implementation.md][p-s3i], "Resolve the choices", "Which implementer a step gets" | changed by R3.2: the default is a separate implementer, not the `sprint-coder` agent, and where none can be started the build lead's own session is the implementer |
| Choice 6, summary first (L119) | [stage-3-implementation.md][p-s3i], "Resolve the choices"; [SKILL.md][p-skill], "Gates" | changed by R3.5: the summary also says which steps run in parallel, or why they run serially. "The final go-ahead checkpoint" is said plainly: the user's word to implement is the gate, and the summary, printed and not waited on as in v1, is their chance to stop it |
| Loop: per unit, and who commits (L121-123) | [stage-3-implementation.md][p-s3i], "Loop over the in-scope units" | changed by R3.7: a member of a parallel group makes one commit; every other commit is the build lead's, v1's orchestrator (R3.2) |
| Loop: adversarial before commit, commit prefix, stay observable (L124-126) | [stage-3-implementation.md][p-s3i], "Loop over the in-scope units" | carried |
| Loop: stop on trouble (L127) | [stage-3-implementation.md][p-s3i], "Loop over the in-scope units" | changed by R3.4: STATE is written before the pause |
| Completion: when, the offer, the move (L129-134) | [completion.md][p-done], "Archiving" | changed by R3.10, R3.9 and R3.4: archiving follows integration, is one change on the default branch, and deletes STATE |
| `DONE/README.md` format and its guard (L136-150) | [completion.md][p-done], "`DONE/README.md` format" | carried |
| Feature is a short name (L152) | [completion.md][p-done], "`DONE/README.md` format" | changed by R3.8: `Code-complete` joins the outcome qualifiers |
| Long cells are fragile (L154) | [completion.md][p-done], "`DONE/README.md` format" | carried |
| Example: PLAN step and TASKS line (L156-175) | [stage-3-plan-tasks.md][p-s3p], "Example" | carried |
| Example: commit message (L177) | [stage-3-implementation.md][p-s3i], after "Loop over the in-scope units" | carried, reworded: the step is named in the sentence |

## `epic-implementation.md`

| v1 location | v2 location | Status |
|-------------|-------------|--------|
| Frontmatter `paths:` (L1-5) | [SKILL.md][e-skill], frontmatter `description` | changed by R3.1: loaded by its description, not by path globs |
| Title and opening (L7-9) | [SKILL.md][e-skill], opening | carried, reworded: the stage chain is a diagram and ends in Completion |
| Above the sprint workflow, a thin layer (L11) | [SKILL.md][e-skill], opening | carried, reworded: directory and names only |
| Hierarchy at a glance (L13-19) | [conventions.md][e-conv], "Hierarchy at a glance" | changed by R3.4: the sprint row lists `STATE` |
| Epic numbering: the index (L21-26) | [conventions.md][e-conv], "Epic numbering" | carried, reworded: directory and names only |
| Epic numbering: sprint numbers, slugs are durable (L27-28) | [conventions.md][e-conv], "Epic numbering" | carried, reworded: directory and names only |
| File naming (L30-40) | [conventions.md][e-conv], "File naming" | carried, reworded: directory and names only |
| Slug uniqueness (L42-48) | [conventions.md][e-conv], "Slug uniqueness" | carried, reworded: directory and names only |
| Stage E0: the shared backlog (L50-52) | [stage-e0-backlog.md][e-s0] | changed by R3.13 and R3.9: the backlog has the numbered form and changes only on the default branch |
| Stage E0: starting an epic, pluck and delete (L53) | [stage-e0-backlog.md][e-s0] | changed by R3.13: the item's document is deleted with it, and THOUGHTS names its number |
| Stage E0: gate (L54) | [stage-e0-backlog.md][e-s0]; [SKILL.md][e-skill], "Gates" | carried, reworded: directory and names only |
| Stage E1: EPIC THOUGHTS (L56-62) | [stage-e1-thoughts.md][e-s1] | changed by R3.13 and R3.9: a plucked item's document is deleted with it, and the file and the index bump are written on the default branch |
| Stage E2: the charter and its sections (L64-73) | [stage-e2-charter.md][e-s2] | carried |
| Stage E2: promote, don't copy (L75) | [stage-e2-charter.md][e-s2] | carried |
| Stage E2: critical pass (L77) | [stage-e2-charter.md][e-s2] | changed by R5.4: its findings are put to the user as the question settings say |
| Stage E2: user review, gate (L79) | [stage-e2-charter.md][e-s2]; [SKILL.md][e-skill], "Gates" | carried |
| Stage E3: explore, create the ROADMAP, living tracker (L81-85) | [stage-e3-roadmap.md][e-s3], opening | changed by R3.9: the ROADMAP is written and changed only on the default branch |
| ROADMAP file structure (L87-106) | [stage-e3-roadmap.md][e-s3], "ROADMAP file structure" | changed by R3.9: the Docs link points at the sprint's THOUGHTS file, which is on the default branch from the start commit, where v1 linked the PRD. Its cross-references point to the conventions file |
| The seam, handing off to the sprint workflow (L108-116) | [stage-e3-roadmap.md][e-s3], "The seam" | changed by R3.9: each edit of the row is made on the default branch, never in the sprint's worktree; the first goes into the sprint's start commit, and the Docs link points at THOUGHTS |
| ROADMAP maintenance (L118-122) | [conventions.md][e-conv], "ROADMAP maintenance" | carried |
| Epic status vocab (L124-130) | [conventions.md][e-conv], "Epic status vocab" | carried |
| Traceability (L132-136) | [conventions.md][e-conv], "Traceability" | carried, reworded: directory and names only |
| Completion and archiving (L138-144) | [completion.md][e-done], opening, "Closing an epic as `Abandoned`" | changed by R3.9, R3.8 and R3.11: done on the default branch, each commit a separate decision; `DEFERRED.md` is looked at before the offer; an epic can close as `Abandoned` |
| `DONE/README.md` Epics table (L146-156) | [completion.md][e-done], "`DONE/README.md` — Epics table" | carried |
| Example: EPIC THOUGHTS header (L158-167) | [stage-e1-thoughts.md][e-s1], "Example" | carried |
| Example: ROADMAP row and sprint up-link (L169-181) | [stage-e3-roadmap.md][e-s3], "Example" | changed by R3.9: the row's Docs link points at the archived THOUGHTS file, where v1 linked the PRD |

## `agents/sprint-coder.md`

The agent's duties are now "The implementer's part" of
[stage-3-implementation.md][p-s3i]. Its section names are quoted below without the file.

| v1 location | v2 location | Status |
|-------------|-------------|--------|
| Frontmatter: name, when to use, examples (L1-3) | [SKILL.md][p-skill], frontmatter `description` and the Implementation rows of "Stages and their files" | dropped under R3.2: the process names no agent. When the stage applies is said by the skill; an agent's own description belongs to a role definition (R4.1) |
| Frontmatter: tools, model, memory (L4-7) | none in the process; a role's profile and limits, as in [`roles/coder/role.toml`][coder] | dropped under R3.2: an agent's configuration belongs to a role definition (R4.1), with its model set by tier (R5.2) |
| Persona (L9) | "The implementer's part", opening | carried, reworded: "the implementer" takes finalized PLAN/TASKS and ships against them; no persona (R3.2) |
| Source of truth for workflow discipline (L11-20) | [stage-3-implementation.md][p-s3i], opening; "The implementer's part", opening | changed by R3.1: the rules are read from [conventions.md][p-conv], not preloaded as a user-level rule. Its "≤2 lines" for annotations is changed by R3.12 |
| Your scope (L22-24) | "Scope" | carried, reworded: "outside the implementer's part" for "outside this agent's lane" |
| Execution loop 1, locate the work (L26-28) | "Execution loop", 1 | carried, reworded: directory and names only |
| Execution loop 2 and 3, read before writing, flip to in-progress (L30-32) | "Execution loop", 2 and 3 | carried |
| Execution loop 4, implement (L34) | "Execution loop", 4 | carried, reworded: "the project's instruction file" and "standing feedback recorded for this project" for `CLAUDE.md` and auto-memory, and "Explore in parallel" for "Spawn parallel sub-explorations" (R2.4) |
| Execution loop 5, self-verify (L36) | "Execution loop", 5 | carried |
| Execution loop 6, close out (L38) | "Execution loop", 6 | changed by R3.12: the annotation is one line of at most 300 characters; more goes in the report |
| Execution loop 7, report (L40) | "Execution loop", 7 | carried, reworded: "build lead" for "orchestrator" (R3.2) |
| Hard rules: heading and scope (L42-44) | "Hard rules" | carried, reworded: they are part of the process now, not additions to it |
| Hard rules: you do not commit, ever (L46) | "Hard rules"; "As a member of a parallel group" | changed by R3.7 and R3.2: a member of a parallel group makes exactly one commit in its own worktree. "Do not commit even when the user appears to authorize it in-thread" now binds only an implementer that is a separate session; a single session that is both parts commits as the build lead, at the cadence |
| Hard rules: rollbacks, dead code, `git -C`, environment, push back (L47-51) | "Hard rules" | carried |
| When to stop and ask (L53-57, L59-61) | "When to stop and ask" | carried |
| When to stop and ask: the change requires a commit (L58) | "When to stop and ask" | changed by R3.7: a group member's one commit is excepted |
| Checklist: TASKS line, PLAN annotation (L63-66) | "Checklist before reporting done" | changed by R3.12: the line at most 150 characters, the annotation one line of at most 300 |
| Checklist: Last updated, verification, scope (L67-69) | "Checklist before reporting done" | carried |
| Checklist: no commits at all (L70) | "Checklist before reporting done" | changed by R3.7: a group member makes one commit and changes no sprint doc |
| Checklist: report leads with the ID (L71) | "Checklist before reporting done" | carried, reworded: "build lead" for "orchestrator" (R3.2) |
| Persistent Agent Memory (L73-85) | [completion.md][p-done], "Lessons"; the `project-memory` skill | changed by R3.6: one agent's private memory, written as it went, becomes lessons for the project memory, proposed at close and written only on the user's approval (R7.1). v1's lists of what to record and what not are in `references/lifecycle.md` of the `project-memory` skill, and the implementer's report names lesson candidates ([stage-3-implementation.md][p-s3i], step 7) |
| Closing line (L87-89) | "Scope", last sentence | carried, reworded: said of the implementer |

## New in v2, with no v1 counterpart

| What | Requirement | Where |
|------|-------------|-------|
| The entry file: "Read before you act", the table of stages and files, the table of gates | R3.1 | [SKILL.md][p-skill]; [SKILL.md][e-skill] |
| Three parts in place of named agents: the build lead, the implementer, an independent review | R3.2 | [SKILL.md][p-skill], "Who does what"; [stage-3-implementation.md][p-s3i], opening |
| STATE, the fifth sprint doc | R3.4 | [state.md][p-state]; [stage-3-implementation.md][p-s3i], "Picking up a sprint in progress", choice 7, "Keep STATE current" |
| Where each doc is written, the one commit that starting a sprint authorizes, and the sprint's workspace made right after it | R3.9, decisions H and I | [conventions.md][p-conv], "Where each doc is written", "The sprint's workspace"; [stage-1-thoughts.md][p-s1]; [conventions.md][e-conv], "Where each doc is written" |
| Settings: the sprint docs directory, and how questions are put to the user | R3.3, R5.3, R5.4 | [SKILL.md][p-skill], "Settings"; [conventions.md][p-conv], "The sprint docs directory", "Questions to the user"; [`scripts/settings.py`][p-set] in each skill |
| Parallel groups and the `light` and `hard` tags, with a group member's one commit | R3.5, R3.7, decision R | [stage-3-plan-tasks.md][p-s3p], "Marks on a step"; [stage-3-implementation.md][p-s3i], "Which implementer a step gets", "Parallel groups", "As a member of a parallel group" |
| Exact limits: an annotation 300 characters, a TASKS line 150, and how they are counted | R3.12 | [conventions.md][p-conv], "Format limits" |
| Deferred items, and closing a sprint as code-complete | R3.8 | [deferred.md][p-def]; [completion.md][p-done], "Closing as code-complete" |
| The backlog item form: one numbered line, an item document, the one-time conversion | R3.13 | [stage-0-backlog.md][p-s0], "The file", "Numbers", "A longer idea"; [backlog-conversion.md][p-conv1] |
| Integration at completion: merge, removal of the worktree and branch, the roadmap row | R3.10 | [completion.md][p-done], "Integration"; [conventions.md][e-conv], "ROADMAP maintenance" |
| Abandon and supersede | R3.11 | [abandon.md][p-ab]; [completion.md][e-done], "Closing an epic as `Abandoned`" |
| Lessons at sprint close | R3.6 | [completion.md][p-done], "Lessons" |
| The check command, with its Notes section and the lesson index check | R3.14, R7.4 | [`scripts/check.py`][p-check]; [deferred.md][p-def], "The check command" |
| Provider notes: putting a question, running a review, handing work to an implementer | R3.2, R2.4 | [claude-code.md][p-cc]; [codex.md][p-cx] |

[p-skill]: ../prd-implementation/SKILL.md
[p-conv]: ../prd-implementation/references/conventions.md
[p-s0]: ../prd-implementation/references/stage-0-backlog.md
[p-s1]: ../prd-implementation/references/stage-1-thoughts.md
[p-s2]: ../prd-implementation/references/stage-2-prd.md
[p-s3p]: ../prd-implementation/references/stage-3-plan-tasks.md
[p-s3i]: ../prd-implementation/references/stage-3-implementation.md
[p-done]: ../prd-implementation/references/completion.md
[p-ab]: ../prd-implementation/references/abandon.md
[p-state]: ../prd-implementation/references/state.md
[p-def]: ../prd-implementation/references/deferred.md
[p-conv1]: ../prd-implementation/references/backlog-conversion.md
[p-cc]: ../prd-implementation/references/claude-code.md
[p-cx]: ../prd-implementation/references/codex.md
[p-set]: ../prd-implementation/scripts/settings.py
[p-check]: ../prd-implementation/scripts/check.py
[e-skill]: ../epic-implementation/SKILL.md
[e-conv]: ../epic-implementation/references/conventions.md
[e-s0]: ../epic-implementation/references/stage-e0-backlog.md
[e-s1]: ../epic-implementation/references/stage-e1-thoughts.md
[e-s2]: ../epic-implementation/references/stage-e2-charter.md
[e-s3]: ../epic-implementation/references/stage-e3-roadmap.md
[e-done]: ../epic-implementation/references/completion.md
[coder]: ../roles/coder/role.toml
