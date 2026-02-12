#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs";
import { parseArgs } from "node:util";
import { typeName, writeJson } from "./common.mjs";

function readText(path) {
  if (!path || path === "-") {
    return fs.readFileSync(0, "utf-8");
  }
  return fs.readFileSync(path, "utf-8");
}

function collectRecordFields(records, sample) {
  const counts = new Map();
  let inspected = 0;
  for (const record of records) {
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      continue;
    }
    for (const key of Object.keys(record)) {
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    inspected += 1;
    if (inspected >= sample) {
      break;
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([key]) => key);
}

function findBestArrayChild(data) {
  let bestKey = null;
  let bestArr = [];
  for (const [key, value] of Object.entries(data)) {
    if (Array.isArray(value) && value.length > bestArr.length) {
      bestKey = key;
      bestArr = value;
    }
  }
  return [bestKey, bestArr];
}

function detectLayout(data) {
  if (Array.isArray(data)) {
    return {
      layout: "array",
      record_count: data.length,
      recommended_array_path: null,
      records: data,
    };
  }

  if (data && typeof data === "object") {
    const values = Object.values(data);
    const dictCount = values.filter((v) => v && typeof v === "object" && !Array.isArray(v)).length;
    if (values.length > 0 && dictCount / values.length >= 0.8) {
      return {
        layout: "object-of-objects",
        record_count: values.length,
        recommended_array_path: ".",
        records: values,
        sample_keys: Object.keys(data).slice(0, 10),
      };
    }

    const [bestKey, bestArr] = findBestArrayChild(data);
    if (bestKey && bestArr.length > 0) {
      return {
        layout: "nested-array",
        record_count: bestArr.length,
        recommended_array_path: bestKey,
        records: bestArr,
        top_level_fields: Object.keys(data).sort(),
      };
    }

    return {
      layout: "object",
      record_count: 1,
      recommended_array_path: null,
      records: [data],
      top_level_fields: Object.keys(data).sort(),
    };
  }

  return {
    layout: "scalar",
    record_count: 0,
    recommended_array_path: null,
    records: [],
  };
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      sample: { type: "string", default: "20" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const input = positionals[0] ?? "-";
  const sample = Number.parseInt(values.sample, 10);
  const text = readText(input);
  const sizeBytes = Buffer.byteLength(text, "utf-8");

  let data;
  try {
    data = JSON.parse(text);
  } catch (err) {
    writeJson({ valid: false, error: err instanceof Error ? err.message : String(err), size_bytes: sizeBytes }, values.compact);
    return;
  }

  const info = detectLayout(data);
  const records = info.records;
  delete info.records;

  const result = {
    valid: true,
    top_level_type: typeName(data),
    layout: info.layout,
    record_count: info.record_count,
    recommended_array_path: info.recommended_array_path,
    size_bytes: sizeBytes,
  };

  if (info.sample_keys) {
    result.sample_keys = info.sample_keys;
  }
  if (info.top_level_fields) {
    result.top_level_fields = info.top_level_fields;
  }

  result.record_fields = collectRecordFields(records, sample);

  if (result.record_fields.length) {
    const fieldTypes = {};
    let inspected = 0;
    for (const record of records) {
      if (!record || typeof record !== "object" || Array.isArray(record)) {
        continue;
      }
      for (const field of result.record_fields) {
        if (Object.hasOwn(record, field)) {
          if (!fieldTypes[field]) {
            fieldTypes[field] = new Set();
          }
          fieldTypes[field].add(typeName(record[field]));
        }
      }
      inspected += 1;
      if (inspected >= sample) {
        break;
      }
    }
    result.field_types = {};
    for (const [field, types] of Object.entries(fieldTypes)) {
      result.field_types[field] = [...types].sort();
    }
  }

  writeJson(result, values.compact);
}

main();
