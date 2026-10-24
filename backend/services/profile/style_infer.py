"""认知风格推断（方案 5.2）。

不能直接问用户「你是什么类型的学习者」——用户答不准。要从行为推断。
"""
from __future__ import annotations

STYLE_INDICATORS = {
    "visual": {
        "keywords": ["画", "图", "示意", "看起来", "直观", "长什么样", "图像"],
        "behaviors": ["对图形解释追问", "要求画图", "用空间词汇"],
    },
    "verbal": {
        "keywords": ["为什么", "原理", "怎么理解", "本质", "解释", "推导过程"],
        "behaviors": ["追问推导", "喜欢文字说明"],
    },
    "kinesthetic": {
        "keywords": ["例子", "实际", "应用", "做一遍", "试试", "上手"],
        "behaviors": ["喜欢动手做", "要求具体案例"],
    },
    "logical": {
        "keywords": ["推导", "证明", "逻辑", "关系", "分类", "体系", "归纳"],
        "behaviors": ["关注体系性", "喜欢归纳"],
    },
}


def detect_behavior(text: str, behaviors: list[str]) -> float:
    """行为特征命中度（0~1）。"""
    if not behaviors:
        return 0.0
    hit = sum(1 for b in behaviors if any(k in text for k in b.split()))
    return hit / len(behaviors)


def infer_style(texts: list[str]) -> dict:
    """从历史对话推断认知风格。返回各风格得分，不返回单一标签。

    人是混合的，只是倾向不同。
    """
    scores = {k: 0.0 for k in STYLE_INDICATORS}
    for text in texts:
        if not text:
            continue
        for style, ind in STYLE_INDICATORS.items():
            for kw in ind["keywords"]:
                if kw in text:
                    scores[style] += 1.0
            scores[style] += detect_behavior(text, ind["behaviors"]) * 1.5

    total = sum(scores.values())
    if total <= 0:
        return {"scores": {k: 0.0 for k in STYLE_INDICATORS}, "primary": None,
                "confidence": 0.0, "samples": 0}

    normalized = {k: round(v / total, 3) for k, v in scores.items()}
    primary = max(normalized, key=normalized.get)
    return {
        "scores": normalized,
        "primary": primary,
        "confidence": normalized[primary],
        "samples": len(texts),
    }


def pick_explain_style(primary_style: str | None) -> str:
    """根据认知风格选择讲解方式（落到 Prompt 上）。"""
    return {
        "visual": "多用图形、示意图、坐标图；先给图再讲公式",
        "verbal": "先讲原理和推导，公式是自然结论；文字要准确",
        "kinesthetic": "用生活实例切入；多给动手做的题",
        "logical": "强调知识体系和逻辑关系；讲清「为什么这样定义」",
    }.get(primary_style or "", "")
