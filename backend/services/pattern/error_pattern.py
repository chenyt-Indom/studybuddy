"""P3 错误归因模式（方案 5.3.3）。

价值：如果用户 70% 的错误是「审题不清」，那解法不是「多学知识」，
而是「养成圈关键词的习惯」——完全不同的建议。
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import MIN_SAMPLES_MISTAKE
from ...models import Mistake

# 六类错因（与 DB 存 code，展示用中文）
ERROR_TYPES = {
    "concept": "概念不清",
    "calculation": "计算失误",
    "careless": "粗心",
    "method": "方法不当",
    "transfer": "迁移失败",
    "timeout": "时间不够",
}

# 属于「会但没做对」的习惯类错因
HABIT_ERRORS = {"careless", "calculation", "timeout"}

HABIT_ACTIONS = {
    "careless": "做题前用笔圈出题干关键词（数字、单位、「不正确的是」）",
    "calculation": "草稿纸分区域写，每步标序号，方便回查",
    "timeout": "先扫一遍全卷，按分值分配时间，卡住超过 3 分钟就跳",
    "concept": "回到定义本身，用自己的话重述一遍，再找一个反例",
    "method": "整理「看到什么题型 → 用什么方法」的对照表",
    "transfer": "把同一个模型换三种情境各做一遍，练迁移",
}


def analyze_error_pattern(db: Session, user_id: int, subject: str) -> dict | None:
    mistakes = db.scalars(
        select(Mistake).where(Mistake.user_id == user_id, Mistake.subject_key == subject)
    ).all()
    if len(mistakes) < MIN_SAMPLES_MISTAKE:
        return {
            "insufficient": True,
            "samples": len(mistakes),
            "need": MIN_SAMPLES_MISTAKE,
            "message": f"错题样本不足（{len(mistakes)}/{MIN_SAMPLES_MISTAKE} 道），先积累再分析",
        }

    counter = Counter(m.error_type for m in mistakes if m.error_type)
    total = sum(counter.values())
    if not total:
        return {"insufficient": True, "message": "错题还没打错因标签，先补标签再分析"}

    dist = {k: round(v / total, 3) for k, v in counter.items()}
    dominant, ratio = max(dist.items(), key=lambda kv: kv[1])

    insight = None
    if ratio > 0.5:
        is_habit = dominant in HABIT_ERRORS
        insight = {
            "type": "non_knowledge_error" if is_habit else "knowledge_error",
            "severity": "high",
            "title": (
                f"你 {ratio:.0%} 的错误不是「不会」，而是「{ERROR_TYPES.get(dominant, dominant)}」"
                if is_habit
                else f"你 {ratio:.0%} 的错误集中在「{ERROR_TYPES.get(dominant, dominant)}」"
            ),
            "detail": (
                f"你的错题中 {ratio:.0%} 属于「{ERROR_TYPES.get(dominant, dominant)}」。"
                + (
                    "这说明**知识层面没问题，是习惯问题**。补知识解决不了这个问题，要改做题习惯。"
                    if is_habit
                    else "这说明**是知识本身的缺口**，不是粗心。需要回到定义重新理解。"
                )
            ),
            "action": HABIT_ACTIONS.get(dominant, "放慢速度，多检查"),
        }

    return {
        "distribution": dist,
        "distribution_cn": {ERROR_TYPES.get(k, k): v for k, v in dist.items()},
        "dominant": dominant,
        "dominant_cn": ERROR_TYPES.get(dominant, dominant),
        "samples": len(mistakes),
        "insight": insight,
    }
