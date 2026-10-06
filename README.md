# AI Skills

Skills, roles, a rule and a setup tool for AI coding agents, written once and installed
for both [Claude Code](https://code.claude.com/docs/en/skills) and
[Codex](https://developers.openai.com/codex/skills). One clone is the source; every
provider home links to it.

This is version 2. Version 1, two rule files and an agent file beside the skills, is at
the tag `v1.0`; [Moving from v1](#moving-from-v1) says how to get from there to here.

## Layout

| Path | Holds |
|------|-------|
| `prd-implementation/`, `epic-implementation/` | The sprint and epic process as two skills: a short entry file and one reference file per stage. |
| `csv-tools/`, `json-tools/`, `self-reflection/`, `usage-cost/` | Skills. A skill is a directory at the root that holds `SKILL.md`. |
| `multiagent-collab/` | A skill with its own setup, protocol file, hooks and tests. |
| `roles/` | The sources of the roles: `<role>/ROLE.md` and `<role>/role.toml`, the sections roles share in `_shared/`, and `bindings.toml`, which says which role follows which stage of the process. Format: [`roles/README.md`](roles/README.md). |
| `rules/` | `avoid-bash-injection-heuristics/`, a rule for Claude Code: how to shape a Bash command so that the permission checks that ignore the allowlist do not fire. Codex has no place for a rule. |
| `providers/` | What differs between providers, in `claude-code/` and `codex/`: `dictionary.toml` (what the tiers and effort names mean there, and the version it was checked on) and `actions.md` (how a role's actions are done there). |
| `tools/` | `setup/`: the setup tool, `workflow_setup.py`, with its shipped defaults and tests. `session-profile/`: prints the role, model and effort a provider recorded for each agent of a session. |
| `docs/` | [`agent-roles-framework.md`](docs/agent-roles-framework.md): the design of the roles and what was checked on each provider. [`v1-to-v2.md`](docs/v1-to-v2.md). The v1 slide. |
| [`AGENTS.md`](AGENTS.md) | The repository's conventions. Both providers read it; there is no `CLAUDE.md`. |

### What each skill is for

| Skill | For | Providers |
|-------|-----|-----------|
| [`prd-implementation`](prd-implementation/SKILL.md) | A sprint in stages with explicit gates: backlog, THOUGHTS, PRD, PLAN and TASKS, implementation, archiving. | Claude Code, Codex |
| [`epic-implementation`](epic-implementation/SKILL.md) | An effort of several sprints: EPIC THOUGHTS, the charter, the roadmap, its sprints, archiving. | Claude Code, Codex |
| [`json-tools`](json-tools/SKILL.md) | Inspect, query and transform JSON files with local scripts (Python or Node, no dependencies). | Claude Code, Codex |
| [`csv-tools`](csv-tools/SKILL.md) | The same for CSV files. | Claude Code, Codex |
| [`self-reflection`](self-reflection/SKILL.md) | A review of the finished conversation that reports only what would change future work. Runs only when asked for. | Claude Code, Codex |
| [`usage-cost`](usage-cost/SKILL.md) | Claude Code usage and list-price cost over a window, from Claude Code's own session logs. | Claude Code |
| [`multiagent-collab`](multiagent-collab/SKILL.md) | An owner and an adversarial reviewer across Codex and Claude, through a shared filesystem baton. | Claude Code, Codex |

## Installation

There are two installers. The collaboration skill, `multiagent-collab`, has its own,
described first; the setup tool leaves that skill alone, whatever is at its path.
Everything else (the other six skills, the rule and the roles) is installed by the setup
tool, under [Skills](#skills) below. The two may use one clone or two: `doctor` reports
a collaboration skill linked from another clone as information, not as a fault.

### `multiagent-collab` for Codex and Claude

This skill needs its setup utility; cloning it directly into one agent's discovery
directory is not enough. Prerequisites are Python 3, Codex CLI, and Claude Code.
The workflow below is locally verified with `codex-cli 0.154.0`. Current OpenAI
documentation identifies `$HOME/.agents/skills` as Codex's user skill location and
supports symlinked skill folders; behavior of other Codex versions should be
verified with the included doctor command. See the official
[Codex skills](https://developers.openai.com/codex/skills) and
[hooks](https://developers.openai.com/codex/hooks) documentation.

Keep one persistent clone, inspect the planned changes, then install for both
agents:

```bash
git clone https://github.com/yzaremba/ai-skills.git ~/workspace/skills
cd ~/workspace/skills
python3 multiagent-collab/scripts/multiagent_collab.py setup --agent both --dry-run
python3 multiagent-collab/scripts/multiagent_collab.py setup --agent both
```

The defaults are home `~` and chat root `~/workspace/chat`. To change them, pass
`--home PATH` and `--chat-root PATH` to both setup invocations. Setup preserves
unrelated configuration, records backups below `<chat-root>/_backups/`, and never
claims or removes the shared `~/.agents` or `~/.agents/skills` directories.

Setup installs session hooks but does not start agents or opt sessions in. Restart
Codex and Claude. In Codex, open `/hooks`, review the exact user hook, and trust its
current hash. Then give each agent this instruction in its own session:

```text
Use $multiagent-collab. Bind this session to ~/workspace/chat and verify wake delivery.
```

Claude will ask you to keep its printed `tail -n 0 -F .../monitor.inbox` Monitor
running. Each agent sends a nonce through its real wake transport and verifies the
nonce returned to the session. When both are ready, check the installation:

```bash
cd ~/workspace/skills
python3 multiagent-collab/scripts/multiagent_collab.py doctor --agent both --require-binding
```

Start work from either bound agent; the initiating agent becomes owner and the other
becomes reviewer:

```text
Use $multiagent-collab. Start a task for: <describe the work and completion condition>.
```

For upgrades, first ask both live agents to `release` their bindings. A live
same-session `rebind` is intentionally a no-op and does not reload upgraded watcher
code. Update the persistent clone, review the protocol hash if it changed, and rerun
setup:

```bash
cd ~/workspace/skills
git pull --ff-only
sha256sum ~/workspace/chat/PROTOCOL.md multiagent-collab/assets/PROTOCOL.md
python3 multiagent-collab/scripts/multiagent_collab.py setup --agent both --dry-run --upgrade-protocol-from APPROVED_CURRENT_SHA256
python3 multiagent-collab/scripts/multiagent_collab.py setup --agent both --upgrade-protocol-from APPROVED_CURRENT_SHA256
```

Restart both agents, then use `bind` again, repeat the nonce proofs, and rerun doctor.
Never use `--upgrade-protocol-from` until the displayed current hash and replacement
were reviewed and approved. Setup verifies real Codex discovery with the offline
`codex debug prompt-input` command; if that probe is unavailable, it warns and does
not remove a working legacy discovery link.

To remove the managed integration while preserving protocols, tasks, backups, and
archives:

```bash
cd ~/workspace/skills
python3 multiagent-collab/scripts/multiagent_collab.py uninstall --agent both --dry-run
python3 multiagent-collab/scripts/multiagent_collab.py uninstall --agent both
```

### Skills

The setup tool, `tools/setup/workflow_setup.py`, installs the skills, the rule and the
roles. It needs Python 3.11 or later and nothing outside the standard library. The
provider dictionaries were checked on 2026-10-05:

| Provider | Checked on | Oldest supported |
|----------|------------|------------------|
| Claude Code | 2.1.289 | 2.1.281 |
| Codex CLI | 0.160.0 | 0.134.0 |

Setup installs for each provider that is installed (its program is on `PATH`, or its
home exists). It writes only inside the provider homes (`~/.claude`, `~/.codex`, or
where `CLAUDE_CONFIG_DIR` and `CODEX_HOME` point), `~/.agents`, and a project named with
`--project`; never inside the clone, and never at a credentials file. It backs up every
file it replaces or removes, under `~/.agents/workflow-setup/backups/`, and `uninstall`
puts back what was there.

**One shared clone.** Every home links to the clone, so one clone has to be readable
from every home. On a Linux machine any persistent clone will do. On a Windows machine
with WSL, clone on a Windows drive and use the same clone from both sides: as
`<drive>:\<clone>` from Windows, and through its mount path, `/mnt/<drive>/<clone>`,
from WSL. `render` refuses a clone that both sides cannot read, unless
`--allow-unshared-clone` is given. Pull that clone with Windows git.

```bash
git clone https://github.com/yzaremba/ai-skills.git <clone>
```

**Then, once on each side** (once on Linux; on Windows with WSL, once from Windows and
once from WSL), from the root of the clone. Where `python` is a project's virtual
environment, use a system interpreter.

```bash
python tools/setup/workflow_setup.py homes
python tools/setup/workflow_setup.py init --dry-run
python tools/setup/workflow_setup.py init
python tools/setup/workflow_setup.py render --dry-run
python tools/setup/workflow_setup.py render
python tools/setup/workflow_setup.py doctor
```

- `homes` only reads: it prints the homes this side would handle and whose each place
  is. A place whose real path is on the other side is skipped here and written by the
  run on that side.
- `init` writes `~/.agents/workflow.toml`: which model each tier means and which value
  each effort name means, for each installed provider, and the process, roles and memory
  settings. It asks, proposes the value in effect, and shows the mapping before it
  writes. For Codex it checks the mapping against `codex debug models`.
- `render` links each skill into the skills directory of each provider it names
  (`~/.claude/skills`, and `~/.agents/skills` for Codex), links the rule into
  `~/.claude/rules`, and generates the role definitions and the entry points of a
  session. One conflict (a file, a directory or a foreign link where a link would go)
  stops the run before anything is written. Exit code 3 means the rest was done and
  something was skipped or kept that an option would change; the output names each.
  `render --no-roles` installs the skills and the rule without any role.
- `doctor` checks the sources, what setup wrote and the providers, and writes nothing.
  Exit code 1 means an error. It starts provider programs (`--version`, the model list,
  offline discovery commands) and the collaboration skill's own doctor; a provider's
  program may write state of its own into its home. Only `doctor --prove-discovery`
  starts a session with a model, one per provider, and that spends quota.

Read each dry run before the real run, and run one command at a time; every command's
`--help` states exactly what it does. `uninstall --dry-run` and `uninstall` take an
install back. A home that holds a v1 install is migrated in the same `render`: see
[Moving from v1](#moving-from-v1). Without the option named there, `render` stops on a
v1 copy that is in the way of a link.

## What a `git pull` in the clone does

- **Skills and the rule change at once**, in every home on both sides: each is a link
  into the clone, and no home holds a copy.
- **Generated files change at the next `render`**: the role definitions, the loaded-role
  skills, the Codex profile file, and what a project got. They are made from the role
  sources and the settings. Until then the `drift` check of `doctor` reports each one as
  a warning. Run `render` on each side after a pull; with nothing to change it plans
  nothing and says so.
- **The models stay as confirmed.** The tier and effort mapping in
  `~/.agents/workflow.toml` does not follow a new dictionary; it changes when `init` is
  run again.

## Moving from v1

A v1 install left two import lines in the user-level `CLAUDE.md`, rule copies, loose
skill copies and the `sprint-coder` agent in the homes. `doctor` reports each as an
error until it is gone. `render` removes them with `--migrate-v1`, always with a dry run
first:

```bash
python tools/setup/workflow_setup.py render --migrate-v1 --dry-run
python tools/setup/workflow_setup.py render --migrate-v1
python tools/setup/workflow_setup.py doctor --only v1
```

What it removes, each after a backup:

- The lines `@rules/prd-implementation.md` and `@rules/epic-implementation.md` in the
  Claude Code `CLAUDE.md`, as whole lines. A marked block that points to the two skills
  is added at the end, and the Codex `AGENTS.md` gets the same block.
- The v1 rule files in the Claude Code rules directory, `agents/sprint-coder.md`, and
  the loose copies of the v1 skills in the skills directories, Codex's deprecated
  `<codex home>/skills` among them. A file goes only when its content is a committed
  version of the v1 file; a link only when it leads to such a copy or into this clone.

What it keeps and reports, with exit code 3:

- A copy edited by hand, or a link it does not recognise. The dry run prints
  `--remove-stale PATH` for each; add that option to remove the one named.
- A git clone inside a skills directory, which is never removed, with any option. Move
  it away yourself.

Projects are not migrated: a project whose `.claude/rules/` links to a removed rule copy
is left with a dangling link, and the run warns of it. On a machine with both sides, run
Windows first, then WSL. Each run skips the places the other side owns, so both are
needed; where the WSL home links its `CLAUDE.md` and rules into the Windows home, the
Windows run is the one that changes them. `uninstall` puts back what the migration
removed. [`docs/v1-to-v2.md`](docs/v1-to-v2.md) says, section by section, where each
v1 rule went.

## Using it

**The process.** Both providers load a skill when a request matches its description:
"start a sprint", "write the PRD", "plan an epic". A skill can also be named:
`/prd-implementation` on Claude Code, `$prd-implementation` on Codex. `self-reflection`
runs only when named. The process names no role and needs none: `render --no-roles`
installs it alone.

**Roles.** A role is an agent with its own instructions, a pinned model tier and effort,
and limits. Three exist today; the framework document describes six more (Investigator,
Idea Reviewer, Architect, Plan Reviewer, Implementation Manager, Code Reviewer) that are
not written yet, and until then the Manager briefs the Coder itself. There is no
project-memory skill yet either, though the `memory.dir` setting is already there.

| Role | What it does | Claude Code | Codex |
|------|--------------|-------------|-------|
| Manager | The session the user starts: routes requests, holds the gates, writes no file. | `claude --agent manager`, or `/manager` in a session | `codex --profile manager`, or `$manager` in a session |
| Product Manager | Develops one idea with the user into THOUGHTS and a PRD. | Dispatched by the Manager; the user types in its thread. Or loaded: `/product-manager` | Loaded: `$product-manager`. The user cannot type to a dispatched agent there |
| Coder | Implements one brief and verifies it. A second definition, `coder-hard`, has a higher profile. | Dispatched | Dispatched |

Loading a role suspends any other, and does not switch the session's model: the role
says which model and effort it is meant for, and the user switches with `/model` and
`/effort` on Claude Code, `/model` on Codex. On Codex, start the session at the project
root.

**A project.** Nothing is written in a project unless it is named. To make every session
in a project start as the Manager:

```bash
python tools/setup/workflow_setup.py init --project DIR --manager-default
python tools/setup/workflow_setup.py render --project DIR --dry-run
python tools/setup/workflow_setup.py render --project DIR
```

`init --project DIR` writes `DIR/.agents/workflow.toml`. `render --project DIR` refreshes
the homes as without the option, and in the project sets `"agent"` in
`DIR/.claude/settings.json`, writes a marked block at the head of
`DIR/.codex/config.toml`, writes a role definition for each role the project's settings
change, and lists what it generated in `DIR/.gitignore`.

**Settings.** Four layers, later wins: the shipped defaults, `~/.agents/workflow.toml`,
`DIR/.agents/workflow.toml` and `DIR/.agents/workflow.local.toml`.

```bash
python tools/setup/workflow_setup.py show
python tools/setup/workflow_setup.py show roles
python tools/setup/workflow_setup.py show roles --project DIR
```

`show` prints each effective setting and the layer it came from; `show roles` adds the
model and effort each role definition runs with on each provider.

More: [`roles/README.md`](roles/README.md) for the format of a role,
[`docs/agent-roles-framework.md`](docs/agent-roles-framework.md) for the design and the
gate results, `providers/<name>/actions.md` for how each action is done on a provider,
and each skill's `SKILL.md`.

## Limits known so far

- **On Codex a role's limits are instructions, not enforced.** A definition's read-only
  sandbox is ignored in an interactive session (gate G10, Codex CLI 0.160.0): a
  dispatched agent runs under its parent's sandbox and keeps the agent tools. Claude
  Code denies the tools in the definition.
- **The linked rule in a Cowork session.** In the words of `render --help`: A Cowork
  session on the desktop does not load a linked user-level rule: there Claude Code skips
  "a symlinked ~/.claude/rules/ directory or rule file that points outside the working
  directory" (code.claude.com/docs/en/memory, read 2026-10-05). The page names the rules
  directory and a rule file; a linked directory inside rules/, which is what this
  command makes, is taken to be skipped the same way. Every other Claude Code session
  loads the rule through the link.
- **A loaded role in a long Claude Code session.** After a compaction Claude Code keeps
  the first 5,000 tokens of an invoked skill. `render` marks both loaded roles LONG at
  this commit: about 5,900 tokens for `/manager` and 6,100 for `/product-manager`, by an
  estimate of one token per three bytes, which errs high. What would be cut is the end,
  the provider's action notes.
- **Git on Codex.** The default sandbox keeps `.git` read-only, so a commit or a
  worktree needs approval command by command, or a permission profile (beta in Codex).
  `render --apply-codex-settings` defines one, `workflow`, and with
  `--default-codex-permissions` also selects it. While the user's `config.toml` sets
  `sandbox_mode` no profile is written, because Codex then ignores
  `default_permissions`; setup never changes `sandbox_mode`.
- **Four agents on Codex by default**, counting the main session; the same option sets
  `agents.max_concurrent_threads_per_session = 8` where the file sets no limit.
- **Codex reads a project's `.codex/config.toml` only in a trusted project.** In an
  untrusted one the Manager default does nothing on Codex.
- **Discovery cannot be shown for everything.** No provider output that was found lists
  Codex's role definitions, and Claude Code lists nothing without a session: `doctor`
  reports those items as unproven.
- **The Manager's effort on Claude Code is open.** Its definition pins medium, and the
  session record showed the main thread at high.
- **Not exercised yet:** an approval of a document said to the role that owns it and
  taken at the Manager, on either provider; a loaded role on Codex beyond six turns or
  across a compaction.
- **Other programs.** The guards on where setup writes and removes hold against the disk
  as a run finds it, not against another program that changes the same directories
  while the run is under way.
- **Native Windows.** The setup tool's tests pass under a Windows Python, where a link
  is a directory junction. That Claude Code and Codex on Windows read what is installed
  through junctions has not been shown yet.

## The v1 slide

[`docs/prd-implementation-slide.html`](docs/prd-implementation-slide.html) is a one-page
overview of the sprint process as it was in v1
([rendered](https://yzaremba.github.io/ai-skills/prd-implementation-slide.html)). It
has not been brought up to v2.

## License

Apache-2.0 — see [LICENSE.txt](LICENSE.txt).
