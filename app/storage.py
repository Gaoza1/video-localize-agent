from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.models import Job, JobSummary, Step, utc_now


class JobRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    video_path TEXT,
                    source_srt_path TEXT,
                    translated_srt_path TEXT,
                    output_srt_path TEXT,
                    output_video_path TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    tool TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_steps_job_sequence
                ON steps(job_id, sequence);
                """
            )

    def create_job(self, job: Job) -> Job:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, mode, source_language, target_language, source_name,
                    video_path, source_srt_path, translated_srt_path, output_srt_path,
                    output_video_path, progress, retry_count, error, created_at,
                    updated_at, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.status,
                    job.mode,
                    job.source_language,
                    job.target_language,
                    job.source_name,
                    job.video_path,
                    job.source_srt_path,
                    job.translated_srt_path,
                    job.output_srt_path,
                    job.output_video_path,
                    job.progress,
                    job.retry_count,
                    job.error,
                    job.created_at,
                    job.updated_at,
                    json.dumps(job.metrics, ensure_ascii=False),
                ),
            )
        return job

    def get_job(self, job_id: str) -> Job:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            step_rows = connection.execute(
                "SELECT * FROM steps WHERE job_id = ? ORDER BY sequence, id",
                (job_id,),
            ).fetchall()

        steps = [
            Step(
                id=step_row["id"],
                sequence=step_row["sequence"],
                tool=step_row["tool"],
                label=step_row["label"],
                status=step_row["status"],
                detail=step_row["detail"],
                duration_ms=step_row["duration_ms"],
                payload=json.loads(step_row["payload_json"]),
            )
            for step_row in step_rows
        ]
        return Job(
            id=row["id"],
            status=row["status"],
            mode=row["mode"],
            source_language=row["source_language"],
            target_language=row["target_language"],
            source_name=row["source_name"],
            video_path=row["video_path"],
            source_srt_path=row["source_srt_path"],
            translated_srt_path=row["translated_srt_path"],
            output_srt_path=row["output_srt_path"],
            output_video_path=row["output_video_path"],
            progress=row["progress"],
            retry_count=row["retry_count"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metrics=json.loads(row["metrics_json"]),
            steps=steps,
        )

    def update_job(self, job_id: str, **fields: Any) -> Job:
        if not fields:
            return self.get_job(job_id)
        allowed = {
            "status",
            "video_path",
            "source_srt_path",
            "translated_srt_path",
            "output_srt_path",
            "output_video_path",
            "progress",
            "retry_count",
            "error",
            "metrics",
        }
        if unknown := set(fields) - allowed:
            raise ValueError(f"Unsupported job fields: {sorted(unknown)}")

        values: list[Any] = []
        assignments: list[str] = []
        for key, value in fields.items():
            if key == "metrics":
                assignments.append("metrics_json = ?")
                values.append(json.dumps(value, ensure_ascii=False))
            else:
                assignments.append(f"{key} = ?")
                values.append(value)
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.append(job_id)

        with self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get_job(job_id)

    def append_step(self, job_id: str, step: Step) -> Step:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO steps (
                    job_id, sequence, tool, label, status, detail,
                    duration_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    step.sequence,
                    step.tool,
                    step.label,
                    step.status,
                    step.detail,
                    step.duration_ms,
                    json.dumps(step.payload, ensure_ascii=False),
                ),
            )
            step_id = int(cursor.lastrowid)
        return step.model_copy(update={"id": step_id})

    def update_step(
        self,
        job_id: str,
        sequence: int,
        *,
        status: str,
        detail: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE steps
                SET status = ?, detail = ?
                WHERE job_id = ? AND sequence = ?
                """,
                (status, detail, job_id, sequence),
            )

    def list_recent(self, limit: int = 10) -> list[JobSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, status, mode, source_name, target_language, progress,
                       created_at, updated_at
                FROM jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [JobSummary(**dict(row)) for row in rows]
