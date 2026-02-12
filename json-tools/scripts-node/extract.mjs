#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { extractValues, loadJson, resolveArray, writeJson } from "./common.mjs";

function parseFields(raw) {
  if (!raw) {
    return [];
  }
  return raw.split(",").map((field) => field.trim()).filter(Boolean);
}

function selectRows(data, arrayPath, first, last) {
  let rows = resolveArray(data, arrayPath);
  if (first !== null) {
    rows = rows.slice(0, Math.max(first, 0));
  }
  if (last !== null) {
    rows = rows.slice(-Math.max(last, 0));
  }
  return rows;
}

function extractFields(rows, fields, includeMissing) {
  const output = [];
  for (const row of rows) {
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      output.push({ _value: row });
      continue;
    }
    const item = {};
    for (const field of fields) {
      const values = extractValues(row, field);
      if (values.length) {
        item[field] = values.length > 1 ? values : values[0];
      } else if (includeMissing) {
        item[field] = null;
      }
    }
    output.push(item);
  }
  return output;
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "array-path": { type: "string" },
      fields: { type: "string" },
      first: { type: "string" },
      last: { type: "string" },
      "include-missing": { type: "boolean", default: false },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const first = values.first !== undefined ? Number.parseInt(values.first, 10) : null;
  const last = values.last !== undefined ? Number.parseInt(values.last, 10) : null;
  const data = loadJson(input);
  const fields = parseFields(values.fields);

  let rows = selectRows(data, values["array-path"], first, last);
  if (!rows.length && !Array.isArray(data)) {
    rows = [data];
  } else if (Array.isArray(data) && values["array-path"] === undefined) {
    rows = selectRows(data, undefined, first, last);
  }

  const result = fields.length ? extractFields(rows, fields, values["include-missing"]) : rows;
  writeJson(result, values.compact);
}

main();
