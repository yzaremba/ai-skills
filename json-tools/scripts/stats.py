#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Generate summary statistics for JSON records."""

from __future__ import annotations

import argparse
import math
from collections import Counter, defaultdict
from typing import Any

from common import extract_values, frequency, load_json, resolve_array, type_name, unique_types, write_json


def parse_fields(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def numeric_summary(values: list[Any]) -> dict[str, Any]:
    nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not nums:
        return {}
    return {
        "count": len(nums),
        "min": min(nums),
        "max": max(nums),
        "mean": sum(nums) / len(nums),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute practical JSON stats for arrays of records.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--array-path", help="Path to the array to analyze.")
    parser.add_argument("--fields", help="Comma-separated field paths to analyze.")
    parser.add_argument("--top", type=int, default=10, help="Top N frequent values to include.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    data = load_json(args.input)
    records = resolve_array(data, args.array_path)
    if not records:
        records = data if isinstance(data, list) else [data]

    selected_fields = parse_fields(args.fields)
    if not selected_fields:
        field_candidates: set[str] = set()
        for record in records:
            if isinstance(record, dict):
                field_candidates.update(record.keys())
        selected_fields = sorted(field_candidates)

    field_stats: dict[str, Any] = {}
    for field in selected_fields:
        values: list[Any] = []
        presence = 0
        for record in records:
            found = extract_values(record, field)
            if found:
                presence += 1
                values.extend(found)
        freq = frequency(values)
        has_complex = any(isinstance(v, (dict, list)) for v in values)
        entry: dict[str, Any] = {
            "presence": f"{presence}/{len(records)}",
            "types": unique_types(values),
            "unique_values": len(freq),
        }
        if not has_complex:
            entry["top_values"] = [
                {"value": key, "count": count}
                for key, count in freq.most_common(max(args.top, 0))
            ]
        field_stats[field] = entry
        numeric = numeric_summary(values)
        if numeric:
            field_stats[field]["numeric"] = numeric

    result = {
        "record_count": len(records),
        "field_count": len(selected_fields),
        "fields": field_stats,
    }
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
