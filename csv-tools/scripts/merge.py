#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Concatenate CSV files with optional deduplication by key column."""

from __future__ import annotations

import argparse
import sys

from common import load_csv, parse_delimiter, write_csv, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge (concat) CSV files.")
    parser.add_argument("inputs", nargs="+", help="Input CSV files in order.")
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row of each file is data.")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines per file; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")
    parser.add_argument("--unique-by", help="Deduplicate by this column (keep first occurrence).")
    parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format (default: csv).")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON when --format json.")
    args = parser.parse_args()

    all_columns: list[str] | None = None
    all_rows: list[dict[str, str]] = []
    delim = parse_delimiter(args.delimiter)

    for path in args.inputs:
        columns, rows = load_csv(
            path,
            delimiter=delim,
            has_header=not args.no_header,
            comment_char=args.comment_char,
            encoding=args.encoding,
            skip_lines=args.skip_lines,
        )[:2]
        if all_columns is None:
            all_columns = columns
        for row in rows:
            if all_columns and columns == all_columns:
                all_rows.append(dict(row))
            else:
                all_rows.append({c: row.get(c, "") for c in all_columns})

    if all_columns is None:
        all_columns = []

    if args.unique_by and all_columns and args.unique_by in all_columns:
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for row in all_rows:
            key = (row.get(args.unique_by) or "").strip()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        all_rows = deduped

    if args.format == "csv":
        write_csv(all_columns, all_rows, delim, sys.stdout)
    else:
        write_json(all_rows, compact=args.compact)


if __name__ == "__main__":
    main()
