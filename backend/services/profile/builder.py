"""四维画像构建（方案 5.1 / 5.4）。

画像四个维度：
  ① 学业基础  成绩 + 错题 + 对话
  ② 认知风格  对话行为推断
  ③ 学习习惯  行为数据
  ④ 心理状态  对话情绪分析
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ...models import Conversation, KnowledgePoint, KpMastery, Message, UserProfile
from .style_infer import infer_style, pick_explain_style

# 情绪词表（心理状态粗估；后续可换模型判断）
ANXIETY_WORDS = ["焦虑", "紧张", "怕", "完了", "崩溃", "来不及", "考不好", "没希望", "放弃", "烦"]
CONFIDENCE_WORDS = ["会了", "懂了", "明白了", "简单", "没问题", "搞定了", "有把握"]
DEFEAT_WORDS = ["不会", "太难", "学不会", "不行", "废了", "听不懂", "懵"]


def get_or_create_profile(db: Session, user_id: int) -> UserProfile:
    p = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if p:
        return p
    p = UserProfile(user_id=user_id)
    db.add(p)
    db.flush()
    return p


def recent_user_texts(db: Session, user_id: int, limit: int = 60) -> list[str]:
    rows = db.scalars(
        select(Message.content)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id, Message.role == "user")
        .order_by(desc(Message.id))
        .limit(limit)
    ).all()
    return [r for r in rows if r]


def refresh_style(db: Session, user_id: int) -> dict:
    """重算认知风格并写回画像。"""
    texts = recent_user_texts(db, user_id)
    result = infer_style(texts)
    p = get_or_create_profile(db, user_id)
    p.style_scores = json.dumps(result["scores"], ensure_ascii=False)
    p.primary_style = result["primary"]
    p.style_confidence = result["confidence"]
    db.flush()
    return result


def refresh_psych_state(db: Session, user_id: int) -> dict:
    """从最近对话粗估信心 / 焦虑（方案 5.1 ④）。"""
    texts = recent_user_texts(db, user_id, limit=40)
    if not texts:
        return {}
    joined = "\n".join(texts)
    n = max(1, len(texts))
    anx = sum(joined.count(w) for w in ANXIETY_WORDS)
    conf = sum(joined.count(w) for w in CONFIDENCE_WORDS)
    defeat = sum(joined.count(w) for w in DEFEAT_WORDS)

    anxiety = min(1.0, 0.3 + 0.12 * anx - 0.05 * conf)
    confidence = max(0.0, min(1.0, 0.5 + 0.08 * conf - 0.07 * defeat))
    motivation = max(0.0, min(1.0, 0.5 + 0.02 * n))

    p = get_or_create_profile(db, user_id)
    p.anxiety_level = round(anxiety, 3)
    p.confidence_level = round(confidence, 3)
    p.motivation = round(motivation, 3)
    p.updated_at = datetime.now()
    db.flush()
    return {
        "anxiety": p.anxiety_level,
        "confidence": p.confidence_level,
        "motivation": p.motivation,
        "samples": n,
    }


def weak_points(db: Session, user_id: int, subject_key: str | None = None,
                limit: int = 5) -> list[dict]:
    """薄弱知识点（掌握度升序）。"""
    q = select(KpMastery, KnowledgePoint).join(
        KnowledgePoint, KpMastery.kp_code == KnowledgePoint.kp_code
    ).where(KpMastery.user_id == user_id)
    if subject_key:
        q = q.where(KpMastery.subject_key == subject_key)
    q = q.order_by(KpMastery.mastery.asc()).limit(limit)

    out = []
    for m, kp in db.execute(q).all():
        if m.mastery >= 0.75:
            continue
        out.append(
            {
                "kp_code": m.kp_code,
                "name": kp.name,
                "mastery": round(m.mastery, 3),
                "subject": m.subject_key,
            }
        )
    return out


def build_profile_context(
    db: Session, user_id: int, subject_key: str, extra: dict | None = None
) -> dict:
    """组装「学生情况」上下文，供 tutor prompt 使用。"""
    p = get_or_create_profile(db, user_id)
    extra = extra or {}
    return {
        "stage": p.stage or "senior",
        "grade": p.grade or "senior_1",
        "target_major": p.target_major,
        "primary_style": p.primary_style,
        "style_hint": pick_explain_style(p.primary_style),
        "confidence": p.confidence_level,
        "anxiety": p.anxiety_level,
        "weak_points": extra.get("weak_points") or weak_points(db, user_id, subject_key, 3),
        "patterns": extra.get("patterns") or [],
        "cross_subject": extra.get("cross_subject"),
        "memories": extra.get("memories") or [],
    }
