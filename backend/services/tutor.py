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

    # ① 年级约束：先框死范围，避免拿高年级工具解低年级的题
    grade_cn = ctx.get("grade_cn") or GRADE_CN.get(ctx.get("grade") or "", "")
    if grade_cn:
        parts.append(
            f"【年级约束】该生读{grade_cn}。讲解**优先用{grade_cn}及以前学过的概念、符号和方法**，"
            "不要默认他掌握更高年级的工具。\n"
            "如果这道题绕不开更高年级的内容（例如初中题用相似与勾股、高一题碰导数），"
            "先用一句话说明「这属于X年级的内容」，再给一个当前年级能听懂的说法或结论，"
            "并提示他什么时候会正式学。"
        )

    # ①b 时间感知
    parts.append(ctx.get("time_line") or _default_time_line())

    # ①b 学习档案（综述层）：整体背景，比单条记忆更像"了解这个人"
    docs = ctx.get("profile_docs")
    if docs:
        parts.append(
            "【学习档案】以下是长期积累的档案综述，用于把握整体情况，"
            "**不要整段复述给用户**，只在讲法、举例、难度上体现。\n\n" + docs
        )

    # ①c 教材定位：对齐课本章节，顺序和符号约定才对得上
    tb = ctx.get("textbook")
    if tb and tb.get("text") and tb.get("matched"):
        vols = "、".join(tb.get("volumes") or [tb.get("volume") or ""])
        parts.append(
            f"【教材定位】学生用的是《{tb['textbook']}》（{vols}）。\n"
            f"与本次问题相关的章节：\n{tb['text']}\n"
            "讲解时请**沿用该教材的章节顺序、术语和符号约定**，"
            "必要时说明「这在你课本的哪一册哪一节」。不要整段照抄教材原文。"
        )

    # ①d 题目图片：先对题再讲，看不清就说看不清
    n_img = ctx.get("images") or 0
    if n_img:
        parts.append(
            f"【题目图片】学生这次上传了 {n_img} 张图片（可能是题目截图、手写解答或课本照片）。\n"
            "请严格按这个顺序处理：\n"
            "1. **先复述题目**：用一两句话说出你从图里读到的已知条件、要求什么、"
            "关键数字与符号，让学生确认你读对了；\n"
            "2. 然后按上面的讲法讲解（风格、教材定位、学生薄弱点都要体现）；\n"
            "3. 图片模糊、被遮挡、关键数字或符号看不清时，**直接说看不清并指出是哪一处**，"
            "请学生补拍或补充文字，**绝对不要猜题目条件或数字**；\n"
            "4. 不要描述图片本身（比如「这是一张纸」「光线偏暗」），只讲题目内容。\n"
            "如果是学生自己的解答，先判断他做到哪一步、哪一步开始出错，再针对那一步讲。"
        )

    # ①e 知识点提示：把「最该记住的」和「最容易错的」直接递到嘴边
    hints = ctx.get("kp_hints") or []
    if hints:
        blocks = []
        for h in hints[:3]:
            lines = [f"- {h.get('name') or ''}"]
            if h.get("summary"):
                lines.append(f"  要点：{h['summary']}")
            if h.get("pitfall"):
                lines.append(f"  易错：{h['pitfall']}")
            if h.get("mnemonic"):
                lines.append(f"  记忆锚点：{h['mnemonic']}")
            blocks.append("\n".join(lines))
        parts.append(
            "【知识点提示】以下是课本口径的要点、常见易错和记忆锚点。\n"
            "用法：把「易错」那一条**明确指出**（如果学生正踩在上面），"
            "把「记忆锚点」自然地讲成一句口诀，**不要原文照念成列表**。\n\n"
            + "\n".join(blocks)
        )

    # ①f 外部教材摘录（IMA）：用来校准术语/顺序，不是拿来照抄的
    ext = ctx.get("ext_textbook") or {}
    if ext.get("items"):
        from .ext_kb import render_context
        body = render_context(ext)
        if body:
            parts.append(
                "【教材摘录】以下是从教材知识库检索到的原文片段（不是我的记忆）。\n"
                "用法：**只用来校准术语、符号、章节顺序和课本口径**；"
                "讲解时用自己的话，**不要整段照抄**，也不要说「课本原话是…」除非摘录里确实有。\n"
                "如果摘录与你的记忆冲突，以摘录为准，并说明依据。\n\n" + body
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

    # ⑥ 跨学科联动 —— 目的是**好记、记得久**，不是炫知识面
    cs = ctx.get("cross_subject")
    if cs:
        m = cs.get("related_mastery")
        strength = "他已经比较熟" if (m or 0) >= 0.6 else (
            "他那里也不太稳，正好一起补" if m is not None else "还没测过"
        )
        parts.append(
            f"【跨科联动·记忆锚点】本知识点可以用{cs['related_subject_cn']}的"
            f"「{cs['related_kp']}」来锚定（{cs['relation_cn']}，{strength}）。\n"
            f"怎么借力：{cs.get('note') or ''}\n"
            "用法：**最多点一次**，用「这个你其实在X科学过」这种一句话建立连接，"
            "然后回到本题。不要展开成两科对比，更不要为了联动而联动。"
        )

    # ⑦ 历史记忆（分两层展示：关于这个人 / 关于这个学科）
    mems = ctx.get("memories") or []
    if mems:
        type_cn = {
            "identity": "身份", "goal": "目标", "habit": "习惯", "preference": "偏好",
            "emotion": "情绪", "weakness": "薄弱", "misconception": "误区",
            "observation": "观察",
        }
        g = [m for m in mems if m.get("scope") == "global"]
        s_ = [m for m in mems if m.get("scope") != "global"]
        blocks = []
        if g:
            blocks.append(
                "关于这个学生（跨学科，长期有效）：\n"
                + "\n".join(
                    f"- [{type_cn.get(m['type'], m['type'])}] {m['content']}"
                    for m in g
                )
            )
        if s_:
            blocks.append(
                "关于本学科的历史观察：\n"
                + "\n".join(
                    f"- [{type_cn.get(m['type'], m['type'])}] {m['content']}"
                    for m in s_
                )
            )
        parts.append(
            "【历史观察】以下是用长期记忆库记录的信息，用于调整讲法，**不要直接复述给用户**。\n"
            "如果它与本次对话内容矛盾，以本次对话为准。\n\n" + "\n\n".join(blocks)
        )

    # ⑧ 联网检索到的实时资料（有才加）
    search_ctx = ctx.get("search_context")
    if search_ctx:
        parts.append(
            "【联网检索结果】以下是刚刚实时检索到的网页摘要，"
            "回答涉及时效性内容时**优先以此为准**，并在句末用 [1] [2] 这样的编号标注来源。\n"
            "如果资料与你的记忆冲突，以资料为准；如果资料不足以回答，明确说明缺什么。\n\n"
            f"{search_ctx}"
        )

    # ⑨ 输出要求
    parts.append(OUTPUT_REQUIREMENTS)
    return "\n\n".join(parts)


def _default_time_line() -> str:
    from ..config import now_context

    c = now_context()
    return (
        f"【当前时间】现在是 {c['display']}（北京时间）。"
        "回答时效性问题时以此时间为准。"
    )


def style_hint_of(profile: UserProfile) -> str:
    return STYLE_HINT.get(profile.primary_style or "", "") if profile else ""
