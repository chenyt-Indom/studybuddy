"""P1 题型分层分析（方案 5.3.2）——最直观、最有冲击力的洞察。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import MIN_SAMPLES_QUESTION
from ...models import QuestionRecord


def analyze_question_tier(db: Session, user_id: int, subject: str) -> dict | None:
    """需要录入成绩时带上每题对错。只有总分做不了这个分析。"""
    records = db.scalars(
        select(QuestionRecord).where(
            QuestionRecord.user_id == user_id, QuestionRecord.subject_key == subject
        )
    ).all()
    if len(records) < MIN_SAMPLES_QUESTION:
        return {
            "insufficient": True,
            "samples": len(records),
            "need": MIN_SAMPLES_QUESTION,
            "message": f"样本不足（{len(records)}/{MIN_SAMPLES_QUESTION} 题），不下结论，避免误导",
        }

    # 按题位分组（假设试卷结构稳定）
    tiers: dict[str, list[QuestionRecord]] = {
        "基础题": [r for r in records if 1 <= r.q_no <= 7],
        "中档题": [r for r in records if 8 <= r.q_no <= 12],
        "压轴题": [r for r in records if r.q_no >= 13],
    }
    result: dict[str, dict] = {}
    for name, recs in tiers.items():
        if not recs:
            continue
        correct = sum(1 for r in recs if r.is_correct)
        result[name] = {
            "accuracy": round(correct / len(recs), 3),
            "count": len(recs),
        }

    insight = None
    basic = result.get("基础题", {}).get("accuracy", 0)
    mid = result.get("中档题", {}).get("accuracy")
    if basic > 0.85 and mid is not None and mid < 0.5:
        insight = {
            "type": "tier_gap",
            "severity": "high",
            "title": "中档题是主要失分区",
            "detail": (
                f"基础题正确率 {basic:.0%}，但中档题只有 {mid:.0%}。"
                "这说明知识能听懂，但**中档题的训练量不够**，还没形成解题的肌肉记忆。"
            ),
            "action": "建议每天专练 3 道中档题，持续两周。压轴题暂时放一放。",
        }
    elif mid is not None and mid < 0.4 and basic <= 0.85:
        insight = {
            "type": "base_weak",
            "severity": "high",
            "title": "基础和中档同时塌陷",
            "detail": (
                f"基础题只有 {basic:.0%}，中档题 {mid:.0%}。"
                "这不是训练量问题，而是**基础还没打通**，先别碰难题。"
            ),
            "action": "回到课本例题，先把基础题正确率拉到 85% 以上。",
        }

    return {"tiers": result, "insight": insight, "samples": len(records)}
