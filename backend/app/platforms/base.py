from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class VideoInfo:
    """Platform-agnostic video metadata."""

    video_id: str
    title: str
    author: str
    url: str
    duration: int = 0  # seconds
    cover_url: str = ""
    platform: str = ""


class PlatformAdapter(ABC):
    """Abstract base class for video platform adapters.

    To add a new platform, subclass this and register with
    @PlatformRegistry.register("platform_name").
    """

    @abstractmethod
    async def search_videos(self, query: str, max_results: int = 10) -> list[VideoInfo]:
        """Search for videos matching the query."""
        ...

    @abstractmethod
    async def get_subtitles(self, video_id: str) -> str | None:
        """Get subtitle/CC text for a video. Returns None if unavailable."""
        ...

    @abstractmethod
    async def get_audio_url(self, video_id: str) -> str | None:
        """Get audio download URL for Whisper fallback. Returns None if unavailable."""
        ...


class PlatformRegistry:
    """Registry for platform adapters. Use as a decorator to register new platforms."""

    _adapters: ClassVar[dict[str, type[PlatformAdapter]]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a platform adapter class."""

        def decorator(adapter_cls: type[PlatformAdapter]):
            cls._adapters[name] = adapter_cls
            return adapter_cls

        return decorator

    @classmethod
    def get(cls, name: str) -> PlatformAdapter:
        """Instantiate and return a registered platform adapter."""
        if name not in cls._adapters:
            available = ", ".join(cls._adapters.keys()) or "(none)"
            raise ValueError(
                f"Unknown platform '{name}'. Available: {available}"
            )
        return cls._adapters[name]()

    @classmethod
    def list_platforms(cls) -> list[str]:
        return list(cls._adapters.keys())
