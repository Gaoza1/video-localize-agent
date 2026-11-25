import subprocess
import sys
import json
from pathlib import Path


def test_benchmark_cli_can_import_project_modules() -> None:
    project_root = Path(__file__).resolve().parent.parent

    result = subprocess.run(
        [sys.executable, "scripts/benchmark_agent.py", "--help"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "fault-injection benchmark" in result.stdout


def test_benchmark_cli_writes_json_report(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parent.parent
    output_path = tmp_path / "benchmark.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_agent.py",
            "--repetitions",
            "1",
            "--output",
            str(output_path),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["total_tasks"] == 5
