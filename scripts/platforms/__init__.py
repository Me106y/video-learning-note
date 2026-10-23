"""平台注册表。

新增一个平台只需要在 platforms/ 下加一个模块，实现
`KEY` / `LABEL` / `match(url)` / `source_id(url, config)` / `capture(config, manifest, path)`，
然后在 ADAPTERS 里登记。主流程、SKILL.md 与 CLI 都不需要改。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import base, bilibili, douyin  # noqa: F401  base 供 CLI 以 platforms.base 访问
from .base import SkillError

ADAPTERS = [bilibili, douyin]


def detect(url: str) -> Any:
    for adapter in ADAPTERS:
        if adapter.match(url):
            return adapter
    supported = "、".join(f"{item.LABEL}（{item.KEY}）" for item in ADAPTERS)
    raise SkillError(f"暂不支持这个站点。目前支持：{supported}")


def get(key: str) -> Any:
    for adapter in ADAPTERS:
        if adapter.KEY == key:
            return adapter
    raise SkillError(f"unknown platform: {key}")


def describe() -> List[Dict[str, str]]:
    return [
        {
            "key": adapter.KEY,
            "label": adapter.LABEL,
            "hosts": ", ".join(getattr(adapter, "HOSTS", ())),
        }
        for adapter in ADAPTERS
    ]


def source_id(url: str, config: Dict[str, Any]) -> Optional[str]:
    adapter = detect(url)
    resolver = getattr(adapter, "resolve_source_id", None)
    if resolver is None:
        return None
    try:
        return resolver(url, config)
    except Exception:
        return None
