#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Per-column statistics: presence, unique count, top values, numeric min/max/mean."""

from __future__ import annotations

import argparse
from collections import Counter

from common import load_csv, parse_delimiter, sniff_type, write_json


def add_dialect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", nargs="?", default="-", help="Input CSV file or '-' for stdin.")
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row is data.")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")


def parse_fields(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [f.strip() for f in raw.split(",") if f.strip()]


def numeric_summary(values: list[str]) -> dict | None:
    nums: list[float] = []
    for v in values:
        v = (v or "").strip()
        if not v:
            continue
        try:
            nums.append(float(v))
        except ValueError:
            pass
    if not nums:
        return None
    return {
        "count": len(nums),
        "min": min(nums),
        "max": max(nums),
        "mean": sum(nums) / len(nums),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute per-column statistics for CSV.")
    add_dialect_args(parser)
    parser.add_argument("--fields", help="Comma-separated columns to analyze (default: all).")
    parser.add_argument("--top", type=int, default=10, help="Top N frequent values per column.")
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

    selected = parse_fields(args.fields) if args.fields else columns
    selected = [c for c in selected if c in columns]
    if not selected:
        selected = columns

    field_stats: dict = {}
    for col in selected:
        values = [row.get(col, "") or "" for row in rows]
        presence = sum(1 for v in values if (v or "").strip())
        freq = Counter(values)
        entry = {
            "presence": f"{presence}/{len(rows)}",
            "unique_values": len(freq),
            "top_values": [{"value": k, "count": c} for k, c in freq.most_common(max(0, args.top))],
        }
        num = numeric_summary(values)
        if num:
            entry["numeric"] = num
        field_stats[col] = entry

    result = {"record_count": len(rows), "field_count": len(selected), "fields": field_stats}
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
