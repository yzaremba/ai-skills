#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Filter CSV rows by column conditions: --where, --in, --contains, --regex, --empty, --non-empty."""

from __future__ import annotations

import argparse
import operator
import re
import sys
from typing import Callable

from common import load_csv, parse_delimiter, write_csv, write_json

OPS: dict[str, Callable[[str, str], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}
EXPR_RE = re.compile(r"^(.+?)(==|!=|>=|<=|>|<)(.+)$")


def add_dialect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", nargs="?", default="-", help="Input CSV file or '-' for stdin.")
    parser.add_argument("--delimiter", default=",", help="Field delimiter (use '\\t' for tab).")
    parser.add_argument("--no-header", action="store_true", help="First row is data.")
    parser.add_argument("--skip-lines", type=int, default=None, help="Skip this many preamble lines; next line is header.")
    parser.add_argument("--comment-char", help="Skip lines starting with this character.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding.")


def parse_rhs(raw: str) -> str:
    s = raw.strip().strip('"').strip("'")
    return s


def compare_condition(expr: str) -> Callable[[dict[str, str]], bool]:
    match = EXPR_RE.match(expr.strip())
    if not match:
        raise ValueError(f"Invalid --where expression: {expr!r}")
    field, op, rhs = match.groups()
    field = field.strip()
    rhs_val = parse_rhs(rhs)
    comp = OPS[op]

    def pred(row: dict[str, str]) -> bool:
        val = row.get(field, "")
        return comp(val, rhs_val)

    return pred


def in_condition(col: str, values: list[str]) -> Callable[[dict[str, str]], bool]:
    val_set = {v.strip() for v in values}

    def pred(row: dict[str, str]) -> bool:
        return (row.get(col, "") or "").strip() in val_set

    return pred


def contains_condition(col: str, substring: str) -> Callable[[dict[str, str]], bool]:
    def pred(row: dict[str, str]) -> bool:
        return substring in (row.get(col, "") or "")

    return pred


def regex_condition(col: str, pattern: str) -> Callable[[dict[str, str]], bool]:
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid --regex pattern: {e}") from e

    def pred(row: dict[str, str]) -> bool:
        return bool(compiled.search(row.get(col, "") or ""))

    return pred


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter CSV rows by column conditions.")
    add_dialect_args(parser)
    parser.add_argument("--where", action="append", default=[], help='Comparison e.g. "age>=18". In shell, escape $ (e.g. \\$0.00) or use single quotes: --where \'Fees!="$0.00"\'.')
    parser.add_argument("--in", dest="in_spec", help="Column:value1,value2 — keep rows where column in values.")
    parser.add_argument("--contains", action="append", default=[], help="Column:substring — keep rows where column contains substring.")
    parser.add_argument("--regex", action="append", default=[], help="Column:pattern — keep rows where column matches regex.")
    parser.add_argument("--empty", action="append", default=[], help="Column must be empty (or missing).")
    parser.add_argument("--non-empty", action="append", default=[], help="Column must be non-empty.")
    parser.add_argument("--or", dest="use_or", action="store_true", help="Combine conditions with OR instead of AND.")
    parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format (default: csv).")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON when --format json.")
    args = parser.parse_args()

    columns, rows = load_csv(
        args.input,
        delimiter=parse_delimiter(args.delimiter),
        has_header=not args.no_header,
        comment_char=args.comment_char,
        encoding=args.encoding,
        skip_lines=args.skip_lines,
    )[:2]

    preds: list[Callable[[dict[str, str]], bool]] = []
    for expr in args.where:
        preds.append(compare_condition(expr))
    if args.in_spec:
        if ":" not in args.in_spec:
            raise ValueError("--in must be column:value1,value2")
        col, rest = args.in_spec.split(":", 1)
        preds.append(in_condition(col.strip(), rest.split(",")))
    for spec in args.contains:
        if ":" not in spec:
            raise ValueError("--contains must be column:substring")
        col, substring = spec.split(":", 1)
        preds.append(contains_condition(col.strip(), substring))
    for spec in args.regex:
        if ":" not in spec:
            raise ValueError("--regex must be column:pattern")
        col, pattern = spec.split(":", 1)
        preds.append(regex_condition(col.strip(), pattern))
    for col in args.empty:
        c = col.strip()
        preds.append(lambda row, c=c: not (row.get(c, "") or "").strip())
    for col in args.non_empty:
        c = col.strip()
        preds.append(lambda row, c=c: bool((row.get(c, "") or "").strip()))

    def combined(row: dict[str, str]) -> bool:
        if not preds:
            return True
        if args.use_or:
            return any(p(row) for p in preds)
        return all(p(row) for p in preds)

    filtered = [r for r in rows if combined(r)]

    if args.format == "csv":
        write_csv(columns, filtered, parse_delimiter(args.delimiter), sys.stdout)
    else:
        write_json(filtered, compact=args.compact)


if __name__ == "__main__":
    main()
