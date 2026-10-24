"""记忆存储与衰减（方案第八章）。

注意：这一版用 SQLite + 字符 n-gram 做召回，没有引入 ChromaDB。
接口按 VectorStore 的语义留好，后续换成向量检索时只改 recall.py。
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Memory

# 衰减：半年未被用到，权重掉一半（半衰期模型）
HALF_LIFE_DAYS = 180.0


def add_memory(
    db: Session,
    user_id: int,
    content: str,
    mtype: str = "observation",
    subject_key: str | None = None,
    keywords: str = "",
) -> Memory | None:
    content = (content or "").strip()
    if not content:
        return None
    # 去重：内容高度相似就不重复写
    exists = db.scalar(
        select(Memory).where(Memory.user_id == user_id, Memory.content == content)
    )
    if exists:
        exists.weight = min(2.0, exists.weight + 0.2)
        db.flush()
        return exists
    m = Memory(
        user_id=user_id,
        subject_key=subject_key,
        mtype=mtype,
        content=content,
        keywords=keywords,
        weight=1.0,
    )
    db.add(m)
    db.flush()
    return m


def decay_all(db: Session, user_id: int, now: datetime | None = None) -> int:
    """按时间衰减权重；低于阈值标记为弱记忆（不物理删除，便于回溯）。"""
    now = now or datetime.now()
    rows = db.scalars(select(Memory).where(Memory.user_id == user_id)).all()
    n = 0
    for m in rows:
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


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\s\W_]+", "", text or "")
    if len(t) < 2:
        return {t} if t else set()
    return {t[i : i + 2] for i in range(len(t) - 1)}
