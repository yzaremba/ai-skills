#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Merge or concatenate JSON files."""

from __future__ import annotations

import argparse
import copy
from typing import Any

from common import first_value, load_json, write_json


def shallow_merge(objs: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for obj in objs:
        out.update(obj)
    return out


def deep_merge_values(left: Any, right: Any) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        merged = dict(left)
        for key, value in right.items():
            if key in merged:
                merged[key] = deep_merge_values(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged
    if isinstance(left, list) and isinstance(right, list):
        return left + right
    return copy.deepcopy(right)


def merge_arrays(arrays: list[list[Any]], unique_by: str | None) -> list[Any]:
    combined: list[Any] = []
    for arr in arrays:
        combined.extend(arr)
    if not unique_by:
        return combined
    seen: set[str] = set()
    deduped: list[Any] = []
    for item in combined:
        key = first_value(item, unique_by)
        token = repr(key)
        if token in seen:
            continue
        seen.add(token)
        deduped.append(item)
    return deduped


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge multiple JSON files.")
    parser.add_argument("inputs", nargs="+", help="Input JSON files in merge order.")
    parser.add_argument(
        "--mode",
        choices=["concat", "shallow", "deep"],
        default="concat",
        help="concat expects arrays; shallow/deep expect objects.",
    )
    parser.add_argument("--unique-by", help="Field path used to deduplicate in concat mode.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    docs = [load_json(path) for path in args.inputs]
    if args.mode == "concat":
        arrays = [doc for doc in docs if isinstance(doc, list)]
        result = merge_arrays(arrays, args.unique_by)
    elif args.mode == "shallow":
        objects = [doc for doc in docs if isinstance(doc, dict)]
        result = shallow_merge(objects)
    else:
        objects = [doc for doc in docs if isinstance(doc, dict)]
        result: dict[str, Any] = {}
        for obj in objects:
            result = deep_merge_values(result, obj)
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
