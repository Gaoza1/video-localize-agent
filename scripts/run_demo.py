from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.job_service import JobService  # noqa: E402


async def main() -> None:
    service = JobService(PROJECT_ROOT / "data")
    job = service.create_demo_job(target_language="zh-CN")
    reviewed = await service.run_until_review(job.id)
    if reviewed.status != "awaiting_approval":
        raise SystemExit(reviewed.error or "Demo stopped before review")

    completed = service.approve(job.id)
    print(f"job_id={completed.id}")
    print(f"status={completed.status}")
    print(f"subtitle={completed.output_srt_path}")
    print(f"video={completed.output_video_path}")
    print(f"trace={service.artifacts_root / job.id / 'agent_trace.json'}")


if __name__ == "__main__":
    asyncio.run(main())
