"""画像接口：四维画像读取 / 修改 / 认知风格重算。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User, UserProfile
from ..services.cross_subject.graph import imbalance_warning, subject_radar
from ..services.profile.builder import (
    get_or_create_profile,
    recent_user_texts,
    refresh_psych_state,
    refresh_style,
    weak_points,
)
from ..services.tutor import GRADE_CN, SUBJECT_CN, build_tutor_prompt
from ..services.profile.builder import build_profile_context

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileIn(BaseModel):
    stage: str | None = None
    grade: str | None = None
    target_major: str | None = None
    target_score: int | None = None
    electives: list[str] | None = None
    preferred_hours: list[str] | None = None


def _dump(p: UserProfile) -> dict:
    return {
        "stage": p.stage,
        "grade": p.grade,
        "grade_cn": GRADE_CN.get(p.grade or "", p.grade),
        "target_major": p.target_major,
        "target_score": p.target_score,
        "electives": json.loads(p.electives) if p.electives else [],
        "style_scores": json.loads(p.style_scores) if p.style_scores else {},
        "primary_style": p.primary_style,
        "style_confidence": p.style_confidence,
        "preferred_hours": json.loads(p.preferred_hours) if p.preferred_hours else [],
        "confidence_level": p.confidence_level,
        "anxiety_level": p.anxiety_level,
        "motivation": p.motivation,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
def read_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_or_create_profile(db, user.id)
    db.commit()
    return _dump(p)


@router.put("")
def update_profile(body: ProfileIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    p = get_or_create_profile(db, user.id)
    if body.stage is not None:
        p.stage = body.stage
    if body.grade is not None:
        p.grade = body.grade
    if body.target_major is not None:
        p.target_major = body.target_major
    if body.target_score is not None:
        p.target_score = body.target_score
    if body.electives is not None:
        p.electives = json.dumps(body.electives, ensure_ascii=False)
    if body.preferred_hours is not None:
        p.preferred_hours = json.dumps(body.preferred_hours, ensure_ascii=False)
    db.commit()
    return _dump(p)


@router.post("/refresh-style")
def do_refresh_style(user: User = Depends(current_user), db: Session = Depends(get_db)):
    res = refresh_style(db, user.id)
    psy = refresh_psych_state(db, user.id)
    db.commit()
    return {"style": res, "psych": psy}


@router.get("/overview")
def overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """画像总览：给档案页用。"""
    p = get_or_create_profile(db, user.id)
    return {
        "profile": _dump(p),
        # 认知风格是按样本比例算的，样本太少时置信度会虚高，前端要如实展示样本量
        "style_samples": len(recent_user_texts(db, user.id, limit=200)),
        "radar": subject_radar(db, user.id),
        "weak_points": weak_points(db, user.id, limit=8),
        "imbalance": imbalance_warning(db, user.id),
        "subjects": [{"key": k, "name": v} for k, v in SUBJECT_CN.items()],
        "grades": [{"key": k, "name": v} for k, v in GRADE_CN.items()],
    }


@router.get("/prompt-preview")
def prompt_preview(subject: str = "math", q: str = "", user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """看看「同一个问题，你的 Prompt 长什么样」—— 专精化的透明化展示。

    用 build_context（和真对话同一条路），这样【知识点提示】【跨科联动】
    【教材定位】都能看到；只给 profile 会漏掉这些真正体现"专精化"的部分。
    """
    from ..services.chat_service import build_context
    from ..services.websearch import today_line

    text = (q or "").strip() or "比如这道题我没思路，你帮我看看从哪下手"
    ctx = build_context(db, user.id, subject, text)
    ctx["time_line"] = today_line()
    return {"subject": subject, "q": text,
            "system_prompt": build_tutor_prompt(ctx, subject)}
