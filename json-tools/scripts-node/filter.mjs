#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { existsPath, extractValues, loadJson, resolveArray, typeName, writeJson } from "./common.mjs";

const EXPR_RE = /^(.+?)(==|!=|>=|<=|>|<)(.+)$/;
const ALLOWED_TYPES = new Set(["string", "int", "float", "bool", "null", "array", "object"]);

function parseRhs(raw) {
  const text = raw.trim();
  const low = text.toLowerCase();
  if (low === "true") {
    return true;
  }
  if (low === "false") {
    return false;
  }
  if (low === "null") {
    return null;
  }
  if (text.includes(".")) {
    const asFloat = Number.parseFloat(text);
    if (!Number.isNaN(asFloat)) {
      return asFloat;
    }
  }
  const asInt = Number.parseInt(text, 10);
  if (!Number.isNaN(asInt) && /^-?\d+$/.test(text)) {
    return asInt;
  }
  return text.replace(/^["']|["']$/g, "");
}

function compareValues(left, right, op) {
  switch (op) {
    case "==":
      return left === right;
    case "!=":
      return left !== right;
    case ">":
      return left > right;
    case "<":
      return left < right;
    case ">=":
      return left >= right;
    case "<=":
      return left <= right;
    default:
      return false;
  }
}

function compareCondition(expr) {
  const match = EXPR_RE.exec(expr.trim());
  if (!match) {
    throw new Error(`Invalid --where expression: ${expr}`);
  }
  const [, fieldRaw, op, rhsRaw] = match;
  const field = fieldRaw.trim();
  const rhsValue = parseRhs(rhsRaw);

  return (record) => {
    const values = extractValues(record, field);
    for (const value of values) {
      try {
        if (compareValues(value, rhsValue, op)) {
          return true;
        }
      } catch {
        // Keep behavior similar to python TypeError skip.
      }
    }
    return false;
  };
}

function typeCondition(spec) {
  if (!spec.includes("=")) {
    throw new Error("--type must use field=typename syntax");
  }
  const [fieldRaw, expectedRaw] = spec.split("=", 2);
  const field = fieldRaw.trim();
  const expected = expectedRaw.trim();
  if (!ALLOWED_TYPES.has(expected)) {
    throw new Error(`Unsupported type '${expected}'. Use one of: ${JSON.stringify([...ALLOWED_TYPES].sort())}`);
  }
  return (record) => extractValues(record, field).some((value) => typeName(value) === expected);
}

function existsCondition(path, invert = false) {
  return (record) => {
    const result = existsPath(record, path.trim());
    return invert ? !result : result;
  };
}

function containsCondition(spec) {
  if (!spec.includes(":")) {
    throw new Error("--contains must be field:substring");
  }
  const [fieldRaw, substring] = spec.split(":", 2);
  const field = fieldRaw.trim();
  return (record) =>
    extractValues(record, field).some(
      (value) => typeof value === "string" && value.includes(substring)
    );
}

function regexCondition(spec) {
  if (!spec.includes(":")) {
    throw new Error("--regex must be field:pattern");
  }
  const [fieldRaw, pattern] = spec.split(":", 2);
  const field = fieldRaw.trim();
  let re;
  try {
    re = new RegExp(pattern);
  } catch (e) {
    throw new Error(`Invalid --regex pattern: ${e.message}`);
  }
  return (record) =>
    extractValues(record, field).some(
      (value) => typeof value === "string" && re.test(value)
    );
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "array-path": { type: "string" },
      where: { type: "string", multiple: true, default: [] },
      exists: { type: "string", multiple: true, default: [] },
      "not-exists": { type: "string", multiple: true, default: [] },
      type: { type: "string", multiple: true, default: [] },
      contains: { type: "string", multiple: true, default: [] },
      regex: { type: "string", multiple: true, default: [] },
      or: { type: "boolean", default: false },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const data = loadJson(input);
  let rows = resolveArray(data, values["array-path"]);
  if (!rows.length && !Array.isArray(data)) {
    rows = [data];
  }

  const predicates = [];
  for (const expr of values.where) {
    predicates.push(compareCondition(expr));
  }
  for (const path of values.exists) {
    predicates.push(existsCondition(path, false));
  }
  for (const path of values["not-exists"]) {
    predicates.push(existsCondition(path, true));
  }
  for (const spec of values.type) {
    predicates.push(typeCondition(spec));
  }
  for (const spec of values.contains) {
    predicates.push(containsCondition(spec));
  }
  for (const spec of values.regex) {
    predicates.push(regexCondition(spec));
  }

  if (!predicates.length) {
    writeJson(rows, values.compact);
    return;
  }

  const filtered = values.or
    ? rows.filter((row) => predicates.some((pred) => pred(row)))
    : rows.filter((row) => predicates.every((pred) => pred(row)));
  writeJson(filtered, values.compact);
}

main();
