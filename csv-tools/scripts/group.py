#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Group CSV rows by column(s) with optional aggregations."""

from __future__ import annotations

import argparse
from collections import defaultdict

from common import load_csv, parse_delimiter, write_json


def add_dialect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", nargs="?", default="-", help="Input CSV file or '-' for stdin.")
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row is data.")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")


def parse_fields(raw: str) -> list[str]:
    return [f.strip() for f in raw.split(",") if f.strip()]


def parse_agg(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ValueError(f"Invalid --agg '{spec}'. Use field:func.")
    field, func = spec.rsplit(":", 1)
    func = func.strip().lower()
    if func not in {"count", "sum", "min", "max", "mean", "list", "unique"}:
        raise ValueError(f"Unknown agg: {func}")
    return (field.strip(), func)


def compute_agg(values: list[str], func: str):
    if func == "count":
        return len(values)
    if func == "list":
        return values
    if func == "unique":
        seen: list[str] = []
        seen_set: set[str] = set()
        for v in values:
            if v not in seen_set:
                seen_set.add(v)
                seen.append(v)
        return seen
    nums = []
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
    if func == "sum":
        return sum(nums)
    if func == "min":
        return min(nums)
    if func == "max":
        return max(nums)
    if func == "mean":
        return sum(nums) / len(nums)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Group CSV by columns with optional aggregations.")
    add_dialect_args(parser)
    parser.add_argument("--by", required=True, help="Comma-separated columns to group by.")
    parser.add_argument("--agg", action="append", default=[], help="field:func (sum, mean, min, max, list, unique).")
    parser.add_argument("--sort", choices=["count", "key"], default="count", help="Sort groups by count (desc) or key (asc).")
    parser.add_argument("--top", type=int, help="Limit to top N groups.")
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

    by_fields = parse_fields(args.by)
    by_fields = [f for f in by_fields if f in columns]
    if not by_fields:
        by_fields = columns[:1]

    agg_specs = [parse_agg(s) for s in args.agg]

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = tuple((row.get(f, "") or "").strip() for f in by_fields)
        groups[key].append(row)

    out_rows: list[dict] = []
    for key_tuple, group_rows in groups.items():
        row_dict = dict(zip(by_fields, key_tuple))
        row_dict["count"] = len(group_rows)
        for agg_field, agg_func in agg_specs:
            vals = [(r.get(agg_field, "") or "").strip() for r in group_rows]
            label = f"{agg_field}:{agg_func}"
            row_dict[label] = compute_agg(vals, agg_func)
        out_rows.append(row_dict)

    if args.sort == "count":
        out_rows.sort(key=lambda r: r["count"], reverse=True)
    else:
        out_rows.sort(key=lambda r: tuple(r.get(f, "") for f in by_fields))

    if args.top is not None:
        out_rows = out_rows[: max(0, args.top)]

    result = {"total_records": len(rows), "total_groups": len(groups), "groups": out_rows}
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
