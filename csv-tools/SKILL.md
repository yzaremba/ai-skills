---
name: csv-tools
description: Inspect, query, and manipulate CSV files with self-contained local scripts. Supports schema discovery, column extraction, row sampling (first/last N), filtering by value/presence, statistics, group-by/cross-tabulation with aggregations, diffs, format transforms (JSON/JSONL), sorting, reversing, merging, and validation. Use when the user references a .csv file and wants to find, get, show, list, search, filter, sort, group, aggregate, count, pivot, explore, query, summarize, inspect, analyze, transform, compare, or clean CSV data — including requests like "give me the top N", "which have X", "most recent", "count by", "group by", or "find all where".
license: Apache-2.0 (see LICENSE.txt)
---

# CSV Tools

This skill provides a local, self-contained toolkit for CSV work.

## Location

- Python scripts are in `csv-tools/scripts/` (Python stdlib only; uses `csv` module).
- Node.js scripts are in `csv-tools/scripts-node/` (Node built-ins only, no npm deps).

## Usage Conventions

- Run from the skill directory or use full paths.
- Every script supports `--help`.
- Most scripts accept input file path or `-` for stdin.
- If a temporary file is needed, create it in the OS temp directory (not in the project tree). Clean up temp files after use unless the user explicitly asks to keep them.
- **Delimiter**: `--delimiter` (e.g. `,`, `\t`, `;`). Use the value from probe output in subsequent commands.
- **Header**: By default the header is **auto-detected**: the first row that has the "stable" column count (the count that appears most often among non-blank rows, at least 2 rows) is treated as the header. This skips descriptive preamble lines (e.g. report title, date range) that have fewer columns. Use `--no-header` for headless CSVs (columns become `col0`, `col1`, ...). Use `--skip-lines N` to skip exactly N preamble lines so the next line is the header.
- **Comment lines**: Optional `--comment-char` (e.g. `#`) to skip lines that start with that character.
- **Footers and comment lines**: Many CSVs contain trailing lines that do not fit the schema (footers, comments, source notes), often at the bottom. Scripts treat only **schema-conforming rows** as data: any row that does not have the same number of columns as the header is **ignored** for probe, stats, filter, group, and all other meaningful operations. Optionally, lines that start with `--comment-char` are skipped. Inform the user when relevant that footer/comment lines are excluded by design.
- **Output format**: Row-data scripts (extract, filter, sort, merge) default to **CSV** output so pipelines work without an extra transform step. Use `--format json` when you need JSON (e.g. for the final step or a JSON consumer). Report scripts (probe, schema, stats, group, diff, validate) always output JSON.

## Pipelines

Chain scripts via stdin/stdout. Row-data scripts default to CSV, so the next stage reads CSV from stdin without needing `transform.py` in between.

```bash
python scripts/filter.py data.csv --where "amount>0" | python scripts/sort.py - --by date
python scripts/extract.py data.csv --first 100 | python scripts/filter.py - --non-empty id
```

With Node.js:

```bash
node scripts-node/filter.mjs data.csv --where "amount>0" | node scripts-node/sort.mjs - --by date
```

To get JSON from the last step, add `--format json`:

```bash
python scripts/filter.py data.csv --where "amount>0" --format json
python scripts/filter.py data.csv --where "amount>0" | python scripts/sort.py - --by date --format json
```

## Quick Workflow

1. **Probe first** — run `probe.py` on any new CSV **before** opening or reading the file. Do not open or read the CSV to inspect structure; use probe’s output as the source of truth for delimiter, row count, column names, and sample.
2. Use the probe output (`delimiter`, `columns`, `has_header`) for all subsequent commands.
3. Use `--skip-lines`, `--no-header`, or `--delimiter` only when probe (or a later script) shows they’re needed, or when the user specifies them — do not infer these from having read the file.
4. Extract/filter/sort/group/transform as needed.
5. Use stats, schema, or diff for deeper inspection.

```bash
python scripts/probe.py data.csv
# Then use delimiter and columns in subsequent commands.
```

## Command Reference

If using Node.js, substitute `node scripts-node/X.mjs` for `python scripts/X.py` — all arguments are identical.

### 0) Probe file structure

Run this first on any new CSV. Returns `delimiter`, `has_header`, `header_row` (1-based index of the header in the parsed rows; 0 if no header), `record_count` (schema-conforming rows only), `columns`, `encoding`, and a sample row. Rows with wrong column count (e.g. footers) are not counted. Use `header_row - 1` as `--skip-lines` in other scripts to reproduce the same header when needed.

```bash
python scripts/probe.py data.csv
python scripts/probe.py data.csv --delimiter "\t"
python scripts/probe.py data.csv --no-header --comment-char "#"
python scripts/probe.py data.csv --skip-lines 6   # skip 6 preamble lines; line 7 = header
```

### 1) Show schema

```bash
python scripts/schema.py data.csv
python scripts/schema.py data.csv --delimiter ";" --counts
```

### 2) Extract columns and/or rows

Output is CSV by default; use `--format json` for JSON.

```bash
python scripts/extract.py data.csv --fields id,name,amount
python scripts/extract.py data.csv --first 10
python scripts/extract.py data.csv --last 5 --fields date,value --format json
```

### 3) Filter by conditions

Output is CSV by default; use `--format json` for JSON.

```bash
python scripts/filter.py data.csv --where "age>=18"
python scripts/filter.py data.csv --in status:active,pending --empty notes
python scripts/filter.py data.csv --contains description:urgent --regex id:"^A[0-9]+"
python scripts/filter.py data.csv --non-empty email --format json
```

**Shell escaping**: Values for `--where`, `--in`, `--contains`, `--regex` are interpreted by the shell before the script sees them. If a value contains `$` (e.g. `$0.00`), the shell expands it as a variable and the filter can return wrong results. Use **single-quoted** arguments so the shell does not expand: `--where 'Fees!="$0.00"'`. Alternatively escape `$` in double-quoted strings: `--where "Fees!='\$0.00'"`.

### 4) Statistics

Per-column: presence, unique count, top values, min/max/mean for numeric. Only schema-conforming rows are included.

```bash
python scripts/stats.py data.csv
python scripts/stats.py data.csv --fields region,amount --top 5
```

### 5) Sort

Output is CSV by default; use `--format json` for JSON.

```bash
python scripts/sort.py data.csv --by date,id --desc
python scripts/sort.py data.csv --by amount --numeric --format json
```

### 6) Reverse row order

Output is CSV by default; use `--format json` for JSON.

```bash
python scripts/reverse.py data.csv
python scripts/reverse.py data.csv --format json
```

### 7) Group by / cross-tabulation

```bash
python scripts/group.py data.csv --by region
python scripts/group.py data.csv --by region,status --agg "amount:sum" --agg "id:count"
python scripts/group.py data.csv --by region --sort key --top 5
```

Supported `--agg` functions: `count`, `sum`, `min`, `max`, `mean`, `list`, `unique`. Use `--sort count` (default, descending) or `--sort key` (ascending).

### 8) Merge (concat) CSVs

Output is CSV by default; use `--format json` for JSON.

```bash
python scripts/merge.py a.csv b.csv c.csv --unique-by id
python scripts/merge.py a.csv b.csv --format json
```

### 9) Transform to JSON / JSONL / CSV

When `--to` is omitted, output format matches input (CSV in → CSV out, JSON in → JSON out) so pipelines stay consistent.

```bash
python scripts/transform.py data.csv --to json
python scripts/transform.py data.csv --to jsonl > data.jsonl
python scripts/transform.py data.json --from-format json --to csv > out.csv
python scripts/transform.py -   # stdin CSV → stdout CSV (e.g. in a pipeline)
```

### 10) Diff two CSVs

```bash
python scripts/diff.py before.csv after.csv --key id
python scripts/diff.py before.csv after.csv --format text
```

### 11) Validate CSV

Checks consistent column count, encoding, and optionally strict row length. Reports non-data rows (e.g. footer count).

```bash
python scripts/validate.py data.csv
python scripts/validate.py data.csv --strict
```

## Script Intent

- **probe.py**: Detect delimiter, header, row count (data rows only), columns, sample; output JSON for the agent. Ignores footer/comment lines. Header is auto-detected (first row with stable column count) unless `--skip-lines` or `--no-header` is set.
- **common.py**: Shared CSV read/write; skip rows that don't match header column count or that start with comment-char. Auto-detect header as first row with stable column count (skips preamble); optional `skip_lines` for explicit preamble skip.
- **schema.py**: Infer column types and optional presence/counts.
- **extract.py**: Select columns and/or first/last N rows. Default output CSV; `--format json` for JSON.
- **filter.py**: Keep rows matching `--where`, `--in`, `--contains`, `--regex`, `--empty`, `--non-empty`. Default output CSV; `--format json` for JSON.
- **stats.py**: Per-column summaries (presence, uniques, top values, numeric). Output JSON.
- **sort.py**: Sort by one or more columns. Default output CSV; `--format json` for JSON.
- **reverse.py**: Reverse the order of data rows. Default output CSV; `--format json` for JSON.
- **group.py**: Group by column(s) with optional aggregations. Output JSON.
- **merge.py**: Concat CSVs with optional deduplication by key column. Default output CSV; `--format json` for JSON.
- **transform.py**: CSV to JSON/JSONL/CSV; JSON/JSONL to CSV. When `--to` is omitted, output format matches input.
- **diff.py**: Compare two CSVs by key columns or row order.
- **validate.py**: Well-formed CSV check; report data vs non-data row counts.
- **scripts-node/*.mjs**: Node.js equivalents for every script above with matching CLI flags and output shapes.

## Notes for the Agent

- Do NOT read the CSV before running `probe.py`. If already done, please disregard and use the results of `probe.py` only.
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
- **Always probe first** on a new CSV: run probe **without having read the file**, then use probe’s output for `--delimiter` and other options in later commands. Do not infer `--skip-lines` or header handling from reading the file; add those options only when probe (or a later script) indicates they’re needed, or the user specifies them.
- **Use these scripts** over ad-hoc code for CSV operations they support. Only write custom code when no script covers the task.
- Do not narrate every script invocation; run scripts and present interpreted results. Include command details only when the user asks for verbose output.
- **Footers/comments**: CSV files often have footer or comment lines that don't match the schema (usually at the bottom). All scripts ignore such lines for meaningful operations — only schema-conforming rows are counted, filtered, grouped, etc. Tell the user when this is relevant.
- Pipelines: chain scripts via pipes; row-data scripts default to CSV so `filter.py ... | sort.py - --by col` works without a transform step. Use `--format json` on the final step when JSON is needed. Same with Node: `node scripts-node/filter.mjs ... | node scripts-node/sort.mjs - --by col`.
- If a script gives unexpected output, check `--help` and adjust `--delimiter`, `--no-header`, or `--comment-char`.
- **Escaping in filter/where**: When `--where` (or `--in`, `--contains`, `--regex`) values contain shell-special characters like `$`, use single-quoted arguments (e.g. `--where 'Fees!="$0.00"'`) so the shell does not expand variables. Otherwise the script may receive a different string and return incorrect results (e.g. everything matching).
