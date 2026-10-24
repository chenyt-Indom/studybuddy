"""P4 知识断层识别（方案 5.3.4）。

核心：知识点之间有依赖关系。如果前置没掌握，后置怎么学都费劲。
用户以为要补 A，其实真正要补的是 B。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import KnowledgePoint, KpDependency, KpMastery

MAX_DEPTH = 4


def _mastery(db: Session, user_id: int, kp_code: str) -> float | None:
    m = db.scalar(
        select(KpMastery).where(
            KpMastery.user_id == user_id, KpMastery.kp_code == kp_code
        )
    )
    return m.mastery if m else None


def find_knowledge_gap(
    db: Session, user_id: int, kp_code: str, depth: int = 0
) -> dict | None:
    """追溯某知识点的「断层根源」。"""
    if depth > MAX_DEPTH:
        return None

    deps = db.scalars(
        select(KpDependency).where(KpDependency.kp_code == kp_code)
    ).all()
    if not deps:
        return None

    kp_names = {kp.kp_code: kp.name for kp in db.scalars(select(KnowledgePoint))}

    weak = []
    for d in deps:
        m = _mastery(db, user_id, d.depends_on)
        # 没有记录的前置也算「未掌握」——学生从没接触过
        if m is None or m < 0.5:
            weak.append({"kp": d.depends_on, "name": kp_names.get(d.depends_on, d.depends_on),
                         "mastery": 0.0 if m is None else round(m, 3)})
    if not weak:
        return None

    weak.sort(key=lambda x: x["mastery"])
    deeper = []
    for w in weak:
        sub = find_knowledge_gap(db, user_id, w["kp"], depth + 1)
        if sub:
            deeper.append(sub)

    root = deeper[0]["root_cause"] if deeper else weak[0]["kp"]
    root_name = kp_names.get(root, root)
    first = weak[0]
    return {
        "current": kp_code,
        "current_name": kp_names.get(kp_code, kp_code),
        "weak_prerequisites": weak,
        "root_cause": root,
        "root_cause_name": root_name,
        "insight": {
            "type": "knowledge_gap",
            "severity": "high" if first["mastery"] < 0.3 else "medium",
            "title": "找到根源了",
            "detail": (
                f"你在「{kp_names.get(kp_code, kp_code)}」上吃力，但**根源不在它本身**——"
                f"是你的前置知识点「{first['name']}」（掌握度 {first['mastery']:.0%}）没打牢。"
                "跳过它硬学后面的，会很痛苦且效率低。"
            ),
            "action": f"先花 2~3 天把「{first['name']}」补上，再回头看"
                      f"「{kp_names.get(kp_code, kp_code)}」，会轻松很多。",
        },
    }


def scan_all_gaps(db: Session, user_id: int, subject: str) -> list[dict]:
    """扫描某科目下所有「自身薄弱 + 前置也薄弱」的知识点。"""
    rows = db.execute(
        select(KpMastery).where(
            KpMastery.user_id == user_id,
            KpMastery.subject_key == subject,
            KpMastery.mastery < 0.5,
        )
    ).scalars().all()

    out = []
    for m in rows:
        gap = find_knowledge_gap(db, user_id, m.kp_code)
        if gap:
            out.append(gap)
    out.sort(key=lambda g: g["weak_prerequisites"][0]["mastery"])
    return out[:5]
