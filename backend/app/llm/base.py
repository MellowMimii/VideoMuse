from __future__ import annotations

from abc import ABC, abstractmethod


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
