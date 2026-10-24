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
    structured,
    summary_message,
    tool_call_message,
    verdict_message,
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
        tool_call_message(
            ("web_search", {"query": "first query"}),
            ("fetch_page", {"url": "https://example.com/a"}),
        ),
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


def test_fetch_gate_autofetches_a_page(tmp_path):
    model = scripted(
        plan_message(["gateway query"]),
        tool_call_message(("web_search", {"query": "gateway query"})),
        summary_message("- A search hit (https://example.com/a)."),
        summary_message("- Page text confirms the search hit."),
        critique_message(sufficient=True),
        digest_message(),
    )
    events: list[dict[str, object]] = []

    result = run_research(
        _settings(tmp_path),
        llm=model,
        tools=STUB_TOOLS,
        max_tool_turns=2,
        event_sink=events.append,
    )

    fetch_events = [
        event for event in events if event["stage"] == "fetch" and event["status"] == "started"
    ]
    assert [event["url"] for event in fetch_events] == ["https://example.com/a"]
    page_sources = [source for source in result.sources if source["kind"] == "page"]
    assert [source["url"] for source in page_sources] == ["https://example.com/a"]
    assert model.cursor == 6


def test_verify_strips_out_of_range_citations(tmp_path):
    digest = (
        "## TL;DR\n\n- A concise finding [1].\n\n"
        "## Key findings\n\n- Phantom claim [9].\n\n"
        "## Uncertainties and conflicting claims\n\n- None recorded.\n\n"
        "## Open questions\n\n- None.\n"
    )
    model = scripted(
        plan_message(),
        tool_call_message(
            ("web_search", {"query": "test topic overview"}),
            ("fetch_page", {"url": "https://example.com/a"}),
        ),
        summary_message(),
        critique_message(sufficient=True),
        AIMessage(content=digest),
    )
    events: list[dict[str, object]] = []

    result = run_research(
        _settings(tmp_path), llm=model, tools=STUB_TOOLS, event_sink=events.append
    )

    text = (tmp_path / result.output_path.split("/")[-1]).read_text(encoding="utf-8")
    assert "[9]" not in text
    assert "[1]" in text
    verify = [event for event in events if event["stage"] == "verify"][-1]
    assert verify["dropped"] == 1
    assert verify["verdict"] == "pass"


def test_verify_revise_loop_rewrites_draft_once(tmp_path):
    model = structured(
        plan_message(),
        tool_call_message(
            ("web_search", {"query": "test topic overview"}),
            ("fetch_page", {"url": "https://example.com/a"}),
        ),
        summary_message(),
        critique_message(sufficient=True),
        AIMessage(content="## TL;DR\n\n- Draft one claim [1]."),
        verdict_message("revise", claims=["draft claim has no source"], issues=[]),
        AIMessage(content="## TL;DR\n\n- Draft two cites corroboration [1][2]."),
        verdict_message("pass"),
    )
    events: list[dict[str, object]] = []

    result = run_research(
        _settings(tmp_path),
        llm=model,
        tools=STUB_TOOLS,
        use_structured_outputs=True,
        event_sink=events.append,
    )

    assert model.cursor == 8
    assert model.structured_schemas == [
        "PlanResponse",
        "CritiqueResponse",
        "VerificationResponse",
    ]
    writes = [
        event for event in events if event["stage"] == "write" and event["status"] == "started"
    ]
    assert len(writes) == 2
    revised = [event for event in events if event["stage"] == "verify" and event.get("revised")]
    assert len(revised) == 1
    text = (tmp_path / result.output_path.split("/")[-1]).read_text(encoding="utf-8")
    assert "Draft two cites corroboration" in text
    assert "Draft one claim" not in text


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
        tool_call_message(
            ("web_search", {"query": "test topic overview"}),
            ("fetch_page", {"url": "https://example.com/a"}),
        ),
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
