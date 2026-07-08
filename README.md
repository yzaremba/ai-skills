# AI Skills

A collection of [Cursor Agent Skills](https://docs.cursor.com/context/skills) — self-contained toolkits that give AI coding agents new capabilities.

## Available Skills

| Skill | Description |
|-------|-------------|
| **json-tools** | Inspect, query, and manipulate JSON files using local scripts (Python & Node.js, no external dependencies). |
| **csv-tools** | Inspect, query, and manipulate CSV files using local Python scripts (stdlib only). Probe, filter, sort, group, stats, transform to JSON/JSONL, diff, validate; ignores footer/comment lines. |
| **usage-cost** | Aggregate Claude Code session usage + list-price cost over a configurable window from `~/.claude/projects/`. Per-day bar chart, per-project totals, top-N sessions, token totals (Python stdlib only). |

## Docs

- [PRD Implementation Workflow (slide)](docs/prd-implementation-slide.html) — one-page overview of the [`prd-implementation.md`](prd-implementation.md) / [`epic-implementation.md`](epic-implementation.md) sprint & epic doc workflow.

## Deployment

### Project-level (single repo)

Clone into your project's `.cursor/skills/` directory:

```bash
git clone https://github.com/yzaremba/ai-skills.git .cursor/skills
```

Then add the skill in **Cursor Settings > Skills**, pointing to the `SKILL.md` inside the cloned directory.

### Global (all projects)

Clone to a shared location:

```bash
git clone https://github.com/yzaremba/ai-skills.git ~/.cursor/skills
```

Then add the skill in **Cursor Settings > Skills** (global scope), pointing to the `SKILL.md` at the shared path.

## License

Apache-2.0 — see [LICENSE.txt](LICENSE.txt).
