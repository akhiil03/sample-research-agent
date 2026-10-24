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


def test_graph_caps_tool_turns(tmp_path):
    model = scripted(
        plan_message(["loop query"]),
        tool_call_message(("web_search", {"query": "loop query"})),
        tool_call_message(("fetch_page", {"url": "https://example.com/b"})),
        critique_message(sufficient=True),
        digest_message(),
    )

    result = run_research(
        _settings(tmp_path),
        llm=model,
        tools=STUB_TOOLS,
        max_tool_turns=2,
    )

    assert model.cursor == 5
    assert result.rounds == 1
    assert result.output_path
