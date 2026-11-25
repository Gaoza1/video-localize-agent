from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "rendering",
    "completed",
    "failed",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Step(BaseModel):
    id: int | None = None
    sequence: int
    tool: str
    label: str
    status: Literal["running", "succeeded", "failed", "waiting"]
    detail: str = ""
    duration_ms: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    id: str
    status: JobStatus = "queued"
    mode: Literal["demo", "live"] = "demo"
    source_language: str = "en"
    target_language: str = "zh-CN"
    source_name: str = "Demo clip"
    video_path: str | None = None
    source_srt_path: str | None = None
    translated_srt_path: str | None = None
    output_srt_path: str | None = None
    output_video_path: str | None = None
    progress: float = 0.0
    retry_count: int = 0
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    metrics: dict[str, Any] = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)


class JobSummary(BaseModel):
    id: str
    status: JobStatus
    mode: str
    source_name: str
    target_language: str
    progress: float
    created_at: str
    updated_at: str


class AppConfig(BaseModel):
    demo_mode_available: bool
    live_model_configured: bool
    asr_configured: bool
    ffmpeg_available: bool
    max_upload_mb: int
    max_agent_steps: int
