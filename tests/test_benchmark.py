import asyncio
from pathlib import Path

from app.benchmark import run_benchmark, run_scenario


def test_transient_retry_recovers_and_records_both_failure_types(
    tmp_path: Path,
) -> None:
    result = asyncio.run(run_scenario(tmp_path, "transient_retry"))

    assert result.completed is True
    kinds = [failure.kind for failure in result.failures]
    assert "constraint_repair" in kinds
    assert "transient_tool" in kinds
    transient = next(
        failure for failure in result.failures if failure.kind == "transient_tool"
    )
    assert transient.recovery_ms is not None
    assert transient.recovery_ms >= 0


def test_configuration_failure_stops_without_recovery_time(tmp_path: Path) -> None:
    result = asyncio.run(run_scenario(tmp_path, "configuration_failure"))

    assert result.completed is False
    assert [(failure.kind, failure.recovery_ms) for failure in result.failures] == [
        ("configuration_error", None)
    ]


def test_benchmark_matrix_tracks_success_and_manual_rework(tmp_path: Path) -> None:
    report = asyncio.run(run_benchmark(tmp_path, repetitions=1))

    assert report["summary"]["total_tasks"] == 5
    assert report["summary"]["completed_tasks"] == 3
    assert report["summary"]["success_rate_pct"] == 60.0
    assert report["summary"]["manual_rework_tasks"] == 1
    assert report["summary"]["manual_rework_rate_pct"] == 33.33
