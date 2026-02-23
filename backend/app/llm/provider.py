from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI

from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds


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
            timeout=120.0,
        )

    async def chat(self, messages: list[dict], **kwargs) -> str:
        temperature = kwargs.pop("temperature", 0.7)
        max_tokens = kwargs.pop("max_tokens", 4096)

        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                content = response.choices[0].message.content or ""
                logger.debug("LLM response (%d chars): %s...", len(content), content[:100])
                return content
            except Exception as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %ds...",
                        attempt, MAX_RETRIES, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM call failed after %d attempts: %s", MAX_RETRIES, e)

        raise last_exc

    async def chat_json(self, messages: list[dict], **kwargs) -> dict:
        """Request JSON output and parse it."""
        if messages and messages[0]["role"] == "system":
            if "JSON" not in messages[0]["content"]:
                messages[0]["content"] += "\n\nYou must respond with valid JSON only."
        else:
            messages.insert(0, {
                "role": "system",
                "content": "You must respond with valid JSON only.",
            })

        text = await self.chat(messages, **kwargs)

        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        return json.loads(text)

    async def chat_with_tools(self, messages: list[dict], tools: list[dict], **kwargs):
        """Send a chat completion with tool definitions. Returns the raw response."""
        temperature = kwargs.pop("temperature", 0.3)
        max_tokens = kwargs.pop("max_tokens", 4096)
        tool_choice = kwargs.pop("tool_choice", "auto")

        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                return response
            except Exception as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM tool call failed (attempt %d/%d): %s. Retrying in %ds...",
                        attempt, MAX_RETRIES, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "LLM tool call failed after %d attempts: %s",
                        MAX_RETRIES, e,
                    )

        raise last_exc
