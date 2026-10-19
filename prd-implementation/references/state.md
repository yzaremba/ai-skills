# STATE — where a sprint in progress stands

`SPRINTXX-STATE-<Description>.md` is the fifth sprint doc. It lets a session that saw none of the work, on either provider, pick a sprint up from the sprint docs alone. It holds what the other docs and git do not: the workspace, the choices the user made, who holds the work, an open parallel group, and what comes next. Read [conventions.md](conventions.md) for its name and for where it is written.

## Rules

- **The build lead keeps it.** The implementer does not write it. The build lead creates it when the implementation choices are resolved, before any code ([stage-3-implementation.md](stage-3-implementation.md)). One exception, until the Ready commit: whoever changes the PLAN or TASKS outside the build, as when a phase is added, sets the target and the next action to match, such as "P2.1 waits for the PLAN gate", lists those changes under "Uncommitted" while they are, and writes the "Written" line from the clock; nothing else. From the Ready commit on, the close's rules below hold.
- **Write it before a step starts, after a step closes, after each commit, and before any stop**: a question to the user, a blocking finding, the end of a session. A session that dies without warning then leaves it at most one step stale. Writes that fall together are one write. The close is the one exception: see the Ready commit below.
- **The date and time on the "Written" line are read from the clock** (`date`), never estimated.
- **Overwrite; never append.** It holds the present only. What happened is in `git log` and on the PLAN steps. The template is the whole file: if it grows past one screen, cut it. One screen is exact: at most 70 lines and at most 8000 characters ([conventions.md](conventions.md), "Format limits"), which the check command reports.
- **It sits beside the other sprint docs and is committed with them**, at the cadence. It is written again after each commit, so the copy in the working tree is usually one write ahead of the committed one; that is expected.
- **The Ready commit is the last write in the sprint's worktree.** At the close ([completion.md](completion.md), "Integration", step 1) STATE is written once more, with `closing` on its "Written" line and the merge as its next action, and goes into the Ready commit. From then until the archive change deletes it, STATE is not written in the sprint's worktree: not after that commit, and not before a question to the user. The worktree has to stay clean, or `git worktree remove` refuses. Between the Ready commit and the merge nothing needs writing: the committed STATE already names the merge as next. After the merge, a close that has to stop is tracked in the copy the merge brought to the default branch, in the working tree that has it checked out. That copy may be left uncommitted; the archive change deletes it.
- **On pickup, read it first, then compare it with git** before doing anything else: the branch checked out in the workspace, `HEAD`, and `git status`. They match when the branch is the one recorded, `HEAD` is the commit recorded, and nothing is uncommitted beyond this file and what "Uncommitted" lists. **Put any mismatch to the user**, with what STATE says and what git says. Never resolve it silently, in either direction: do not "fix" STATE to match git, and do not reset or discard work to match STATE.
- **What counts as a match.** `HEAD` matches when it is the recorded commit, or when the recorded commit is its parent and the later commit changed only sprint docs: STATE cannot name the commit that holds it, so a pickup from a fresh clone or after the Ready commit finds it one commit back. A workspace path that differs only because the machine, or the side of one machine, names it differently is not a mismatch when the branch and `HEAD` agree. A STATE whose "Written" line reads `closing` is in the Ready commit itself: it matches when that commit is `HEAD` of the sprint's branch or, after the merge, is on the default branch. Anything else is a mismatch.
- **Sprint docs in a separate repository.** STATE is then in the docs repository, on its default branch, and writing it never touches the code's worktree. It is written through the close as at any other time, and what it is compared with on pickup is the code's workspace.
- **While a parallel group is open, it records the group**: the base commit, and each member's worktree, branch and step, from the moment the worktrees are made until the last one is removed ([stage-3-implementation.md](stage-3-implementation.md), "Parallel groups"). On pickup, compare that with `git worktree list` too. A member worktree that stays because it could not be removed without force stays listed, with its reason.
- **It carries the lesson candidates to the close.** When it writes STATE, the build lead records under "Lesson candidates" each candidate an implementer's report named, one line with its step, and its own; a report's `none` adds nothing. This one section is kept from write to write, not overwritten. At the close the lessons are proposed from it ([completion.md](completion.md), "Lessons"). A STATE written after the user has answered holds there only the approved lessons not yet written, one line each, `approved, to write: <lesson>`; the rejected ones are dropped. A session that picks up a stopped close then loses no approval and proposes nothing again.
- **The recorded choices stand across runs.** When the recorded target is exhausted, for instance after a run of one task, only the target is asked again; the other recorded choices stand unless the user changes them.
- A sprint in implementation with no STATE is itself a mismatch: ask the user before continuing, then create it.
- **It is deleted when the sprint closes**, completed ([completion.md](completion.md)) or abandoned ([abandon.md](abandon.md)), and not before every worktree it lists has been dealt with or, for an abandoned sprint, taken into the report to the user. It is never moved to the archive.

## Template

```markdown
# SPRINT07 STATE — mobile-layout

**Written:** YYYY-MM-DD HH:MM, <before P2.3 | after P2.3 | after the commit of P2 | stopping: why | closing>

## Workspace

- Path: <absolute path of the worktree, as this machine names it | in place: the path of the repository>
- Branch: `sprint/07-mobile-layout`
- Base commit: `<hash>` on `<default branch>`, the fork point
- HEAD: `<hash>` <its subject line>
- Uncommitted: <none | the files, and which step they belong to>

## Choices

- Target: <the ordered steps or phases in scope>
- Workspace: <new worktree | in place>
- Review: <after each phase | after each task | at completion | none>
- Commits: <after each phase | after each task | at completion | don't commit>
- Implementer: <a separate implementer | the build lead's own session>

## Who holds the work

- Build lead: <provider, and the session if it has a name>
- Step in progress: <P2.3, with whom | none>

## Parallel group

<none | while a group is open, its base and one line per member>

- Group: <P2, letter A>, base commit `<hash>`
- P2.2: <absolute path of the member's worktree>, branch `group/s07-p2.2`, <at work | reported `<hash>` | merged | failed: why | left in place: why>

## Next action

<One action, exact enough to start from: "hand P2.4 to the implementer", "run the review of phase 2", "commit phase 2 as S7P2".>

## Half-done work

<none | what is started and not finished: a step at `[~]` and what remains of it, review findings not yet fixed, a question waiting for the user's answer>

## Lesson candidates

<none | one line per candidate, with the step it came from: "P2.3: the suite needs the system Python" | after the user's answer at the close, one line per approved lesson not yet written: "approved, to write: <lesson>">
```
