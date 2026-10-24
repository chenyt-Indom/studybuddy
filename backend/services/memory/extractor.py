"""记忆提取（方案 8.2 / 附录 A2）。

⚠ 必须异步：写记忆不能拖慢对话响应。走 asyncio.create_task。
"""
from __future__ import annotations

from ...config import TEMPERATURE_MAP
from ...prompts import MEMORY_EXTRACT_PROMPT
from ..llm.teleai import get_provider
from ..util import parse_json_loose
from .store import add_memory

VALID_TYPES = {"weakness", "misconception", "preference", "habit", "emotion", "goal"}


async def extract_memories(conversation_text: str, subject: str) -> list[dict]:
    """从一段对话里提取关于学生的长期信息。失败返回空列表，不抛。"""
    if not conversation_text.strip():
        return []
    llm = get_provider()
    try:
        raw = await llm.chat(
            [
                {"role": "system", "content": "你只输出 JSON，不写任何解释。"},
                {
                    "role": "user",
                    "content": MEMORY_EXTRACT_PROMPT.format(
                        conversation=conversation_text[:4000]
                    ),
                },
            ],
            temperature=TEMPERATURE_MAP["extract_memory"],
            max_tokens=800,
            scene="extract_memory",
        )
        data = parse_json_loose(raw, (list, dict))
        if isinstance(data, dict):
            data = data.get("memories") or data.get("items") or []
        out = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            t = str(item.get("type") or "observation").strip()
            out.append(
                {
                    "type": t if t in VALID_TYPES else "observation",
                    "content": content[:120],
                    "keywords": str(item.get("keywords") or "")[:200],
                    "subject": subject,
                }
            )
        return out
    except Exception:
        return []


def persist_memories(db, user_id: int, items: list[dict]) -> int:
    n = 0
    for it in items:
        if add_memory(
            db,
            user_id=user_id,
            content=it["content"],
            mtype=it["type"],
            subject_key=it.get("subject"),
            keywords=it.get("keywords", ""),
        ):
            n += 1
    return n
