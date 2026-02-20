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

function main() {
  const { values, positionals } = parseArgs({
    options: {
      delimiter: { type: "string", default: "," },
      "no-header": { type: "boolean", default: false },
      "skip-lines": { type: "string" },
      "comment-char": { type: "string" },
      encoding: { type: "string", default: DEFAULT_ENCODING },
      "unique-by": { type: "string" },
      format: { type: "string", default: "csv" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const inputs = positionals;
  if (!inputs.length) {
    console.error("merge.mjs: at least one input file required");
    process.exit(1);
  }

  const delim = parseDelimiter(values.delimiter);
  const dialect = {
    delimiter: delim,
    hasHeader: !values["no-header"],
    commentChar: values["comment-char"] ?? null,
    encoding: values.encoding,
    skipLines: values["skip-lines"] != null ? Number.parseInt(values["skip-lines"], 10) : null,
  };

  let allColumns = null;
  const allRows = [];

  for (const path of inputs) {
    const { columns, rows } = loadCsv(path, dialect);
    if (allColumns == null) allColumns = columns;
    for (const row of rows) {
      if (allColumns && columns.length === allColumns.length && columns.every((c, i) => c === allColumns[i])) {
        allRows.push({ ...row });
      } else {
        const obj = {};
        for (const c of allColumns) obj[c] = row[c] ?? "";
        allRows.push(obj);
      }
    }
  }

  if (allColumns == null) allColumns = [];

  let result = allRows;
  if (values["unique-by"] && allColumns.includes(values["unique-by"])) {
    const seen = new Set();
    result = [];
    for (const row of allRows) {
      const key = (row[values["unique-by"]] ?? "").trim();
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(row);
    }
  }

  if (values.format === "json") {
    writeJson(result, values.compact);
  } else {
    writeCsv(allColumns, result, delim, process.stdout);
  }
}

main();
