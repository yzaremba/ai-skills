#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import {
  DEFAULT_ENCODING,
  loadCsv,
  parseDelimiter,
  writeCsv,
  writeJson,
} from "./common.mjs";

function parseFields(raw) {
  return raw.split(",").map((f) => f.trim()).filter(Boolean);
}

function keyForRow(row, fields, numeric) {
  return fields.map((field) => {
    let v = (row[field] ?? "").trim();
    if (numeric && v) {
      const n = Number.parseFloat(v);
      if (!Number.isNaN(n)) return n;
    }
    return v || (numeric ? -Infinity : "");
  });
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
      desc: { type: "boolean", default: false },
      numeric: { type: "boolean", default: false },
      format: { type: "string", default: "csv" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  if (!values.by) {
    console.error("sort.mjs: --by is required");
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

  const sorted = [...rows].sort((a, b) => {
    const ka = keyForRow(a, byFields, values.numeric);
    const kb = keyForRow(b, byFields, values.numeric);
    for (let i = 0; i < ka.length; i++) {
      const va = ka[i];
      const vb = kb[i];
      if (va < vb) return values.desc ? 1 : -1;
      if (va > vb) return values.desc ? -1 : 1;
    }
    return 0;
  });

  const delim = parseDelimiter(values.delimiter);
  if (values.format === "json") {
    writeJson(sorted, values.compact);
  } else {
    writeCsv(columns, sorted, delim, process.stdout);
  }
}

main();
