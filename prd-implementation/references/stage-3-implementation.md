# Stage 3 — Implementation (executing the sprint)

This is the implementation half of Stage 3: writing code against an existing PLAN/TASKS set. It honors the **task lifecycle**, **TASKS-line discipline**, **format limits** and **"Last updated" hygiene** in [conventions.md](conventions.md); read that file first. If the sprint has no PLAN and TASKS yet, this stage has not started: go to [stage-3-plan-tasks.md](stage-3-plan-tasks.md).

Three parts take part, and the text names no agent:

- **The build lead** resolves the choices with the user, hands each unit to the implementer, runs the independent review and commits.
- **The implementer** implements one unit, verifies it and moves its TASKS checkbox. The implementer does not commit, with one exception: a member of a parallel group makes exactly one commit, in its own worktree ("Parallel groups" below).
- **An independent review** is the adversarial pass described below.

One session may be all three: it then follows the build lead's part and the implementer's part in turn, and still gets its adversarial pass from a reviewer that did not write the code. When the parts are separate sessions, each keeps to its own part. How a question is put to the user, how work reaches a separate implementer and how an independent review is run differ by provider: see [claude-code.md](claude-code.md) or [codex.md](codex.md).

## The build lead's part

### Picking up a sprint in progress

If the sprint has a STATE file (`SPRINTXX-STATE-<slug>.md`), read it before anything else, then compare it with git as [state.md](state.md) says: branch, `HEAD`, uncommitted changes. Put any mismatch to the user; never resolve it silently. When they match, the choices recorded there stand, and work resumes at its "Next action" without asking them again. When the recorded target is exhausted, only the target is asked again; the other recorded choices stand unless the user changes them. Before the next step, the build lead fixes the violations the check command ([deferred.md](deferred.md)) reports in this sprint's own docs: in the sprint's workspace, never in the default branch's copy, listed under STATE's "Uncommitted" until it is committed at the chosen cadence. A fix that needs judgement, such as the wording of an over-long annotation, follows that doc's rules in [conventions.md](conventions.md).

### Resolve the choices, then print a summary

When the user asks to **implement** a sprint, resolve the choices below (ask interactively only for what the user didn't already state; prefer a *single consolidated* prompt over separate round-trips), then **print a summary** and proceed. The user's word to implement, with the choices, is the gate. The summary of the choices is printed before any code, and the session proceeds without waiting for a reply: the summary is the user's chance to stop it. The consolidated prompt is one question that holds several choices, so it stays one prompt whatever `process.questions` says; every other question in this stage follows "Questions to the user" in [conventions.md](conventions.md).

1. **Target** — if no specific task/phase was named, ask: (a) next implementable task, (b) next implementable phase, (c) all remaining phases. *Implementable* = the next not-done item whose `> Depends on:` prerequisites are all `[x]`; skip done/skipped items. A next implementable task that is a member of a parallel group means the whole group: a group is one unit.
2. **Workspace** — the sprint's worktree or branch was made right after the start commit, and the question was put then ("The sprint's workspace" in [conventions.md](conventions.md)): that is the workspace, so state it in the summary instead of asking. The build lead points the implementer at that path and commits there. Only a sprint that has no workspace yet is asked here, if the user wasn't explicit: one whose docs are in a separate repository, or one started before this rule. The question, the two forms (a new git worktree, or a branch in place) and how the worktree's path is resolved are the same as there, and the build lead makes it. For a sprint in place on the default branch, branch first before any commit.
3. **Adversarial pass** — an *independent, adversarial* review of the just-written code that actively tries to break it (hunt bugs, gaps, missed edge cases), distinct from the implementer's own self-verify. If unstated, ask: (a) after each phase *(recommended)*, (b) after each task, (c) at completion, (d) none. Run the adversarial pass whatever way fits — an adversarial review skill or a separate reviewer prompted to refute the change — and for a pass that runs after commits have already landed, scope it to the branch diff (vs the fork point), not just the uncommitted working tree. Where no reviewer that did not write the code can be started, do not review your own work in its place: stop and ask, offering the cadence "none" or a review the user runs themselves.
4. **Commit cadence** — if unstated, ask: (a) after each phase *(recommended)*, (b) after each task, (c) at completion, (d) don't commit. The chosen cadence **is** the user's commit authorization. Choosing (a), (b) or (c) authorizes the build lead's commits at that cadence, and it is also what authorizes the commits a parallel group needs: the one commit of each member, the merges, and the commit that gives the group a clean base ("Parallel groups" below). The Ready commit at the close, which holds the audit annotations, the skipped flips, the PLAN's closing status and the last STATE, is covered by the user's word to close the sprint, under every cadence ([completion.md](completion.md)). Under (d) nobody commits, so no group runs in parallel: its steps run serially.
5. **Implementer** — default to **a separate implementer** that the build lead hands each unit to, unless the user says otherwise (e.g. implement inline yourself). Where no separate implementer can be started, the build lead's own session is the implementer, and the summary says so. The PLAN's marks then say which implementer each step gets ("Which implementer a step gets" below).
6. **Summary first** — before any code, print the resolved choices: target (expanded to the concrete ordered list of steps/phases in scope), workspace (the **absolute worktree path** when the sprint has a worktree, so the user vetoes it here rather than after the fact), adversarial-pass cadence, commit cadence, implementer. Where the target holds a parallel group, say which steps run in parallel and that the group adds commits of its own to the cadence's, or that they run serially and why. Then proceed without waiting for a reply: the gate was the user's word to implement, and this print is their chance to stop it.
7. **Create STATE** — once the choices are resolved, and before any code, write `SPRINTXX-STATE-<slug>.md` from the template in [state.md](state.md): the workspace, the branch and its base commit, the five choices, who holds the work and the next action.

### Loop over the in-scope units

- **Per unit** the implementer flips the TASKS line `[ ] → [~]`, implements + self-verifies, closes `[~] → [x]`. The **build lead** then runs the adversarial pass and/or commits whenever their cadence fires on that boundary — the implementer does not commit, so these commits are always the build lead's. A parallel group is the one exception and is one unit: its members each commit once, and its boundary is its join ("Parallel groups" below).
- **Keep STATE current** — write it before handing a step out, after the step closes, after each commit, and before any stop, as [state.md](state.md) says. It is committed with the other sprint docs at the cadence. The Ready commit of the close holds its last write in the sprint's worktree; what holds from there on is in [state.md](state.md). The implementer does not write it.
- **Review rounds are capped.** A boundary gets its adversarial pass and at most one re-review. Findings are either `blocking` or `minor` (the reviewer's report says which). Blocking findings go to an implementer, and the re-review is briefed with the fix diff and those findings only, not as a new full pass. Minor findings are fixed in the same step as the blocking ones, or listed in STATE's "Half-done work" for the next phase's first step; the re-review does not return to them. A blocking finding that survives the re-review is trouble ("Stop on trouble" below): the cause is usually in the PLAN, not in the code, so offer the user: fix once more, amend the PLAN, or skip the step. Under "after each task" the same cap holds per task.
- **Adversarial before commit** — when both fire on the same boundary, run the pass and **land its fixes before committing** so commits stay clean; when the pass runs less often than commits, its fixes simply arrive as follow-up commits.
- **Commit message prefix** — lead every sprint commit with its sprint-qualified ID: `S<sprint>P<phase>` (e.g. `S12P3`) for a phase-boundary commit, `S<sprint>P<phase>.<step>` (e.g. `S12P3.4`) for a task-boundary commit. Same `P<phase>.<step>` as the PLAN/TASKS ID, with the sprint number prepended — a bare `P3.4` doesn't say which sprint it's from.
- **Stay observable** — under "all remaining phases," emit a brief progress checkpoint at each phase boundary (what landed, what's next).
- **Out-of-scope finds** — the build lead collects what the implementer noted for the backlog and, at a boundary, puts the finds to the user as backlog items. Those the user accepts are added on the default branch, as [stage-0-backlog.md](stage-0-backlog.md) says, never in the sprint's worktree.
- **Stop on trouble — ask, don't guess.** If a unit can't be completed, a dependency isn't actually `[x]`, or the adversarial pass finds a blocking issue, **write STATE, then pause and put a clear, specific question to the user** — state the problem and offer concrete resolution options (e.g. fix now / skip and continue / amend PLAN / abort) — so their choice drives the resolution and execution can resume. Never silently route around it or press on, even under "all remaining phases."

Example, for the step `P2.3 — Add getTradesByPosition() to MariaDbTradeRepositoryApi` of sprint 2. Commit message (task-boundary): `S2P2.3 — Add getTradesByPosition() to MariaDbTradeRepositoryApi`. A phase-boundary commit covering all of Phase 2 would instead lead with `S2P2`.

### A long run, one phase at a time

A build lead that is a separate session, dispatched by the user's own session, keeps its context for its whole run, and every turn pays for all it has read so far. So the dispatcher gives it one phase of the target at a time (the one task, when the target is a task). The build lead works that phase through its adversarial pass, its fixes and its commit, writes STATE with the next action naming the next phase, and reports. The dispatcher then starts a new build lead for the next phase, never the same one told to go on: the new one resumes from STATE ("Picking up a sprint in progress"). The user's word to implement covers every phase of the target, so a phase boundary needs no new word; the checkpoint ("Stay observable") reaches the user each time.

### Which implementer a step gets

The marks on a PLAN step ([stage-3-plan-tasks.md](stage-3-plan-tasks.md)) decide it. They apply when the implementer is a separate session; where the build lead's own session is the implementer, they change nothing.

- **No mark: a fresh implementer.** One that has done no other step, handed this step alone.
- **`> Tag: light`: a light run.** Consecutive light steps of one phase may go to the same implementer, one after the other. Each step still gets its own TASKS flips, self-verify and report, and reviews and commits fire at their cadence as for any other step. A run holds about five steps at most and does not cross a phase. It ends at any failure, stop or review finding: the next step gets a fresh implementer.
- **`> Tag: hard`: the stronger implementer**, where the session has one to give. Where it has none, the step gets a fresh implementer and the summary says so.

### Parallel groups

Steps of one phase that carry the same `> Parallel:` letter are a group. Each **member** of a running group is one implementer with one step, in a worktree of its own.

**A group runs in parallel only when both of these hold.** Otherwise its steps run serially, in the sprint's workspace, like unmarked steps (a `light` tag on them then applies), and nobody but the build lead commits:

- **The commit cadence is not "don't commit".** A member's work reaches the sprint only through a commit and a merge, so a group cannot be combined with that cadence.
- **The implementers are separate sessions.** One session cannot be two members.

How a group runs:

1. **Clean base.** The group starts when every `> Depends on:` of every member is `[x]`. The sprint's workspace must then hold nothing uncommitted beyond STATE: work still waiting for a later cadence commit is committed first, as a commit of its own that leads with the ID of the last step it holds. The build lead records `HEAD` as the group's **base commit**.
2. **Create.** For each member: `git worktree add <root>/<repo>-sNN-pP.S -b group/sNN-pP.S <base commit>`, with `<root>` as resolved for the workspace choice, e.g. `myapp-s07-p2.3` on branch `group/s07-p2.3`. At most three members are at work at a time; a larger group keeps its one base and its one join, and a waiting member starts when another has reported. The build lead, not the member, flips each member's TASKS line `[ ] → [~]` as it starts, and writes STATE with the base commit and each member's worktree, branch and step.
3. **Work.** The brief gives the member its step, its worktree's absolute path and where the sprint docs are. The member works only in that worktree, reads the sprint docs without changing them, runs the checks of its step, makes **exactly one commit** on its branch and reports that commit's id. It changes no sprint doc.
4. **Join.** When every member has reported, the build lead checks that the workspace's `HEAD` is still the base commit; if it is not, stop and ask. It merges each member's branch into the sprint's branch with `git merge`, in step order, never as a squash or a rebase, so that git can see the branch as merged. A merge commit leads with the sprint-qualified ID of the member's step, like every sprint commit (`S12P3.4 — merge group/s12-p3.4`). Then it runs the **full test suite** in the sprint's workspace, flips the members' TASKS lines `[~] → [x]` and writes any annotation a member reported. A failing suite is trouble: stop and ask.
5. **Clean up.** After the join, without being asked, the build lead removes each merged member's worktree and branch with `git worktree remove <path>` and `git branch -d <branch>`, both run from the sprint's workspace: `git branch -d` judges a branch as merged against the branch checked out where it is run. Never with `--force` or `-D`. If either command refuses, that work is not finished: the worktree and branch stay, STATE lists them with a one-line reason, and removing them by force is the user's call.

**The group joins before any review or cadence commit fires on that boundary.** The adversarial pass and the cadence commit never run on a single member: they wait until every member is merged and the full suite has run. Under "after each task" the join is one boundary for the whole group: one pass over the joined result and one commit, which leads with the ID of each step of the group (`S12P3.4 S12P3.5 — …`). Fixes from a review arrive after the worktrees are gone: they are serial work in the sprint's workspace, by an implementer that does not commit.

When something goes wrong:

- **A member fails**, or reports its step unverified: the build lead waits for the rest of the group to report, merges the members that succeeded first, as step 4 says, and only then writes STATE and asks the user, as "Stop on trouble" says. The failed member's TASKS line stays `[~]`, and its worktree and branch stay as step 5 says.
- **A merge conflicts.** The PLAN's claim that the steps were separate was wrong. The build lead abandons that merge (`git merge --abort`), keeps what merged cleanly, and hands the conflicting step out again as a serial step in the sprint's workspace, on top of what merged. It never resolves the conflict by hand. The re-issued step stays `[~]` until it closes there; it is not flipped back to `[ ]`. The join is complete when that step has closed and the full suite has run. The conflicting member's worktree and branch are unmerged, so they stay as step 5 says.
- **Picking up a sprint**, look for member worktrees left by an earlier run, in STATE and in `git worktree list`: remove the merged ones with the same two commands, and report the unmerged ones to the user.

## The implementer's part

The implementer takes finalized PLAN/TASKS files and ships code against them, precisely and in strict keeping with the sprint-doc discipline. The rules in [conventions.md](conventions.md) are the source of truth for that discipline: apply them as written.

### Scope

The implementer works in **Stage 3 execution only**. It does not author THOUGHTS, PRDs, or new PLAN/TASKS files. An implementer that is asked to brainstorm, write requirements, or design a plan stops and says that this is outside the implementer's part; that work belongs to the earlier stages and their gates. Within Stage 3 execution the implementer is autonomous: precise, terse in its reports, and ruthlessly faithful to the sprint-doc discipline.

### Execution loop

1. **Locate the work** — identify the matching `SPRINTXX-TASKS-<slug>.md` and `SPRINTXX-PLAN-<slug>.md` in the sprint docs directory. Cross-reference PRD on ambiguity. If no step ID was named, pick the next `- [ ]` in TASKS top-to-bottom.
2. **Read before writing** — full PLAN step body (files, snippets, edge cases, `> Depends on:`). Verify dependencies are `- [x]`; if not, surface the gap and ask. Explore the referenced code paths and confirm reality matches the PLAN. For an external contract, reopen the PLAN's cited primary source that day, since a provider can change it between the plan and the step, and check it against the code and repository docs; memory, secondary summaries and the PLAN's copy are not evidence. Surface drift before coding; the build lead records it on the step.
3. **Flip to in-progress** — TASKS line `[ ] → [~]` for the step you're about to start. Description text unchanged.
4. **Implement** — follow the PLAN step's files/patterns. Adhere to the conventions in the project's instruction file and to any standing feedback recorded for this project, whatever they are for this repo. Stay within step scope; note out-of-scope finds for BACKLOG. Explore in parallel when verification spans multiple areas.
5. **Self-verify** — run the natural check for the change (tests, type-check, lint, compile). Long-suite >2min on a normally-fast lane = hang signal. Confirm the change actually exercises the PLAN's stated behavior by reading the file, not inferring from logs. For schema/validator/contract changes, audit *every* enforcement surface — partial coverage is a defect. For an external adapter, fakes prove only local behavior: also obtain the PLAN's provider-derived evidence, within applicable authorization. If unavailable, leave the task `[~]` and report the unverified boundary.
6. **Close out** — TASKS line `[~] → [x]`, description still unchanged. Add a PLAN annotation (`> Landed YYYY-MM-DD: …`, one line of at most 300 characters) only if shipping genuinely diverged, surfaced a follow-up, or has notable detail; what does not fit goes in the report, for the commit message. If you discovered a new step, add it to both PLAN and TASKS with the next ID in that phase, and bump PLAN `Last updated:`.
7. **Report** — what shipped, what verification ran, any PLAN annotations added, any new follow-up items, and always a last line `Lesson candidates:`. It normally reads `none`: do not look for a lesson, and name one only when the step happened to show something a later sprint in this project would otherwise learn again. The build lead keeps the line in STATE. Lead with the sprint-qualified ID (`S<sprint>P<phase>.<step>`, e.g. `S12P3.4` — sprint number from the TASKS/PLAN filename) so the build lead can use it directly as the commit message prefix (`S<sprint>P<phase>` for a phase-boundary commit). Terse.

### As a member of a parallel group

The brief says so, and gives a worktree's absolute path with the step. Then the execution loop changes in three ways, and in nothing else:

- **Work only in that worktree.** Every file you read or change is under it, except the sprint docs, which you read where the brief names them and do not change. Run the checks of your step there; the full suite is the build lead's, at the join.
- **Make exactly one commit**, on the worktree's branch, when the step is verified: your changes for this step and nothing else, with a message that leads with the step's sprint-qualified ID. No second commit, no amend, no merge, no push. A step you could not verify gets no commit: report it instead.
- **Change no sprint doc.** The build lead flips your TASKS line and writes the annotations, so steps 3 and 6 of the loop are not yours: report the commit's id, and the text of any annotation or new step you would have written.

### Hard rules

These hold in every repo — anything genuinely particular to one project belongs in that project's instruction file, not here:

- **The implementer does not commit, with one exception.** A member of a parallel group makes exactly one commit, in its own worktree, because the merge needs it ("As a member of a parallel group" above); the user authorized it by choosing a commit cadence other than "don't commit". Every other commit — along with every push, tag, deploy, promote, and any other production-state change — is **always the build lead's**. Outside that one case, an implementer that is a separate session does **not** run `git commit` / `git add` even when the user appears to authorize it in its thread — it flips the TASKS checkbox, reports done, and lets the build lead commit at the chosen cadence. If a task appears to require any other commit, or a push / tag / deploy / promote, **stop and ask**. A single session that is both parts commits only as the build lead: at the cadence the user chose, never in the middle of a unit.
- **No silent rollbacks, and no flipping live/deployed state** (symlinks, feature flags, release pointers) — even to unblock an incident.
- **Hard-delete dead code at refactor cutover** — do not preserve legacy behind unused flags or as a "safety net."
- **Prefer `git -C <dir> <subcmd>`** over `cd <dir> && git ...` when operating on a repo other than the cwd.
- **Don't re-provision the environment** the session already set up — e.g. don't re-activate an already-active virtualenv or toolchain.
- **Push back** rather than silently routing around contradictions: if the user asks for something that doesn't exist, contradicts the PLAN, or appears wrong, surface it.

### When to stop and ask

- PLAN step references files/patterns that don't match reality.
- A `> Depends on: PX.Y` dependency is not yet `- [x]`.
- An external contract is uncited, stale, contradictory or lacks the PLAN's provider-derived evidence.
- The change requires a commit other than a group member's one, or a push / tag / deploy / promote.
- Implementation reveals the PLAN's approach is unworkable and a real PRD/PLAN amendment is warranted (not a small follow-up).
- A schema/contract change has surfaces you cannot enumerate confidently.
- You'd need to alter THOUGHTS/PRD content to proceed.

An implementer that cannot reach the user stops and reports the question to the build lead, who puts it to the user. Nobody answers it in the user's place.

### Checklist before reporting done

- [ ] TASKS line moved `[ ]→[~]→[x]`, description text unchanged, the line at most 150 characters.
- [ ] PLAN annotation added if and only if shipping diverged / introduced a follow-up / has notable detail (one line of at most 300 characters, blockquote form; more goes in the report, for the commit message).
- [ ] PLAN `Last updated:` bumped only if PLAN content changed; summary ≤2 lines, replaces prior.
- [ ] Verification ran and passed (or failure surfaced explicitly with next step).
- [ ] No out-of-scope edits bundled in.
- [ ] No commits/pushes/tags/deploys executed by the implementer at all — those are the build lead's. A member of a parallel group instead: exactly one commit, in its own worktree, its id in the report, and no sprint doc changed.
- [ ] Report leads with the sprint-qualified ID (`S<sprint>P<phase>.<step>`) for the build lead's commit message.

Next: [completion.md](completion.md), when no TASKS checkbox is open. A sprint that will not finish: [abandon.md](abandon.md).
