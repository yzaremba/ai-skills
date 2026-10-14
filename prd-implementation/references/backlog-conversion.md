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
   - It is longer, has sub-bullets, or holds a code block or a table: its full original text goes, unchanged, into `BACKLOG-B<n>-<slug>.md`, and the item becomes one line that names the idea and ends with the link to that document.
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
