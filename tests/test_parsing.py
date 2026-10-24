from __future__ import annotations

import json
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, ToolMessage

from research_agent.graph import (
    _ensure_report_shape,
    build_evidence,
    build_numbered_sources,
    extract_json,
    slugify,
    write_report,
)


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    content = 'Here you go:\n```json\n{"sufficient": true}\n```\nThanks'
    assert extract_json(content) == {"sufficient": True}


def test_extract_json_from_content_blocks():
    content = [{"type": "text", "text": '{"questions": ["q"]}'}]
    assert extract_json(content) == {"questions": ["q"]}


def test_extract_json_returns_none_for_garbage():
    assert extract_json("no json here") is None
    assert extract_json("") is None
    assert extract_json([1, 2, 3]) is None


def test_slugify():
    assert slugify("AI Agents: 2026 & Beyond!") == "ai-agents-2026-beyond"
    assert slugify("???") == "digest"


def test_write_report_adds_frontmatter_and_sources(tmp_path):
    path = write_report(
        topic="A Topic",
        report="# Title\n\nBody\n",
        output_dir=tmp_path,
        model="openrouter/free",
        rounds=2,
        sources=[
            {"title": "Source A", "url": "https://example.com/a", "snippet": "", "kind": "page"}
        ],
        generated_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    text = path.read_text(encoding="utf-8")
    assert path.name == "2026-01-02-a-topic.md"
    assert 'topic: "A Topic"' in text
    assert "rounds: 2" in text
    assert "sources: 1" in text
    assert text.count("# Title") == 1


def test_ensure_report_shape_adds_title_and_sources():
    sources = [{"title": "Source", "url": "https://example.com", "snippet": "", "kind": "page"}]
    report = _ensure_report_shape("## TL;DR\n\n- Point.\n", "topic", sources)
    assert report.startswith("# Research digest: topic")
    assert "## Sources" in report


def test_ensure_report_shape_does_not_duplicate_sources_section():
    sources = [{"title": "Source", "url": "https://example.com", "snippet": "", "kind": "page"}]
    report = _ensure_report_shape(
        "# Title\n\n## Sources\n\n1. [Source](https://example.com)\n", "topic", sources
    )
    assert report.count("## Sources") == 1


def test_build_numbered_sources_empty():
    assert build_numbered_sources([]) == "_No sources were retrieved._"


def test_build_evidence_is_bounded():
    huge = "x" * 50_000
    messages = [
        ToolMessage(
            name="fetch_page",
            content=json.dumps({"url": "https://e.com", "title": "T", "text": huge}),
            tool_call_id="1",
        )
    ]
    evidence = build_evidence(messages, max_chars=2000)
    assert len(evidence) <= 2000


def test_build_evidence_ignores_non_tool_messages():
    messages = [AIMessage(content="hello"), ToolMessage(name="x", content="raw", tool_call_id="1")]
    evidence = build_evidence(messages)
    assert "TOOL x" in evidence
    assert "hello" not in evidence
