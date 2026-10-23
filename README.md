# 视频学习笔记 · video-learning-note

把 B 站、抖音上的视频，变成一篇能看懂的 Obsidian 笔记。

你只管把链接发给 AI，剩下的它自己做：下载声音 → 在你自己电脑上转成文字 → 整理成笔记 → 存进 Obsidian。

```
视频链接  →  AI 技能  →  下载音轨  →  本地转写  →  整理成笔记  →  写入 Obsidian
```

## 它能帮你做什么

你看到一条不错的视频，比如「30 分钟讲透 RAG」，但不想反复拖进度条。把链接发给 AI，几分钟后 Obsidian 里会多出一篇这样的笔记：

- **一句话总结**：这条视频到底讲了什么
- **思维导图**：一眼看清结构
- **详细梳理**：按逻辑重新组织，不是流水账
- **面试题模式**：如果视频在讲面试题，自动整理成「考察点 / 回答框架 / 口述回答 / 补充标准答案」
- **可行动项**：看完能马上做什么
- **原视频链接**：随时回去核对

支持 **B 站**和**抖音**。B 站不需要登录，抖音需要把浏览器短暂弹出来一次。

## 安装

两种方式，选一种就行。**推荐方式一**，最省事。

### 方式一：一条命令

前提：电脑上装了 [Node.js](https://nodejs.org/zh-cn)（选 LTS 版本，一路「下一步」即可）。

打开终端（Windows 用 PowerShell），粘贴这一行回车：

```bash
npx video-learning-note install
```

看到「已安装到 …」就成功了。它会自动找你电脑上的 AI 工具（Claude Code、Codex、DSH 等），把技能放进去，不用你手动找目录。

### 方式二：把下面这段直接发给你的 AI

打开你的 AI 工具，把下面整段话复制粘贴过去，发出去：

```text
请帮我安装 video-learning-note 这个技能，它能把 B 站/抖音视频整理成 Obsidian 笔记。

步骤：
1. 在终端运行：npx video-learning-note@latest install
2. 运行：npx video-learning-note doctor，把输出贴给我
3. 如果提示缺 uv 或 ffmpeg，帮我装好（macOS 用 brew，Windows 用 winget）
4. 装完告诉我：技能装到了哪个目录，以及我还需要做什么

注意：不要让我手动复制文件夹，直接用命令安装。
```

AI 会自己执行命令。如果它问「要不要安装依赖」，选「是」。

## 第一次使用

1. 确认桌面上有一个叫 `Note` 的文件夹（Obsidian 的库，默认路径是「桌面 / Note」）。
2. 在 AI 里发一条消息，把链接带上：

```text
把这条视频整理成笔记：https://www.bilibili.com/video/BVxxxxxxxxxx
```

3. 等它说「已写入」，然后去 Obsidian 里看。默认位置是 `Note / 学习 / 视频笔记`。

你也可以直接说：

- 「整理成面试题」
- 「存到 `学习/AI` 目录下」
- 「这条我已经记过了，重新整理一遍」

## 你的电脑上发生了什么

- **B 站**：读取公开的视频信息和字幕；有字幕就直接用，没有才下载音轨在本地转写。
- **抖音**：用你自己的浏览器打开视频页面（会短暂弹出一个窗口，正常现象），拿到音轨后在本地转写。
- **不登录**、**不上传**、**不把音频发给任何在线服务**。
- 第一次运行会下载一次语音模型（约 1–3 GB），之后可以离线使用。

## 常见问题

**需要提前装什么？**
Node.js 必须有；Python、uv、ffmpeg 这些 AI 会帮你装。装不上就让它跑 `npx video-learning-note doctor`，它会告诉你缺什么。

**抖音一直失败？**
抖音要求大陆网络。关掉 VPN 再试。如果弹出验证码，在弹出的浏览器窗口里手动过一次，之后会记住。

**转写很慢？**
第一次要下载模型，慢是正常的。之后一条 15 分钟的视频，Mac 大约几分钟，普通 Windows 电脑会更久一些。

**笔记没出现在 Obsidian 里？**
先看 AI 的回复里有没有「已写入」和路径。没有就让它运行 `scripts/run.sh doctor`（Windows 是 `run.ps1`），按提示补齐环境。

**能改笔记格式吗？**
可以。AI 生成笔记时读的是 `references/note-template.md`，改这个文件就能改结构。

**支持其他平台吗？**
目前是 B 站和抖音。结构上留给新平台的位置很清楚，见下面「给折腾的人」。

## 给折腾的人

**目录结构**

```text
SKILL.md                 技能说明（AI 读这个）
skill.json               元信息（名称、版本、平台）
VERSION                  版本号唯一真相源
scripts/video_note.py    CLI：start / wait / commit / probe / doctor
scripts/platforms/       平台适配器：bilibili.py / douyin.py
references/              笔记模板、ASR 纠错表
bin/video-note.mjs       npm 安装器
```

**常用命令**

```bash
python3 scripts/video_note.py platforms          # 当前支持的平台
python3 scripts/video_note.py probe --url <链接>  # 只取元信息，不下载
python3 scripts/video_note.py doctor             # 环境自检
```

**加一个平台**

在 `scripts/platforms/` 下新建一个模块，实现 `KEY`、`LABEL`、`match(url)`、`source_id(url, config)`、`capture(config, manifest, path)`，然后在 `scripts/platforms/__init__.py` 的 `ADAPTERS` 里登记。主流程不用改。

**版本管理**

版本号只写在 `VERSION` 文件里：

```bash
echo 1.0.1 > VERSION
npm run sync-version     # 同步到 package.json 和 skill.json
npm test                 # Python 单测
git tag v1.0.1 && git push --tags
```

打 tag 会触发 GitHub Actions 发布到 npm，并生成 Release。

**许可证**

MIT
