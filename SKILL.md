---
name: video-learning-note
description: 把 B 站、抖音等平台的视频整理成 Obsidian 学习笔记。用户发来视频链接或分享文案，要求总结、记笔记、整理成问答、做思维导图、取标题、存进 Obsidian 时使用。本地转写不上传音视频，B 站优先用官方字幕，抖音用本机浏览器抓取，支持面试题与学习两种笔记模式。
---

# 视频学习笔记

把一条公开视频整理成 Obsidian 笔记。默认写入共享配置里的 vault，用户可以在调用时覆盖 vault 或子目录。

## 支持的平台

| 平台 | 抓取方式 | 是否需要浏览器 | 是否需要登录 |
|---|---|---|---|
| B 站（bilibili.com / b23.tv 短链） | 公开 API：元信息 + 字幕 + DASH 音轨 | 不需要 | 不需要 |
| 抖音（douyin.com） | 本机 Chrome / Edge 抓取播放流 | 需要 | 不需要，但必须大陆网络 |

新增平台只在 `scripts/platforms/` 加一个模块，主流程不动。用 `platforms` 命令可以查看当前支持列表。

## 硬性规则

- 只用本 skill 的脚本抓取和转写，不要调用 `yt-dlp`，不要把视频或音频上传到在线 ASR / 第三方解析服务。
- 转写只在本机完成。B 站有字幕时直接用字幕，没有才做 ASR；抖音一律走 ASR。后端按平台自动选择：macOS 用 `mlx-whisper`，Windows / Linux 用 `faster-whisper`，可用 `asr_backend` 显式指定。
- 最终笔记只保留整理后的总结、问答和思维导图；**不要把完整逐字稿写进笔记**。
- 不要直接写 vault。先生成 `note.md`，再调用 `commit`，让脚本校验、查重、原子写入并清理临时目录。
- 写库成功后临时目录自动删除；失败时保留并返回 `session_dir`。
- 笔记默认使用简体中文，技术名词保留通用英文写法。
- 口述回答只基于视频内容；视频没讲到但标准答案需要的内容，写进单独的“补充标准答案”，并明确标记为非视频内容。

## 路径与配置

本 skill 目录是包含当前 `SKILL.md` 的目录。入口脚本按平台二选一，参数完全相同：

```bash
# macOS / Linux
"<SKILL_DIR>/scripts/run.sh" ...
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\run.ps1" ...
```

下文所有 `"<SKILL_DIR>/scripts/run.sh" ...` 示例，在 Windows 上就是把前缀换成 `run.ps1` 那行，其余参数（`start` / `wait` / `commit` / `probe` / `doctor` 及 `--input`、`--session` 等）一字不差。

共享配置默认位置：

```text
macOS / Linux: ~/.config/video-learning-note/config.json
Windows:       %APPDATA%\video-learning-note\config.json
```

关键配置（留空表示用平台默认值）：

```json
{
  "vault_path": "",
  "note_subdir": "学习/视频笔记",
  "asr_backend": "auto",
  "model": "mlx-community/whisper-large-v3-mlx",
  "faster_model": "large-v3",
  "faster_device": "auto",
  "faster_compute_type": "auto",
  "browser_channel": "auto",
  "browser_profile_dir": "",
  "headless": false,
  "proxy_url": "",
  "work_root": ""
}
```

平台默认值：

- `vault_path`：`<用户目录>/Desktop/Note`
- `work_root`：Windows `%LOCALAPPDATA%\video-learning-note\sessions`；macOS `~/Library/Caches/video-learning-note/sessions`；Linux `~/.cache/video-learning-note/sessions`
- `asr_backend`：`auto` = macOS 用 `mlx`，Windows / Linux 用 `faster`
- `faster_device` / `faster_compute_type`：`auto` 会在 CUDA 不可用时回退到 CPU + int8，通常不需要手改
- `browser_channel`：仅抖音需要。`auto` 自动探测系统浏览器；也可指定 `chrome` / `msedge` / `chromium` 或浏览器可执行文件绝对路径
- `browser_profile_dir`：留空则用缓存目录下的固定 profile，复用 Cookie，避免每次都触发验证码
- `headless`：默认 `false`。抖音对 headless + 全新 profile 会弹验证码，所以抓取用有头模式，抓取时会短暂弹出浏览器窗口

用户说“保存到某个目录”时，把路径作为 `--vault` 或 `--subdir` 传给 `start`。用户说“重新整理并覆盖”时传 `--force`。

## 工作流

1. 用户消息里通常包含分享文案和链接。原样传给 `start`：

```bash
"<SKILL_DIR>/scripts/run.sh" start --input "<用户原始消息>"
```

用户指定了目录就追加 `--vault "<vault>"` 或 `--subdir "<子目录>"`；要覆盖已有笔记就追加 `--force`。

2. 解析 `start` 输出的 JSON：

- `state == "duplicate"`：直接告诉用户已有笔记路径。只有用户明确要求覆盖时才加 `--force` 重跑。
- 否则记录 `session_id`，告诉用户后台已开始抓取和转写。

3. 轮询状态。优先用 `wait`，超时后再调用，不要高频轮询：

```bash
"<SKILL_DIR>/scripts/run.sh" wait --session "<session_id>" --timeout 150 --interval 10
```

返回 `timed_out: true` 或 `state == "running"` 时，给用户一句简短进度，然后继续等。B 站只需要下载音轨，通常比抖音快；转写耗时约为音频时长的 1–3 倍（`mlx-whisper` 接近 1 倍，纯 CPU 的 `faster-whisper` 更慢），首次运行还要算上下载模型的时间。

4. `state == "failed"`：把 `error.message` 和 `session_dir` 告诉用户并停止。不要写笔记。

5. `state == "ready"` 后，读取状态里的：

- `paths.metadata_json`
- `paths.transcript_segments_md`
- `paths.transcript_txt`

先读 [references/asr-glossary.md](references/asr-glossary.md)，结合视频标题、标签和上下文纠正明显的 ASR 同音词；平台自带字幕的（`transcription.backend == "subtitle"`）错误通常很少，只需要修术语。无法确定的词保留并标“待核实”。

6. 按 [references/note-template.md](references/note-template.md) 生成笔记：

- 自动判断是面试题模式还是普通学习模式；无法判断时按普通学习模式。
- 面试题模式：每题包含“考察点、回答框架、口述回答、补充标准答案、追问 / 易错点”。
- 口述回答写成 300–600 字的自然段，不要只写几句概括。
- 普通学习模式：包含“核心要点、详细梳理、可行动项 / 启发”。
- 两种模式都必须有 Mermaid `mindmap` 和来源链接。
- 保留题目时间戳，不写完整逐字稿。
- tags 至少包含 `视频笔记` 和平台名（`B站` / `抖音`），面试题再加 `面试题`，普通学习加 `学习`，再加 1–3 个内容主题标签。
- 标题由内容总结生成，面试题默认以 `面试题｜` 开头，普通学习默认以 `学习笔记｜` 开头；不要直接复用平台的点击诱饵标题。
- 把笔记写到 `paths.note_md` 指向的路径。

7. 写库：

```bash
"<SKILL_DIR>/scripts/run.sh" commit --session "<session_id>" --note "<paths.note_md>"
```

`commit` 会校验结构、检查重复、生成安全文件名、原子写入，并在成功后删除整个临时 session。

8. 把最终 `note_path` 返回给用户。如果 `commit` 返回 `duplicate`，返回已有笔记路径。

## 辅助命令

```bash
# 只取元信息，不下载、不转写（B 站可用；抖音需要浏览器，直接 start）
"<SKILL_DIR>/scripts/run.sh" probe --url "<视频链接>"

# 查看当前支持的平台
"<SKILL_DIR>/scripts/run.sh" platforms

# 环境自检
"<SKILL_DIR>/scripts/run.sh" doctor
```

## 环境与失败处理

- B 站不需要浏览器；抖音需要 Chrome / Edge / Chromium。脚本会按平台自动探测，一个都没有时把 `browser_channel` 设为 `chromium` 并执行 `uv run --with playwright playwright install chromium`。
- 转写依赖 `ffmpeg` 和 `uv`。没装 `uv` 时：Windows `winget install --id astral-sh.uv -e`，macOS / Linux `curl -LsSf https://astral.sh/uv/install.sh | sh`。
- worker 依赖由脚本按平台临时拉起（B 站不需要 playwright），首次运行会从镜像下载模型，之后走缓存。
- 网络必须能访问 `pypi.tuna.tsinghua.edu.cn` 和 `hf-mirror.com`；脚本默认已设置这两个镜像。
- **系统代理陷阱**：Windows 上 Python 的 requests 会自动继承系统 / IE 代理，如果那个代理转发不了外网，就会出现「curl 直连正常、Python 连接被重置」。脚本在 `proxy_url` 为空时强制直连，需要代理时把 `proxy_url` 配上即可。
- 抖音必须识别为大陆出口。若 worker 报 `GeoBlockedError`，让用户关闭 VPN 或配置大陆代理，然后重新调用。
- 只支持公开可访问的视频。登录、私密、付费或已删除的视频不要绕过权限，直接报告失败。
- B 站接口返回 `-404` 表示视频不存在或已删除；`-403` 表示视频仅限特定用户观看。这两种情况都不要重试。
- 不要清理 session 目录以外的文件。模型缓存保留，不删除。

## 快速自检

```bash
"<SKILL_DIR>/scripts/run.sh" doctor
```

`doctor` 会报告当前平台、版本、`asr_backend`、`uv`、`ffmpeg`、探测到的浏览器、vault 是否存在、模型缓存、以及 B 站 / 模型镜像的连通性。`warnings` 非空时先按提示补齐环境再重试。
