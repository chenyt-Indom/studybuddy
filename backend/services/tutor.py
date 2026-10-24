"""讲解风格自适应（方案 5.4）——「专精化」的最终落地点。

同样的问题，不同用户拿到的 Prompt 完全不同。这才是专精化。
"""
from __future__ import annotations

from ..models import UserProfile
from ..prompts import OUTPUT_REQUIREMENTS, STAGE_ROLE, STYLE_HINT

SUBJECT_CN = {
    "math": "数学",
    "physics": "物理",
    "chemistry": "化学",
    "biology": "生物",
    "chinese": "语文",
    "english": "英语",
}

GRADE_CN = {
    "primary_1": "小学一年级", "primary_2": "小学二年级", "primary_3": "小学三年级",
    "primary_4": "小学四年级", "primary_5": "小学五年级", "primary_6": "小学六年级",
    "junior_1": "初一", "junior_2": "初二", "junior_3": "初三",
    "senior_1": "高一", "senior_2": "高二", "senior_3": "高三",
    "college_1": "大一", "college_2": "大二", "college_3": "大三", "college_4": "大四",
}


def build_tutor_prompt(ctx: dict, subject_key: str) -> str:
    """组装完整辅导提示词。ctx 来自 profile.builder.build_profile_context。"""
    parts: list[str] = []

    stage = ctx.get("stage") or "senior"
    role_tpl = STAGE_ROLE.get(stage, STAGE_ROLE["senior"])
    subject_cn = SUBJECT_CN.get(subject_key, subject_key)
    grade_cn = GRADE_CN.get(ctx.get("grade") or "", ctx.get("grade") or "")
    parts.append(
        role_tpl.format(
            subject=subject_cn,
            grade=grade_cn,
            major=ctx.get("target_major") or "未填写",
        )
    )

    # ② 认知风格 → 讲解方式
    style = ctx.get("primary_style")
    if style and STYLE_HINT.get(style):
        parts.append(f"【讲解风格】{STYLE_HINT[style]}")

    # ③ 心理状态 → 语气调整
    if (ctx.get("confidence") or 0.5) < 0.4:
        parts.append(
            "【语气提示】该生近期信心不足，请：\n"
            "- 从简单问题切入，先建立成功体验\n"
            "- 指出问题时用「这里有提升空间」而不是「你错了」\n"
            "- 具体肯定进步，不要空洞夸奖"
        )
    elif (ctx.get("anxiety") or 0.0) > 0.6:
        parts.append(
            "【语气提示】该生近期焦虑偏高，请先明确「现在只需要解决哪一个点」，"
            "把任务拆小，避免一次给太多内容。"
        )

    # ④ 薄弱点 → 提醒重点
    weak = ctx.get("weak_points") or []
    if weak:
        wp = "、".join(f"{w['name']}({w['mastery']:.0%})" for w in weak[:3])
        parts.append(f"【重点关注】{wp}")

    # ⑤ 模式洞察 → 针对性建议
    for p in (ctx.get("patterns") or [])[:3]:
        parts.append(f"【模式洞察】{p.get('title','')}\n{p.get('detail','')}\n建议：{p.get('action','')}")

    # ⑥ 跨科目关联
    cs = ctx.get("cross_subject")
    if cs:
        parts.append(
            f"【跨科关联】本知识点与{cs['related_subject_cn']}的「{cs['related_kp']}」"
            f"相关（该生该处掌握度 {cs['related_mastery']:.0%}），可适时提及联动。"
        )

    # ⑦ 历史记忆
    mems = ctx.get("memories") or []
    if mems:
        mem = "\n".join(f"- [{m['type']}] {m['content']}" for m in mems)
        parts.append(f"【历史观察】\n{mem}")

    # ⑧ 输出要求
    parts.append(OUTPUT_REQUIREMENTS)
    return "\n\n".join(parts)


def style_hint_of(profile: UserProfile) -> str:
    return STYLE_HINT.get(profile.primary_style or "", "") if profile else ""
