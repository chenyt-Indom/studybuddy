"""复习卡片自动生成（方案 6.6）。"""
from __future__ import annotations

from ...config import TEMPERATURE_MAP
from ...models import KnowledgePoint, KpMastery, Mistake
from ...prompts import CARD_PROMPT
from ..llm.teleai import get_provider
from ..util import parse_json_loose


async def generate_cards(
    kp: KnowledgePoint,
    mastery: float,
    last_error: str | None,
    style: str | None,
) -> list[dict]:
    llm = get_provider()
    prompt = CARD_PROMPT.format(
        subject=kp.subject_key,
        kp_name=kp.name,
        mastery=f"{mastery:.0%}",
        last_error=last_error or "暂无记录",
        style=style or "未确定",
    )
    try:
        raw = await llm.chat(
            [
                {"role": "system", "content": "你只输出 JSON，不写任何解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=TEMPERATURE_MAP["generate_quiz"],
            max_tokens=1200,
            scene="card",
        )
        cards = parse_json_loose(raw, list)
        out = []
        for c in cards[:3]:
            if isinstance(c, dict) and c.get("q"):
                out.append(
                    {
                        "q": str(c.get("q", "")),
                        "a": str(c.get("a", "")),
                        "hint": str(c.get("hint", "")),
                    }
                )
        if out:
            return out
    except Exception:
        pass
    # 兜底：保证 UI 不空白（方案要求「失败时返回兜底结构，不打断流程」）
    return [
        {
            "q": f"用自己的话说明「{kp.name}」的核心定义",
            "a": "（离线兜底卡片，接入星辰 API 后会自动生成针对性题目）",
            "hint": "先回忆定义，再想一个反例",
        },
        {
            "q": f"给出一道用到「{kp.name}」的典型题，并写出解题第一步",
            "a": "（离线兜底卡片）",
            "hint": "重点看是不是先识别题型",
        },
        {
            "q": f"「{kp.name}」最容易错的地方是什么？",
            "a": "（离线兜底卡片）",
            "hint": "回忆最近一次做错的细节",
        },
    ]
