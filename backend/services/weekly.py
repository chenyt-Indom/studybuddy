"""学习周报：把「这一周到底做了什么」用数字讲清楚。

设计上的三个取舍：
1. **先算数据，再让模型写**。模型只负责组织语言，不许编数字 —— 所以 prompt 里
   把 stats 以 JSON 塞进去，并要求"每个判断后面跟数字"。
2. **一定要有输出**。没配 Key / 模型报错时退回规则版（模板拼数字），
   周报是"给过去的自己留的凭据"，不能因为网关挂了就空白。
3. **落库覆盖**。同一周重复生成就覆盖那一周的记录（唯一键 user_id + week_start），
   不产生一堆重复周报。

统计口径（写清楚，免得以后自己都忘了）：
  · 答疑次数 = 本周我发出的消息条数（不含 AI 回复）
  · 新增错题 = mistakes.created_at 落在本周
  · 考试 = grades.exam_date（为空则看 created_at）落在本周
  · 薄弱 = 当前掌握度 < 0.6 且按掌握度升序取前 5（这是"现在弱"，不是"本周变弱"）
  · 待复习 = review_state.next_review <= 现在
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Conversation,
    Grade,
    KpMastery,
    Message,
    Mistake,
    ReviewState,
    WeeklyReport,
)
from .kp import kp_name_map
from .llm import MockProvider, get_provider

SUBJECT_CN = {
    "math": "数学", "physics": "物理", "chemistry": "化学",
    "biology": "生物", "chinese": "语文", "english": "英语",
}
ERROR_CN = {
    "concept": "概念不清", "calculation": "计算失误", "careless": "审题马虎",
    "method": "方法不会", "transfer": "迁移失败", "timeout": "时间不够",
}


def week_bounds(d: date | None = None) -> tuple[date, date]:
    """本周一 ~ 本周日。"""
    d = d or date.today()
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _dt_start(d: date) -> datetime:
    return datetime.combine(d, time.min)


def _dt_end(d: date) -> datetime:
    return datetime.combine(d, time.max)


# ---------------------------------------------------------------- 取数
def collect_stats(db: Session, user_id: int, start: date, end: date) -> dict:
    lo, hi = _dt_start(start), _dt_end(end)

    conv_ids = [c.id for c in db.scalars(
        select(Conversation).where(Conversation.user_id == user_id)
    ).all()]

    msg_total = msg_user = 0
    if conv_ids:
        msg_total = db.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id.in_(conv_ids),
                Message.created_at >= lo, Message.created_at <= hi,
            )
        ) or 0
        msg_user = db.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id.in_(conv_ids), Message.role == "user",
                Message.created_at >= lo, Message.created_at <= hi,
            )
        ) or 0

    mistakes = db.scalars(
        select(Mistake).where(
            Mistake.user_id == user_id,
            Mistake.created_at >= lo, Mistake.created_at <= hi,
        )
    ).all()
    by_err: dict[str, int] = {}
    by_subj: dict[str, int] = {}
    for m in mistakes:
        if m.error_type:
            by_err[m.error_type] = by_err.get(m.error_type, 0) + 1
        by_subj[m.subject_key] = by_subj.get(m.subject_key, 0) + 1

    grades = db.scalars(
        select(Grade).where(Grade.user_id == user_id)
    ).all()
    week_grades = [
        g for g in grades
        if (g.exam_date and start <= g.exam_date <= end)
        or (not g.exam_date and g.created_at and lo <= g.created_at <= hi)
    ]
    exams = [
        {"subject": SUBJECT_CN.get(g.subject_key, g.subject_key),
         "name": g.exam_name or "考试",
         "rate": round((g.score / g.full_score) if g.full_score else 0, 3),
         "score": g.score, "full": g.full_score}
        for g in week_grades
    ]
    avg_rate = round(sum(e["rate"] for e in exams) / len(exams), 3) if exams else None

    mastery = db.scalars(
        select(KpMastery).where(KpMastery.user_id == user_id)
    ).all()
    names = kp_name_map(db)
    weak = sorted(
        [m for m in mastery if m.mastery < 0.6],
        key=lambda m: m.mastery,
    )[:5]
    weak_items = [
        {"name": names.get(m.kp_code, {}).get("name", m.kp_code),
         "subject": SUBJECT_CN.get(m.subject_key, m.subject_key),
         "mastery": round(m.mastery, 2)}
        for m in weak
    ]
    touched = [
        m for m in mastery
        if m.updated_at and lo <= m.updated_at <= hi
    ]

    reviews = db.scalars(
        select(ReviewState).where(ReviewState.user_id == user_id)
    ).all()
    now = datetime.now()
    due = sum(1 for r in reviews if r.next_review and r.next_review <= now)
    done = sum(1 for r in reviews if r.last_review and lo <= r.last_review <= hi)

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "messages_total": msg_total,
        "qa_count": msg_user,
        "new_mistakes": len(mistakes),
        "error_types": [
            {"type": ERROR_CN.get(k, k), "count": v}
            for k, v in sorted(by_err.items(), key=lambda kv: -kv[1])
        ],
        "mistakes_by_subject": [
            {"subject": SUBJECT_CN.get(k, k), "count": v}
            for k, v in sorted(by_subj.items(), key=lambda kv: -kv[1])
        ],
        "exams": exams,
        "exam_avg_rate": avg_rate,
        "weak_kps": weak_items,
        "kp_touched": len(touched),
        "kp_total": len(mastery),
        "review_due": due,
        "review_done": done,
    }


# ---------------------------------------------------------------- 写周报
def _pct(x: float | None) -> str:
    return "—" if x is None else f"{round(x * 100)}%"


def rule_report(st: dict) -> str:
    """没有可用模型时的兜底：只用数字拼，不编故事。"""
    r = st["range"]
    lines = [f"## 本周概况（{r['start']} ~ {r['end']}）", ""]
    lines.append(
        f"这周你在对话里问了 **{st['qa_count']}** 次（共 {st['messages_total']} 条消息），"
        f"新记了 **{st['new_mistakes']}** 道错题，"
        f"复习了 **{st['review_done']}** 个到期知识点。"
    )
    if st["exam_avg_rate"] is not None:
        lines.append(f"本周有 {len(st['exams'])} 场考试，平均得分率 **{_pct(st['exam_avg_rate'])}**。")
    lines.append("")

    lines += ["## 需要盯的地方", ""]
    if st["error_types"]:
        top = st["error_types"][0]
        lines.append(f"- 错题里最多的是**{top['type']}**（{top['count']} 道）。")
    if st["weak_kps"]:
        wk = "、".join(f"{x['name']}（{round(x['mastery'] * 100)}%）" for x in st["weak_kps"][:3])
        lines.append(f"- 当前最薄弱的三个知识点：{wk}。")
    if st["review_due"]:
        lines.append(f"- 还有 **{st['review_due']}** 个知识点到了复习期没做。")
    if not (st["error_types"] or st["weak_kps"] or st["review_due"]):
        lines.append("- 数据还不够看出问题，下周多记几道错题会更准。")
    lines.append("")

    lines += ["## 下周三个动作", ""]
    acts = []
    if st["review_due"]:
        acts.append(f"先把 {st['review_due']} 个到期复习清掉（一次 15 分钟就够）")
    if st["weak_kps"]:
        acts.append(f"挑「{st['weak_kps'][0]['name']}」专门过一遍，做 3 道同类题")
    if st["error_types"]:
        acts.append(f"针对「{st['error_types'][0]['type']}」，下次做题前先按这个点自查")
    if not acts:
        acts = ["每天固定 20 分钟做一组题", "错题当天记，别攒", "每周挑一个薄弱知识点重讲一遍"]
    for i, a in enumerate(acts[:3], 1):
        lines.append(f"{i}. {a}")
    lines.append("")
    lines.append("> 本周报由数据自动生成（未接入大模型，纯数字模板）。")
    return "\n".join(lines)


def build_messages(st: dict) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "你是学习教练，写周报。硬性要求：\n"
                "1. 只使用给定的统计数据，**不许编造任何数字或事件**；某项缺失就跳过不提。\n"
                "2. 每个判断后面必须跟一个数字佐证（例如「错题 7 道，其中 4 道是计算失误」）。\n"
                "3. 用 Markdown，四个小标题：本周概况 / 做对了什么 / 卡在哪 / 下周三个动作。\n"
                "4. 总长 350~500 字，语气像一个了解他的教练，不喊口号、不空泛鼓励。\n"
                "5. 最后一行给一句不超过 20 字的具体提醒（不要「加油」这种）。"
            ),
        },
        {
            "role": "user",
            "content": "这是我这一周的学习数据（JSON）：\n"
                       + json.dumps(st, ensure_ascii=False, indent=1),
        },
    ]


async def generate(db: Session, user_id: int, start: date | None = None) -> dict:
    """生成（或覆盖）这一周的周报，返回 {content, source, stats, week_start}。"""
    s, e = week_bounds(start)
    st = collect_stats(db, user_id, s, e)

    content, source = "", "rule"
    llm = get_provider()
    if not isinstance(llm, MockProvider):
        try:
            txt = await llm.chat(build_messages(st), scene="report")
            if txt and len(txt.strip()) > 80:
                content, source = txt.strip(), "llm"
        except Exception:
            pass
    if not content:
        content, source = rule_report(st), "rule"

    row = db.scalar(
        select(WeeklyReport).where(
            WeeklyReport.user_id == user_id, WeeklyReport.week_start == s
        )
    )
    payload = json.dumps(st, ensure_ascii=False)
    if row is None:
        row = WeeklyReport(user_id=user_id, week_start=s, week_end=e)
        db.add(row)
    row.week_end = e
    row.content = content
    row.stats = payload
    row.source = source
    db.commit()

    return {"content": content, "source": source, "stats": st,
            "week_start": s.isoformat(), "week_end": e.isoformat()}


def latest(db: Session, user_id: int) -> dict | None:
    row = db.scalar(
        select(WeeklyReport)
        .where(WeeklyReport.user_id == user_id)
        .order_by(WeeklyReport.week_start.desc())
    )
    if not row:
        return None
    return {
        "content": row.content,
        "source": row.source,
        "week_start": row.week_start.isoformat(),
        "week_end": row.week_end.isoformat(),
        "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M"),
        "stats": json.loads(row.stats) if row.stats else {},
    }


def history(db: Session, user_id: int, limit: int = 8) -> list[dict]:
    rows = db.scalars(
        select(WeeklyReport)
        .where(WeeklyReport.user_id == user_id)
        .order_by(WeeklyReport.week_start.desc())
        .limit(limit)
    ).all()
    return [
        {"week_start": r.week_start.isoformat(), "week_end": r.week_end.isoformat(),
         "source": r.source, "excerpt": (r.content or "").split("\n")[0][:60]}
        for r in rows
    ]
