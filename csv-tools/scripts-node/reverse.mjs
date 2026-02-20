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

  const reversedRows = [...rows].reverse();
  const delim = parseDelimiter(values.delimiter);
  if (values.format === "json") {
    writeJson(reversedRows, values.compact);
  } else {
    writeCsv(columns, reversedRows, delim, process.stdout);
  }
}

main();
