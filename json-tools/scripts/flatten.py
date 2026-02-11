#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Flatten nested JSON using dot-notation keys."""

from __future__ import annotations

import argparse
from typing import Any

from common import flatten_json, load_json, resolve_array, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Flatten nested JSON structures.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--array-path", help="Path to array or value to flatten.")
    parser.add_argument("--separator", default=".", help="Separator used in flattened keys.")
    parser.add_argument(
        "--array-mode",
        choices=["index", "ignore", "expand"],
        default="index",
        help="How to handle arrays while flattening.",
    )
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    data = load_json(args.input)
    if args.array_path:
        target = resolve_array(data, args.array_path)
        if not target:
            # If path does not resolve to array, keep original behavior by flattening source.
            target = data
    else:
        target = data

    if isinstance(target, list):
        result: Any = [flatten_json(item, args.separator, args.array_mode) for item in target]
    else:
        result = flatten_json(target, args.separator, args.array_mode)
    write_json(result, compact=args.compact)


if __name__ == "__main__":
    main()
