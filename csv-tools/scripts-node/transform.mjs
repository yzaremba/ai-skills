#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import {
  DEFAULT_ENCODING,
  loadCsv,
  parseDelimiter,
  readText,
  writeCsv,
  writeJson,
} from "./common.mjs";

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "from-format": { type: "string" },
      to: { type: "string" },
      delimiter: { type: "string", default: "," },
      "no-header": { type: "boolean", default: false },
      "skip-lines": { type: "string" },
      "comment-char": { type: "string" },
      encoding: { type: "string", default: DEFAULT_ENCODING },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const delim = parseDelimiter(values.delimiter);

  const inputIsJson =
    values["from-format"] === "json" ||
    (input !== "-" && input.endsWith(".json"));

  let columns;
  let rows;

  if (inputIsJson) {
    const text = readText(input, values.encoding);
    const data = JSON.parse(text);
    if (Array.isArray(data)) {
      rows = data;
      columns = rows.length && typeof rows[0] === "object" && rows[0] !== null && !Array.isArray(rows[0])
        ? Object.keys(rows[0])
        : [];
    } else if (data && typeof data === "object" && !Array.isArray(data)) {
      rows = [data];
      columns = Object.keys(data);
    } else {
      rows = [];
      columns = [];
    }
    if (rows.length && typeof rows[0] === "object" && rows[0] !== null && !Array.isArray(rows[0]) && !columns.length) {
      columns = Object.keys(rows[0]);
    }
  } else {
    const { columns: c, rows: r } = loadCsv(input, {
      delimiter: delim,
      hasHeader: !values["no-header"],
      commentChar: values["comment-char"] ?? null,
      encoding: values.encoding,
      skipLines: values["skip-lines"] != null ? Number.parseInt(values["skip-lines"], 10) : null,
    });
    columns = c;
    rows = r;
  }

  let toFormat = values.to;
  if (toFormat == null) {
    toFormat = inputIsJson ? "json" : "csv";
  }

  if (toFormat === "json") {
    writeJson(rows, values.compact);
  } else if (toFormat === "jsonl") {
    for (const row of rows) {
      process.stdout.write(JSON.stringify(row) + "\n");
    }
  } else {
    writeCsv(columns, rows, delim, process.stdout);
  }
}

main();
