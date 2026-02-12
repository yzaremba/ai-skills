#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Quick structural probe of a JSON file for the agent to decide optimal parameters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from common import type_name, write_json


def read_text(path: str | None) -> str:
    if not path or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def collect_record_fields(records: list[Any], sample: int) -> list[str]:
    """Collect field names from up to `sample` records, in frequency order."""
    from collections import Counter

    counts: Counter[str] = Counter()
    inspected = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        counts.update(record.keys())
        inspected += 1
        if inspected >= sample:
            break
    return [key for key, _ in counts.most_common()]


def find_best_array_child(data: dict[str, Any]) -> tuple[str | None, list[Any]]:
    """Find the largest array child of an object, which is the likely record set."""
    best_key: str | None = None
    best_arr: list[Any] = []
    for key, value in data.items():
        if isinstance(value, list) and len(value) > len(best_arr):
            best_key = key
            best_arr = value
    return best_key, best_arr


def detect_layout(data: Any) -> dict[str, Any]:
    """Detect the JSON layout and recommend --array-path."""

    if isinstance(data, list):
        return {
            "layout": "array",
            "record_count": len(data),
            "recommended_array_path": None,
            "records": data,
        }

    if isinstance(data, dict):
        # Check for object-of-objects: all (or nearly all) values are dicts.
        values = list(data.values())
        dict_count = sum(1 for v in values if isinstance(v, dict))
        if len(values) > 0 and dict_count / len(values) >= 0.8:
            return {
                "layout": "object-of-objects",
                "record_count": len(values),
                "recommended_array_path": ".",
                "records": values,
                "sample_keys": list(data.keys())[:10],
            }

        # Check for nested-array: object with a prominent array child.
        best_key, best_arr = find_best_array_child(data)
        if best_key and len(best_arr) > 0:
            return {
                "layout": "nested-array",
                "record_count": len(best_arr),
                "recommended_array_path": best_key,
                "records": best_arr,
                "top_level_fields": sorted(data.keys()),
            }

        # Plain object (configuration-style, single record).
        return {
            "layout": "object",
            "record_count": 1,
            "recommended_array_path": None,
            "records": [data],
            "top_level_fields": sorted(data.keys()),
        }

    # Scalar.
    return {
        "layout": "scalar",
        "record_count": 0,
        "recommended_array_path": None,
        "records": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick structural probe of a JSON file.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--sample", type=int, default=20, help="Number of records to sample for field discovery.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    text = read_text(args.input)
    size_bytes = len(text.encode("utf-8"))

    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        write_json({"valid": False, "error": err.msg, "size_bytes": size_bytes}, compact=args.compact)
        return

    info = detect_layout(data)
    records = info.pop("records")

    result: dict[str, Any] = {
        "valid": True,
        "top_level_type": type_name(data),
        "layout": info["layout"],
        "record_count": info["record_count"],
        "recommended_array_path": info["recommended_array_path"],
        "size_bytes": size_bytes,
    }

    if "sample_keys" in info:
        result["sample_keys"] = info["sample_keys"]
    if "top_level_fields" in info:
        result["top_level_fields"] = info["top_level_fields"]

    result["record_fields"] = collect_record_fields(records, args.sample)

    # Type summary for each field from sampled records.
    if result["record_fields"]:
        field_types: dict[str, set[str]] = {}
        inspected = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            for field in result["record_fields"]:
                if field in record:
                    field_types.setdefault(field, set()).add(type_name(record[field]))
            inspected += 1
            if inspected >= args.sample:
                break
        result["field_types"] = {field: sorted(types) for field, types in field_types.items()}

    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
