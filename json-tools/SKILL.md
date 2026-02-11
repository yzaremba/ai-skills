---
name: json-tools
description: Inspect and manipulate JSON files with self-contained local scripts. Supports schema discovery, field extraction, row sampling (first/last N), filtering by value/presence/type/structure, flattening, statistics, diffs, format transforms (CSV/JSONL), sorting, merging, and validation. Use when the user asks to explore, query, transform, compare, or clean JSON data.
license: Apache-2.0 (see LICENSE.txt)
---

# JSON Tools

This skill provides a local, self-contained toolkit for JSON work.

## Location

All scripts are in `json-tools/scripts/` and use Python stdlib only.

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

```bash
python scripts/stats.py data.json --array-path users --fields age,country --top 5
```

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

## Notes for the Agent

- Prefer these scripts over ad-hoc one-off commands for consistency.
- If the user asks about this skill's capabilities, respond first with a concise 5-8 bullet summary of supported operations, then ask which operation they want to run.
- If this skill creates new files inside the project directory/subdirectories, explicitly tell the user which files were created and reference the paths in your response so those files are brought into active context.
- After creating project files, briefly restate the new artifacts before moving on to the next step.
- Be quiet about script execution details by default. Report concise outcomes, file artifacts, and actionable errors; only include per-command/script narration when the user asks for verbose output.
- If the user asks for only a quick peek, start with:
  - `python scripts/validate.py <file>`
  - `python scripts/schema.py <file>`
- For large arrays, combine commands:
  - `extract.py --first/--last` then `stats.py` or `filter.py`.
