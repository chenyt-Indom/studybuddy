"""外部教材知识库（IMA）对接接口。

链路：设置里填 IMA Token → 测试连接（会列出 IMA 暴露的工具）→ 一键同步
（按 年级×科目×知识点 批量检索，**只把片段与出处**存进 kb_snippets）→
对话时自动带上【教材摘录】。

降级策略贯穿始终：没 token / 超时 / 401 都不报错拦住用户，只是"这次没有教材摘录"。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import KbSnippet, KnowledgePoint, User, UserProfile
from ..services import ext_kb
from ..services.secrets_store import mask

router = APIRouter(prefix="/api/ext", tags=["ext"])

SUBJECT_CN = {
    "math": "数学", "physics": "物理", "chemistry": "化学",
    "biology": "生物", "chinese": "语文", "english": "英语",
}
GRADE_CN = {
    "junior_1": "初一", "junior_2": "初二", "junior_3": "初三",
    "senior_1": "高一", "senior_2": "高二", "senior_3": "高三",
    "all": "通用",
}


class TokenIn(BaseModel):
    token: str = ""


class ToggleIn(BaseModel):
    enabled: bool


class SyncIn(BaseModel):
    stage: str = "senior"
    subject: str = "all"
    grade: str = ""
    max_queries: int = 12


def _status(db: Session, user: User) -> dict:
    cnt = db.scalar(
        select(func.count(KbSnippet.id)).where(KbSnippet.user_id == user.id)
    ) or 0
    tok = settings.ima_token
    return {
        "url": ext_kb.IMA_URL,
        "configured": bool(tok),
        "token_masked": mask(tok) if tok else "",
        "secure_storage": settings.key_protected,
        "enabled": settings.ima_enabled,
        "cached_snippets": int(cnt),
        "note": (
            "IMA 里挂了小学到大学的教材知识库；这里只用它的检索能力，"
            "本地只缓存片段与出处，不保存整本教材正文。"
        ),
    }


@router.get("/ima")
def ima_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"ok": True, **_status(db, user)}


@router.post("/ima/token")
def set_token(body: TokenIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    settings.set_ima_token(body.token)
    return {"ok": True, **_status(db, user)}


@router.post("/ima/enabled")
def set_enabled(body: ToggleIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    settings.set_ima_enabled(body.enabled)
    return {"ok": True, **_status(db, user)}


@router.post("/ima/test")
async def test_ima(user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """探明 IMA 到底暴露了哪些工具、挑哪个当检索用（工具名不对外公开，只能探）。"""
    res = await ext_kb.probe()
    return {"ok": res.get("ok", False), "probe": res, **_status(db, user)}


@router.post("/ima/sync")
async def sync_ima(body: SyncIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """按知识点清单批量检索并落库。

    为什么按「知识点」而不是整本教材：教材正文不能整本搬（版权 + 上下文也用不上），
    按知识点检索出来的片段才是讲解真正要用的东西。
    """
    if not settings.ima_token:
        return {"ok": False, "message": "还没配置 IMA Token，先去填令牌"}

    grade = body.grade
    if not grade:
        p = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
        grade = (p.grade if p else "") or "senior_1"

    q = select(KnowledgePoint).where(KnowledgePoint.stage == body.stage)
    if body.subject and body.subject != "all":
        q = q.where(KnowledgePoint.subject_key == body.subject)
    kps = db.scalars(q.order_by(KnowledgePoint.importance.desc())).all()
    kps = kps[: max(1, min(body.max_queries, 40))]

    added = 0
    calls = 0
    reason = ""
    for kp in kps:
        subj_cn = SUBJECT_CN.get(kp.subject_key, "")
        query = f"{GRADE_CN.get(kp.grade or grade, '')}{subj_cn} {kp.name} 教材"
        res = await ext_kb.search(query, limit=3)
        calls += 1
        if not res.get("ok"):
            reason = res.get("reason") or reason
            if "Token" in reason or "未授权" in reason:
                break      # 认证问题，后面的就不用试了
            continue
        added += ext_kb.save_snippets(
            db, user.id, res.get("items") or [],
            stage=body.stage, grade=kp.grade or grade,
            subject=kp.subject_key, query=query,
        )
    db.commit()
    return {
        "ok": added > 0 or not reason,
        "added": added,
        "calls": calls,
        "message": (f"同步完成：检索 {calls} 次，新增 {added} 条片段"
                    if not reason else f"部分失败：{reason}（已存 {added} 条）"),
        **_status(db, user),
    }


@router.get("/kb")
def local_kb(q: str = Query(""), subject: str = Query(""), stage: str = Query(""),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    """本地已同步片段的手动检索（排查用，也给前端展示有多少可用）。"""
    items = ext_kb.local_search(db, user.id, q, subject=subject, stage=stage, limit=8)
    return {"ok": True, "items": items, "count": len(items)}


@router.delete("/kb")
def clear_kb(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(KbSnippet).where(KbSnippet.user_id == user.id))
    db.commit()
    return {"ok": True, "cleared": True, **_status(db, user)}
