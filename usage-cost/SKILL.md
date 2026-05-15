---
name: usage-cost
description: Show Claude Code usage + list-price cost across all sessions over a window (default last 24h). Aggregates the local JSONL session logs under ~/.claude/projects/ and prints a per-day bar chart, per-project totals, top-N sessions by cost, and token totals. Use when the user asks about Claude usage, cost, burn, billing, /usage, or "what did I spend on Claude". Args parsed as "[N]" or "[Nd]" (days; fractional ok), with word forms "today / week / month", and optional flags "top=N", "no-per-day", "no-top".
license: Apache-2.0 (see LICENSE.txt)
---

# Usage Cost

Aggregates Claude Code session usage from `~/.claude/projects/**/*.jsonl` and surfaces totals + breakdowns over a configurable window. Cost is **public-API list price** — on Claude Pro / Max plans the real billing is the flat subscription, so these numbers are **relative-burn**, not an invoice preview.

## Location

- Python script: `usage-cost/scripts/usage_cost.py` (Python stdlib only — no pip deps).

## How to invoke

From the skill directory:

```
python3 scripts/usage_cost.py [--days N] [--top N] [--no-per-day] [--no-top]
```

Or by absolute path (useful when wired into an agent slash command):

```
python3 <path-to-skill>/scripts/usage_cost.py [--days N] [...]
```

Defaults: `--days 1 --top 15` (last 24h, top 15 sessions by cost).

## Parsing the user's args

Take whatever the user typed after the skill name and map it:

- Bare number → `--days N` (e.g. `7` → `--days 7`, `0.5` → `--days 0.5`)
- `Nd` / `N day` / `N days` → `--days N`
- `Nh` / `Nhr` / `N hour` / `N hours` → `--days N/24`
- `24h` / `today` / `1d` → `--days 1`
- `week` → `--days 7`
- `month` → `--days 30`
- `top=N` or `--top N` → `--top N`
- `no-per-day` / `nopd` → `--no-per-day` (omits the daily bar chart)
- `no-top` → `--no-top` (omits the top-sessions table)

If args are empty, run with defaults. If args are ambiguous, ask the user.

## After running

The script prints six sections: window header, per-day breakdown (with bar chart), per-project totals, top-N sessions, token totals, and a pricing-reference footer.

Surface the raw output to the user verbatim (inside a fenced code block), then add 2–3 lines of interpretation if anything stands out:

- A single day or session that's a meaningful outlier
- Cache-read savings (cache_read tokens × $13.50/M = list-price avoided vs uncached input)
- An unusual project consuming meaningful share

Do **not** invent context about what specific sessions did — session IDs are opaque without reading the JSONLs. If the user asks "what was session X about", read the first few lines of the matching `~/.claude/projects/*/X*.jsonl` to surface the first user prompt.

## Accounting

- **Strict in-window**: only assistant messages whose timestamp falls inside the window contribute to per-day, per-project, and per-session totals. A long-running session that started before the window is included with only its in-window portion.
- **Side effect**: "start UTC" in the top-sessions table is the **first in-window** message timestamp, not the session's true birth time. The alternative was inflated totals from pre-window activity.
- **Subagent JSONLs** under `**/subagents/` are included via `rglob` — they're real billable token use.

## Pricing reference

USD per 1M tokens (Anthropic public API list, as of mid-2026):

| Model family | Input | Output | Cache read | Cache write 5m | Cache write 1h |
|---|---:|---:|---:|---:|---:|
| Opus 4.x   | $15.00 | $75.00 | $1.50 | $18.75 | $30.00 |
| Sonnet 4.x | $3.00  | $15.00 | $0.30 | $3.75  | $6.00  |
| Haiku 4.x  | $0.80  | $4.00  | $0.08 | $1.00  | $1.60  |

Edit the `PRICING` table in `scripts/usage_cost.py` when rates change or when adding model families.

## When *not* to use

- The user opened `/usage` (built-in settings panel in some clients) — that's a different command. Only run this skill if they explicitly ask for the data, or `/usage` left them wanting more detail.
- The user wants **real-money billing** — direct them to the Anthropic Console (`console.anthropic.com`) for invoiced usage.
