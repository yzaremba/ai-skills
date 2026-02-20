#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Filter JSON arrays by field conditions."""

from __future__ import annotations

import argparse
import operator
import re
from typing import Any, Callable

from common import exists_path, extract_values, first_value, load_json, resolve_array, type_name, write_json

OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}

EXPR_RE = re.compile(r"^(.+?)(==|!=|>=|<=|>|<)(.+)$")
ALLOWED_TYPES = {"string", "int", "float", "bool", "null", "array", "object"}


def parse_rhs(raw: str) -> Any:
    text = raw.strip()
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text.strip('"').strip("'")


def compare_condition(expr: str) -> Callable[[Any], bool]:
    match = EXPR_RE.match(expr.strip())
    if not match:
        raise ValueError(f"Invalid --where expression: {expr}")
    field, op, rhs = match.groups()
    field = field.strip()
    rhs_value = parse_rhs(rhs)
    comparator = OPS[op]

    def predicate(record: Any) -> bool:
        values = extract_values(record, field)
        for value in values:
            try:
                if comparator(value, rhs_value):
                    return True
            except TypeError:
                continue
        return False

    return predicate


def type_condition(spec: str) -> Callable[[Any], bool]:
    if "=" not in spec:
        raise ValueError("--type must use field=typename syntax")
    field, expected = spec.split("=", 1)
    field = field.strip()
    expected = expected.strip()
    if expected not in ALLOWED_TYPES:
        raise ValueError(f"Unsupported type '{expected}'. Use one of: {sorted(ALLOWED_TYPES)}")

    def predicate(record: Any) -> bool:
        values = extract_values(record, field)
        return any(type_name(value) == expected for value in values)

    return predicate


def exists_condition(path: str, invert: bool = False) -> Callable[[Any], bool]:
    def predicate(record: Any) -> bool:
        result = exists_path(record, path.strip())
        return not result if invert else result

    return predicate


def contains_condition(spec: str) -> Callable[[Any], bool]:
    if ":" not in spec:
        raise ValueError("--contains must be field:substring")
    field, substring = spec.split(":", 1)
    field = field.strip()

    def predicate(record: Any) -> bool:
        values = extract_values(record, field)
        for value in values:
            if isinstance(value, str) and substring in value:
                return True
        return False

    return predicate


def regex_condition(spec: str) -> Callable[[Any], bool]:
    if ":" not in spec:
        raise ValueError("--regex must be field:pattern")
    field, pattern = spec.split(":", 1)
    field = field.strip()
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid --regex pattern: {e}") from e

    def predicate(record: Any) -> bool:
        values = extract_values(record, field)
        for value in values:
            if isinstance(value, str) and compiled.search(value):
                return True
        return False

    return predicate


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter JSON rows by field conditions.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--array-path", help="Path to the array to filter.")
    parser.add_argument("--where", action="append", default=[], help='Comparison expression. Example: "age>=21"')
    parser.add_argument("--exists", action="append", default=[], help="Keep rows where path exists.")
    parser.add_argument("--not-exists", action="append", default=[], help="Keep rows where path does not exist.")
    parser.add_argument("--type", action="append", default=[], help="Type condition field=typename.")
    parser.add_argument("--contains", action="append", default=[], help="Field:substring — keep records where any string value contains substring.")
    parser.add_argument("--regex", action="append", default=[], help="Field:pattern — keep records where any string value matches regex.")
    parser.add_argument("--or", dest="use_or", action="store_true", help="Use OR logic instead of AND.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    data = load_json(args.input)
    rows = resolve_array(data, args.array_path)
    if not rows and not isinstance(data, list):
        rows = [data]

    predicates: list[Callable[[Any], bool]] = []
    for expr in args.where:
        predicates.append(compare_condition(expr))
    for path in args.exists:
        predicates.append(exists_condition(path, invert=False))
    for path in args.not_exists:
        predicates.append(exists_condition(path, invert=True))
    for spec in args.type:
        predicates.append(type_condition(spec))
    for spec in args.contains:
        predicates.append(contains_condition(spec))
    for spec in args.regex:
        predicates.append(regex_condition(spec))

    if not predicates:
        write_json(rows, compact=args.compact)
        return

    if args.use_or:
        filtered = [row for row in rows if any(pred(row) for pred in predicates)]
    else:
        filtered = [row for row in rows if all(pred(row) for pred in predicates)]
    write_json(filtered, compact=args.compact)


if __name__ == "__main__":
    main()
