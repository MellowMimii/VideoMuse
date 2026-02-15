from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """LLM provider for any OpenAI-compatible API.

    Works with: OpenAI, DeepSeek, Zhipu GLM, Qwen (DashScope),
    AiHubMix, and other compatible endpoints.
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    async def chat(self, messages: list[dict], **kwargs) -> str:
        temperature = kwargs.pop("temperature", 0.7)
        max_tokens = kwargs.pop("max_tokens", 4096)

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        content = response.choices[0].message.content or ""
        logger.debug("LLM response (%d tokens): %s...", len(content), content[:100])
        return content

    async def chat_json(self, messages: list[dict], **kwargs) -> dict:
        """Request JSON output and parse it."""
        # Add JSON instruction to system message if not present
        if messages and messages[0]["role"] == "system":
            if "JSON" not in messages[0]["content"]:
                messages[0]["content"] += "\n\nYou must respond with valid JSON only."
        else:
            messages.insert(0, {
                "role": "system",
                "content": "You must respond with valid JSON only.",
            })

        text = await self.chat(messages, **kwargs)

        # Try to extract JSON from response (handles markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            # Remove markdown code block wrapper
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        return json.loads(text)
