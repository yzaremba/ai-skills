# Completion and archiving

Read [conventions.md](conventions.md) first. A sprint that closes with tasks still open follows "Sprint closure with residuals" there before anything below; open steps that only wait follow "Closing as code-complete". A sprint that will not finish is not closed here: [abandon.md](abandon.md).

A sprint closes in this order: its last open steps are settled, its work is **integrated**, **lessons** are proposed, and its docs are **archived**, the approved lessons with them. The build lead closes it.

## Closing as code-complete

A sprint whose only open steps wait on elapsed time or on an outside event does not stay open for them. On the user's word it closes as **code-complete**: each waiting step becomes an item in `DEFERRED.md`, and its PLAN step and TASKS line are closed as [deferred.md](deferred.md) says. Read that file before closing such a sprint.

After that no checkbox is open, and the sprint is integrated and archived like a finished one, with one difference: the PLAN header's status and, in `DONE/README.md`, the sprint's Completed cell read `Code-complete YYYY-MM-DD`. When the sprint's last deferred item is closed, resolved or dropped, the cell becomes that day's date, without the qualifier; the PLAN's status stays, a record of how the sprint closed. A code-complete sprint is not abandoned later: what remains of it is settled item by item, as [deferred.md](deferred.md) says.

Its epic roadmap row becomes `Done`, like a finished sprint's: the code has landed, and the sprints that depend on it may start. What still waits is in `DEFERRED.md` and in the Completed cell, not in the row.

## Integration

When no TASKS checkbox is open, the sprint's work is brought to the default branch before its docs are archived.

**Each of these needs the user's authorization, and each is a separate decision**: the merge to the default branch, the commit of the archive change, and any push. Put them to the user as "Questions to the user" in [conventions.md](conventions.md) says. An answer to one is not an answer to another, and the commit cadence authorizes none of them: it covered the commits on the sprint's own branch and nothing after.

1. **Ready.** First, a member worktree of a parallel group that STATE still lists is dealt with: a merged one is removed with `git worktree remove` and `git branch -d`, run from the sprint's workspace and never forced, and an unmerged one is put to the user. Integration waits for their answer. Then the PLAN header's status is set to `Completed YYYY-MM-DD`, or `Code-complete YYYY-MM-DD` for a sprint closed as code-complete, with the day of the Ready commit, which the `DONE/README.md` row repeats; an abandoned or superseded sprint keeps the status [abandon.md](abandon.md) gave it. STATE is written for the last time in the sprint's workspace, with `closing` on its "Written" line and the merge as its next action, and **the Ready commit** is made: it holds everything still uncommitted, the audit annotations, the skipped flips, that status and that STATE among it. The commit cadence covers the Ready commit under every cadence except "don't commit"; under "at completion" it is that cadence's commit. Under "don't commit" it is made on the user's word, or integration does not start. After it the sprint's workspace holds nothing uncommitted, and it stays that way: **from here until the archive change deletes it, STATE is not written in the sprint's worktree** ([state.md](state.md)), so a question to the user during the close leaves the worktree clean.
2. **Merge**, on the user's authorization. STATE is not written for this question: the committed copy already names the merge as next. In the working tree that has the default branch checked out (if none has, ask the user): `git merge sprint/NN-slug`, never as a squash or a rebase, so that git can see the branch as merged. Then run the full test suite there. A conflict or a failing suite is trouble: abandon a conflicting merge (`git merge --abort`), then stop and ask, as "Stop on trouble" in [stage-3-implementation.md](stage-3-implementation.md) says, except that after an aborted merge STATE is not written: the default branch has no copy yet, and the committed one still names the merge as next. If the user integrates another way, such as a pull request, wait until the default branch holds the sprint's work, then go on. **From the merge on, a close that has to stop is tracked in the copy of STATE on the default branch**, in that working tree. It may be left uncommitted there; the archive change deletes it.
3. **Remove the sprint's worktree and branch** with `git worktree remove <path>` and `git branch -d sprint/NN-slug`, run from the working tree that has the default branch checked out. Never with `--force` or `-D`. If either command refuses, that work is not finished: the worktree and branch stay, the copy of STATE on the default branch lists them with a one-line reason, and removing them by force is the user's call. The sprint is not archived and STATE is not deleted until the user has said what happens to them. A pull request merged as a squash or a rebase makes `git branch -d` refuse, because git cannot see the branch as merged into the default branch: that refusal goes to the user in the same way, and is not answered with `-D`. A copy of the branch on a remote is left alone: deleting it is a push.
4. **Update the epic roadmap row**, when THOUGHTS carries `Epic: NN`: its Status becomes `Done`. The roadmap is a shared file, so this is written on the default branch, in the archive change below.

Not every sprint has a branch to merge:

- **In place, on a branch of its own.** There is one working tree: switch it to the default branch (`git switch <default branch>`) before step 2. There is no worktree to remove; step 3 is `git branch -d` alone. STATE follows the same rule: not written between the Ready commit and the merge.
- **In place, on the default branch.** This arises only for a sprint whose docs are in a separate repository, or one that predates the rule that a sprint gets its workspace right after the start commit. The work is already there. Steps 2 and 3 fall away; step 1 still holds.
- **Sprint docs in a separate repository.** The docs were committed on that repository's default branch all along, so nothing of the docs is merged. Steps 1 to 3 apply to the code, in its own repository, as far as it has a branch. STATE is in the docs repository, so writing it never dirties the code's worktree: it is written through the close as at any other time, and the audit annotations, the skipped flips, the PLAN header's status and STATE are committed there with the other sprint docs, not in the code's Ready commit. Step 4 and the archive change are made in the docs repository, on its default branch.

## Archiving

When **all TASKS checkboxes** are resolved (no `- [ ]` or `- [~]`) and the sprint is integrated:

1. **Offer** to move the sprint set to `DONE/` in the sprint docs directory: THOUGHTS, PRD, PLAN, TASKS (same filenames). With the offer, **propose the lessons** ("Lessons" below).
2. After the user agrees, make **the archive change**, as one change **on the default branch**: move those files; update `DONE/README.md` with one row for the feature; ensure **`SPRINT-INDEX.md`** still reflects the highest `NN` in use (it should match the archived sprint unless newer sprints exist in the sprint docs directory); **delete the STATE file**, which is never archived ([state.md](state.md)); for a sprint of an epic set its roadmap row, Status as above and the Docs link pointing into `DONE/`; and write each lesson the user approved (with sprint docs in a separate repository the lessons are a change of their own: "Lessons" below).
3. **Ask for the commit** of that change. It is a separate decision of the user, and so is a push of the default branch afterwards.

If the user declines the move, the set stays where it is and the rest of the change is still made: STATE is deleted, the roadmap row is set and the approved lessons are written.

`DONE/README.md`, the sprint index, the roadmap and `DEFERRED.md` are shared between sprints, so they change on the default branch (see "Where each doc is written" in [conventions.md](conventions.md)). The sprint's own docs are there too by now: the merge brought them, and that is why the move is made after it and not in the sprint's worktree.

## Lessons

When a sprint closes, whether finished, code-complete or abandoned, the build lead looks back once and **proposes** what is worth keeping: the lesson candidates the implementers' reports named, which STATE holds ([state.md](state.md)), and what the build lead saw itself. They are put to the user with the offer to archive, before the archive change, so that the approved ones are written in that change and committed with it. A build lead that cannot ask the user names them earlier, in the report of the change that writes the last STATE (step 1 of "Integration"); for an abandoned sprint, of the change that deletes it.

- **A lesson about the project** (a trap in the code, a check that would have caught a bug, a fact about a provider) is proposed for the project memory. The `project-memory` skill says what is worth recording and where and how such a lesson is written; follow it, and do not pick a place of your own. Where that skill is not installed, give the lesson in the closing message and write nothing.
- **A lesson about the process itself** (a rule that was missing, unclear or in the way) is proposed as a change to the process skills. It is the user's to accept: do not edit a skill on your own.
- **Nothing is written without the user's approval**, lesson by lesson. Put each to the user as one or two lines: what happened, and what to do differently.
- **The build lead writes each approved lesson**, its file and its index line, in the archive change. The project memory is shared between sprints and is in the project's repository: with sprint docs in a separate repository, the lessons are a change of their own on the project's default branch, and its commit is a separate decision of the user.
- **"No lessons" is a fine outcome.** Say so in a line. Do not manufacture one to have something to propose, and do not restate what a PLAN annotation or `git log` already holds.

## `DONE/README.md` format

Create the file if missing. Use a table that includes THOUGHTS:

```markdown
# Completed features (sprints)

> **Index, not a changelog.** `Feature` is a short name (≤ ~100 chars) — what shipped, in a phrase. Scope, deviations, bugs found, live-verification notes and residuals live on the sprint's PLAN steps (`> Landed` / `> Bug fix` / `> Audit`) and in `git log`. Never extend a row.

| Sprint | Feature | THOUGHTS | PRD | Plan | Tasks | Completed |
|--------|---------|----------|-----|------|-------|-----------|
| 01 | Short name | [THOUGHTS](SPRINT01-THOUGHTS-slug.md) | [PRD](SPRINT01-PRD-slug.md) | [PLAN](SPRINT01-PLAN-slug.md) | [TASKS](SPRINT01-TASKS-slug.md) | YYYY-MM-DD |
```

Carry that blockquote into the file — the guard belongs where the drift happens, same as in SPRINT-INDEX.

**Feature is a short name, not a changelog.** A row records *that* a sprint shipped and *where its docs are*; the sprint's own docs record *what happened*. Outcome qualifiers (`Abandoned` / `Retracted` / `Superseded` / `Concluded` / `Code-complete`) go in the **Completed** cell, so the name stays a name. This table is an archive **index**; a row that grows into a paragraph is the same drift as a SPRINT-INDEX history log. **Trim rows you notice; never extend one** — and trim by cutting, not by relocating: the prose is already in the sprint docs and `git log`, so do not "rescue" it into an archived PLAN/PRD.

Long cells are also **fragile**, not just noisy: one unescaped `|` — easy to slip in inside inline code like `` `--flag-a|--flag-b` `` — splits the cell and silently shifts every link in that row into the wrong column. A short name has nowhere to hide one.
