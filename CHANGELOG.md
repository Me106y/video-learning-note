# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)：主版本号.次版本号.修订号。

## [1.0.0] - 2026-10-23

### 新增

- 首个正式版本：把 B 站 / 抖音视频整理成 Obsidian 学习笔记。
- 平台适配层：`scripts/platforms/`，新增平台只需一个模块。
- B 站：公开 API 取元信息，优先使用官方字幕，无字幕时下载 DASH 音轨本地转写，不需要浏览器和登录。
- 抖音：本机 Chrome / Edge 抓取播放流，持久化 profile 复用 Cookie。
- 笔记模式：面试题模式与普通学习模式，均含 Mermaid 思维导图。
- 本地转写：macOS 用 `mlx-whisper`，Windows / Linux 用 `faster-whisper`，不上传音视频。
- 自动查重、原子写库、写库后清理临时会话。
- npm 安装器 `video-note`：自动探测已存在的 Agent 技能目录。
- 版本管理：`VERSION` 为唯一真相源，`npm run sync-version` 同步，tag 触发发布。
