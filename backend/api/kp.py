"""知识点汇总 / 详情 / 搜索。

产品上的三个用途：
1. **汇总**：把 6 科 × 各年级的知识点按模块摊开，看得见全局，也知道自己薄在哪
2. **提示**：每个知识点带一句话要点、常见易错、记忆锚点 —— 这才是"提示"不是"标题"
3. **联动**：跨学科相关的知识点互相挂上，用已经会的去锚定新学的（好记、也记得久）

数据来源只有 seeds_kp.py（140 条），不在这里编内容。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import (
    CrossSubjectLink,
    KnowledgePoint,
    KpDependency,
    KpMastery,
    Mistake,
    ReviewState,
    User,
    UserProfile,
)
from ..services.kp import grade_rank, is_visible, search_kps

router = APIRouter(prefix="/api/kp", tags=["kp"])

SUBJECT_CN = {
    "math": "数学", "physics": "物理", "chemistry": "化学",
    "biology": "生物", "chinese": "语文", "english": "英语",
}
GRADE_CN = {
    "primary_1": "一年级", "primary_2": "二年级", "primary_3": "三年级",
    "primary_4": "四年级", "primary_5": "五年级", "primary_6": "六年级",
    "junior_1": "初一", "junior_2": "初二", "junior_3": "初三",
    "senior_1": "高一", "senior_2": "高二", "senior_3": "高三",
    "all": "贯穿",
}
RELATION_CN = {
    "tool_for": "可当工具用",
    "concept_shared": "同一个概念",
    "same_skill": "考同一项能力",
}


def _level(m: float | None) -> str:
    if m is None:
        return "unknown"
    if m < 0.4:
        return "weak"
    if m < 0.7:
        return "mid"
    return "good"


def _subject_cn(k: str) -> str:
    return SUBJECT_CN.get(k, k)


@router.get("/overview")
def overview(
    stage: str = Query("senior"),
    subject: str = Query("all"),
    grade: str = Query(""),
    mode: str = Query("all"),  # all / learned / current / weak / due
    q: str = Query(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """按 学段 → 科目 → 模块 汇总知识点，带我的掌握度与跨科联动。"""
    if not grade:
        p = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
        grade = (p.grade if p else "") or "senior_1"
    max_rank = grade_rank(grade)

    kps = db.scalars(select(KnowledgePoint).where(KnowledgePoint.stage == stage)).all()
    if subject and subject != "all":
        kps = [k for k in kps if k.subject_key == subject]

    mastery = {
        m.kp_code: m for m in db.scalars(
            select(KpMastery).where(KpMastery.user_id == user.id)
        )
    }
    reviews = {
        r.kp_code: r for r in db.scalars(
            select(ReviewState).where(ReviewState.user_id == user.id)
        )
    }
    links = db.scalars(select(CrossSubjectLink)).all()
    name_map = {k.kp_code: k for k in db.scalars(select(KnowledgePoint))}

    cross_of: dict[str, list[dict]] = {}
    for l in links:
        other = name_map.get(l.to_kp)
        if not other:
            continue
        cross_of.setdefault(l.from_kp, []).append(
            {
                "code": other.kp_code,
                "name": other.name,
                "subject": other.subject_key,
                "subject_cn": _subject_cn(other.subject_key),
                "relation": l.relation_type,
                "relation_cn": RELATION_CN.get(l.relation_type, "相关"),
                "note": l.note,
            }
        )

    now = datetime.now()
    ql = (q or "").strip().lower()

    items: list[dict] = []
    for kp in kps:
        learned = is_visible(kp, max_rank)
        m = mastery.get(kp.kp_code)
        mv = m.mastery if m else None
        rv = reviews.get(kp.kp_code)
        due = bool(rv and rv.next_review and rv.next_review <= now)

        if mode == "learned" and not learned:
            continue
        if mode == "current" and kp.grade != grade:
            continue
        if mode == "weak" and (mv is None or mv >= 0.5):
            continue
        if mode == "due" and not due:
            continue
        if ql:
            hay = " ".join(filter(None, [kp.name, kp.summary, kp.module, kp.keywords]))
            if ql not in hay.lower():
                continue

        items.append(
            {
                "code": kp.kp_code,
                "name": kp.name,
                "subject": kp.subject_key,
                "subject_cn": _subject_cn(kp.subject_key),
                "stage": kp.stage,
                "grade": kp.grade or "all",
                "grade_cn": GRADE_CN.get(kp.grade or "all", kp.grade or "贯穿"),
                "module": kp.module or "其他",
                "difficulty": kp.difficulty,
                "importance": kp.importance,
                "summary": kp.summary,
                "learned": learned,
                "mastery": None if mv is None else round(mv, 3),
                "level": _level(mv),
                "due": due,
                "next_review": rv.next_review.date().isoformat()
                if (rv and rv.next_review) else None,
                "cross": cross_of.get(kp.kp_code, [])[:3],
            }
        )

    # 按科目 → 模块分组
    subjects: dict[str, dict] = {}
    for it in items:
        s = subjects.setdefault(
            it["subject"],
            {"key": it["subject"], "cn": it["subject_cn"], "total": 0, "weak": 0,
             "due": 0, "modules": {}},
        )
        s["total"] += 1
        if it["level"] == "weak":
            s["weak"] += 1
        if it["due"]:
            s["due"] += 1
        mod = s["modules"].setdefault(it["module"], {"name": it["module"], "items": []})
        mod["items"].append(it)

    subj_list = []
    for s in sorted(subjects.values(), key=lambda x: -x["total"]):
        mods = []
        for mod in s["modules"].values():
            mod["items"].sort(key=lambda x: (grade_rank(x["grade"]) is None,
                                             grade_rank(x["grade"]) or 0, -x["importance"]))
            mods.append(mod)
        mods.sort(key=lambda m: min((grade_rank(i["grade"]) or 0) for i in m["items"]))
        s["modules"] = mods
        subj_list.append(s)
    subj_list.sort(key=lambda s: list(SUBJECT_CN).index(s["key"])
                   if s["key"] in SUBJECT_CN else 99)

    all_kps = db.scalars(select(KnowledgePoint).where(KnowledgePoint.stage == stage)).all()
    learned_total = sum(1 for k in all_kps if is_visible(k, max_rank))
    return {
        "ok": True,
        "stage": stage,
        "grade": grade,
        "grade_cn": GRADE_CN.get(grade, grade),
        "subject": subject,
        "mode": mode,
        "stats": {
            "total_all": len(all_kps),
            "total_shown": len(items),
            "learned": learned_total,
            "weak": sum(1 for i in items if i["level"] == "weak"),
            "unknown": sum(1 for i in items if i["level"] == "unknown"),
            "due": sum(1 for i in items if i["due"]),
            "cross": sum(1 for i in items if i["cross"]),
        },
        "subjects": subj_list,
    }


@router.get("/search")
def search(
    q: str = Query(""),
    subject: str = Query(""),
    stage: str = Query(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = search_kps(db, q, subject or None, stage or None)
    return {
        "ok": True,
        "q": q,
        "items": [
            {**r, "subject_cn": _subject_cn(r["subject"]),
             "grade_cn": GRADE_CN.get(r["grade"] or "all", "贯穿")}
            for r in rows
        ],
    }


@router.get("/{code}")
def detail(code: str, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """单个知识点的完整提示：要点 / 易错 / 记忆锚点 / 前后依赖 / 跨科联动。"""
    kp = db.get(KnowledgePoint, code)
    if not kp:
        return {"ok": False, "message": "知识点不存在"}

    name_map = {k.kp_code: k for k in db.scalars(select(KnowledgePoint))}
    deps = db.scalars(
        select(KpDependency).where(KpDependency.kp_code == code)
    ).all()
    children = db.scalars(
        select(KpDependency).where(KpDependency.depends_on == code)
    ).all()

    cross = []
    for l in db.scalars(
        select(CrossSubjectLink).where(
            (CrossSubjectLink.from_kp == code) | (CrossSubjectLink.to_kp == code)
        )
    ).all():
        other_code = l.to_kp if l.from_kp == code else l.from_kp
        other = name_map.get(other_code)
        if not other:
            continue
        cross.append({
            "code": other.kp_code, "name": other.name,
            "subject": other.subject_key, "subject_cn": _subject_cn(other.subject_key),
            "relation": l.relation_type,
            "relation_cn": RELATION_CN.get(l.relation_type, "相关"),
            "note": l.note, "strength": l.strength,
        })
    cross.sort(key=lambda x: -x["strength"])

    m = db.scalar(
        select(KpMastery).where(
            KpMastery.user_id == user.id, KpMastery.kp_code == code
        )
    )
    rv = db.scalar(
        select(ReviewState).where(
            ReviewState.user_id == user.id, ReviewState.kp_code == code
        )
    )
    mistake_cnt = len(db.scalars(
        select(Mistake).where(Mistake.user_id == user.id, Mistake.kp_code == code)
    ).all())

    return {
        "ok": True,
        "item": {
            "code": kp.kp_code, "name": kp.name,
            "subject": kp.subject_key, "subject_cn": _subject_cn(kp.subject_key),
            "stage": kp.stage, "grade": kp.grade or "all",
            "grade_cn": GRADE_CN.get(kp.grade or "all", "贯穿"),
            "module": kp.module, "difficulty": kp.difficulty,
            "importance": kp.importance,
            "summary": kp.summary, "pitfall": kp.pitfall, "mnemonic": kp.mnemonic,
        },
        "mastery": None if not m else {
            "value": round(m.mastery, 3), "level": _level(m.mastery),
            "score_rate": round(m.score_rate, 3), "error_rate": round(m.error_rate, 3),
        },
        "review": None if not rv else {
            "next_review": rv.next_review.date().isoformat(),
            "interval": rv.interval, "repetitions": rv.repetitions,
            "due": bool(rv.next_review and rv.next_review <= datetime.now()),
        },
        "prerequisites": [
            {"code": d.depends_on,
             "name": name_map[d.depends_on].name if d.depends_on in name_map else d.depends_on,
             "grade": name_map[d.depends_on].grade if d.depends_on in name_map else ""}
            for d in deps
        ],
        "unlocks": [
            {"code": d.kp_code,
             "name": name_map[d.kp_code].name if d.kp_code in name_map else d.kp_code,
             "grade": name_map[d.kp_code].grade if d.kp_code in name_map else ""}
            for d in children
        ],
        "cross": cross,
        "mistakes": mistake_cnt,
    }
