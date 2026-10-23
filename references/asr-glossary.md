# ASR 术语与纠错表

本机转写（`mlx-whisper` / `faster-whisper`）的中文结果可能出现同音词、英文术语和专有名词误识别。整理笔记时，结合视频标题、分区、UP 主、上下文和下面的术语表做**保守纠错**。

## 基本原则

1. 只改正上下文能明确判断的错误，不凭空补全听不清的内容。
2. 无法判断时保留原词，并在对应位置写“待核实”。
3. 技术名词优先使用行业通用写法，保留英文缩写与原大小写（`AGENTS.md`、`MCP`、`RAG`）。
4. 平台自带字幕（`transcription.backend == "subtitle"`）错误少，通常只需要统一术语；ASR 结果才需要逐段检查。
5. 纠错只影响整理后的笔记；不要在笔记里保留原始错字。

## 高频术语

- Agent / 智能体
- AGENTS.md / CLAUDE.md
- AI Coding、Cursor、Claude Code、Codex、Qoder
- MCP（模型上下文协议）、Skill、Subagent
- monorepo、CI/CD、lint、PR
- RAG（检索增强生成）、Embedding、Reranker、BM25、RRF
- LangChain、LangGraph、DeepSeek
- Session ID / 会话 ID、会话隔离、命名空间隔离
- 向量数据库、元数据过滤、乐观锁、事件溯源
- 沙箱、工具调用、上下文工程、Token 预算

## 已观测到的典型误识别

| ASR 输出 | 应理解为 |
|---|---|
| Redmi / Redmi MD / Ready MD | README / README.md |
| Agent10 / Agent S MD / Agents MD | AGENTS.md |
| CLAWD.md / Cloud.md | CLAUDE.md |
| CoderCoder / Cloud Code / CloseCode | Claude Code |
| Enthophic / Anthropic 音译 | Anthropic |
| mongrep / mono report / mono repo | monorepo |
| Gate 3 Module / 给的三毛豆 | Git Submodule |
| Backcase / back case | bad case（复盘用例） |
| 避还 / 避环 / 闭环还 | 闭环 |
| 私域组建 / 私有组建 | 私有组件 |
| 原码 | 源码 |
| 藏库 | 仓库 |
| 传口 | 窗口 |
| 權戰 / 全战 | 全栈 |
| 歉意成本 | 迁移成本 |
| 手册 / 手冊 / Redmi | README（文档语境下）或“手册” |
| 绘画 / 绘画 ID / 绘画隔离 | 会话 / 会话 ID / 会话隔离（仅在 Agent 语境成立） |
| 群职 | 隔离 |
| 采购 | 踩坑（“线上采购”这类语境） |
| 存储实力 | 存储实例 |
| 弹幕 | Demo（产品演示语境） |

注意：`绘画` 在美术、设计、图像生成语境下可能是正确词，不能无条件替换；`手册` 也可能是真的手册。必须先判断视频主题再改。
