from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.benchmark import DEFAULT_SCENARIO_COUNTS, run_benchmark  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic VideoLocalize Agent fault-injection benchmark."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/benchmark-results.json"),
        help="Path for the JSON report.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        help="Run each scenario this many times. Defaults to the weighted 12-task matrix.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    with tempfile.TemporaryDirectory(
        prefix="videolocalize-benchmark-",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        report = await run_benchmark(
            Path(temp_dir),
            repetitions=args.repetitions,
            scenario_counts=(
                None if args.repetitions is not None else DEFAULT_SCENARIO_COUNTS
            ),
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
