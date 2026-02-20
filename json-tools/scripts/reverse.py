#!/usr/bin/env python3
# Copyright 2026 Yevgeniy Zaremba
# SPDX-License-Identifier: Apache-2.0

"""Reverse the order of JSON array entries."""

from __future__ import annotations

import argparse
from typing import Any

from common import load_json, resolve_array, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverse the order of JSON array entries.")
    parser.add_argument("input", nargs="?", default="-", help="Input JSON file path or '-' for stdin.")
    parser.add_argument("--array-path", help="Path to the array to reverse.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON output.")
    args = parser.parse_args()

    data: Any = load_json(args.input)
    rows = resolve_array(data, args.array_path)
    if not rows:
        rows = data if isinstance(data, list) else [data]

    reversed_rows = list(reversed(rows))
    write_json(reversed_rows, compact=args.compact)


if __name__ == "__main__":
    main()
