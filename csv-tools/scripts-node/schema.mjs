#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import {
  DEFAULT_ENCODING,
  loadCsv,
  parseDelimiter,
  sniffType,
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
      counts: { type: "boolean", default: false },
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

  const fields = {};
  for (const col of columns) {
    const typesCounter = new Map();
    let presence = 0;
    for (const row of rows) {
      const val = row[col] ?? "";
      const t = sniffType(val);
      typesCounter.set(t, (typesCounter.get(t) ?? 0) + 1);
      if ((val || "").trim()) presence += 1;
    }
    const entry = { types: [...typesCounter.keys()].sort() };
    if (values.counts) {
      entry.presence = `${presence}/${rows.length}`;
      entry.type_counts = Object.fromEntries(typesCounter);
    }
    fields[col] = entry;
  }

  const result = { columns, record_count: rows.length, fields };
  writeJson(result, values.compact);
}

main();
