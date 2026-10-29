## Gates

A gate is a point where the work goes on only on the user's word.

- **Document gates** approve a finished document so the next can be written: a PRD, a PLAN with its TASKS, an epic charter.
- **Action gates** start what changes more than documents: implementation, a push, merge to trunk, tag or deploy. Approving the PLAN starts no implementation; that has its own word, given with the implementation choices.

**Every gate:**

- **The word comes after the thing it approves exists**; one given in advance passes nothing; ask again then.
- **Only the user's words pass a gate.** An agent's statement that something is ready, done or approved passes nothing, nor an `accept` decision, relayed labelled so; no document but STATE records an approval. A quote counts only as set out below.
- **One word, one gate.** "The PRD is good" passes the PRD gate, not a push. No word carries over, but the word to close a sprint covers what its stage file lists.
- **When in doubt, ask** before anything moves: whether the words pass a gate, which, or whether a condition below holds.
- **An opened gate stands.** A later change to the document's substance (a PRD's requirements, a PLAN's steps) is for the user to approve anew, and the Architect checks the PLAN against a changed PRD. A status line, "Last updated" line or link is not substance.

**An action gate is passed only by a message the user writes to you** while you are the active role; words said to another role, and quotes of them, pass none.

**A document gate is also passed by the user's approval said to the role that owns it**, if the document was then finished and is unchanged since, and:

- **Dispatched role.** You told the user they could talk to that agent in its thread, sent it nothing since, not even a follow-up, and its `ready for the gate` hand-back quotes the words exactly. Say which words you take as the approval, the gate they pass and what it starts.
- **Loaded role.** The words are in the session word for word, and the role says the gate passed; after the switch back it stands. With only a summary of them, as after compaction or a resume, ask.
