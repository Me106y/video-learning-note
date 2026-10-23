#!/usr/bin/env python3
"""video-learning-note 的 CLI 主体。

职责边界：
- 本文件负责配置、会话状态、CLI、笔记校验与写库；
- 平台相关的抓取逻辑全部在 scripts/platforms/ 下，新增平台不改本文件。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import platforms  # noqa: E402
from platforms.base import (  # noqa: E402
    CommitError,
    SkillError,
    TranscriptionError,
    apply_network_env,
    atomic_write_json,
    atomic_write_text,
    deep_merge,
    find_ffmpeg,
    format_seconds,
    now_iso,
    read_json,
)

APP_NAME = "video-learning-note"
LEGACY_APP_NAME = "douyin-learning-note"
URL_RE = re.compile(r"https?://[^\s]+")


def _load_version() -> str:
    """版本号唯一真相源是仓库根目录的 VERSION 文件；装进技能目录后同样带过去。"""
    for candidate in (
        Path(__file__).resolve().parent.parent / "VERSION",
        Path(__file__).resolve().parent / "VERSION",
    ):
        try:
            text = candidate.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", text):
            return text
    return "0.0.0"


VERSION = _load_version()


def env_value(name: str) -> Optional[str]:
    """优先读 VIDEO_NOTE_<name>，回退到旧前缀 DOUYIN_NOTE_<name>。"""
    for prefix in ("VIDEO_NOTE_", "DOUYIN_NOTE_"):
        value = os.environ.get(prefix + name)
        if value:
            return value
    return None


def default_work_root() -> str:
    plat = platforms.base.current_platform()
    if plat == "windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return str(Path(base) / APP_NAME / "sessions")
    if plat == "macos":
        return f"~/Library/Caches/{APP_NAME}/sessions"
    base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return str(Path(base).expanduser() / APP_NAME / "sessions")


def default_vault_path() -> str:
    return str(Path.home() / "Desktop" / "Note")


DEFAULT_CONFIG: Dict[str, Any] = {
    "vault_path": default_vault_path(),
    "note_subdir": "学习/视频笔记",
    "asr_backend": "auto",
    "model": "mlx-community/whisper-large-v3-mlx",
    "faster_model": "large-v3",
    "faster_device": "auto",
    "faster_compute_type": "auto",
    "faster_vad_filter": True,
    "language": "zh",
    "word_timestamps": False,
    "include_timestamps": True,
    "note_mode": "auto",
    "pypi_index": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "hf_endpoint": "https://hf-mirror.com",
    "browser_channel": "auto",
    "browser_profile_dir": "",
    "user_agent": "",
    "headless": False,
    "proxy_url": "",
    "keep_temp_on_failure": True,
    "work_root": default_work_root(),
    "max_duration_minutes": 0,
    "download_timeout_seconds": 120,
    "transcription_estimate_factor": 3.0,
}


def config_path() -> Path:
    override = env_value("CONFIG")
    if override:
        return Path(override).expanduser()
    if platforms.base.current_platform() == "windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        primary = Path(base) / APP_NAME / "config.json"
        legacy = Path(base) / LEGACY_APP_NAME / "config.json"
    else:
        primary = Path.home() / ".config" / APP_NAME / "config.json"
        legacy = Path.home() / ".config" / LEGACY_APP_NAME / "config.json"
    if not primary.exists() and legacy.exists():
        return legacy
    return primary


def load_config() -> Dict[str, Any]:
    path = config_path()
    if not path.exists():
        atomic_write_json(path, DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    data = read_json(path, {}) or {}
    merged = deep_merge(DEFAULT_CONFIG, data)
    for key in ("vault_path", "work_root", "model", "note_subdir", "asr_backend", "browser_channel"):
        if not merged.get(key):
            merged[key] = DEFAULT_CONFIG[key]
    return merged


def work_root(config: Dict[str, Any]) -> Path:
    return Path(config.get("work_root") or default_work_root()).expanduser()


def session_dir(config: Dict[str, Any], session_id: str) -> Path:
    return work_root(config) / session_id


def read_state(config: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    path = session_dir(config, session_id) / "state.json"
    data = read_json(path)
    if not data:
        raise SkillError(f"session not found: {session_id}")
    return data


def update_state(config: Dict[str, Any], session_id: str, state: str, stage: str,
                 progress: Optional[float] = None, error: Optional[Dict[str, Any]] = None,
                 extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    path = session_dir(config, session_id) / "state.json"
    data = read_json(path, {}) or {}
    data.update({
        "session_id": session_id,
        "state": state,
        "stage": stage,
        "progress": progress,
        "updated_at": now_iso(),
    })
    if error is not None:
        data["error"] = error
    if extra:
        data.update(extra)
    atomic_write_json(path, data)
    return data


def resolve_session_dir(config: Dict[str, Any], session_id: str) -> Path:
    path = session_dir(config, session_id)
    if not path.exists():
        raise SkillError(f"session not found: {session_id}")
    return path


def extract_url(text: str) -> str:
    found = URL_RE.search(text or "")
    if not found:
        raise SkillError("没有找到视频链接。请把分享文案或链接一起发给我。")
    return found.group(0).rstrip("，。,.；;！!？?、\"'」")


def find_existing_note(vault: Path, source_id: Optional[str]) -> Optional[Path]:
    if not source_id or not vault.exists():
        return None
    needle = re.compile(rf'^source_id:\s*["\']?{re.escape(source_id)}["\']?\s*$', re.M)
    skip_parts = {".obsidian", ".git", ".qoder", "node_modules"}
    for path in vault.rglob("*.md"):
        if any(part in skip_parts for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if needle.search(text):
            return path
    return None


def resolve_asr_backend(config: Dict[str, Any]) -> str:
    requested = str(config.get("asr_backend") or "auto").strip().lower()
    if requested in ("mlx", "mlx-whisper", "mlx_whisper"):
        return "mlx"
    if requested in ("faster", "faster-whisper", "faster_whisper"):
        return "faster"
    return "mlx" if platforms.base.current_platform() == "macos" else "faster"


def find_uv() -> Optional[str]:
    uv = env_value("UV") or shutil.which("uv")
    if uv:
        return uv
    candidates = [
        Path.home() / ".local/bin/uv",
        Path.home() / ".cargo/bin/uv",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Microsoft/WinGet/Links/uv.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "uv/uv.exe",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates += sorted(Path(appdata).glob("Python/Python3*/Scripts/uv.exe"))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def worker_python_packages(config: Dict[str, Any], platform_key: str) -> List[str]:
    """按平台按需装依赖：B 站走 HTTP，不需要 playwright。"""
    backend = resolve_asr_backend(config)
    packages = ["requests", "mlx-whisper" if backend == "mlx" else "faster-whisper"]
    if platform_key == "douyin":
        packages.insert(0, "playwright")
    return packages


def spawn_worker(config: Dict[str, Any], session_id: str, platform_key: str) -> int:
    uv = find_uv()
    if not uv:
        raise SkillError(
            "uv not found; install uv first "
            "(Windows: winget install --id astral-sh.uv -e)"
        )
    script = Path(__file__).resolve()
    path = session_dir(config, session_id)
    cmd = [uv, "run", "--python", "3.12"]
    for package in worker_python_packages(config, platform_key):
        cmd += ["--with", package]
    cmd += ["--", "python", str(script), "_worker", "--session", session_id]
    env = os.environ.copy()
    env["HF_ENDPOINT"] = config.get("hf_endpoint") or env.get("HF_ENDPOINT") or "https://hf-mirror.com"
    env["UV_DEFAULT_INDEX"] = config.get("pypi_index") or env.get("UV_DEFAULT_INDEX") or "https://pypi.tuna.tsinghua.edu.cn/simple"
    env["PYTHONUNBUFFERED"] = "1"
    log_path = path / "worker.log"
    log = open(log_path, "ab", buffering=0)
    popen_kwargs: Dict[str, Any] = {
        "stdout": log,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "cwd": str(path),
        "env": env,
        "close_fds": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(cmd, **popen_kwargs)
    return process.pid


def start_command(args: argparse.Namespace) -> int:
    config = load_config()
    apply_network_env(config)
    text = args.input
    share_url = extract_url(text)
    adapter = platforms.detect(share_url)
    share_author, share_title = (None, None)
    parser = getattr(adapter, "parse_share_text", None)
    if parser:
        share_author, share_title = parser(text)
    source_id = platforms.source_id(share_url, config)

    if adapter.KEY == "douyin":
        checker = getattr(adapter, "quick_geo_blocked", None)
        if checker and checker(share_url):
            print(json.dumps({
                "ok": False,
                "state": "geo_blocked",
                "error": "抖音识别当前网络不是大陆出口。请关闭 VPN 或配置大陆代理后重试。",
            }, ensure_ascii=False, indent=2))
            return 1

    vault = Path(args.vault or config["vault_path"]).expanduser()
    subdir = args.subdir or config["note_subdir"]

    if source_id and not args.force:
        existing = find_existing_note(vault, source_id)
        if existing:
            print(json.dumps({
                "ok": True,
                "state": "duplicate",
                "platform": adapter.LABEL,
                "existing_note": str(existing),
                "message": "这条视频已经有笔记；如需重新整理，请使用 --force。",
            }, ensure_ascii=False, indent=2))
            return 0

    root = work_root(config)
    root.mkdir(parents=True, exist_ok=True)
    base = source_id or (adapter.KEY + "-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    session_id = base
    counter = 2
    while session_dir(config, session_id).exists():
        session_id = f"{base}-{counter}"
        counter += 1

    path = session_dir(config, session_id)
    path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "session_id": session_id,
        "input": text,
        "share_url": share_url,
        "source_id": source_id,
        "platform": adapter.KEY,
        "share_author": share_author,
        "share_title": share_title,
        "created_at": now_iso(),
        "overrides": {
            "vault": args.vault,
            "subdir": args.subdir,
            "force": bool(args.force),
            "mode": args.mode,
        },
    }
    atomic_write_json(path / "manifest.json", manifest)
    update_state(config, session_id, "starting", "init", 0.0)

    try:
        pid = spawn_worker(config, session_id, adapter.KEY)
    except Exception as exc:
        update_state(config, session_id, "failed", "init", None,
                     error={"type": type(exc).__name__, "message": str(exc)})
        print(json.dumps({"ok": False, "error": str(exc), "session_dir": str(path)},
                         ensure_ascii=False, indent=2))
        return 1

    state = read_state(config, session_id)
    print(json.dumps({
        "ok": True,
        "session_id": session_id,
        "session_dir": str(path),
        "platform": adapter.LABEL,
        "state": state.get("state"),
        "worker_pid": pid,
        "message": "后台 worker 已启动。",
    }, ensure_ascii=False, indent=2))
    return 0


def transcribe_with_mlx(config: Dict[str, Any], wav_path: str) -> Dict[str, Any]:
    """macOS（Apple Silicon）本机转写，离线、速度最快。"""
    import mlx_whisper

    return mlx_whisper.transcribe(
        str(wav_path),
        path_or_hf_repo=config["model"],
        language=config.get("language", "zh"),
        word_timestamps=bool(config.get("word_timestamps", False)),
        verbose=False,
    )


def load_wav_float32(wav_path: str) -> Any:
    """把 16k 单声道 WAV 读成 float32 数组，绕开 PyAV 解码路径。"""
    import wave

    import numpy as np

    with wave.open(str(wav_path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise TranscriptionError(f"WAV 位深不支持：{width * 8}bit（需要 16bit）")
    if rate != 16000:
        raise TranscriptionError(f"WAV 采样率不支持：{rate}Hz（需要 16000Hz）")
    data = np.frombuffer(frames, dtype="<i2")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return (data.astype("float32")) / 32768.0


def _faster_transcribe_once(config: Dict[str, Any], audio: Any, model_ref: str,
                            device: str, compute_type: str, note: str = "") -> Dict[str, Any]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_ref, device=device, compute_type=compute_type)
    segment_iter, info = model.transcribe(
        audio,
        language=config.get("language") or None,
        word_timestamps=bool(config.get("word_timestamps", False)),
        vad_filter=bool(config.get("faster_vad_filter", True)),
        beam_size=5,
    )
    segments = [
        {"start": float(segment.start), "end": float(segment.end), "text": segment.text}
        for segment in segment_iter
    ]
    return {
        "text": "".join(segment["text"] for segment in segments).strip(),
        "language": getattr(info, "language", None),
        "device": f"{device}/{compute_type}" + (f"（{note}）" if note else ""),
        "segments": segments,
    }


def transcribe_with_faster(config: Dict[str, Any], wav_path: str) -> Dict[str, Any]:
    """Windows / Linux 转写：CTranslate2 后端，CPU 或 CUDA 均可。"""
    audio = load_wav_float32(wav_path)
    model_ref = str(config.get("faster_model") or "large-v3")
    device = str(config.get("faster_device") or "cpu")
    compute_type = str(config.get("faster_compute_type") or "int8")
    try:
        return _faster_transcribe_once(config, audio, model_ref, device, compute_type)
    except Exception as exc:
        message = str(exc).lower()
        gpu_markers = ("cublas", "cudnn", "cuda", "nvidia", "gpu")
        if device == "cpu" or not any(marker in message for marker in gpu_markers):
            raise
        return _faster_transcribe_once(
            config, audio, model_ref, "cpu", "int8",
            note=f"已从 {device}/{compute_type} 回退：{type(exc).__name__}",
        )


def write_transcript(path: Path, segments: List[Dict[str, Any]], text: str,
                     backend: str, language: Optional[str] = None) -> Dict[str, Any]:
    transcript_json = path / "transcript.json"
    transcript_txt = path / "transcript.txt"
    segments_md = path / "transcript_segments.md"
    atomic_write_json(transcript_json, {"text": text, "language": language,
                                        "backend": backend, "segments": segments})
    atomic_write_text(transcript_txt, text + "\n")

    lines = []
    for segment in segments:
        segment_text = (segment.get("text") or "").strip()
        if not segment_text:
            continue
        lines.append(f"[{format_seconds(segment.get('start', 0))}] {segment_text}")
    atomic_write_text(segments_md, "\n".join(lines) + "\n")

    return {
        "backend": backend,
        "language": language,
        "text_length": len(text),
        "segment_count": len(segments),
        "paths": {
            "metadata_json": str(path / "metadata.json"),
            "transcript_txt": str(transcript_txt),
            "transcript_json": str(transcript_json),
            "transcript_segments_md": str(segments_md),
            "note_md": str(path / "note.md"),
        },
    }


def transcribe_audio(config: Dict[str, Any], wav_path: str, path: Path) -> Dict[str, Any]:
    backend = resolve_asr_backend(config)
    result = transcribe_with_mlx(config, wav_path) if backend == "mlx" else transcribe_with_faster(config, wav_path)
    text = (result.get("text") or "").strip()
    if not text:
        raise TranscriptionError(f"转写结果为空（backend={backend}）")
    try:
        Path(wav_path).unlink(missing_ok=True)
    except Exception:
        pass
    return write_transcript(path, result.get("segments", []), text, backend, result.get("language"))


def start_progress_thread(config: Dict[str, Any], session_id: str,
                          duration_seconds: Optional[float], stop_event: threading.Event) -> threading.Thread:
    factor = float(config.get("transcription_estimate_factor", 3.0) or 3.0)
    estimated_total = max(60.0, float(duration_seconds or 180.0) * factor)

    def loop() -> None:
        started = time.time()
        while not stop_event.wait(10):
            elapsed = time.time() - started
            progress = min(0.9, 0.15 + 0.75 * (elapsed / estimated_total))
            try:
                update_state(config, session_id, "running", "transcribe", progress)
            except Exception:
                pass

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def worker_command(args: argparse.Namespace) -> int:
    config = load_config()
    apply_network_env(config)
    session_id = args.session
    path = resolve_session_dir(config, session_id)
    manifest = read_json(path / "manifest.json", {}) or {}
    adapter = platforms.get(manifest.get("platform") or "douyin")
    try:
        update_state(config, session_id, "running", "capture", 0.05)
        captured = adapter.capture(config, manifest, path)
        metadata = captured["metadata"]
        update_state(config, session_id, "running", "transcribe", 0.15, extra={"metadata": metadata})

        if captured.get("segments"):
            # 平台自带字幕：跳过 ASR，直接用字幕时间轴
            segments = captured["segments"]
            text = "".join((item.get("text") or "").strip() for item in segments)
            transcribed = write_transcript(
                path, segments, text, "subtitle", metadata.get("subtitle_lan"),
            )
        else:
            stop_event = threading.Event()
            progress_thread = start_progress_thread(
                config, session_id, metadata.get("duration_seconds"), stop_event,
            )
            try:
                transcribed = transcribe_audio(config, captured["wav_path"], path)
            finally:
                stop_event.set()
                progress_thread.join(timeout=2)

        update_state(config, session_id, "ready", "done", 1.0,
                     extra={
                         "metadata": metadata,
                         "transcription": {
                             "backend": transcribed.get("backend"), "language": transcribed["language"],
                             "text_length": transcribed["text_length"],
                             "segment_count": transcribed["segment_count"],
                         },
                         "paths": transcribed["paths"],
                     })
        return 0
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        log_path = path / "worker.log"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + traceback.format_exc() + "\n")
            handle.flush()
        update_state(config, session_id, "failed", "error", None, error=error)
        return 1


def status_command(args: argparse.Namespace) -> int:
    config = load_config()
    path = resolve_session_dir(config, args.session)
    state = read_state(config, args.session)
    result = {"ok": True, "session_dir": str(path)}
    result.update(state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def wait_command(args: argparse.Namespace) -> int:
    config = load_config()
    path = resolve_session_dir(config, args.session)
    deadline = time.time() + float(args.timeout)
    terminal = {"ready", "failed", "duplicate", "committed"}
    while True:
        state = read_state(config, args.session)
        if state.get("state") in terminal:
            result = {"ok": state.get("state") != "failed", "session_dir": str(path)}
            result.update(state)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if state.get("state") != "failed" else 1
        if time.time() >= deadline:
            result = {"ok": True, "session_dir": str(path), "timed_out": True}
            result.update(state)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        time.sleep(float(args.interval))


def parse_frontmatter_title(text: str) -> Optional[str]:
    match = re.search(r"^---\s*\n(.*?)\n---", text, re.S | re.M)
    if not match:
        return None
    for line in match.group(1).splitlines():
        if line.strip().startswith("title:"):
            value = line.split(":", 1)[1].strip()
            return value.strip('"').strip("'")
    return None


def sanitize_filename(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', "-", title or "视频笔记")
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if len(name) > 120:
        name = name[:120].rstrip()
    return name or "视频笔记"


def add_updated_field(text: str) -> str:
    if re.search(r"^updated:", text, re.M):
        return text
    match = re.search(r"^(---\s*\n)(.*?)(\n---\s*\n)", text, re.S | re.M)
    if not match:
        return text
    return text[:match.end(2)] + f"\nupdated: {date.today().isoformat()}" + text[match.end(2):]


def validate_note(text: str) -> None:
    if not re.search(r"^#\s+", text, re.M):
        raise CommitError("笔记缺少一级标题")
    if "## 思维导图" not in text:
        raise CommitError("笔记缺少“## 思维导图”")
    if "```mermaid" not in text or "mindmap" not in text:
        raise CommitError("思维导图必须是 Mermaid mindmap")
    if "source_id:" not in text:
        raise CommitError("frontmatter 缺少 source_id")
    for forbidden in ("## 完整转写", "## 原始转写", "## 逐字稿"):
        if forbidden in text:
            raise CommitError(f"笔记不应包含“{forbidden}”")
    if "## 问答整理" in text:
        if not re.search(r"^### Q\d+\.", text, re.M):
            raise CommitError("面试题模式缺少 Q 编号")
        for marker in ("**考察点：**", "**回答框架：**", "**口述回答：**", "**补充标准答案：**"):
            if marker not in text:
                raise CommitError(f"面试题模式缺少 {marker}")
    elif "## 核心要点" not in text:
        raise CommitError("笔记既不是面试题模式，也缺少“## 核心要点”")


def commit_command(args: argparse.Namespace) -> int:
    config = load_config()
    session_id = args.session
    path = resolve_session_dir(config, session_id)
    state = read_state(config, session_id)
    if state.get("state") != "ready":
        raise CommitError(f"session 尚未 ready：{state.get('state')}")
    note_path = Path(args.note).expanduser()
    if not note_path.exists():
        raise CommitError(f"note file not found: {note_path}")
    text = note_path.read_text(encoding="utf-8")
    validate_note(text)
    title = args.title or parse_frontmatter_title(text)
    if not title:
        raise CommitError("无法从 note frontmatter 解析 title，请传 --title")

    manifest = read_json(path / "manifest.json", {}) or {}
    overrides = manifest.get("overrides", {}) or {}
    vault = Path(args.vault or overrides.get("vault") or config["vault_path"]).expanduser()
    subdir = args.subdir or overrides.get("subdir") or config["note_subdir"]
    if not vault.exists():
        raise CommitError(f"vault 路径不存在：{vault}")
    target_dir = vault / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        target_dir.resolve().relative_to(path.resolve())
        raise CommitError("目标目录位于 session 临时目录内，拒绝写入和清理")
    except ValueError:
        pass

    metadata = state.get("metadata", {}) or {}
    source_id = metadata.get("source_id") or manifest.get("source_id")
    force = bool(args.force or overrides.get("force"))
    existing = find_existing_note(vault, source_id) if source_id else None
    if existing and not force:
        shutil.rmtree(path, ignore_errors=True)
        print(json.dumps({
            "ok": True,
            "state": "duplicate",
            "existing_note": str(existing),
            "message": "这条视频已有笔记，未重复创建。",
        }, ensure_ascii=False, indent=2))
        return 0

    if existing and force:
        target = existing
        text = add_updated_field(text)
    else:
        target = target_dir / (sanitize_filename(title) + ".md")
        if target.exists():
            if source_id:
                target = target_dir / f"{sanitize_filename(title)} - {source_id}.md"
            counter = 2
            base = target
            while target.exists():
                target = base.with_name(f"{base.stem} ({counter}){base.suffix}")
                counter += 1

    atomic_write_text(target, text)
    shutil.rmtree(path, ignore_errors=True)
    print(json.dumps({
        "ok": True,
        "state": "committed",
        "note_path": str(target),
        "title": title,
        "platform": metadata.get("platform"),
        "cleanup": not path.exists(),
    }, ensure_ascii=False, indent=2))
    return 0


def probe_command(args: argparse.Namespace) -> int:
    config = load_config()
    apply_network_env(config)
    share_url = extract_url(args.url) if not args.url.startswith("http") else args.url
    adapter = platforms.detect(share_url)
    prober = getattr(adapter, "probe", None)
    if not prober:
        raise SkillError(f"{adapter.LABEL} 平台需要浏览器抓取，请直接使用 start")
    metadata = prober(config, share_url)
    print(json.dumps({"ok": True, "platform": adapter.LABEL, "metadata": metadata},
                     ensure_ascii=False, indent=2))
    return 0


def platforms_command(args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, "platforms": platforms.describe()},
                     ensure_ascii=False, indent=2))
    return 0


def doctor_command(args: argparse.Namespace) -> int:
    config = load_config()
    apply_network_env(config)
    warnings: List[str] = []
    plat = platforms.base.current_platform()
    backend = resolve_asr_backend(config)
    uv = find_uv()
    if not uv:
        warnings.append("uv not found; install it first (Windows: winget install --id astral-sh.uv -e)")
    ffmpeg = None
    try:
        ffmpeg = find_ffmpeg()
    except Exception as exc:
        warnings.append(str(exc))

    browser = platforms.douyin.find_browser(config)
    if browser.get("source") == "none":
        warnings.append("no Chrome / Edge / Chromium found; douyin capture needs one (Bilibili does not)")
    if backend == "mlx" and plat != "macos":
        warnings.append(f"asr_backend=mlx is not supported on {plat}; use asr_backend=faster")
    if backend == "faster" and plat == "macos":
        warnings.append("asr_backend=faster works on macOS but is slower than mlx-whisper")
    vault = Path(config["vault_path"]).expanduser()
    if not vault.exists():
        warnings.append(f"vault path not found: {vault}")

    model_ref = config["model"] if backend == "mlx" else str(config.get("faster_model") or "large-v3")
    if "/" not in model_ref:
        model_ref = f"Systran/faster-whisper-{model_ref}"
    hf_cache = os.environ.get("HF_HUB_CACHE")
    if hf_cache:
        model_root = Path(hf_cache).expanduser()
    else:
        hf_home = Path(os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface"))).expanduser()
        model_root = hf_home / "hub"
    model_dir = model_root / ("models--" + model_ref.replace("/", "--"))
    model_cached = model_dir.exists() and any(
        item.stat().st_size > 2_000_000_000
        for item in model_dir.rglob("blobs/*")
        if item.is_file()
    )

    network: Dict[str, Any] = {}
    for name, url in (("pypi_index", config["pypi_index"]), ("hf_endpoint", config["hf_endpoint"])):
        try:
            import requests
            status = requests.get(url, timeout=8).status_code
            network[f"{name}_status"] = status
            network[f"{name}_reachable"] = status < 500
        except Exception as exc:
            network[f"{name}_error"] = str(exc)
            network[f"{name}_reachable"] = False
    try:
        import requests
        status = requests.get("https://api.bilibili.com/x/web-interface/nav", timeout=8).status_code
        network["bilibili_status"] = status
        network["bilibili_reachable"] = status < 500
    except Exception as exc:
        network["bilibili_error"] = str(exc)
        network["bilibili_reachable"] = False

    result = {
        "ok": not warnings,
        "app": APP_NAME,
        "version": VERSION,
        "platform": plat,
        "python": sys.version.split()[0],
        "asr_backend": backend,
        "platforms": platforms.describe(),
        "proxy_configured": bool(config.get("proxy_url")),
        "config_path": str(config_path()),
        "vault_path": str(vault),
        "vault_exists": vault.exists(),
        "uv": uv,
        "ffmpeg": ffmpeg,
        "browser": browser,
        "model": config["model"],
        "faster_model": config.get("faster_model"),
        "model_ref": model_ref,
        "model_cached": model_cached,
        "model_dir": str(model_dir),
        "network": network,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not warnings else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("start")
    p.add_argument("--input", required=True)
    p.add_argument("--vault")
    p.add_argument("--subdir")
    p.add_argument("--mode", default="auto", choices=["auto", "interview", "general"])
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=start_command)

    p = sub.add_parser("_worker")
    p.add_argument("--session", required=True)
    p.set_defaults(func=worker_command)

    p = sub.add_parser("status")
    p.add_argument("--session", required=True)
    p.set_defaults(func=status_command)

    p = sub.add_parser("wait")
    p.add_argument("--session", required=True)
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--interval", type=float, default=5)
    p.set_defaults(func=wait_command)

    p = sub.add_parser("commit")
    p.add_argument("--session", required=True)
    p.add_argument("--note", required=True)
    p.add_argument("--title")
    p.add_argument("--vault")
    p.add_argument("--subdir")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=commit_command)

    p = sub.add_parser("probe")
    p.add_argument("--url", required=True)
    p.set_defaults(func=probe_command)

    p = sub.add_parser("platforms")
    p.set_defaults(func=platforms_command)

    p = sub.add_parser("doctor")
    p.set_defaults(func=doctor_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except SkillError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": "interrupted"}, ensure_ascii=False, indent=2))
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
