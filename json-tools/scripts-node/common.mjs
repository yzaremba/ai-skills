#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs";

const PATH_TOKEN_RE = /([^.\[\]]+)|(\[(\*|\d+)\])/g;

function readStdin() {
  return fs.readFileSync(0, "utf-8");
}

function pyScalarString(value) {
  if (value === null) {
    return "None";
  }
  if (value === true) {
    return "True";
  }
  if (value === false) {
    return "False";
  }
  return String(value);
}

export function loadJson(path) {
  const text = !path || path === "-" ? readStdin() : fs.readFileSync(path, "utf-8");
  return JSON.parse(text);
}

function stableSortKeys(value) {
  if (Array.isArray(value)) {
    return value.map(stableSortKeys);
  }
  if (value && typeof value === "object") {
    const out = {};
    for (const key of Object.keys(value).sort()) {
      out[key] = stableSortKeys(value[key]);
    }
    return out;
  }
  return value;
}

export function writeJsonStable(data, compact = false) {
  const prepared = stableSortKeys(data);
  if (compact) {
    process.stdout.write(`${JSON.stringify(prepared)}\n`);
    return;
  }
  process.stdout.write(`${JSON.stringify(prepared, null, 2)}\n`);
}

export function writeJson(data, compact = false) {
  writeJsonStable(data, compact);
}

export function parsePath(path) {
  if (!path) {
    return [];
  }
  const tokens = [];
  for (const match of path.matchAll(PATH_TOKEN_RE)) {
    const key = match[1];
    const bracketToken = match[3];
    if (key !== undefined) {
      tokens.push(key);
    } else if (bracketToken !== undefined) {
      if (bracketToken === "*") {
        tokens.push("*");
      } else {
        tokens.push(Number.parseInt(bracketToken, 10));
      }
    }
  }
  return tokens;
}

export function extractValues(data, path) {
  const tokens = parsePath(path);
  if (!tokens.length) {
    return [data];
  }
  let values = [data];
  for (const token of tokens) {
    const nextValues = [];
    for (const item of values) {
      if (token === "*") {
        if (Array.isArray(item)) {
          nextValues.push(...item);
        } else if (item && typeof item === "object") {
          nextValues.push(...Object.values(item));
        }
      } else if (Number.isInteger(token)) {
        if (Array.isArray(item) && token >= -item.length && token < item.length) {
          nextValues.push(item[token]);
        }
      } else if (item && typeof item === "object" && Object.hasOwn(item, token)) {
        nextValues.push(item[token]);
      }
    }
    values = nextValues;
  }
  return values;
}

export function existsPath(data, path) {
  return extractValues(data, path).length > 0;
}

export function firstValue(data, path, defaultValue = null) {
  const values = extractValues(data, path);
  return values.length ? values[0] : defaultValue;
}

export function resolveArray(data, arrayPath) {
  if (arrayPath) {
    const values = extractValues(data, arrayPath);
    for (const value of values) {
      if (Array.isArray(value)) {
        return value;
      }
    }
    // Fallback: treat object-of-objects as an array of its values.
    for (const value of values) {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        return Object.values(value);
      }
    }
    return [];
  }
  if (Array.isArray(data)) {
    return data;
  }
  return [];
}

export function flattenJson(data, separator = ".", arrayMode = "index") {
  const output = {};

  function walk(value, prefix) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      if (!Object.keys(value).length && prefix) {
        output[prefix] = {};
        return;
      }
      for (const [key, inner] of Object.entries(value)) {
        const nextPrefix = prefix ? `${prefix}${separator}${key}` : key;
        walk(inner, nextPrefix);
      }
      return;
    }

    if (Array.isArray(value)) {
      if (arrayMode === "ignore") {
        output[prefix] = value;
        return;
      }
      if (arrayMode === "expand") {
        const allScalars = value.every((item) => !(item && typeof item === "object"));
        if (allScalars) {
          output[prefix] = value;
          return;
        }
      }
      value.forEach((inner, idx) => {
        const nextPrefix = arrayMode === "expand" ? prefix : (prefix ? `${prefix}[${idx}]` : `[${idx}]`);
        walk(inner, nextPrefix);
      });
      if (!value.length && prefix) {
        output[prefix] = [];
      }
      return;
    }

    output[prefix] = value;
  }

  walk(data, "");
  return output;
}

export function typeName(value) {
  if (value === null) {
    return "null";
  }
  if (typeof value === "boolean") {
    return "bool";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? "int" : "float";
  }
  if (typeof value === "string") {
    return "string";
  }
  if (Array.isArray(value)) {
    return "array";
  }
  if (value && typeof value === "object") {
    return "object";
  }
  return typeof value;
}

export function uniqueTypes(values) {
  return [...new Set(values.map(typeName))].sort();
}

export function frequency(values) {
  const counts = new Map();
  for (const value of values) {
    const normalized = value && typeof value === "object"
      ? JSON.stringify(stableSortKeys(value))
      : pyScalarString(value);
    counts.set(normalized, (counts.get(normalized) ?? 0) + 1);
  }
  return counts;
}

export function parseLiteral(value) {
  const candidate = value.trim();
  const lowered = candidate.toLowerCase();
  if (lowered === "null") {
    return null;
  }
  if (lowered === "true") {
    return true;
  }
  if (lowered === "false") {
    return false;
  }
  try {
    return JSON.parse(candidate);
  } catch {
    return candidate;
  }
}
