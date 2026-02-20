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
  if (!raw) return [];
  return raw.split(",").map((f) => f.trim()).filter(Boolean);
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
      first: { type: "string" },
      last: { type: "string" },
      format: { type: "string", default: "csv" },
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

  let outColumns = values.fields ? parseFields(values.fields) : columns;
  outColumns = outColumns.filter((c) => columns.includes(c));
  if (!outColumns.length) outColumns = [...columns];

  let outRows = rows;
  if (values.first != null) {
    const n = Math.max(0, Number.parseInt(values.first, 10));
    outRows = outRows.slice(0, n);
  }
  if (values.last != null) {
    const n = Math.max(0, Number.parseInt(values.last, 10));
    outRows = outRows.slice(-n);
  }

  const result = outRows.map((r) => {
    const obj = {};
    for (const k of outColumns) obj[k] = r[k] ?? "";
    return obj;
  });

  const delim = parseDelimiter(values.delimiter);
  if (values.format === "json") {
    writeJson(result, values.compact);
  } else {
    writeCsv(outColumns, result, delim, process.stdout);
  }
}

main();
