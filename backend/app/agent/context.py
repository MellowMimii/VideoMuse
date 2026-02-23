"""Agent context — shared state for the agent loop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from app.platforms.base import VideoInfo


class AgentCancelledError(Exception):
    """Raised when the agent task is cancelled by the user."""


@dataclass
class AgentContext:
    """Shared state for the agent loop.

    Replaces PipelineContext with a more flexible structure
    suited for autonomous agent execution.
    """

    # Task parameters
    query: str
    platform: str = "bilibili"
    max_videos: int = 10
    task_id: int | None = None

    # System prompt (filled in by task_service)
    system_prompt: str = ""

    # Video data store: video_id -> dict with keys:
    #   "info": VideoInfo, "transcript": str, "summary": str
    video_data: dict[str, dict] = field(default_factory=dict)

    # All search results (for reference)
    search_results: list[VideoInfo] = field(default_factory=list)

    # Final report
    report_markdown: str = ""
    report_json: dict = field(default_factory=dict)

    # Agent event log (for frontend display)
    events: list[Any] = field(default_factory=list)

    # Progress tracking
    progress: float = 0.0

    # Cancellation
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    # Callbacks
    _progress_callback: Callable[..., Coroutine] | None = None
    _event_callback: Callable[..., Coroutine] | None = None

    def cancel(self):
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def check_cancelled(self):
        if self.is_cancelled:
            raise AgentCancelledError("Task was cancelled by user")

    async def set_progress(self, progress: float):
        self.progress = progress
        if self._progress_callback:
            await self._progress_callback(self.task_id, progress)

    async def add_event(self, event: Any):
        """Record an agent event and persist it."""
        self.events.append(event)
        if self._event_callback:
            await self._event_callback(self.task_id, event)

    def get_video_info(self, video_id: str) -> VideoInfo | None:
        """Look up a video by ID from video_data or search_results."""
        data = self.video_data.get(video_id)
        if data and data.get("info"):
            return data["info"]
        for vi in self.search_results:
            if vi.video_id == video_id:
                return vi
        return None
