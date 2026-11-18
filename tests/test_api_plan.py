from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from whoneedsacoach.api.app import create_app
from whoneedsacoach.models.training import TrainingPlan, Workout
from whoneedsacoach.planner.training import TrainingResult


def _plan_body():
    return {
        "race": {"distance": "half_marathon", "date": "2027-06-01"},
        "schedule": {"run_days": ["wed", "fri", "sun"], "long_run_day": "sun"},
        "baseline": {"weekly_km": 30.0, "long_run_km": 12.0},
        "pr": {"time": "1:45:00", "date": "2026-06-01"},
    }


def _client(tmp_path):
    app = create_app(db_path=tmp_path / "coach.db", tokens_root=tmp_path / "tokens")
    client = TestClient(app)
    reg = client.post(
        "/auth/register",
        json={"email": "anay@example.com", "password": "password1"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    return client, headers, app


@pytest.fixture
def fake_build(monkeypatch):
    async def _build(profile, today=None):
        today = today or date.today()
        plan = TrainingPlan(
            short_summary="Test plan",
            workouts=[
                Workout(
                    date=today,
                    kind="easy",
                    distance_km=8.0,
                    pace_low="5:30",
                    pace_high="5:50",
                    structure="",
                )
            ],
        )
        return TrainingResult(plan=plan, warnings=[])

    monkeypatch.setattr("whoneedsacoach.jobs.plan_build.build_training_plan", _build)
    monkeypatch.setattr("whoneedsacoach.jobs.plan_build.write_plan", lambda *a, **k: None)
    return _build


def test_create_plan_without_provider_and_poll(tmp_path, fake_build):
    client, headers, _ = _client(tmp_path)
    created = client.post("/plan", headers=headers, json=_plan_body())
    assert created.status_code == 202
    assert created.json()["status"] == "pending"
    assert created.json()["plan"] is None

    # TestClient runs BackgroundTasks before returning from the request.
    polled = client.get("/plan", headers=headers)
    assert polled.status_code == 200
    body = polled.json()
    assert body["status"] == "active"
    assert body["plan"] is not None
    assert body["race"]["distance"] == "half_marathon"


def test_post_plan_overwrites_never_409(tmp_path, fake_build):
    client, headers, _ = _client(tmp_path)
    first = client.post("/plan", headers=headers, json=_plan_body())
    assert first.status_code == 202
    second_body = _plan_body()
    second_body["race"]["distance"] = "10k"
    second_body["race"]["date"] = "2027-05-01"
    second_body["pr"] = {"time": "49:04", "date": "2026-06-01"}
    second = client.post("/plan", headers=headers, json=second_body)
    assert second.status_code == 202
    assert second.status_code != 409
    polled = client.get("/plan", headers=headers)
    assert polled.json()["race"]["distance"] == "10k"
    assert polled.json()["status"] == "active"


def test_get_plan_404_when_missing(tmp_path):
    client, headers, _ = _client(tmp_path)
    assert client.get("/plan", headers=headers).status_code == 404


def test_bad_plan_body_rejected_before_queue(tmp_path, fake_build):
    client, headers, app = _client(tmp_path)
    spy = AsyncMock()
    # If validation fails, background job must not run.
    app.state  # keep app referenced
    bad = _plan_body()
    bad["baseline"]["weekly_km"] = 999
    response = client.post("/plan", headers=headers, json=bad)
    assert response.status_code == 400
    assert client.get("/plan", headers=headers).status_code == 404


def test_failed_status_sets_error_message(tmp_path, monkeypatch):
    async def boom(profile, today=None):
        raise RuntimeError("llm down")

    monkeypatch.setattr("whoneedsacoach.jobs.plan_build.build_training_plan", boom)
    monkeypatch.setattr("whoneedsacoach.jobs.plan_build.write_plan", lambda *a, **k: None)

    client, headers, _ = _client(tmp_path)
    created = client.post("/plan", headers=headers, json=_plan_body())
    assert created.status_code == 202
    polled = client.get("/plan", headers=headers)
    assert polled.json()["status"] == "failed"
    assert "llm down" in polled.json()["error_message"]
    assert polled.json()["failed_at"]
