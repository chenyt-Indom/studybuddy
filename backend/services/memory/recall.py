"""记忆召回（方案第八章）。

当前实现：字符 bigram 重叠打分 + 权重加权。对中文短句够用，
且零依赖；后续接 ChromaDB 时只需替换本文件的 recall()。
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
        target = _bigrams(m.content) | _bigrams(m.keywords)
        if not target:
            continue
        overlap = len(q & target)
        if overlap == 0:
            continue
        score = overlap / (len(q) ** 0.5) * (0.6 + 0.4 * min(1.0, m.weight))
        if subject_key and m.subject_key == subject_key:
            score *= 1.25  # 同科目优先
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
                "type": m.mtype,
                "content": m.content,
                "subject": m.subject_key,
                "weight": round(m.weight, 3),
                "score": round(score, 3),
            }
        )
    db.flush()
    return out
