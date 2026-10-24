"""系统接口：星辰 API 配置 / 连通性自检 / 模型探测 / 记忆库。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DEFAULT_BASE_URL, settings, save_settings
from ..db import get_db
from ..deps import current_user
from ..models import Memory, User
from ..services.llm.teleai import TeleAIProvider, get_provider

router = APIRouter(prefix="/api/system", tags=["system"])


class ConfigIn(BaseModel):
    app_key: str | None = None
    model: str | None = None
    base_url: str | None = None


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


@router.get("/config")
def read_config(user: User = Depends(current_user)):
    return {
        "app_key_masked": _mask(settings.app_key),
        "has_key": bool(settings.app_key),
        "model": settings.model,
        "base_url": settings.base_url,
        "default_base_url": DEFAULT_BASE_URL,
        "configured": settings.configured,
        "mode": "teleai" if settings.configured else "mock",
    }


@router.post("/config")
def write_config(body: ConfigIn, user: User = Depends(current_user)):
    patch = {}
    if body.app_key is not None and body.app_key.strip():
        patch["app_key"] = body.app_key.strip()
    if body.model is not None:
        patch["model"] = body.model.strip()
    if body.base_url is not None and body.base_url.strip():
        patch["base_url"] = body.base_url.strip()
    save_settings(patch)
    settings.reload()
    return read_config(user)


@router.get("/models")
async def probe_models(user: User = Depends(current_user)):
    """探测可用模型 —— 解决「model 字段到底填什么」这个必须自己确认的问题。

    走 OpenAI 兼容的 GET /v1/models。如果网关不开放这个接口，会如实报错。
    """
    if not settings.app_key:
        return {"ok": False, "message": "还没填 AppKey", "models": []}
    p = TeleAIProvider()
    try:
        models = await p.list_models()
        return {"ok": True, "count": len(models), "models": models,
                "current": settings.model}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)[:400], "models": []}


@router.get("/health")
async def health(user: User = Depends(current_user)):
    p = get_provider()
    info = await p.health()
    return {"provider": p.name, "configured": settings.configured,
            "base_url": settings.base_url, "model": settings.model, **info}


@router.post("/test-chat")
async def test_chat(user: User = Depends(current_user)):
    """最小连通性验证（方案 M1：必须先做这一步）。"""
    p = get_provider()
    try:
        text = await p.chat(
            [{"role": "user", "content": "只回复两个字：联通"}],
            temperature=0.1,
            max_tokens=32,
        )
        return {"ok": True, "provider": p.name, "reply": text[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "provider": p.name, "message": str(exc)[:500]}


@router.get("/memories")
def memories(subject: str | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    q = select(Memory).where(Memory.user_id == user.id)
    if subject:
        q = q.where(Memory.subject_key == subject)
    rows = db.scalars(q.order_by(Memory.weight.desc(), Memory.id.desc()).limit(100)).all()
    return [
        {
            "id": m.id,
            "type": m.mtype,
            "content": m.content,
            "subject": m.subject_key,
            "weight": round(m.weight, 3),
            "hits": m.hits,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]
