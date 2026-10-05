## Working from a brief, writing the report

Dispatched, you start with a fresh context. The brief is all you know, and your report is all your dispatcher gets back.

**A brief states** the goal; the spec, by file and by requirement id or PLAN step id (where no document exists, the brief's own text is the spec and says so); the working directory and the branch; the files or area you may change; what is decided and ruled out; whether the user will talk to you in your thread or there is no dialogue; the check; whether to commit and with what message; and anything extra to return. A brief that does not ask for a commit means no commit. A brief that does not say the user will talk to you means no dialogue.

**A report states,** in this order and briefly:

- **Status.** Done, partly done, or stopped.
- **What changed.** The files, and the commit id if a commit was asked for.
- **Verification.** What was run and its result, and what was not verified.
- **Deviations** from the spec, each with its reason.
- **Open.** Questions with their options, follow-ups, and anything found outside the scope.

**Rules:**

- **Stop instead of guessing.** If you cannot complete your brief as written, stop and report the specific question with concrete options. A brief that lacks its spec or its working directory is answered with what is missing, not with work.
- **Report what was observed.** "The tests pass" means they were run in this turn and passed.
