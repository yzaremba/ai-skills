#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { loadJson, typeName, writeJson } from "./common.mjs";

function normalizeForSet(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => [k, normalizeForSet(v)]);
  }
  if (Array.isArray(value)) {
    return value.map(normalizeForSet);
  }
  return value;
}

function diffValues(left, right, path, changes, ignoreOrder) {
  if (typeof left !== typeof right || Array.isArray(left) !== Array.isArray(right) || (left === null) !== (right === null)) {
    changes.push({
      path: path || "$",
      kind: "type_change",
      left_type: typeName(left),
      right_type: typeName(right),
      left,
      right,
    });
    return;
  }

  if (left && typeof left === "object" && !Array.isArray(left)) {
    const leftKeys = new Set(Object.keys(left));
    const rightKeys = new Set(Object.keys(right));

    for (const key of [...leftKeys].filter((k) => !rightKeys.has(k)).sort()) {
      changes.push({ path: path ? `${path}.${key}` : key, kind: "removed", left: left[key] });
    }
    for (const key of [...rightKeys].filter((k) => !leftKeys.has(k)).sort()) {
      changes.push({ path: path ? `${path}.${key}` : key, kind: "added", right: right[key] });
    }
    for (const key of [...leftKeys].filter((k) => rightKeys.has(k)).sort()) {
      const childPath = path ? `${path}.${key}` : key;
      diffValues(left[key], right[key], childPath, changes, ignoreOrder);
    }
    return;
  }

  if (Array.isArray(left)) {
    if (ignoreOrder) {
      const leftSet = new Set(left.map((item) => JSON.stringify(normalizeForSet(item))));
      const rightSet = new Set(right.map((item) => JSON.stringify(normalizeForSet(item))));
      const sameSize = leftSet.size === rightSet.size;
      const sameValues = [...leftSet].every((item) => rightSet.has(item));
      if (!sameSize || !sameValues) {
        changes.push({ path: path || "$", kind: "array_set_change", left, right });
      }
      return;
    }

    const minLen = Math.min(left.length, right.length);
    for (let idx = 0; idx < minLen; idx += 1) {
      diffValues(left[idx], right[idx], path ? `${path}[${idx}]` : `[${idx}]`, changes, ignoreOrder);
    }
    if (left.length > right.length) {
      for (let idx = minLen; idx < left.length; idx += 1) {
        changes.push({ path: path ? `${path}[${idx}]` : `[${idx}]`, kind: "removed", left: left[idx] });
      }
    } else if (right.length > left.length) {
      for (let idx = minLen; idx < right.length; idx += 1) {
        changes.push({ path: path ? `${path}[${idx}]` : `[${idx}]`, kind: "added", right: right[idx] });
      }
    }
    return;
  }

  if (left !== right) {
    changes.push({ path: path || "$", kind: "changed", left, right });
  }
}

function toText(changes) {
  if (!changes.length) {
    return "No differences.\n";
  }
  const lines = [];
  for (const change of changes) {
    const kind = change.kind;
    const path = change.path;
    if (kind === "added") {
      lines.push(`+ ${path}: ${JSON.stringify(change.right)}`);
    } else if (kind === "removed") {
      lines.push(`- ${path}: ${JSON.stringify(change.left)}`);
    } else if (kind === "type_change") {
      lines.push(`~ ${path}: type ${change.left_type} -> ${change.right_type} (left=${JSON.stringify(change.left)}, right=${JSON.stringify(change.right)})`);
    } else {
      lines.push(`~ ${path}: ${JSON.stringify(change.left)} -> ${JSON.stringify(change.right)}`);
    }
  }
  return `${lines.join("\n")}\n`;
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "ignore-order": { type: "boolean", default: false },
      format: { type: "string", default: "json" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  if (positionals.length < 2) {
    throw new Error("Two input files are required: left and right.");
  }
  if (!["json", "text"].includes(values.format)) {
    throw new Error("--format must be one of: json, text");
  }

  const left = loadJson(positionals[0]);
  const right = loadJson(positionals[1]);
  const changes = [];
  diffValues(left, right, "", changes, values["ignore-order"]);

  if (values.format === "text") {
    process.stdout.write(toText(changes));
  } else {
    writeJson({ change_count: changes.length, changes }, values.compact);
  }
}

main();
