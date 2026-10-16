# Format of the project memory

Read [lifecycle.md](lifecycle.md) for when each of these is written. Nothing here is written without the user's approval.

## The memory directory

It is the setting `memory.dir`: a path relative to the project root and inside the project, `docs/memory` by default. An absolute path, or one that leads outside the project, is not supported: the index links each lesson by a path relative to the project root. If the setting holds one, stop and report it. Read it before the first lesson is touched in a session:

```text
python scripts/settings.py memory --project <project root>
```

`scripts/settings.py` is in this skill's directory; run it by its path, with the Python the session has. The project root is the main working tree of the project's repository, never a worktree made for a sprint: the first entry of `git worktree list`. If the script exits with an error, stop and report it: a settings file is wrong, and the default would hide that. The default is used only when no Python 3.11 or later can start the script; say so then.

Below, `<memory dir>` stands for that directory, written as the setting gives it.

## The index

The index is a block in the project's `AGENTS.md`, in the project root, between two marker lines:

```markdown
## Project memory

Lessons of this project, one line each. Before work a line applies to, read its file.

<!-- project-memory:index:start -->
- [Run the suite with the system Python](<memory dir>/system-python-for-tests.md): before any test run; `python` is another project's venv here
- Local lessons, private or of this machine: read `<memory dir>/local/INDEX.md` if it exists.
<!-- project-memory:index:end -->
```

- **The markers are exactly these two lines**, each on a line of its own, once in the file. The check command of the `prd-implementation` skill finds the block by them.
- **One line per lesson**: `- [<title>](<path of the lesson file>): <when it applies>; <what to do>`. The path is relative to the project root. The line is enough to tell whether the lesson applies to the work at hand; the rest is in the file.
- **The block holds index lines only.** Every line between the markers counts toward the limit, a blank line and a heading among them: the heading and the sentence under it stay above the start marker.
- **At most 50 lines of at most 150 characters each.** Both are inclusive, and a line's length is the number of Unicode characters of the whole line, markup and link included, without its newline.
- **The last line is fixed**: the line on local lessons shown above, with the project's memory directory in it. It is written when the block is created, counts as one of the 50, and stays also in a clone that has no local lesson: `local/` is git-ignored, so a committed file cannot know whether one exists.
- **Order** is the order of writing, the fixed line last. A line is never extended to hold a second lesson.
- **The block is created with the first lesson**, at the end of `AGENTS.md`, with the heading and the sentence above it. If the project has no `AGENTS.md` in its root, ask the user before creating one.

## A lesson file

One file per lesson, `<memory dir>/<slug>.md`. The slug is short kebab-case and names the subject, not the date or the sprint: `system-python-for-tests.md`.

```markdown
# Run the suite with the system Python

**Recorded:** YYYY-MM-DD, <sprint NN | outside a sprint>
**Roles:** <all | who it concerns: the implementer, a reviewer, whoever commits, or the project's own names for them>

## What

<The fact or the rule, in a sentence or two. A command is given in full.>

## Why

<What happened, or what breaks without it. One short paragraph.>

## When it applies

<The files, commands or kind of work that should bring it to mind.>
```

- **All four are stated**: what, why, when it applies, which roles. A lesson that cannot say when it applies is not ready to be written.
- **One lesson, one file, one screen.** A file that grows a second lesson is split; two files that say one thing are consolidated.
- **No machine path** in a shared lesson: no home directory, user name or drive letter. Such a lesson is a local one.
- A correction overwrites the text and changes the `Recorded` date. The file keeps no history of itself: `git log` has it.

## The local folder

`<memory dir>/local/` holds the lessons that are private or hold only on one machine: a path, an account, a tool installed in an unusual place.

- **It is git-ignored.** Before the first local lesson is written, the project's `.gitignore` gets the line `<memory dir>/local/`. That line is a change to a committed file: say so when the lesson is proposed.
- **Its lessons have the same file format**, in `<memory dir>/local/<slug>.md`.
- **It has its own index file**, `<memory dir>/local/INDEX.md`: a heading, then one line per local lesson in the form of an index line, with the path relative to the project root. It holds no markers and nothing else. Keep it within the same limits; no command checks it.
- **Nothing in it is committed, and none of its lessons has a line in `AGENTS.md`.** The one fixed line of the index is what leads a session to it.
