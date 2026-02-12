#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Group-by / cross-tabulation for JSON arrays of records."""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any

from common import first_value, load_json, resolve_array, write_json


def parse_fields(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_agg(spec: str) -> tuple[str, str]:
    """Parse an aggregation spec like 'age:mean' or 'count'."""
    if spec.strip().lower() == "count":
        return ("", "count")
    if ":" not in spec:
        raise ValueError(f"Invalid --agg spec '{spec}'. Use field:func or 'count'.")
    field, func = spec.rsplit(":", 1)
    func = func.strip().lower()
    allowed = {"count", "sum", "min", "max", "mean", "list", "unique"}
    if func not in allowed:
        raise ValueError(f"Unknown aggregation '{func}'. Use one of: {sorted(allowed)}")
    return (field.strip(), func)


def group_key(record: Any, by_fields: list[str]) -> tuple[Any, ...]:
    """Build a hashable group key from the record."""
    parts: list[Any] = []
    for field in by_fields:
        value = first_value(record, field)
        # Make lists/dicts hashable for grouping.
        if isinstance(value, (dict, list)):
            import json
            value = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        parts.append(value)
    return tuple(parts)


def compute_agg(values: list[Any], func: str) -> Any:
    """Compute a single aggregation over a list of values."""
    if func == "count":
        return len(values)
    if func == "list":
        return values
    if func == "unique":
        seen: list[Any] = []
        seen_set: set[str] = set()
        for v in values:
            token = repr(v)
            if token not in seen_set:
                seen_set.add(token)
                seen.append(v)
        return seen

    # Numeric aggregations — preserve int where possible.
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
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
    parser = argparse.ArgumentParser(description="Group-by / cross-tabulation for JSON records.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--array-path", help="Path to the array to group.")
    parser.add_argument("--by", required=True, help="Comma-separated fields to group by.")
    parser.add_argument(
        "--agg",
        action="append",
        default=[],
        help="Aggregation spec: 'count', or 'field:func' where func is count|sum|min|max|mean|list|unique. Repeatable.",
    )
    parser.add_argument("--sort", choices=["count", "key"], default="count", help="Sort groups by count (desc) or key (asc).")
    parser.add_argument("--top", type=int, help="Limit output to top N groups.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    by_fields = parse_fields(args.by)
    agg_specs = [parse_agg(spec) for spec in args.agg] if args.agg else [("", "count")]

    data = load_json(args.input)
    records = resolve_array(data, args.array_path)
    if not records:
        records = data if isinstance(data, list) else [data]

    # Group records.
    groups: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
    for record in records:
        key = group_key(record, by_fields)
        groups[key].append(record)

    # Build output rows.
    rows: list[dict[str, Any]] = []
    for key_tuple, group_records in groups.items():
        row: dict[str, Any] = {}
        for field, value in zip(by_fields, key_tuple):
            row[field] = value
        row["count"] = len(group_records)
        for agg_field, agg_func in agg_specs:
            if agg_field == "" and agg_func == "count":
                continue  # Already included as 'count'.
            values: list[Any] = []
            for record in group_records:
                v = first_value(record, agg_field)
                if v is not None:
                    values.append(v)
            label = f"{agg_field}:{agg_func}"
            row[label] = compute_agg(values, agg_func)
        rows.append(row)

    # Sort.
    if args.sort == "count":
        rows.sort(key=lambda r: r["count"], reverse=True)
    else:
        rows.sort(key=lambda r: tuple(r.get(f) or "" for f in by_fields))

    # Limit.
    if args.top is not None:
        rows = rows[: max(args.top, 0)]

    result = {
        "total_records": len(records),
        "total_groups": len(groups),
        "groups": rows,
    }
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
