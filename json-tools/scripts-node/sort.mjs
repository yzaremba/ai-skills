#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { firstValue, loadJson, resolveArray, writeJson } from "./common.mjs";

function parseFields(raw) {
  return raw.split(",").map((item) => item.trim()).filter(Boolean);
}

function normalize(value, numeric) {
  if (value === null || value === undefined) {
    return numeric ? Number.NEGATIVE_INFINITY : "";
  }
  if (numeric) {
    const converted = Number(value);
    return Number.isNaN(converted) ? Number.NEGATIVE_INFINITY : converted;
  }
  return String(value);
}

function keyForRecord(record, fields, numeric) {
  return fields.map((field) => normalize(firstValue(record, field), numeric));
}

function compareKeys(left, right) {
  for (let i = 0; i < left.length; i += 1) {
    if (left[i] < right[i]) {
      return -1;
    }
    if (left[i] > right[i]) {
      return 1;
    }
  }
  return 0;
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      by: { type: "string" },
      "array-path": { type: "string" },
      desc: { type: "boolean", default: false },
      numeric: { type: "boolean", default: false },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  if (!values.by) {
    throw new Error("--by is required");
  }

  const fields = parseFields(values.by);
  const input = positionals[0] ?? "-";
  const data = loadJson(input);
  let rows = resolveArray(data, values["array-path"]);
  if (!rows.length) {
    rows = Array.isArray(data) ? data : [data];
  }

  const sortedRows = [...rows].sort((a, b) => {
    const cmp = compareKeys(keyForRecord(a, fields, values.numeric), keyForRecord(b, fields, values.numeric));
    return values.desc ? -cmp : cmp;
  });
  writeJson(sortedRows, values.compact);
}

main();
