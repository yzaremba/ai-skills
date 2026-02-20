#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Validate CSV: consistent column count, encoding; report data vs non-data (footer) row counts."""

from __future__ import annotations

import argparse
import csv
import io

from common import _lines_filter_comment, parse_delimiter, read_text, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate CSV structure and report issues.")
    parser.add_argument("input", nargs="?", default="-", help="Input CSV file or '-' for stdin.")
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row is data.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")
    parser.add_argument("--strict", action="store_true", help="Fail on inconsistent column counts.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    text = read_text(args.input, args.encoding)
    lines = text.splitlines()
    lines = _lines_filter_comment(lines, args.comment_char)

    delim = parse_delimiter(args.delimiter)
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
    rows = list(reader)

    if not rows:
        write_json({"valid": True, "record_count": 0, "message": "empty file"}, compact=args.compact)
        return

    expected_len = len(rows[0])
    if args.no_header:
        data_rows = [r for r in rows if len(r) == expected_len]
        skipped = sum(1 for r in rows if len(r) != expected_len)
    else:
        data_rows = [r for r in rows[1:] if len(r) == expected_len]
        skipped = sum(1 for r in rows[1:] if len(r) != expected_len)

    valid = skipped == 0 or not args.strict
    result = {
        "valid": valid,
        "record_count": len(data_rows),
        "skipped_rows": skipped,
        "expected_columns": expected_len,
        "size_bytes": len(text.encode(args.encoding)),
    }
    if not valid and args.strict:
        result["error"] = f"Inconsistent column count: {skipped} row(s) skipped (footer/comment lines)."
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
