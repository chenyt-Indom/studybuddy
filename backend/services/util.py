"""公共工具：大模型 JSON 输出的健壮解析（方案多次强调「健壮解析」）。"""
from __future__ import annotations

import json
import re
from typing import Any


def parse_json_loose(text: str, expect: type | tuple[type, ...] = (list, dict)) -> Any:
    """从模型输出里抠出 JSON。

    模型常见毛病：包 ```json 代码块、前后加解释、尾随逗号、单引号。
    """
    if not text:
        raise ValueError("空输出")
    t = text.strip()

    # 优先取代码块
    fence = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()

    # 直接解析
    try:
        v = json.loads(t)
        if isinstance(v, expect):
            return v
    except json.JSONDecodeError:
        pass

    # 截取最外层数组/对象
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = t.find(open_ch)
        end = t.rfind(close_ch)
        if start != -1 and end > start:
            frag = t[start : end + 1]
            frag = re.sub(r",\s*([}\]])", r"\1", frag)  # 去尾随逗号
            try:
                v = json.loads(frag)
                if isinstance(v, expect):
                    return v
            except json.JSONDecodeError:
                continue
    raise ValueError(f"无法解析为 JSON：{text[:200]}")
