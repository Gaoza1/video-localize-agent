from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from app.job_service import JobService
from app.models import Job


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


class DemoJobRequest(BaseModel):
    target_language: str = Field(default="zh-CN", pattern=r"^[A-Za-z-]{2,12}$")


def _safe_upload_name(filename: str | None, fallback: str) -> str:
    name = Path(filename or fallback).name.strip()
    return name or fallback


def create_app(
    data_root: Path | None = None,
    auto_start_jobs: bool = True,
) -> FastAPI:
    root = data_root or Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
    app = FastAPI(
        title="VideoLocalize Agent",
        description="A verifier-in-the-loop subtitle localization agent.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    service = JobService(root)
    app.state.job_service = service
    background_tasks: set[asyncio.Task] = set()

    def start_job(job: Job) -> Job:
        if not auto_start_jobs:
            return job
        task = asyncio.create_task(service.run_until_review(job.id))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return job

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return service.config()

    @app.post("/api/jobs/demo", status_code=201)
    async def create_demo_job(payload: DemoJobRequest):
        job = service.create_demo_job(target_language=payload.target_language)
        return start_job(job)

    @app.post("/api/jobs", status_code=201)
    async def create_upload_job(
        video: UploadFile = File(...),
        subtitle: UploadFile | None = File(default=None),
        source_language: str = Form(default="en"),
        target_language: str = Form(default="zh-CN"),
        mode: str = Form(default="live"),
    ):
        upload_id = uuid.uuid4().hex
        upload_dir = service.uploads_root / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        video_name = _safe_upload_name(video.filename, "upload.mp4")
        video_path = upload_dir / video_name
        max_bytes = service.max_upload_mb * 1024 * 1024
        total = 0
        with video_path.open("wb") as destination:
            while chunk := await video.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    destination.close()
                    video_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Video exceeds {service.max_upload_mb} MB",
                    )
                destination.write(chunk)

        subtitle_path: Path | None = None
        if subtitle and subtitle.filename:
            subtitle_name = _safe_upload_name(subtitle.filename, "source.srt")
            subtitle_path = upload_dir / subtitle_name
            subtitle_bytes = await subtitle.read(2 * 1024 * 1024)
            if len(subtitle_bytes) > 2 * 1024 * 1024:
                video_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Subtitle exceeds 2 MB")
            subtitle_path.write_bytes(subtitle_bytes)

        job = service.create_upload_job(
            video_path=video_path,
            source_name=video_name,
            source_language=source_language,
            target_language=target_language,
            subtitle_path=subtitle_path,
            mode=mode,
        )
        return start_job(job)

    @app.get("/api/jobs")
    def list_jobs(limit: int = 10):
        return service.list_recent(limit=max(1, min(limit, 50)))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return service.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.post("/api/jobs/{job_id}/approve")
    def approve_job(job_id: str):
        try:
            return service.approve(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/artifacts/{filename}")
    def get_artifact(job_id: str, filename: str):
        job_dir = (service.artifacts_root / job_id).resolve()
        requested = (job_dir / Path(filename).name).resolve()
        if requested.parent != job_dir or not requested.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found")
        return FileResponse(requested, filename=requested.name)

    frontend_dir = PROJECT_ROOT / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


app = create_app()
