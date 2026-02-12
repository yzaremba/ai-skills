#!/usr/bin/env node
// Copyright 2026 Yevgeniy Zaremba
// SPDX-License-Identifier: Apache-2.0

import { parseArgs } from "node:util";
import { flattenJson, loadJson, resolveArray, writeJson } from "./common.mjs";

function main() {
  const { values, positionals } = parseArgs({
    options: {
      "array-path": { type: "string" },
      separator: { type: "string", default: "." },
      "array-mode": { type: "string", default: "index" },
      compact: { type: "boolean", default: false },
    },
    allowPositionals: true,
  });

  if (!["index", "ignore", "expand"].includes(values["array-mode"])) {
    throw new Error("--array-mode must be one of: index, ignore, expand");
  }

  const input = positionals[0] ?? "-";
  const data = loadJson(input);

  let target;
  if (values["array-path"]) {
    target = resolveArray(data, values["array-path"]);
    if (!target.length) {
      target = data;
    }
  } else {
    target = data;
  }

  const result = Array.isArray(target)
    ? target.map((item) => flattenJson(item, values.separator, values["array-mode"]))
    : flattenJson(target, values.separator, values["array-mode"]);
  writeJson(result, values.compact);
}

main();
