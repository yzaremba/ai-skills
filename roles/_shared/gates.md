## Gates

A gate is a point where the work goes on only on the user's word. There are two kinds.

- **Document gates** approve a finished document so that the next one can be written: the PRD, and the PLAN with its TASKS.
- **Action gates** start something that changes more than documents: implementation, and any push, merge to trunk, tag or deploy.

Approving the PLAN with its TASKS does not start implementation. That is a separate action gate with its own word to the Manager, which the user gives with the implementation choices.

**Every gate:**

- **The word comes after the thing it approves exists.** A word given in advance ("whatever it writes, build it") passes nothing. The Manager asks again when the thing exists.
- **Only the user's words pass a gate.** An agent's own statement that something is ready, done or approved passes nothing and triggers nothing. Words it quotes from the user count only as set out below.
- **One word, one gate.** "The PRD is good" passes the PRD gate. It does not authorize a push, and no gate's word carries over to the next.
- **When in doubt, ask.** If it is unclear whether the user's words pass a gate, or which one, or whether a condition below holds, the Manager asks before anything moves.

**An action gate is passed only by a message the user writes to the Manager** while the Manager is the active role. Words said to another role, in its thread or while it was loaded, pass no action gate, and neither does any quote of them.

**A document gate is also passed by the user's approval said to the role that owns the document**, when the first condition holds and the one that fits how the role ran:

- **The document was finished when the user spoke and has not changed since.** An approval covers the document as it stood. Any later change voids it: the role says so and never repeats an earlier approval as current.
- **Dispatched role.** The Manager itself told the user to talk to that agent in its thread, has sent the agent nothing since, not even a follow-up, and the agent's `ready for the gate` hand-back quotes the words exactly. A quote from an agent dispatched without dialogue passes nothing. Nor does any agent's quote on a provider where the user cannot type to a dispatched agent; the action notes say which.
- **Loaded role.** After the switch back, the user's own message is in the Manager's context word for word. With only a summary of it, as after compaction or a resume, the Manager asks.

The Manager then tells the user which words it takes as the approval, which gate they pass and what it starts.

**No other role passes a gate or starts the next stage.** A role the user approves its finished document to records the words and says that the Manager decides what they pass and will say so. For an action gate it tells the user to say it to the Manager.
