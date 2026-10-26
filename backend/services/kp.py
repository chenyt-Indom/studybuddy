"""知识点归因与提示（方案约定：不能让模型凭空生成知识点代码）。

正确做法：先从知识点库检索候选，再让模型从候选里选。
这一版用名称/关键词匹配做候选召回，零依赖；换向量检索时只改 candidates()。

**年级过滤是"专精化"的关键一环**：
高一的学生问函数，不该给他召回导数、极限、圆锥曲线 —— 那是高二高三的。
所以召回时按 `grade_rank(kp.grade) <= 学生年级` 收口，`grade="all"` 的贯穿型永远放行。
超过年级的内容不是不能说，而是**要先标明"这是后面的内容"**，这条写进了 prompt。
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgePoint

# 每个知识点补一组口语同义词，提升命中率
ALIASES: dict[str, list[str]] = {
    "math.set": ["集合", "交集", "并集", "补集"],
    "math.logic": ["充分条件", "必要条件", "充要", "量词", "命题"],
    "math.quadratic_function": ["二次函数", "抛物线", "顶点", "配方法", "对称轴"],
    "math.linear_function": ["一次函数", "直线", "斜率"],
    "math.power_function": ["幂函数"],
    "math.function_basic": ["函数", "定义域", "值域", "单调性", "奇偶性"],
    "math.function_zero": ["零点", "二分法", "函数与方程"],
    "math.inequality": ["不等式", "区间", "基本不等式"],
    "math.factorization": ["因式分解", "十字相乘"],
    "math.exponential": ["指数", "幂", "指数函数"],
    "math.logarithm": ["对数", "ln", "log", "换底"],
    "math.trigonometry": ["三角函数", "正弦", "余弦", "正切", "弧度", "诱导公式"],
    "math.trig_identity": ["恒等变换", "两角和", "二倍角", "辅助角"],
    "math.triangle_solve": ["正弦定理", "余弦定理", "解三角形", "面积公式"],
    "math.sequence": ["数列", "等差", "等比", "通项", "前n项和"],
    "math.vector": ["向量", "点积", "数量积", "共线"],
    "math.space_vector": ["空间向量", "法向量", "二面角", "线面角"],
    "math.complex": ["复数", "虚部", "虚数"],
    "math.probability": ["概率", "期望", "分布", "条件概率"],
    "math.permutation": ["排列", "组合", "二项式"],
    "math.random_variable": ["随机变量", "分布列", "方差", "正态分布"],
    "math.statistics": ["统计", "直方图", "回归", "抽样"],
    "math.derivative": ["导数", "求导", "切线", "极值", "单调区间"],
    "math.integral": ["积分", "原函数", "定积分"],
    "math.limit": ["极限"],
    "math.solid_geometry": ["立体几何", "三视图", "体积", "表面积", "线面"],
    "math.line_circle": ["直线与圆", "圆的方程", "点到直线距离"],
    "math.analytic_geometry": ["解析几何", "椭圆", "双曲线", "圆锥曲线", "离心率"],
    "physics.ohm_law": ["欧姆定律", "电阻", "电压", "电流"],
    "physics.circuit": ["电路", "串联", "并联", "内阻", "电源"],
    "physics.closed_circuit": ["闭合电路", "路端电压", "电动势"],
    "physics.motion_basic": ["运动", "位移", "速度", "加速度"],
    "physics.uvm": ["匀变速", "匀加速", "速度时间公式"],
    "physics.free_fall": ["自由落体"],
    "physics.projectile": ["抛体", "平抛", "斜抛"],
    "physics.curvilinear": ["曲线运动"],
    "physics.circular": ["圆周运动", "向心力", "角速度"],
    "physics.newton_law": ["牛顿", "受力", "受力分析", "惯性"],
    "physics.force_composition": ["力的合成", "力的分解", "合力", "正交分解"],
    "physics.gravity_elastic": ["重力", "弹力", "胡克定律"],
    "physics.friction": ["摩擦力", "静摩擦", "滑动摩擦"],
    "physics.equilibrium": ["共点力", "平衡条件"],
    "physics.gravitation": ["万有引力", "卫星", "宇宙速度"],
    "physics.work_power": ["功", "功率"],
    "physics.work_energy": ["功和能", "机械能", "能量守恒"],
    "physics.kinetic_theorem": ["动能定理"],
    "physics.mechanical_energy": ["机械能守恒"],
    "physics.momentum": ["动量", "冲量", "碰撞"],
    "physics.electric_field": ["电场", "电势", "电场强度", "电场线"],
    "physics.coulomb": ["库仑定律"],
    "physics.potential": ["电势能", "电势差", "等势面"],
    "physics.magnetic_field": ["磁场", "洛伦兹", "安培力", "磁感应强度"],
    "physics.ampere_force": ["安培力"],
    "physics.lorentz": ["洛伦兹力"],
    "physics.induction": ["电磁感应", "楞次定律", "法拉第"],
    "physics.ac": ["交变电流", "交流电", "变压器", "有效值"],
    "physics.wave": ["机械波", "波动", "波长"],
    "physics.optics": ["光学", "折射", "全反射", "干涉"],
    "physics.photoelectric": ["光电效应", "光子", "遏止电压"],
    "chemistry.mole": ["物质的量", "摩尔", "摩尔质量", "阿伏加德罗"],
    "chemistry.ion": ["离子反应", "离子方程式", "离子共存"],
    "chemistry.redox": ["氧化还原", "化合价", "电子转移"],
    "chemistry.periodic": ["元素周期律", "周期表"],
    "chemistry.bond": ["化学键", "离子键", "共价键", "电子式"],
    "chemistry.sodium": ["钠", "过氧化钠"],
    "chemistry.chlorine": ["氯", "次氯酸", "漂白"],
    "chemistry.iron": ["铁", "亚铁", "三价铁"],
    "chemistry.energy": ["反应热", "焓变", "盖斯定律"],
    "chemistry.reaction_rate": ["反应速率"],
    "chemistry.equilibrium": ["化学平衡", "平衡移动", "勒夏特列"],
    "chemistry.ionization": ["电离平衡", "弱电解质"],
    "chemistry.ph": ["pH", "水的电离", "离子积"],
    "chemistry.hydrolysis": ["盐类水解"],
    "chemistry.battery": ["原电池", "电极"],
    "chemistry.electrolysis": ["电解", "电解池", "电镀"],
    "chemistry.organic": ["有机", "官能团", "同分异构"],
    "chemistry.experiment": ["化学实验", "除杂", "气体制备"],
    "biology.genetics": ["遗传", "基因", "孟德尔", "分离定律", "自由组合"],
    "biology.cell": ["细胞", "细胞器"],
    "biology.respiration": ["细胞呼吸", "有氧呼吸", "无氧呼吸"],
    "biology.photosynthesis": ["光合作用", "光反应", "暗反应"],
    "biology.dna": ["DNA", "复制", "碱基互补"],
    "biology.gene_expression": ["转录", "翻译", "中心法则"],
    "biology.homeostasis": ["内环境", "稳态"],
    "biology.nerve": ["神经调节", "反射弧", "突触"],
    "biology.immune": ["免疫", "抗体", "淋巴细胞"],
    "chinese.classical": ["文言文", "实词", "虚词", "翻译"],
    "chinese.argumentative": ["议论文", "论证", "论点"],
    "english.grammar": ["语法", "时态", "从句"],
    "english.reading": ["阅读理解", "阅读"],
    "physics.j.ohm": ["欧姆定律", "伏安法"],
    "chemistry.j.acid_base": ["酸碱盐", "中和反应", "复分解"],
}

# 年级顺序（小学 → 大学）。"all" 单独处理，永远可见。
_GRADE_SEQ = [
    "primary_1", "primary_2", "primary_3", "primary_4", "primary_5", "primary_6",
    "junior_1", "junior_2", "junior_3",
    "senior_1", "senior_2", "senior_3",
    "college_1", "college_2", "college_3", "college_4",
]
_RANK = {g: i for i, g in enumerate(_GRADE_SEQ)}


def grade_rank(grade: str | None) -> int | None:
    """年级 → 序号；"all"/空 → None（表示贯穿型，不参与比较）。"""
    if not grade or grade == "all":
        return None
    return _RANK.get(grade)


def is_visible(kp: KnowledgePoint, max_rank: int | None) -> bool:
    """这个知识点对「读到 max_rank 年级」的学生是否已经学过。"""
    if max_rank is None:
        return True
    r = grade_rank(kp.grade)
    return r is None or r <= max_rank


def _text_blob(kp: KnowledgePoint) -> str:
    return " ".join(filter(None, [kp.name, kp.summary, kp.module, kp.keywords]))


def candidates(
    db: Session, subject: str, text: str, limit: int = 20,
    max_grade: str | None = None,
) -> list[dict]:
    """从知识点库检索候选（供模型从中选择，禁止编造 code）。

    max_grade：学生当前年级（如 "senior_1"）。给了就只召回该年级及以前的，
    避免高一的内容里混进导数、圆锥曲线。
    """
    kps = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.subject_key == subject)
    ).all()
    if not kps:
        return []

    max_rank = grade_rank(max_grade)
    pool = [kp for kp in kps if is_visible(kp, max_rank)] or list(kps)

    t = text or ""
    tl = t.lower()
    scored = []
    for kp in pool:
        score = 0.0
        if kp.name and kp.name in t:
            score += 3.0
        for alias in ALIASES.get(kp.kp_code, []):
            if alias and alias.lower() in tl:
                score += 2.0
        # 要点/模块里出现的词也算（学生描述往往不是标准术语）
        for tok in re.split(r"[、，,。；;/\s]+", _text_blob(kp)):
            if len(tok) >= 2 and tok in t:
                score += 0.6
        # 名称片段（如「二次」命中「二次函数」）
        for n in (2, 3):
            if len(kp.name) >= n and kp.name[:n] in t:
                score += 0.3
        if score > 0:
            scored.append((score, kp))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        # 没命中就给高重要度的，避免空列表
        scored = [(0.0, kp) for kp in sorted(pool, key=lambda k: -k.importance)[:8]]

    return [
        {
            "kp_code": kp.kp_code, "name": kp.name, "importance": kp.importance,
            "grade": kp.grade, "module": kp.module,
        }
        for _, kp in scored[:limit]
    ]


def match_kp_codes(
    db: Session, subject: str, text: str, top: int = 2,
    max_grade: str | None = None,
) -> list[str]:
    """规则版归因：直接返回最可能的 kp_code（模型不可用时用）。"""
    cands = candidates(db, subject, text, limit=5, max_grade=max_grade)
    out = []
    t = text or ""
    tl = t.lower()
    for c in cands:
        if c["name"] and c["name"] in t:
            out.append(c["kp_code"])
        else:
            for alias in ALIASES.get(c["kp_code"], []):
                if alias and alias.lower() in tl:
                    out.append(c["kp_code"])
                    break
    # 去重保序
    seen, res = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            res.append(c)
    return res[:top]


def hints_for(db: Session, codes: list[str]) -> list[dict]:
    """把 kp_code 变成「知识点提示」：要点 / 易错 / 记忆锚点。

    这是「提示」功能的落点 —— 讲解时不光说知识点名字，
    还把最容易错的那一句和最好记的那一句递过去。
    """
    if not codes:
        return []
    rows = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.kp_code.in_(codes))
    ).all()
    order = {c: i for i, c in enumerate(codes)}
    rows = sorted(rows, key=lambda k: order.get(k.kp_code, 99))
    return [
        {
            "kp_code": kp.kp_code, "name": kp.name, "subject": kp.subject_key,
            "grade": kp.grade, "module": kp.module,
            "summary": kp.summary, "pitfall": kp.pitfall, "mnemonic": kp.mnemonic,
            "importance": kp.importance, "difficulty": kp.difficulty,
        }
        for kp in rows
    ]


def search_kps(
    db: Session, q: str, subject: str | None = None, stage: str | None = None,
    limit: int = 40,
) -> list[dict]:
    """知识点搜索：名称 / 别名 / 要点 / 模块 都能命中。"""
    q = (q or "").strip()
    if not q:
        return []
    kps = db.scalars(select(KnowledgePoint)).all()
    ql = q.lower()
    hits = []
    for kp in kps:
        if subject and kp.subject_key != subject:
            continue
        if stage and kp.stage != stage:
            continue
        hay = " ".join(filter(None, [
            kp.name, kp.summary, kp.module, kp.keywords,
            " ".join(ALIASES.get(kp.kp_code, [])),
        ]))
        if ql in hay.lower():
            score = 3 if ql in (kp.name or "").lower() else 1
            hits.append((score, kp))
    hits.sort(key=lambda x: (-x[0], -x[1].importance))
    return [
        {"kp_code": kp.kp_code, "name": kp.name, "subject": kp.subject_key,
         "grade": kp.grade, "module": kp.module, "summary": kp.summary}
        for _, kp in hits[:limit]
    ]


def kp_name_map(db: Session) -> dict[str, dict]:
    return {
        kp.kp_code: {"name": kp.name, "subject": kp.subject_key}
        for kp in db.scalars(select(KnowledgePoint))
    }
