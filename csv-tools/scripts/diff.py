#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Compare two CSV files: report added, removed, and changed rows (by key column or row order)."""

from __future__ import annotations

import argparse
from typing import Any

from common import load_csv, parse_delimiter, write_json


def add_dialect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row is data.")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines per file; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")


def row_key(row: dict[str, str], key_columns: list[str]) -> tuple:
    return tuple((row.get(c, "") or "").strip() for c in key_columns)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diff two CSV files.")
    parser.add_argument("left", help="Left CSV file.")
    parser.add_argument("right", help="Right CSV file.")
    add_dialect_args(parser)
    parser.add_argument("--key", help="Comma-separated key columns for row identity (default: row order).")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    dialect = {
        "delimiter": parse_delimiter(args.delimiter),
        "has_header": not args.no_header,
        "comment_char": args.comment_char,
        "encoding": args.encoding,
        "skip_lines": args.skip_lines,
    }

    _, left_rows = load_csv(args.left, **dialect)[:2]
    _, right_rows = load_csv(args.right, **dialect)[:2]

    key_cols: list[str] | None = [c.strip() for c in args.key.split(",")] if args.key else None

    changes: list[dict[str, Any]] = []

    if key_cols:
        left_by_key = {row_key(r, key_cols): r for r in left_rows}
        right_by_key = {row_key(r, key_cols): r for r in right_rows}
        left_keys = set(left_by_key)
        right_keys = set(right_by_key)
        for k in left_keys - right_keys:
            changes.append({"kind": "removed", "key": list(k), "left": left_by_key[k]})
        for k in right_keys - left_keys:
            changes.append({"kind": "added", "key": list(k), "right": right_by_key[k]})
        for k in left_keys & right_keys:
            lr, rr = left_by_key[k], right_by_key[k]
            if lr != rr:
                changes.append({"kind": "changed", "key": list(k), "left": lr, "right": rr})
    else:
        # Row-order diff
        for i, (lr, rr) in enumerate(zip(left_rows, right_rows)):
            if lr != rr:
                changes.append({"kind": "changed", "row_index": i, "left": lr, "right": rr})
        if len(left_rows) > len(right_rows):
            for i in range(len(right_rows), len(left_rows)):
                changes.append({"kind": "removed", "row_index": i, "left": left_rows[i]})
        elif len(right_rows) > len(left_rows):
            for i in range(len(left_rows), len(right_rows)):
                changes.append({"kind": "added", "row_index": i, "right": right_rows[i]})

    if args.format == "text":
        if not changes:
            print("No differences.")
        else:
            for c in changes:
                k = c["kind"]
                if k == "removed":
                    print(f"- removed: {c.get('key', c.get('row_index'))} {c.get('left', {})}")
                elif k == "added":
                    print(f"+ added: {c.get('key', c.get('row_index'))} {c.get('right', {})}")
                else:
                    print(f"~ changed: {c.get('key', c.get('row_index'))}")
        return

    write_json({"change_count": len(changes), "changes": changes}, compact=args.compact)


if __name__ == "__main__":
    main()
