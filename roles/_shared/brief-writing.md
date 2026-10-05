## Writing briefs, reading reports

A role you dispatch starts with a fresh context. Your brief is all it knows, and its report is all you get back.

**A brief states:**

- **Goal.** One sentence.
- **Spec.** The document by file, and the part of it by requirement id or PLAN step id: pointed at, not paraphrased. Where no document exists, as for a hotfix, the brief's own text is the spec and says so.
- **Where.** The working directory, in full as the session shows it, and the branch.
- **Scope.** What the role may change, and what it must leave alone.
- **Known.** What is decided and what is ruled out. The user's decisions are quoted.
- **Dialogue.** One of two: the user will talk to the role in its thread, or there is no dialogue.
- **Check.** How the work is verified.
- **Git.** Whether to commit, and with what message. No ask means no commit.
- **Return.** Anything the report must hold beyond status, changes, verification, deviations and open questions.

**A report is a claim.** Check what is cheap to check, such as that a commit exists, before you relay the result.
