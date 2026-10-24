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
from ..services.memory.consolidate import (consolidate, docs_public, get_meta)
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


# ================================================================ 记忆档案（综述层）

class DocPatch(BaseModel):
    content: str | None = None
    section: str | None = None


class DocIn(BaseModel):
    section: str
    content: str


class MetaIn(BaseModel):
    auto_extract: bool | None = None
    auto_consolidate: bool | None = None


class ImportIn(BaseModel):
    text: str
    section: str = "导入的档案"


@router.get("/meta")
def read_meta(user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = get_meta(db, user.id)
    db.commit()
    return {
        "auto_extract": m.auto_extract,
        "auto_consolidate": m.auto_consolidate,
        "last_consolidated_at": m.last_consolidated_at.isoformat() if m.last_consolidated_at else None,
        "consolidate_count": m.consolidate_count,
        "last_summary": m.last_summary,
    }


@router.post("/meta")
def write_meta(body: MetaIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    m = get_meta(db, user.id)
    if body.auto_extract is not None:
        m.auto_extract = body.auto_extract
    if body.auto_consolidate is not None:
        m.auto_consolidate = body.auto_consolidate
    db.commit()
    return read_meta(user, db)


@router.get("/docs")
def list_docs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"docs": docs_public(db, user.id)}


@router.put("/docs/{did}")
def update_doc(did: int, body: DocPatch, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    from ..models import MemoryDoc

    d = db.get(MemoryDoc, did)
    if not d or d.user_id != user.id:
        return {"ok": False, "message": "分节不存在"}
    if body.content is not None:
        d.content = body.content.strip()
        d.user_edited = True      # 手改过的，自动整理不再覆盖
        d.auto_generated = False
    if body.section:
        d.section = body.section.strip()[:64]
    d.updated_at = datetime.now()
    db.commit()
    return {"ok": True, "docs": docs_public(db, user.id)}


@router.post("/docs")
def create_doc(body: DocIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    from ..models import MemoryDoc

    rows = db.scalars(
        select(MemoryDoc).where(MemoryDoc.user_id == user.id)
    ).all()
    d = MemoryDoc(
        user_id=user.id, section=body.section.strip()[:64],
        content=body.content.strip(), order_index=len(rows),
        auto_generated=False, user_edited=True,
    )
    db.add(d)
    db.commit()
    return {"ok": True, "docs": docs_public(db, user.id)}


@router.delete("/docs/{did}")
def delete_doc(did: int, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    from ..models import MemoryDoc

    d = db.get(MemoryDoc, did)
    if not d or d.user_id != user.id:
        return {"ok": False, "message": "分节不存在"}
    db.delete(d)
    db.commit()
    return {"ok": True, "docs": docs_public(db, user.id)}


@router.post("/consolidate")
async def run_consolidate(user: User = Depends(current_user)):
    """立即整理：合并重复、归档过时、重写综述。"""
    res = await consolidate(user.id, reason="manual")
    return res


@router.post("/reset")
def reset_all(scope: str = Query("all", pattern="^(all|docs|memories)$"),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    """重置：清空记忆。scope 控制只清原子记忆、只清档案、或全清。"""
    from ..models import MemoryDoc

    n_mem = n_doc = 0
    if scope in ("all", "memories"):
        rows = db.scalars(select(Memory).where(Memory.user_id == user.id)).all()
        n_mem = len(rows)
        for m in rows:
            db.delete(m)
    if scope in ("all", "docs"):
        rows = db.scalars(select(MemoryDoc).where(MemoryDoc.user_id == user.id)).all()
        n_doc = len(rows)
        for d in rows:
            db.delete(d)
    meta = get_meta(db, user.id)
    meta.last_consolidated_at = None
    meta.last_summary = "已重置"
    db.commit()
    return {"ok": True, "deleted_memories": n_mem, "deleted_docs": n_doc,
            "stats": mem_stats(db, user.id)}


@router.post("/import")
def import_text(body: ImportIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    """导入：把一段现成的档案文本收进来（比如从别处搬过来的自我介绍）。"""
    from ..models import MemoryDoc

    text = (body.text or "").strip()
    if not text:
        return {"ok": False, "message": "内容为空"}
    rows = db.scalars(select(MemoryDoc).where(MemoryDoc.user_id == user.id)).all()
    d = MemoryDoc(
        user_id=user.id,
        section=(body.section or "导入的档案").strip()[:64],
        content=text[:8000],
        order_index=len(rows),
        auto_generated=False,
        user_edited=True,   # 导入的内容不自动改写
    )
    db.add(d)
    db.commit()
    return {"ok": True, "docs": docs_public(db, user.id)}
