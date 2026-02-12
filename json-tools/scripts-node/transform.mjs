#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs";
import { parseArgs } from "node:util";
import { flattenJson, loadJson, resolveArray, writeJson } from "./common.mjs";

function parseColumns(raw) {
  if (!raw) {
    return [];
  }
  return raw.split(",").map((item) => item.trim()).filter(Boolean);
}

function csvEscape(value) {
  let text = "";
  if (value === true) {
    text = "True";
  } else if (value === false) {
    text = "False";
  } else if (value === null || value === undefined) {
    text = "";
  } else {
    text = String(value);
  }
  if (text.includes(",") || text.includes('"') || text.includes("\n")) {
    return `"${text.replaceAll('"', '""')}"`;
  }
  return text;
}

function jsonToCsv(data, columns) {
  const rows = Array.isArray(data) ? data : [data];
  const flattened = rows.map((row) => ((row && typeof row === "object")
    ? flattenJson(row)
    : { value: row }));

  let chosenColumns = columns;
  if (!chosenColumns.length) {
    const columnSet = new Set();
    for (const row of flattened) {
      for (const key of Object.keys(row)) {
        columnSet.add(key);
      }
    }
    chosenColumns = [...columnSet].sort();
  }

  const lines = [];
  lines.push(chosenColumns.map(csvEscape).join(","));
  for (const row of flattened) {
    lines.push(chosenColumns.map((col) => csvEscape(row[col])).join(","));
  }
  return `${lines.join("\r\n")}\r\n`;
}

function jsonWithSpaces(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => jsonWithSpaces(item)).join(", ")}]`;
  }
  return `{${Object.entries(value)
    .map(([key, val]) => `${JSON.stringify(key)}: ${jsonWithSpaces(val)}`)
    .join(", ")}}`;
}

function jsonToJsonl(data) {
  const rows = Array.isArray(data) ? data : [data];
  return `${rows.map((row) => jsonWithSpaces(row)).join("\n")}\n`;
}

function parseCsvLine(line) {
  const out = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        current += ch;
      }
    } else if (ch === ",") {
      out.push(current);
      current = "";
    } else if (ch === '"') {
      inQuotes = true;
    } else {
      current += ch;
    }
  }
  out.push(current);
  return out;
}

function csvToJson(path) {
  const text = !path || path === "-" ? fs.readFileSync(0, "utf-8") : fs.readFileSync(path, "utf-8");
  const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
  if (!lines.length) {
    return [];
  }
  const headers = parseCsvLine(lines[0]);
  const rows = [];
  for (const line of lines.slice(1)) {
    const values = parseCsvLine(line);
    const row = {};
    headers.forEach((header, idx) => {
      row[header] = values[idx] ?? "";
    });
    rows.push(row);
  }
  return rows;
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      to: { type: "string" },
      "from-format": { type: "string" },
      "array-path": { type: "string" },
      columns: { type: "string" },
    },
    allowPositionals: true,
  });

  if (values.to && !["csv", "jsonl"].includes(values.to)) {
    throw new Error("--to must be csv or jsonl");
  }
  if (values["from-format"] && values["from-format"] !== "csv") {
    throw new Error("--from-format currently supports only csv");
  }

  const input = positionals[0] ?? "-";
  const columns = parseColumns(values.columns);

  if (values["from-format"] === "csv") {
    const result = csvToJson(input);
    writeJson(result);
    return;
  }

  let data = loadJson(input);
  if (values["array-path"]) {
    const extracted = resolveArray(data, values["array-path"]);
    data = extracted.length ? extracted : data;
  }

  if (values.to === "csv") {
    process.stdout.write(jsonToCsv(data, columns));
  } else if (values.to === "jsonl") {
    process.stdout.write(jsonToJsonl(data));
  } else {
    writeJson(data);
  }
}

main();
