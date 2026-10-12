## Worktrees of a parallel group

A group runs in parallel only when the PLAN marks it; unmarked steps run one after another in the sprint's workspace. The stage file your binding names sets out the steps under "Parallel groups". These rules hold through all of them:

- **At most `roles.max_parallel_coders` Coders at work at once**, a setting of the project, and only tasks within one phase.
- **A clean, committed base.** Record the workspace's HEAD before the first worktree is made. A "don't commit" cadence cannot be combined with a parallel group.
- **One worktree and one branch per Coder**, made from that commit under the project's worktree root, never inside the workspace. The brief gives the worktree's path in full.
- **Join before review.** Before the first merge, check that the workspace's HEAD is still the recorded commit; if it is not, stop and report. Merge each branch with a real merge, never a squash, then run the full suite. The adversarial pass and the cadence commit wait for the whole group.
- **A Coder fails:** wait for the rest of the group, then stop and report.
- **A merge conflicts:** the parallel claim was wrong. Keep what merged cleanly and dispatch the conflicting task again, serially, on top. Never resolve the conflict by hand.
- **Finished means merged, and git verifies it.** Remove each merged worktree and branch without being asked, with the non-forcing remove and the non-forcing branch delete only. If either refuses, the work is not finished.
- **Never force.** An unmerged worktree stays and is listed in your report with a one-line reason. Forcing is the user's call.
- **Sweep at start.** Starting on a sprint, look for worktrees an earlier run left: remove the merged ones, report the unmerged.
- **The sprint itself** is the Manager's to remove. Once its branch is verifiably merged into trunk, its worktree and local branch are removed without a separate request. Deleting a remote branch is a push: it rides on the user's word for the push that lands the merge.
