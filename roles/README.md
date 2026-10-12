# Roles

A role is an agent with its own instructions, a pinned model tier and effort, and limits. The design and its reasons are in [`docs/agent-roles-framework.md`](../docs/agent-roles-framework.md). This file states the format of a role's sources.

## Layout

```text
roles/
  README.md
  SPECIALISTS.md    the convention for a project's own specialist
  bindings.toml     which role follows which stage file of the process
  _shared/          sections that several roles include
  <role>/ROLE.md    the role's instructions
  <role>/role.toml  the role's profile, limits and entry points
```

- **One directory per role**, named by the role's id in kebab-case: `manager`, `product-manager`, `coder`.
- **`_shared/`** is not a role. Each file in it is one section, starting at a level-two heading. Most sections come in two parts, one for each side, so that a role carries only its own:

  | File | For a role that |
  |---|---|
  | `gates.md` | holds the gates: the Manager |
  | `gates-owning.md` | owns a gated document |
  | `hand-back-writing.md` | is dispatched and hands back to the Manager |
  | `hand-back-reading.md` | receives hand-backs: the Manager |
  | `brief-writing.md` | dispatches: writes briefs and reads reports |
  | `brief-reading.md` | is dispatched: works from a brief and writes the report |
  | `review-commissioning.md` | commissions a review |
  | `review-reporting.md` | reviews: the three reviewers |
  | `specialists.md` | no shipped role; a project's own specialist carries it (`SPECIALISTS.md`) |
  | `worktrees.md` | runs a parallel group of Coders |
  | `questions.md` | puts questions to the user |
- **A role's full text** is `ROLE.md` followed by its includes, in the order `role.toml` lists them. A provider's definition adds the role's rows of `bindings.toml` and that provider's action notes after it: the whole file, or the sections the role's `actions` names.

## `role.toml`

| Key | Type | Meaning |
|---|---|---|
| `name` | string | The role's id. Equals the directory name. |
| `title` | string | The name used in prose, e.g. `Product Manager`. |
| `description` | string | One sentence. It becomes the description in each provider's definition, so it says when the role is used. |
| `includes` | array of strings | File names in `_shared/`, appended to `ROLE.md` in this order. |
| `actions` | array of strings, optional | The sections of each provider's `actions.md` the role is given, by id: the notes of the actions it takes and no others. Without the key the role is given the whole file. |
| `[profile]` `tier` | string | `fast`, `standard`, `deep` or `frontier`. |
| `[profile]` `effort` | string | `low`, `medium`, `high` or `max`. |
| `[profile]` `high_stakes_tier` | string, optional | The tier used in place of `tier` when the settings mark the work as high-stakes. |
| `[profile]` `cache` | string, optional | `long`: the role waits between its turns, on the user or on agents it dispatched, and its context stays cached the longer time where the provider's definition can say so. Without the key the provider's own lifetime holds. On Claude Code a dispatched role's definition then names the one-hour prompt cache (`providers/claude-code/dictionary.toml`, `[cache]`); Codex has no such key and nothing is written there. No setting changes it, and `[profile.hard]` does not take it. |
| `[profile.hard]` | table, optional | A second profile, with `tier` and `effort`. It yields a second definition named `<name>-hard` from the same instructions. Only the Coder has one. |
| `[limits]` `edits` | boolean | May the role change files. |
| `[limits]` `commands` | boolean | May the role run shell commands. |
| `[limits]` `dispatches` | array of strings | The definitions the role may dispatch, by id (`coder-hard` counts as one). An empty array bars dispatch. |
| `[entry]` `dispatch` | boolean | The role can be dispatched as a subagent with a fresh context. |
| `[entry]` `load` | boolean | The role can be loaded into the user's own session. |
| `[entry]` `start` | boolean | The role can be the role a session starts as. |

A role names a tier and an effort, never a model. The settings map both to each provider's values.

A limit is enforced by the provider's definition wherever that provider can enforce it. `ROLE.md` states every limit as well, because not every provider enforces every one.

## `bindings.toml`

The process is two skills, `prd-implementation` and `epic-implementation`. Each is split into stage files under its `references/` directory, and neither names a role. `bindings.toml` is the binding table: the one file that says which role follows which stage file, with a row for every stage file of both skills. No other file names both a stage and a role. It also binds the roles that write lessons to `lifecycle.md` of the `project-memory` skill, which is no process skill: a file of it needs no row.

The file holds `schema_version = 1` and one `[[binding]]` table per row:

| Key | Type | Meaning |
|---|---|---|
| `role` | string | A role's id: a directory under `roles/`. A row of `coder` holds for both of its definitions. |
| `skill` | string | The name of a process skill, or of `project-memory`: a directory at the repository root that holds `SKILL.md`. Never a path. |
| `stage` | string | The file name of a file in that skill's `references/` directory: a stage file, such as `stage-2-prd.md`, or `lifecycle.md`. A file name only, with no directory. |
| `part` | string | What the role does in that stage: `owns`, or the id of a part of it, in lower-case letters and hyphens. |
| `note` | string, optional | One line of at most 200 characters that says what the part covers. It is given to the role with the row. |

```toml
[[binding]]
role = "<role id>"
skill = "<skill name>"
stage = "<stage file name>"
part = "owns"
note = "<optional: what the part covers>"
```

- **`owns`** means that the role does everything the stage file asks of whoever runs the stage: it writes the stage's documents, takes the stage's own confirmations from the user, and makes the changes to shared files that the stage file calls for.
- **Any other `part`** names a share of the stage. Where the stage file defines the part under that name, as `stage-3-implementation.md` defines the implementer's part, the id is that name. Where it does not, the row has a `note`.

  | `part` | Meaning |
  |---|---|
  | `implementer` | The implementer's part of the implementation stage. |
  | `build-lead` | The build lead's part of the implementation stage, and of the file on a sprint's STATE. |
  | `choices` | Of the implementation stage: resolves the implementation choices with the user and prints their summary. |
  | `critical-pass` | Of a PRD or charter stage: makes the tests of the critical pass and none of the stage's changes. |
  | `reviews` | Reads what the stage's documents must hold, to check a document against it. Writes nothing. |
  | `decomposes` | Of the roadmap stage: writes the roadmap, all but the seam. |
  | `seam` | Of the roadmap stage: the seam, when a sprint the roadmap plans is started. |
  | `checks` | Of the deferred items: runs the check command when a session starts, makes the full check with its named checks when the user asks, and puts what needs a decision to the user. Writes nothing. |
  | `writes` | Of the deferred items: writes the outcome the user decided for an item. |
  | `close-commands` | Of completion, and of abandoning a sprint: puts the decisions of the close to the user and runs its commands. Writes nothing. |
  | `close-writer` | Of completion, and of abandoning a sprint: what the close writes and commits. |
  | `lessons` | Of the project memory's lifecycle: proposes lessons, and writes each one the user approved. The Manager has no row: it puts a proposal to the user, sends the answer to the role that made it, and writes no file. A lesson the user asks it to record goes, outside a build, to the Product Manager. |

- **A row is unique** by `role`, `skill` and `stage`. A stage file may have several rows, one for each role with a part in it.
- **Every stage file has a row**, and `validate` fails one that has none (`stage-unbound`). A process skill is a skill that holds a file `references/stage-*.md`. Its stage files are the `.md` files directly in its `references/` directory, whatever their names, with three exceptions: `conventions.md`, which holds in every stage and is read through each stage file, and the two provider files, `claude-code.md` and `codex.md`, which say how an action is done and not who does it. A file in a directory below `references/` is not a stage file.
- **Not every role has a row.** The Investigator and the Code Reviewer follow no stage file: the brief and the role's own text are all they work from, and their definitions say so.
- **Every name is checked.** The role is a directory here, the skill is a directory at the repository root, and the stage file exists in it.
- **A role's rows reach the role in its generated definition.** Role text therefore says "the stage file your binding names" and never names the file. The generated section tells the role to read the file before it acts on it. Setup writes a skill's rows under the path of that skill's stage files in the provider's skills directory, from `~`, so that no role searches the disk for a skill.
- **A note may give a command of the skill** where the role runs it without reading the stage file first, as the Manager runs the check command when a session starts.

## Action notes

`providers/<provider>/actions.md` says how that provider performs each action the role text names. It opens with a level-two heading and a short head, which every role is given, and goes on in sections under level-three headings. A section's id is its heading in lower case with hyphens: "In dialogue" is `in-dialogue`. Both providers' files have the same sections, and a role's `actions` names the ones it needs:

| Section | For a role that |
|---|---|
| `start` | none: how the user starts a session as a role, and what the notes were checked against, kept as the record |
| `session` | is loaded into the user's session, or tells the user to load one |
| `dispatch` | dispatches |
| `dialogue` | dispatches a role the user talks to |
| `in-dialogue` | is dispatched and talks to the user |
| `read` | reads and runs no command: the Idea and Plan Reviewers |
| `commands` | runs commands |
| `files` | changes files |
| `commit` | commits, or creates or switches a branch |
| `parallel-group` | runs several Coders at once, each in a worktree |

## Rules for role text

- **Actions, not tools.** Role text says what is done: dispatch a role, follow up with an agent, load a role, change a file, run a command, commit. It never names a provider's tool or command. How each provider performs an action is in `providers/<provider>/actions.md`.
- **One active role.** Loading a role suspends any other role loaded in the session. Setup puts that sentence at the head of the skill a loaded role is installed as, so `ROLE.md` does not repeat it.
- **The minimum.** Role text holds what the role needs to act and nothing else: no rule said twice between a role and a section it includes, no reason where the rule alone is enough, no include and no action section the role does not use. A section that a role needs only a part of is split by side.
- **The process by name.** A role follows the two process skills and names them by skill name, never by path. Which stage file it reads comes from its bindings. A command of a skill is described, as in "the check command of the `prd-implementation` skill"; the exact invocation is in the skill. It is given to a role, relative to the skill, only where the role runs it without reading a stage file first: in a binding's note, and for the settings script where the role is told to read a setting.
- **No machine paths.** No home directory, mounted drive or drive letter appears in any file here. A role is pointed at "the working directory your brief names", and the brief supplies the path when the work starts.
- **Size.** A role that can be loaded (`load = true`) gives a skill of at most 5,000 tokens on every provider, by setup's estimate of one token per three bytes: that is what Claude Code keeps of an invoked skill after a compaction. The skill is everything the role is given, with setup's own lines at its head. For every role, `ROLE.md` plus its includes stays under 12,000 bytes, because a dispatched role shares its budget with the project's instruction files. `validate` fails a role over either limit, and its `--json` output gives each loaded role's size on each provider.
- **Bytes.** UTF-8, LF line endings.
