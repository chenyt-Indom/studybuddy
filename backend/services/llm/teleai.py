"""向后兼容垫片。

实现已合并到 `openai_compat.py`（DeepSeek 与星辰共用一套 OpenAI 兼容逻辑）。
新代码请直接从 `backend.services.llm.openai_compat` 或 `backend.services.llm` 导入。
"""
from .openai_compat import (  # noqa: F401
    DeepSeekProvider,
    MockProvider,
    OpenAICompatProvider,
    TeleAIProvider,
    get_provider,
)
