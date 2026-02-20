#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Quick structural probe of a CSV file: delimiter, columns, row count (data rows only), sample."""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

from common import (
    DEFAULT_ENCODING,
    _lines_filter_comment,
    parse_delimiter,
    read_text,
    write_json,
)


def detect_delimiter(lines: list[str], comment_char: str | None) -> str:
    """Try comma, tab, semicolon; pick the one that yields most consistent column count in first 20 lines."""
    candidates = [",", "\t", ";"]
    filtered = _lines_filter_comment(lines, comment_char)
    if not filtered:
        return ","

    best_delim: str = ","
    best_score = -1

    for delim in candidates:
        counts: list[int] = []
        for line in filtered[:30]:
            if not line.strip():
                continue  # skip leading/blank lines
            parsed = list(csv.reader(io.StringIO(line), delimiter=delim))
            if not parsed:
                continue
            row = parsed[0]
            counts.append(len(row))
        if not counts:
            continue
        # Prefer delimiter that gives same count across lines (mode).
        from collections import Counter
        mode_count = Counter(counts).most_common(1)[0]
        score = mode_count[1] * (mode_count[0] if mode_count[0] > 1 else 0)
        if score > best_score:
            best_score = score
            best_delim = delim

    return best_delim


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe CSV structure: delimiter, columns, row count, sample.")
    parser.add_argument("input", nargs="?", default="-", help="Input CSV file or '-' for stdin.")
    parser.add_argument("--delimiter", help="Delimiter (e.g. ',' or '\\t'). Auto-detect if omitted.")
    parser.add_argument("--no-header", action="store_true", help="First row is data, not header.")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines that start with this character (e.g. '#').")
    parser.add_argument("--encoding", default=DEFAULT_ENCODING, help="File encoding.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    text = read_text(args.input, args.encoding)
    lines = text.splitlines()
    size_bytes = len(text.encode(args.encoding))

    comment_char = args.comment_char
    delimiter = parse_delimiter(args.delimiter) if args.delimiter else detect_delimiter(lines, comment_char)

    from common import load_csv

    columns, rows, header_row = load_csv(
        args.input,
        delimiter=delimiter,
        has_header=not args.no_header,
        comment_char=comment_char,
        encoding=args.encoding,
        text_override=text,
        skip_lines=args.skip_lines,
    )

    sample = rows[0] if rows else {}
    result = {
        "valid": True,
        "delimiter": delimiter,
        "has_header": not args.no_header,
        "header_row": header_row,
        "record_count": len(rows),
        "columns": columns,
        "encoding": args.encoding,
        "size_bytes": size_bytes,
        "sample_row": sample,
    }
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
