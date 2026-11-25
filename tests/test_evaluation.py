from app.evaluation import FailureEvent, ScenarioResult, summarize_results


def test_summarize_results_uses_task_and_event_denominators() -> None:
    results = [
        ScenarioResult(
            scenario="baseline",
            completed=True,
            manually_reworked=False,
            failures=[FailureEvent(kind="constraint_repair", recovery_ms=20)],
        ),
        ScenarioResult(
            scenario="transient_retry",
            completed=True,
            manually_reworked=True,
            failures=[
                FailureEvent(kind="constraint_repair", recovery_ms=40),
                FailureEvent(kind="transient_tool", recovery_ms=60),
            ],
        ),
        ScenarioResult(
            scenario="configuration_failure",
            completed=False,
            manually_reworked=False,
            failures=[FailureEvent(kind="configuration_error", recovery_ms=None)],
        ),
        ScenarioResult(
            scenario="clean",
            completed=True,
            manually_reworked=False,
            failures=[],
        ),
    ]

    summary = summarize_results(results)

    assert summary["total_tasks"] == 4
    assert summary["completed_tasks"] == 3
    assert summary["success_rate_pct"] == 75.0
    assert summary["manual_rework_tasks"] == 1
    assert summary["manual_rework_rate_pct"] == 33.33
    assert summary["failure_type_counts"] == {
        "constraint_repair": 2,
        "transient_tool": 1,
        "configuration_error": 1,
    }
    assert summary["failure_type_distribution_pct"] == {
        "constraint_repair": 50.0,
        "transient_tool": 25.0,
        "configuration_error": 25.0,
    }
    assert summary["average_recovery_ms"] == 40.0
    assert summary["average_recovery_ms_by_type"] == {
        "constraint_repair": 30.0,
        "transient_tool": 60.0,
    }


def test_summarize_results_handles_no_tasks_and_no_recovery_events() -> None:
    empty = summarize_results([])
    failed = summarize_results(
        [
            ScenarioResult(
                scenario="configuration_failure",
                completed=False,
                manually_reworked=False,
                failures=[FailureEvent(kind="configuration_error", recovery_ms=None)],
            )
        ]
    )

    assert empty["success_rate_pct"] == 0.0
    assert empty["manual_rework_rate_pct"] == 0.0
    assert empty["average_recovery_ms"] is None
    assert failed["average_recovery_ms"] is None
