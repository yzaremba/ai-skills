#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import {
  DEFAULT_ENCODING,
  loadCsv,
  parseDelimiter,
  writeJson,
} from "./common.mjs";

function rowKey(row, keyColumns) {
  return keyColumns.map((c) => (row[c] ?? "").trim());
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      delimiter: { type: "string", default: "," },
      "no-header": { type: "boolean", default: false },
      "skip-lines": { type: "string" },
      "comment-char": { type: "string" },
      encoding: { type: "string", default: DEFAULT_ENCODING },
      key: { type: "string" },
      format: { type: "string", default: "json" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  const leftPath = positionals[0];
  const rightPath = positionals[1];
  if (!leftPath || !rightPath) {
    console.error("diff.mjs: requires left and right file paths");
    process.exit(1);
  }

  const dialect = {
    delimiter: parseDelimiter(values.delimiter),
    hasHeader: !values["no-header"],
    commentChar: values["comment-char"] ?? null,
    encoding: values.encoding,
    skipLines: values["skip-lines"] != null ? Number.parseInt(values["skip-lines"], 10) : null,
  };

  const { rows: leftRows } = loadCsv(leftPath, dialect);
  const { rows: rightRows } = loadCsv(rightPath, dialect);

  const keyCols = values.key ? values.key.split(",").map((c) => c.trim()) : null;
  const changes = [];

  if (keyCols && keyCols.length > 0) {
    const leftByKey = new Map();
    const rightByKey = new Map();
    for (const r of leftRows) leftByKey.set(JSON.stringify(rowKey(r, keyCols)), r);
    for (const r of rightRows) rightByKey.set(JSON.stringify(rowKey(r, keyCols)), r);

    const leftKeys = new Set(leftByKey.keys());
    const rightKeys = new Set(rightByKey.keys());

    for (const k of leftKeys) {
      if (!rightKeys.has(k)) {
        changes.push({ kind: "removed", key: JSON.parse(k), left: leftByKey.get(k) });
      }
    }
    for (const k of rightKeys) {
      if (!leftKeys.has(k)) {
        changes.push({ kind: "added", key: JSON.parse(k), right: rightByKey.get(k) });
      }
    }
    for (const k of leftKeys) {
      if (rightKeys.has(k)) {
        const lr = leftByKey.get(k);
        const rr = rightByKey.get(k);
        const lStr = JSON.stringify(lr);
        const rStr = JSON.stringify(rr);
        if (lStr !== rStr) {
          changes.push({ kind: "changed", key: JSON.parse(k), left: lr, right: rr });
        }
      }
    }
  } else {
    const maxLen = Math.max(leftRows.length, rightRows.length);
    for (let i = 0; i < maxLen; i++) {
      const lr = leftRows[i];
      const rr = rightRows[i];
      if (lr === undefined) {
        changes.push({ kind: "added", row_index: i, right: rr });
      } else if (rr === undefined) {
        changes.push({ kind: "removed", row_index: i, left: lr });
      } else if (JSON.stringify(lr) !== JSON.stringify(rr)) {
        changes.push({ kind: "changed", row_index: i, left: lr, right: rr });
      }
    }
  }

  if (values.format === "text") {
    if (changes.length === 0) {
      console.log("No differences.");
    } else {
      for (const c of changes) {
        const k = c.kind;
        const id = c.key ?? c.row_index;
        if (k === "removed") console.log(`- removed: ${JSON.stringify(id)} ${JSON.stringify(c.left ?? {})}`);
        else if (k === "added") console.log(`+ added: ${JSON.stringify(id)} ${JSON.stringify(c.right ?? {})}`);
        else console.log(`~ changed: ${JSON.stringify(id)}`);
      }
    }
    return;
  }

  writeJson({ change_count: changes.length, changes }, values.compact);
}

main();
