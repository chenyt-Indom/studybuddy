"""知识点归因（方案约定：不能让模型凭空生成知识点代码）。

正确做法：先从知识点库检索候选，再让模型从候选里选。
这一版用名称/关键词匹配做候选召回，零依赖；换向量检索时只改 candidates()。
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgePoint

# 每个知识点补一组口语同义词，提升命中率
ALIASES: dict[str, list[str]] = {
    "math.quadratic_function": ["二次函数", "抛物线", "顶点", "配方法"],
    "math.linear_function": ["一次函数", "直线", "斜率"],
    "math.function_basic": ["函数", "定义域", "值域", "单调性"],
    "math.inequality": ["不等式", "区间"],
    "math.factorization": ["因式分解", "十字相乘"],
    "math.exponential": ["指数", "幂"],
    "math.logarithm": ["对数", "ln", "log"],
    "math.trigonometry": ["三角函数", "正弦", "余弦", "正切", "弧度"],
    "math.sequence": ["数列", "等差", "等比"],
    "math.vector": ["向量", "点积", "数量积"],
    "math.probability": ["概率", "期望", "分布"],
    "math.derivative": ["导数", "求导", "切线", "极值"],
    "math.integral": ["积分", "原函数"],
    "math.solid_geometry": ["立体几何", "三视图", "体积"],
    "math.analytic_geometry": ["解析几何", "椭圆", "双曲线", "圆锥曲线"],
    "math.limit": ["极限"],
    "math.permutation": ["排列", "组合"],
    "physics.ohm_law": ["欧姆定律", "电阻", "电压", "电流"],
    "physics.circuit": ["电路", "串联", "并联", "内阻", "电源"],
    "physics.motion_basic": ["运动", "位移", "速度", "加速度"],
    "physics.projectile": ["抛体", "平抛", "斜抛"],
    "physics.newton_law": ["牛顿", "受力", "受力分析"],
    "physics.force_composition": ["力的合成", "力的分解", "合力"],
    "physics.work_energy": ["功", "动能", "机械能", "能量守恒"],
    "physics.momentum": ["动量", "冲量", "碰撞"],
    "physics.electric_field": ["电场", "电势", "电场强度"],
    "physics.magnetic_field": ["磁场", "洛伦兹", "安培力"],
    "physics.wave": ["机械波", "波动", "波长"],
    "physics.optics": ["光学", "折射", "全反射"],
    "chemistry.mole": ["物质的量", "摩尔", "摩尔质量"],
    "chemistry.reaction_rate": ["反应速率"],
    "chemistry.equilibrium": ["化学平衡", "平衡移动", "勒夏特列"],
    "chemistry.organic": ["有机", "官能团"],
    "biology.genetics": ["遗传", "基因", "孟德尔", "分离定律"],
    "biology.cell": ["细胞", "细胞器"],
    "chinese.classical": ["文言文", "实词", "虚词", "翻译"],
    "chinese.argumentative": ["议论文", "论证", "论点"],
    "english.grammar": ["语法", "时态", "从句"],
    "english.reading": ["阅读理解", "阅读"],
}


def candidates(db: Session, subject: str, text: str, limit: int = 20) -> list[dict]:
    """从知识点库检索候选（供模型从中选择，禁止编造 code）。"""
    kps = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.subject_key == subject)
    ).all()
    if not kps:
        return []

    t = text or ""
    scored = []
    for kp in kps:
        score = 0.0
        if kp.name and kp.name in t:
            score += 3.0
        for alias in ALIASES.get(kp.kp_code, []):
            if alias and alias.lower() in t.lower():
                score += 2.0
        # 名称片段（如「二次」命中「二次函数」）
        for n in (2, 3):
            if len(kp.name) >= n and kp.name[:n] in t:
                score += 0.3
        if score > 0:
            scored.append((score, kp))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        # 没命中就给高重要度的，避免空列表
        scored = [(0.0, kp) for kp in sorted(kps, key=lambda k: -k.importance)[:8]]

    return [
        {"kp_code": kp.kp_code, "name": kp.name, "importance": kp.importance}
        for _, kp in scored[:limit]
    ]


def match_kp_codes(db: Session, subject: str, text: str, top: int = 2) -> list[str]:
    """规则版归因：直接返回最可能的 kp_code（模型不可用时用）。"""
    cands = candidates(db, subject, text, limit=5)
    out = []
    t = text or ""
    for c in cands:
        if c["name"] and c["name"] in t:
            out.append(c["kp_code"])
        else:
            for alias in ALIASES.get(c["kp_code"], []):
                if alias and alias.lower() in t.lower():
                    out.append(c["kp_code"])
                    break
    # 去重保序
    seen, res = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            res.append(c)
    return res[:top]


def kp_name_map(db: Session) -> dict[str, dict]:
    return {
        kp.kp_code: {"name": kp.name, "subject": kp.subject_key}
        for kp in db.scalars(select(KnowledgePoint))
    }
