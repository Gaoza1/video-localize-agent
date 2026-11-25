from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.agent import ToolRunner, ToolSpec
from app.evaluation import FailureEvent, ScenarioResult, summarize_results
from app.job_service import JobService
from app.srt import parse_srt, to_srt


SCENARIOS = (
    "baseline",
    "transient_retry",
    "manual_rework",
    "configuration_failure",
    "persistent_tool_failure",
)

DEFAULT_SCENARIO_COUNTS = {
    "baseline": 3,
    "transient_retry": 3,
    "manual_rework": 2,
    "configuration_failure": 2,
    "persistent_tool_failure": 2,
}


class FaultInjectingToolRunner(ToolRunner):
    def __init__(self, failures: dict[str, int] | None = None) -> None:
        super().__init__(max_retries=1)
        self.failures = dict(failures or {})
        self.recovery_ms: dict[str, float] = {}

    async def run(
        self,
        spec: ToolSpec,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[Any, list[dict[str, Any]]]:
        original_handler = spec.handler
        started = time.perf_counter()

        def flaky_handler(*handler_args: Any, **handler_kwargs: Any) -> Any:
            remaining = self.failures.get(spec.name, 0)
            if remaining:
                self.failures[spec.name] = remaining - 1
                raise RuntimeError(f"Injected failure in {spec.name}")
            return original_handler(*handler_args, **handler_kwargs)

        wrapped = ToolSpec(name=spec.name, label=spec.label, handler=flaky_handler)
        result, trace = await super().run(wrapped, *args, **kwargs)
        if any(item["status"] == "failed" for item in trace):
            self.recovery_ms[spec.name] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        return result, trace


async def run_scenario(root: Path, scenario: str) -> ScenarioResult:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown benchmark scenario: {scenario}")

    service = JobService(root / scenario)
    injected: dict[str, int] = {}
    if scenario == "transient_retry":
        injected["inspect_video"] = 1
    elif scenario == "persistent_tool_failure":
        injected["inspect_video"] = 2

    runner = FaultInjectingToolRunner(injected)
    service.tool_runner = runner

    if scenario == "configuration_failure":
        video_path, _ = service._ensure_demo_assets()
        job = service.create_upload_job(
            video_path=video_path,
            source_name="Missing ASR configuration",
            source_language="en",
            target_language="zh-CN",
            subtitle_path=None,
            mode="live",
        )
    else:
        job = service.create_demo_job(target_language="zh-CN")

    reviewed = await service.run_until_review(job.id)
    manually_reworked = False
    if reviewed.status == "awaiting_approval":
        if scenario == "manual_rework":
            _apply_manual_rework(Path(reviewed.translated_srt_path))
            manually_reworked = True
        completed = service.approve(job.id)
    else:
        completed = reviewed

    failures: list[FailureEvent] = []
    repair_step = next(
        (step for step in completed.steps if step.tool == "repair_subtitles"),
        None,
    )
    if repair_step is not None:
        failures.append(
            FailureEvent(
                kind="constraint_repair",
                recovery_ms=float(repair_step.duration_ms),
            )
        )

    if runner.recovery_ms.get("inspect_video") is not None:
        failures.append(
            FailureEvent(
                kind="transient_tool",
                recovery_ms=runner.recovery_ms["inspect_video"],
            )
        )

    if completed.status == "failed":
        error = completed.error or ""
        if "ASR_BASE_URL" in error or "ASR_API_KEY" in error:
            kind = "configuration_error"
        elif "Injected failure in inspect_video" in error:
            kind = "persistent_tool_failure"
        else:
            kind = "unexpected_error"
        failures.append(FailureEvent(kind=kind, recovery_ms=None))

    return ScenarioResult(
        scenario=scenario,
        completed=completed.status == "completed",
        manually_reworked=manually_reworked,
        failures=failures,
    )


async def run_benchmark(
    root: Path,
    repetitions: int | None = None,
    scenario_counts: dict[str, int] | None = None,
) -> dict:
    if repetitions is not None and scenario_counts is not None:
        raise ValueError("Use repetitions or scenario_counts, not both")

    counts = scenario_counts or {
        scenario: repetitions if repetitions is not None else 1
        for scenario in SCENARIOS
    }
    results: list[ScenarioResult] = []
    for scenario, count in counts.items():
        for run_index in range(count):
            results.append(
                await run_scenario(
                    root / f"{scenario}-{run_index + 1}",
                    scenario,
                )
            )

    return {
        "summary": summarize_results(results),
        "results": [asdict(result) for result in results],
        "benchmark": {
            "mode": "offline deterministic demo",
            "scenario_counts": counts,
        },
    }


def _apply_manual_rework(review_path: Path) -> None:
    cues = parse_srt(review_path.read_text(encoding="utf-8"))
    if not cues:
        raise ValueError("Review subtitle has no cues to edit")
    cues[0] = replace(cues[0], text="人工审校后的字幕。")
    review_path.write_text(to_srt(cues), encoding="utf-8")
