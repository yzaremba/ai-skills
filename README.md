# AI Skills

A collection of extensions for AI coding agents, including
[Codex](https://developers.openai.com/codex/skills),
[Cursor](https://docs.cursor.com/context/skills), and
[Claude Code](https://code.claude.com/docs/en/skills). Compatibility is documented
per skill; the repository also includes Claude-Code-specific rules and a subagent.

## Available Skills

| Skill | Description |
|-------|-------------|
| **json-tools** | Inspect, query, and manipulate JSON files using local scripts (Python & Node.js, no external dependencies). |
| **csv-tools** | Inspect, query, and manipulate CSV files using local Python scripts (stdlib only). Probe, filter, sort, group, stats, transform to JSON/JSONL, diff, validate; ignores footer/comment lines. |
| **usage-cost** | Aggregate Claude Code session usage + list-price cost over a configurable window from `~/.claude/projects/`. Per-day bar chart, per-project totals, top-N sessions, token totals (Python stdlib only). *Claude Code only — reads Claude Code's own session logs.* |
| **self-reflection** | End-of-conversation self-review that surfaces only genuinely critical observations — lessons learned, memory candidates, workflow recommendations. High bar: silent if there's nothing worth saying. Invoked explicitly, not auto-triggered. |
| **multiagent-collab** | Coordinate a Codex/Claude owner-reviewer workflow through a shared filesystem baton, including setup, watchers, diagnosis, and verified archival. |

## Rules (Claude Code)

Plain markdown files meant to live in Claude Code's [`.claude/rules/`](https://code.claude.com/docs/en/memory#organize-rules-with-claude/rules/) directory — a different mechanism from Skills above, and not applicable to Cursor.

| Rule | Loads when | Description |
|------|-----------|-------------|
| [`prd-implementation.md`](prd-implementation.md) | Working with `docs/SPRINT*-*.md`, `docs/SPRINT-INDEX.md` (`paths:` frontmatter) | Gated Backlog → THOUGHTS → PRD → PLAN/TASKS → Implementation workflow for feature sprints. See the [one-page overview](docs/prd-implementation-slide.html). |
| [`epic-implementation.md`](epic-implementation.md) | Working with `docs/EPIC*-*.md`, `docs/EPIC-INDEX.md` (`paths:` frontmatter) | Multi-sprint EPIC container — THOUGHTS → PRD (charter) → ROADMAP — that decomposes into ordinary sprints run under the rule above. |
| [`avoid-bash-injection-heuristics.md`](avoid-bash-injection-heuristics.md) | Every session (no `paths:` field) | Reference for reshaping Bash commands to dodge the two permission gates that ignore your allowlist: the "too-complex" parser heuristics, and the `deniedPathInsideDirectory` circuit breaker that fires whenever a `Read()` deny rule exists. |

## Agents (Claude Code)

| Agent | Description |
|-------|-------------|
| [`sprint-coder`](agents/sprint-coder.md) | Implementation subagent for Stage 3 (PLAN/TASKS execution) of `prd-implementation.md` — flips TASKS checkboxes, ships code, self-verifies, and never commits/pushes/deploys unilaterally. Uses Claude Code's native `memory: project` scope for persistent, per-project learnings. |

## Docs

[![PRD Implementation Workflow slide preview](docs/prd-implementation-slide-preview.png)](https://yzaremba.github.io/ai-skills/prd-implementation-slide.html)

- [PRD Implementation Workflow (slide)](https://yzaremba.github.io/ai-skills/prd-implementation-slide.html) — one-page overview of the [`prd-implementation.md`](prd-implementation.md) / [`epic-implementation.md`](epic-implementation.md) sprint & epic doc workflow.

## Installation

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

#### Claude Code

Skills are auto-discovered from `.claude/skills/` (project) or `~/.claude/skills/` (personal, all projects) — no settings step needed.

```bash
# Project-level (this project only)
git clone https://github.com/yzaremba/ai-skills.git .claude/skills

# Personal (all projects)
git clone https://github.com/yzaremba/ai-skills.git ~/.claude/skills
```

#### Cursor

Clone into your project's `.cursor/skills/` directory:

```bash
git clone https://github.com/yzaremba/ai-skills.git .cursor/skills
```

Then add the skill in **Cursor Settings > Skills**, pointing to the `SKILL.md` inside the cloned directory. For a global install (all projects), clone to `~/.cursor/skills` instead and add it under Cursor's global scope.

Rules and the agent below are individual files rather than self-contained folders, so both start from one persistent clone (avoid `/tmp` here — it's typically wiped on reboot, which would leave symlinks into it dangling):

```bash
git clone https://github.com/yzaremba/ai-skills.git ~/ai-skills
```

### Rules (Claude Code only)

Drop the rule file(s) you want into `.claude/rules/` (project) or `~/.claude/rules/` (personal, all projects) — they're auto-discovered, no `@import` line needed. Symlinks work too, so you can keep the one clone above and link in only what you want:

```bash
mkdir -p ~/.claude/rules
ln -s ~/ai-skills/prd-implementation.md ~/.claude/rules/prd-implementation.md
ln -s ~/ai-skills/epic-implementation.md ~/.claude/rules/epic-implementation.md
ln -s ~/ai-skills/avoid-bash-injection-heuristics.md ~/.claude/rules/avoid-bash-injection-heuristics.md
```

(Swap `ln -s` for `cp` if you'd rather not depend on `~/ai-skills` sticking around.)

### Agents (Claude Code only)

Copy the agent file into `.claude/agents/` (project) or `~/.claude/agents/` (personal) — subagents are auto-discovered the same way:

```bash
cp ~/ai-skills/agents/sprint-coder.md ~/.claude/agents/sprint-coder.md
```

## License

Apache-2.0 — see [LICENSE.txt](LICENSE.txt).
