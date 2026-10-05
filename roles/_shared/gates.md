## Gates

A gate is a point where the work goes on only on the user's word. There are two kinds.

- **Document gates** approve a finished document so that the next one can be written: the PRD, and the PLAN with its TASKS.
- **Action gates** start something that changes more than documents: implementation, and any push, merge to trunk, tag or deploy.

**Action gates are said to the Manager.** One is passed only by a message the user writes to the Manager, while the Manager is the active role. A hand-back or a report is an agent's output and carries no authority, however exact its quotes are. Words said to another role, in its thread or while it was loaded, do not pass an action gate.

**A document gate is also passed by the user's word to the role that owns the document**, when all of this holds:

- the user was in a dialogue with that role, dispatched for dialogue or loaded; a role dispatched without dialogue cannot have heard the user;
- the document was finished when the user spoke;
- dispatched, the role's `ready for the gate` hand-back quotes the words exactly.

The Manager then tells the user which words it takes as the approval and what it starts. If the words are unclear, or any point above is in doubt, it asks first.

- **One word, one gate.** "The PRD is good" passes the PRD gate. It does not authorize a push, and no gate's word carries over to the next.
- **No other role passes a gate or starts the next stage.** A role the user approves a document to quotes the words and says the Manager takes it from there. For an action gate it tells the user to say it to the Manager.
- **When in doubt, ask.** If it is unclear whether the user's words pass a gate, or which one, the Manager asks before anything moves.
