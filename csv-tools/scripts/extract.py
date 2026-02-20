#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Extract selected columns and/or first/last N rows from CSV."""

from __future__ import annotations

import argparse
import sys

from common import load_csv, parse_delimiter, write_csv, write_json


def add_dialect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", nargs="?", default="-", help="Input CSV file or '-' for stdin.")
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row is data; columns named col0, col1, ...")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")


def parse_fields(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [f.strip() for f in raw.split(",") if f.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract columns and/or first/last N rows from CSV.")
    add_dialect_args(parser)
    parser.add_argument("--fields", help="Comma-separated columns to output (default: all).")
    parser.add_argument("--first", type=int, help="Output only first N data rows.")
    parser.add_argument("--last", type=int, help="Output only last N data rows.")
    parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format (default: csv).")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON when --format json.")
    args = parser.parse_args()

    columns, rows = load_csv(
        args.input,
        delimiter=parse_delimiter(args.delimiter),
        has_header=not args.no_header,
        comment_char=args.comment_char,
        encoding=args.encoding,
        skip_lines=args.skip_lines,
    )[:2]

    out_columns = parse_fields(args.fields) if args.fields else columns
    out_columns = [c for c in out_columns if c in columns]
    if not out_columns:
        out_columns = columns

    if args.first is not None:
        rows = rows[: max(0, args.first)]
    if args.last is not None:
        rows = rows[-max(0, args.last) :]

    out_rows = [dict((k, r.get(k, "")) for k in out_columns) for r in rows]
    if args.format == "csv":
        write_csv(out_columns, out_rows, parse_delimiter(args.delimiter), sys.stdout)
    else:
        write_json(out_rows, compact=args.compact)


if __name__ == "__main__":
    main()
