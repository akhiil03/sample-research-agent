from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from research_agent.api import ResearchService, create_app
from research_agent.state import RunResult


def _result(topic: str, model: str) -> RunResult:
    return RunResult(
        topic=topic,
        model=model,
        output_path="reports/fake.md",
        report="# Fake digest\n\n- A finding [1]\n\n## Sources\n\n1. [Example](https://example.com)",
        sources=[
            {
                "title": "Example",
                "url": "https://example.com",
                "snippet": "Example snippet",
                "kind": "search",
            }
        ],
        rounds=1,
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        thread_id="thread-1",
        elapsed_seconds=0.42,
    )


def fake_runner(settings: Any, *, event_sink=None) -> RunResult:
    if event_sink:
        event_sink({"stage": "plan", "status": "complete", "questions": ["q"], "queries": ["q1"]})
        event_sink({"stage": "research", "status": "started", "rounds": 0, "queries": ["q1"]})
        event_sink(
            {"stage": "research", "status": "complete", "tool_calls": 1, "sources": 1, "rounds": 0}
        )
        event_sink(
            {
                "stage": "critique",
                "status": "complete",
                "round": 1,
                "sufficient": True,
                "gaps": [],
            }
        )
        event_sink({"stage": "write", "status": "started", "sources": 1, "rounds": 1})
        event_sink(
            {
                "stage": "save",
                "status": "complete",
                "output_path": "reports/fake.md",
                "rounds": 1,
                "sources": 1,
            }
        )
    return _result(settings.topic, settings.model)


def failing_runner(settings: Any, *, event_sink=None) -> RunResult:
    raise RuntimeError(f"provider unavailable for {settings.topic}")


def _wait(client: TestClient, run_id: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_FAKE_MODEL", "1")
    for name in ("AGENT_MODEL", "AGENT_PROVIDER", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    service = ResearchService(fake_runner)
    with TestClient(create_app(service)) as test_client:
        yield test_client


def test_health_reports_offline_mode(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["fake_model"] is True
    assert payload["provider"] == "google"
    assert payload["default_model"] == "gemini-3.5-flash-lite"


def test_create_run_validates_topic(client):
    assert client.post("/api/runs", json={"topic": " "}).status_code == 422
    assert client.post("/api/runs", json={"topic": "ok", "max_iterations": 9}).status_code == 422


def test_run_lifecycle(client):
    response = client.post(
        "/api/runs",
        json={"topic": "  small   language models ", "max_iterations": 1},
    )
    assert response.status_code == 202
    created = response.json()
    assert created["topic"] == "small language models"
    assert created["status"] in {"queued", "running"}

    finished = _wait(client, created["id"])
    assert finished["status"] == "succeeded"
    assert finished["stage"] == "done"
    assert finished["rounds"] == 1
    assert finished["source_count"] == 1
    assert finished["report"].startswith("# Fake digest")
    assert finished["elapsed_seconds"] >= 0
    assert finished["usage"]["total_tokens"] == 15
    assert [event["stage"] for event in finished["events"]][:2] == ["plan", "research"]

    report = client.get(f"/api/runs/{created['id']}/report")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/markdown")
    assert "attachment" in report.headers["content-disposition"]

    listing = client.get("/api/runs").json()["runs"]
    assert listing[0]["id"] == created["id"]
    assert "report" not in listing[0]


def test_unknown_run_returns_404(client):
    assert client.get("/api/runs/run_missing").status_code == 404
    assert client.get("/api/runs/run_missing/report").status_code == 404


def test_failed_run_surfaces_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_FAKE_MODEL", "1")
    service = ResearchService(failing_runner)
    with TestClient(create_app(service)) as client:
        created = client.post("/api/runs", json={"topic": "failure case"}).json()
        finished = _wait(client, created["id"])
        assert finished["status"] == "failed"
        assert "provider unavailable" in finished["error"]
        assert client.get(f"/api/runs/{created['id']}/report").status_code == 409
