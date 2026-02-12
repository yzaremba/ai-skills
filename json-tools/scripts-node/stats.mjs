#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { extractValues, frequency, loadJson, resolveArray, uniqueTypes, writeJson } from "./common.mjs";

function parseFields(raw) {
  if (!raw) {
    return [];
  }
  return raw.split(",").map((item) => item.trim()).filter(Boolean);
}

function numericSummary(values) {
  const nums = values.filter((v) => typeof v === "number" && !Number.isNaN(v));
  if (!nums.length) {
    return {};
  }
  return {
    count: nums.length,
    min: Math.min(...nums),
    max: Math.max(...nums),
    mean: nums.reduce((acc, item) => acc + item, 0) / nums.length,
  };
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "array-path": { type: "string" },
      fields: { type: "string" },
      top: { type: "string", default: "10" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const top = Number.parseInt(values.top, 10);
  const data = loadJson(input);
  let records = resolveArray(data, values["array-path"]);
  if (!records.length) {
    records = Array.isArray(data) ? data : [data];
  }

  let selectedFields = parseFields(values.fields);
  if (!selectedFields.length) {
    const fieldCandidates = new Set();
    for (const record of records) {
      if (record && typeof record === "object" && !Array.isArray(record)) {
        for (const key of Object.keys(record)) {
          fieldCandidates.add(key);
        }
      }
    }
    selectedFields = [...fieldCandidates].sort();
  }

  const fieldStats = {};
  for (const field of selectedFields) {
    const fieldValues = [];
    let presence = 0;
    for (const record of records) {
      const found = extractValues(record, field);
      if (found.length) {
        presence += 1;
        fieldValues.push(...found);
      }
    }
    const freq = frequency(fieldValues);
    const hasComplex = fieldValues.some((v) => v && typeof v === "object");
    const entry = {
      presence: `${presence}/${records.length}`,
      types: uniqueTypes(fieldValues),
      unique_values: freq.size,
    };
    if (!hasComplex) {
      const topValues = [...freq.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, Math.max(top, 0))
        .map(([value, count]) => ({ value, count }));
      entry.top_values = topValues;
    }
    const numeric = numericSummary(fieldValues);
    if (Object.keys(numeric).length) {
      entry.numeric = numeric;
    }
    fieldStats[field] = entry;
  }

  writeJson({
    record_count: records.length,
    field_count: selectedFields.length,
    fields: fieldStats,
  }, values.compact);
}

main();
