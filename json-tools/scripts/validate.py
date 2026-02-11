#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Validate JSON syntax and report useful diagnostics."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from common import type_name, write_json

TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def read_text(path: str | None) -> str:
    if not path or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def analyze(text: str, strict: bool) -> dict[str, Any]:
    warnings: list[str] = []
    if strict and TRAILING_COMMA_RE.search(text):
        warnings.append("Possible trailing comma detected.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as err:
        return {
            "valid": False,
            "error": err.msg,
            "line": err.lineno,
            "column": err.colno,
            "position": err.pos,
            "warnings": warnings,
        }

    result: dict[str, Any] = {
        "valid": True,
        "top_level_type": type_name(parsed),
        "size_bytes": len(text.encode("utf-8")),
        "warnings": warnings,
    }
    if isinstance(parsed, list):
        result["record_count"] = len(parsed)
    elif isinstance(parsed, dict):
        result["field_count"] = len(parsed)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate JSON file syntax.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--strict", action="store_true", help="Enable extra non-fatal checks.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    text = read_text(args.input)
    result = analyze(text, strict=args.strict)
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
