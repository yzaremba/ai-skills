#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Sort JSON array entries by one or more fields."""

from __future__ import annotations

import argparse
from typing import Any

from common import first_value, load_json, resolve_array, write_json


def parse_fields(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def normalize(value: Any, numeric: bool) -> Any:
    if value is None:
        return float("-inf") if numeric else ""
    if numeric:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("-inf")
    return str(value)


def key_for_record(record: Any, fields: list[str], numeric: bool) -> tuple[Any, ...]:
    return tuple(normalize(first_value(record, field), numeric) for field in fields)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sort JSON arrays by selected fields.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--by", required=True, help="Comma-separated sort fields.")
    parser.add_argument("--array-path", help="Path to the array to sort.")
    parser.add_argument("--desc", action="store_true", help="Sort descending.")
    parser.add_argument("--numeric", action="store_true", help="Use numeric sorting semantics.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    fields = parse_fields(args.by)
    data = load_json(args.input)
    rows = resolve_array(data, args.array_path)
    if not rows:
        rows = data if isinstance(data, list) else [data]

    sorted_rows = sorted(rows, key=lambda row: key_for_record(row, fields, args.numeric), reverse=args.desc)
    write_json(sorted_rows, compact=args.compact)


if __name__ == "__main__":
    main()
