"""模式挖掘调度器（方案 5.3.5）。

不要每轮对话都跑 —— 计算成本高，且数据不够时结论不稳。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import json

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...models import Mistake, PatternInsight, QuestionRecord
from .analyzer import analyze_question_tier
from .error_pattern import analyze_error_pattern
from .gap import scan_all_gaps

SUBJECTS = ["math", "physics", "chemistry", "biology", "chinese", "english"]


def should_mine(db: Session, user_id: int, trigger: str) -> bool:
    if trigger == "exam_recorded":
        return True
    if trigger == "weekly":
        return True
    if trigger == "mistake_count":
        cutoff = datetime.now() - timedelta(days=7)
        n = db.scalar(
            select(func.count()).select_from(Mistake).where(
                Mistake.user_id == user_id, Mistake.created_at >= cutoff
            )
        )
        return (n or 0) >= 10
    return False


def mine_subject(db: Session, user_id: int, subject: str) -> list[dict]:
    """跑一个科目的全部分析器，落库并返回。"""
    found: list[dict] = []

    tier = analyze_question_tier(db, user_id, subject)
    if tier and tier.get("insight"):
        found.append(tier["insight"])

    err = analyze_error_pattern(db, user_id, subject)
    if err and err.get("insight"):
        found.append(err["insight"])

    for gap in scan_all_gaps(db, user_id, subject):
        found.append(gap["insight"])

    # 重新生成：先清掉本科目旧的洞察，避免越积越多
    db.execute(
        delete(PatternInsight).where(
            PatternInsight.user_id == user_id, PatternInsight.subject_key == subject
        )
    )
    for ins in found:
        db.add(
            PatternInsight(
                user_id=user_id,
                subject_key=subject,
                pattern_type=ins.get("type", "unknown"),
                severity=ins.get("severity", "medium"),
                title=ins.get("title", ""),
                detail=ins.get("detail", ""),
                action=ins.get("action", ""),
                data=json.dumps(ins, ensure_ascii=False),
                is_active=True,
            )
        )
    db.flush()
    return found


def mine_all(db: Session, user_id: int) -> dict:
    active = [s for s in SUBJECTS if _has_data(db, user_id, s)]
    out = {}
    for s in active:
        out[s] = mine_subject(db, user_id, s)
    return out


def _has_data(db: Session, user_id: int, subject: str) -> bool:
    n1 = db.scalar(
        select(func.count()).select_from(QuestionRecord).where(
            QuestionRecord.user_id == user_id, QuestionRecord.subject_key == subject
        )
    )
    n2 = db.scalar(
        select(func.count()).select_from(Mistake).where(
            Mistake.user_id == user_id, Mistake.subject_key == subject
        )
    )
    return bool((n1 or 0) + (n2 or 0))


def list_insights(db: Session, user_id: int, subject: str | None = None) -> list[dict]:
    q = select(PatternInsight).where(
        PatternInsight.user_id == user_id, PatternInsight.is_active == True  # noqa: E712
    )
    if subject:
        q = q.where(PatternInsight.subject_key == subject)
    rows = db.scalars(q.order_by(PatternInsight.id.desc())).all()
    return [
        {
            "id": r.id,
            "subject": r.subject_key,
            "type": r.pattern_type,
            "severity": r.severity,
            "title": r.title,
            "detail": r.detail,
            "action": r.action,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
