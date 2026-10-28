"""学习周报接口。

三个动作：生成（可重复生成，覆盖本周）、取最新一份、看历史列表。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..services import weekly

router = APIRouter(prefix="/api/weekly", tags=["weekly"])


@router.post("/generate")
async def generate(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """重新算一遍本周数据并写周报（会覆盖同一周的旧版本）。"""
    r = await weekly.generate(db, user.id)
    return {"ok": True, **r}


@router.get("/latest")
def latest(user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = weekly.latest(db, user.id)
    if not r:
        s, e = weekly.week_bounds()
        return {"ok": True, "exists": False,
                "week_start": s.isoformat(), "week_end": e.isoformat(),
                "message": "这周还没生成周报"}
    return {"ok": True, "exists": True, **r}


@router.get("/list")
def list_reports(limit: int = Query(8), user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    return {"ok": True, "items": weekly.history(db, user.id, limit)}
