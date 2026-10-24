"""星辰大模型适配器（方案第四章）。

接口规格（已实测确认）：
  大陆节点   https://ai.ctaigw.cn
  版本前缀   /v1
  对话接口   POST /v1/chat/completions
  鉴权       Authorization: Bearer <AppKey>
  协议       OpenAI 兼容

⚠ 官方说明「不同区域、不同类型的模型，终端请求地址有所差异」，以控制台
  「模型广场 → 模型详情 → 调用示例」为准。这里全部可由环境变量覆盖。

不用 openai SDK，直接用 httpx：
  - 少一层依赖（openai SDK 在 Windows 上出现过 DLL 加载失败）
  - 流式解析逻辑自己控，出错好定位
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ...config import settings
from .base import LLMProvider

UA = "StudyBuddy/0.1 (+https://github.com/chenyt-Indom/studybuddy)"


class TeleAIProvider(LLMProvider):
    name = "teleai"

    def __init__(self, app_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: float = 120.0) -> None:
        self.app_key = app_key or settings.app_key
        self.base_url = (base_url or settings.base_url).rstrip("/")
        self.model = model or settings.model
        self.timeout = timeout

    # ---------- 内部 ----------
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.app_key}",
            "Content-Type": "application/json",
            # 官方建议加 User-Agent，避免被安全护栏拦截
            "User-Agent": UA,
        }

    def _payload(self, messages: list[dict], **kw) -> dict:
        return {
            "model": kw.get("model") or self.model,
            "messages": messages,
            "temperature": kw.get("temperature", 0.7),
            "max_tokens": kw.get("max_tokens", 2048),
            "stream": bool(kw.get("stream", False)),
        }

    # ---------- 对外 ----------
    async def chat(self, messages: list[dict], **kw) -> str:
        payload = self._payload(messages, stream=False, **kw)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
            )
            r.raise_for_status()
            data = r.json()
        return (data["choices"][0]["message"]["content"] or "").strip()

    async def stream(self, messages: list[dict], **kw) -> AsyncIterator[str]:
        payload = self._payload(messages, stream=True, **kw)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise RuntimeError(f"星辰 API {resp.status_code}: {body[:400]}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk in ("", "[DONE]"):
                        continue
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield text

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{self.base_url}/models", headers=self._headers())
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
        rows = data.get("data") if isinstance(data, dict) else data
        out = []
        for row in rows or []:
            if isinstance(row, dict):
                mid = row.get("id") or row.get("model")
                if mid:
                    out.append(str(mid))
            elif isinstance(row, str):
                out.append(row)
        return out

    async def health(self) -> dict:
        if not self.app_key:
            return {"ok": False, "message": "未配置 AppKey"}
        try:
            models = await self.list_models()
            return {
                "ok": True,
                "base_url": self.base_url,
                "model": self.model,
                "models_count": len(models),
                "models": models[:20],
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "base_url": self.base_url, "message": str(exc)[:300]}


class MockProvider(LLMProvider):
    """没有 AppKey 时的降级实现。

    作用：让整套 UI / 数据流 / 三个引擎在拿不到 key 的情况下也能跑通验证。
    它不会假装自己是真模型 —— 所有输出都带标记。
    """

    name = "mock"

    async def chat(self, messages: list[dict], **kw) -> str:
        return "".join([c async for c in self.stream(messages, **kw)])

    async def stream(self, messages: list[dict], **kw) -> AsyncIterator[str]:
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = (m.get("content") or "").strip()
                break
        scene = kw.get("scene", "tutor")
        text = (
            "【离线演示模式】未检测到星辰 AppKey，以下为占位回复。\n\n"
            f"你问的是：{user_text[:200]}\n\n"
            "接入真实模型的步骤：\n"
            "1. 打开左下角「设置」，填入 AppKey；\n"
            "2. 点「探测可用模型」，从返回列表里选一个 model；\n"
            "3. 保存后回到这里重新提问。\n\n"
            "在此之前，学情看板 / 复习调度 / 错题归因 / 知识点掌握度这些"
            "**不依赖大模型**的功能都可以正常使用。"
        )
        for i in range(0, len(text), 8):
            yield text[i : i + 8]

    async def list_models(self) -> list[str]:
        return ["mock-telechat-demo"]

    async def health(self) -> dict:
        return {"ok": True, "mode": "mock", "message": "未配置 AppKey，当前为离线演示模式"}


def get_provider() -> LLMProvider:
    """按当前配置返回可用 provider。"""
    if settings.app_key and settings.model:
        return TeleAIProvider()
    return MockProvider()
