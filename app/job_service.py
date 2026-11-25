from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from app.agent import ToolRunner, ToolSpec
from app.media import create_demo_video, extract_audio, probe_video, render_subtitled_video
from app.models import AppConfig, Job, Step
from app.providers import (
    DemoTranslationProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
    create_translation_provider,
)
from app.srt import SubtitleCue, parse_srt, to_srt, validate_cues
from app.storage import JobRepository


DEMO_SRT = """1
00:00:00,000 --> 00:00:02,000
Every great story begins with a single frame.

2
00:00:02,000 --> 00:00:04,400
Localization keeps timing, tone, and context intact.

3
00:00:04,500 --> 00:00:07,000
This agent plans, verifies, and retries before delivery.
"""


class JobService:
    def __init__(
        self,
        root: Path,
        provider_config: ProviderConfig | None = None,
        max_upload_mb: int = 80,
        max_agent_steps: int = 8,
    ) -> None:
        self.root = root
        self.artifacts_root = root / "artifacts"
        self.uploads_root = root / "uploads"
        self.demo_root = root / "demo"
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.uploads_root.mkdir(parents=True, exist_ok=True)
        self.demo_root.mkdir(parents=True, exist_ok=True)
        self.provider_config = provider_config or ProviderConfig.from_env()
        self.max_upload_mb = max_upload_mb
        self.max_agent_steps = max_agent_steps
        self.repository = JobRepository(root / "jobs.db")
        self.tool_runner = ToolRunner(max_retries=1)

    def config(self) -> AppConfig:
        return AppConfig(
            demo_mode_available=True,
            live_model_configured=self.provider_config.llm_configured,
            asr_configured=self.provider_config.asr_configured,
            ffmpeg_available=bool(probe_video),
            max_upload_mb=self.max_upload_mb,
            max_agent_steps=self.max_agent_steps,
        )

    def _job_dir(self, job_id: str) -> Path:
        path = self.artifacts_root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_demo_assets(self) -> tuple[Path, Path]:
        video_path = self.demo_root / "demo.mp4"
        if not video_path.exists():
            create_demo_video(video_path)
        subtitle_path = self.demo_root / "source.srt"
        if not subtitle_path.exists():
            subtitle_path.write_text(DEMO_SRT, encoding="utf-8")
        return video_path, subtitle_path

    def create_demo_job(self, target_language: str = "zh-CN") -> Job:
        video_path, subtitle_path = self._ensure_demo_assets()
        job = Job(
            id=uuid.uuid4().hex,
            status="queued",
            mode="demo",
            source_language="en",
            target_language=target_language,
            source_name="Demo / verifier in the loop",
            video_path=str(video_path),
            source_srt_path=str(subtitle_path),
        )
        return self.repository.create_job(job)

    def create_upload_job(
        self,
        video_path: Path,
        source_name: str,
        source_language: str,
        target_language: str,
        subtitle_path: Path | None = None,
        mode: str = "live",
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex,
            status="queued",
            mode="demo" if mode == "demo" else "live",
            source_language=source_language,
            target_language=target_language,
            source_name=source_name,
            video_path=str(video_path),
            source_srt_path=str(subtitle_path) if subtitle_path else None,
        )
        return self.repository.create_job(job)

    def get_job(self, job_id: str) -> Job:
        return self.repository.get_job(job_id)

    def list_recent(self, limit: int = 10):
        return self.repository.list_recent(limit=limit)

    def _save_job_dir(self, job_id: str) -> Path:
        return self._job_dir(job_id)

    async def _execute_tool(
        self,
        job: Job,
        sequence: int,
        spec: ToolSpec,
        *args,
        **kwargs,
    ):
        started = time.perf_counter()
        result, attempts = await self.tool_runner.run(spec, *args, **kwargs)
        duration_ms = round((time.perf_counter() - started) * 1000)
        retry_count = max(0, len(attempts) - 1)
        status = "succeeded" if attempts[-1]["status"] == "succeeded" else "failed"
        detail = attempts[-1]["detail"]
        if retry_count:
            detail = f"Retried {retry_count} time(s). {detail}"
        step = Step(
            sequence=sequence,
            tool=spec.name,
            label=spec.label,
            status=status,
            detail=detail,
            duration_ms=duration_ms,
            payload={"attempts": attempts},
        )
        self.repository.append_step(job.id, step)
        if retry_count:
            current = self.repository.get_job(job.id)
            self.repository.update_job(
                job.id,
                retry_count=current.retry_count + retry_count,
            )
        if job.mode == "demo":
            await asyncio.sleep(0.16)
        return result

    def _prepare_cues(self, job: Job) -> list[SubtitleCue]:
        if job.source_srt_path:
            return parse_srt(Path(job.source_srt_path).read_text(encoding="utf-8"))
        raise ValueError("No source subtitle supplied")

    async def run_until_review(self, job_id: str) -> Job:
        job = self.repository.get_job(job_id)
        self.repository.update_job(job.id, status="running", progress=0.04, error=None)
        try:
            media_info: dict = {}
            if job.video_path:
                media_info = await self._execute_tool(
                    job,
                    1,
                    ToolSpec(
                        name="inspect_video",
                        label="Inspect source media",
                        handler=probe_video,
                    ),
                    Path(job.video_path),
                )
            self.repository.update_job(
                job.id,
                progress=0.2,
                metrics={"media": media_info},
            )

            async def prepare_transcript() -> list[SubtitleCue]:
                if job.source_srt_path:
                    cues = self._prepare_cues(job)
                    return cues
                if not job.video_path:
                    raise ValueError("Upload a subtitle file or a video with ASR configured")
                audio_path = self._job_dir(job.id) / "source.wav"
                extract_audio(Path(job.video_path), audio_path)
                if not self.provider_config.asr_configured:
                    raise ValueError(
                        "Upload an SRT file or set ASR_BASE_URL, ASR_API_KEY, and ASR_MODEL"
                    )
                provider = OpenAICompatibleProvider(self.provider_config)
                return parse_srt(await provider.transcribe(audio_path))

            cues = await self._execute_tool(
                job,
                2,
                ToolSpec(
                    name="prepare_transcript",
                    label="Prepare timed transcript",
                    handler=prepare_transcript,
                ),
            )
            self.repository.update_job(job.id, progress=0.38)

            provider = create_translation_provider(self.provider_config, job.mode)
            async def translate() -> list[SubtitleCue]:
                return await provider.translate(
                    cues,
                    job.source_language,
                    job.target_language,
                )

            translated = await self._execute_tool(
                job,
                3,
                ToolSpec(
                    name="translate_segments",
                    label="Translate timed segments",
                    handler=translate,
                ),
            )
            self.repository.update_job(job.id, progress=0.58)

            issues = await self._execute_tool(
                job,
                4,
                ToolSpec(
                    name="validate_subtitles",
                    label="Validate subtitle constraints",
                    handler=lambda: validate_cues(translated, max_chars=24),
                ),
            )
            self.repository.update_job(job.id, progress=0.7)

            repaired = translated
            if any(issue.code == "CUE_TOO_LONG" for issue in issues):
                async def repair() -> list[SubtitleCue]:
                    return _split_long_cues(translated, max_chars=24)

                repaired = await self._execute_tool(
                    job,
                    5,
                    ToolSpec(
                        name="repair_subtitles",
                        label="Split overlong subtitles",
                        handler=repair,
                    ),
                )
                self.repository.update_job(job.id, progress=0.82)
            else:
                self.repository.update_job(job.id, progress=0.82)

            review_path = self._save_job_dir(job.id) / "review.srt"
            review_path.write_text(to_srt(repaired), encoding="utf-8")
            self.repository.append_step(
                job.id,
                Step(
                    sequence=6,
                    tool="human_checkpoint",
                    label="Review translated subtitles",
                    status="waiting",
                    detail="Approve the translation to render final artifacts.",
                    payload={"issues": [asdict(issue) for issue in issues]},
                ),
            )
            self.repository.update_job(
                job.id,
                status="awaiting_approval",
                progress=0.86,
                translated_srt_path=str(review_path),
                metrics={
                    "media": media_info,
                    "segments": len(repaired),
                    "issues": len(issues),
                    "source_segments": len(cues),
                    "agent_steps": 6,
                },
            )
            return self.repository.get_job(job.id)
        except Exception as exc:
            self.repository.append_step(
                job.id,
                Step(
                    sequence=99,
                    tool="fail_job",
                    label="Agent stopped",
                    status="failed",
                    detail=str(exc),
                ),
            )
            self.repository.update_job(
                job.id,
                status="failed",
                error=str(exc),
                progress=1.0,
            )
            return self.repository.get_job(job.id)

    def approve(self, job_id: str) -> Job:
        job = self.repository.get_job(job_id)
        if job.status != "awaiting_approval" or not job.translated_srt_path:
            raise ValueError("Job is not awaiting subtitle review")

        self.repository.update_job(job.id, status="rendering", progress=0.9, error=None)
        self.repository.update_step(
            job.id,
            6,
            status="succeeded",
            detail="Human approved the translated subtitles.",
        )
        started = time.perf_counter()
        artifact_dir = self._save_job_dir(job.id)
        output_srt = artifact_dir / f"localized.{job.target_language}.srt"
        shutil.copyfile(job.translated_srt_path, output_srt)
        output_video_path: Path | None = None
        if job.video_path:
            candidate = artifact_dir / "localized.mp4"
            try:
                output_video_path = render_subtitled_video(
                    Path(job.video_path),
                    output_srt,
                    candidate,
                )
            except Exception:
                output_video_path = None

        duration_ms = round((time.perf_counter() - started) * 1000)
        self.repository.append_step(
            job.id,
            Step(
                sequence=7,
                tool="render_outputs",
                label="Render approved outputs",
                status="succeeded",
                detail="Final subtitle and video artifacts were written.",
                duration_ms=duration_ms,
                payload={
                    "subtitle": output_srt.name,
                    "video": output_video_path.name if output_video_path else None,
                },
            ),
        )
        trace_path = artifact_dir / "agent_trace.json"
        current = self.repository.get_job(job.id)
        trace_path.write_text(
            json.dumps(current.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.repository.update_job(
            job.id,
            status="completed",
            progress=1.0,
            output_srt_path=str(output_srt),
            output_video_path=str(output_video_path) if output_video_path else None,
            metrics={
                **job.metrics,
                "render_ms": duration_ms,
                "completed_steps": len(current.steps) + 1,
            },
        )


def _split_long_cues(cues: list[SubtitleCue], max_chars: int) -> list[SubtitleCue]:
    result: list[SubtitleCue] = []
    for cue in cues:
        text = cue.text.strip()
        if len(text) <= max_chars:
            result.append(cue)
            continue

        split_at = _best_split(text, max_chars)
        left = text[:split_at].strip(" ，,")
        right = text[split_at:].strip(" ，,")
        if not left or not right:
            result.append(cue)
            continue

        midpoint = cue.start_ms + (cue.end_ms - cue.start_ms) // 2
        result.append(SubtitleCue(0, cue.start_ms, midpoint, left))
        result.append(SubtitleCue(0, midpoint, cue.end_ms, right))

    return [
        SubtitleCue(index, cue.start_ms, cue.end_ms, cue.text)
        for index, cue in enumerate(result, start=1)
    ]


def _best_split(text: str, max_chars: int) -> int:
    punctuation = [match.end() for match in re.finditer(r"[，。；：！？,.;:!?]", text)]
    valid = [point for point in punctuation if 0 < point <= max_chars + 4]
    if valid:
        return min(valid, key=lambda point: abs(point - len(text) / 2))
    return min(max_chars, max(1, len(text) // 2))
