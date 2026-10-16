# Converting an existing backlog (one time)

A backlog written before items had numbers is free-form: bullets, items of several lines, half-thoughts. This procedure brings it into the form [stage-0-backlog.md](stage-0-backlog.md) defines. Read that file first.

- **It runs once per project, on the user's word.** A `BACKLOG.md` that has a `Latest assigned:` line is converted; never run this on it again, because that would renumber items.
- **It is one change, on the default branch**, in the working tree that has the default branch checked out (see "Where each doc is written" in [conventions.md](conventions.md)). The change holds the backlog file and the item documents it creates, and nothing else.
- **It changes the form, never the content.** No idea is dropped, merged, reworded beyond what one line needs, or re-prioritised. Pruning the backlog is a separate decision of the user.

## Procedure

1. **Check the starting point.** `BACKLOG.md` has no uncommitted change and no `Latest assigned:` line. If it has uncommitted changes, ask the user before going on.
2. **Read the whole file and mark the items**, without writing anything yet. A top-level bullet is one item, together with its sub-bullets and continuation lines. A paragraph that stands alone is one item. Grouping headers are kept as they are.
3. **Number the items in file order**, top to bottom, from `B1`. The order in the file is the only order there is: do not sort by priority, age or topic.
4. **Decide the form of each item.**
   - It fits one line of at most 300 characters without losing anything: it becomes `- **B<n>** <text>`, in its own words. A priority tag it already has moves to directly after the number.
   - It is longer, has sub-bullets, or holds a code block or a table: its full original text goes, unchanged, into `BACKLOG/B<n>-<slug>.md`, and the item becomes one line that names the idea and ends with the link to that document.
   - It holds several unrelated ideas: it is still one item, pointing to a document, unless the user says to split it. A split gives each part its own number, in the order the parts appear.
5. **Put the doubtful cases to the user before writing**: the items that would be split, any text that is not an item (an introduction, a note to self, a dated log), and any item whose one-line name you had to invent. Text that is not an item is deleted or moved only as the user says.
6. **Write the change**: the title `# Backlog` if the file has none, then the pointer line `Latest assigned: B<n>` with the highest number assigned, above the first item; the item lines under their headers; the item documents.
7. **Verify.**
   - Run the check command ([deferred.md](deferred.md)): it reports no violation for the backlog.
   - Count: the items marked in step 2, plus the parts added by splits, equal the item lines in the file, and the pointer line holds the highest number.
   - Nothing is lost: every line of the old file, as `git show HEAD:<docs>/BACKLOG.md` prints it, is in the new file or in an item document, apart from what the user said to delete. The item documents are new and untracked, so `git diff` does not show them: read them.
8. **Report and stop.** Tell the user how many items there are, which got documents and which were split. The commit is the user's decision; propose one commit holding exactly this change.

## Afterwards

- Numbers assigned here are permanent from the moment the change is committed. If the user rejects the result before a commit, discard the change and start again; after a commit, fix an item in place and leave its number.
- Other docs did not cite backlog numbers before the conversion, so nothing else needs editing. A THOUGHTS file that quotes an item plucked earlier stays as it is.

## Item documents at their earlier place

A backlog converted before item documents had their folder keeps them beside `BACKLOG.md` as `BACKLOG-B<n>-<slug>.md`, and its items link to those names. The check command reports this once, as a note for the backlog. Moving them is one change on the default branch, in the working tree that has it checked out, made on the user's word. The links of steps 3 to 5 are text, fixed by whoever keeps the backlog; the deletions and moves of steps 1 and 2 are exact commands, which another session may run. Step 6 is the keeper's. The change holds the moved documents, `BACKLOG.md` and the links that steps 3 and 5 fix, and nothing else.

1. **Check the starting point.** A document the note says is also in `BACKLOG/` has two copies: compare them. The same text: delete the copy beside `BACKLOG.md` instead of moving it, with `git rm`, or a plain delete if git does not track it. Different text: put both to the user before going on.
2. **Move each document**, keeping its number and slug: from the sprint docs directory, after creating the folder `BACKLOG/` there, `git mv BACKLOG-B<n>-<slug>.md BACKLOG/B<n>-<slug>.md`. A document git does not track, as an uncommitted conversion leaves it, is moved with a plain move instead. Its name in the folder starts with a capital `B`, whatever the case of the earlier name.
3. **Fix the links inside each moved document.** A link to a sprint's or an epic's doc becomes that doc's file name in backticks, as "Links and names" in [conventions.md](conventions.md) says: `[plan](SPRINT07-PRD-x.md)` becomes ``plan (`SPRINT07-PRD-x.md`)``. Any other relative link now starts one folder deeper: `../src/a.py` becomes `../../src/a.py`, and a link to another moved document, `BACKLOG-B4-y.md`, becomes `B4-y.md`. A URL, an anchor in the same file and an absolute path stay as they are.
4. **Point each item's link to the new place**: in `BACKLOG.md`, the target `BACKLOG-B<n>-<slug>.md` becomes `BACKLOG/B<n>-<slug>.md`. Nothing else in the file changes: no number, text, tag or order.
5. **Fix the links from other files.** Search the repository for `BACKLOG-B`, `DONE/` left out: a sprint doc, `DEFERRED-context.md` or a lesson of the project memory may link to a moved document. Each such link becomes the document's name in backticks, its link text kept, as in step 3: `[notes](BACKLOG-B9-a.md)` becomes ``notes (`B9-a.md`)`` ("Links and names" in [conventions.md](conventions.md)). A doc in `DONE/` is left as it is, and a name whose document was deleted with its item earlier stays as it is.
6. **Verify and stop.** The check command reports no note and no violation for the backlog: nothing at the earlier place, no document missing and no orphan. A second search for `BACKLOG-B` finds no reference to a moved document outside `DONE/`. `git status` shows the moves, `BACKLOG.md` and the files whose links were fixed, and nothing else. The commit is the user's decision; propose one commit holding exactly this change.
