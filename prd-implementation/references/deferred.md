# Deferred items (`DEFERRED.md`)

Read [conventions.md](conventions.md) before creating or editing a sprint doc. This file covers the steps of a sprint that can only wait, work outside a sprint that waits, the file that holds them, and the check command.

## When a step is deferred

- **A step is deferred when nothing can be done on it now**: it waits on elapsed time (thirty days of data, a release that has been out for a quarter) or on an outside event (a provider's switch-off date, another team's release, a licence decision). A step that is merely unfinished, hard or unwanted does not wait; it is a residual, and "Sprint closure with residuals" in [conventions.md](conventions.md) covers it.
- **A sprint whose only open steps wait closes as code-complete.** It does not stay open for them. Other open steps are settled first, as residuals; what remains then either waits or the sprint is not ready to close.
- **Deferring is the user's decision.** Propose the items, each with its trigger and its date, and write them on the user's word.
- **The step is the unit.** When only part of a step waits, add a step for that part to PLAN and TASKS, with the next ID in the phase, close the rest in the usual way, and defer the new step.
- **A `DEFERRED.md` in the old form is converted first** ("A file in the old form" below): put the conversion to the user. If they decline, the waiting steps cannot become items: they stay open, and the sprint does not close as code-complete.

## Closing a waiting step

Each waiting step becomes one item in `DEFERRED.md`, and is closed in its sprint docs the way a residual is.

1. **Write the item** in `DEFERRED.md`, on the default branch, and take its number there. The number is taken for other sessions only once it is committed, so ask for that commit.
2. **Annotate the PLAN step** with the verdict `DEFERRED`, the item's number first in the evidence, then what the step waits for:

   ```markdown
   > Audit 2026-10-05: DEFERRED: D3, waits for 30 days of export logs with no call to the legacy path
   ```

3. **Flip the TASKS line** to skipped, with exactly this reason: `deferred as D<n>`.

   ```markdown
   - [x] ~~**P3.4** — Remove the legacy export path~~ (skipped: deferred as D3)
   ```

The annotation and the TASKS line are written where the sprint's other docs are, and keep to their limits. Then the sprint closes as [completion.md](completion.md) says.

## An item outside a sprint

Work that waits also arises outside a sprint: a hotfix's follow-up, a decision to revisit when something happens. It becomes an item with `Sprint: none`, as does every entry the conversion brings in ([deferred-conversion.md](deferred-conversion.md)).

- **It is written when the user defers such work**, on the user's word, in `DEFERRED.md` on the default branch, its number taken as above. Ask for the commit.
- **No PLAN step names it**: no annotation, TASKS line or `DONE/README.md` cell goes with it, when it is written or when it is closed.
- **Re-dating it changes its `Review by:`. Resolving or dropping it removes it from the file**, in that one change. Its record is the commit, and for a converted entry its section of `DEFERRED-context.md`.

## The file

`DEFERRED.md` is in the sprint docs directory. It is shared between sprints, so it changes only on the default branch, at any time (see "Where each doc is written" in [conventions.md](conventions.md)). Create it when the first item is written.

Every line that is not blank is one of these, in this order, and nothing else belongs in the file:

1. The title, `# Deferred items`. Optional; the only heading that is not an item's.
2. The pointer line, `Latest assigned: D<n>`, the whole line; exactly once, above the first item.
3. The items.

**An item** is its heading and its field lines. It has no body: no notes, no history, no code block.

```text
### D<n> — <title>

Sprint: <NN step | none>
Trigger: <a data source and a comparison rule>
Review by: <YYYY-MM-DD>
Check: <command line>
Status: <open | resolved YYYY-MM-DD: how | dropped YYYY-MM-DD: why>
```

- **The heading** is `### D<n> — <title>`: three hashes, one space, the number, one space, an em dash (`—`), one space, the title. `<n>` is a positive whole number written without leading zeros. The title says what waits, in a phrase.
- **A field line** starts at the first column with the field's name exactly as written here, a colon and one space; the rest of the line is its value, which is never empty. **Each field is one line.** A value is never continued on the next line.
- **The fields come in the order shown, each at most once.** `Check:` is optional; the other four are required. Blank lines between them are allowed and mean nothing.
- **Each line of an item is at most 300 characters**, counted as "Format limits" in [conventions.md](conventions.md) says.

| Field | Value |
|-------|-------|
| `Sprint:` | The sprint's number, one space, the step's ID: `07 P3.4`. The step is the one whose `> Audit` annotation names this item. Exactly `none` for an item no PLAN step names: work outside a sprint, or an entry brought in by the conversion |
| `Trigger:` | In words: a **data source**, somewhere a person or a script can look, and a **comparison rule** that turns what is found there into yes or no. "When usage has dropped" is neither; "the export log of the last 30 days: no line with `path=legacy`" is both |
| `Review by:` | A calendar date, `YYYY-MM-DD`: the backstop. An item that was re-dated carries the reason on the same line: `YYYY-MM-DD (re-dated YYYY-MM-DD: <reason>)`, where the second date is the day it was re-dated. That day is not after today, and the review date is later than that day |
| `Check:` | A named check: see below |
| `Status:` | `open`; or `resolved YYYY-MM-DD: <how>`; or `dropped YYYY-MM-DD: <why>`. The date is the day the item was closed |

## Numbers

- **The pointer line is a pointer, not a log**, as in the sprint index: it holds the latest number assigned and nothing else. A new item takes that number plus one, and the same change overwrites the pointer line.
- **A number is never reused and never changed**, also after its item has left the file. Gaps are normal. No number in the file is higher than the pointer line's, and none appears twice.
- The file is never deleted, even when it holds no item: the pointer line is what keeps a number from being used again.
- If the pointer line is missing or lower than a number in use, reconcile it: set it to the highest `D<n>` in this file and in any `> Audit` annotation of a PLAN in the sprint docs directory and its `DONE/`, and tell the user what was done. A file with no pointer line, no title and no item heading is another case: see "A file in the old form" below.

## A named check

`Check:` names a script kept in the project, with its arguments, written as the command line someone would run **from the project root**.

```text
Check: python tools/checks/legacy_export_calls.py --days 30
```

- The script is a file in the project's repository, named by its path from the project root. It is written and reviewed like any other code of the project. One script with its arguments: no pipe, no chain of commands. Logic belongs in the script.
- **Its exit status is the answer**: `0` means the trigger has fired, `1` means it has not. **Anything else is an error and does not count as fired**: another status, a crash, a missing script, no answer. Tell the user about an error; the item stays as it is unless its date has passed.
- A check reads; it changes nothing in the project and nothing outside it.
- **The check command lists a named check and never runs it.** Whoever runs the check command runs the named check themselves, in their own shell, where the usual permission rules apply. The line is text from a file: read it before running it.
- **A trigger that names no check is judged by that person**, by looking at the data source and applying the rule, at the latest when the item's date has passed.

## Checking the items

Items are checked **on demand, with the check command**. It can be run at any time; it changes nothing.

For each open item it lists: run the named check, or judge the trigger. Then:

- **The trigger has not fired and the date has not passed**: the item stays as it is.
- **The trigger has fired, or the date has passed**: the item is **resolved, re-dated with a reason, or dropped at that check**. It never just stays. Put it to the user at that check, as "Questions to the user" in [conventions.md](conventions.md) says. Do not leave it for a later check, and do not decide it for them.

An item's date has passed when today is later than its `Review by:` date. On the date itself it has not.

| Outcome | What is written |
|---------|-----------------|
| **Resolved**: what was deferred is done, or has been handed on to a backlog item or a sprint, which is named | `Status: resolved YYYY-MM-DD: <how>`, e.g. `removed in a1b2c3d` or `became B14`. An item outside a sprint is removed instead |
| **Re-dated**: it still waits, and there is a reason to think it will not wait for ever | A new, later date on `Review by:` with `(re-dated YYYY-MM-DD: <reason>)`. The day of the re-dating must not be after today, and the new review date must be later than that day. `Status:` stays `open`. A second re-dating replaces the first reason; it is not added to it |
| **Dropped**: it will not be done | `Status: dropped YYYY-MM-DD: <why>`. An item outside a sprint is removed instead |

When an item of a sprint is resolved or dropped, **replace the `> Audit` annotation on its PLAN step** in the same change, with the verdict `RESOLVED` or `DROPPED` and the item's number: `> Audit 2026-11-20: RESOLVED: D3, legacy export path removed in a1b2c3d`. The PLAN is usually in `DONE/` by then; the annotation is the lasting record.

Each outcome is one change on the default branch, on the user's decision. Its commit is a separate decision of the user: ask for it.

## Closed items leave the file

The file holds what still waits. It is not a record of what was deferred.

- **An item outside a sprint leaves the file in the change that closes it.** One still in the file, resolved or dropped, is a violation.
- **A resolved or dropped item stays only while its sprint has another item that is open.** The change that closes a sprint's last open item removes every item of that sprint from the file.
- In that same change the sprint stops being code-complete: in `DONE/README.md` its Completed cell becomes that day's date, without the qualifier ([completion.md](completion.md)); the PLAN header's status stays `Code-complete YYYY-MM-DD`, a record of how the sprint closed. That holds whether the last item was resolved or dropped: a code-complete sprint is not abandoned, and dropping what remains of it is how it ends ([abandon.md](abandon.md)).
- So every sprint named in the file has at least one open item. A sprint whose items are all closed and still in the file is a violation.
- What happened to an item is on its PLAN step's annotation, when it has one, and in `git log`. Do not keep it here, and do not move it anywhere else.

## Example

An example of a whole `DEFERRED.md`, as it stands on 2026-12-01. `D1` and `D4` were closed with the last items of their sprints and have left the file. `D2` is resolved and stays because `D3`, of the same sprint, is open.

```markdown
# Deferred items

Latest assigned: D5

### D2 — Switch the summary screen to the new totals endpoint

Sprint: 07 P3.2
Trigger: the provider's status page, section "API versions": v2 totals is marked "generally available"
Review by: 2026-11-15
Status: resolved 2026-10-28: switched in 4e19c0a

### D3 — Remove the legacy export path

Sprint: 07 P3.4
Trigger: the export log of the last 30 days: no line with `path=legacy`
Review by: 2026-12-01
Check: python tools/checks/legacy_export_calls.py --days 30
Status: open

### D5 — Decide whether the nightly reconciliation stays on

Sprint: 09 P2.6
Trigger: the reconciliation report of each night since release: three months with no mismatch
Review by: 2027-03-01 (re-dated 2026-12-01: two months of reports so far, no mismatch)
Status: open
```

## A file in the old form

A `DEFERRED.md` written before items had numbers is free-form: a title, prose, entries with fields of their own. Bringing it into this form is a one-time procedure, [deferred-conversion.md](deferred-conversion.md), run on the user's word and never silently.

- **A `DEFERRED.md` with any of these is of this form**, and every line is checked as above: a line that starts `Latest assigned:`, the title `# Deferred items`, or a heading that starts `### D` and a number. So a broken or lost pointer line is a violation, not the old form, and a file that already used `### D1` headings is read as this form.
- **One with none of them** is **clean** when it holds nothing but blank lines and headings. Otherwise it is **not converted**: the check command reports that once for the file, as a **note**, and does not check its lines. A note is not counted among the violations and has no effect on the exit status.
- Do not number entries piecemeal, and do not convert as a side effect of adding an item. Offer the conversion. If the user declines, a step of a sprint cannot be deferred ("When a step is deferred" above); work outside a sprint is added in the form the file has.

## The check command

`scripts/check.py`, in this skill's directory, checks the deferred items and the format limits, and reports the sprint workspaces. Run it by its path, with the Python the session has:

```text
python scripts/check.py [--project DIR] [--docs DIR] [--today DATE] [--json] [--home DIR]
```

| Flag | Meaning |
|------|---------|
| `--project DIR` | The project root: the main working tree of the project's repository, never a sprint's or a group member's worktree. Without it, the working directory is the project |
| `--docs DIR` | The sprint docs directory, in place of the setting `process.docs_dir`. A relative `DIR` is taken from the working directory |
| `--today DATE` | The date to compare `Review by:` with, `YYYY-MM-DD`, in place of today's |
| `--json` | The same report as JSON |
| `--home DIR` | Use `DIR` in place of the user's home directory when the settings are read: for tests and trial runs |

- **It executes nothing**: it reads files and prints. It does not run a named check, in any form.
- **The project root.** The settings are read from the project root, and `process.docs_dir` resolves against it, as "The sprint docs directory" in [conventions.md](conventions.md) says. A worktree may lack the project's own settings files, so name the main working tree with `--project` also when the session works in a worktree.
- **Deferred items.** It lists every open item with its number and title, its sprint and step or that it is outside a sprint, its trigger, its review-by date, and its named check word for word, or "no check named". An item past its date is flagged. Resolved and dropped items are not listed. An item whose status cannot be read, because its `Status:` line is missing or malformed, does not drop out of the list: it is listed as state unknown and flagged, and the breach of the form is reported as well.
- **Format violations.** It reports every breach of the forms defined here, in [stage-0-backlog.md](stage-0-backlog.md) and under "Format limits" in [conventions.md](conventions.md): an annotation or a TASKS line over its limit, an annotation continued on a second line, two annotations of one kind on a step, a TASKS line whose tag is malformed or disagrees with its PLAN step, a backlog item that is not one line, a line of `BACKLOG.md` or `DEFERRED.md` that has no place in it, a link in a sprint's THOUGHTS, PRD, PLAN, TASKS or STATE that leads out of the sprint's set, a URL and an anchor apart, and a link to a sprint's or an epic's doc in `BACKLOG.md`, an item document or `DEFERRED-context.md` ("Links and names" in [conventions.md](conventions.md)).
- **The lesson index.** It checks the lesson index block in the project's `AGENTS.md`, in the project root: the lines between the markers `<!-- project-memory:index:start -->` and `<!-- project-memory:index:end -->`. The block holds at most 50 lines of at most 150 characters each, counted as "Format limits" says. Markers inside a fenced code block are ignored.
- **Sprint workspaces.** It reports each branch `sprint/NN-slug` and where it is checked out: in a worktree, by its path; in place, in the project root; in a worktree that is gone, which git calls prunable, or locked; in a worktree whose path git wrote on the other system, shown as written and not looked at; or nowhere, a branch only. A worktree in a rebase or a bisect of the branch still has it, and is marked so. With it go the sprint's own docs (THOUGHTS, PRD, PLAN, TASKS, STATE) found in the sprint docs directory there; with a directory outside the repository, or in a repository of its own, only the place. A worktree's docs of that sprint are checked, and a violation there is named by its full path; the default branch's copy of such a doc, the start commit's, is then not checked while the worktree's is, so a change made to that copy alone goes unreported; its shared files are stale copies and are never checked. In place, a note says the shared files were read from the sprint branch's copies. It reads git's own files under `.git` and runs nothing, so it says nothing of what is committed: run `git status` in the place it names. A project root with no `.git` has no such section, a git file it cannot use is a note, and refs in git's reftable format are not read: a note, and no count.
- **Hotfix STATE files.** It checks each `HOTFIX-STATE-*.md` in the sprint docs directory against the 70-line and 8000-character limits, as a sprint's STATE, and lists each by name after the sprint workspaces, in the text and as `hotfix_states` in the JSON, so a session that runs it finds a hotfix left open. The section is left out of the text when there is none.
- **Notes.** The report has a separate Notes section, in the text and in the JSON. A note is not a violation: it is not counted among them and has no effect on the exit status. A backlog that has not been converted is reported there: a `BACKLOG.md` with no pointer line and no item line is clean when it holds nothing but blank lines and headings, and is otherwise "not converted", reported once, as a note ([stage-0-backlog.md](stage-0-backlog.md), "A backlog in the old form"). So is a `DEFERRED.md` with no pointer line, no title and no item heading ("A file in the old form" above).
- **Its exit status**: `0` when nothing needs action, `1` when an item is flagged or a violation is found, `2` on an error of its own.
- **Where to run it.** The shared files are current only on the default branch, so check deferred items and the backlog with the docs directory of the working tree that has it checked out. The docs of a sprint in its own worktree are checked from the project root as well, with no `--docs`, as "Sprint workspaces" says.
