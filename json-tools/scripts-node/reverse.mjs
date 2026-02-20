#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { loadJson, resolveArray, writeJson } from "./common.mjs";

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "array-path": { type: "string" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const data = loadJson(input);
  let rows = resolveArray(data, values["array-path"]);
  if (!rows.length) {
    rows = Array.isArray(data) ? data : [data];
  }

  const reversedRows = [...rows].reverse();
  writeJson(reversedRows, values.compact);
}

main();
