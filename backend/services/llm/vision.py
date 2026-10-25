"""模型能力探测：这个模型能不能看图。

为什么不在代码里写死「deepseek-flash 支持图片」：
厂商随时可能改模型矩阵，写死的表迟早与线上不一致，然后出现
「界面允许传图 → 发出去报 400 → 用户不知道错在哪」。

权威来源就是官方 `GET /v1/models` 里的 `input_modalities`：
  deepseek-flash   → ["text", "image"]   ← 能看图
  deepseek-v4-pro  → ["text"]            ← 不能看图
所以这里现查、缓存 10 分钟，查不到就**放行让 API 自己报错**（附提示），
而不是假装支持或不给用。
"""
from __future__ import annotations

import time

import httpx

from ...config import settings

_TTL = 600.0
_cache: dict[str, tuple[float, bool, str]] = {}


async def _probe(provider: str, model: str) -> tuple[bool, str]:
    key = settings.key_of(provider)
    if not key:
        return False, "当前是离线演示模式（没有 API Key），看不了图片"
    base = (settings.base_url or "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(f"{base}/models", headers={"Authorization": f"Bearer {key}",
                                                       "User-Agent": "StudyBuddy/0.1"})
            if r.status_code >= 400:
                return True, ""   # 探测失败不拦人，交给真正调用时报错
            rows = (r.json() or {}).get("data") or []
    except Exception:
        return True, ""

    for row in rows:
        if not isinstance(row, dict) or row.get("id") != model:
            continue
        mods = row.get("input_modalities") or []
        if not mods:            # 老接口不返回能力字段 → 不拦
            return True, ""
        if "image" in mods:
            return True, ""
        return False, (
            f"当前模型「{model}」不支持图片输入（官方能力：{'、'.join(mods)}）。"
            "请到「设置」把模型换成 deepseek-flash 再试。"
        )
    return True, ""


async def image_support(provider: str | None = None,
                        model: str | None = None) -> tuple[bool, str]:
    """(是否支持看图, 不支持时的说明)。"""
    provider = provider or settings.provider
    model = model or settings.model
    ck = f"{provider}|{model}"
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1], hit[2]
    ok, note = await _probe(provider, model)
    _cache[ck] = (time.time(), ok, note)
    return ok, note


def forget() -> None:
    """设置变更（换模型/换 Key）后调用，别让旧结论粘住。"""
    _cache.clear()
