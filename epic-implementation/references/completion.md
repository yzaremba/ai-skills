# Completion and archiving

Read [conventions.md](conventions.md) first.

When **every ROADMAP row** is resolved (`Done` or `Skipped`) and the PRD's success criteria are met:

1. **Offer** to move the epic set (THOUGHTS, PRD, ROADMAP) to `DONE/` in the epic docs directory.
2. After the user agrees, move them and add a row to the **Epics** table in `DONE/README.md`. Constituent sprints archive on their own schedule per the `prd-implementation` skill; update the ROADMAP's Docs links to be relative to its new `DONE/` location — sprint sets archived alongside it are bare filenames, sprints still in the epic docs directory itself need a `../` prefix.
3. Ensure `EPIC-INDEX.md` still reflects the highest epic `NN` in use.

All of this is done on the default branch (see "Where each doc is written" in [conventions.md](conventions.md)). Each commit of it, and each push, is a separate decision of the user.

A row is `Done` also for a sprint that closed as code-complete. Before the offer, look in `DEFERRED.md` for open items of the epic's sprints (an item of `Sprint: none` is of no sprint), and put to the user whether the success criteria are met while those wait.

## Closing an epic as `Abandoned`

This follows the sprint rule, the abandon procedure of the `prd-implementation` skill, one level up.

- **It is always the user's decision.** No work is removed by it, and the epic number stays used.
- Each `In progress` sprint is closed first, with that skill: finished or abandoned, as the user decides for each.
- Every remaining `Planned` row becomes `Skipped` with a one-line reason. `Done` rows stay as they are.
- The ROADMAP header's status becomes `Abandoned`, with the date and why, in a line.
- The set is then archived as above, with `Abandoned YYYY-MM-DD` in the Completed cell of its row in the Epics table.

## `DONE/README.md` — Epics table

Add alongside the existing sprint table (create the file if missing):

```markdown
## Completed epics

| Epic | Name | THOUGHTS | PRD | Roadmap | Sprints | Completed |
|------|------|----------|-----|---------|---------|-----------|
| 01 | Short name | [THOUGHTS](EPIC01-THOUGHTS-slug.md) | [PRD](EPIC01-PRD-slug.md) | [ROADMAP](EPIC01-ROADMAP-slug.md) | 07–09 | YYYY-MM-DD |
```
