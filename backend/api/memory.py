"""记忆库管理接口 —— 双层记忆 + 可核查。

设计原则（「公开透明」的具体化）：
  1. 用户能看到**每一条**记忆，包括模型自己打的分（置信度）和原始依据（evidence）
  2. 用户能判定每条「准确 / 不准确」—— 判为不准确的**立即不再参与召回**
  3. 用户能直接改内容、改类型、置顶、删除、手工新增
  4. 提供「这次对话会用到哪些记忆」的预览，不是黑盒
  5. 准确率只在**有判定**时才计算，没判定就返回 null，不假装 100%
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Memory, User
from ..services.memory.recall import recall
from ..services.memory.store import add_memory, stats as mem_stats

router = APIRouter(prefix="/api/memory", tags=["memory"])

TYPE_CN = {
    "identity": "身份", "goal": "目标", "habit": "习惯", "preference": "偏好",
    "emotion": "情绪", "weakness": "薄弱", "misconception": "误区",
    "observation": "观察",
}
SUBJECT_CN = {
    "math": "数学", "physics": "物理", "chemistry": "化学",
    "biology": "生物", "chinese": "语文", "english": "英语",
}
ACCURACY = {"unverified", "correct", "wrong"}


class MemoryIn(BaseModel):
    content: str
    scope: str = "subject"
    subject_key: str | None = None
    type: str = "observation"
    evidence: str | None = None
    pinned: bool = False


class MemoryPatch(BaseModel):
    content: str | None = None
    type: str | None = None
    scope: str | None = None
    subject_key: str | None = None
    pinned: bool | None = None
    accuracy: str | None = None
    evidence: str | None = None


class VerifyIn(BaseModel):
    accuracy: str


def _dump(m: Memory) -> dict:
    return {
        "id": m.id,
        "scope": m.scope,
        "subject": m.subject_key,
        "subject_cn": SUBJECT_CN.get(m.subject_key or "", ""),
        "type": m.mtype,
        "type_cn": TYPE_CN.get(m.mtype, m.mtype),
        "content": m.content,
        "evidence": m.evidence,
        "source": m.source,
        "source_message_id": m.source_message_id,
        "confidence": round(m.confidence, 3),
        "weight": round(m.weight, 3),
        "hits": m.hits,
        "accuracy": m.accuracy,
        "pinned": m.pinned,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "verified_at": m.verified_at.isoformat() if m.verified_at else None,
    }


@router.get("/stats")
def get_stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = mem_stats(db, user.id)
    s["type_cn"] = TYPE_CN
    s["subject_cn"] = SUBJECT_CN
    return s


@router.get("")
def list_memories(
    scope: str = Query("all", pattern="^(all|global|subject)$"),
    subject: str | None = Query(None),
    accuracy: str | None = Query(None),
    q: str | None = Query(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Memory).where(Memory.user_id == user.id)
    if scope != "all":
        stmt = stmt.where(Memory.scope == scope)
    if subject:
        stmt = stmt.where(Memory.subject_key == subject)
    if accuracy in ACCURACY:
        stmt = stmt.where(Memory.accuracy == accuracy)
    rows = db.scalars(stmt).all()
    if q:
        kw = q.strip()
        rows = [m for m in rows if kw in m.content or kw in (m.keywords or "")]
    # 置顶优先，然后按权重/置信度
    rows.sort(key=lambda m: (m.pinned, m.weight, m.confidence, m.id), reverse=True)
    return {"items": [_dump(m) for m in rows], "count": len(rows)}


@router.post("")
def create_memory(body: MemoryIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    if body.scope not in ("global", "subject"):
        return {"ok": False, "message": "scope 只能是 global 或 subject"}
    m = add_memory(
        db,
        user_id=user.id,
        content=body.content,
        mtype=body.type,
        scope=body.scope,
        subject_key=body.subject_key if body.scope == "subject" else None,
        evidence=body.evidence,
        source="manual",
        confidence=1.0,  # 用户手填的，默认满置信
    )
    if m and body.pinned:
        m.pinned = True
    db.commit()
    return {"ok": True, "item": _dump(m) if m else None}


@router.put("/{mid}")
def update_memory(mid: int, body: MemoryPatch, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    m = db.get(Memory, mid)
    if not m or m.user_id != user.id:
        return {"ok": False, "message": "记录不存在"}

    if body.content is not None and body.content.strip():
        m.content = body.content.strip()[:200]
    if body.type is not None:
        m.mtype = body.type
    if body.scope is not None and body.scope in ("global", "subject"):
        m.scope = body.scope
        if body.scope == "global":
            m.subject_key = None
    if body.subject_key is not None and m.scope == "subject":
        m.subject_key = body.subject_key or None
    if body.pinned is not None:
        m.pinned = body.pinned
    if body.evidence is not None:
        m.evidence = body.evidence or None
    if body.accuracy is not None and body.accuracy in ACCURACY:
        m.accuracy = body.accuracy
        m.verified_at = datetime.now() if body.accuracy != "unverified" else None
    m.updated_at = datetime.now()
    db.commit()
    return {"ok": True, "item": _dump(m)}


@router.post("/{mid}/verify")
def verify_memory(mid: int, body: VerifyIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """用户判定这条记忆准不准。判为 wrong 后立即不再参与召回。"""
    m = db.get(Memory, mid)
    if not m or m.user_id != user.id:
        return {"ok": False, "message": "记录不存在"}
    if body.accuracy not in ACCURACY:
        return {"ok": False, "message": "accuracy 只能是 unverified/correct/wrong"}
    m.accuracy = body.accuracy
    m.verified_at = datetime.now() if body.accuracy != "unverified" else None
    if body.accuracy == "correct":
        # 用户确认过的，权重拉起来，别让它被衰减掉
        m.weight = max(m.weight, 1.0)
    db.commit()
    return {"ok": True, "item": _dump(m), "stats": mem_stats(db, user.id)}


@router.delete("/{mid}")
def delete_memory(mid: int, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    m = db.get(Memory, mid)
    if not m or m.user_id != user.id:
        return {"ok": False, "message": "记录不存在"}
    db.delete(m)
    db.commit()
    return {"ok": True, "stats": mem_stats(db, user.id)}


@router.post("/cleanup")
def cleanup_wrong(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """一键清掉所有被判定为「不准确」的记忆。"""
    rows = db.scalars(
        select(Memory).where(Memory.user_id == user.id, Memory.accuracy == "wrong")
    ).all()
    n = len(rows)
    for m in rows:
        db.delete(m)
    db.commit()
    return {"ok": True, "deleted": n, "stats": mem_stats(db, user.id)}


@router.get("/preview")
def preview_injection(subject: str = Query("math"), query: str = Query(""),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    """透明化：预览「这次对话实际会注入哪些记忆」。

    不传 query 就只返回全局记忆（模拟冷启动）。
    """
    from ..services.memory.recall import global_memories

    used = recall(db, user.id, query or "随便问问", subject_key=subject, limit=6) if query else []
    gl = global_memories(db, user.id, limit=4)
    seen = {m["id"] for m in used}
    merged = gl + [m for m in used if m["id"] not in seen]
    return {
        "subject": subject,
        "query": query,
        "count": len(merged),
        "global": [_dump(db.get(Memory, m["id"])) for m in merged if m.get("scope") == "global"],
        "subject_items": [_dump(db.get(Memory, m["id"])) for m in merged if m.get("scope") != "global"],
        "note": "被判为「不准确」的记忆不会出现在这里，也不会进 Prompt。",
    }
