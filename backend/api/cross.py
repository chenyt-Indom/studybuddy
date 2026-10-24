"""跨科目协调接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import KnowledgePoint, User
from ..services.cross_subject.graph import (
    SUBJECT_CN,
    cross_hint,
    graph_data,
    imbalance_warning,
    subject_radar,
)
from ..services.profile.builder import weak_points

router = APIRouter(prefix="/api/cross", tags=["cross"])


@router.get("/graph")
def graph(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return graph_data(db, user.id)


@router.get("/hint")
def hint(kp_code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    h = cross_hint(db, user.id, kp_code)
    return {"hint": h}


@router.get("/radar")
def radar(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"radar": subject_radar(db, user.id),
            "imbalance": imbalance_warning(db, user.id)}


@router.get("/synergy")
def synergy(subject: str = Query("math"), user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    """协同建议：哪科拖累哪科、先补哪科（规则驱动，不依赖大模型）。"""
    weak = weak_points(db, user.id, subject, limit=5)
    items = []
    for w in weak:
        cs = cross_hint(db, user.id, w["kp_code"])
        if not cs:
            continue
        items.append(
            {
                "weak_kp": w["name"],
                "weak_mastery": w["mastery"],
                "related_subject": cs["related_subject_cn"],
                "related_kp": cs["related_kp"],
                "related_mastery": cs["related_mastery"],
                "advice": (
                    f"「{w['name']}」和{cs['related_subject_cn']}的「{cs['related_kp']}」"
                    f"是同一套东西。那边掌握度只有 {cs['related_mastery']:.0%}，"
                    f"建议先花 2 天补{cs['related_subject_cn']}的这个点，再回来会轻松很多。"
                ),
            }
        )
    return {
        "subject": subject,
        "subject_cn": SUBJECT_CN.get(subject, subject),
        "items": items,
        "imbalance": imbalance_warning(db, user.id),
    }


@router.get("/knowledge-points")
def kps(subject: str | None = Query(None), user: User = Depends(current_user),
        db: Session = Depends(get_db)):
    q = select(KnowledgePoint)
    if subject:
        q = q.where(KnowledgePoint.subject_key == subject)
    rows = db.scalars(q.order_by(KnowledgePoint.subject_key, KnowledgePoint.name)).all()
    return [
        {"kp_code": r.kp_code, "name": r.name, "subject": r.subject_key,
         "importance": r.importance, "difficulty": r.difficulty}
        for r in rows
    ]
