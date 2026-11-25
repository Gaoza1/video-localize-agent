import asyncio

from app.agent import ToolRunner, ToolSpec


def test_tool_runner_retries_transient_failure() -> None:
    attempts = 0

    async def unstable_tool() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise RuntimeError("temporary failure")
        return "ok"

    runner = ToolRunner(max_retries=1)
    result, trace = asyncio.run(
        runner.run(
            ToolSpec(
                name="unstable_tool",
                label="Unstable tool",
                handler=unstable_tool,
            )
        )
    )

    assert result == "ok"
    assert attempts == 2
    assert [item["status"] for item in trace] == ["failed", "succeeded"]


def test_tool_runner_stops_after_budget() -> None:
    attempts = 0

    async def always_fails() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("still broken")

    runner = ToolRunner(max_retries=1)

    try:
        asyncio.run(
            runner.run(
                ToolSpec(
                    name="always_fails",
                    label="Always fails",
                    handler=always_fails,
                )
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "still broken"
    else:
        raise AssertionError("Expected tool failure")

    assert attempts == 2
