#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Reverse the order of CSV data rows."""

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverse the order of CSV data rows.")
    add_dialect_args(parser)
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

    reversed_rows = list(reversed(rows))

    if args.format == "csv":
        write_csv(columns, reversed_rows, parse_delimiter(args.delimiter), sys.stdout)
    else:
        write_json(reversed_rows, compact=args.compact)


if __name__ == "__main__":
    main()
