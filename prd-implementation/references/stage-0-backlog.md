# Stage 0 — BACKLOG (`BACKLOG.md`)

Read [conventions.md](conventions.md) before creating or editing a sprint doc.

- `BACKLOG.md`, in the sprint docs directory, is a persistent **dumping ground** for ideas, bug reports, and wishlist items captured outside any active sprint. It is **not** sprint-scoped.
- **An item is one line**, or one line that points to a dedicated document. Each item has a number `B<n>` that is stable and never reused. "The file" below gives the exact form.
- Optional grouping under headers (e.g. `## Bugs`, `## Features`, `## UX`) is fine but not required — do not impose grouping the user did not ask for. An item may be moved to another group; its number goes with it.
- Create the file if it does not exist the first time an item needs to be added.
- The backlog is shared between sprints: it and its item documents change only on the default branch, never in a sprint worktree (see "Where each doc is written" in [conventions.md](conventions.md)).
- **Starting a new sprint:** the user picks one or more items from `BACKLOG.md` that form a coherent theme. Those items seed the new `SPRINTXX-THOUGHTS-<slug>.md` (Stage 1). **Delete** the plucked items from `BACKLOG.md` in the same change, and with each its dedicated document if it has one — traceability lives in the new THOUGHTS file, which should quote or paraphrase the original idea and name its number (`B12`). The pointer line stays as it is: a plucked number is not free again.
- Items not yet picked up stay in `BACKLOG.md` indefinitely. No expiry — keep it lightweight. Priority tagging is optional; an item without a tag is as valid as one with.
- **Gate:** Do not start a sprint (THOUGHTS file) without an explicit user signal about which backlog items to pluck, or explicit direction that the sprint theme comes from outside the backlog.

## The file

Every line of `BACKLOG.md` that is not blank is one of three things, and nothing else belongs in the file.

| Line | Form |
|------|------|
| A heading | Starts with `#`: the title `# Backlog`, and any grouping headers |
| The pointer line | `Latest assigned: B<n>`, the whole line; exactly once, above the first item |
| An item | `- **B<n>** <text>`, or with a priority tag `- **B<n>** **[HIGH]** <text>` |

- **An item line** starts at the first column with `- **B<n>** `: a hyphen, one space, the number in bold, one space. `<n>` is a positive whole number written without leading zeros (`B7`, not `B07`).
- **The priority tag** is optional. When used it comes directly after the number: `**[HIGH]** `, `**[MED]** ` or `**[LOW]** `, followed by one space, and nowhere else on the line.
- **The text** is what the item is, in a phrase or a sentence. It may hold inline markup and links, but a sprint's or an epic's doc is named by its file name in backticks, never linked: the sprint's close moves it ("Links and names" in [conventions.md](conventions.md)). The same holds in an item document.
- **One line means one line**, of at most 300 characters, counted as "Format limits" in [conventions.md](conventions.md) says. No continuation line, no sub-bullet, no paragraph under an item, no code block. A list line without a number is not an item, and is a violation like any other stray line.
- **A number appears once** in the file, and none is higher than the pointer line's.

## Numbers

- **The pointer line is a pointer, not a log**, as in the sprint index: it holds the latest number assigned and nothing else. A new item takes that number plus one, and the same change overwrites the pointer line.
- **A number is never reused and never changed**: not when its item is plucked or deleted, not when items are reordered or regrouped. Gaps are normal. Other docs may cite a number (a THOUGHTS file, a skipped TASKS line `moved to BACKLOG as B14`), and it must go on meaning that item.
- An item whose text is rewritten keeps its number as long as it is the same idea. Two ideas are two items.
- **A missing or wrong pointer line is reconciled by rule, not by guessing.** If a number in the file is higher than the pointer line, or the line is gone from a file that has item lines, set it to the highest `B<n>` found in the file and in the sprint docs directory with its `DONE/`, and tell the user what was done. A file with no pointer line and no item line is another case: see "A backlog in the old form" below.

## A longer idea

What does not fit one line goes in a **dedicated document**, and the item is the one line that points to it.

- The document is `B<n>-<slug>.md` in the folder `BACKLOG/` of the sprint docs directory, beside `BACKLOG.md`, with the item's own number and a short kebab-case slug: `BACKLOG/B9-offline-journal.md`. Of the backlog, only `BACKLOG.md` is in the sprint docs directory itself; its item documents are in the folder, which is named `BACKLOG` in capitals on every system.
- The item points to it with a markdown link **at the end of the line**, whose target is the document's path from `BACKLOG.md`, `BACKLOG/B<n>-<slug>.md`: `- **B9** Offline mode for the trade journal — [notes](BACKLOG/B9-offline-journal.md)`. The link's text is free. An item has at most one document.
- The document is free-form: bullets, half-thoughts, sketches, open questions. It has no required sections and no limits. This is where the unstructured thinking goes; the backlog file stays a list.
- An item and its document live and die together: a pointer whose document is missing, and a `.md` file in `BACKLOG/` that no item points to, are both violations.
- **Documents at their earlier place**, `BACKLOG-B<n>-<slug>.md` beside `BACKLOG.md`, and links to those names, are the layout of a backlog converted before the folder. The check command reports them once for the backlog, as a note like "not converted" below, and not item by item. Moving them is "Item documents at their earlier place" in [backlog-conversion.md](backlog-conversion.md), on the user's word.
- Do not start a document for an idea that fits its line.

## Example

An example of a whole `BACKLOG.md`. `B1`, `B2`, `B5` to `B8`, `B10` and `B13` were plucked or deleted earlier; their numbers are not used again.

```markdown
# Backlog

Latest assigned: B14

## Bugs

- **B3** **[HIGH]** Export drops the last row when the file does not end with a newline
- **B11** The date filter ignores the account's time zone on the summary screen

## Features

- **B9** **[MED]** Offline mode for the trade journal — [notes](BACKLOG/B9-offline-journal.md)
- **B12** Let a note carry a link to the trade it is about
- **B14** **[LOW]** Keyboard shortcuts for the three most used filters

## UX

- **B4** The settings screen needs a search box; see the [support thread](https://example.com/t/481)
```

## Checking

The check command reports a backlog item that is not one line and every other breach of the form above. It is `scripts/check.py` in this skill's directory; [deferred.md](deferred.md) says how it is run and what it reports.

## A backlog in the old form

An older backlog is free-form: bullets without numbers, items of several lines, no pointer line. Bringing it into this form is a one-time procedure, [backlog-conversion.md](backlog-conversion.md), run on the user's word and never silently.

- **A `BACKLOG.md` with no pointer line and no item line** is one of two things. It is **clean** when it holds nothing but blank lines and headings: a new, empty backlog. Otherwise it is **not converted**.
- The check command reports "not converted" once for the file, instead of each of its lines, and as a **note**: in a separate Notes section of its report, in the text and in the JSON, not counted among the violations and with no effect on its exit status. A project that declined the conversion is therefore not reported as needing action.
- Do not number items piecemeal, and do not convert as a side effect of adding an item. Offer the conversion; if the user declines, add the item in the form the file has.

Next: [stage-1-thoughts.md](stage-1-thoughts.md), once the user has given the signal to start a sprint.
