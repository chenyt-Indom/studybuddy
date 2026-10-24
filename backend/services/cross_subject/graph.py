"""跨科目知识图谱与协同建议（方案 7.1 / 7.3）。

规则驱动：即使大模型不可用，跨科关联提示也能正常给出。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import CrossSubjectLink, KnowledgePoint, KpMastery

SUBJECT_CN = {
    "math": "数学",
    "physics": "物理",
    "chemistry": "化学",
    "biology": "生物",
    "chinese": "语文",
    "english": "英语",
}

RELATION_CN = {
    "tool_for": "是它的工具",
    "concept_shared": "共享同一概念",
    "same_skill": "考同一项能力",
}


def _mastery(db: Session, user_id: int, kp_code: str) -> float | None:
    m = db.scalar(
        select(KpMastery).where(
            KpMastery.user_id == user_id, KpMastery.kp_code == kp_code
        )
    )
    return m.mastery if m else None


def cross_hint(db: Session, user_id: int, kp_code: str) -> dict | None:
    """给单个知识点找跨科关联 + 对方掌握度。用于对话 Prompt 注入和 UI 提示。"""
    links = db.scalars(
        select(CrossSubjectLink).where(CrossSubjectLink.from_kp == kp_code)
    ).all()
    if not links:
        return None

    kp_map = {kp.kp_code: kp for kp in db.scalars(select(KnowledgePoint))}
    best = None
    for link in links:
        other = kp_map.get(link.to_kp)
        if not other:
            continue
        other_m = _mastery(db, user_id, link.to_kp)
        # 对方越弱，越值得提醒
        weak = 0.5 if other_m is None else (1.0 - other_m)
        score = link.strength * 0.6 + weak * 0.4
        if best is None or score > best["_score"]:
            best = {
                "_score": score,
                "from_kp": kp_code,
                "from_name": kp_map.get(kp_code).name if kp_map.get(kp_code) else kp_code,
                "to_kp": link.to_kp,
                "related_kp": other.name,
                "related_subject": other.subject_key,
                "related_subject_cn": SUBJECT_CN.get(other.subject_key, other.subject_key),
                "related_mastery": 0.0 if other_m is None else round(other_m, 3),
                "relation": link.relation_type,
                "relation_cn": RELATION_CN.get(link.relation_type, link.relation_type),
                "note": link.note,
                "strength": link.strength,
            }
    if best:
        best.pop("_score", None)
    return best


def subject_radar(db: Session, user_id: int) -> list[dict]:
    """各科平均掌握度 —— 雷达图数据。"""
    rows = db.scalars(select(KpMastery).where(KpMastery.user_id == user_id)).all()
    agg: dict[str, list[float]] = {}
    for m in rows:
        agg.setdefault(m.subject_key, []).append(m.mastery)
    return [
        {
            "subject": s,
            "subject_cn": SUBJECT_CN.get(s, s),
            "mastery": round(sum(v) / len(v), 3),
            "count": len(v),
        }
        for s, v in sorted(agg.items())
    ]


def imbalance_warning(db: Session, user_id: int) -> dict | None:
    """偏科预警：某科明显低于均值且样本足够。"""
    radar = [r for r in subject_radar(db, user_id) if r["count"] >= 2]
    if len(radar) < 2:
        return None
    avg = sum(r["mastery"] for r in radar) / len(radar)
    worst = min(radar, key=lambda r: r["mastery"])
    gap = avg - worst["mastery"]
    if gap < 0.15:
        return None
    return {
        "type": "imbalance",
        "severity": "high" if gap >= 0.3 else "medium",
        "subject": worst["subject"],
        "subject_cn": worst["subject_cn"],
        "mastery": worst["mastery"],
        "average": round(avg, 3),
        "gap": round(gap, 3),
        "title": f"{worst['subject_cn']}明显落后",
        "detail": (
            f"{worst['subject_cn']}平均掌握度 {worst['mastery']:.0%}，"
            f"比你其他科目的均值 {avg:.0%} 低 {gap:.0%}。"
        ),
        "action": f"接下来两周给{worst['subject_cn']}多分一点时间，别让短板继续拖。",
    }


def graph_data(db: Session, user_id: int) -> dict:
    """知识图谱数据：返回节点 + 边，节点带掌握度。"""
    kps = {kp.kp_code: kp for kp in db.scalars(select(KnowledgePoint))}
    mastery = {
        m.kp_code: round(m.mastery, 3)
        for m in db.scalars(select(KpMastery).where(KpMastery.user_id == user_id))
    }
    links = db.scalars(select(CrossSubjectLink)).all()

    used = set()
    edges = []
    for l in links:
        if l.from_kp not in kps or l.to_kp not in kps:
            continue
        used.add(l.from_kp)
        used.add(l.to_kp)
        edges.append(
            {
                "source": l.from_kp,
                "target": l.to_kp,
                "relation": l.relation_type,
                "relation_cn": RELATION_CN.get(l.relation_type, l.relation_type),
                "strength": l.strength,
            }
        )
    nodes = [
        {
            "id": code,
            "name": kps[code].name,
            "subject": kps[code].subject_key,
            "subject_cn": SUBJECT_CN.get(kps[code].subject_key, kps[code].subject_key),
            "mastery": mastery.get(code, 0.0),
            "has_record": code in mastery,
        }
        for code in sorted(used)
    ]
    return {"nodes": nodes, "edges": edges}
