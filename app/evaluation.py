from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True, slots=True)
class FailureEvent:
    kind: str
    recovery_ms: int | None


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario: str
    completed: bool
    manually_reworked: bool
    failures: list[FailureEvent]


def summarize_results(results: list[ScenarioResult]) -> dict:
    total_tasks = len(results)
    completed_tasks = sum(result.completed for result in results)
    manually_reworked = sum(
        result.completed and result.manually_reworked for result in results
    )

    failure_counts = Counter(
        failure.kind
        for result in results
        for failure in result.failures
    )
    failure_total = sum(failure_counts.values())
    recovery_times = [
        failure.recovery_ms
        for result in results
        for failure in result.failures
        if failure.recovery_ms is not None
    ]
    recovery_by_type: dict[str, list[float]] = {}
    for result in results:
        for failure in result.failures:
            if failure.recovery_ms is not None:
                recovery_by_type.setdefault(failure.kind, []).append(
                    failure.recovery_ms
                )

    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "success_rate_pct": _percentage(completed_tasks, total_tasks),
        "manual_rework_tasks": manually_reworked,
        "manual_rework_rate_pct": _percentage(manually_reworked, completed_tasks),
        "failure_event_count": failure_total,
        "failure_type_counts": dict(failure_counts),
        "failure_type_distribution_pct": {
            kind: _percentage(count, failure_total)
            for kind, count in failure_counts.items()
        },
        "average_recovery_ms": (
            round(mean(recovery_times), 2) if recovery_times else None
        ),
        "average_recovery_ms_by_type": {
            kind: round(mean(values), 2)
            for kind, values in recovery_by_type.items()
        },
    }


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator * 100, 2)
