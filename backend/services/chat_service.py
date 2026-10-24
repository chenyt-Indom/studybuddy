"""对话服务（方案 3.2 一次对话的完整数据流）。

关键点：一次对话触发三个引擎 —— 不是靠一个大 Prompt，
而是多个引擎各自提供上下文，最后组装。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import desc, select

from ..db import session_scope
from ..models import Conversation, KpMastery, Message
from .cross_subject.graph import cross_hint
from .forgetting.scheduler import check_review_in_chat, ensure_review_state
from .kp import candidates, match_kp_codes
from .llm.teleai import get_provider
from .memory.extractor import extract_memories, persist_memories
from .memory.recall import recall
from .memory.store import decay_all
from .pattern.miner import list_insights
from .profile.builder import (
    build_profile_context,
    refresh_psych_state,
    refresh_style,
)
from .tutor import build_tutor_prompt, SUBJECT_CN

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
    patterns = list_insights(db, user_id, subject_key)
    kp_codes = match_kp_codes(db, subject_key, user_text, top=1)
    cs = cross_hint(db, user_id, kp_codes[0]) if kp_codes else None
    ctx = build_profile_context(
        db, user_id, subject_key,
        extra={"memories": mems, "patterns": patterns, "cross_subject": cs},
    )
    ctx["kp_hint"] = kp_codes
    return ctx


async def stream_reply(user_id: int, subject_key: str, user_text: str) -> AsyncIterator[dict]:
    """SSE 数据流。yield dict：{type: meta|delta|done|error}"""
    user_text = (user_text or "").strip()
    if not user_text:
        yield {"type": "error", "message": "空消息"}
        return

    with session_scope() as db:
        conv = get_or_create_conversation(db, user_id, subject_key)
        conv_id = conv.id
        db.add(Message(conversation_id=conv_id, role="user", content=user_text))
        db.flush()
        hist = history(db, conv_id)
        ctx = build_context(db, user_id, subject_key, user_text)
        review_note = check_review_in_chat(db, user_id, subject_key)
        kp_hint = ctx.get("kp_hint") or []

    system_prompt = build_tutor_prompt(ctx, subject_key)
    messages = [{"role": "system", "content": system_prompt}] + hist

    yield {
        "type": "meta",
        "conversation_id": conv_id,
        "style": ctx.get("primary_style"),
        "weak_points": ctx.get("weak_points"),
        "memories_used": len(ctx.get("memories") or []),
        "patterns_used": len(ctx.get("patterns") or []),
        "cross_subject": ctx.get("cross_subject"),
        "kp_hint": kp_hint,
    }

    llm = get_provider()
    acc: list[str] = []
    try:
        async for delta in llm.stream(
            messages, temperature=0.7, max_tokens=2048, scene="tutor"
        ):
            acc.append(delta)
            yield {"type": "delta", "text": delta}
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

    # ⑥ 异步后处理：抽取记忆 / 更新掌握度 / 排复习 / 重算风格
    asyncio.create_task(
        _post_process(user_id, subject_key, conv_id, user_text, answer, kp_hint)
    )

    if review_note:
        yield {"type": "delta", "text": review_note}
        answer += review_note

    with session_scope() as db:
        db.add(Message(conversation_id=conv_id, role="assistant", content=answer))

    yield {"type": "done", "conversation_id": conv_id}


async def _post_process(
    user_id: int,
    subject_key: str,
    conv_id: int,
    user_text: str,
    answer: str,
    kp_hint: list[str],
) -> None:
    """异步后处理管道。失败不影响主流程。"""
    try:
        dialogue = f"学生：{user_text[:600]}\n老师：{answer[:1200]}"
        items = await extract_memories(dialogue, subject_key)

        with session_scope() as db:
            persist_memories(db, user_id, items)

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
