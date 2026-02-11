#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Compute structural differences between two JSON documents."""

from __future__ import annotations

import argparse
from typing import Any

from common import load_json, type_name, write_json


def normalize_for_set(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, normalize_for_set(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(normalize_for_set(v) for v in value)
    return value


def diff_values(left: Any, right: Any, path: str, changes: list[dict[str, Any]], ignore_order: bool) -> None:
    if type(left) is not type(right):
        changes.append(
            {
                "path": path or "$",
                "kind": "type_change",
                "left_type": type_name(left),
                "right_type": type_name(right),
                "left": left,
                "right": right,
            }
        )
        return

    if isinstance(left, dict):
        left_keys = set(left.keys())
        right_keys = set(right.keys())
        for key in sorted(left_keys - right_keys):
            changes.append({"path": f"{path}.{key}" if path else key, "kind": "removed", "left": left[key]})
        for key in sorted(right_keys - left_keys):
            changes.append({"path": f"{path}.{key}" if path else key, "kind": "added", "right": right[key]})
        for key in sorted(left_keys & right_keys):
            child_path = f"{path}.{key}" if path else key
            diff_values(left[key], right[key], child_path, changes, ignore_order)
        return

    if isinstance(left, list):
        if ignore_order:
            left_set = {normalize_for_set(item) for item in left}
            right_set = {normalize_for_set(item) for item in right}
            if left_set != right_set:
                changes.append({"path": path or "$", "kind": "array_set_change", "left": left, "right": right})
            return
        min_len = min(len(left), len(right))
        for idx in range(min_len):
            diff_values(left[idx], right[idx], f"{path}[{idx}]" if path else f"[{idx}]", changes, ignore_order)
        if len(left) > len(right):
            for idx in range(min_len, len(left)):
                changes.append({"path": f"{path}[{idx}]" if path else f"[{idx}]", "kind": "removed", "left": left[idx]})
        elif len(right) > len(left):
            for idx in range(min_len, len(right)):
                changes.append({"path": f"{path}[{idx}]" if path else f"[{idx}]", "kind": "added", "right": right[idx]})
        return

    if left != right:
        changes.append({"path": path or "$", "kind": "changed", "left": left, "right": right})


def to_text(changes: list[dict[str, Any]]) -> str:
    if not changes:
        return "No differences.\n"
    lines: list[str] = []
    for change in changes:
        kind = change["kind"]
        path = change["path"]
        if kind == "added":
            lines.append(f"+ {path}: {change.get('right')!r}")
        elif kind == "removed":
            lines.append(f"- {path}: {change.get('left')!r}")
        elif kind == "type_change":
            lines.append(
                f"~ {path}: type {change['left_type']} -> {change['right_type']} "
                f"(left={change.get('left')!r}, right={change.get('right')!r})"
            )
        else:
            lines.append(f"~ {path}: {change.get('left')!r} -> {change.get('right')!r}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Diff two JSON files.")
    parser.add_argument("left", help="Left JSON file.")
    parser.add_argument("right", help="Right JSON file.")
    parser.add_argument("--ignore-order", action="store_true", help="Treat arrays as unordered sets.")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    left = load_json(args.left)
    right = load_json(args.right)
    changes: list[dict[str, Any]] = []
    diff_values(left, right, "", changes, args.ignore_order)

    if args.format == "text":
        print(to_text(changes), end="")
    else:
        write_json({"change_count": len(changes), "changes": changes}, compact=args.compact)


if __name__ == "__main__":
    main()
