"""知识点掌握度计算引擎（方案 B34）。

掌握度不是拍脑袋给的，是三路证据的加权：
  ① 逐题正确率（最硬）
  ② 错题错误率（负向）
  ③ 复习表现（SM-2 评分已单独平滑，这里只作修正）
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KpMastery, QuestionRecord


def get_mastery(db: Session, user_id: int, kp_code: str) -> float | None:
    m = db.scalar(
        select(KpMastery).where(
            KpMastery.user_id == user_id, KpMastery.kp_code == kp_code
        )
    )
    return m.mastery if m else None


def upsert(
    db: Session,
    user_id: int,
    subject_key: str,
    kp_code: str,
    mastery: float | None = None,
    score_rate: float | None = None,
    error_rate: float | None = None,
) -> KpMastery:
    m = db.scalar(
        select(KpMastery).where(
            KpMastery.user_id == user_id, KpMastery.kp_code == kp_code
        )
    )
    if not m:
        m = KpMastery(user_id=user_id, subject_key=subject_key, kp_code=kp_code, mastery=0.5)
        db.add(m)
        db.flush()
    if mastery is not None:
        m.mastery = round(max(0.0, min(1.0, mastery)), 4)
    if score_rate is not None:
        m.score_rate = round(max(0.0, min(1.0, score_rate)), 4)
    if error_rate is not None:
        m.error_rate = round(max(0.0, min(1.0, error_rate)), 4)
    return m


def recompute_from_records(db: Session, user_id: int, subject_key: str) -> int:
    """从逐题记录重算掌握度。返回更新的知识点个数。"""
    rows = db.scalars(
        select(QuestionRecord).where(
            QuestionRecord.user_id == user_id,
            QuestionRecord.subject_key == subject_key,
            QuestionRecord.kp_code.is_not(None),
        )
    ).all()
    agg: dict[str, list[bool]] = {}
    for r in rows:
        agg.setdefault(r.kp_code, []).append(bool(r.is_correct))

    n = 0
    for kp_code, flags in agg.items():
        correct = sum(1 for f in flags if f)
        rate = correct / len(flags)
        # 正确率直接作为掌握度主证据；样本少时向 0.5 收缩，避免 1 道题就判满
        k = len(flags)
        shrunk = (rate * k + 0.5 * 2) / (k + 2)
        upsert(
            db, user_id, subject_key, kp_code,
            mastery=shrunk, score_rate=rate, error_rate=1 - rate,
        )
        n += 1
    db.flush()
    return n
