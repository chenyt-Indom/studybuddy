"""教材接口：导入 / 查看结构 / 选择版本 / 定位预览。

⚠️ 版权：上传的教材文件只落在本机 data/textbooks/，不对外传输；
   本项目不含任何教材正文，bundled 教材只有章节结构。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Textbook, TextbookSection, User
from ..seeds_textbook import editions_for
from ..services.kp import match_kp_codes
from ..services.textbook import (
    build_textbook_context,
    check_latest,
    get_user_textbook,
    import_file,
    import_outline_text,
    list_textbooks,
    outline,
    refill_contents,
    search_sections,
    section_detail,
    set_user_textbook,
)

router = APIRouter(prefix="/api/textbook", tags=["textbook"])

SUBJECT_CN = {
    "math": "数学", "physics": "物理", "chemistry": "化学",
    "biology": "生物", "chinese": "语文", "english": "英语",
}


class OutlineIn(BaseModel):
    subject: str
    raw: str
    title: str = "自定义教材目录"
    stage: str = "senior"
    grade: str = "senior_1"
    edition_code: str = ""       # 从版本卡点进来时带上，导入后就挂到那个版本下


@router.get("/list")
def list_all(subject: str | None = Query(None), user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    items = list_textbooks(db, user.id, subject)
    cur = {}
    for s in SUBJECT_CN:
        tb = get_user_textbook(db, user.id, s)
        if tb:
            cur[s] = {"code": tb.code, "title": tb.title}
    return {"items": items, "current": cur, "subjects": SUBJECT_CN}


@router.get("/current")
def current(subject: str = Query("math"), user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    tb = get_user_textbook(db, user.id, subject)
    if not tb:
        return {"ok": False, "message": "该科目还没有可用教材"}
    return {"ok": True, "id": tb.id, "code": tb.code, "title": tb.title,
            "volume": tb.volume, "publisher": tb.publisher, "bundled": tb.bundled}


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    subject: str = Form("math"),
    stage: str = Form("senior"),
    grade: str = Form("senior_1"),
    volume: str = Form(""),
    edition_name: str = Form(""),
    edition_year: int | None = Form(None),
    edition_code: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """导入自己手上的正版教材（PDF / TXT / MD），本地解析成章节结构。"""
    data = await file.read()
    res = import_file(
        db, user.id, file.filename or "textbook.pdf", data,
        subject_key=subject, stage=stage, grade=grade, volume=volume,
        edition_name=edition_name, edition_year=edition_year,
        edition_code=edition_code or "custom",
    )
    if res.get("ok"):
        set_user_textbook(db, user.id, subject, res["code"])
        db.commit()
    return res


@router.post("/outline")
def create_outline(body: OutlineIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """粘贴目录文本导入（每行：`第一章 xxx | 1.1 xxx | 关键词`）。"""
    res = import_outline_text(
        db, user.id, body.raw, body.subject,
        stage=body.stage, grade=body.grade, title=body.title,
        edition_code=body.edition_code or "custom",
    )
    if res.get("ok"):
        set_user_textbook(db, user.id, body.subject, res["code"])
        db.commit()
    return res


@router.get("/section/{section_id}")
def get_section(section_id: int, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    """读某一节的正文（离线可读，数据来自自己导入的教材）。"""
    data = section_detail(db, section_id, user.id)
    if not data:
        return {"ok": False, "message": "章节不存在或不属于你"}
    return {"ok": True, **data}


@router.get("/search")
def search_text(q: str = Query(""), subject: str = Query(""),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    """在自己导入的教材正文里搜原话（给"课本上怎么说的"这类问题用）。"""
    items = search_sections(db, user.id, q, subject=subject, limit=8)
    return {"ok": True, "q": q, "count": len(items), "items": items}


@router.post("/{tb_id}/refill")
def refill(tb_id: int, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """给早先只导入结构的教材补正文（重新解析原文件）。"""
    r = refill_contents(db, tb_id)
    return r


@router.get("/{tb_id}/outline")
def get_outline(tb_id: int, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    data = outline(db, tb_id, user.id)
    if not data:
        return {"ok": False, "message": "教材不存在"}
    return {"ok": True, **data}


@router.post("/select")
def select_textbook(subject: str = Query(...), code: str = Query(...),
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    """切换当前使用的教材。

    注意：函数名不能叫 select —— 会覆盖 SQLAlchemy 的 select（踩过）。"""
    tb = db.scalar(select(Textbook).where(Textbook.code == code))
    if not tb or (not tb.bundled and tb.user_id != user.id):
        return {"ok": False, "message": "教材不存在"}
    set_user_textbook(db, user.id, subject, code)
    db.commit()
    return {"ok": True, "subject": subject, "code": code, "title": tb.title}


@router.delete("/{tb_id}")
def delete_tb(tb_id: int, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    tb = db.get(Textbook, tb_id)
    if not tb or tb.bundled or tb.user_id != user.id:
        return {"ok": False, "message": "只能删除自己导入的教材"}
    # 删章节 + 文件
    for s in db.scalars(
        select(TextbookSection).where(TextbookSection.textbook_id == tb_id)
    ).all():
        db.delete(s)
    if tb.file_path:
        try:
            from pathlib import Path

            Path(tb.file_path).unlink(missing_ok=True)
        except Exception:
            pass
    db.delete(tb)
    db.commit()
    return {"ok": True}


@router.get("/match")
def match_preview(subject: str = Query("math"), q: str = Query(""),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """透明化：这次提问会命中课本的哪几节。

    注意：必须先把问题映射成知识点再传进去，否则只能靠字面匹配，
    会出现"二次函数"匹配到"三角函数"这种事（踩过）。
    """
    kp_hints = match_kp_codes(db, subject, q, top=3) if q else []
    ctx = build_textbook_context(db, user.id, subject, q, kp_hints=kp_hints)
    if not ctx:
        return {"ok": False, "message": "该科目还没有可用教材"}
    return {"ok": True, "kp_hints": kp_hints, **ctx}


# ================================================================ 版本与最新性

@router.get("/editions")
def list_editions(subject: str = Query("math"), stage: str = Query("senior"),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """可选教材版本（出版社 + 修订年）。

    builtin=True 表示本项目内置了该版本的公开目录结构；
    False 表示该版本确实存在，但目录需要你自己导入（不编造）。
    """
    eds = editions_for(stage, subject)
    mine = db.scalars(
        select(Textbook).where(
            Textbook.subject_key == subject,
            (Textbook.bundled == True) | (Textbook.user_id == user.id),  # noqa: E712
        )
    ).all()
    have = {}
    for t in mine:
        have.setdefault(t.edition_code or "", []).append(
            {"code": t.code, "title": t.title, "volume": t.volume,
             "bundled": t.bundled, "status": t.parse_status,
             "edition_year": t.edition_year}
        )
    out = []
    for e in eds:
        books = have.get(e["code"], [])
        out.append({**e, "books": books, "available": len(books) > 0})
    # 用户导入的、不在注册表里的版本也列出来
    extra = [t for t in mine if not t.bundled and (t.edition_code or "") not in {e["code"] for e in eds}]
    for t in extra:
        out.append({
            "code": t.edition_code or f"user_{t.id}",
            "name": t.edition_name or t.publisher or "自定义",
            "publisher": t.publisher,
            "edition": t.volume,
            "year": t.edition_year,
            "builtin": False,
            "books": [{"code": t.code, "title": t.title, "volume": t.volume,
                       "bundled": False, "status": t.parse_status,
                       "edition_year": t.edition_year}],
            "available": True,
            "custom": True,
        })
    return {"subject": subject, "stage": stage, "editions": out}


@router.post("/{tb_id}/check-update")
async def do_check(tb_id: int, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """联网核查这本教材是否最新。结论给来源链接，由用户自行确认。"""
    tb = db.get(Textbook, tb_id)
    if not tb or (not tb.bundled and tb.user_id != user.id):
        return {"ok": False, "message": "教材不存在"}
    res = await check_latest(db, tb)
    db.commit()
    return res


@router.get("/{tb_id}/latest")
def latest_info(tb_id: int, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    tb = db.get(Textbook, tb_id)
    if not tb or (not tb.bundled and tb.user_id != user.id):
        return {"ok": False, "message": "教材不存在"}
    import json as _json

    return {
        "ok": True,
        "checked_at": tb.latest_check_at.isoformat() if tb.latest_check_at else None,
        "verdict": tb.latest_verdict,
        "sources": _json.loads(tb.latest_sources) if tb.latest_sources else [],
    }
