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
from ..models import Conversation, KpMastery, Message, UserProfile
from . import attachments as attach
from .cross_subject.graph import cross_hint
from .forgetting.scheduler import check_review_in_chat, ensure_review_state
from .kp import candidates, hints_for, match_kp_codes
from .llm import get_provider
from .llm.vision import image_support
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
    out = []
    for m in reversed(rows):
        try:
            atts = json.loads(m.attachments) if m.attachments else []
        except Exception:
            atts = []
        out.append({"role": m.role, "content": m.content, "attachments": atts})
    return out


def _content_with_images(text: str, urls: list[str]) -> str | list[dict]:
    """OpenAI 兼容的多模态消息体：纯文本时仍给字符串（省得模型不认数组）。"""
    if not urls:
        return text
    return [{"type": "text", "text": text or "请看图片"} ] + [
        {"type": "image_url", "image_url": {"url": u}} for u in urls
    ]


def build_context(db, user_id: int, subject_key: str, user_text: str) -> dict:
    """②③④ 各引擎提供上下文。"""
    mems = recall(db, user_id, user_text, subject_key=subject_key, limit=5)
    # 全局记忆不依赖关键词：置顶的 / 高权重的每轮都带上
    gl = global_memories(db, user_id, limit=4)
    seen = {m["id"] for m in mems}
    mems = gl + [m for m in mems if m["id"] not in seen]
    patterns = list_insights(db, user_id, subject_key)
    # 知识点召回按学生年级收口：高一不该被召回导数、圆锥曲线（专精化的一部分）
    prof = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    grade = (prof.grade if prof else "") or "senior_1"
    kp_codes = match_kp_codes(db, subject_key, user_text, top=2, max_grade=grade)
    cs = None
    for code in kp_codes:
        h = cross_hint(db, user_id, code)
        if h and (cs is None or h.get("strength", 0) > cs.get("strength", 0)):
            cs = h
    ctx = build_profile_context(
        db, user_id, subject_key,
        extra={"memories": mems, "patterns": patterns, "cross_subject": cs},
    )
    ctx["kp_hint"] = kp_codes
    # 知识点提示：要点 / 常见易错 / 记忆锚点（讲解里直接能用）
    ctx["kp_hints"] = hints_for(db, kp_codes)
    ctx["grade"] = grade
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
    attachments: list[str] | None = None,
) -> AsyncIterator[dict]:
    """SSE 数据流。事件类型：meta / status / search / reasoning / delta / error / done

    use_web: True 强制联网、False 强制不联网、None 交给启发式判断
    attachments: 图片附件 id（题目截图/手写照片），最多 4 张
    """
    user_text = (user_text or "").strip()
    wanted = [a for a in (attachments or []) if a][: attach.MAX_IMAGES_PER_MSG]
    if not user_text and not wanted:
        yield {"type": "error", "message": "空消息"}
        return

    # 只认自己的图（resolve 会校验文件名里的 user_id），失效的静默丢掉
    valid = [a for a in wanted if attach.resolve(user_id, a)]
    image_urls = [u for u in (attach.data_url(user_id, a) for a in valid) if u]
    # 只发图不打字也要能问：给一句默认问法，后续所有引擎（知识点/记忆/联网）都有字可用
    display_text = user_text or "（见图片）请帮我讲解这道题"

    img_blocked = ""
    if image_urls:
        ok, note = await image_support()
        if not ok:
            img_blocked = note or "当前模型不支持图片输入，请换用支持看图的模型"

    with session_scope() as db:
        conv = get_or_create_conversation(db, user_id, subject_key)
        conv_id = conv.id
        user_msg = Message(
            conversation_id=conv_id, role="user", content=display_text,
            attachments=json.dumps(valid, ensure_ascii=False) if valid else None,
        )
        db.add(user_msg)
        db.flush()
        user_msg_id = user_msg.id
        hist = history(db, conv_id)
        ctx = build_context(db, user_id, subject_key, display_text)
        review_note = check_review_in_chat(db, user_id, subject_key)
        kp_hint = ctx.get("kp_hint") or []

        # 本次消息带上图片；再往前找最近一条带图的提问补上，
        # 这样追问（"那第二步为什么这么算"）时模型还看得到原题。
        # 只补一条，避免每轮都重传导致 token 越滚越大。
        prev_img = None
        for m in reversed(hist[:-1][-6:]):
            if m["role"] == "user" and m.get("attachments"):
                prev_img = m
                break
        chat_msgs: list[dict] = []
        for m in hist:
            if m is hist[-1]:
                chat_msgs.append({"role": "user",
                                  "content": _content_with_images(display_text, image_urls)})
                continue
            urls: list[str] = []
            if prev_img is not None and m is prev_img:
                urls = [u for u in (attach.data_url(user_id, a)
                                    for a in m.get("attachments") or []) if u]
            chat_msgs.append({"role": m["role"],
                              "content": _content_with_images(m["content"], urls)})

    ctx["images"] = len(image_urls)

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
        do_search = can_search and should_search(display_text)

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
        q = build_search_query(display_text, SUBJECT_CN.get(subject_key, ""))
        yield {"type": "status", "text": f"正在联网检索：{q}"}
        res = await WebSearchClient().search(q, ori_question=display_text)
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
    messages = [{"role": "system", "content": system_prompt}] + chat_msgs

    if img_blocked:
        yield {"type": "error", "message": img_blocked}
        with session_scope() as db:
            db.add(Message(conversation_id=conv_id, role="assistant",
                           content=f"（图片没能处理）{img_blocked}"))
        return
    if image_urls:
        yield {"type": "status", "text": f"正在读图（{len(image_urls)} 张）并讲解…"}

    llm = get_provider()
    acc: list[str] = []
    reasoning: list[str] = []
    finish_reason = ""
    try:
        async for evt in llm.stream(
            messages,
            temperature=TEMPERATURE_MAP["tutor"],
            max_tokens=MAX_TOKENS_MAP["tutor"],
            scene="tutor",
        ):
            if evt["type"] == "finish":
                # 以官方 finish_reason 为准判断是否被截断。
                # 之前只看字数，答「红色」这种极短正确回答会被误报成"疑似截断"。
                finish_reason = evt.get("reason") or ""
            elif evt["type"] == "reasoning":
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
        _post_process(user_id, subject_key, conv_id, display_text, answer, kp_hint,
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
        # 有 finish_reason 就信它；拿不到才退回字数粗判
        "truncated": (finish_reason == "length") if finish_reason else (len(answer) < 40),
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
