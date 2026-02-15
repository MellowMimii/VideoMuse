from app.config import settings
from app.llm.base import LLMProvider
from app.llm.provider import OpenAICompatibleProvider


def get_llm_provider() -> LLMProvider:
    """Factory function to create an LLM provider from config."""
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )


__all__ = ["LLMProvider", "get_llm_provider"]
