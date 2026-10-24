"""记忆召回（方案第八章）。

两层一起召回：
  · 全局记忆（scope=global）无条件参与候选 —— 它描述"这个人"，任何科目都相关
  · 科目记忆（scope=subject）只召回当前科目的

用户判定为「不准确」的记忆**直接不参与召回** —— 它已经被证伪了，
继续往 Prompt 里塞只会污染回答。这是「可核查」的实际意义。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Memory
from .store import _bigrams


def recall(
    db: Session,
    user_id: int,
    query: str,
    subject_key: str | None = None,
    limit: int = 6,
    min_score: float = 0.08,
) -> list[dict]:
    rows = db.scalars(select(Memory).where(Memory.user_id == user_id)).all()
    if not rows:
        return []

    q = _bigrams(query)
    if not q:
        return []

    scored = []
    for m in rows:
        # 被用户判定为错的，不再使用
        if m.accuracy == "wrong":
            continue
        # 科目记忆只取当前科目；全局记忆都参与
        if m.scope == "subject" and subject_key and m.subject_key != subject_key:
            continue
        if m.scope == "subject" and not subject_key:
            continue

        target = _bigrams(m.content) | _bigrams(m.keywords)
        if not target:
            continue
        overlap = len(q & target)
        if overlap == 0 and not m.pinned:
            continue

        score = (overlap / (len(q) ** 0.5)) * (0.6 + 0.4 * min(1.0, m.weight))
        # 用户确认过的更可信；置顶的是用户主动认可的重点
        if m.accuracy == "correct":
            score *= 1.4
        if m.pinned:
            score *= 1.3
        score *= 0.7 + 0.3 * max(0.0, min(1.0, m.confidence))

        if m.scope == "global":
            # 全局记忆哪怕关键词命中少，也值得带进去（它管"怎么教这个人"）
            score = max(score, 0.06) if m.pinned or m.accuracy == "correct" else score
        if score >= min_score:
            scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    now = datetime.now()
    for score, m in scored[:limit]:
        m.hits += 1
        m.last_used_at = now
        out.append(
            {
                "id": m.id,
                "scope": m.scope,
                "type": m.mtype,
                "content": m.content,
                "subject": m.subject_key,
                "weight": round(m.weight, 3),
                "confidence": round(m.confidence, 3),
                "accuracy": m.accuracy,
                "score": round(score, 3),
            }
        )
    db.flush()
    return out


def global_memories(db: Session, user_id: int, limit: int = 8) -> list[dict]:
    """置顶 + 高权重的全局记忆。用于每轮都注入（不依赖关键词命中）。"""
    rows = db.scalars(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.scope == "global",
               Memory.accuracy != "wrong")
    ).all()
    rows.sort(key=lambda m: (m.pinned, m.weight, m.confidence), reverse=True)
    return [
        {
            "id": m.id,
            "scope": "global",
            "type": m.mtype,
            "content": m.content,
            "subject": None,
            "weight": round(m.weight, 3),
            "confidence": round(m.confidence, 3),
            "accuracy": m.accuracy,
            "pinned": m.pinned,
            "score": 1.0,
        }
        for m in rows[:limit]
    ]
