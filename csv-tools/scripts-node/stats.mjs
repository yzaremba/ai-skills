#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import {
  DEFAULT_ENCODING,
  loadCsv,
  parseDelimiter,
  writeJson,
} from "./common.mjs";

function parseFields(raw) {
  if (!raw) return [];
  return raw.split(",").map((f) => f.trim()).filter(Boolean);
}

function numericSummary(values) {
  const nums = [];
  for (const v of values) {
    const s = (v ?? "").trim();
    if (!s) continue;
    const n = Number.parseFloat(s);
    if (!Number.isNaN(n)) nums.push(n);
  }
  if (!nums.length) return null;
  const sum = nums.reduce((a, b) => a + b, 0);
  return {
    count: nums.length,
    min: Math.min(...nums),
    max: Math.max(...nums),
    mean: sum / nums.length,
  };
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      delimiter: { type: "string", default: "," },
      "no-header": { type: "boolean", default: false },
      "skip-lines": { type: "string" },
      "comment-char": { type: "string" },
      encoding: { type: "string", default: DEFAULT_ENCODING },
      fields: { type: "string" },
      top: { type: "string", default: "10" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const { columns, rows } = loadCsv(input, {
    delimiter: parseDelimiter(values.delimiter),
    hasHeader: !values["no-header"],
    commentChar: values["comment-char"] ?? null,
    encoding: values.encoding,
    skipLines: values["skip-lines"] != null ? Number.parseInt(values["skip-lines"], 10) : null,
  });

  let selected = values.fields ? parseFields(values.fields) : columns;
  selected = selected.filter((c) => columns.includes(c));
  if (!selected.length) selected = [...columns];

  const topN = Math.max(0, Number.parseInt(values.top, 10));
  const fieldStats = {};

  for (const col of selected) {
    const colValues = rows.map((r) => r[col] ?? "");
    const presence = colValues.filter((v) => (v || "").trim()).length;
    const freq = new Map();
    for (const v of colValues) {
      freq.set(v, (freq.get(v) ?? 0) + 1);
    }
    const sorted = [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, topN);
    const entry = {
      presence: `${presence}/${rows.length}`,
      unique_values: freq.size,
      top_values: sorted.map(([value, count]) => ({ value, count })),
    };
    const num = numericSummary(colValues);
    if (num) entry.numeric = num;
    fieldStats[col] = entry;
  }

  const result = {
    record_count: rows.length,
    field_count: selected.length,
    fields: fieldStats,
  };
  writeJson(result, values.compact);
}

main();
