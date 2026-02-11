#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for json-tools scripts."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator, List

PATH_TOKEN_RE = re.compile(r"([^.\\[\\]]+)|(\\[(\\*|\\d+)\\])")


def load_json(path: str | None) -> Any:
    """Load JSON from a file path or stdin when path is '-' or None."""
    if not path or path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def write_json(data: Any, compact: bool = False) -> None:
    """Write JSON to stdout with deterministic formatting."""
    if compact:
        json.dump(data, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    else:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def parse_path(path: str) -> list[str | int]:
    """Parse dot path syntax with optional array indices and wildcards."""
    if not path:
        return []
    tokens: list[str | int] = []
    for match in PATH_TOKEN_RE.finditer(path):
        key = match.group(1)
        bracket_token = match.group(3)
        if key is not None:
            tokens.append(key)
        elif bracket_token is not None:
            if bracket_token == "*":
                tokens.append("*")
            else:
                tokens.append(int(bracket_token))
    return tokens


def extract_values(data: Any, path: str) -> list[Any]:
    """Extract all values matching path. Wildcards return multiple matches."""
    tokens = parse_path(path)
    if not tokens:
        return [data]
    values: list[Any] = [data]
    for token in tokens:
        next_values: list[Any] = []
        for item in values:
            if token == "*":
                if isinstance(item, list):
                    next_values.extend(item)
                elif isinstance(item, dict):
                    next_values.extend(item.values())
            elif isinstance(token, int):
                if isinstance(item, list) and -len(item) <= token < len(item):
                    next_values.append(item[token])
            else:
                if isinstance(item, dict) and token in item:
                    next_values.append(item[token])
        values = next_values
    return values


def exists_path(data: Any, path: str) -> bool:
    """Return true when at least one value exists for path."""
    return bool(extract_values(data, path))


def first_value(data: Any, path: str, default: Any = None) -> Any:
    """Get the first value matching path or default."""
    values = extract_values(data, path)
    return values[0] if values else default


def resolve_array(data: Any, array_path: str | None) -> list[Any]:
    """Resolve an array from data or an explicit path."""
    if array_path:
        values = extract_values(data, array_path)
        for value in values:
            if isinstance(value, list):
                return value
        return []
    if isinstance(data, list):
        return data
    return []


def flatten_json(data: Any, separator: str = ".", array_mode: str = "index") -> dict[str, Any]:
    """Flatten nested JSON structure into key/value pairs."""
    output: dict[str, Any] = {}

    def walk(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            if not value and prefix:
                output[prefix] = {}
                return
            for key, inner in value.items():
                next_prefix = f"{prefix}{separator}{key}" if prefix else key
                walk(inner, next_prefix)
            return
        if isinstance(value, list):
            if array_mode == "ignore":
                output[prefix] = value
                return
            if array_mode == "expand":
                # For expand mode, scalar arrays become repeated string joins.
                if all(not isinstance(item, (dict, list)) for item in value):
                    output[prefix] = value
                    return
            for idx, inner in enumerate(value):
                if array_mode == "expand":
                    next_prefix = prefix
                else:
                    next_prefix = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
                walk(inner, next_prefix)
            if not value and prefix:
                output[prefix] = []
            return
        output[prefix] = value

    walk(data, "")
    return output


def type_name(value: Any) -> str:
    """Map python value to a JSON-like type name."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def unique_types(values: Iterable[Any]) -> list[str]:
    """Collect sorted unique type names for values."""
    return sorted({type_name(v) for v in values})


def frequency(values: Iterable[Any]) -> Counter:
    """Build frequency counter for hashable representations."""
    normalized: list[str] = []
    for value in values:
        if isinstance(value, (dict, list)):
            normalized.append(json.dumps(value, sort_keys=True, ensure_ascii=False))
        else:
            normalized.append(str(value))
    return Counter(normalized)


def parse_literal(value: str) -> Any:
    """Parse CLI literal values into JSON-ish python values."""
    candidate = value.strip()
    lowered = candidate.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return candidate
