#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { firstValue, loadJson, writeJson } from "./common.mjs";

function shallowMerge(objects) {
  const out = {};
  for (const obj of objects) {
    Object.assign(out, obj);
  }
  return out;
}

function deepClone(value) {
  if (value && typeof value === "object") {
    return JSON.parse(JSON.stringify(value));
  }
  return value;
}

function deepMergeValues(left, right) {
  if (left && typeof left === "object" && !Array.isArray(left)
    && right && typeof right === "object" && !Array.isArray(right)) {
    const merged = { ...left };
    for (const [key, value] of Object.entries(right)) {
      if (Object.hasOwn(merged, key)) {
        merged[key] = deepMergeValues(merged[key], value);
      } else {
        merged[key] = deepClone(value);
      }
    }
    return merged;
  }
  if (Array.isArray(left) && Array.isArray(right)) {
    return [...left, ...right];
  }
  return deepClone(right);
}

function mergeArrays(arrays, uniqueBy) {
  const combined = [];
  for (const arr of arrays) {
    combined.push(...arr);
  }
  if (!uniqueBy) {
    return combined;
  }
  const seen = new Set();
  const deduped = [];
  for (const item of combined) {
    const key = firstValue(item, uniqueBy);
    const token = `${typeof key}:${JSON.stringify(key)}`;
    if (seen.has(token)) {
      continue;
    }
    seen.add(token);
    deduped.push(item);
  }
  return deduped;
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      mode: { type: "string", default: "concat" },
      "unique-by": { type: "string" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  if (positionals.length < 1) {
    throw new Error("At least one input path is required.");
  }
  if (!["concat", "shallow", "deep"].includes(values.mode)) {
    throw new Error("--mode must be one of: concat, shallow, deep");
  }

  const docs = positionals.map((path) => loadJson(path));
  let result;
  if (values.mode === "concat") {
    const arrays = docs.filter((doc) => Array.isArray(doc));
    result = mergeArrays(arrays, values["unique-by"]);
  } else if (values.mode === "shallow") {
    const objects = docs.filter((doc) => doc && typeof doc === "object" && !Array.isArray(doc));
    result = shallowMerge(objects);
  } else {
    const objects = docs.filter((doc) => doc && typeof doc === "object" && !Array.isArray(doc));
    result = {};
    for (const obj of objects) {
      result = deepMergeValues(result, obj);
    }
  }
  writeJson(result, values.compact);
}

main();
