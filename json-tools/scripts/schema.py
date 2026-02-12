#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Infer a practical schema summary from JSON."""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from common import load_json, resolve_array, type_name, write_json


def infer_schema(value: Any, depth: int, include_counts: bool) -> dict[str, Any]:
    if depth < 0:
        return {"type": type_name(value)}

    if isinstance(value, dict):
        fields: dict[str, Any] = {}
        for key, inner in value.items():
            fields[key] = infer_schema(inner, depth - 1, include_counts)
        out: dict[str, Any] = {"type": "object", "fields": fields}
        if include_counts:
            out["field_count"] = len(value)
        return out

    if isinstance(value, list):
        item_types = Counter(type_name(item) for item in value)
        out = {
            "type": "array",
            "size": len(value),
            "item_types": sorted(item_types.keys()),
        }
        if value and depth > 0:
            if all(isinstance(item, dict) for item in value):
                # Merge object keys for heterogeneous records.
                key_counts = Counter()
                for item in value:
                    key_counts.update(item.keys())
                merged_fields: dict[str, Any] = {}
                for key in sorted(key_counts):
                    samples = [item.get(key) for item in value if key in item]
                    sample_value = samples[0] if samples else None
                    merged_fields[key] = infer_schema(sample_value, depth - 1, include_counts)
                    if include_counts:
                        merged_fields[key]["presence"] = f"{key_counts[key]}/{len(value)}"
                out["item_schema"] = {"type": "object", "fields": merged_fields}
            else:
                out["item_schema"] = infer_schema(value[0], depth - 1, include_counts)
        return out

    return {"type": type_name(value)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Show inferred schema for a JSON file.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--array-path", help="Path to an array (or object-of-objects) to summarize.")
    parser.add_argument("--depth", type=int, default=6, help="Maximum nesting depth to inspect.")
    parser.add_argument("--counts", action="store_true", help="Include field presence/count metadata.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    data = load_json(args.input)
    if args.array_path:
        resolved = resolve_array(data, args.array_path)
        if resolved:
            data = resolved
    schema = infer_schema(data, args.depth, args.counts)
    write_json(schema, compact=args.compact)


if __name__ == "__main__":
    main()
