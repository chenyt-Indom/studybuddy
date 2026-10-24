"""记忆强度建模（方案 6.3）。

SM-2 给的是「什么时候复习」，这里给的是「现在还记得多少」——用于可视化。
指数衰减模型：R = exp(-t / S)
  t = 距上次复习天数
  S = 稳定性，由 EF 和重复次数决定
"""
from __future__ import annotations

import math
from datetime import datetime


def memory_strength(state: dict, now: datetime | None = None) -> float:
    now = now or datetime.now()
    last = state.get("last_review")
    if not last:
        return 0.0
    t = (now - last).total_seconds() / 86400  # 天数
    if t < 0:
        t = 0.0
    ef = float(state.get("ef", 2.5))
    reps = int(state.get("repetitions", 0))
    # 稳定性：基础稳定性 × 难度因子 × 重复次数加成
    S = 1.0 * (ef / 2.5) * (1 + 0.8 * reps)
    if S <= 0:
        return 0.0
    return max(0.0, min(1.0, math.exp(-t / S)))


def curve_points(state: dict, days: int = 30, points: int = 30) -> list[dict]:
    """给前端画遗忘曲线用：未来 days 天内每天的记忆强度。"""
    last = state.get("last_review")
    if not last:
        return []
    ef = float(state.get("ef", 2.5))
    reps = int(state.get("repetitions", 0))
    S = 1.0 * (ef / 2.5) * (1 + 0.8 * reps)
    step = max(1, days // points)
    out = []
    for d in range(0, days + 1, step):
        out.append(
            {"day": d, "strength": round(max(0.0, min(1.0, math.exp(-d / S))), 4)}
        )
    return out
