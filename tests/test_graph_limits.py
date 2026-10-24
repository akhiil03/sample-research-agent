from __future__ import annotations

from research_agent.config import Settings
from research_agent.graph import run_research

from .helpers import (
    STUB_TOOLS,
    critique_message,
    digest_message,
    plan_message,
    scripted,
    tool_call_message,
)


def _settings(tmp_path, **overrides):
    defaults = {
        "topic": "test topic",
        "model": "openrouter/free",
        "fake_model": True,
        "output_dir": tmp_path,
        "max_iterations": 1,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_graph_caps_tool_turns_and_emits_events(tmp_path):
    model = scripted(
        plan_message(["loop query"]),
        tool_call_message(("web_search", {"query": "loop query"})),
        tool_call_message(("fetch_page", {"url": "https://example.com/b"})),
        critique_message(sufficient=True),
        digest_message(),
    )
    events = []

    result = run_research(
        _settings(tmp_path),
        llm=model,
        tools=STUB_TOOLS,
        max_tool_turns=2,
        event_sink=events.append,
    )

    assert model.cursor == 5
    assert result.rounds == 1
    assert result.output_path

    stages = [event["stage"] for event in events]
    assert stages[:2] == ["plan", "research"]
    assert "tools" in stages
    assert stages[-1] == "save"
    plan_event = events[0]
    assert plan_event["status"] == "complete"
    assert plan_event["queries"] == ["loop query"]
    save_event = events[-1]
    assert save_event["output_path"] == result.output_path
    assert save_event["sources"] == len(result.sources)
