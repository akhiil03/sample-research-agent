from __future__ import annotations

import types

from research_agent.publish import MAX_EVENTS, StatusPublisher, describe_event


def make_publisher(monkeypatch) -> tuple[StatusPublisher, list[dict]]:
    calls: list[dict] = []

    def fake_request(self, method, url, body=None):  # noqa: ANN001, ANN202
        calls.append({"method": method, "url": url, "body": body})
        return {"content": {"sha": "sha-1"}}

    monkeypatch.setattr(StatusPublisher, "_request", fake_request)
    publisher = StatusPublisher(
        repository="owner/repo",
        token="token",
        run_id="run_test",
        topic="tiny models",
        model="gemini-test",
        max_iterations=2,
    )
    return publisher, calls


def test_from_env_disabled_without_configuration(monkeypatch):
    monkeypatch.delenv("STATUS_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert StatusPublisher.from_env(topic="t", model="m", max_iterations=1) is None


def test_from_env_reads_workflow_environment(monkeypatch):
    monkeypatch.setenv("STATUS_RUN_ID", "run_123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.delenv("STATUS_BRANCH", raising=False)
    publisher = StatusPublisher.from_env(topic="t", model="m", max_iterations=1)
    assert publisher is not None
    assert publisher.repository == "owner/repo"
    assert publisher.run_id == "run_123"
    assert publisher.branch == "status"


def test_apply_event_records_timestamped_events(monkeypatch):
    publisher, calls = make_publisher(monkeypatch)
    publisher.apply_event({"stage": "plan", "status": "started"})
    publisher.apply_event({"stage": "plan", "queries": ["a", "b"]})
    assert len(calls) == 1  # throttled
    publisher.publish(force=True)
    assert len(calls) == 2
    events = publisher.data["events"]
    assert len(events) == 2
    assert all("at" in event for event in events)
    assert publisher.data["stage"] == "plan"
    assert publisher.data["message"] == "Planned 2 search queries"


def test_apply_event_caps_growth(monkeypatch):
    publisher, _ = make_publisher(monkeypatch)
    for index in range(MAX_EVENTS + 25):
        publisher.apply_event({"stage": "tools", "results": index})
    assert len(publisher.data["events"]) == MAX_EVENTS


def test_success_and_failure_states(monkeypatch):
    publisher, calls = make_publisher(monkeypatch)
    result = types.SimpleNamespace(
        rounds=2,
        sources=[{"title": "a", "url": "https://a", "snippet": "b", "kind": "page"}],
        report="# digest",
        output_path="reports/x.md",
        usage={"total_tokens": 10},
    )
    publisher.succeed(result)
    assert publisher.data["status"] == "succeeded"
    assert publisher.data["report"] == "# digest"
    assert publisher.data["source_count"] == 1
    assert publisher.data["finished_at"] is not None
    assert "sha" not in calls[-1]["body"]

    publisher.fail("boom")
    assert publisher.data["status"] == "failed"
    assert publisher.data["error"] == "boom"
    assert calls[-1]["body"]["sha"] == "sha-1"


def test_describe_event_variants():
    assert describe_event({"stage": "research", "tool_calls": 3, "sources": 4}).startswith(
        "Gathering evidence"
    )
    assert describe_event({"stage": "critique", "sufficient": True}) == (
        "Critic is satisfied with the evidence"
    )
    assert describe_event({"stage": "save"}) == "Digest saved"
    assert describe_event({}) == "Working"
