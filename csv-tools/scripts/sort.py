#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Sort CSV rows by one or more columns."""

from __future__ import annotations

import argparse
import sys

from common import load_csv, parse_delimiter, write_csv, write_json


def add_dialect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", nargs="?", default="-", help="Input CSV file or '-' for stdin.")
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row is data.")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")


def parse_fields(raw: str) -> list[str]:
    return [f.strip() for f in raw.split(",") if f.strip()]


def key_for_row(row: dict[str, str], fields: list[str], numeric: bool) -> tuple:
    def norm(field: str):
        v = (row.get(field, "") or "").strip()
        if numeric and v:
            try:
                return float(v)
            except ValueError:
                pass
        return v or (float("-inf") if numeric else "")

    return tuple(norm(f) for f in fields)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sort CSV by columns.")
    add_dialect_args(parser)
    parser.add_argument("--by", required=True, help="Comma-separated columns to sort by.")
    parser.add_argument("--desc", action="store_true", help="Sort descending.")
    parser.add_argument("--numeric", action="store_true", help="Compare as numbers.")
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

    by_fields = parse_fields(args.by)
    by_fields = [f for f in by_fields if f in columns]
    if not by_fields:
        by_fields = columns[:1]

    sorted_rows = sorted(
        rows,
        key=lambda r: key_for_row(r, by_fields, args.numeric),
        reverse=args.desc,
    )

    if args.format == "csv":
        write_csv(columns, sorted_rows, parse_delimiter(args.delimiter), sys.stdout)
    else:
        write_json(sorted_rows, compact=args.compact)


if __name__ == "__main__":
    main()
