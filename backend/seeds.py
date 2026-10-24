"""预置数据：知识点、依赖关系、跨科目关联（方案 C4 数据准备清单）。

按方案建议：先做数学 + 物理两科跑通三个引擎，再扩展。
"""
from __future__ import annotations

from sqlalchemy import select

from .db import session_scope
from .models import CrossSubjectLink, KnowledgePoint, KpDependency

# (kp_code, subject_key, name, stage, importance, difficulty)
KNOWLEDGE_POINTS = [
    # ===== 数学 =====
    ("math.set", "math", "集合", "senior", 0.7, 2),
    ("math.ratio", "math", "比例与比值运算", "senior", 0.7, 2),
    ("math.inequality", "math", "不等式", "senior", 0.8, 3),
    ("math.factorization", "math", "因式分解", "senior", 0.75, 2),
    ("math.function_basic", "math", "函数概念与性质", "senior", 0.95, 3),
    ("math.linear_function", "math", "一次函数", "senior", 0.8, 2),
    ("math.quadratic_function", "math", "二次函数", "senior", 0.95, 4),
    ("math.exponential", "math", "指数函数", "senior", 0.85, 3),
    ("math.logarithm", "math", "对数函数", "senior", 0.85, 4),
    ("math.trigonometry", "math", "三角函数", "senior", 0.9, 4),
    ("math.sequence", "math", "数列", "senior", 0.9, 4),
    ("math.vector", "math", "平面向量", "senior", 0.8, 3),
    ("math.probability", "math", "概率与统计", "senior", 0.85, 3),
    ("math.permutation", "math", "排列组合", "senior", 0.75, 3),
    ("math.limit", "math", "极限", "senior", 0.7, 4),
    ("math.derivative", "math", "导数", "senior", 0.95, 5),
    ("math.integral", "math", "积分", "senior", 0.6, 5),
    ("math.solid_geometry", "math", "立体几何", "senior", 0.85, 4),
    ("math.analytic_geometry", "math", "解析几何", "senior", 0.9, 5),
    # ===== 物理 =====
    ("physics.motion_basic", "physics", "运动学基础", "senior", 0.9, 3),
    ("physics.projectile", "physics", "抛体运动", "senior", 0.8, 4),
    ("physics.newton_law", "physics", "牛顿运动定律", "senior", 0.95, 4),
    ("physics.force_composition", "physics", "力的合成与分解", "senior", 0.8, 3),
    ("physics.work_energy", "physics", "功和能", "senior", 0.9, 4),
    ("physics.momentum", "physics", "动量", "senior", 0.8, 4),
    ("physics.ohm_law", "physics", "欧姆定律", "senior", 0.9, 3),
    ("physics.circuit", "physics", "电路分析", "senior", 0.9, 4),
    ("physics.electric_field", "physics", "电场", "senior", 0.85, 4),
    ("physics.magnetic_field", "physics", "磁场", "senior", 0.85, 4),
    ("physics.wave", "physics", "机械波", "senior", 0.7, 3),
    ("physics.optics", "physics", "光学", "senior", 0.7, 3),
    # ===== 化学 =====
    ("chemistry.mole", "chemistry", "物质的量", "senior", 0.9, 3),
    ("chemistry.reaction_rate", "chemistry", "反应速率", "senior", 0.8, 3),
    ("chemistry.equilibrium", "chemistry", "化学平衡", "senior", 0.9, 5),
    ("chemistry.organic", "chemistry", "有机化学基础", "senior", 0.85, 4),
    # ===== 生物 =====
    ("biology.genetics", "biology", "遗传规律", "senior", 0.9, 4),
    ("biology.cell", "biology", "细胞结构", "senior", 0.8, 2),
    # ===== 语文 / 英语 =====
    ("chinese.classical", "chinese", "文言文阅读", "senior", 0.9, 4),
    ("chinese.argumentative", "chinese", "议论文写作", "senior", 0.85, 4),
    ("english.grammar", "english", "英语语法", "senior", 0.9, 3),
    ("english.reading", "english", "阅读理解", "senior", 0.95, 3),
]

# 知识点 → 前置依赖（P4 知识断层识别）
KP_DEPENDENCIES = [
    ("math.quadratic_function", "math.inequality"),
    ("math.quadratic_function", "math.factorization"),
    ("math.logarithm", "math.exponential"),
    ("math.logarithm", "math.function_basic"),
    ("math.derivative", "math.limit"),
    ("math.derivative", "math.function_basic"),
    ("math.integral", "math.derivative"),
    ("math.analytic_geometry", "math.quadratic_function"),
    ("math.trigonometry", "math.function_basic"),
    ("math.probability", "math.permutation"),
    ("physics.circuit", "physics.ohm_law"),
    ("physics.circuit", "math.linear_function"),
    ("physics.projectile", "math.quadratic_function"),
    ("physics.projectile", "physics.newton_law"),
    ("physics.motion_basic", "physics.newton_law"),
    ("physics.work_energy", "physics.newton_law"),
    ("physics.momentum", "physics.work_energy"),
    ("physics.electric_field", "physics.force_composition"),
    ("chemistry.equilibrium", "chemistry.reaction_rate"),
    ("chemistry.equilibrium", "math.ratio"),
    ("chemistry.mole", "math.ratio"),
    ("biology.genetics", "math.probability"),
]

# 跨科目关联（第三章问题一表格）
CROSS_LINKS = [
    ("math.function_basic", "physics.motion_basic", "tool_for", 0.9, "函数图像是运动图像的数学工具"),
    ("math.quadratic_function", "physics.projectile", "tool_for", 0.95, "抛体运动本质是二次函数"),
    ("math.linear_function", "physics.ohm_law", "tool_for", 0.9, "U-I 图像是线性函数"),
    ("math.probability", "biology.genetics", "tool_for", 0.9, "概率是遗传计算基础"),
    ("math.vector", "physics.force_composition", "tool_for", 0.95, "向量是受力分析工具"),
    ("math.derivative", "physics.motion_basic", "concept_shared", 0.8, "速度/加速度即位移的导数"),
    ("math.exponential", "chemistry.reaction_rate", "concept_shared", 0.7, "指数衰减/增长模型"),
    ("chinese.classical", "chinese.argumentative", "same_skill", 0.6, "阅读能力互通"),
    ("english.grammar", "chinese.classical", "same_skill", 0.5, "语法概念相通"),
]


def load_seeds() -> None:
    with session_scope() as db:
        existing = {kp.kp_code for kp in db.scalars(select(KnowledgePoint))}
        if not existing:
            for code, subj, name, stage, imp, diff in KNOWLEDGE_POINTS:
                db.add(
                    KnowledgePoint(
                        kp_code=code,
                        subject_key=subj,
                        name=name,
                        stage=stage,
                        importance=imp,
                        difficulty=diff,
                    )
                )

        if not db.scalars(select(KpDependency)).first():
            for child, parent in KP_DEPENDENCIES:
                db.add(KpDependency(kp_code=child, depends_on=parent))

        if not db.scalars(select(CrossSubjectLink)).first():
            for a, b, rel, strength, note in CROSS_LINKS:
                db.add(
                    CrossSubjectLink(
                        from_kp=a, to_kp=b, relation_type=rel, strength=strength, note=note
                    )
                )
