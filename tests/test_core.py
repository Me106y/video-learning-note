"""不联网的单元测试：平台识别、链接解析、笔记校验、版本一致性。"""
import json
from pathlib import Path

import pytest

import platforms
from platforms import bilibili, douyin
import video_note

ROOT = Path(__file__).resolve().parent.parent


def test_detect_bilibili_and_douyin():
    assert platforms.detect("https://www.bilibili.com/video/BV1Wj3y68EUD").KEY == "bilibili"
    assert platforms.detect("https://b23.tv/abcd123").KEY == "bilibili"
    assert platforms.detect("https://www.douyin.com/video/7300000000000000000").KEY == "douyin"
    assert platforms.detect("https://v.douyin.com/iAbCdEf/").KEY == "douyin"


def test_detect_unsupported():
    with pytest.raises(platforms.SkillError):
        platforms.detect("https://example.com/video/1")


def test_bilibili_resolve_ref_with_page():
    ref = bilibili.resolve_ref("https://www.bilibili.com/video/BV1Wj3y68EUD?p=3")
    assert ref["bvid"] == "BV1Wj3y68EUD"
    assert ref["page"] == 3
    assert ref["url"].endswith("?p=3")


def test_bilibili_resolve_ref_av():
    ref = bilibili.resolve_ref("https://www.bilibili.com/video/av117001838206560")
    assert ref["aid"] == "117001838206560"
    assert ref["page"] == 1


def test_bilibili_source_id():
    assert bilibili.resolve_source_id("https://www.bilibili.com/video/BV1Wj3y68EUD") == "BV1Wj3y68EUD"
    assert bilibili.resolve_source_id("https://www.bilibili.com/video/BV1Wj3y68EUD?p=2") == "BV1Wj3y68EUD-p2"


def test_probe_maps_api_payload(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "bvid": "BV1Wj3y68EUD",
            "aid": 117001838206560,
            "title": "测试标题",
            "desc": "描述",
            "duration": 868,
            "pubdate": 1785643200,
            "owner": {"name": "某 UP"},
            "tname": "科技",
            "stat": {"view": 100},
            "cid": 111,
            "pages": [{"cid": 111, "duration": 868, "part": "第一集"}],
        },
    }
    monkeypatch.setattr(bilibili, "get_json", lambda *a, **k: payload)
    meta = bilibili.probe({}, "https://www.bilibili.com/video/BV1Wj3y68EUD")
    assert meta["source_title"] == "测试标题"
    assert meta["author"] == "某 UP"
    assert meta["duration"] == "14:28"
    assert meta["source_id"] == "BV1Wj3y68EUD"
    assert meta["platform"] == "B站"
    assert meta["extra"]["cid"] == 111


def test_douyin_parse_share_text():
    text = "【张三的作品】3分钟讲清楚 Agent 记忆 https://v.douyin.com/iAbCdEf/"
    author, title = douyin.parse_share_text(text)
    assert author == "张三"
    assert title == "3分钟讲清楚 Agent 记忆"


def test_extract_url_strips_punctuation():
    assert video_note.extract_url("看这个 https://b23.tv/abc123，") == "https://b23.tv/abc123"


def test_sanitize_filename():
    assert video_note.sanitize_filename('a/b:c*"d?') == "a-b-c-d-"
    assert len(video_note.sanitize_filename("x" * 300)) == 120


GOOD_NOTE = """---
title: "学习笔记｜测试"
source: "https://www.bilibili.com/video/BV1"
source_id: "BV1"
tags:
  - "视频笔记"
  - "B站"
---

# 学习笔记｜测试

## 思维导图

```mermaid
mindmap
  root((主题))
    要点
```

## 核心要点
- 一条

## 来源
[B 站原视频](https://www.bilibili.com/video/BV1)
"""


def test_validate_note_accepts_good_note():
    video_note.validate_note(GOOD_NOTE)


def test_validate_note_rejects_transcript_dump():
    with pytest.raises(video_note.CommitError):
        video_note.validate_note(GOOD_NOTE + "\n## 完整转写\n...\n")


def test_validate_note_requires_mindmap():
    broken = GOOD_NOTE.replace("```mermaid", "```text")
    with pytest.raises(video_note.CommitError):
        video_note.validate_note(broken)


def test_versions_are_synced():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"] == version
    assert json.loads((ROOT / "skill.json").read_text(encoding="utf-8"))["version"] == version
    assert video_note.VERSION == version


def test_skill_frontmatter_present():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: video-learning-note" in text
