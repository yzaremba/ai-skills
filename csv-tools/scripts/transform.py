#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Transform CSV to JSON/JSONL and JSON/JSONL to CSV."""

from __future__ import annotations

import argparse
import json
import sys

from common import load_csv, parse_delimiter, read_text, write_csv, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Transform CSV to JSON/JSONL or JSON/JSONL to CSV.")
    parser.add_argument("input", nargs="?", default="-", help="Input file or '-' for stdin.")
    parser.add_argument("--from-format", choices=["csv", "json"], help="Input format (default: infer from file or CSV for stdin).")
    parser.add_argument("--to", choices=["json", "jsonl", "csv"], help="Output format (default: same as input — csv in → csv out, json in → json out).")
    parser.add_argument("--delimiter", default=",", help="CSV delimiter (for CSV in or out).")
    parser.add_argument("--no-header", action="store_true", help="CSV has no header row.")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines; next line is header.")
    parser.add_argument("--comment-char", help="Skip CSV lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")
    parser.add_argument("--compact", action="store_true", help="Compact JSON output.")
    args = parser.parse_args()

    delim = parse_delimiter(args.delimiter)

    # Input: CSV or JSON
    input_is_json = args.from_format == "json" or (
        args.input != "-" and args.input.endswith(".json")
    )
    if input_is_json:
        text = read_text(args.input, args.encoding)
        data = json.loads(text)
        if isinstance(data, list):
            rows = data
            columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
        elif isinstance(data, dict):
            rows = [data]
            columns = list(data.keys())
        else:
            rows = []
            columns = []
        if rows and isinstance(rows[0], dict) and not columns:
            columns = list(rows[0].keys())
    else:
        columns, rows = load_csv(
            args.input,
            delimiter=delim,
            has_header=not args.no_header,
            comment_char=args.comment_char,
            encoding=args.encoding,
            skip_lines=args.skip_lines,
        )[:2]

    # Default --to to match input format for pipeline-friendly behavior
    to_format = args.to
    if to_format is None:
        to_format = "json" if input_is_json else "csv"

    if to_format == "json":
        write_json(rows, compact=args.compact)
    elif to_format == "jsonl":
        for row in rows:
            sys.stdout.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        write_csv(columns, rows, delim, sys.stdout)


if __name__ == "__main__":
    main()
