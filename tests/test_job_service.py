import asyncio
from pathlib import Path

from app.job_service import JobService


def test_demo_job_pauses_for_human_review_and_completes(tmp_path: Path) -> None:
    service = JobService(tmp_path)
    job = service.create_demo_job(target_language="zh-CN")

    asyncio.run(service.run_until_review(job.id))
    reviewed = service.get_job(job.id)

    assert reviewed.status == "awaiting_approval"
    assert reviewed.progress >= 0.8
    assert any(step.tool == "translate_segments" for step in reviewed.steps)
    assert any(step.tool == "validate_subtitles" for step in reviewed.steps)
    assert Path(reviewed.translated_srt_path).exists()

    completed = service.approve(job.id)

    assert completed.status == "completed"
    assert Path(completed.output_srt_path).exists()
    assert "每一段故事" in Path(completed.output_srt_path).read_text(encoding="utf-8")
    checkpoint = next(step for step in completed.steps if step.tool == "human_checkpoint")
    assert checkpoint.status == "succeeded"
