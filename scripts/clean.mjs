#!/usr/bin/env node
/** 打包前清掉本地缓存，避免把 __pycache__ / .pytest_cache 发到 npm。 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const TARGETS = new Set(["__pycache__", ".pytest_cache"]);

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === ".git" || entry.name === "node_modules") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (TARGETS.has(entry.name)) {
        fs.rmSync(full, { recursive: true, force: true });
        console.log(`removed ${path.relative(root, full)}`);
      } else {
        walk(full);
      }
    } else if (entry.name.endsWith(".pyc")) {
      fs.rmSync(full, { force: true });
    }
  }
}

walk(root);
