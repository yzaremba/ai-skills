---
name: json-tools
description: Inspect, query, and manipulate JSON files with self-contained local scripts. Supports schema discovery, field extraction, row sampling (first/last N), filtering by value/presence/type/structure, flattening, statistics, diffs, format transforms (CSV/JSONL), sorting, merging, and validation. Use when the user references a .json file and wants to do anything with its contents, or asks to find, get, show, list, search, look up, filter, sort, count, explore, query, summarize, inspect, analyze, transform, compare, or clean records/fields/values in JSON data — including natural-language requests like "give me the top N", "which have X enabled", "most recent", or "find all where".
license: Apache-2.0 (see LICENSE.txt)
---

# JSON Tools

This skill provides a local, self-contained toolkit for JSON work.

## Location

- Python scripts are in `json-tools/scripts/` (Python stdlib only).
- Node.js scripts are in `json-tools/scripts-node/` (Node built-ins only, no npm deps).

## Usage Conventions

- Run from the skill directory or use full paths.
- Every script supports `--help`.
- Most scripts accept input file path or `-` for stdin.
- If a temporary file is needed, create it in the OS temp directory (not in the project tree).
  - Shell: use `mktemp` (or equivalent) so files land under the system temp folder.
  - Python: use `tempfile` (`tempfile.gettempdir()`, `NamedTemporaryFile`, or `TemporaryDirectory`).
  - Clean up temp files/directories after use unless the user explicitly asks to keep them.
- JSON path syntax:
  - Dot keys: `user.profile.name`
  - Array index: `users[0].id`
  - Wildcard: `users[*].email`

## Quick Workflow

1. Validate input JSON.
2. Inspect schema.
3. Extract/filter/sort/transform as needed.
4. Use stats or diff for QA checks.

```bash
python scripts/validate.py data.json --strict
python scripts/schema.py data.json --counts
```

## Command Reference

If using Node.js, substitute `node scripts-node/X.mjs` for `python scripts/X.py` -- all arguments are identical.

### 1) Show schema

```bash
python scripts/schema.py data.json --depth 6 --counts
```

### 2) Extract fields

```bash
python scripts/extract.py data.json --array-path users --fields id,name,address.city
```

### 3) Extract rows (first/last N)

```bash
python scripts/extract.py data.json --array-path users --first 10
python scripts/extract.py data.json --array-path users --last 10
```

### 4) Filter by fields/presence/types

```bash
python scripts/filter.py data.json --array-path users --where "age>=18" --exists email
python scripts/filter.py data.json --array-path users --type "address=object" --not-exists deletedAt
```

### 5) Flatten nested JSON

```bash
python scripts/flatten.py data.json --array-path users --separator "."
```

### 6) Statistics

Output: `record_count`, `field_count`, and per-field breakdown with `presence` (e.g. `50/100`), `types`, `unique_values`, `top_values` (most frequent, controlled by `--top`), and `numeric` (min/max/mean) when applicable. Omit `--fields` to auto-discover all top-level fields.

```bash
python scripts/stats.py data.json --array-path users
python scripts/stats.py data.json --array-path users --fields age,country --top 5
python scripts/stats.py data.json --array-path items --fields status,country --top 10
```

When the user asks to "summarize" or "describe" a JSON dataset, use `stats.py` (optionally combined with `schema.py`). `stats.py` already provides per-field detail (with --fields flag) including presence, types, unique counts, top values, and numeric summaries — do NOT write custom code for these.  Please limit the summary to what stats.py provides unless the user explicitely asks for more.

### 7) Diff two JSON files

```bash
python scripts/diff.py before.json after.json --format text
python scripts/diff.py before.json after.json --ignore-order
```

### 8) Transform formats

```bash
python scripts/transform.py data.json --array-path users --to csv > users.csv
python scripts/transform.py data.json --array-path users --to jsonl > users.jsonl
python scripts/transform.py users.csv --from-format csv > users.json
```

### 9) Sort by fields

```bash
python scripts/sort.py data.json --array-path users --by age,name --numeric
python scripts/sort.py data.json --array-path users --by createdAt --desc
```

### 10) Merge files

```bash
python scripts/merge.py a.json b.json c.json --mode concat --unique-by id
python scripts/merge.py a.json b.json --mode shallow
python scripts/merge.py a.json b.json --mode deep
```

### 11) Validate JSON

```bash
python scripts/validate.py data.json --strict
```

## Script Intent

- `common.py`: shared path parsing, extraction, flattening, typing, output helpers.
- `schema.py`: infer practical structure and field presence.
- `extract.py`: select fields and sample rows.
- `filter.py`: conditional record filtering.
- `flatten.py`: normalize nested data to flat keys.
- `stats.py`: descriptive summaries for arrays of records.
- `diff.py`: structural change report.
- `transform.py`: JSON<->CSV/JSONL conversion.
- `sort.py`: deterministic ordering by fields.
- `merge.py`: concat/shallow/deep merge modes.
- `validate.py`: syntax and structural sanity checks.
- `scripts-node/*.mjs`: Node.js equivalents for every script above with matching CLI flags and output shapes.

## Notes for the Agent

- Runtime auto-selection (do this once per session and reuse the choice):
  - Detect runtimes:
    - `python3 --version 2>/dev/null || python --version 2>/dev/null`
    - `node --version 2>/dev/null`
  - Prefer Python when available:
    - `python3 scripts/<tool>.py` (fallback to `python` if needed)
  - If Python is unavailable but Node.js is available:
    - `node scripts-node/<tool>.mjs`
  - Do not ask the user which runtime to use; select automatically and continue.
  - **Node.js stdout verification** (run once, only when Node.js will be used):
    - Run: `node -e "console.log('__stdout_ok__')"`
    - If the output contains `__stdout_ok__`, Node.js stdout works — proceed normally.
    - If the output is empty (exit code 0 but no captured text), the execution environment is silently swallowing Node.js stdout. Inform the user and recommend one of:
      1. Run Node.js commands with `required_permissions: ["all"]` to bypass sandbox restrictions.
      2. Have scripts write output to a temp file, then read the file back.
    - Ask the user which approach they prefer before proceeding. Reuse their choice for the rest of the session.
- Do NOT narrate individual script invocations (e.g., avoid "Let me run stats.py..." or "Running the schema command..."). Do NOT display raw command lines or uninterpreted JSON output to the user. Execute scripts silently and present only the final interpreted results. Include per-command details only when the user asks for verbose output.
- **Always use** these scripts over ad-hoc one-off commands. Only use custom code when no script covers the task.
- **Do not** use ad-hoc Python scripts or other ad-hoc tools for JSON operations that these scripts already support. Only write custom code when no bundled script covers the task.
- **If a script gives unexpected output**, check `--help` and adjust arguments (e.g. `--array-path`, field names, `--top`). Debug the invocation rather than falling back to ad-hoc code.
- If the user asks about this skill's capabilities, respond first with a concise 5-8 bullet summary of supported operations, then ask which operation they want to run.
- If the user asks for only a quick peek, start with:
  - `python scripts/validate.py <file>`
  - `python scripts/schema.py <file>`
- For large arrays, combine commands:
  - `extract.py --first/--last` then `stats.py` or `filter.py`.
