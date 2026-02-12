#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs";
import { parseArgs } from "node:util";
import { typeName, writeJson } from "./common.mjs";

const TRAILING_COMMA_RE = /,\s*([}\]])/;

function readText(path) {
  if (!path || path === "-") {
    return fs.readFileSync(0, "utf-8");
  }
  return fs.readFileSync(path, "utf-8");
}

function analyze(text, strict) {
  const warnings = [];
  if (strict && TRAILING_COMMA_RE.test(text)) {
    warnings.push("Possible trailing comma detected.");
  }

  try {
    const parsed = JSON.parse(text);
    const result = {
      valid: true,
      top_level_type: typeName(parsed),
      size_bytes: Buffer.byteLength(text, "utf-8"),
      warnings,
    };
    if (Array.isArray(parsed)) {
      result.record_count = parsed.length;
    } else if (parsed && typeof parsed === "object") {
      result.field_count = Object.keys(parsed).length;
    }
    return result;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const posMatch = /position (\d+)/i.exec(message);
    const position = posMatch ? Number.parseInt(posMatch[1], 10) : null;
    let line = null;
    let column = null;
    if (position !== null) {
      const upTo = text.slice(0, position);
      const lineParts = upTo.split("\n");
      line = lineParts.length;
      column = lineParts[lineParts.length - 1].length + 1;
    }
    let error = message;
    const trailingMatch = /,\s*([}\]])/.exec(text);
    if (trailingMatch) {
      error = trailingMatch[1] === "}" ?
        "Expecting property name enclosed in double quotes" :
        "Expecting value";
      if (position === null) {
        const trailingPos = trailingMatch.index + trailingMatch[0].length - 1;
        const upTo = text.slice(0, trailingPos);
        const lineParts = upTo.split("\n");
        line = lineParts.length;
        column = lineParts[lineParts.length - 1].length + 1;
      }
    }
    return {
      valid: false,
      error,
      line,
      column,
      position,
      warnings,
    };
  }
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      strict: { type: "boolean", default: false },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const text = readText(input);
  const result = analyze(text, values.strict);
  writeJson(result, values.compact);
}

main();
