#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Infer column types and optional presence/counts from CSV."""

from __future__ import annotations

import argparse
from collections import Counter

from common import load_csv, parse_delimiter, sniff_type, write_json


def add_dialect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", nargs="?", default="-", help="Input CSV file or '-' for stdin.")
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row is data; columns named col0, col1, ...")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer schema (column types) for a CSV.")
    add_dialect_args(parser)
    parser.add_argument("--counts", action="store_true", help="Include presence counts per column.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    columns, rows = load_csv(
        args.input,
        delimiter=parse_delimiter(args.delimiter),
        has_header=not args.no_header,
        comment_char=args.comment_char,
        encoding=args.encoding,
        skip_lines=args.skip_lines,
    )[:2]

    fields: dict = {}
    for col in columns:
        types_counter: Counter = Counter()
        presence = 0
        for row in rows:
            val = row.get(col, "")
            types_counter[sniff_type(val)] += 1
            if (val or "").strip():
                presence += 1
        entry = {"types": sorted(types_counter.keys())}
        if args.counts:
            entry["presence"] = f"{presence}/{len(rows)}"
            entry["type_counts"] = dict(types_counter)
        fields[col] = entry

    result = {"columns": columns, "record_count": len(rows), "fields": fields}
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
