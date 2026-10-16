# Stage E1 — EPIC THOUGHTS (brainstorm)

Read [conventions.md](conventions.md) first: the epic number comes from the index, and the file name follows the naming pattern. The items that seed this file come from the backlog (Stage E0, [stage-e0-backlog.md](stage-e0-backlog.md)) and are deleted from it, each with its item document if it has one, in the same change that creates the file.

- The user may create `EPICXX-THOUGHTS-<Description>.md` themselves or ask you to. Put these lines at the **top** (before freeform notes), then a blank line:
  - `Epic: NN` (match the filename)
  - `Slug: <kebab-case-slug>` (must match the `<Description>` segment in all three filenames)
- Content below is **intentionally unstructured**: the problem, rough scope, candidate sprints, sequencing hunches, open questions, risks.
- After creating the first file of a new epic, update the index (see [conventions.md](conventions.md)): overwrite the latest assigned `NN`, and add nothing else.
- The file and the index bump are written on the default branch (see "Where each doc is written" in [conventions.md](conventions.md)).
- **Gate:** Before writing the PRD, **confirm** the brainstorm is ready to become a charter. Stay here if more brainstorming is wanted.

## Example (EPIC THOUGHTS header)

EPIC THOUGHTS header:

```markdown
Epic: 01
Slug: payments-platform

Rough idea: replace the bolt-on billing with a first-class payments service…
```

Next: [stage-e2-charter.md](stage-e2-charter.md), once the user has confirmed.
