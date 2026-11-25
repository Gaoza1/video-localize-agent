import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_demo_job_can_be_created_and_read(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path, auto_start_jobs=False)
    client = TestClient(app)

    response = client.post("/api/jobs/demo", json={"target_language": "zh-CN"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["mode"] == "demo"
    assert payload["status"] == "queued"

    asyncio.run(app.state.job_service.run_until_review(payload["id"]))
    detail = client.get(f"/api/jobs/{payload['id']}")

    assert detail.status_code == 200
    assert detail.json()["status"] == "awaiting_approval"


def test_config_reports_demo_mode(tmp_path: Path) -> None:
    client = TestClient(create_app(data_root=tmp_path))

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["demo_mode_available"] is True


def test_recent_jobs_endpoint_accepts_limit(tmp_path: Path) -> None:
    client = TestClient(create_app(data_root=tmp_path))

    response = client.get("/api/jobs?limit=6")

    assert response.status_code == 200
    assert response.json() == []
