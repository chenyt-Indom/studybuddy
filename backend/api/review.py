"""复习中心：队列 / 打分 / 遗忘曲线 / 复习卡。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import KnowledgePoint, KpMastery, ReviewLog, ReviewState, User
from ..services.forgetting.card_gen import generate_cards
from ..services.forgetting.scheduler import apply_review, get_review_queue
from ..services.forgetting.strength import curve_points, memory_strength
from ..services.profile.builder import get_or_create_profile

router = APIRouter(prefix="/api/review", tags=["review"])


class ReviewIn(BaseModel):
    quality: int = Field(ge=0, le=5)


@router.get("/queue")
def queue(limit: int = Query(20, ge=1, le=100), user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    return {"items": get_review_queue(db, user.id, limit=limit)}


@router.post("/{kp_code}/grade")
def grade(kp_code: str, body: ReviewIn, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    try:
        res = apply_review(db, user.id, kp_code, body.quality)
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    db.commit()
    return {"ok": True, **res}


@router.get("/state")
def state(kp_code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    st = db.scalar(
        select(ReviewState).where(
            ReviewState.user_id == user.id, ReviewState.kp_code == kp_code
        )
    )
    if not st:
        return {"exists": False}
    kp = db.get(KnowledgePoint, kp_code)
    strength = memory_strength(
        {"last_review": st.last_review, "ef": st.ef, "repetitions": st.repetitions}
    )
    return {
        "exists": True,
        "kp_code": kp_code,
        "kp_name": kp.name if kp else kp_code,
        "subject": st.subject_key,
        "ef": round(st.ef, 3),
        "interval": st.interval,
        "repetitions": st.repetitions,
        "strength": round(strength, 3),
        "next_review": st.next_review.isoformat() if st.next_review else None,
        "last_review": st.last_review.isoformat() if st.last_review else None,
    }


@router.get("/curve")
def curve(kp_code: str, days: int = 30, user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    st = db.scalar(
        select(ReviewState).where(
            ReviewState.user_id == user.id, ReviewState.kp_code == kp_code
        )
    )
    if not st:
        return {"points": [], "message": "该知识点还没有复习记录"}
    kp = db.get(KnowledgePoint, kp_code)
    pts = curve_points(
        {"last_review": st.last_review, "ef": st.ef, "repetitions": st.repetitions},
        days=days,
    )
    return {
        "kp_code": kp_code,
        "kp_name": kp.name if kp else kp_code,
        "points": pts,
        "ef": round(st.ef, 3),
        "interval": st.interval,
    }


@router.get("/cards")
async def cards(kp_code: str, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    kp = db.get(KnowledgePoint, kp_code)
    if not kp:
        return {"error": "知识点不存在"}
    m = db.scalar(
        select(KpMastery).where(
            KpMastery.user_id == user.id, KpMastery.kp_code == kp_code
        )
    )
    p = get_or_create_profile(db, user.id)
    out = await generate_cards(
        kp=kp,
        mastery=m.mastery if m else 0.5,
        last_error=None,
        style=p.primary_style,
    )
    return {"kp_code": kp_code, "cards": out}


@router.get("/stats")
def stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    total = db.scalar(
        select(func.count()).select_from(ReviewState).where(ReviewState.user_id == user.id)
    ) or 0
    due = len(get_review_queue(db, user.id, limit=500))
    reviewed = db.scalar(
        select(func.count()).select_from(ReviewLog).where(ReviewLog.user_id == user.id)
    ) or 0
    states = db.scalars(
        select(ReviewState).where(ReviewState.user_id == user.id)
    ).all()
    strengths = [
        memory_strength(
            {"last_review": s.last_review, "ef": s.ef, "repetitions": s.repetitions}
        )
        for s in states
    ]
    avg_strength = round(sum(strengths) / len(strengths), 3) if strengths else 0.0
    return {
        "tracked": total,
        "due": due,
        "reviewed_count": reviewed,
        "avg_strength": avg_strength,
    }
