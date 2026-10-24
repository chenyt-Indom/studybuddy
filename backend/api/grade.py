"""成绩录入 + 逐题记录 + 趋势（方案 13.3 的重要数据要求）。

只有总分 → 无法分析题型分层；有逐题数据 → 才能做 L3 洞察。
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Grade, QuestionRecord, User
from ..services.forgetting.scheduler import ensure_review_state
from ..services.mastery import recompute_from_records
from ..services.pattern.miner import mine_subject


router = APIRouter(prefix="/api/grades", tags=["grades"])


class QuestionIn(BaseModel):
    q_no: int
    kp_code: str | None = None
    is_correct: bool = True
    score: float = 0
    full_score: float = 0


class GradeIn(BaseModel):
    subject: str
    exam_name: str = ""
    score: float
    full_score: float = 100
    exam_date: str | None = None
    questions: list[QuestionIn] = []


def _tier_of(q_no: int) -> str:
    if q_no <= 7:
        return "basic"
    if q_no <= 12:
        return "medium"
    return "hard"


@router.post("")
def create_grade(body: GradeIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    ed = None
    if body.exam_date:
        try:
            ed = date.fromisoformat(body.exam_date)
        except ValueError:
            ed = date.today()

    g = Grade(
        user_id=user.id,
        subject_key=body.subject,
        exam_name=body.exam_name or "未命名考试",
        score=body.score,
        full_score=body.full_score,
        exam_date=ed or date.today(),
    )
    db.add(g)
    db.flush()

    wrong_kps = []
    for q in body.questions:
        db.add(
            QuestionRecord(
                user_id=user.id,
                subject_key=body.subject,
                exam_id=g.id,
                q_no=q.q_no,
                kp_code=q.kp_code,
                is_correct=q.is_correct,
                score=q.score,
                full_score=q.full_score or 0,
                max_tier=_tier_of(q.q_no),
            )
        )
        if not q.is_correct and q.kp_code:
            wrong_kps.append(q.kp_code)

    # 错到的知识点 → 进入复习队列
    for kp in set(wrong_kps):
        ensure_review_state(db, user.id, body.subject, kp, source="exam", source_id=g.id)

    updated = recompute_from_records(db, user.id, body.subject) if body.questions else 0

    # 录成绩后必跑模式挖掘（方案 5.3.5）
    insights = mine_subject(db, user.id, body.subject) if body.questions else []

    db.commit()
    return {
        "id": g.id,
        "questions_saved": len(body.questions),
        "kp_updated": updated,
        "wrong_kps": sorted(set(wrong_kps)),
        "insights_found": len(insights),
        "has_per_question": len(body.questions) > 0,
    }


@router.get("")
def list_grades(subject: str | None = Query(None), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    q = select(Grade).where(Grade.user_id == user.id)
    if subject:
        q = q.where(Grade.subject_key == subject)
    rows = db.scalars(q.order_by(Grade.exam_date, Grade.id)).all()
    return [
        {
            "id": r.id,
            "subject": r.subject_key,
            "exam_name": r.exam_name,
            "score": r.score,
            "full_score": r.full_score,
            "rate": round(r.score / r.full_score, 3) if r.full_score else 0,
            "exam_date": r.exam_date.isoformat() if r.exam_date else None,
        }
        for r in rows
    ]


@router.get("/trend")
def trend(subject: str | None = Query(None), user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    """成绩趋势（统一换算成百分制，便于跨试卷比较）。"""
    q = select(Grade).where(Grade.user_id == user.id)
    if subject:
        q = q.where(Grade.subject_key == subject)
    rows = db.scalars(q.order_by(Grade.exam_date, Grade.id)).all()
    series = []
    for r in rows:
        rate = (r.score / r.full_score * 100) if r.full_score else 0
        series.append(
            {
                "id": r.id,
                "label": r.exam_name or (r.exam_date.isoformat() if r.exam_date else ""),
                "value": round(rate, 1),
                "raw": f"{r.score:g}/{r.full_score:g}",
                "subject": r.subject_key,
                "date": r.exam_date.isoformat() if r.exam_date else "",
            }
        )
    return {"series": series, "count": len(series)}


@router.delete("/{grade_id}")
def delete_grade(grade_id: int, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    g = db.get(Grade, grade_id)
    if not g or g.user_id != user.id:
        return {"ok": False, "message": "记录不存在"}
    for r in db.scalars(
        select(QuestionRecord).where(QuestionRecord.exam_id == grade_id)
    ).all():
        db.delete(r)
    db.delete(g)
    db.commit()
    return {"ok": True}
