#!/usr/bin/env node
/**
 * video-learning-note 的安装器。
 *
 * 它做的事只有一件：把技能文件放进各个 AI Agent 会读取的目录，
 * 让用户不用关心 `~/.claude/skills` 这类路径。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = path.resolve(__dirname, "..");
const SKILL_NAME = "video-learning-note";
const VERSION = readVersion();

const SKIP_NAMES = new Set([
  ".git",
  "node_modules",
  ".github",
  "tests",
  "dist",
  ".pytest_cache",
  "__pycache__",
  ".DS_Store",
  ".gitignore",
  ".gitattributes",
  "package-lock.json",
]);

function readVersion() {
  try {
    return fs.readFileSync(path.join(PKG_ROOT, "VERSION"), "utf8").trim();
  } catch {
    return JSON.parse(fs.readFileSync(path.join(PKG_ROOT, "package.json"), "utf8")).version;
  }
}

function skillRoots() {
  const home = os.homedir();
  // 只装到「已经存在」的目录，避免在你机器上凭空造出一堆空文件夹。
  const candidates = [
    path.join(home, ".agents", "skills"),
    path.join(home, ".claude", "skills"),
    path.join(home, ".codex", "skills"),
    path.join(home, ".dsh", "skills"),
    path.join(home, ".qoder", "skills"),
    path.join(home, ".config", "agents", "skills"),
  ];
  return candidates.filter((dir) => fs.existsSync(dir));
}

function copyRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (SKIP_NAMES.has(entry.name)) continue;
    const from = path.join(src, entry.name);
    const to = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyRecursive(from, to);
    } else if (entry.isFile()) {
      fs.copyFileSync(from, to);
      if (entry.name.endsWith(".sh")) fs.chmodSync(to, 0o755);
    }
  }
}

function installInto(root) {
  const target = path.join(root, SKILL_NAME);
  fs.rmSync(target, { recursive: true, force: true });
  copyRecursive(PKG_ROOT, target);
  return target;
}

function cmdInstall(args) {
  const explicit = args.find((value) => !value.startsWith("--"));
  let roots = [];
  if (explicit) {
    roots = [path.resolve(explicit.replace(/^~(?=$|\/|\\)/, os.homedir()))];
  } else {
    roots = skillRoots();
    if (roots.length === 0) {
      // 一台全新的机器：装到通用目录，Claude Code / Codex 等也认这个位置。
      roots = [path.join(os.homedir(), ".agents", "skills")];
    }
  }

  const installed = [];
  for (const root of roots) {
    fs.mkdirSync(root, { recursive: true });
    installed.push(installInto(root));
  }

  const silent = args.includes("--silent");
  if (!silent) {
    console.log(`video-learning-note v${VERSION} 已安装到：`);
    for (const dir of installed) console.log(`  ${dir}`);
    console.log("");
    console.log("接下来在 AI 里直接发视频链接就行，例如：");
    console.log('  「把这个视频整理成笔记：https://www.bilibili.com/video/BVxxxxxxxxxx」');
    console.log("");
    console.log("第一次使用前建议自检：");
    console.log(`  python3 "${path.join(installed[0], "scripts", "video_note.py")}" doctor`);
  }
  return 0;
}

function cmdUninstall() {
  const home = os.homedir();
  const roots = [
    ...skillRoots(),
    path.join(home, ".agents", "skills"),
  ];
  const seen = new Set();
  let removed = 0;
  for (const root of roots) {
    const target = path.join(root, SKILL_NAME);
    if (seen.has(target) || !fs.existsSync(target)) continue;
    seen.add(target);
    fs.rmSync(target, { recursive: true, force: true });
    console.log(`已删除 ${target}`);
    removed += 1;
  }
  if (removed === 0) console.log("没有找到已安装的 video-learning-note。");
  return 0;
}

function cmdDoctor() {
  const checks = [
    ["node", () => process.version],
    ["python3", () => execFileSync("python3", ["--version"], { encoding: "utf8" }).trim()],
    ["uv", () => execFileSync("uv", ["--version"], { encoding: "utf8" }).trim()],
    ["ffmpeg", () => execFileSync("ffmpeg", ["-version"], { encoding: "utf8" }).split("\n")[0]],
  ];
  console.log(`video-learning-note v${VERSION}`);
  for (const [name, run] of checks) {
    try {
      console.log(`  ✓ ${name}: ${run()}`);
    } catch {
      console.log(`  ✗ ${name}: 未安装`);
    }
  }
  const roots = skillRoots();
  console.log("  已探测到的技能目录：");
  if (roots.length === 0) console.log("    （没有，安装时会默认创建 ~/.agents/skills）");
  for (const root of roots) {
    const target = path.join(root, SKILL_NAME);
    console.log(`    ${fs.existsSync(target) ? "✓" : "·"} ${target}`);
  }
  return 0;
}

function usage() {
  console.log(`video-learning-note v${VERSION}

用法：
  video-note install [目标目录]   安装到所有已存在的 Agent 技能目录
  video-note uninstall           从这些目录里删除
  video-note doctor              检查依赖与安装位置
  video-note version             显示版本

示例：
  npx video-learning-note install
  npx video-learning-note install ~/.claude/skills`);
}

const [command, ...rest] = process.argv.slice(2);
switch (command) {
  case "install":
    process.exit(cmdInstall(rest));
    break;
  case "uninstall":
    process.exit(cmdUninstall());
    break;
  case "doctor":
    process.exit(cmdDoctor());
    break;
  case "version":
  case "--version":
  case "-v":
    console.log(VERSION);
    break;
  case undefined:
  case "help":
  case "--help":
  case "-h":
    usage();
    break;
  default:
    console.error(`未知命令：${command}`);
    usage();
    process.exit(1);
}
