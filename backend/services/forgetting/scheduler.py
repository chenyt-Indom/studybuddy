"""复习调度器（方案 6.4 / 6.5）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import KnowledgePoint, KpMastery, ReviewLog, ReviewState
from .sm2 import SM2Scheduler
from .strength import memory_strength


def ensure_review_state(
    db: Session,
    user_id: int,
    subject_key: str,
    kp_code: str,
    source: str = "chat",
    source_id: int | None = None,
) -> ReviewState:
    """为该知识点建立 SM-2 状态（已存在则原样返回）。新知识点从「今天该复习」开始。"""
    st = db.scalar(
        select(ReviewState).where(
            ReviewState.user_id == user_id, ReviewState.kp_code == kp_code
        )
    )
    if st:
        return st
    st = ReviewState(
        user_id=user_id,
        subject_key=subject_key,
        kp_code=kp_code,
        ef=2.5,
        interval=1,
        repetitions=0,
        next_review=datetime.now(),
        last_review=None,
        source=source,
        source_id=source_id,
    )
    db.add(st)
    db.flush()
    return st


def get_review_queue(
    db: Session, user_id: int, now: datetime | None = None, limit: int = 20
) -> list[dict]:
    """今日复习队列，按优先级排序。

    优先级 = 紧急度 × 0.5 + 重要度 × 0.3 + 薄弱度 × 0.2
    """
    now = now or datetime.now()
    states = db.scalars(select(ReviewState).where(ReviewState.user_id == user_id)).all()
    kp_map = {kp.kp_code: kp for kp in db.scalars(select(KnowledgePoint))}
    mastery_map = {
        m.kp_code: m
        for m in db.scalars(select(KpMastery).where(KpMastery.user_id == user_id))
    }

    out = []
    for st in states:
        if st.next_review and st.next_review > now:
            continue
        strength = memory_strength(
            {"last_review": st.last_review, "ef": st.ef, "repetitions": st.repetitions}, now
        )
        urgency = 1.0 - strength
        kp = kp_map.get(st.kp_code)
        importance = kp.importance if kp else 0.5
        m = mastery_map.get(st.kp_code)
        weakness = 1.0 - (m.mastery if m else 0.5)
        priority = urgency * 0.5 + importance * 0.3 + weakness * 0.2
        overdue = (now - st.next_review).days if st.next_review else 0
        out.append(
            {
                "kp_code": st.kp_code,
                "kp_name": kp.name if kp else st.kp_code,
                "subject": st.subject_key,
                "strength": round(strength, 3),
                "priority": round(priority, 3),
                "overdue_days": max(0, overdue),
                "ef": round(st.ef, 2),
                "interval": st.interval,
                "repetitions": st.repetitions,
            }
        )
    out.sort(key=lambda x: x["priority"], reverse=True)
    return out[:limit]


def apply_review(
    db: Session, user_id: int, kp_code: str, quality: int, now: datetime | None = None
) -> dict:
    """记录一次复习结果，按 SM-2 更新状态，并联动掌握度。"""
    now = now or datetime.now()
    st = db.scalar(
        select(ReviewState).where(
            ReviewState.user_id == user_id, ReviewState.kp_code == kp_code
        )
    )
    if not st:
        raise ValueError(f"知识点 {kp_code} 没有复习状态，先建立再复习")

    before = {"ef": st.ef, "interval": st.interval, "repetitions": st.repetitions}
    after = SM2Scheduler.update(before, quality, now)

    st.ef = after["ef"]
    st.interval = after["interval"]
    st.repetitions = after["repetitions"]
    st.next_review = after["next_review"]
    st.last_review = after["last_review"]

    db.add(
        ReviewLog(
            user_id=user_id,
            kp_code=kp_code,
            quality=quality,
            ef_before=before["ef"],
            ef_after=after["ef"],
            interval_before=before["interval"],
            interval_after=after["interval"],
            reviewed_at=now,
        )
    )

    # 联动掌握度：复习表现作为一路证据（EMA 平滑）
    m = db.scalar(
        select(KpMastery).where(
            KpMastery.user_id == user_id, KpMastery.kp_code == kp_code
        )
    )
    observed = quality / 5.0
    if m:
        m.mastery = round(0.7 * m.mastery + 0.3 * observed, 4)
    else:
        db.add(
            KpMastery(
                user_id=user_id,
                subject_key=st.subject_key,
                kp_code=kp_code,
                mastery=round(observed, 4),
            )
        )
    db.flush()
    return {
        "kp_code": kp_code,
        "before": before,
        "after": after,
        "next_review": after["next_review"].isoformat(),
        "interval_days": after["interval"],
    }


def check_review_in_chat(db: Session, user_id: int, subject: str) -> str | None:
    """对话内复习提醒（方案 6.5）：给选择权，不强制打断。"""
    due = [d for d in get_review_queue(db, user_id, limit=30) if d["subject"] == subject]
    if not due:
        return None
    names = "、".join(d["kp_name"] for d in due[:3])
    return (
        f"\n\n---\n\n📌 **复习提醒**：你在「{subject}」有 {len(due)} 个知识点快忘了：{names}。\n"
        f"（记忆强度已降到 {due[0]['strength']:.0%}）\n\n"
        "要不要先花 5 分钟复习一下？还是先解决你现在的问题？"
    )
