"""外部教材知识库（IMA）适配层。

背景：IMA（ima.qq.com）里挂了从小学到大学的教材知识库，通过 MCP 暴露
（`https://ima.qq.com/mcp`，streamable HTTP，需要 access token）。

这里只做三件事：
1. **探明工具面**：IMA 的工具名不对外公开，所以先 `tools/list`，
   再按名字/描述挑「检索类」工具（不是写死的 `ima_search`，避免它一改名就崩）
2. **归一化**：把各家可能的返回（structuredContent / JSON 文本 / 纯文本）
   统一成 `{title, snippet, url, source}`
3. **降级**：没有 token、超时、401 —— 一律返回空并给出原因，**绝不阻塞对话**

版权口径：只保存**检索片段 + 出处**，不落整本正文、不对外分发。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from .mcp_client import MCPClient, MCPError, text_of

IMA_URL = os.getenv("STUDYBUDDY_IMA_URL", "https://ima.qq.com/mcp")

# 名字里出现这些词，认为它可能是「检索」工具（后面还会按描述再打一次分）
_SEARCH_WORDS = ("search", "retrieve", "query", "lookup", "recall", "ask", "chat", "qa")
_WRITE_WORDS = ("create", "add", "update", "delete", "remove", "upload", "import", "write")
_QUERY_KEYS = ("query", "q", "keyword", "keywords", "text", "question", "prompt", "search_query")
_TOPK_KEYS = ("top_k", "topk", "count", "limit", "size", "num", "n", "k", "max_results")
_MAX_SNIPPET = 700          # 单条片段上限（防止把整节课塞进 prompt）
_MAX_CONTEXT = 2400         # 注入 prompt 的总字数上限


def _client(timeout: float = 12.0) -> MCPClient:
    return MCPClient(IMA_URL, token=settings.ima_token, timeout=timeout)


# ---------------------------------------------------------------- 工具发现
def _score_tool(tool: dict) -> int:
    name = (tool.get("name") or "").lower()
    desc = (tool.get("description") or "").lower()
    score = 0
    for w in _SEARCH_WORDS:
        if w in name:
            score += 4
            break
    for w in ("检索", "搜索", "查询", "问答"):
        if w in desc or w in (tool.get("description") or ""):
            score += 3
            break
    for w in _WRITE_WORDS:
        if w in name:
            score -= 6
            break
    if tool.get("inputSchema"):
        score += 1
    return score


def pick_search_tool(tools: list[dict]) -> dict | None:
    if not tools:
        return None
    ranked = sorted(tools, key=_score_tool, reverse=True)
    best = ranked[0]
    return best if _score_tool(best) > 0 else None


def _schema_props(tool: dict) -> dict:
    return ((tool.get("inputSchema") or {}).get("properties") or {})


def build_args(tool: dict, query: str, top_k: int = 4) -> dict:
    """按工具自己的 inputSchema 拼参数，而不是猜死一个 query 字段。"""
    props = _schema_props(tool)
    args: dict = {}
    qkey = next((k for k in _QUERY_KEYS if k in props), None)
    if qkey is None:
        # schema 没声明（有些服务端省略）→ 用最常见的名字兜底
        qkey = "query"
    args[qkey] = query

    for k in _TOPK_KEYS:
        if k in props:
            args[k] = top_k
            break
    return args


# ---------------------------------------------------------------- 归一化
def _norm_item(raw: dict) -> dict | None:
    title = (raw.get("title") or raw.get("name") or raw.get("doc_name")
             or raw.get("file_name") or "").strip()
    body = (raw.get("snippet") or raw.get("summary") or raw.get("content")
            or raw.get("text") or raw.get("chunk") or "").strip()
    if not body:
        return None
    url = (raw.get("url") or raw.get("link") or raw.get("doc_url") or "").strip()
    src = (raw.get("source") or raw.get("source_name") or raw.get("kb_name")
           or raw.get("knowledge_base") or "").strip()
    return {
        "title": title or "教材片段",
        "snippet": body[:_MAX_SNIPPET],
        "url": url,
        "source": src,
    }


def normalize(result: dict, limit: int = 4) -> list[dict]:
    """三种返回形态都要能吃下：structuredContent / JSON 文本 / 纯文本。"""
    out: list[dict] = []

    sc = result.get("structuredContent")
    if isinstance(sc, dict):
        for key in ("results", "items", "docs", "chunks", "data", "list"):
            rows = sc.get(key)
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict):
                        item = _norm_item(r)
                        if item:
                            out.append(item)
                break

    if not out:
        text = text_of(result).strip()
        if text:
            obj = None
            if text[:1] in "[{":
                try:
                    obj = json.loads(text)
                except Exception:
                    obj = None
            if isinstance(obj, dict):
                for key in ("results", "items", "docs", "chunks", "data", "list"):
                    if isinstance(obj.get(key), list):
                        for r in obj[key]:
                            if isinstance(r, dict):
                                item = _norm_item(r)
                                if item:
                                    out.append(item)
                        break
                else:
                    item = _norm_item(obj)
                    if item:
                        out.append(item)
            elif isinstance(obj, list):
                for r in obj:
                    if isinstance(r, dict):
                        item = _norm_item(r)
                        if item:
                            out.append(item)
            if not out:
                out.append({"title": "教材检索结果", "snippet": text[:_MAX_SNIPPET],
                            "url": "", "source": "IMA"})
    return out[:limit]


# ---------------------------------------------------------------- 对外能力
async def probe() -> dict:
    """诊断：有没有 token、能连上吗、能看见哪些工具、挑了哪个当检索用。"""
    if not settings.ima_token:
        return {"ok": False, "reason": "未配置 IMA Token",
                "hint": "在「设置 → 教材知识库（IMA）」里填入访问令牌"}
    try:
        c = _client()
        info = await c.initialize()
        tools = await c.list_tools()
    except MCPError as exc:
        return {"ok": False, "reason": str(exc), "tools": []}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"连接失败：{exc}", "tools": []}

    picked = pick_search_tool(tools)
    return {
        "ok": bool(picked),
        "server": (info.get("serverInfo") or {}).get("name") or "ima",
        "protocol": info.get("protocolVersion"),
        "tools": [{"name": t.get("name"), "description": (t.get("description") or "")[:90],
                   "args": list(_schema_props(t).keys())} for t in tools],
        "picked": picked.get("name") if picked else None,
        "reason": "" if picked else "连上了，但没找到「检索类」工具（见 tools 列表）",
    }


async def search(query: str, limit: int = 4) -> dict:
    """实时检索。返回 {ok, items, reason}；任何异常都不抛给上层。"""
    if not settings.ima_token:
        return {"ok": False, "items": [], "reason": "未配置 IMA Token"}
    if not (query or "").strip():
        return {"ok": False, "items": [], "reason": "空查询"}
    try:
        c = _client()
        await c.initialize()
        tools = await c.list_tools()
        tool = pick_search_tool(tools)
        if not tool:
            return {"ok": False, "items": [], "reason": "IMA 未提供检索类工具"}
        res = await c.call_tool(tool["name"], build_args(tool, query, limit))
        items = normalize(res, limit)
        if not items:
            return {"ok": True, "items": [], "reason": "没有检索到相关片段"}
        return {"ok": True, "items": items, "reason": "", "tool": tool.get("name")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "items": [], "reason": str(exc)}


# ---------------------------------------------------------------- 本地缓存
def snippet_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def save_snippets(db: Session, user_id: int, items: list[dict], *,
                  stage: str = "", grade: str = "", subject: str = "",
                  query: str = "") -> int:
    """落库（幂等：同一条片段不重复存）。只存片段 + 出处。"""
    from ..models import KbSnippet

    have = {
        h for (h,) in db.execute(
            select(KbSnippet.hash).where(KbSnippet.user_id == user_id)
        ).all()
    }
    added = 0
    for it in items:
        text = (it.get("snippet") or "").strip()
        if not text:
            continue
        h = snippet_hash(it.get("title", "") + "|" + text)
        if h in have:
            continue
        db.add(KbSnippet(
            user_id=user_id, hash=h, title=(it.get("title") or "")[:200],
            snippet=text, url=(it.get("url") or "")[:500],
            source=(it.get("source") or "IMA")[:80],
            stage=stage, grade=grade, subject_key=subject, query=query[:200],
        ))
        have.add(h)
        added += 1
    db.flush()
    return added


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def local_search(db: Session, user_id: int, query: str, *,
                 subject: str = "", stage: str = "", limit: int = 4) -> list[dict]:
    """本地片段检索（char bigram 重叠打分）。换向量检索时只改这里。"""
    from ..models import KbSnippet

    rows = db.scalars(
        select(KbSnippet).where(KbSnippet.user_id == user_id)
    ).all()
    if not rows:
        return []
    qb = _bigrams(query)
    scored = []
    for r in rows:
        if subject and r.subject_key and r.subject_key != subject:
            continue
        if stage and r.stage and r.stage != stage:
            continue
        tb = _bigrams((r.title or "") + (r.snippet or ""))
        if not qb or not tb:
            continue
        hit = len(qb & tb)
        if hit == 0:
            continue
        scored.append((hit / (len(qb) ** 0.5), r))
    scored.sort(key=lambda x: -x[0])
    return [
        {"title": r.title, "snippet": r.snippet, "url": r.url, "source": r.source,
         "grade": r.grade, "subject": r.subject_key}
        for _, r in scored[:limit]
    ]


async def context(user_id: int, subject_key: str, text: str, *,
                  stage: str = "senior", grade: str = "senior_1",
                  limit: int = 3) -> dict | None:
    """给对话用的教材上下文：优先实时 IMA，其次本地缓存；都没有就返回 None。"""
    if not settings.ima_enabled:
        return None

    q = _query_for(text, subject_key)
    items: list[dict] = []
    origin = ""

    if settings.ima_token:
        res = await search(q, limit=limit)
        if res.get("items"):
            items, origin = res["items"], "live"

    if not items:
        from ..db import session_scope
        with session_scope() as db:
            items = local_search(db, user_id, q, subject=subject_key,
                                 stage=stage, limit=limit)
        if items:
            origin = "local"

    if not items:
        return None
    return {"items": items, "origin": origin, "query": q}


def _query_for(text: str, subject_key: str) -> str:
    cn = {"math": "数学", "physics": "物理", "chemistry": "化学",
          "biology": "生物", "chinese": "语文", "english": "英语"}.get(subject_key, "")
    t = re.sub(r"\s+", " ", (text or "")).strip()
    return f"{cn} {t[:60]} 教材".strip()


def render_context(ctx: dict | None) -> str:
    """拼成 prompt 里的一段。总字数封顶，避免挤掉别的上下文。"""
    if not ctx or not ctx.get("items"):
        return ""
    lines = []
    total = 0
    for i, it in enumerate(ctx["items"], 1):
        head = it.get("title") or "教材片段"
        src = it.get("source") or ""
        body = (it.get("snippet") or "").replace("\n", " ").strip()
        block = f"[{i}] {head}" + (f"（{src}）" if src else "") + f"\n{body}"
        if total + len(block) > _MAX_CONTEXT:
            break
        lines.append(block)
        total += len(block)
    return "\n\n".join(lines)
