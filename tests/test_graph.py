from __future__ import annotations

from langchain_core.messages import AIMessage

from research_agent.config import Settings
from research_agent.graph import build_checkpointer, build_graph, run_research

from .helpers import (
    STUB_TOOLS,
    critique_message,
    digest_message,
    plan_message,
    scripted,
    summary_message,
    tool_call_message,
)


def _settings(tmp_path, **overrides):
    defaults = {
        "topic": "test topic",
        "model": "openrouter/free",
        "fake_model": True,
        "output_dir": tmp_path,
        "max_iterations": 2,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_graph_runs_end_to_end_and_writes_cited_digest(tmp_path):
    model = scripted(
        plan_message(),
        tool_call_message(
            ("web_search", {"query": "test topic overview", "max_results": 2}),
            ("fetch_page", {"url": "https://example.com/a"}),
        ),
        summary_message(),
        critique_message(sufficient=True),
        digest_message(),
    )

    result = run_research(_settings(tmp_path), llm=model, tools=STUB_TOOLS)

    report_path = tmp_path / result.output_path.split("/")[-1]
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "## TL;DR" in text
    assert "## Sources" in text
    assert "https://example.com/a" in text
    assert "https://example.org/b" in text
    assert result.rounds == 1
    assert len(result.sources) == 2
    assert result.thread_id


def test_graph_stops_at_iteration_cap(tmp_path):
    model = scripted(
        plan_message(["first query"]),
        tool_call_message(("web_search", {"query": "first query"})),
        summary_message(),
        critique_message(sufficient=False, follow_ups=["second query"]),
        summary_message(),
        critique_message(sufficient=False, follow_ups=["third query"]),
        digest_message(),
    )

    result = run_research(_settings(tmp_path, max_iterations=2), llm=model, tools=STUB_TOOLS)

    assert model.cursor == 7
    assert result.rounds == 2
    assert (tmp_path / result.output_path.split("/")[-1]).exists()


def test_graph_handles_no_tool_calls(tmp_path):
    model = scripted(
        plan_message(),
        summary_message("No tools were needed."),
        critique_message(sufficient=True),
        digest_message(),
    )

    result = run_research(_settings(tmp_path, max_iterations=1), llm=model, tools=STUB_TOOLS)

    assert result.sources == []
    text = (tmp_path / result.output_path.split("/")[-1]).read_text(encoding="utf-8")
    assert "No sources were retrieved." in text


def test_graph_recovers_from_invalid_plan_json(tmp_path):
    model = scripted(
        AIMessage(content="Sorry, I cannot produce JSON today."),
        summary_message(),
        critique_message(sufficient=True),
        digest_message(),
    )

    result = run_research(_settings(tmp_path, max_iterations=1), llm=model, tools=STUB_TOOLS)

    assert result.output_path
    assert result.rounds == 1


def test_sqlite_checkpointer_persists_state(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite"
    saver = build_checkpointer("sqlite", db_path)
    settings = _settings(tmp_path, checkpointer="sqlite", sqlite_path=db_path, max_iterations=1)
    model = scripted(
        plan_message(),
        tool_call_message(("web_search", {"query": "test topic overview"})),
        summary_message(),
        critique_message(sufficient=True),
        digest_message(),
    )

    result = run_research(settings, llm=model, tools=STUB_TOOLS, checkpointer=saver)

    assert db_path.exists()
    graph = build_graph(
        llm=scripted(digest_message()),
        tools=STUB_TOOLS,
        checkpointer=saver,
        output_dir=tmp_path,
    )
    snapshot = graph.get_state({"configurable": {"thread_id": result.thread_id}})
    assert snapshot.values["output_path"] == result.output_path
    assert snapshot.values["final_report"]
