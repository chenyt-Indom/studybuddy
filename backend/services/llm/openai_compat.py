"""OpenAI 兼容适配器（统一支持 DeepSeek / 星辰）。

DeepSeek 要点（已核对官方文档）：
- 模型名：`deepseek-flash`（= DeepSeek-V4.1-Flash-1017）、`deepseek-v4-pro`
  旧名 `deepseek-v4-flash` 仍可调但已下线，会路由到 V4.1-Flash
- base_url（OpenAI 格式）：`https://api.deepseek.com`
- 思考模式**默认开启**，参数放 body 根：`{"thinking": {"type": "enabled"|"disabled"}}`
  强度：`{"reasoning_effort": "low"|"high"|"max"}`
- ⚠️ 思考模式下 `temperature` / `presence_penalty` / `frequency_penalty` **不生效**
  所以「要温度」的场景必须显式关掉思考，否则调参是白调
- 流式返回里 `reasoning_content`（思维链）与 `content` 同级

不用 openai SDK，直接 httpx：
  - 少一层依赖（openai SDK 在 Windows 上出现过 DLL 加载失败）
  - 流式解析自己控，出错好定位
  - 能精确控制 thinking / reasoning_effort 这种非标准字段
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ...config import PROVIDERS, THINKING_OFF_SCENES, settings
from ..secrets_store import scrub
from .base import LLMProvider

UA = "StudyBuddy/0.1 (+https://github.com/chenyt-Indom/studybuddy)"


class OpenAICompatProvider(LLMProvider):
    """所有走 OpenAI 协议的供应商都用这一套，差异只在默认值和额外参数。"""

    supports_thinking = False

    def __init__(
        self,
        provider_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.provider_name = provider_name
        self.meta = PROVIDERS[provider_name]
        self.api_key = api_key if api_key is not None else settings.key_of(provider_name)
        self.base_url = (base_url or settings.base_url).rstrip("/")
        self.model = model or settings.model
        self.timeout = timeout
        self.name = provider_name

    # ---------- 内部 ----------
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # 官方建议带 UA，避免被安全护栏拦截
            "User-Agent": UA,
        }

    def _body(self, messages: list[dict], scene: str, **kw) -> dict:
        body: dict = {
            "model": kw.get("model") or self.model,
            "messages": messages,
            "max_tokens": kw.get("max_tokens", 2048),
        }
        if self.supports_thinking:
            # 讲解类让它想（质量优先）；要控制温度的场景关掉，顺带让 temperature 生效
            use_thinking = kw.get("thinking")
            if use_thinking is None:
                use_thinking = scene not in THINKING_OFF_SCENES
            body["thinking"] = {"type": "enabled" if use_thinking else "disabled"}
            if use_thinking:
                body["reasoning_effort"] = kw.get("reasoning_effort", "low")
            else:
                body["temperature"] = kw.get("temperature", 0.7)
        else:
            body["temperature"] = kw.get("temperature", 0.7)
        return body

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _err(self, resp: httpx.Response, raw: str) -> RuntimeError:
        return RuntimeError(
            f"{self.provider_name} HTTP {resp.status_code}: "
            f"{scrub(raw, self.api_key)}"
        )

    # ---------- 对外 ----------
    async def chat(self, messages: list[dict], **kw) -> str:
        scene = kw.get("scene", "tutor")
        body = self._body(messages, scene, **kw)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(self._url("chat/completions"),
                                  headers=self._headers(), json=body)
            raw = r.text
            if r.status_code >= 400:
                raise self._err(r, raw)
            data = json.loads(raw)
        msg = data["choices"][0]["message"]
        return (msg.get("content") or "").strip()

    async def stream(self, messages: list[dict], **kw) -> AsyncIterator[dict]:
        """yield {"type": "content"|"reasoning", "text": ...}"""
        scene = kw.get("scene", "tutor")
        body = self._body(messages, scene, stream=True, **kw)
        body["stream"] = True
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", self._url("chat/completions"),
                                     headers=self._headers(), json=body) as resp:
                if resp.status_code >= 400:
                    raw = (await resp.aread()).decode("utf-8", "ignore")
                    raise self._err(resp, raw)
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
                    rc = delta.get("reasoning_content")
                    if rc:
                        yield {"type": "reasoning", "text": rc}
                    text = delta.get("content")
                    if text:
                        yield {"type": "content", "text": text}

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(self._url("models"), headers=self._headers())
            raw = r.text
            if r.status_code >= 400:
                raise self._err(r, raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"返回的不是 JSON：{scrub(raw, self.api_key)[:200]}")
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
        if not self.api_key:
            return {"ok": False, "message": "未配置 API Key"}
        try:
            models = await self.list_models()
            return {
                "ok": True,
                "base_url": self.base_url,
                "model": self.model,
                "models_count": len(models),
                "models": models[:30],
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "base_url": self.base_url,
                    "message": scrub(str(exc), self.api_key)}


class DeepSeekProvider(OpenAICompatProvider):
    supports_thinking = True

    def __init__(self, **kw) -> None:
        kw.pop("provider_name", None)
        super().__init__("deepseek", **kw)


class TeleAIProvider(OpenAICompatProvider):
    supports_thinking = False

    def __init__(self, **kw) -> None:
        kw.pop("provider_name", None)
        super().__init__("teleai", **kw)


class MockProvider(LLMProvider):
    """没有 Key 时的降级实现。

    作用：让整套 UI / 数据流 / 三个引擎在拿不到 key 的情况下也能跑通验证。
    它不会假装自己是真模型 —— 所有输出都带标记。
    """

    name = "mock"

    async def chat(self, messages: list[dict], **kw) -> str:
        return "".join([e["text"] async for e in self.stream(messages, **kw)])

    async def stream(self, messages: list[dict], **kw) -> AsyncIterator[dict]:
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = (m.get("content") or "").strip()
                break
        text = (
            "【离线演示模式】还没配置 API Key，以下为占位回复。\n\n"
            f"你问的是：{user_text[:200]}\n\n"
            "接入真实模型的步骤：\n"
            "1. 左下角「设置」→ 选供应商（推荐 DeepSeek）\n"
            "2. 粘贴 API Key（加密保存在本机，不会再回传浏览器）\n"
            "3. 点「测试连接」，通过后保存\n\n"
            "在此之前，学情看板 / 复习调度 / 错题归因 / 知识点掌握度这些"
            "**不依赖大模型**的功能都可以正常使用。"
        )
        for i in range(0, len(text), 8):
            yield {"type": "content", "text": text[i : i + 8]}

    async def list_models(self) -> list[str]:
        return []

    async def health(self) -> dict:
        return {"ok": True, "mode": "mock", "message": "未配置 API Key，当前为离线演示模式"}


def get_provider(provider_name: str | None = None) -> LLMProvider:
    """按当前配置返回可用 provider。"""
    name = provider_name or settings.provider
    if not settings.key_of(name):
        return MockProvider()
    model = settings.model if name == settings.provider else (
        (settings._slot(name).get("model") or PROVIDERS[name]["default_model"])
    )
    if not model:
        return MockProvider()  # 星辰必须自己填 model，没填就降级
    if name == "deepseek":
        return DeepSeekProvider(model=model)
    return TeleAIProvider(model=model)
