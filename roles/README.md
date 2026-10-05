# Roles

A role is an agent with its own instructions, a pinned model tier and effort, and limits. The design and its reasons are in [`docs/agent-roles-framework.md`](../docs/agent-roles-framework.md). This file states the format of a role's sources.

## Layout

```text
roles/
  README.md
  _shared/          sections that several roles include
  <role>/ROLE.md    the role's instructions
  <role>/role.toml  the role's profile, limits and entry points
```

- **One directory per role**, named by the role's id in kebab-case: `manager`, `product-manager`, `coder`.
- **`_shared/`** is not a role. Each file in it is one section, starting at a level-two heading. `gates.md` reads the same for every role. The other sections come in two parts, one for each side, so that a role carries only its own:

  | File | For a role that |
  |---|---|
  | `gates.md` | holds a gate or owns a gated document |
  | `hand-back-writing.md` | is dispatched and hands back to the Manager |
  | `hand-back-reading.md` | receives hand-backs |
  | `brief-writing.md` | dispatches: writes briefs and reads reports |
  | `brief-reading.md` | is dispatched: works from a brief and writes the report |
- **A role's full text** is `ROLE.md` followed by its includes, in the order `role.toml` lists them. A provider's definition adds that provider's action notes after it.

## `role.toml`

| Key | Type | Meaning |
|---|---|---|
| `name` | string | The role's id. Equals the directory name. |
| `title` | string | The name used in prose, e.g. `Product Manager`. |
| `description` | string | One sentence. It becomes the description in each provider's definition, so it says when the role is used. |
| `includes` | array of strings | File names in `_shared/`, appended to `ROLE.md` in this order. |
| `[profile]` `tier` | string | `fast`, `standard`, `deep` or `frontier`. |
| `[profile]` `effort` | string | `low`, `medium`, `high` or `max`. |
| `[profile]` `high_stakes_tier` | string, optional | The tier used in place of `tier` when the settings mark the work as high-stakes. |
| `[profile.hard]` | table, optional | A second profile, with `tier` and `effort`. It yields a second definition named `<name>-hard` from the same instructions. Only the Coder has one. |
| `[limits]` `edits` | boolean | May the role change files. |
| `[limits]` `commands` | boolean | May the role run shell commands. |
| `[limits]` `dispatches` | array of strings | The definitions the role may dispatch, by id (`coder-hard` counts as one). An empty array bars dispatch. |
| `[entry]` `dispatch` | boolean | The role can be dispatched as a subagent with a fresh context. |
| `[entry]` `load` | boolean | The role can be loaded into the user's own session. |
| `[entry]` `start` | boolean | The role can be the role a session starts as. |

A role names a tier and an effort, never a model. The settings map both to each provider's values.

A limit is enforced by the provider's definition wherever that provider can enforce it. `ROLE.md` states every limit as well, because not every provider enforces every one.

## Rules for role text

- **Actions, not tools.** Role text says what is done: dispatch a role, follow up with an agent, load a role, change a file, run a command, commit. It never names a provider's tool or command. How each provider performs an action is in `providers/<provider>/actions.md`.
- **One active role.** Every `ROLE.md` says that loading it suspends any other role loaded in the session.
- **No machine paths.** No home directory, mounted drive or drive letter appears in any file here. A role is pointed at "the project's process text" or "the working directory your brief names", and the brief supplies the path when the work starts.
- **Size.** `ROLE.md` plus its includes stays under 12,000 bytes. A loaded role has to survive context compaction, and a dispatched one shares its budget with the project's instruction files.
- **Bytes.** UTF-8, LF line endings.
