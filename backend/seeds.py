"""预置数据装载：知识点总库 + 前置依赖 + 跨学科联动。

数据本体在 `seeds_kp.py`（140 个知识点，按 学段/年级/科目/模块 组织），
这里只负责**幂等入库**：
  · 已有知识点 → 刷新内容字段（课标/话术改了要能生效），不动 code
  · 没有的 → 插入
  · 依赖与跨科关联 → 按 (a,b) 去重，重复启动不会翻倍

为什么要 upsert 而不是"有数据就跳过"：
老版本库里只有 41 个知识点、没有年级和要点。跳过就永远补不上新字段，
而全删重建会把错题/复习状态里引用的 kp_code 一起弄丢。
"""
from __future__ import annotations

from sqlalchemy import select

from .db import session_scope
from .models import CrossSubjectLink, KnowledgePoint, KpDependency
from .seeds_kp import CROSS_LINKS, KP_DEPS, KP_ROWS


def load_seeds() -> None:
    from .services.kp import ALIASES  # 延迟导入，避免循环依赖

    with session_scope() as db:
        have = {kp.kp_code: kp for kp in db.scalars(select(KnowledgePoint))}

        for row in KP_ROWS:
            (code, subj, name, stage, grade, module,
             imp, diff, summary, pitfall, mnem) = row
            kp = have.get(code)
            if kp is None:
                kp = KnowledgePoint(kp_code=code, subject_key=subj, name=name, stage=stage)
                db.add(kp)
            kp.subject_key = subj
            kp.name = name
            kp.stage = stage
            kp.grade = grade or "all"
            kp.module = module or ""
            kp.importance = imp
            kp.difficulty = diff
            kp.summary = summary
            kp.pitfall = pitfall
            kp.mnemonic = mnem
            # 口语别名也存一份，给「知识点搜索」用（讲解召回另有 ALIASES 表）
            kp.keywords = ",".join(ALIASES.get(code, [])) or None
        db.flush()

        # ---- 前置依赖 ----
        deps = {(d.kp_code, d.depends_on) for d in db.scalars(select(KpDependency))}
        for child, parent in KP_DEPS:
            if (child, parent) not in deps:
                db.add(KpDependency(kp_code=child, depends_on=parent))

        # ---- 跨学科联动 ----
        links = {
            (l.from_kp, l.to_kp): l for l in db.scalars(select(CrossSubjectLink))
        }
        for a, b, rel, strength, note in CROSS_LINKS:
            old = links.get((a, b))
            if old is None:
                db.add(
                    CrossSubjectLink(
                        from_kp=a, to_kp=b, relation_type=rel,
                        strength=strength, note=note,
                    )
                )
            else:
                # 话术会迭代（"怎么借力"比"它们有关"重要），所以要覆盖
                old.relation_type, old.strength, old.note = rel, strength, note
