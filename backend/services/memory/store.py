"""记忆存储与衰减（方案第八章）。

两种记忆：
  scope='global'  → 跨科目，关于这个人本身
  scope='subject' → 单科记忆

去重不靠精确字符串匹配，而用字符 bigram 相似度 —— 模型每次措辞都不同，
精确匹配根本挡不住重复。
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Memory

# 衰减：半年未被用到，权重掉一半（半衰期模型）
HALF_LIFE_DAYS = 180.0
# 相似度阈值：超过就认为是同一条，合并而不是新增
DEDUPE_THRESHOLD = 0.62


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\s\W_]+", "", text or "")
    if len(t) < 2:
        return {t} if t else set()
    return {t[i : i + 2] for i in range(len(t) - 1)}


def similarity(a: str, b: str) -> float:
    """Jaccard 相似度。中文短句上够用，且零依赖。"""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def add_memory(
    db: Session,
    user_id: int,
    content: str,
    mtype: str = "observation",
    scope: str = "subject",
    subject_key: str | None = None,
    keywords: str = "",
    evidence: str | None = None,
    source: str = "chat",
    source_message_id: int | None = None,
    confidence: float = 0.6,
) -> Memory | None:
    content = (content or "").strip()
    if not content:
        return None
    if scope not in ("global", "subject"):
        scope = "subject"
    if scope == "global":
        subject_key = None

    # 只在同一层里比：全局记忆不和分科记忆合并
    q = select(Memory).where(Memory.user_id == user_id, Memory.scope == scope)
    if scope == "subject":
        q = q.where(Memory.subject_key == subject_key)
    existing = db.scalars(q).all()

    best, best_sim = None, 0.0
    for m in existing:
        s = similarity(content, m.content)
        if s > best_sim:
            best, best_sim = m, s

    if best is not None and best_sim >= DEDUPE_THRESHOLD:
        # 合并：内容取更长的（信息更多），权重和置信度取高，补证据
        if len(content) > len(best.content):
            best.content = content
        best.weight = round(min(2.0, best.weight + 0.15), 3)
        best.confidence = round(max(best.confidence, confidence), 3)
        best.hits += 1
        if evidence and (not best.evidence or len(evidence) > len(best.evidence)):
            best.evidence = evidence
        best.updated_at = datetime.now()
        db.flush()
        return best

    m = Memory(
        user_id=user_id,
        scope=scope,
        subject_key=subject_key,
        mtype=mtype,
        content=content,
        evidence=evidence,
        source=source,
        source_message_id=source_message_id,
        confidence=round(max(0.0, min(1.0, confidence)), 3),
        keywords=keywords,
        weight=1.0,
        accuracy="unverified",
    )
    db.add(m)
    db.flush()
    return m


def decay_all(db: Session, user_id: int, now: datetime | None = None) -> int:
    """按时间衰减权重；用户的判定会覆盖衰减（标为正确的不轻易掉）。"""
    now = now or datetime.now()
    rows = db.scalars(select(Memory).where(Memory.user_id == user_id)).all()
    n = 0
    for m in rows:
        if m.pinned or m.accuracy == "correct":
            continue
        ref = m.last_used_at or m.created_at
        if not ref:
            continue
        days = (now - ref).total_seconds() / 86400
        factor = 0.5 ** (days / HALF_LIFE_DAYS)
        new_w = m.weight * factor
        if abs(new_w - m.weight) > 1e-6:
            m.weight = round(new_w, 4)
            n += 1
    db.flush()
    return n


def stats(db: Session, user_id: int) -> dict:
    """记忆库准确度统计 —— 供「透明可核查」页面用。"""
    rows = db.scalars(select(Memory).where(Memory.user_id == user_id)).all()
    total = len(rows)
    g = sum(1 for m in rows if m.scope == "global")
    correct = sum(1 for m in rows if m.accuracy == "correct")
    wrong = sum(1 for m in rows if m.accuracy == "wrong")
    unverified = total - correct - wrong
    judged = correct + wrong

    by_subject: dict[str, dict] = {}
    for m in rows:
        if m.scope != "subject" or not m.subject_key:
            continue
        d = by_subject.setdefault(m.subject_key, {"total": 0, "correct": 0, "wrong": 0})
        d["total"] += 1
        if m.accuracy == "correct":
            d["correct"] += 1
        elif m.accuracy == "wrong":
            d["wrong"] += 1

    return {
        "total": total,
        "global": g,
        "subject": total - g,
        "correct": correct,
        "wrong": wrong,
        "unverified": unverified,
        "judged": judged,
        # 只在有判定时才算准确率，否则返回 None 而不是假装 100%
        "accuracy_rate": round(correct / judged, 3) if judged else None,
        "by_subject": by_subject,
    }
