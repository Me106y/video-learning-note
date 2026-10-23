"""抖音适配器：用本机浏览器抓取播放流。

抖音的媒体地址由前端 JS 动态签发，公开接口拿不到稳定的直链，所以这里沿用
Playwright + 持久化 profile 的做法：复用 Cookie 与指纹，减少验证码。
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    CaptureError,
    GeoBlockedError,
    UA,
    atomic_write_json,
    extract_wav,
    format_seconds,
    now_iso,
)

KEY = "douyin"
LABEL = "抖音"

HOSTS = ("douyin.com", "iesdouyin.com")


def match(url: str) -> bool:
    lowered = (url or "").lower()
    return any(host in lowered for host in HOSTS)


def browser_candidates() -> List[Tuple[str, Optional[str]]]:
    """按优先级返回 (可执行文件, playwright channel) 候选；channel=None 表示用自带 chromium。"""
    plat = os.environ.get("VIDEO_NOTE_OS", "").lower()
    if not plat:
        import sys
        plat = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")
    items: List[Tuple[str, Optional[str]]] = []
    if plat == "windows":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        chrome_dirs = [
            Path(program_files) / "Google" / "Chrome" / "Application",
            Path(program_files_x86) / "Google" / "Chrome" / "Application",
        ]
        if local_appdata:
            chrome_dirs.append(Path(local_appdata) / "Google" / "Chrome" / "Application")
        items += [(str(directory / "chrome.exe"), "chrome") for directory in chrome_dirs]
        items += [
            (str(Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe"), "msedge"),
            (str(Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe"), "msedge"),
        ]
    elif plat == "macos":
        items += [
            ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chrome"),
            ("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary", "chrome"),
            ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "msedge"),
            ("/Applications/Chromium.app/Contents/MacOS/Chromium", None),
        ]
    for command, channel in (
        ("google-chrome", "chrome"),
        ("google-chrome-stable", "chrome"),
        ("microsoft-edge", "msedge"),
        ("microsoft-edge-stable", "msedge"),
        ("chromium", None),
        ("chromium-browser", None),
        ("chrome", "chrome"),
        ("msedge", "msedge"),
    ):
        found = shutil.which(command)
        if found:
            items.append((found, channel))
    return items


def find_browser(config: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[str]]:
    """定位可用浏览器，返回 {path, channel, source}。"""
    requested = str((config or {}).get("browser_channel") or "auto").strip()
    lowered = requested.lower()
    if lowered in ("chromium", "bundled", "none", "playwright"):
        return {"path": None, "channel": None, "source": "bundled-chromium"}
    candidates = browser_candidates()
    if lowered and lowered != "auto":
        for path, channel in candidates:
            if channel == lowered and Path(path).exists():
                return {"path": path, "channel": channel, "source": "config"}
        if Path(requested).exists():
            return {"path": requested, "channel": None, "source": "config-path"}
        for path, channel in candidates:
            if Path(path).exists():
                return {"path": path, "channel": channel, "source": "auto-fallback"}
        return {"path": None, "channel": lowered, "source": "config-forced"}
    for path, channel in candidates:
        if Path(path).exists():
            return {"path": path, "channel": channel, "source": "auto"}
    return {"path": None, "channel": None, "source": "none"}


def resolve_source_id(url: str, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    match_id = re.search(r"/(?:video|share/video)/(\d+)", url or "")
    if match_id:
        return match_id.group(1)
    try:
        import requests
        response = requests.get(
            url,
            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            timeout=15,
            allow_redirects=True,
        )
        final = response.url
        match_id = re.search(r"/(?:video|share/video)/(\d+)", final)
        if match_id:
            return match_id.group(1)
        match_id = re.search(r"[?&]modal_id=(\d+)", final)
        if match_id:
            return match_id.group(1)
        match_id = re.search(r'"aweme_id"\s*:\s*"(\d+)"', response.text)
        if match_id:
            return match_id.group(1)
    except Exception:
        pass
    return None


def quick_geo_blocked(url: str) -> bool:
    try:
        import requests
        response = requests.get(
            url,
            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            timeout=15,
            allow_redirects=True,
        )
        text = response.text or ""
        return ('"isMainland":false' in text) or ('"country":"hk"' in text) or ('country:"hk"' in text)
    except Exception:
        return False


def choose_media_url(requests_list: List[Dict[str, Any]], video: Any) -> Optional[str]:
    urls = []
    for item in requests_list:
        url = item.get("url") or ""
        if not url.startswith("http"):
            continue
        if "douyinvod.com" not in url and "video/tos" not in url:
            continue
        urls.append(url)

    def score(url: str) -> float:
        value = 0.0
        if "media-audio-und-mp4a" in url:
            value += 1000.0
        elif "media-video" in url:
            value += 500.0
        if "mime_type=video_mp4" in url:
            value += 50.0
        match_br = re.search(r"[?&]br=(\d+)", url)
        if match_br:
            value += min(int(match_br.group(1)), 5000) / 10000.0
        return value

    unique = sorted(set(urls), key=score, reverse=True)
    if unique:
        return unique[0]

    try:
        current = video.evaluate("e => e.currentSrc || e.src || ''")
        if current and current.startswith("http"):
            return current
    except Exception:
        pass
    return None


def parse_share_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    author = None
    title = None
    found = re.search(r"【(.+?)的作品】", text or "")
    if found:
        author = found.group(1).strip()
    found = re.search(r"【.+?的作品】\s*(.*?)\s*https?://", text or "", re.S)
    if found:
        title = re.sub(r"\s+", " ", found.group(1)).strip()
    return author, title


def capture(config: Dict[str, Any], manifest: Dict[str, Any], path: Path) -> Dict[str, Any]:
    from playwright.sync_api import sync_playwright

    source_id = manifest.get("source_id")
    share_url = manifest["share_url"]
    canonical_url = f"https://www.douyin.com/video/{source_id}" if source_id else share_url
    profile_dir = Path(config.get("browser_profile_dir") or "").expanduser()
    if not profile_dir or str(profile_dir) in (".", ""):
        profile_dir = Path(config["work_root"]).expanduser().parent / "browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    media_requests: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}
    context = None

    def on_request(request: Any) -> None:
        url = request.url
        if ("douyinvod.com" in url or "video/tos" in url or "mime_type=video_mp4" in url):
            media_requests.append({"url": url, "resource_type": request.resource_type})

    try:
        browser = find_browser(config)
        if browser.get("source") == "none":
            raise CaptureError(
                "未找到可用的 Chrome / Edge / Chromium。请安装任一浏览器，"
                "或在配置里把 browser_channel 设为 chromium 并执行 playwright install chromium。"
            )
        with sync_playwright() as play:
            proxy = {"server": config["proxy_url"]} if config.get("proxy_url") else None
            launch_kwargs: Dict[str, Any] = {
                "user_data_dir": str(profile_dir),
                "headless": bool(config.get("headless", False)),
                "locale": "zh-CN",
                "user_agent": config.get("user_agent") or UA,
                "viewport": {"width": 1440, "height": 900},
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                "proxy": proxy,
            }
            if browser.get("channel"):
                launch_kwargs["channel"] = browser["channel"]
            context = play.chromium.launch_persistent_context(**launch_kwargs)
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                "window.chrome = window.chrome || {runtime: {}};"
            )
            page = context.new_page()
            page.on("request", on_request)

            page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)
            is_mainland = page.evaluate(
                "() => (window.EXPOSE_DATA && typeof window.EXPOSE_DATA.isMainland === 'boolean') "
                "? window.EXPOSE_DATA.isMainland : null"
            )
            if is_mainland is False:
                raise GeoBlockedError(
                    "抖音识别当前网络不是大陆出口。请关闭 VPN 或配置大陆代理后重试。"
                )

            page.goto(canonical_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            is_mainland = page.evaluate(
                "() => (window.EXPOSE_DATA && typeof window.EXPOSE_DATA.isMainland === 'boolean') "
                "? window.EXPOSE_DATA.isMainland : null"
            )
            if is_mainland is False:
                raise GeoBlockedError(
                    "抖音识别当前网络不是大陆出口。请关闭 VPN 或配置大陆代理后重试。"
                )
            page.wait_for_selector("video", state="attached", timeout=45000)
            video = page.locator("video").first
            for _ in range(30):
                try:
                    ready = bool(video.evaluate(
                        "e => e.readyState >= 1 || (Number.isFinite(e.duration) && e.duration > 0)"
                    ))
                except Exception:
                    ready = False
                if ready:
                    break
                page.wait_for_timeout(1000)

            try:
                duration = video.evaluate("e => Number.isFinite(e.duration) ? e.duration : null")
            except Exception:
                duration = None

            if config.get("max_duration_minutes") and duration:
                if duration > float(config["max_duration_minutes"]) * 60:
                    raise CaptureError("视频时长超过配置上限")

            title = ""
            try:
                if page.locator("h1").count():
                    title = page.locator("h1").first.inner_text().strip()
            except Exception:
                title = ""
            if not title:
                title = page.title().replace(" - 抖音", "").strip()
            if not title:
                title = manifest.get("share_title") or "抖音视频"

            description = ""
            try:
                description = page.locator('meta[name="description"]').first.get_attribute("content") or ""
            except Exception:
                description = ""
            author = manifest.get("share_author")
            published = None
            found = re.search(r"-\s*(.+?)于(\d{8})发布", description)
            if found:
                author = found.group(1).strip()
                raw_date = found.group(2)
                published = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

            metadata = {
                "source": canonical_url,
                "source_share_url": share_url,
                "source_id": source_id,
                "source_title": title,
                "platform": LABEL,
                "platform_key": KEY,
                "author": author,
                "published": published,
                "duration_seconds": duration,
                "duration": format_seconds(duration) if duration else None,
                "captured_at": now_iso(),
                "transcript_source": "asr",
            }

            try:
                page.evaluate("() => { const v = document.querySelector('video'); if (v) { v.muted = false; v.play().catch(() => {}); } }")
            except Exception:
                pass
            page.wait_for_timeout(6000)

            for _ in range(5):
                if choose_media_url(media_requests, video):
                    break
                page.wait_for_timeout(3000)

            media_url = choose_media_url(media_requests, video)
            if not media_url:
                raise CaptureError("没有捕获到音视频播放流")

            response = context.request.get(
                media_url,
                headers={"Referer": canonical_url},
                timeout=int(config.get("download_timeout_seconds", 120)) * 1000,
            )
            if not response.ok:
                raise CaptureError(f"下载媒体流失败：HTTP {response.status}")
            media_path = path / "media.bin"
            media_path.write_bytes(response.body())
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        # 保留 profile（Cookie/指纹/已通过的验证码），下次运行不必重新过风控

    wav_path = path / "audio.wav"
    extract_wav(path / "media.bin", wav_path)
    atomic_write_json(path / "metadata.json", metadata)
    return {"wav_path": str(wav_path), "segments": None, "metadata": metadata}
