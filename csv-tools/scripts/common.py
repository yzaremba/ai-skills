#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for csv-tools scripts: read/write CSV, skip footers and comment lines."""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path
from typing import Any

# Default encoding for CSV files.
DEFAULT_ENCODING = "utf-8"


def read_text(path: str | None, encoding: str = DEFAULT_ENCODING) -> str:
    """Read file or stdin as text."""
    if not path or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding=encoding)


def _lines_filter_comment(lines: list[str], comment_char: str | None) -> list[str]:
    """Drop lines that start with comment_char (after strip)."""
    if not comment_char:
        return lines
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if s and s.startswith(comment_char):
            continue
        out.append(line)
    return out


def _is_blank_row(row: list[str]) -> bool:
    """True if every cell in the row is empty or whitespace."""
    return all((c or "").strip() == "" for c in row)


def _find_header_row(rows_list: list[list[str]], min_same_count: int = 2) -> int:
    """
    Find the first row index that has the "stable" column count (mode among non-blank rows).
    Requires the stable count to appear in at least min_same_count rows so we don't pick a fluke.
    Returns 0 if we can't determine (fall back to first row as header).
    """
    from collections import Counter

    non_blank = [r for r in rows_list if not _is_blank_row(r)]
    if not non_blank:
        return 0
    count_freq = Counter(len(r) for r in non_blank)
    # Prefer a count that appears at least min_same_count times.
    best = None
    for count, freq in count_freq.most_common():
        if freq >= min_same_count:
            best = count
            break
    if best is None:
        best = count_freq.most_common(1)[0][0]
    for i, row in enumerate(rows_list):
        if len(row) == best:
            return i
    return 0


def load_csv(
    path: str | None,
    delimiter: str = ",",
    has_header: bool = True,
    comment_char: str | None = None,
    encoding: str = DEFAULT_ENCODING,
    text_override: str | None = None,
    skip_lines: int | None = None,
) -> tuple[list[str], list[dict[str, str]], int]:
    """
    Load CSV and return (columns, data_rows, header_row).
    header_row is 1-based index of the header in the parsed rows (1 = first row); 0 when has_header is False.
    Only rows with the same number of columns as the header are included (footers/comments excluded).
    Lines that start with comment_char are skipped before parsing.
    If text_override is provided, use it instead of reading from path.
    If skip_lines is set, that many lines are dropped after blank/comment handling; the next line is the header.
    Otherwise, when has_header is True, the header is the first row that has the "stable" column count
    (the count that appears most often among non-blank rows, at least 2 rows), so descriptive preamble
    lines (single-column or different column count) are skipped automatically.
    """
    text = text_override if text_override is not None else read_text(path, encoding)
    # Strip UTF-8 BOM so it does not become a column name or break header detection.
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines:
        return ([], [], 0)

    lines = _lines_filter_comment(lines, comment_char)
    if not lines:
        return ([], [], 0)

    # Drop leading blank lines (empty or whitespace-only).
    while lines and not lines[0].strip():
        lines = lines[1:]
    if not lines:
        return ([], [], 0)

    # Optional: skip a fixed number of preamble lines (then first parsed row = header).
    if skip_lines is not None and skip_lines > 0:
        lines = lines[skip_lines:]
    if not lines:
        return ([], [], 0)

    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows_list: list[list[str]] = list(reader)
    if not rows_list:
        return ([], [], 0)

    # Skip any leading blank rows that still made it through (e.g. BOM-only row).
    while rows_list and _is_blank_row(rows_list[0]):
        rows_list = rows_list[1:]
    if not rows_list:
        return ([], [], 0)

    header_row_1based: int
    if has_header:
        if skip_lines is not None and skip_lines > 0:
            header = rows_list[0]
            data_rows_raw = rows_list[1:]
            header_row_1based = 1
        else:
            header_idx = _find_header_row(rows_list)
            header = rows_list[header_idx]
            data_rows_raw = rows_list[header_idx + 1 :]
            header_row_1based = header_idx + 1
    else:
        ncols = len(rows_list[0]) if rows_list else 0
        header = [f"col{i}" for i in range(ncols)]
        data_rows_raw = rows_list
        header_row_1based = 0

    expected_len = len(header)
    data_rows_raw = [r for r in data_rows_raw if len(r) == expected_len]

    rows: list[dict[str, str]] = []
    for r in data_rows_raw:
        rows.append(dict(zip(header, r)))

    return (header, rows, header_row_1based)


def write_csv(
    columns: list[str],
    rows: list[dict[str, str]],
    delimiter: str = ",",
    stream: Any = None,
) -> None:
    """Write CSV to stream (default stdout)."""
    if stream is None:
        stream = sys.stdout
    writer = csv.DictWriter(stream, fieldnames=columns, delimiter=delimiter, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})


def sniff_type(value: str) -> str:
    """Return 'empty', 'number', or 'string' for a cell value."""
    s = value.strip()
    if not s:
        return "empty"
    try:
        float(s)
        return "number"
    except ValueError:
        pass
    return "string"


def parse_delimiter(s: str) -> str:
    """Parse delimiter from CLI; support \\t for tab."""
    if s == "\\t" or s == "tab":
        return "\t"
    return s


def write_json(data: Any, compact: bool = False) -> None:
    """Write JSON to stdout (for scripts that output JSON)."""
    import json

    if compact:
        json.dump(data, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    else:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
