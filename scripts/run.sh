#!/usr/bin/env bash
# macOS / Linux 入口：CLI 只需要 requests；worker 的依赖由 video_note.py 按平台追加。
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="${VIDEO_NOTE_UV:-${DOUYIN_NOTE_UV:-}}"
if [ -z "$UV_BIN" ]; then
  UV_BIN="$(command -v uv || true)"
fi
if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
fi
if [ -z "$UV_BIN" ] && [ -x "$HOME/.cargo/bin/uv" ]; then
  UV_BIN="$HOME/.cargo/bin/uv"
fi
if [ -z "$UV_BIN" ]; then
  echo "uv not found. Install uv first: https://docs.astral.sh/uv/" >&2
  echo "  macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

export VIDEO_NOTE_UV="$UV_BIN"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

exec "$UV_BIN" run --python 3.12 \
  --with requests \
  -- python "$SKILL_DIR/scripts/video_note.py" "$@"
