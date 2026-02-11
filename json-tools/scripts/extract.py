#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Extract rows and/or fields from JSON."""

from __future__ import annotations

import argparse
from typing import Any

from common import extract_values, first_value, load_json, resolve_array, write_json


def parse_fields(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [field.strip() for field in raw.split(",") if field.strip()]


def select_rows(data: Any, array_path: str | None, first: int | None, last: int | None) -> list[Any]:
    rows = resolve_array(data, array_path)
    if first is not None:
        rows = rows[: max(first, 0)]
    if last is not None:
        rows = rows[-max(last, 0) :]
    return rows


def extract_fields(rows: list[Any], fields: list[str], include_missing: bool) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            output.append({"_value": row})
            continue
        item: dict[str, Any] = {}
        for field in fields:
            values = extract_values(row, field)
            if values:
                item[field] = values if len(values) > 1 else values[0]
            elif include_missing:
                item[field] = None
        output.append(item)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract rows and fields from JSON.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--array-path", help="Path to the array to extract rows from.")
    parser.add_argument("--fields", help="Comma-separated paths to extract from each row.")
    parser.add_argument("--first", type=int, help="Keep first N rows.")
    parser.add_argument("--last", type=int, help="Keep last N rows.")
    parser.add_argument("--include-missing", action="store_true", help="Include missing fields as null.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    data = load_json(args.input)
    fields = parse_fields(args.fields)

    # If fields are requested but no array is selected, treat entire doc as one row.
    rows = select_rows(data, args.array_path, args.first, args.last)
    if not rows and not isinstance(data, list):
        rows = [data]
    elif isinstance(data, list) and args.array_path is None:
        rows = select_rows(data, None, args.first, args.last)

    if fields:
        result: Any = extract_fields(rows, fields, args.include_missing)
    else:
        result = rows
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
