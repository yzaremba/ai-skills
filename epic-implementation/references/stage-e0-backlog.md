# Stage E0 — Promote from BACKLOG

Read [conventions.md](conventions.md) before creating or editing an epic doc.

- Epic-scale ideas live in the shared `BACKLOG.md` in the epic docs directory (the same backlog the sprint workflow uses — there is no separate epic backlog). It changes only on the default branch.
- **The backlog's form is the sprint workflow's**: an item is one line, `- **B<n>** <text>`, with a number that is stable and never reused, under a `Latest assigned: B<n>` pointer line; a longer idea goes in a dedicated document, `BACKLOG/B<n>-<slug>.md` in a folder beside `BACKLOG.md`, that the one line points to. An epic-scale idea usually needs such a document. The exact form and the numbering rules are in the backlog stage of the `prd-implementation` skill: read it before adding, editing or plucking an item.
- **Starting an epic:** the user picks one or more backlog items that together form a multi-sprint theme. Those items seed `EPICXX-THOUGHTS-<slug>.md`. **Delete** the plucked items from `BACKLOG.md` in the same change, and with each its dedicated document if it has one — traceability lives in the new THOUGHTS file, which should quote or paraphrase the original idea and name its number (`B12`). The pointer line stays as it is: a plucked number is not free again.
- **Gate:** Do not start an epic without an explicit signal that the effort is **epic-sized** (multi-sprint). If it fits one sprint, use the `prd-implementation` skill instead.

Next: [stage-e1-thoughts.md](stage-e1-thoughts.md), once the user has given that signal.
