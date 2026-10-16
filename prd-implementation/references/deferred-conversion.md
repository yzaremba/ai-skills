# Converting an existing deferred file (one time)

A `DEFERRED.md` written before items had numbers is free-form: a title and prose, entries under headings of their own (`## INFRA-01 — …`) with bold fields (`**Added:**`, `**Context:**`, `**Trigger:**`) and paragraphs. This procedure brings it into the form [deferred.md](deferred.md) defines. Read that file first.

- **It runs once per project, on the user's word, and only on a file in the old form** ("A file in the old form" in [deferred.md](deferred.md)). A `DEFERRED.md` with a line that starts `Latest assigned:`, the title `# Deferred items` or a heading `### D<n>` is in the new form; never run this on it, because that would renumber items.
- **It is one change, on the default branch**, in the working tree that has the default branch checked out (see "Where each doc is written" in [conventions.md](conventions.md)). The change holds `DEFERRED.md` and `DEFERRED-context.md`, and nothing else.
- **It changes the form, never the content.** Nothing is dropped, merged or reworded beyond what a field's one line needs. An entry that is already moot is put to the user, not pruned; removing it is a separate decision of the user.

## `DEFERRED-context.md`

Items have no body, so the prose of each entry moves, word for word, to `DEFERRED-context.md` in the sprint docs directory beside `DEFERRED.md`: one section per entry, headed `## D<n> — <old ID>`, or `## D<n>` for an entry that had no ID. It is a plain record of what the old entries said, with one change: the conversion writes a reference to a sprint's or an epic's doc as that doc's file name in backticks, never as a link, since the sprint's close moves the doc ("Links and names" in [conventions.md](conventions.md)). The check command reads it for such links only, and it has no form of its own. It is not edited after the conversion, with one exception: a file converted before this rule may get one later edit that turns its links to sprint and epic docs into names, its link text kept. Its sections stay when their items leave `DEFERRED.md`, and a new item adds no section.

## Procedure

1. **Check the starting point.** The check command reports `DEFERRED.md` as not converted; no `> Audit` annotation of a PLAN in the sprint docs directory or its `DONE/` names a `D<n>`; `DEFERRED.md` has no uncommitted change; and `DEFERRED-context.md` does not exist. An annotation that names a `D<n>` means the file is not in the old form: its pointer line was lost, so reconcile it as "Numbers" in [deferred.md](deferred.md) says, and do not convert. If another of these does not hold, ask the user before going on.
2. **Read the whole file and mark the entries**, without writing anything yet. An entry is a heading that names one deferred decision, with everything under it up to the next such heading. What is not an entry (the title, an introduction, a rule `---`) is kept for step 6.
3. **Number the entries in file order**, top to bottom, from `D1`, closed entries included. The order in the file is the only order there is: do not sort by date, age or topic.
4. **Map each open entry to one item.** A closed entry, one the file says was resolved or dropped, becomes no item, since a closed item outside a sprint leaves the file; it keeps its number and its section.
   - **Heading**: `### D<n> — <old ID>: <title>` when the entry had an ID, so that a search for the old ID in docs and code still finds it; otherwise `### D<n> — <title>`.
   - **`Sprint:`** always `none`. A sprint or step the entry names stays in its section of `DEFERRED-context.md`: no PLAN step of the old process names the item, and a code-complete close did not exist then.
   - **`Trigger:`** the entry's trigger or predicate, on one line. A trigger of several conditions is joined on that line (`… OR …`).
   - **`Review by:`** the date the entry gives, a calendar condition of its trigger included (`date >= 2026-10-19`). An entry with no date gets one proposed to the user in step 5; a date is never invented silently.
   - **`Check:`** only when the entry names a runnable check: one script of the project with its arguments, as "A named check" in [deferred.md](deferred.md) says. Any other command stays in the prose.
   - **`Status:`** `open`.
   - **The rest** of the entry (context, history, how to apply, owner, notes) moves word for word to its section of `DEFERRED-context.md`, bold labels and all. A field line also keeps its full original text there when its one line had to shorten it. A closed entry's section holds the whole entry, its `Resolved:` line included.
5. **List what the conversion changes, and put the doubtful cases to the user, before writing**: each entry's new number and heading, and which entries are closed and become no item; every `Review by:` you propose, with its reason; every trigger that would not fit one line without losing its meaning; every entry that looks moot; and the text that is not an entry, which goes to the head of `DEFERRED-context.md` unless the user says otherwise.
6. **Write the change**: `DEFERRED.md` holding the title `# Deferred items`, the pointer line `Latest assigned: D<n>` with the last number, and the items in number order; `DEFERRED-context.md` holding a title, the text that is not an entry, and the entries' sections in number order.
7. **Verify.**
   - Run the check command ([deferred.md](deferred.md)): it reports no violation for `DEFERRED.md` and no note that it is not converted.
   - Count: the entries marked in step 2 equal the sections of `DEFERRED-context.md`, the open ones equal the items, and the pointer line holds the last number.
   - Nothing is lost: every line of the old file, as `git show HEAD:<docs>/DEFERRED.md` prints it, is in one of the two files, apart from what the user said to delete. `DEFERRED-context.md` is new and untracked, so `git diff` does not show it: read it. A search for each old ID finds its heading.
8. **Report and stop.** Tell the user how many entries there are, how many became open items, and which dates were proposed. The commit is the user's decision; propose one commit holding exactly this change.

## Afterwards

- Numbers assigned here are permanent from the moment the change is committed. If the user rejects the result before a commit, discard the change and start again; after a commit, fix an item in place and leave its number.
- Docs and code cite the old IDs, which the headings keep, so nothing else needs editing.
