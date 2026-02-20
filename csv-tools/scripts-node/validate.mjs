#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import {
  DEFAULT_ENCODING,
  parseCsv,
  parseDelimiter,
  readText,
  linesFilterComment,
  writeJson,
} from "./common.mjs";

function main() {
  const { values, positionals } = parseArgs({
    options: {
      delimiter: { type: "string", default: "," },
      "no-header": { type: "boolean", default: false },
      "comment-char": { type: "string" },
      encoding: { type: "string", default: DEFAULT_ENCODING },
      strict: { type: "boolean", default: false },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const text = readText(input, values.encoding);
  let lines = text.replace(/^\uFEFF/, "").split(/\r?\n/);
  lines = linesFilterComment(lines, values["comment-char"] ?? null);
  const delim = parseDelimiter(values.delimiter);
  const rows = parseCsv(lines.join("\n") + "\n", delim);

  if (!rows.length) {
    writeJson({ valid: true, record_count: 0, message: "empty file" }, values.compact);
    return;
  }

  const expectedLen = rows[0].length;
  let dataRows;
  let skipped;

  if (values["no-header"]) {
    dataRows = rows.filter((r) => r.length === expectedLen);
    skipped = rows.filter((r) => r.length !== expectedLen).length;
  } else {
    dataRows = rows.slice(1).filter((r) => r.length === expectedLen);
    skipped = rows.slice(1).filter((r) => r.length !== expectedLen).length;
  }

  const valid = skipped === 0 || !values.strict;
  const result = {
    valid,
    record_count: dataRows.length,
    skipped_rows: skipped,
    expected_columns: expectedLen,
    size_bytes: Buffer.byteLength(text, values.encoding),
  };
  if (!valid && values.strict) {
    result.error = `Inconsistent column count: ${skipped} row(s) skipped (footer/comment lines).`;
  }
  writeJson(result, values.compact);
}

main();
