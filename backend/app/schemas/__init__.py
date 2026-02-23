from datetime import datetime

from pydantic import BaseModel, Field


# --- Task Schemas ---

class TaskCreate(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    platform: str = Field(default="bilibili", description="Video platform")
    max_videos: int = Field(default=10, ge=1, le=50, description="Max videos to analyze")


class TaskResponse(BaseModel):
    id: int
    query: str
    platform: str
    max_videos: int
    status: str
    progress: float
    error_message: str | None = None
    completed_step: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


# --- Video Schemas ---

class VideoResponse(BaseModel):
    id: int
    platform: str
    video_id: str
    title: str
    author: str
    url: str
    duration: int
    cover_url: str
    summary: str | None = None

    model_config = {"from_attributes": True}


# --- Report Schemas ---

class ReportResponse(BaseModel):
    id: int
    task_id: int
    content_markdown: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Agent Event Schemas ---

class AgentEventResponse(BaseModel):
    id: int
    event_type: str
    content: str
    tool_name: str | None = None
    tool_args_json: str | None = None
    tool_result_preview: str | None = None
    timestamp: float

    model_config = {"from_attributes": True}
