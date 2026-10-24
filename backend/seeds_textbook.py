"""内置教材结构（公开目录，不含正文）。

⚠️ 版权声明：这里只有**章/节标题与知识点顺序**，属于公开信息。
   教材正文一律不入库；用户自己导入的正版 PDF 也只存本地、不外传、不随仓库分发。

数据来源：人教A版（2019）数学、人教版（2019）物理的公开目录。
讲解时用它把知识点"定位"到课本：第几章第几节，这样顺序和符号约定才对得上。
"""
from __future__ import annotations

from sqlalchemy import select

from .db import session_scope
from .models import Textbook, TextbookSection

# ---------------------------------------------------------------- 版本注册表
# 「选教材版本」= 选出版社 + 修订年。这里只列真实存在的版本；
# builtin=True 表示本项目内置了该版本的公开目录结构，False 表示需要用户自己导入。
EDITIONS: dict[str, list[dict]] = {
    "senior|math": [
        {"code": "rja", "name": "人教A版", "publisher": "人民教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": True},
        {"code": "rjb", "name": "人教B版", "publisher": "人民教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "bsd", "name": "北师大版", "publisher": "北京师范大学出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "sj", "name": "苏教版", "publisher": "江苏凤凰教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "xj", "name": "湘教版", "publisher": "湖南教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
    ],
    "senior|physics": [
        {"code": "rj", "name": "人教版", "publisher": "人民教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": True},
        {"code": "jk", "name": "教科版", "publisher": "教育科学出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "hk", "name": "沪科版", "publisher": "上海科学技术出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "yj", "name": "粤教版", "publisher": "广东教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "lk", "name": "鲁科版", "publisher": "山东科学技术出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
    ],
    "senior|chemistry": [
        {"code": "rj", "name": "人教版", "publisher": "人民教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "sj", "name": "苏教版", "publisher": "江苏凤凰教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "lk", "name": "鲁科版", "publisher": "山东科学技术出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
    ],
    "senior|biology": [
        {"code": "rj", "name": "人教版", "publisher": "人民教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "sj", "name": "苏教版", "publisher": "江苏凤凰教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "bsd", "name": "北师大版", "publisher": "北京师范大学出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
    ],
    "senior|chinese": [
        {"code": "tjb", "name": "统编版（人教）", "publisher": "人民教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "sj", "name": "苏教版", "publisher": "江苏凤凰教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
    ],
    "senior|english": [
        {"code": "rj", "name": "人教版", "publisher": "人民教育出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "wy", "name": "外研版", "publisher": "外语教学与研究出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "bsd", "name": "北师大版", "publisher": "北京师范大学出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
        {"code": "yl", "name": "译林版", "publisher": "译林出版社",
         "edition": "2019年版", "year": 2019, "builtin": False},
    ],
    "junior|math": [
        {"code": "rj", "name": "人教版", "publisher": "人民教育出版社",
         "edition": "2013年版（2024修订）", "year": 2024, "builtin": False},
        {"code": "bsd", "name": "北师大版", "publisher": "北京师范大学出版社",
         "edition": "2013年版（2024修订）", "year": 2024, "builtin": False},
        {"code": "hdsd", "name": "华师大版", "publisher": "华东师范大学出版社",
         "edition": "2013年版", "year": 2013, "builtin": False},
        {"code": "sk", "name": "苏科版", "publisher": "江苏凤凰科学技术出版社",
         "edition": "2013年版", "year": 2013, "builtin": False},
    ],
}

# 内置目录对应的版本标记
BUNDLED_EDITION = {
    "rj_a_math_bx1": ("rja", "人教A版", 2019),
    "rj_a_math_bx2": ("rja", "人教A版", 2019),
    "rj_a_math_xbx1": ("rja", "人教A版", 2019),
    "rj_a_math_xbx2": ("rja", "人教A版", 2019),
    "rj_phy_bx1": ("rj", "人教版", 2019),
    "rj_phy_bx2": ("rj", "人教版", 2019),
    "rj_phy_bx3": ("rj", "人教版", 2019),
}


def editions_for(stage: str, subject_key: str) -> list[dict]:
    return EDITIONS.get(f"{stage}|{subject_key}", [])


# 结构：code -> (标题, 科目, 学段, 年级, 册次, 出版社, [(章, 节, [kp_code...], 关键词)])
BUNDLED: dict[str, tuple] = {
    # ==================== 人教A版 数学 必修第一册 ====================
    "rj_a_math_bx1": (
        "人教A版 高中数学 必修第一册", "math", "senior", "senior_1", "必修第一册", "人教A版", [
            ("第一章 集合与常用逻辑用语", "1.1 集合的概念", ["math.set"], "集合,元素,列举法,描述法"),
            ("第一章 集合与常用逻辑用语", "1.2 集合间的基本关系", ["math.set"], "子集,真子集,集合相等"),
            ("第一章 集合与常用逻辑用语", "1.3 集合的基本运算", ["math.set"], "交集,并集,补集"),
            ("第一章 集合与常用逻辑用语", "1.4 充分条件与必要条件", ["math.set"], "充分,必要,充要"),
            ("第一章 集合与常用逻辑用语", "1.5 全称量词与存在量词", ["math.set"], "全称量词,存在量词,否定"),
            ("第二章 一元二次函数、方程和不等式", "2.1 等式性质与不等式性质", ["math.inequality"], "不等式性质,作差法"),
            ("第二章 一元二次函数、方程和不等式", "2.2 基本不等式", ["math.inequality"], "基本不等式,最值"),
            ("第二章 一元二次函数、方程和不等式", "2.3 二次函数与一元二次方程、不等式", ["math.quadratic_function", "math.inequality"], "二次不等式,根分布,判别式"),
            ("第三章 函数的概念与性质", "3.1 函数的概念及其表示", ["math.function_basic"], "定义域,值域,解析式,分段函数"),
            ("第三章 函数的概念与性质", "3.2 函数的基本性质", ["math.function_basic"], "单调性,奇偶性,最值"),
            ("第三章 函数的概念与性质", "3.3 幂函数", ["math.function_basic"], "幂函数,指数"),
            ("第三章 函数的概念与性质", "3.4 函数的应用（一）", ["math.function_basic", "math.linear_function"], "函数模型,实际应用"),
            ("第四章 指数函数与对数函数", "4.1 指数", ["math.exponential"], "根式,分数指数幂,运算性质"),
            ("第四章 指数函数与对数函数", "4.2 指数函数", ["math.exponential"], "指数函数,图像,单调性"),
            ("第四章 指数函数与对数函数", "4.3 对数", ["math.logarithm"], "对数定义,运算性质,换底公式"),
            ("第四章 指数函数与对数函数", "4.4 对数函数", ["math.logarithm"], "对数函数,图像,反函数"),
            ("第四章 指数函数与对数函数", "4.5 函数的应用（二）", ["math.exponential", "math.logarithm"], "零点,二分法"),
            ("第五章 三角函数", "5.1 任意角和弧度制", ["math.trigonometry"], "弧度制,终边相同角"),
            ("第五章 三角函数", "5.2 三角函数的概念", ["math.trigonometry"], "正弦,余弦,正切,单位圆"),
            ("第五章 三角函数", "5.3 诱导公式", ["math.trigonometry"], "诱导公式,符号"),
            ("第五章 三角函数", "5.4 三角函数的图象与性质", ["math.trigonometry"], "周期,对称轴,单调区间"),
            ("第五章 三角函数", "5.5 三角恒等变换", ["math.trigonometry"], "两角和差,二倍角,辅助角"),
            ("第五章 三角函数", "5.6 函数 y=Asin(ωx+φ)", ["math.trigonometry"], "振幅,周期,相位,平移"),
            ("第五章 三角函数", "5.7 三角函数的应用", ["math.trigonometry"], "简谐运动,实际建模"),
        ],
    ),
    # ==================== 人教A版 数学 必修第二册 ====================
    "rj_a_math_bx2": (
        "人教A版 高中数学 必修第二册", "math", "senior", "senior_1", "必修第二册", "人教A版", [
            ("第六章 平面向量及其应用", "6.1 平面向量的概念", ["math.vector"], "向量,相等向量,共线向量"),
            ("第六章 平面向量及其应用", "6.2 平面向量的运算", ["math.vector"], "加减法,数乘,数量积"),
            ("第六章 平面向量及其应用", "6.3 平面向量基本定理及坐标表示", ["math.vector"], "基底,坐标运算"),
            ("第六章 平面向量及其应用", "6.4 平面向量的应用", ["math.vector", "math.trigonometry"], "正弦定理,余弦定理"),
            ("第八章 立体几何初步", "8.1 基本立体图形", ["math.solid_geometry"], "棱柱,棱锥,球"),
            ("第八章 立体几何初步", "8.2 立体图形的直观图", ["math.solid_geometry"], "斜二测画法"),
            ("第八章 立体几何初步", "8.3 简单几何体的表面积与体积", ["math.solid_geometry"], "表面积,体积"),
            ("第八章 立体几何初步", "8.4 空间点、直线、平面之间的位置关系", ["math.solid_geometry"], "异面直线,公理"),
            ("第八章 立体几何初步", "8.5 空间直线、平面的平行", ["math.solid_geometry"], "线面平行,面面平行"),
            ("第八章 立体几何初步", "8.6 空间直线、平面的垂直", ["math.solid_geometry"], "线面垂直,二面角"),
            ("第十章 概率", "10.1 随机事件与概率", ["math.probability"], "样本空间,古典概型"),
            ("第十章 概率", "10.2 事件的相互独立性", ["math.probability"], "独立,乘法公式"),
            ("第十章 概率", "10.3 频率与概率", ["math.probability"], "频率,随机模拟"),
        ],
    ),
    # ==================== 人教A版 数学 选择性必修第一册 ====================
    "rj_a_math_xbx1": (
        "人教A版 高中数学 选择性必修第一册", "math", "senior", "senior_2",
        "选择性必修第一册", "人教A版", [
            ("第一章 空间向量与立体几何", "1.1 空间向量及其运算", ["math.vector", "math.solid_geometry"], "空间向量,坐标"),
            ("第一章 空间向量与立体几何", "1.4 空间向量的应用", ["math.vector", "math.solid_geometry"], "法向量,夹角"),
            ("第二章 直线和圆的方程", "2.1 直线的倾斜角与斜率", ["math.analytic_geometry", "math.linear_function"], "斜率,倾斜角"),
            ("第二章 直线和圆的方程", "2.2 直线的方程", ["math.analytic_geometry"], "点斜式,一般式"),
            ("第二章 直线和圆的方程", "2.4 圆的方程", ["math.analytic_geometry"], "圆的标准方程,一般方程"),
            ("第三章 圆锥曲线的方程", "3.1 椭圆", ["math.analytic_geometry"], "椭圆,离心率,焦点"),
            ("第三章 圆锥曲线的方程", "3.2 双曲线", ["math.analytic_geometry"], "双曲线,渐近线"),
            ("第三章 圆锥曲线的方程", "3.3 抛物线", ["math.analytic_geometry", "math.quadratic_function"], "抛物线,准线,焦半径"),
        ],
    ),
    # ==================== 人教A版 数学 选择性必修第二册 ====================
    "rj_a_math_xbx2": (
        "人教A版 高中数学 选择性必修第二册", "math", "senior", "senior_2",
        "选择性必修第二册", "人教A版", [
            ("第四章 数列", "4.1 数列的概念", ["math.sequence"], "通项公式,递推"),
            ("第四章 数列", "4.2 等差数列", ["math.sequence"], "公差,前n项和"),
            ("第四章 数列", "4.3 等比数列", ["math.sequence"], "公比,求和公式"),
            ("第四章 数列", "4.4 数学归纳法", ["math.sequence"], "归纳法,证明"),
            ("第五章 一元函数的导数及其应用", "5.1 导数的概念及其意义", ["math.derivative", "math.limit"], "瞬时变化率,切线"),
            ("第五章 一元函数的导数及其应用", "5.2 导数的运算", ["math.derivative"], "求导公式,四则运算,复合函数"),
            ("第五章 一元函数的导数及其应用", "5.3 导数在研究函数中的应用", ["math.derivative"], "单调性,极值,最值"),
        ],
    ),
    # ==================== 人教版 物理 必修第一册 ====================
    "rj_phy_bx1": (
        "人教版 高中物理 必修第一册", "physics", "senior", "senior_1", "必修第一册", "人教版", [
            ("第一章 运动的描述", "1. 质点 参考系", ["physics.motion_basic"], "质点,参考系,坐标系"),
            ("第一章 运动的描述", "2. 时间 位移", ["physics.motion_basic"], "时刻,时间间隔,位移,路程"),
            ("第一章 运动的描述", "3. 位置变化快慢的描述——速度", ["physics.motion_basic"], "平均速度,瞬时速度"),
            ("第一章 运动的描述", "4. 速度变化快慢的描述——加速度", ["physics.motion_basic"], "加速度,方向,图像"),
            ("第二章 匀变速直线运动的研究", "1. 实验：探究小车速度随时间变化的规律", ["physics.motion_basic"], "打点计时器,纸带"),
            ("第二章 匀变速直线运动的研究", "2. 匀变速直线运动的速度与时间的关系", ["physics.motion_basic"], "v-t 图像,公式"),
            ("第二章 匀变速直线运动的研究", "3. 匀变速直线运动的位移与时间的关系", ["physics.motion_basic"], "位移公式,推论"),
            ("第二章 匀变速直线运动的研究", "4. 自由落体运动", ["physics.motion_basic"], "自由落体,重力加速度"),
            ("第三章 相互作用——力", "1. 重力与弹力", ["physics.force_composition"], "重力,弹力,胡克定律"),
            ("第三章 相互作用——力", "2. 摩擦力", ["physics.force_composition"], "静摩擦,滑动摩擦"),
            ("第三章 相互作用——力", "3. 牛顿第三定律", ["physics.newton_law"], "作用力与反作用力"),
            ("第三章 相互作用——力", "4. 力的合成和分解", ["physics.force_composition"], "平行四边形,正交分解"),
            ("第三章 相互作用——力", "5. 共点力的平衡", ["physics.force_composition"], "平衡条件,受力分析"),
            ("第四章 运动和力的关系", "1. 牛顿第一定律", ["physics.newton_law"], "惯性,力与运动"),
            ("第四章 运动和力的关系", "3. 牛顿第二定律", ["physics.newton_law"], "F=ma,单位制"),
            ("第四章 运动和力的关系", "5. 牛顿运动定律的应用", ["physics.newton_law"], "两类基本问题"),
            ("第四章 运动和力的关系", "6. 超重和失重", ["physics.newton_law"], "超重,失重,完全失重"),
        ],
    ),
    # ==================== 人教版 物理 必修第二册 ====================
    "rj_phy_bx2": (
        "人教版 高中物理 必修第二册", "physics", "senior", "senior_1", "必修第二册", "人教版", [
            ("第五章 抛体运动", "1. 曲线运动", ["physics.projectile"], "曲线运动,条件,速度方向"),
            ("第五章 抛体运动", "2. 运动的合成与分解", ["physics.projectile", "math.vector"], "合运动,分运动"),
            ("第五章 抛体运动", "3. 实验：探究平抛运动的特点", ["physics.projectile"], "平抛,频闪"),
            ("第五章 抛体运动", "4. 抛体运动的规律", ["physics.projectile", "math.quadratic_function"], "平抛,斜抛,轨迹方程"),
            ("第六章 圆周运动", "1. 圆周运动", ["physics.motion_basic"], "线速度,角速度,周期"),
            ("第六章 圆周运动", "3. 向心加速度", ["physics.motion_basic"], "向心加速度,方向"),
            ("第六章 圆周运动", "4. 生活中的圆周运动", ["physics.newton_law"], "向心力,临界问题"),
            ("第七章 万有引力与宇宙航行", "2. 万有引力定律", ["physics.motion_basic"], "万有引力,常量"),
            ("第八章 机械能守恒定律", "1. 功与功率", ["physics.work_energy"], "功,正负功,功率"),
            ("第八章 机械能守恒定律", "3. 动能和动能定理", ["physics.work_energy"], "动能定理"),
            ("第八章 机械能守恒定律", "4. 机械能守恒定律", ["physics.work_energy"], "机械能,守恒条件"),
        ],
    ),
    # ==================== 人教版 物理 必修第三册 ====================
    "rj_phy_bx3": (
        "人教版 高中物理 必修第三册", "physics", "senior", "senior_2", "必修第三册", "人教版", [
            ("第九章 静电场及其应用", "1. 电荷", ["physics.electric_field"], "电荷,守恒,元电荷"),
            ("第九章 静电场及其应用", "2. 库仑定律", ["physics.electric_field"], "库仑力,点电荷"),
            ("第九章 静电场及其应用", "3. 电场 电场强度", ["physics.electric_field"], "电场强度,电场线"),
            ("第十章 静电场中的能量", "1. 电势能和电势", ["physics.electric_field"], "电势,等势面"),
            ("第十章 静电场中的能量", "3. 电势差与电场强度的关系", ["physics.electric_field"], "U=Ed"),
            ("第十一章 电路及其应用", "1. 电源和电流", ["physics.circuit"], "电流,电源"),
            ("第十一章 电路及其应用", "2. 导体的电阻", ["physics.ohm_law", "physics.circuit"], "电阻定律,电阻率"),
            ("第十一章 电路及其应用", "3. 实验：导体电阻率的测量", ["physics.ohm_law"], "伏安法,内接外接"),
            ("第十二章 电能 能量守恒定律", "1. 电路中的能量转化", ["physics.circuit"], "电功,电功率,焦耳定律"),
            ("第十二章 电能 能量守恒定律", "2. 闭合电路的欧姆定律", ["physics.ohm_law", "physics.circuit"], "电动势,内阻,路端电压"),
        ],
    ),
}


def load_textbook_seeds() -> None:
    with session_scope() as db:
        existing = {
            t.code for t in db.scalars(select(Textbook).where(Textbook.bundled == True))  # noqa: E712
        }
        all_tb = {t.code: t for t in db.scalars(select(Textbook)).all()}
        for code, (title, subj, stage, grade, volume, publisher, sections) in BUNDLED.items():
            if code in existing:
                # 老库里已有：补齐版本字段
                old = all_tb.get(code)
                if old and not old.edition_code:
                    ec, en, ey = BUNDLED_EDITION.get(code, ("", publisher, 2019))
                    old.edition_code, old.edition_name, old.edition_year = ec, en, ey
                continue
            ed_code, ed_name, ed_year = BUNDLED_EDITION.get(code, ("", publisher, 2019))
            tb = Textbook(
                user_id=None, code=code, title=title, subject_key=subj,
                stage=stage, grade=grade, volume=volume, publisher=publisher,
                edition_code=ed_code, edition_name=ed_name, edition_year=ed_year,
                year=2019, bundled=True, parse_status="outline",
                parse_note=f"内置公开目录（{ed_name} {ed_year} 年版结构，无正文）",
            )
            db.add(tb)
            db.flush()
            for i, (chapter, section, kps, kw) in enumerate(sections):
                db.add(
                    TextbookSection(
                        textbook_id=tb.id, chapter=chapter, section=section,
                        order_index=i,
                        kp_codes=__import__("json").dumps(kps, ensure_ascii=False),
                        keywords=kw, char_count=0,
                    )
                )
