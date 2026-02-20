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

const EXPR_RE = /^(.+?)(==|!=|>=|<=|>|<)(.+)$/;

function parseRhs(raw) {
  return raw.trim().replace(/^["']|["']$/g, "").trim();
}

function compareCondition(expr) {
  const m = expr.trim().match(EXPR_RE);
  if (!m) throw new Error(`Invalid --where expression: ${expr}`);
  const [, fieldRaw, op, rhsRaw] = m;
  const field = fieldRaw.trim();
  const rhsVal = parseRhs(rhsRaw);
  const ops = {
    "==": (a, b) => a === b,
    "!=": (a, b) => a !== b,
    ">": (a, b) => a > b,
    "<": (a, b) => a < b,
    ">=": (a, b) => a >= b,
    "<=": (a, b) => a <= b,
  };
  const comp = ops[op];
  return (row) => comp((row[field] ?? "").trim(), rhsVal);
}

function inCondition(col, valuesList) {
  const valSet = new Set(valuesList.map((v) => v.trim()));
  return (row) => valSet.has((row[col] ?? "").trim());
}

function containsCondition(col, substring) {
  return (row) => (row[col] ?? "").includes(substring);
}

function regexCondition(col, pattern) {
  let re;
  try {
    re = new RegExp(pattern);
  } catch (e) {
    throw new Error(`Invalid --regex pattern: ${e.message}`);
  }
  return (row) => re.test(row[col] ?? "");
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      delimiter: { type: "string", default: "," },
      "no-header": { type: "boolean", default: false },
      "skip-lines": { type: "string" },
      "comment-char": { type: "string" },
      encoding: { type: "string", default: DEFAULT_ENCODING },
      where: { type: "string", multiple: true, default: [] },
      in: { type: "string" },
      contains: { type: "string", multiple: true, default: [] },
      regex: { type: "string", multiple: true, default: [] },
      empty: { type: "string", multiple: true, default: [] },
      "non-empty": { type: "string", multiple: true, default: [] },
      or: { type: "boolean", default: false },
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

  const preds = [];
  for (const expr of values.where) {
    preds.push(compareCondition(expr));
  }
  if (values.in) {
    if (!values.in.includes(":")) throw new Error("--in must be column:value1,value2");
    const [col, rest] = values.in.split(":", 2);
    preds.push(inCondition(col.trim(), rest.split(",")));
  }
  for (const spec of values.contains) {
    if (!spec.includes(":")) throw new Error("--contains must be column:substring");
    const [col, substring] = spec.split(":", 2);
    preds.push(containsCondition(col.trim(), substring));
  }
  for (const spec of values.regex) {
    if (!spec.includes(":")) throw new Error("--regex must be column:pattern");
    const [col, pattern] = spec.split(":", 2);
    preds.push(regexCondition(col.trim(), pattern));
  }
  for (const col of values.empty) {
    const c = col.trim();
    preds.push((row) => !(row[c] ?? "").trim());
  }
  for (const col of values["non-empty"]) {
    const c = col.trim();
    preds.push((row) => Boolean((row[c] ?? "").trim()));
  }

  const combined = (row) => {
    if (!preds.length) return true;
    if (values.or) return preds.some((p) => p(row));
    return preds.every((p) => p(row));
  };

  const filtered = rows.filter(combined);
  const delim = parseDelimiter(values.delimiter);
  if (values.format === "json") {
    writeJson(filtered, values.compact);
  } else {
    writeCsv(columns, filtered, delim, process.stdout);
  }
}

main();
