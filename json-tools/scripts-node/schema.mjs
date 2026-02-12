#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { loadJson, resolveArray, typeName, writeJson } from "./common.mjs";

function inferSchema(value, depth, includeCounts) {
  if (depth < 0) {
    return { type: typeName(value) };
  }

  if (value && typeof value === "object" && !Array.isArray(value)) {
    const fields = {};
    for (const [key, inner] of Object.entries(value)) {
      fields[key] = inferSchema(inner, depth - 1, includeCounts);
    }
    const out = { type: "object", fields };
    if (includeCounts) {
      out.field_count = Object.keys(value).length;
    }
    return out;
  }

  if (Array.isArray(value)) {
    const itemTypeSet = new Set(value.map((item) => typeName(item)));
    const out = {
      type: "array",
      size: value.length,
      item_types: [...itemTypeSet].sort(),
    };
    if (value.length && depth > 0) {
      if (value.every((item) => item && typeof item === "object" && !Array.isArray(item))) {
        const keyCounts = new Map();
        for (const item of value) {
          for (const key of Object.keys(item)) {
            keyCounts.set(key, (keyCounts.get(key) ?? 0) + 1);
          }
        }
        const mergedFields = {};
        for (const key of [...keyCounts.keys()].sort()) {
          const samples = value.map((item) => item[key]).filter((sample) => sample !== undefined);
          const sampleValue = samples.length ? samples[0] : null;
          mergedFields[key] = inferSchema(sampleValue, depth - 1, includeCounts);
          if (includeCounts) {
            mergedFields[key].presence = `${keyCounts.get(key)}/${value.length}`;
          }
        }
        out.item_schema = { type: "object", fields: mergedFields };
      } else {
        out.item_schema = inferSchema(value[0], depth - 1, includeCounts);
      }
    }
    return out;
  }

  return { type: typeName(value) };
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "array-path": { type: "string" },
      depth: { type: "string", default: "6" },
      counts: { type: "boolean", default: false },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const depth = Number.parseInt(values.depth, 10);
  let data = loadJson(input);
  if (values["array-path"]) {
    const resolved = resolveArray(data, values["array-path"]);
    if (resolved.length) {
      data = resolved;
    }
  }
  const schema = inferSchema(data, depth, values.counts);
  writeJson(schema, values.compact);
}

main();
