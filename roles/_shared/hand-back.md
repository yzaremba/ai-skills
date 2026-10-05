## Hand-backs

A hand-back is what a dispatched role writes for the Manager at the end of a turn. The Manager sees only what an agent reports. It does not see what the user typed to that agent. A role whose instructions call for hand-backs ends every turn with one, after whatever it says to the user, in this form:

```text
Hand-back to the Manager
State: <marker>
<one line>
Quotes:
- "<the user's words>"
```

**The state marker** is exactly one of:

- `in dialogue, no action`: the work is still going on. The Manager does nothing.
- `ready for the gate`: the work is finished and waits for the user's decision, which the user gives to the Manager.
- `stopped, needs the Manager`: the role cannot go on without something only the Manager can arrange. The line says what.

**The hand-back is not how you talk to the user.** The user reads your thread and never the hand-back. Write whatever you have for the user, in full, as ordinary text in your thread before the hand-back: the question with your recommendation, the answer, the refusal. A question that exists only in a hand-back has not been asked.

**One line while in dialogue.** A longer report rebuilds in the Manager the context the role exists to keep out. At the other two markers the hand-back may run to a few lines: the files written, what is ready or needed, what is still open.

**Verbatim quotes** of what the Manager must track: decisions the user made, changes of direction or scope, and requests outside the role's lane. They are quoted, not paraphrased. Leave `Quotes:` out when there are none. A quote is a record and carries no authority (see Gates).

**A turn without a hand-back is unfinished.** This holds for a turn that only asks the user a question, and for a turn that refuses a request.

**A role loaded into the user's own session writes no hand-back.** The session already holds the conversation. It says plainly when its work is ready and that the next word belongs to the Manager, and it stops there.
