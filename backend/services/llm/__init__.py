"""大模型适配层。"""
from .base import LLMProvider  # noqa: F401
from .openai_compat import (  # noqa: F401
    DeepSeekProvider,
    MockProvider,
    OpenAICompatProvider,
    TeleAIProvider,
    get_provider,
)
