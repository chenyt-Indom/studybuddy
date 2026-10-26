"""极简 MCP 客户端（streamable HTTP）。

为什么自己写而不是装 `mcp` SDK：
- 只用到四个方法（initialize / initialized 通知 / tools/list / tools/call），
  SDK 会带进来一堆 pydantic、anyio 版本约束，和本项目「零重依赖」的取向冲突
- 出问题时要能一眼看到原始 JSON-RPC 报文，SDK 把细节包住了

streamable HTTP 的几个坑（都踩过）：
1. 请求必须带 `Accept: application/json, text/event-stream`，少了会被 406
2. 响应**可能是 JSON，也可能是 SSE**（`text/event-stream`，一行一个 `data: {...}`），
   两种都要能解析
3. 服务端可能返回 `Mcp-Session-Id`，后续每个请求都要把它回传，否则状态丢失
4. `initialize` 之后要发一条 `notifications/initialized`（无 id），
   有些服务端不发就不认后面的 tools/call
"""
from __future__ import annotations

import json
from typing import Any

import httpx

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(
        self,
        url: str,
        token: str | None = None,
        timeout: float = 15.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.session_id: str | None = None
        self._id = 0
        self._initialized = False

    # ---------- 底层 ----------
    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "StudyBuddy/0.1 (+https://github.com/chenyt-Indom/studybuddy)",
        }
        if self.token:
            h.update(auth_headers(self.token))
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        h.update(self.extra_headers)
        return h

    @staticmethod
    def _parse(resp: httpx.Response, want_id: int | None) -> dict | None:
        """从 JSON 或 SSE 里取出 JSON-RPC 响应。"""
        ctype = (resp.headers.get("content-type") or "").lower()
        if "text/event-stream" in ctype:
            picked = None
            for line in resp.text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if want_id is None or obj.get("id") == want_id:
                    picked = obj
            return picked
        try:
            return resp.json()
        except Exception:
            return None

    async def _rpc(self, method: str, params: dict | None = None,
                   notify: bool = False) -> Any:
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            self._id += 1
            payload["id"] = self._id

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.url, headers=self._headers(), json=payload)

        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid

        if resp.status_code == 401:
            raise MCPError(_unauthorized_hint(resp))
        if resp.status_code >= 400:
            raise MCPError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if notify:
            return None

        data = self._parse(resp, self._id)
        if data is None:
            raise MCPError(f"响应不是有效 JSON/SSE：{resp.text[:200]}")
        if data.get("error"):
            err = data["error"]
            raise MCPError(f"{err.get('code')}: {err.get('message')}")
        return data.get("result")

    # ---------- 对外 ----------
    async def initialize(self) -> dict:
        result = await self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "StudyBuddy", "version": "0.1.10"},
        })
        # 通知型消息，失败不影响后面（有的服务端不实现）
        try:
            await self._rpc("notifications/initialized", notify=True)
        except Exception:
            pass
        self._initialized = True
        return result or {}

    async def list_tools(self) -> list[dict]:
        if not self._initialized:
            await self.initialize()
        result = await self._rpc("tools/list", {})
        return (result or {}).get("tools") or []

    async def call_tool(self, name: str, args: dict) -> dict:
        if not self._initialized:
            await self.initialize()
        result = await self._rpc("tools/call", {"name": name, "arguments": args})
        return result or {}


def auth_headers(token: str) -> dict[str, str]:
    """IMA 的凭证有两种常见形态，粘哪种都要能用：

    · 纯 token（或已经带 Bearer 前缀）→ `Authorization: Bearer <token>`
    · 直接粘 F12 里拿到的 `X-Ima-Cookie` 整串（含 IMA-TOKEN=…）→ 原样放进 `X-Ima-Cookie`
      这种最长也最省事：地址栏打开 ima.qq.com 登录后 F12 → Network → 任一 cgi-bin 请求 →
      复制 Request Headers 里的 X-Ima-Cookie 整行即可。
    """
    t = (token or "").strip()
    if not t:
        return {}
    low = t.lower()
    if low.startswith("bearer "):
        return {"Authorization": t}
    if ("ima-token" in low) or (";" in t) or ("ima-uid" in low):
        return {"X-Ima-Cookie": t}
    return {"Authorization": f"Bearer {t}"}


def _unauthorized_hint(resp: httpx.Response) -> str:
    body = (resp.text or "")[:200]
    if "empty access token" in body or "access token" in body.lower():
        return ("IMA 未授权：请求里没有 access token。"
                "请在「设置 → 教材知识库（IMA）」里填入 IMA 的访问令牌后重试。")
    return f"IMA 返回 401（未授权）：{body}"


def text_of(result: dict) -> str:
    """把 tools/call 的 content 数组拼成纯文本。"""
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
        elif isinstance(item, str):
            parts.append(item)
    return "\n".join(p for p in parts if p)
