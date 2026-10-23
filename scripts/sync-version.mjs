#!/usr/bin/env node
/** 把根目录 VERSION 写进 package.json 与 skill.json，保证单一真相源。 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const version = fs.readFileSync(path.join(root, "VERSION"), "utf8").trim();

if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(version)) {
  console.error(`VERSION 不是合法 semver：${version}`);
  process.exit(1);
}

for (const file of ["package.json", "skill.json"]) {
  const target = path.join(root, file);
  const data = JSON.parse(fs.readFileSync(target, "utf8"));
  data.version = version;
  fs.writeFileSync(target, JSON.stringify(data, null, 2) + "\n");
  console.log(`${file} → ${version}`);
}
