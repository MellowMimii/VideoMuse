from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Coroutine, Any

from app.platforms.base import VideoInfo


class PipelineCancelledError(Exception):
    """Raised when a pipeline is cancelled by the user."""


@dataclass
class VideoResult:
    """Holds extracted content and summary for a single video."""

    info: VideoInfo
    transcript: str = ""
    summary: str = ""
    extraction_method: str = ""  # "subtitle" or "whisper"


@dataclass
class PipelineContext:
    """Shared state passed through all pipeline steps."""

    query: str
    platform: str = "bilibili"
    max_videos: int = 10
    task_id: int | None = None

    # Populated by SearchStep
    videos: list[VideoInfo] = field(default_factory=list)

    # Populated by ExtractStep
    video_results: list[VideoResult] = field(default_factory=list)

    # Populated by ConsolidateStep
    consolidated_summary: str = ""

    # Populated by ReportStep
    report_markdown: str = ""
    report_json: dict = field(default_factory=dict)

    # Progress tracking
    progress: float = 0.0
    current_step: str = ""
    total_steps: int = 5  # total pipeline steps

    # Cancellation support
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    # Callback for progress updates
    _progress_callback: Callable[..., Coroutine[Any, Any, None]] | None = None

    # Callback for persisting intermediate results after each step
    _step_complete_callback: Callable[..., Coroutine[Any, Any, None]] | None = None

    # Resume support: name of last completed step (skip steps up to this one)
    resume_after_step: str | None = None

    def cancel(self):
        """Signal the pipeline to cancel."""
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def check_cancelled(self):
        """Raise PipelineCancelledError if cancelled."""
        if self.is_cancelled:
            raise PipelineCancelledError("Pipeline was cancelled by user")

    async def set_progress(self, progress: float, step: str = ""):
        self.progress = progress
        if step:
            self.current_step = step
        if self._progress_callback:
            await self._progress_callback(self.task_id, progress, step)

    def get_step_progress(self, step_index: int, sub_progress: float = 0.0) -> float:
        """Calculate overall progress including sub-step progress.

        Args:
            step_index: 0-based index of current step
            sub_progress: progress within this step (0.0 to 1.0)
        """
        step_size = 100.0 / self.total_steps
        return step_index * step_size + sub_progress * step_size
