from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


ToolHandler = Callable[..., Any] | Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    label: str
    handler: ToolHandler


class ToolRunner:
    def __init__(self, max_retries: int = 1) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        self.max_retries = max_retries

    async def run(self, spec: ToolSpec, *args: Any, **kwargs: Any) -> tuple[Any, list[dict[str, Any]]]:
        trace: list[dict[str, Any]] = []
        attempts = self.max_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                result = spec.handler(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                trace.append(
                    {
                        "tool": spec.name,
                        "label": spec.label,
                        "attempt": attempt,
                        "status": "succeeded",
                        "detail": "Tool completed.",
                    }
                )
                return result, trace
            except Exception as exc:
                trace.append(
                    {
                        "tool": spec.name,
                        "label": spec.label,
                        "attempt": attempt,
                        "status": "failed",
                        "detail": str(exc),
                    }
                )
                if attempt == attempts:
                    raise

        raise RuntimeError("Tool runner exhausted without returning")
