#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { firstValue, loadJson, resolveArray, writeJson } from "./common.mjs";

function parseFields(raw) {
  return raw.split(",").map((item) => item.trim()).filter(Boolean);
}

function parseAgg(spec) {
  if (spec.trim().toLowerCase() === "count") {
    return ["", "count"];
  }
  if (!spec.includes(":")) {
    throw new Error(`Invalid --agg spec '${spec}'. Use field:func or 'count'.`);
  }
  const idx = spec.lastIndexOf(":");
  const field = spec.slice(0, idx).trim();
  const func = spec.slice(idx + 1).trim().toLowerCase();
  const allowed = new Set(["count", "sum", "min", "max", "mean", "list", "unique"]);
  if (!allowed.has(func)) {
    throw new Error(`Unknown aggregation '${func}'. Use one of: ${JSON.stringify([...allowed].sort())}`);
  }
  return [field, func];
}

function groupKey(record, byFields) {
  return byFields.map((field) => {
    let value = firstValue(record, field);
    if (value && typeof value === "object") {
      value = JSON.stringify(value);
    }
    return value;
  });
}

function groupKeyString(keyArr) {
  return keyArr.map((v) => `${typeof v}:${JSON.stringify(v)}`).join("|");
}

function computeAgg(values, func) {
  if (func === "count") {
    return values.length;
  }
  if (func === "list") {
    return values;
  }
  if (func === "unique") {
    const seen = [];
    const seenSet = new Set();
    for (const v of values) {
      const token = JSON.stringify(v);
      if (!seenSet.has(token)) {
        seenSet.add(token);
        seen.push(v);
      }
    }
    return seen;
  }
  // Numeric aggregations.
  const nums = values.filter((v) => typeof v === "number" && !Number.isNaN(v));
  if (!nums.length) {
    return null;
  }
  if (func === "sum") {
    return nums.reduce((acc, n) => acc + n, 0);
  }
  if (func === "min") {
    return Math.min(...nums);
  }
  if (func === "max") {
    return Math.max(...nums);
  }
  if (func === "mean") {
    return nums.reduce((acc, n) => acc + n, 0) / nums.length;
  }
  return null;
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "array-path": { type: "string" },
      by: { type: "string" },
      agg: { type: "string", multiple: true, default: [] },
      sort: { type: "string", default: "count" },
      top: { type: "string" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  if (!values.by) {
    throw new Error("--by is required");
  }
  if (!["count", "key"].includes(values.sort)) {
    throw new Error("--sort must be 'count' or 'key'");
  }

  const byFields = parseFields(values.by);
  const aggSpecs = values.agg.length ? values.agg.map(parseAgg) : [["", "count"]];

  const input = positionals[0] ?? "-";
  const data = loadJson(input);
  let records = resolveArray(data, values["array-path"]);
  if (!records.length) {
    records = Array.isArray(data) ? data : [data];
  }

  // Group records.
  const groupMap = new Map();
  const groupKeys = new Map();
  for (const record of records) {
    const keyArr = groupKey(record, byFields);
    const keyStr = groupKeyString(keyArr);
    if (!groupMap.has(keyStr)) {
      groupMap.set(keyStr, []);
      groupKeys.set(keyStr, keyArr);
    }
    groupMap.get(keyStr).push(record);
  }

  // Build output rows.
  const rows = [];
  for (const [keyStr, groupRecords] of groupMap) {
    const keyArr = groupKeys.get(keyStr);
    const row = {};
    byFields.forEach((field, i) => {
      row[field] = keyArr[i];
    });
    row.count = groupRecords.length;
    for (const [aggField, aggFunc] of aggSpecs) {
      if (aggField === "" && aggFunc === "count") {
        continue;
      }
      const fieldValues = [];
      for (const record of groupRecords) {
        const v = firstValue(record, aggField);
        if (v !== null && v !== undefined) {
          fieldValues.push(v);
        }
      }
      const label = `${aggField}:${aggFunc}`;
      row[label] = computeAgg(fieldValues, aggFunc);
    }
    rows.push(row);
  }

  // Sort.
  if (values.sort === "count") {
    rows.sort((a, b) => b.count - a.count);
  } else {
    rows.sort((a, b) => {
      for (const field of byFields) {
        const av = a[field] ?? "";
        const bv = b[field] ?? "";
        if (av < bv) return -1;
        if (av > bv) return 1;
      }
      return 0;
    });
  }

  // Limit.
  const top = values.top !== undefined ? Number.parseInt(values.top, 10) : null;
  const limited = top !== null ? rows.slice(0, Math.max(top, 0)) : rows;

  writeJson({
    total_records: records.length,
    total_groups: groupMap.size,
    groups: limited,
  }, values.compact);
}

main();
