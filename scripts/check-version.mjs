#!/usr/bin/env node
/** 发布前校验：VERSION / package.json / skill.json 三者一致。 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (file) => JSON.parse(fs.readFileSync(path.join(root, file), "utf8")).version;
const version = fs.readFileSync(path.join(root, "VERSION"), "utf8").trim();
const pkg = read("package.json");
const skill = read("skill.json");

const problems = [];
if (pkg !== version) problems.push(`package.json=${pkg}`);
if (skill !== version) problems.push(`skill.json=${skill}`);
if (problems.length) {
  console.error(`版本不一致：VERSION=${version}，${problems.join("，")}`);
  console.error("先运行 npm run sync-version");
  process.exit(1);
}
console.log(`版本一致：v${version}`);
