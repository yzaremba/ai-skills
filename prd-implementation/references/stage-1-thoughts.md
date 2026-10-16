# Stage 1 — THOUGHTS (brainstorm)

Read [conventions.md](conventions.md) first: the sprint number comes from `SPRINT-INDEX.md` in the sprint docs directory, whose whole form is under "Sprint numbering" there, and the file name follows the naming pattern. Do not look for the index's form anywhere else.

- THOUGHTS for a new sprint typically starts by plucking items from `BACKLOG.md` (Stage 0, [stage-0-backlog.md](stage-0-backlog.md)). The plucked items should be **deleted from the backlog** as part of the same change that creates this file, each with its item document if it has one; name each item's number (`B12`) where this file quotes or paraphrases it.
- The user may create `SPRINTXX-THOUGHTS-<Description>.md` themselves or ask you to create it.
- Put these lines at the **top** of the file (before freeform notes), then a blank line:
  - `Sprint: NN` (match the filename's sprint)
  - `Slug: <kebab-case-slug>` (must match the `<Description>` segment in every filename of the set)
  - `Epic: NN` *(optional)* — include only when this sprint belongs to a multi-sprint epic; this is the up-link to the `epic-implementation` skill, a number and not a link. Omit for standalone sprints.
- An epic doc, another sprint's doc, a backlog item document or any other doc this file refers to is named by its file name in backticks, never linked ("Links and names" in [conventions.md](conventions.md)). A plucked item is named by its number; its document is deleted with it.
- No line of the file records an approval or a review ("No approval in a doc" in [conventions.md](conventions.md)).
- Content below is **intentionally unstructured**: bullets, questions, rough ideas, unordered notes. No need for full sections or IDs.
- After creating the first file of a new sprint, update the index (see [conventions.md](conventions.md)): overwrite the latest assigned `NN`, and add nothing else.
- **Where, and the one commit.** The first THOUGHTS file and the index bump are written in the working tree that has the default branch checked out (if none has, ask the user) and committed there as **one local commit**, with the other changes that belong to starting the sprint: the plucked backlog items, their deleted item documents and, for a sprint of an epic, its roadmap row. Commit only those files, by name. The user's signal to start the sprint authorizes exactly that commit, so the number is taken before another session can assign it. Do not push it, and do not take it as leave for any later commit.
- **Then the sprint's workspace, at once.** Right after that commit, make the sprint's worktree or branch, as "The sprint's workspace" in [conventions.md](conventions.md) says; the question of which is put to the user there, once. All further work on the sprint's own docs happens in that workspace, more brainstorming in this file included: nothing of the sprint's own is written on the default branch again until the close. With sprint docs in a separate repository this does not apply to the docs, which stay on that repository's default branch.
- **Gate:** Before writing a PRD, **confirm with the user** that THOUGHTS are ready to turn into requirements. If they want more brainstorming, stay in this stage.

Next: [stage-2-prd.md](stage-2-prd.md), once the user has confirmed.
