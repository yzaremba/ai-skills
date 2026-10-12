# Abandoning or superseding a sprint

Read [conventions.md](conventions.md) first. This closes a sprint that will not finish, at any stage from THOUGHTS on, and records why.

- **Abandoned**: the sprint is dropped. **Superseded**: another sprint replaces it, and that sprint is named.
- **It is always the user's decision.** Propose it when a sprint has lost its reason; never decide it, and never treat a stalled sprint as abandoned.
- It is not a way round the other closes. A sprint whose work is done apart from residuals or waiting steps closes as [completion.md](completion.md) says.
- **A code-complete sprint is not abandoned.** Its code has landed and its docs are archived. What remains of it are its items in `DEFERRED.md`, and each is resolved or dropped as [deferred.md](deferred.md) says; when the last is closed, its Completed cell becomes a plain date. This procedure does not apply to it.
- **No work is removed by this procedure.** It closes the docs and reports what is left.

## The steps

1. **Record the reason**, in the sprint's own docs, where they are written (the sprint's worktree or branch, once it has one). On the PLAN it is the header's status. Before a PLAN exists it is a line of its own in THOUGHTS, directly under the header lines. One line in either place:

   ```markdown
   **Status:** Abandoned 2026-10-05 — the provider withdrew the API this was built on
   **Status:** Superseded 2026-10-05 by sprint 12 — the redesign covers it; work left on `sprint/09-export-v2`
   ```

   When unmerged work stays (step 3), the line names its branch, as the second example does: STATE will be gone, and this is what still says where the work is.
2. **Close every open TASKS line**, `[ ]` and `[~]`, as skipped with the reason: `(skipped: sprint abandoned)` or `(skipped: superseded by sprint NN)`. The steps get no `> Audit` annotation each: the status line covers them. One exception: a step that was in progress and has code gets `> Audit YYYY-MM-DD: NOT DONE: <what exists of it>`, because STATE held that until now. **Delete the STATE file** in the same change, if there is one; first take from it the workspace and every worktree it lists, for steps 3 and 5, and its lesson candidates, which the report of this change carries. Steps 1 and 2 are one change; its commit is a separate decision of the user, so ask for it. STATE is not written again after this change, in the sprint's worktree or anywhere else: what the close still has to track is in the status line and in the report of step 5.
3. **Settle the work, without removing any.** Look at what the sprint has beyond the default branch: its worktree and branch, the commits on the branch that the default branch lacks (`git log <default branch>..sprint/NN-slug`), uncommitted files, a copy of the branch on a remote, and member worktrees of a parallel group that STATE listed. Put it to the user:
   - **Keep it**: the branch is merged on the user's authorization and then removed, as "Integration" in [completion.md](completion.md) says. The change of steps 1 and 2 is committed first, with whatever else is uncommitted, on the user's word: that is this sprint's Ready commit, and the worktree must be clean for `git worktree remove`.
   - **Leave it**: the worktree and the branch stay as they are, on the remote too. Nothing is reset, stashed or discarded. A later decision to keep that work is not a continuation of this sprint: it is a new sprint, or a deliberate merge that the user resolves, because the docs copied into `DONE/` in step 4 will conflict with the branch's own copies. The report of step 5 says so.

   **Removing unmerged work is the user's call.** A worktree or branch with commits that are not on the default branch is removed only when the user says so, for that worktree or branch; `--force` and `-D` are never used on the process's own initiative, and deleting a branch on a remote is a push.
4. **Archive the docs that exist**, as one change on the default branch, as "Archiving" in [completion.md](completion.md) says and with these differences:
   - The set is whatever exists: THOUGHTS alone, or with a PRD, or all four. A doc that is only on an unmerged branch is copied into `DONE/` from the sprint's worktree or branch, and replaces the older copy the default branch has of THOUGHTS.
   - The row in `DONE/README.md` has `—` in the cell of a doc that does not exist, and its Completed cell reads `Abandoned YYYY-MM-DD` or `Superseded YYYY-MM-DD by NN`.
   - **The sprint number stays used.** Numbers are never reused: the index is not lowered, also when the sprint was the latest one.
   - **A sprint of an epic**: its roadmap row becomes `Skipped` with a one-line reason, and stays in the table ("Scope changes" in the conventions of the `epic-implementation` skill). A sprint that supersedes it gets a row of its own.
   - The commit of this change is a separate decision of the user, and a push another.
5. **Report** what was closed and everything that is left in place: each worktree by its path, each branch with the number of commits the default branch lacks and whether a remote has it, and any uncommitted files. For work left in place, name what a later decision to keep it means (step 3).

Lessons are put to the user with the archive offer of step 4, and the approved ones are written where "Lessons" in [completion.md](completion.md) says: with sprint docs in a separate repository, not in the docs repository.

An idea of the abandoned sprint that should still be done goes to the backlog as a new item with a new number, on the user's word ([stage-0-backlog.md](stage-0-backlog.md)). The numbers of the items it was started from are not used again.

## When there is no sprint branch

- **Before the sprint has a worktree or branch** (only the start commit exists), or **in place on the default branch** (a sprint that predates the rule that the workspace is made right after the start commit): steps 1, 2 and 4 are one change on the default branch, and step 3 has only uncommitted files to report.
- **Sprint docs in a separate repository**: steps 1, 2 and 4 are one change on that repository's default branch, and nothing is copied. Step 3 applies to the code, in its own repository.
