"""SM-2 间隔重复调度器（方案 6.2）。

每个知识点维护三个参数：
  EF (Easiness Factor)：难度因子，1.3~2.5，越高表示越容易
  interval：当前复习间隔（天）
  repetitions：连续答对次数
每次复习后根据评分（0~5）更新这三个参数。
"""
from __future__ import annotations

from datetime import datetime, timedelta


class SM2Scheduler:
    MIN_EF = 1.3
    MAX_EF = 2.5

    @staticmethod
    def update(state: dict, quality: int, now: datetime | None = None) -> dict:
        """根据复习表现更新调度状态。

        quality:
            5 = 完美回忆，秒答
            4 = 正确，略有犹豫
            3 = 正确，但很吃力
            2 = 错误，但看到答案想起来
            1 = 错误，看到答案仍不理解
            0 = 完全不会
        """
        now = now or datetime.now()
        quality = max(0, min(5, int(quality)))

        ef = float(state.get("ef", 2.5))
        interval = int(state.get("interval", 0))
        reps = int(state.get("repetitions", 0))

        # ① 更新难度因子 EF
        # EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
        delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        ef = ef + delta
        ef = max(SM2Scheduler.MIN_EF, min(SM2Scheduler.MAX_EF, ef))

        # ② 更新间隔
        if quality < 3:
            reps = 0
            interval = 1  # 明天再来
        else:
            reps += 1
            if reps == 1:
                interval = 1
            elif reps == 2:
                interval = 6
            else:
                interval = round(interval * ef)  # 关键：乘以难度因子

        return {
            "ef": round(ef, 3),
            "interval": interval,
            "repetitions": reps,
            "next_review": now + timedelta(days=interval),
            "last_review": now,
        }
