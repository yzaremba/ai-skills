#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Transform JSON to CSV/JSONL and CSV to JSON."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from typing import Any

from common import flatten_json, load_json, resolve_array, write_json


def parse_columns(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def json_to_csv(data: Any, columns: list[str]) -> str:
    rows = data if isinstance(data, list) else [data]
    flattened = [flatten_json(row) if isinstance(row, (dict, list)) else {"value": row} for row in rows]
    if not columns:
        column_set: set[str] = set()
        for row in flattened:
            column_set.update(row.keys())
        columns = sorted(column_set)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in flattened:
        writer.writerow({col: row.get(col) for col in columns})
    return output.getvalue()


def json_to_jsonl(data: Any) -> str:
    rows = data if isinstance(data, list) else [data]
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"


def csv_to_json(path: str | None) -> Any:
    if not path or path == "-":
        text = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            text = handle.read()
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transform JSON<->CSV/JSONL.")
    parser.add_argument("input", nargs="?", default="-", help="Input file path or '-' for stdin.")
    parser.add_argument("--to", choices=["csv", "jsonl"], help="Convert JSON input to the target format.")
    parser.add_argument("--from-format", choices=["csv"], help="Convert non-JSON input into JSON.")
    parser.add_argument("--array-path", help="Path to array when converting JSON input.")
    parser.add_argument("--columns", help="Comma-separated columns for CSV output.")
    args = parser.parse_args()

    columns = parse_columns(args.columns)

    if args.from_format == "csv":
        result = csv_to_json(args.input)
        write_json(result)
        return

    data = load_json(args.input)
    if args.array_path:
        extracted = resolve_array(data, args.array_path)
        data = extracted if extracted else data

    if args.to == "csv":
        print(json_to_csv(data, columns), end="")
    elif args.to == "jsonl":
        print(json_to_jsonl(data), end="")
    else:
        # Default passthrough when no transform is requested.
        write_json(data)


if __name__ == "__main__":
    main()
