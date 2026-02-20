#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import fs from "node:fs";

export const DEFAULT_ENCODING = "utf-8";

function readStdin(encoding = DEFAULT_ENCODING) {
  return fs.readFileSync(0, encoding);
}

export function readText(path, encoding = DEFAULT_ENCODING) {
  if (!path || path === "-") {
    return readStdin(encoding);
  }
  return fs.readFileSync(path, encoding);
}

export function linesFilterComment(lines, commentChar) {
  if (!commentChar) return lines;
  const out = [];
  for (const line of lines) {
    const s = line.trim();
    if (s && s.startsWith(commentChar)) continue;
    out.push(line);
  }
  return out;
}

function isBlankRow(row) {
  return row.every((c) => !(c || "").trim());
}

/**
 * Parse CSV text into array of rows (each row = array of strings).
 * Handles RFC 4180: quoted fields, "" escape, newlines inside quotes.
 */
export function parseCsv(text, delimiter) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  const len = text.length;
  let i = 0;

  while (i < len) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (i + 1 < len && text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
      i += 1;
      continue;
    }
    if (c === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (c === delimiter) {
      row.push(field);
      field = "";
      i += 1;
      continue;
    }
    if (c === "\n" || c === "\r") {
      if (c === "\r" && i + 1 < len && text[i + 1] === "\n") i += 1;
      row.push(field);
      field = "";
      rows.push(row);
      row = [];
      i += 1;
      continue;
    }
    field += c;
    i += 1;
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function findHeaderRow(rowsList, minSameCount = 2) {
  const nonBlank = rowsList.filter((r) => !isBlankRow(r));
  if (!nonBlank.length) return 0;
  const countFreq = new Map();
  for (const r of nonBlank) {
    const n = r.length;
    countFreq.set(n, (countFreq.get(n) ?? 0) + 1);
  }
  const sorted = [...countFreq.entries()].sort((a, b) => b[1] - a[1]);
  let best = null;
  for (const [count, freq] of sorted) {
    if (freq >= minSameCount) {
      best = count;
      break;
    }
  }
  if (best == null) best = sorted[0][0];
  for (let i = 0; i < rowsList.length; i++) {
    if (rowsList[i].length === best) return i;
  }
  return 0;
}

export function parseDelimiter(s) {
  if (s === "\\t" || s === "tab") return "\t";
  return s;
}

/**
 * Detect delimiter by trying , \t ; and picking the one with most stable column count.
 */
export function detectDelimiter(lines, commentChar) {
  const candidates = [",", "\t", ";"];
  const filtered = linesFilterComment(lines, commentChar);
  if (!filtered.length) return ",";

  let bestDelim = ",";
  let bestScore = -1;

  for (const delim of candidates) {
    const counts = [];
    for (let i = 0; i < Math.min(30, filtered.length); i++) {
      const line = filtered[i];
      if (!line.trim()) continue;
      const rows = parseCsv(line + "\n", delim);
      if (rows.length && rows[0].length) counts.push(rows[0].length);
    }
    if (!counts.length) continue;
    const freq = new Map();
    for (const c of counts) freq.set(c, (freq.get(c) ?? 0) + 1);
    const mode = [...freq.entries()].sort((a, b) => b[1] - a[1])[0];
    const score = mode[1] * (mode[0] > 1 ? mode[0] : 0);
    if (score > bestScore) {
      bestScore = score;
      bestDelim = delim;
    }
  }
  return bestDelim;
}

export function loadCsv(path, options = {}) {
  const {
    delimiter = ",",
    hasHeader = true,
    commentChar = null,
    encoding = DEFAULT_ENCODING,
    textOverride = null,
    skipLines = null,
  } = options;

  const text = textOverride != null ? textOverride : readText(path, encoding);
  let content = text.startsWith("\ufeff") ? text.slice(1) : text;
  let lines = content.split(/\r?\n/);
  if (!lines.length) return { columns: [], rows: [], headerRow: 0 };

  lines = linesFilterComment(lines, commentChar);
  if (!lines.length) return { columns: [], rows: [], headerRow: 0 };

  while (lines.length && !lines[0].trim()) lines = lines.slice(1);
  if (!lines.length) return { columns: [], rows: [], headerRow: 0 };

  if (skipLines != null && skipLines > 0) {
    lines = lines.slice(skipLines);
  }
  if (!lines.length) return { columns: [], rows: [], headerRow: 0 };

  const textToParse = lines.join("\n") + (lines[lines.length - 1].endsWith("\n") ? "" : "\n");
  let rowsList = parseCsv(textToParse, delimiter);
  if (!rowsList.length) return { columns: [], rows: [], headerRow: 0 };

  while (rowsList.length && isBlankRow(rowsList[0])) rowsList = rowsList.slice(1);
  if (!rowsList.length) return { columns: [], rows: [], headerRow: 0 };

  let header;
  let dataRowsRaw;
  let headerRow1Based;

  if (hasHeader) {
    if (skipLines != null && skipLines > 0) {
      header = rowsList[0];
      dataRowsRaw = rowsList.slice(1);
      headerRow1Based = 1;
    } else {
      const headerIdx = findHeaderRow(rowsList);
      header = rowsList[headerIdx];
      dataRowsRaw = rowsList.slice(headerIdx + 1);
      headerRow1Based = headerIdx + 1;
    }
  } else {
    const ncols = rowsList[0]?.length ?? 0;
    header = Array.from({ length: ncols }, (_, i) => `col${i}`);
    dataRowsRaw = rowsList;
    headerRow1Based = 0;
  }

  const expectedLen = header.length;
  dataRowsRaw = dataRowsRaw.filter((r) => r.length === expectedLen);

  const rows = dataRowsRaw.map((r) => {
    const obj = {};
    for (let i = 0; i < header.length; i++) {
      obj[header[i]] = r[i] ?? "";
    }
    return obj;
  });

  return { columns: header, rows, headerRow: headerRow1Based };
}

export function writeCsv(columns, rows, delimiter = ",", stream = process.stdout) {
  const line = columns.join(delimiter) + "\n";
  stream.write(line);
  for (const row of rows) {
    const escaped = columns.map((col) => {
      let v = (row[col] ?? "").toString();
      if (v.includes('"') || v.includes("\n") || v.includes("\r") || v.includes(delimiter)) {
        v = '"' + v.replace(/"/g, '""') + '"';
      }
      return v;
    });
    stream.write(escaped.join(delimiter) + "\n");
  }
}

function sortKeys(obj) {
  if (obj === null || typeof obj !== "object") return obj;
  if (Array.isArray(obj)) return obj.map(sortKeys);
  const out = {};
  for (const k of Object.keys(obj).sort()) {
    out[k] = sortKeys(obj[k]);
  }
  return out;
}

export function writeJson(data, compact = false) {
  const prepared = sortKeys(data);
  if (compact) {
    process.stdout.write(JSON.stringify(prepared) + "\n");
  } else {
    process.stdout.write(JSON.stringify(prepared, null, 2) + "\n");
  }
}

export function sniffType(value) {
  const s = (value ?? "").toString().trim();
  if (!s) return "empty";
  const n = Number.parseFloat(s);
  if (!Number.isNaN(n) && s.trim() !== "") return "number";
  return "string";
}
