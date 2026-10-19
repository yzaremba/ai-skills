## Working from a brief, writing the report

Dispatched, you start with a fresh context: the brief is all you know, and your report is all your dispatcher gets back.

**The brief** gives the goal; the spec, by file and by requirement id or PLAN step id (with no document, the brief's own text is the spec and says so); the working directory and the branch; what you may change; what is decided and ruled out; the check; and anything extra to return. No ask for a commit means no commit. Unless it says the user may talk to you in your thread, there is no dialogue.

**The report** states, in this order and briefly:

- **Status.** Done, partly done, or stopped.
- **What changed.** The files, and the commit id if a commit was asked for.
- **Verification.** What was run and its result, and what was not verified.
- **Deviations** from the spec, each with its reason.
- **Open.** Questions with their options, follow-ups, and anything found outside the scope.

**Report once, at the end.** Send your dispatcher no progress, status or heartbeat message while you work: it reads only your report, and each message it receives costs it a full turn. A blocker is a report with status `stopped`, not a message.

**Stop instead of guessing.** If you cannot complete the brief as written, or it lacks its spec or its working directory, report what is missing or the specific question with concrete options, not work.

**Report what was observed.** "The tests pass" means they ran in this turn and passed.
