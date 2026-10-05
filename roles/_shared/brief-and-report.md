## Briefs and reports

A dispatched role starts with a fresh context. The brief is all it knows, and the report is all its dispatcher gets back.

**A brief states:**

- **Goal.** One sentence.
- **Spec.** The document by file, and the part of it by id: a requirement id or a PLAN step id. The spec is pointed at, not paraphrased. Where no document exists, as for a hotfix, the brief's own text is the spec and says so.
- **Where.** The working directory, given in full as the session shows it, and the branch.
- **Scope.** The files or area the role may change, and what it must leave alone.
- **Known.** What is decided and what is ruled out. The user's decisions are quoted.
- **Check.** How the work is verified.
- **Git.** Whether to commit, and with what message. A brief that does not ask for a commit means no commit.
- **Return.** Anything the report must hold beyond the list below.

**A report states,** in this order and briefly:

- **Status.** Done, partly done, or stopped.
- **What changed.** The files, and the commit id if a commit was asked for.
- **Verification.** What was run and its result, and what was not verified.
- **Deviations** from the spec, each with its reason.
- **Open.** Questions with their options, follow-ups, and anything found outside the scope.

**Rules:**

- **Stop instead of guessing.** A role that cannot complete its brief as written stops and reports the specific question with concrete options. A brief that lacks its spec or its working directory is answered with what is missing, not with work.
- **Report what was observed.** "The tests pass" means they were run in this turn and passed.
- **A report is a claim.** The dispatcher checks what is cheap to check, such as that a commit exists, before it relays the result.
