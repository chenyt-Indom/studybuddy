"""记忆整理（consolidate）—— 把原子记忆合成综述，并处理重复与过时。

为什么需要这一步：
  原子记忆（Memory）是一条条事实，越攒越多、越攒越像流水账；
  用户想看的（也是模型最需要的）是**按主题合成后的整体理解**。
  所以每天整理一次：合并同义、标记过时、重写综述。

三种处理：
  1. **合并**（duplicates）—— 同义的多条留一条，其余标 superseded，不物理删除，可回溯
  2. **取代**（supersede）—— 新事实覆盖旧事实（比如目标变了），旧条标 superseded
  3. **综述**（sections）—— 分节长文，用户手动改过的分节不覆盖

没有配大模型时走规则版兜底，保证离线也能用。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import TEMPERATURE_MAP, settings
from ...db import session_scope
from ...models import Memory, MemoryDoc, MemoryMeta, User
from ...prompts import CONSOLIDATE_PROMPT
from ..llm import get_provider, MockProvider
from ..util import parse_json_loose

# 一次整理最多喂多少条，防止上下文爆炸
MAX_INPUT_MEMORIES = 120

TYPE_BUCKET = {
    "identity": "学习背景",
    "goal": "学习目标",
    "habit": "学习习惯与偏好",
    "preference": "学习习惯与偏好",
    "weakness": "各科情况",
    "misconception": "各科情况",
    "emotion": "情绪与状态",
    "observation": "其他观察",
}


def get_meta(db: Session, user_id: int) -> MemoryMeta:
    m = db.get(MemoryMeta, user_id)
    if not m:
        m = MemoryMeta(user_id=user_id, auto_extract=True, auto_consolidate=True)
        db.add(m)
        db.flush()
    return m


def _active_memories(db: Session, user_id: int) -> list[Memory]:
    rows = db.scalars(
        select(Memory).where(
            Memory.user_id == user_id,
            Memory.accuracy != "wrong",
            Memory.superseded == False,  # noqa: E712
        )
    ).all()
    # 置顶/判定为准/高权重的优先，截断到上限
    rows.sort(key=lambda m: (m.pinned, m.accuracy == "correct", m.weight, m.id), reverse=True)
    return rows[:MAX_INPUT_MEMORIES]


def _fmt_memories(rows: list[Memory]) -> str:
    out = []
    for m in rows:
        scope = "全局" if m.scope == "global" else f"科目-{m.subject_key}"
        ts = (m.created_at.strftime("%m-%d") if m.created_at else "")
        out.append(f"#{m.id} [{scope}][{m.mtype}] {m.content}（{ts}）")
    return "\n".join(out)


def _fmt_docs(docs: list[MemoryDoc]) -> str:
    if not docs:
        return "（暂无）"
    out = []
    for d in docs:
        mark = "【用户手改，勿覆盖】" if d.user_edited else ""
        out.append(f"## {d.section}{mark}\n{d.content}")
    return "\n\n".join(out)


# ---------------------------------------------------------------- 规则兜底
def _rule_sections(rows: list[Memory]) -> list[dict]:
    """没有大模型时按类型分桶拼综述。宁可是清单，也不要空白。"""
    buckets: dict[str, list[str]] = {}
    for m in rows:
        sec = TYPE_BUCKET.get(m.mtype, "其他观察")
        if m.scope == "subject" and m.subject_key and m.mtype in ("weakness", "misconception"):
            sec = f"{m.subject_key} 科目情况"
        line = m.content
        if m.evidence:
            line += f"（依据：{m.evidence}）"
        buckets.setdefault(sec, []).append(f"· {line}")

    # 固定顺序，稳定输出
    order = ["学习背景", "学习目标", "学习习惯与偏好", "情绪与状态", "其他观察"]
    keys = [k for k in order if k in buckets] + [k for k in buckets if k not in order]
    return [{"section": k, "content": "\n".join(buckets[k])} for k in keys]


# ---------------------------------------------------------------- LLM 版
async def _llm_consolidate(rows: list[Memory], docs: list[MemoryDoc]) -> dict | None:
    llm = get_provider()
    if isinstance(llm, MockProvider):
        return None
    try:
        raw = await llm.chat(
            [
                {"role": "system", "content": "你只输出 JSON，不写任何解释。"},
                {
                    "role": "user",
                    "content": CONSOLIDATE_PROMPT.format(
                        existing=_fmt_docs(docs),
                        memories=_fmt_memories(rows),
                    ),
                },
            ],
            temperature=TEMPERATURE_MAP["mine_pattern"],
            max_tokens=4096,
            scene="mine_pattern",
        )
        data = parse_json_loose(raw, dict)
        if not isinstance(data, dict) or "sections" not in data:
            return None
        return data
    except Exception:
        return None


# ---------------------------------------------------------------- 主流程
async def consolidate(user_id: int, reason: str = "manual") -> dict:
    """整理一次。返回统计，供 UI 展示。"""
    with session_scope() as db:
        meta = get_meta(db, user_id)
        rows = _active_memories(db, user_id)
        if not rows:
            meta.last_consolidated_at = datetime.now()
            meta.last_summary = "没有可整理的记忆"
            return {"ok": True, "mode": "skip", "message": "还没有记忆，跳过",
                    "sections": 0, "superseded": 0, "duplicates": 0}
        docs = db.scalars(
            select(MemoryDoc).where(MemoryDoc.user_id == user_id).order_by(MemoryDoc.order_index)
        ).all()

    payload = await _llm_consolidate(rows, docs)
    mode = "llm"
    if not payload:
        payload = {"sections": _rule_sections(rows), "supersede": [], "duplicates": []}
        mode = "rule"

    n_sup = n_dup = 0
    edited_skipped: list[str] = []

    with session_scope() as db:
        meta = get_meta(db, user_id)

        # 1) 合并重复：保留 keep，其余归档
        for item in payload.get("duplicates") or []:
            if not isinstance(item, dict):
                continue
            keep = item.get("keep")
            for rid in item.get("remove") or []:
                if keep and rid and rid != keep:
                    m = db.get(Memory, int(rid))
                    if m and m.user_id == user_id and not m.superseded:
                        m.superseded = True
                        m.superseded_by = int(keep)
                        n_dup += 1

        # 2) 取代过时
        for item in payload.get("supersede") or []:
            rid = item.get("id") if isinstance(item, dict) else item
            if not rid:
                continue
            m = db.get(Memory, int(rid))
            if m and m.user_id == user_id and not m.superseded:
                m.superseded = True
                n_sup += 1

        # 3) 写综述：用户手改过的分节不覆盖
        existing = {
            d.section: d
            for d in db.scalars(select(MemoryDoc).where(MemoryDoc.user_id == user_id)).all()
        }
        idx = 0
        for sec in payload.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            name = str(sec.get("section") or "").strip()[:64]
            content = str(sec.get("content") or "").strip()
            if not name or not content:
                continue
            doc = existing.get(name)
            if doc:
                if doc.user_edited:
                    edited_skipped.append(name)
                    idx += 1
                    continue
                doc.content = content
                doc.version += 1
                doc.auto_generated = True
                doc.updated_at = datetime.now()
            else:
                db.add(
                    MemoryDoc(
                        user_id=user_id, section=name, content=content,
                        order_index=idx, version=1, auto_generated=True,
                    )
                )
            idx += 1

        meta.last_consolidated_at = datetime.now()
        meta.consolidate_count += 1
        meta.last_summary = (
            f"{'模型' if mode == 'llm' else '规则'}整理：{len(payload.get('sections') or [])} 节，"
            f"合并 {n_dup} 条，归档过时 {n_sup} 条"
            + (f"，保留手改 {len(edited_skipped)} 节" if edited_skipped else "")
        )
        summary = meta.last_summary
        count = meta.consolidate_count

    return {
        "ok": True,
        "mode": mode,
        "reason": reason,
        "sections": len(payload.get("sections") or []),
        "superseded": n_sup,
        "duplicates": n_dup,
        "skipped_user_edited": edited_skipped,
        "message": summary,
        "count": count,
    }


def should_auto_run(db: Session, user_id: int, min_hours: int = 20) -> bool:
    meta = get_meta(db, user_id)
    if not meta.auto_consolidate:
        return False
    if not meta.last_consolidated_at:
        return True
    delta = datetime.now() - meta.last_consolidated_at
    return delta.total_seconds() >= min_hours * 3600


async def consolidate_all(min_hours: int = 20) -> list[dict]:
    """给后台定时任务用：把所有开启自动整理的用户过一遍。"""
    with session_scope() as db:
        users = [u.id for u in db.scalars(select(User)).all()]
        todo = []
        for uid in users:
            if should_auto_run(db, uid, min_hours):
                todo.append(uid)
    out = []
    for uid in todo:
        try:
            out.append(await consolidate(uid, reason="auto"))
        except Exception as exc:  # noqa: BLE001
            out.append({"ok": False, "user_id": uid, "error": str(exc)[:200]})
    return out


def docs_public(db: Session, user_id: int) -> list[dict]:
    rows = db.scalars(
        select(MemoryDoc).where(MemoryDoc.user_id == user_id).order_by(MemoryDoc.order_index)
    ).all()
    return [
        {
            "id": d.id,
            "section": d.section,
            "content": d.content,
            "version": d.version,
            "user_edited": d.user_edited,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in rows
    ]


def build_doc_context(db: Session, user_id: int, max_chars: int = 1800) -> str:
    """把综述注入对话 Prompt —— 这是"高层背景"，比单条记忆更省 token。"""
    rows = db.scalars(
        select(MemoryDoc).where(MemoryDoc.user_id == user_id).order_by(MemoryDoc.order_index)
    ).all()
    if not rows:
        return ""
    parts, used = [], 0
    for d in rows:
        block = f"## {d.section}\n{d.content}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)
