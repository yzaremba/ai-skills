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
  return raw.split(",").map((f) => f.trim()).filter(Boolean);
}

function parseAgg(spec) {
  if (!spec.includes(":")) throw new Error(`Invalid --agg '${spec}'. Use field:func.`);
  const idx = spec.lastIndexOf(":");
  const field = spec.slice(0, idx).trim();
  const func = spec.slice(idx + 1).trim().toLowerCase();
  const allowed = new Set(["count", "sum", "min", "max", "mean", "list", "unique"]);
  if (!allowed.has(func)) throw new Error(`Unknown agg: ${func}`);
  return [field, func];
}

function computeAgg(values, func) {
  if (func === "count") return values.length;
  if (func === "list") return values;
  if (func === "unique") {
    const seen = new Set();
    const out = [];
    for (const v of values) {
      if (!seen.has(v)) {
        seen.add(v);
        out.push(v);
      }
    }
    return out;
  }
  const nums = [];
  for (const v of values) {
    const s = (v ?? "").trim();
    if (!s) continue;
    const n = Number.parseFloat(s);
    if (!Number.isNaN(n)) nums.push(n);
  }
  if (!nums.length) return null;
  if (func === "sum") return nums.reduce((a, b) => a + b, 0);
  if (func === "min") return Math.min(...nums);
  if (func === "max") return Math.max(...nums);
  if (func === "mean") return nums.reduce((a, b) => a + b, 0) / nums.length;
  return null;
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      delimiter: { type: "string", default: "," },
      "no-header": { type: "boolean", default: false },
      "skip-lines": { type: "string" },
      "comment-char": { type: "string" },
      encoding: { type: "string", default: DEFAULT_ENCODING },
      by: { type: "string" },
      agg: { type: "string", multiple: true, default: [] },
      sort: { type: "string", default: "count" },
      top: { type: "string" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  if (!values.by) {
    console.error("group.mjs: --by is required");
    process.exit(1);
  }

  const input = positionals[0] ?? "-";
  const { columns, rows } = loadCsv(input, {
    delimiter: parseDelimiter(values.delimiter),
    hasHeader: !values["no-header"],
    commentChar: values["comment-char"] ?? null,
    encoding: values.encoding,
    skipLines: values["skip-lines"] != null ? Number.parseInt(values["skip-lines"], 10) : null,
  });

  let byFields = parseFields(values.by);
  byFields = byFields.filter((f) => columns.includes(f));
  if (!byFields.length) byFields = columns.slice(0, 1);

  const aggSpecs = values.agg.map(parseAgg);

  const groups = new Map();
  for (const row of rows) {
    const key = JSON.stringify(byFields.map((f) => (row[f] ?? "").trim()));
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }

  let outRows = [];
  for (const [keyStr, groupRows] of groups) {
    const keyTuple = JSON.parse(keyStr);
    const rowDict = {};
    for (let i = 0; i < byFields.length; i++) rowDict[byFields[i]] = keyTuple[i];
    rowDict.count = groupRows.length;
    for (const [aggField, aggFunc] of aggSpecs) {
      const vals = groupRows.map((r) => (r[aggField] ?? "").trim());
      rowDict[`${aggField}:${aggFunc}`] = computeAgg(vals, aggFunc);
    }
    outRows.push(rowDict);
  }

  if (values.sort === "count") {
    outRows.sort((a, b) => b.count - a.count);
  } else {
    outRows.sort((a, b) => {
      for (const f of byFields) {
        const va = a[f] ?? "";
        const vb = b[f] ?? "";
        if (va !== vb) return va < vb ? -1 : 1;
      }
      return 0;
    });
  }

  if (values.top != null) {
    const n = Math.max(0, Number.parseInt(values.top, 10));
    outRows = outRows.slice(0, n);
  }

  const result = {
    total_records: rows.length,
    total_groups: groups.size,
    groups: outRows,
  };
  writeJson(result, values.compact);
}

main();
