"""B 站适配器：走公开 API，不需要浏览器，也不需要登录。

流程：
1. `x/web-interface/view` 拿标题 / UP / 时长 / cid；
2. 优先取官方或 AI 字幕（`x/player/v2`），有字幕就不做 ASR；
3. 没有字幕时用 `x/player/playurl` 取 DASH 音轨，下载后用 ffmpeg 抽 16k 单声道 WAV。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    CaptureError,
    SkillError,
    atomic_write_json,
    download_to,
    extract_wav,
    format_seconds,
    get_json,
    http_session,
    now_iso,
)

KEY = "bilibili"
LABEL = "B站"

API_VIEW = "https://api.bilibili.com/x/web-interface/view"
API_PLAYER = "https://api.bilibili.com/x/player/v2"
API_PLAYURL = "https://api.bilibili.com/x/player/playurl"

HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn")
BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
AV_RE = re.compile(r"(?:/av|aid=)(\d+)")
PAGE_RE = re.compile(r"[?&]p=(\d+)")


def match(url: str) -> bool:
    lowered = (url or "").lower()
    return any(host in lowered for host in HOSTS)


def _canonical(bvid: Optional[str], aid: Optional[str], page: int) -> str:
    base = f"https://www.bilibili.com/video/{bvid}" if bvid else f"https://www.bilibili.com/video/av{aid}"
    return f"{base}?p={page}" if page > 1 else base


def resolve_ref(url: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把分享链接（含 b23.tv 短链）解析成 bvid / aid / 分P。"""
    text = (url or "").strip()
    bvid: Optional[str] = None
    aid: Optional[str] = None
    page = 1

    def parse(value: str) -> None:
        nonlocal bvid, aid, page
        found = BV_RE.search(value or "")
        if found:
            bvid = found.group(1)
        found = AV_RE.search(value or "")
        if found:
            aid = found.group(1)
        found = PAGE_RE.search(value or "")
        if found:
            page = max(1, int(found.group(1)))

    parse(text)
    if not bvid and not aid:
        # 短链必须跟随跳转才能拿到 BV 号
        try:
            response = http_session(config).get(text, timeout=20, allow_redirects=True)
            parse(response.url)
            parse(response.text[:20000])
        except Exception as exc:
            raise SkillError(f"无法解析 B 站链接：{exc}") from exc
    if not bvid and not aid:
        raise SkillError("链接里没有找到 BV 号或 av 号，请确认是 B 站视频链接")
    return {"bvid": bvid, "aid": aid, "page": page, "url": _canonical(bvid, aid, page)}


def resolve_source_id(url: str, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """去重用：BV 号（多分P 带上页码）。不联网也能从链接里拿到。"""
    ref = resolve_ref(url, config)
    if ref["page"] <= 1:
        return ref["bvid"]
    return f"{ref['bvid']}-p{ref['page']}"


def _view(ref: Dict[str, Any], config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    query = f"bvid={ref['bvid']}" if ref.get("bvid") else f"aid={ref['aid']}"
    data = get_json(f"{API_VIEW}?{query}", config=config)
    if data.get("code") != 0:
        code = data.get("code")
        if code == -404:
            raise SkillError("视频不存在或已被删除（B 站返回 -404）")
        if code in (-403, -10403):
            raise SkillError("视频仅限特定用户观看，无法获取（B 站返回 -403）")
        raise SkillError(f"B 站接口返回错误：{code} {data.get('message') or ''}".strip())
    return data["data"] or {}


def probe(config: Dict[str, Any], url: str) -> Dict[str, Any]:
    """只取元信息，不下载媒体；给 `probe` 命令和测试用。"""
    ref = resolve_ref(url, config)
    info = _view(ref, config)
    pages: List[Dict[str, Any]] = info.get("pages") or []
    page_index = min(max(ref["page"], 1), max(len(pages), 1)) - 1
    current = pages[page_index] if pages else {}
    bvid = info.get("bvid") or ref["bvid"]
    source_id = bvid if ref["page"] <= 1 else f"{bvid}-p{ref['page']}"
    duration = current.get("duration") or info.get("duration")
    published = None
    if info.get("pubdate"):
        from datetime import datetime
        published = datetime.fromtimestamp(int(info["pubdate"])).strftime("%Y-%m-%d")
    return {
        "source": _canonical(bvid, ref.get("aid"), ref["page"]),
        "source_share_url": url,
        "source_id": source_id,
        "source_title": info.get("title"),
        "platform": LABEL,
        "platform_key": KEY,
        "author": (info.get("owner") or {}).get("name"),
        "published": published,
        "duration_seconds": duration,
        "duration": format_seconds(duration) if duration else None,
        "captured_at": now_iso(),
        "extra": {
            "bvid": bvid,
            "aid": info.get("aid"),
            "cid": current.get("cid") or info.get("cid"),
            "page": ref["page"],
            "part": current.get("part"),
            "description": (info.get("desc") or "").strip()[:500],
            "category": info.get("tname"),
            "view_count": (info.get("stat") or {}).get("view"),
        },
    }


def _subtitles(metadata: Dict[str, Any], config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """有字幕就直接用，省掉整段 ASR；没有返回 None。"""
    extra = metadata.get("extra") or {}
    query = f"bvid={extra.get('bvid')}&cid={extra.get('cid')}"
    try:
        data = get_json(f"{API_PLAYER}?{query}", config=config)
    except Exception:
        return None
    if data.get("code") != 0:
        return None
    items = ((data.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    if not items:
        return None
    chosen = None
    for item in items:
        lang = str(item.get("lan") or "")
        if lang.startswith("zh"):
            chosen = item
            break
    chosen = chosen or items[0]
    url = chosen.get("subtitle_url") or ""
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        return None
    try:
        payload = get_json(url, referer="https://www.bilibili.com/", config=config)
    except Exception:
        return None
    segments = []
    for line in payload.get("body") or []:
        text = (line.get("content") or "").strip()
        if not text:
            continue
        segments.append({
            "start": float(line.get("from") or 0),
            "end": float(line.get("to") or 0),
            "text": text,
        })
    if not segments:
        return None
    return {"segments": segments, "lan": chosen.get("lan"), "lan_doc": chosen.get("lan_doc")}


def _audio_url(metadata: Dict[str, Any], config: Dict[str, Any]) -> str:
    extra = metadata.get("extra") or {}
    query = f"bvid={extra.get('bvid')}&cid={extra.get('cid')}&fnval=4048&fourk=1"
    data = get_json(f"{API_PLAYURL}?{query}", config=config, referer=metadata["source"])
    if data.get("code") != 0:
        raise CaptureError(f"获取播放地址失败：{data.get('code')} {data.get('message') or ''}")
    payload = data.get("data") or {}
    dash = payload.get("dash") or {}
    audios = dash.get("audio") or []
    if audios:
        # 取码率最低的音轨：语音转写够用，下载最快
        audios = sorted(audios, key=lambda item: item.get("bandwidth") or 0)
        for item in audios:
            url = item.get("baseUrl") or item.get("base_url")
            if url:
                return url
    durl = payload.get("durl") or []
    if durl and durl[0].get("url"):
        return durl[0]["url"]
    raise CaptureError("没有拿到可下载的音轨（视频可能受限或需要登录）")


def capture(config: Dict[str, Any], manifest: Dict[str, Any], path: Path) -> Dict[str, Any]:
    metadata = probe(config, manifest.get("share_url") or manifest.get("source", ""))

    subtitles = _subtitles(metadata, config)
    if subtitles:
        metadata["transcript_source"] = "subtitle"
        metadata["subtitle_lan"] = subtitles.get("lan_doc") or subtitles.get("lan")
        atomic_write_json(path / "metadata.json", metadata)
        return {"wav_path": None, "segments": subtitles["segments"], "metadata": metadata}

    audio_url = _audio_url(metadata, config)
    media_path = path / "media.m4s"
    wav_path = path / "audio.wav"
    download_to(audio_url, media_path, referer=metadata["source"], config=config)
    extract_wav(media_path, wav_path)

    metadata["transcript_source"] = "asr"
    atomic_write_json(path / "metadata.json", metadata)
    return {"wav_path": str(wav_path), "segments": None, "metadata": metadata}
