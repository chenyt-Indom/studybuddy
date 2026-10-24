"""大模型供应商抽象（方案 4.2）。

为什么抽象：将来要加备用模型（星辰某个模型限流时切换），业务代码一行不改。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(self, messages: list[dict], **kw) -> str:
        """非流式，返回完整文本。"""

    @abstractmethod
    def stream(self, messages: list[dict], **kw) -> AsyncIterator[str]:
        """流式，逐段 yield 文本增量。"""

    async def list_models(self) -> list[str]:
        return []

    async def health(self) -> dict:
        return {"ok": False, "message": "not implemented"}
