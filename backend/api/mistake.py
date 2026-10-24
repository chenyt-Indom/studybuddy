"""错题本（错题通路的第一段：手动录入 + 知识点归因）。

OCR 链路留了接口位置（ocr_tasks / mistake_images 表已建好），
本版没接 PaddleOCR —— 见 README「未完成」一节。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import KnowledgePoint, Mistake, User
from ..services.forgetting.scheduler import ensure_review_state
from ..services.kp import candidates, match_kp_codes
from ..services.pattern.error_pattern import ERROR_TYPES, analyze_error_pattern

router = APIRouter(prefix="/api/mistakes", tags=["mistakes"])


class MistakeIn(BaseModel):
    subject: str
    content: str
    kp_code: str | None = None
    error_type: str | None = None
    tier: str | None = None
    difficulty: int = 3
    note: str | None = None


@router.post("")
def create(body: MistakeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.error_type and body.error_type not in ERROR_TYPES:
        return {"ok": False, "message": f"错因必须是 {list(ERROR_TYPES)} 之一"}

    kp = body.kp_code
    attributed_by = "manual"
    if not kp:
        # 约定：先从知识点库检索候选，再选 —— 不允许模型/规则凭空编 code
        got = match_kp_codes(db, body.subject, body.content, top=1)
        kp = got[0] if got else None
        attributed_by = "auto"

    m = Mistake(
        user_id=user.id,
        subject_key=body.subject,
        kp_code=kp,
        content=body.content,
        error_type=body.error_type,
        tier=body.tier,
        difficulty=body.difficulty,
        note=body.note,
    )
    db.add(m)
    db.flush()

    if kp:
        ensure_review_state(db, user.id, body.subject, kp, source="mistake", source_id=m.id)

    db.commit()
    kp_obj = db.get(KnowledgePoint, kp) if kp else None
    return {
        "ok": True,
        "id": m.id,
        "kp_code": kp,
        "kp_name": kp_obj.name if kp_obj else None,
        "attributed_by": attributed_by,
    }


@router.get("")
def list_mistakes(subject: str | None = Query(None), user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    q = select(Mistake).where(Mistake.user_id == user.id)
    if subject:
        q = q.where(Mistake.subject_key == subject)
    rows = db.scalars(q.order_by(Mistake.id.desc()).limit(200)).all()
    kp_map = {kp.kp_code: kp.name for kp in db.scalars(select(KnowledgePoint))}
    return [
        {
            "id": r.id,
            "subject": r.subject_key,
            "content": r.content,
            "kp_code": r.kp_code,
            "kp_name": kp_map.get(r.kp_code or "", ""),
            "error_type": r.error_type,
            "error_type_cn": ERROR_TYPES.get(r.error_type or "", ""),
            "tier": r.tier,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/stats")
def stats(subject: str = Query("math"), user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    data = analyze_error_pattern(db, user.id, subject)
    return {"error_types": ERROR_TYPES, "analysis": data}


@router.get("/candidates")
def kp_candidates(subject: str = Query("math"), text: str = Query(""),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"candidates": candidates(db, subject, text, limit=12)}
