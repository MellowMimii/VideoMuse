from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> str:
        """Send a chat completion request and return the response text."""
        ...

    @abstractmethod
    async def chat_json(self, messages: list[dict], **kwargs) -> dict:
        """Send a chat completion request and parse the response as JSON."""
        ...

    @abstractmethod
    async def chat_with_tools(
        self, messages: list[dict], tools: list[dict], **kwargs
    ) -> Any:
        """Send a chat completion with tool definitions. Returns the raw response."""
        ...
