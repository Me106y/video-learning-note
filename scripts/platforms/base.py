"""跨平台共用的底座：错误类型、路径、网络、ffmpeg、时间格式化。

适配器（douyin.py / bilibili.py）只依赖本模块，不反向依赖 CLI，
这样新增平台时不必改动主流程。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SkillError(RuntimeError):
    """所有可预期错误的基类，CLI 会把它转成 JSON 输出。"""


class GeoBlockedError(SkillError):
    pass


class CaptureError(SkillError):
    pass


class TranscriptionError(SkillError):
    pass


class CommitError(SkillError):
    pass


def current_platform() -> str:
    """当前平台：windows / macos / linux。

    VIDEO_NOTE_OS 可显式覆盖，便于跨平台自检；兼容旧的 DOUYIN_NOTE_OS。
    """
    override = (os.environ.get("VIDEO_NOTE_OS") or os.environ.get("DOUYIN_NOTE_OS") or "").strip().lower()
    if override:
        if override in ("win", "windows", "nt", "win32"):
            return "windows"
        if override in ("mac", "macos", "darwin", "osx"):
            return "macos"
        if override in ("linux", "posix", "unix"):
            return "linux"
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt" or sys.platform.startswith("win"):
        return "windows"
    return "linux"


def user_agent() -> str:
    """UA 与真实运行平台保持一致，避免伪造 UA 触发平台风控。"""
    plat = current_platform()
    if plat == "windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"
        )
    if plat == "macos":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    )


UA = user_agent()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def format_seconds(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds)))
    except Exception:
        return "00:00"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    candidates: List[str] = [
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates += [
            str(Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise SkillError("ffmpeg not found; install ffmpeg first")


def apply_network_env(config: Dict[str, Any]) -> None:
    """把代理意图落到进程环境变量。

    Windows 上 Python 的 requests 会自动继承系统/IE 代理（常见是 Clash 之类），
    即使配置里没写 proxy_url 也会被套上代理，于是出现「curl 直连正常、Python 连接被重置」。
    这里显式表达意图：配了 proxy_url 就用它，没配就强制直连。
    """
    proxy = (config.get("proxy_url") or "").strip()
    if proxy:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[key] = proxy
        os.environ.pop("NO_PROXY", None)
        os.environ.pop("no_proxy", None)
        return
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)


def http_session(config: Optional[Dict[str, Any]] = None) -> Any:
    """带默认头与超时的 requests 会话；代理由环境变量统一控制。"""
    import requests

    if config is not None:
        apply_network_env(config)
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    return session


def get_json(url: str, referer: str = "https://www.bilibili.com/",
             config: Optional[Dict[str, Any]] = None, timeout: float = 20) -> Dict[str, Any]:
    session = http_session(config)
    headers = {"Referer": referer} if referer else {}
    response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.json()


def download_to(url: str, dest: Path, referer: str, config: Optional[Dict[str, Any]] = None,
                timeout: Optional[float] = None) -> Path:
    """流式下载媒体，避免整段读进内存。"""
    session = http_session(config)
    limit = timeout or float(config.get("download_timeout_seconds", 120) if config else 120)
    with session.get(url, headers={"Referer": referer}, timeout=limit, stream=True, allow_redirects=True) as response:
        response.raise_for_status()
        ensure_parent(dest)
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if chunk:
                    handle.write(chunk)
    return dest


def extract_wav(media_path: Path, wav_path: Path) -> Path:
    """抽 16k 单声道 PCM，交给任意 ASR 后端都能直接吃。"""
    ffmpeg = find_ffmpeg()
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(media_path), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(wav_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "")[-800:]
        raise CaptureError(f"ffmpeg 抽音频失败：{tail or exc}") from exc
    except Exception as exc:
        raise CaptureError(f"ffmpeg 抽音频失败：{exc}") from exc
    media_path.unlink(missing_ok=True)
    return wav_path
