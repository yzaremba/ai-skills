## Gates

A gate is a point where the work goes on only on the user's word; it opens when that word passes it.

- **Document gates** approve a finished document so that the next can be written: a PRD, a PLAN with its TASKS, an epic charter, an epic roadmap.
- **Action gates** start something that changes more than documents: implementation, and any push, merge to trunk, tag or deploy.

Approving the PLAN with its TASKS starts no implementation: that action gate has its own word, given with the implementation choices.

**Every gate:**

- **The word comes after the thing it approves exists.** A word given in advance passes nothing: ask again when the thing exists.
- **Only the user's words pass a gate.** An agent's statement that something is ready, done or approved passes nothing and triggers nothing, and no document records an approval. Words an agent quotes from the user count only as set out below.
- **One word, one gate.** "The PRD is good" passes the PRD gate. It authorizes no push, and no gate's word carries over to the next, but the word to close a sprint covers what its stage file lists.
- **When in doubt, ask** before anything moves: whether the user's words pass a gate, which one, or whether a condition below holds.
- **An opened gate stands.** A later change to the document's substance, the requirements of a PRD or the steps of a PLAN, is a new change for the user to approve, and the Architect checks the PLAN against a changed PRD. A status line, a "Last updated" line or a link is not substance.

**An action gate is passed only by a message the user writes to you** while you are the active role. Words said to another role, and any quote of them, pass none.

**A document gate is also passed by the user's approval said to the role that owns the document**, when the document was finished when the user spoke and has not changed since, and:

- **Dispatched role.** You told the user they could talk to that agent in its thread, have sent the agent nothing since, not even a follow-up, and its `ready for the gate` hand-back quotes the words exactly. Tell the user which words you take as the approval, which gate they pass and what it starts.
- **Loaded role.** The words are in the session word for word. The role says the gate passed, and after the switch back it stands. With only a summary of them, as after compaction or a resume, ask.
