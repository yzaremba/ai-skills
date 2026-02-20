#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import {
  DEFAULT_ENCODING,
  detectDelimiter,
  loadCsv,
  linesFilterComment,
  parseDelimiter,
  readText,
  writeJson,
} from "./common.mjs";

function main() {
  const { values, positionals } = parseArgs({
    options: {
      delimiter: { type: "string" },
      "no-header": { type: "boolean", default: false },
      "skip-lines": { type: "string" },
      "comment-char": { type: "string" },
      encoding: { type: "string", default: DEFAULT_ENCODING },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const text = readText(input, values.encoding);
  const lines = text.split(/\r?\n/);
  const sizeBytes = Buffer.byteLength(text, values.encoding);

  const commentChar = values["comment-char"] ?? null;
  const delimiter = values.delimiter
    ? parseDelimiter(values.delimiter)
    : detectDelimiter(lines, commentChar);

  const { columns, rows, headerRow } = loadCsv(input, {
    delimiter,
    hasHeader: !values["no-header"],
    commentChar,
    encoding: values.encoding,
    textOverride: text,
    skipLines: values["skip-lines"] != null ? Number.parseInt(values["skip-lines"], 10) : null,
  });

  const sample = rows[0] ?? {};
  const result = {
    valid: true,
    delimiter,
    has_header: !values["no-header"],
    header_row: headerRow,
    record_count: rows.length,
    columns,
    encoding: values.encoding,
    size_bytes: sizeBytes,
    sample_row: sample,
  };
  writeJson(result, values.compact);
}

main();
