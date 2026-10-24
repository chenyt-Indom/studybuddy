"""洞察页：模式挖掘结果。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..services.pattern.error_pattern import ERROR_TYPES
from ..services.pattern.miner import list_insights, mine_all, mine_subject
from ..services.pattern.analyzer import analyze_question_tier
from ..services.pattern.gap import scan_all_gaps

router = APIRouter(prefix="/api/insight", tags=["insight"])


@router.get("")
def list_all(subject: str | None = Query(None), user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    return {"insights": list_insights(db, user.id, subject)}


@router.post("/run")
def run(subject: str | None = Query(None), user: User = Depends(current_user),
        db: Session = Depends(get_db)):
    if subject:
        found = mine_subject(db, user.id, subject)
        db.commit()
        return {"subject": subject, "found": len(found), "insights": found}
    res = mine_all(db, user.id)
    db.commit()
    return {"subjects": list(res.keys()), "found": sum(len(v) for v in res.values()),
            "insights": res}


@router.get("/detail")
def detail(subject: str = Query("math"), user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """原始分析数据（不经过落库），给图表用。"""
    return {
        "subject": subject,
        "tiers": analyze_question_tier(db, user.id, subject),
        "gaps": scan_all_gaps(db, user.id, subject),
        "error_types": ERROR_TYPES,
    }
