# A project's own specialist

A specialist is an agent for narrow work that only one project needs, such as operations, data research or a release. None is shipped here. A project that needs one defines it, in the project.

## Where it lives

One definition on each provider the project uses, written by hand in the provider's own format:

| Provider | File | Holds |
|---|---|---|
| Claude Code | `.claude/agents/<name>.md` | Frontmatter with `name` and `description`, then the instructions as the body. |
| Codex | `.codex/agents/<name>.toml` | `name`, `description` and `developer_instructions`. |

- **`name`**: not the id of a role here, because a project's definition replaces a user-level one of the same name. The roles here use underscores on Codex where they use hyphens on Claude Code.
- **`description`**: one sentence that says what the specialist knows and when it is used. The dispatching role chooses it by this.
- **Instructions**: the specialist's own. What it knows, what it may touch, and the lines under "What its instructions must carry".
- **Model and effort** are set per specialist, in its definition.
- **On Codex** a project's definitions load only in a trusted project, in a session started at the project root.

The setup tool does not write, change or remove these files. It generates definitions only from the role directories under `roles/`, so nothing here reaches a specialist unless you put it in its instructions.

## How it is engaged

- **A brief with a mode**, as [`_shared/specialists.md`](_shared/specialists.md) states it. `consult` is advice, or an inspection that changes nothing. `act` is anything that changes state outside the repository.
- **Consulted directly.** The role that has the question briefs the specialist with `consult`: the Manager or the Product Manager. An Investigator dispatches no agent: its question for a specialist comes back in its report.
- **Acts only through the Manager.** Only the Manager writes an `act` brief, on the user's word for that action.

## What its instructions must carry

A specialist is given none of the shared text, so copy these into it:

- The brief names a mode. Under `consult`, or with no mode named, change nothing.
- Under `act`, do what the brief names and no more.
- Dispatch no agent.
- Report the answer, the evidence, the confidence, what was not checked and a suggested next step.

On Claude Code a definition can also enforce a limit, with a list of allowed or denied tools. On Codex it cannot: a definition's read-only sandbox is ignored in an interactive session, and the specialist runs under the sandbox of the session that dispatched it and keeps the agent tools. There the lines above are the only limit. See "Provider support" in [`docs/agent-roles-framework.md`](../docs/agent-roles-framework.md).
