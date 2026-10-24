"""对话服务（方案 3.2 一次对话的完整数据流）。

关键点：一次对话触发三个引擎 —— 不是靠一个大 Prompt，
而是多个引擎各自提供上下文，最后组装。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import desc, select

from ..config import MAX_TOKENS_MAP, TEMPERATURE_MAP, now_context, settings
from ..db import session_scope
from ..models import Conversation, KpMastery, Message
from .cross_subject.graph import cross_hint
from .forgetting.scheduler import check_review_in_chat, ensure_review_state
from .kp import candidates, match_kp_codes
from .llm import get_provider
from .memory.extractor import extract_memories, persist_memories
from .memory.consolidate import build_doc_context, get_meta
from .memory.recall import global_memories, recall
from .memory.store import decay_all
from .pattern.miner import list_insights
from .profile.builder import (
    build_profile_context,
    refresh_psych_state,
    refresh_style,
)
from .textbook import build_textbook_context
from .tutor import build_tutor_prompt, SUBJECT_CN
from .websearch import (
    WEB_SEARCH_COUNT,
    WebSearchClient,
    build_search_query,
    format_context,
    should_search,
    sources_public,
    today_line,
)

HISTORY_TURNS = 12


def get_or_create_conversation(db, user_id: int, subject_key: str, stage: str = "senior"):
    conv = db.scalar(
        select(Conversation).where(
            Conversation.user_id == user_id, Conversation.subject_key == subject_key
        )
    )
    if conv:
        return conv
    conv = Conversation(
        user_id=user_id,
        subject_key=subject_key,
        title=f"{SUBJECT_CN.get(subject_key, subject_key)}对话",
        stage=stage,
        is_deletable=0,
    )
    db.add(conv)
    db.flush()
    return conv


def history(db, conversation_id: int, limit: int = HISTORY_TURNS) -> list[dict]:
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(desc(Message.id))
        .limit(limit)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def build_context(db, user_id: int, subject_key: str, user_text: str) -> dict:
    """②③④ 各引擎提供上下文。"""
    mems = recall(db, user_id, user_text, subject_key=subject_key, limit=5)
    # 全局记忆不依赖关键词：置顶的 / 高权重的每轮都带上
    gl = global_memories(db, user_id, limit=4)
    seen = {m["id"] for m in mems}
    mems = gl + [m for m in mems if m["id"] not in seen]
    patterns = list_insights(db, user_id, subject_key)
    kp_codes = match_kp_codes(db, subject_key, user_text, top=1)
    cs = cross_hint(db, user_id, kp_codes[0]) if kp_codes else None
    ctx = build_profile_context(
        db, user_id, subject_key,
        extra={"memories": mems, "patterns": patterns, "cross_subject": cs},
    )
    ctx["kp_hint"] = kp_codes
    # 记忆综述（档案层）：比逐条记忆更省 token，也更能体现"整体理解"
    ctx["profile_docs"] = build_doc_context(db, user_id)
    # 教材定位：对齐课本章节
    try:
        ctx["textbook"] = build_textbook_context(
            db, user_id, subject_key, user_text, kp_hints=kp_codes
        )
    except Exception:
        ctx["textbook"] = None
    return ctx


async def stream_reply(
    user_id: int,
    subject_key: str,
    user_text: str,
    use_web: bool | None = None,
) -> AsyncIterator[dict]:
    """SSE 数据流。事件类型：meta / status / search / reasoning / delta / error / done

    use_web: True 强制联网、False 强制不联网、None 交给启发式判断
    """
    user_text = (user_text or "").strip()
    if not user_text:
        yield {"type": "error", "message": "空消息"}
        return

    with session_scope() as db:
        conv = get_or_create_conversation(db, user_id, subject_key)
        conv_id = conv.id
        user_msg = Message(conversation_id=conv_id, role="user", content=user_text)
        db.add(user_msg)
        db.flush()
        user_msg_id = user_msg.id
        hist = history(db, conv_id)
        ctx = build_context(db, user_id, subject_key, user_text)
        review_note = check_review_in_chat(db, user_id, subject_key)
        kp_hint = ctx.get("kp_hint") or []

    # ---------- 时间感知 ----------
    tc = now_context()
    ctx["time_line"] = today_line()

    # ---------- 是否联网 ----------
    can_search = settings.search_enabled and settings.search_supported
    if use_web is True:
        do_search = can_search
    elif use_web is False:
        do_search = False
    else:
        do_search = can_search and should_search(user_text)

    yield {
        "type": "meta",
        "conversation_id": conv_id,
        "style": ctx.get("primary_style"),
        "weak_points": ctx.get("weak_points"),
        "memories_used": len(ctx.get("memories") or []),
        "memories_global": sum(1 for m in (ctx.get("memories") or []) if m.get("scope") == "global"),
        "memories_subject": sum(1 for m in (ctx.get("memories") or []) if m.get("scope") == "subject"),
        "memories": (ctx.get("memories") or [])[:8],
        "patterns_used": len(ctx.get("patterns") or []),
        "cross_subject": ctx.get("cross_subject"),
        "kp_hint": kp_hint,
        "time": tc["display"],
        "web": {"supported": settings.search_supported,
                "enabled": settings.search_enabled,
                "planned": do_search},
    }

    # ---------- 联网检索（在拼 Prompt 之前，结果要进上下文）----------
    search_info: dict = {"used": False, "results": [], "query": "", "message": ""}
    if do_search:
        q = build_search_query(user_text, SUBJECT_CN.get(subject_key, ""))
        yield {"type": "status", "text": f"正在联网检索：{q}"}
        res = await WebSearchClient().search(q, ori_question=user_text)
        if res.get("ok") and res.get("results"):
            picked = res["results"][:WEB_SEARCH_COUNT]
            ctx["search_context"] = format_context(picked)
            search_info = {
                "used": True,
                "query": q,
                "results": sources_public(picked),
                "message": f"检索到 {len(picked)} 条网页",
            }
        else:
            search_info = {
                "used": False,
                "query": q,
                "results": [],
                "message": res.get("message") or "没有检索到相关网页",
            }
        yield {"type": "search", **search_info}

    system_prompt = build_tutor_prompt(ctx, subject_key)
    messages = [{"role": "system", "content": system_prompt}] + hist

    llm = get_provider()
    acc: list[str] = []
    reasoning: list[str] = []
    try:
        async for evt in llm.stream(
            messages,
            temperature=TEMPERATURE_MAP["tutor"],
            max_tokens=MAX_TOKENS_MAP["tutor"],
            scene="tutor",
        ):
            if evt["type"] == "reasoning":
                reasoning.append(evt["text"])
                # 思维链原样推给前端，由前端折叠展示（可展开/收起）
                yield {"type": "reasoning", "text": evt["text"]}
            else:
                acc.append(evt["text"])
                yield {"type": "delta", "text": evt["text"]}
    except Exception as exc:  # noqa: BLE001
        msg = f"调用大模型失败：{exc}"
        yield {"type": "error", "message": msg}
        with session_scope() as db:
            db.add(
                Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=f"（调用失败）{msg}",
                )
            )
        return

    answer = "".join(acc)
    reason_text = "".join(reasoning)

    # ⑥ 异步后处理：抽取记忆 / 更新掌握度 / 排复习 / 重算风格
    asyncio.create_task(
        _post_process(user_id, subject_key, conv_id, user_text, answer, kp_hint,
                      user_msg_id)
    )

    if review_note:
        yield {"type": "delta", "text": review_note}
        answer += review_note

    with session_scope() as db:
        db.add(
            Message(
                conversation_id=conv_id,
                role="assistant",
                content=answer,
                reasoning=reason_text or None,
                sources=json.dumps(search_info["results"], ensure_ascii=False)
                if search_info["used"] else None,
            )
        )

    yield {
        "type": "done",
        "conversation_id": conv_id,
        "answer_chars": len(answer),
        "reasoning_chars": len(reason_text),
        "truncated": len(answer) < 40,  # 粗判：几乎没内容，多半是被截断
    }


async def _post_process(
    user_id: int,
    subject_key: str,
    conv_id: int,
    user_text: str,
    answer: str,
    kp_hint: list[str],
    user_msg_id: int | None = None,
) -> None:
    """异步后处理管道。失败不影响主流程。"""
    try:
        with session_scope() as db0:
            if not get_meta(db0, user_id).auto_extract:
                return  # 用户关掉了「对话记忆」
        dialogue = f"学生：{user_text[:600]}\n老师：{answer[:1200]}"
        items = await extract_memories(dialogue, subject_key)

        with session_scope() as db:
            persist_memories(db, user_id, items, source_message_id=user_msg_id)

            # 对话里提到的知识点 → 建复习状态（source=chat）
            for code in kp_hint[:2]:
                ensure_review_state(db, user_id, subject_key, code, source="chat", source_id=conv_id)
                m = db.scalar(
                    select(KpMastery).where(
                        KpMastery.user_id == user_id, KpMastery.kp_code == code
                    )
                )
                if m:
                    m.mention_rate = round(min(1.0, m.mention_rate + 0.1), 3)
                    m.updated_at = datetime.now()
                else:
                    db.add(
                        KpMastery(
                            user_id=user_id,
                            subject_key=subject_key,
                            kp_code=code,
                            mastery=0.5,
                            mention_rate=0.1,
                        )
                    )

            refresh_style(db, user_id)
            refresh_psych_state(db, user_id)
            decay_all(db, user_id)
    except Exception:
        # 后处理失败不能影响用户看到回答
        pass


def kp_candidates_for(db, subject_key: str, text: str) -> list[dict]:
    return candidates(db, subject_key, text)
