from __future__ import annotations

from dataclasses import dataclass, field

from app.platforms.base import VideoInfo


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

    # Callback for progress updates
    _progress_callback: callable | None = None

    def set_progress(self, progress: float, step: str = ""):
        self.progress = progress
        if step:
            self.current_step = step
        if self._progress_callback:
            self._progress_callback(self.task_id, progress, step)
