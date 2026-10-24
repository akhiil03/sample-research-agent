"""The LangGraph research pipeline: plan -> research <-> tools -> critique -> write."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from . import prompts
from .config import Settings
from .llm import build_llm, build_offline_llm
from .state import ResearchState, RunResult, Source
from .tools import DEFAULT_TOOLS, OFFLINE_TOOLS, collect_sources

LOGGER = logging.getLogger(__name__)
MAX_EVIDENCE_CHARS = 24_000


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


def extract_json(content: Any) -> dict[str, Any] | None:
    """Pull the first parseable JSON object out of a model response."""
    text = message_text(content).strip()
    if not text:
        return None
    candidates = [text]
    candidates.extend(re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _string_list(value: Any, *, limit: int = 5) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    cleaned = [" ".join(str(item).split()) for item in value if str(item).strip()]
    return cleaned[:limit]


def _prune_code_fences(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(
        r"```(?:markdown|md)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE
    )
    return match.group(1).strip() if match else stripped


def slugify(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug[:60] or "digest"


def _findings(state: ResearchState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = message_text(message.content).strip()
            if text:
                return text
    return ""


def build_evidence(messages: Sequence[Any], max_chars: int = MAX_EVIDENCE_CHARS) -> str:
    """Compress tool outputs into a bounded evidence brief for the writer."""
    blocks: list[str] = []
    used = 0
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        name = message.name or "tool"
        try:
            payload = json.loads(message_text(message.content))
        except (TypeError, ValueError):
            payload = None
        block = ""
        if name == "web_search" and isinstance(payload, list):
            rows = []
            for row in payload:
                if isinstance(row, dict):
                    rows.append(
                        f"- {row.get('title', '')} ({row.get('url', '')}): {row.get('snippet', '')}"
                    )
            block = "SEARCH RESULTS:\n" + "\n".join(rows)
        elif name == "fetch_page" and isinstance(payload, dict):
            block = (
                f"PAGE: {payload.get('title', '')} ({payload.get('url', '')})\n"
                f"{str(payload.get('text', ''))[:8000]}"
            )
        else:
            block = f"TOOL {name}:\n{message_text(message.content)[:1500]}"
        if not block.strip():
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        blocks.append(block[:remaining])
        used += min(len(block), remaining)
    return "\n\n".join(blocks)


def build_numbered_sources(sources: list[Source]) -> str:
    if not sources:
        return "_No sources were retrieved._"
    return "\n".join(
        f"{index}. [{source['title']}]({source['url']})"
        for index, source in enumerate(sources, start=1)
    )


def _ensure_report_shape(report: str, topic: str, sources: list[Source]) -> str:
    body = _prune_code_fences(report)
    if not body:
        body = (
            f"## TL;DR\n\n- The model returned no content for **{topic}**.\n\n"
            "## Key findings\n\n- See the collected sources below.\n\n"
            "## Uncertainties and conflicting claims\n\n- The digest could not be synthesized.\n\n"
            "## Open questions\n\n- Re-run the agent with a different model.\n"
        )
    if not body.lstrip().startswith("# "):
        body = f"# Research digest: {topic}\n\n{body}"
    if "## Sources" not in body:
        body = f"{body.rstrip()}\n\n## Sources\n\n{build_numbered_sources(sources)}\n"
    return body.rstrip() + "\n"


def write_report(
    *,
    topic: str,
    report: str,
    output_dir: Path,
    model: str,
    rounds: int,
    sources: list[Source],
    generated_at: datetime | None = None,
) -> Path:
    timestamp = generated_at or datetime.now(UTC)
    frontmatter = "\n".join(
        [
            "---",
            f'topic: "{topic.replace(chr(34), chr(39))}"',
            f'model: "{model}"',
            f"generated_at: {timestamp.isoformat(timespec='seconds')}",
            f"rounds: {rounds}",
            f"sources: {len(sources)}",
            "generated_by: sample-research-agent",
            "---",
        ]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{timestamp.strftime('%Y-%m-%d')}-{slugify(topic)}.md"
    path.write_text(f"{frontmatter}\n\n{report}", encoding="utf-8", newline="\n")
    return path


def build_checkpointer(
    kind: str = "memory", sqlite_path: Path | str | None = None
) -> InMemorySaver | SqliteSaver:
    if kind == "sqlite":
        path = Path(sqlite_path or Path(".agent") / "checkpoints.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), check_same_thread=False)
        return SqliteSaver(connection)
    return InMemorySaver()


def build_graph(
    *,
    llm: BaseChatModel,
    tools: list[BaseTool] | None = None,
    checkpointer: InMemorySaver | SqliteSaver | None = None,
    max_iterations: int = 2,
    max_tool_turns: int = 3,
    output_dir: Path | str = Path("reports"),
    model_name: str = "",
) -> Any:
    """Compile the research graph. Nodes close over the model, tools, and limits."""
    active_tools = list(tools or DEFAULT_TOOLS)
    research_llm = llm.bind_tools(active_tools)
    destination = Path(output_dir)

    def plan_node(state: ResearchState) -> dict[str, Any]:
        topic = state["topic"]
        response = llm.invoke(
            [
                SystemMessage(content=prompts.PLANNER_SYSTEM),
                HumanMessage(content=prompts.planner_task(topic)),
            ]
        )
        parsed = extract_json(response.content) or {}
        questions = _string_list(parsed.get("questions"), limit=4)
        queries = _string_list(parsed.get("search_queries"), limit=4)
        if not questions:
            questions = [
                f"What is the current state of {topic}?",
                f"What are the main limitations or open questions around {topic}?",
            ]
        if not queries:
            queries = [f"{topic} overview", f"{topic} limitations and criticism"]
        plan = {"questions": questions, "search_queries": queries}
        LOGGER.info("Planned %s questions and %s queries", len(questions), len(queries))
        return {
            "plan": plan,
            "pending_queries": queries,
            "used_queries": [],
            "rounds": 0,
            "tool_turns": 0,
            "messages": [AIMessage(content=json.dumps(plan, ensure_ascii=False))],
        }

    def research_node(state: ResearchState) -> dict[str, Any]:
        topic = state["topic"]
        plan = state.get("plan", {})
        batch = list(state.get("pending_queries", []))
        used = list(state.get("used_queries", []))
        for query in batch:
            if query not in used:
                used.append(query)
        response = research_llm.invoke(
            [
                SystemMessage(content=prompts.RESEARCHER_SYSTEM),
                *state.get("messages", []),
                HumanMessage(
                    content=prompts.research_task(
                        topic,
                        _string_list(plan.get("questions"), limit=4),
                        batch,
                        used,
                    )
                ),
            ]
        )
        messages = [*state.get("messages", []), response]
        sources = collect_sources(messages)
        LOGGER.info(
            "Research turn: %s tool call(s), %s source(s) collected",
            len(response.tool_calls),
            len(sources),
        )
        update: dict[str, Any] = {
            "messages": [response],
            "pending_queries": [],
            "used_queries": used,
            "sources": sources,
            "tool_turns": int(state.get("tool_turns", 0)) + (1 if response.tool_calls else 0),
        }
        if response.tool_calls:
            update["notes"] = "gathering evidence"
        return update

    def critique_node(state: ResearchState) -> dict[str, Any]:
        rounds = int(state.get("rounds", 0)) + 1
        sources = list(state.get("sources", []))
        response = llm.invoke(
            [
                SystemMessage(content=prompts.CRITIC_SYSTEM),
                HumanMessage(
                    content=prompts.critique_task(
                        state["topic"],
                        state.get("plan", {}),
                        sources,
                        _findings(state),
                        rounds,
                        max_iterations,
                    )
                ),
            ]
        )
        parsed = extract_json(response.content)
        if parsed is None:
            parsed = {
                "sufficient": bool(sources),
                "gaps": ["critique response was not valid JSON"],
                "follow_up_queries": [],
                "reason": message_text(response.content)[:500],
            }
        sufficient = bool(parsed.get("sufficient"))
        follow_ups = (
            []
            if sufficient or rounds >= max_iterations
            else _string_list(parsed.get("follow_up_queries"), limit=2)
        )
        LOGGER.info("Critique round %s: sufficient=%s", rounds, sufficient)
        return {
            "critique": {
                "sufficient": sufficient,
                "gaps": _string_list(parsed.get("gaps"), limit=5),
                "follow_up_queries": follow_ups,
                "reason": str(parsed.get("reason", ""))[:800],
            },
            "rounds": rounds,
            "pending_queries": follow_ups,
            "tool_turns": 0,
        }

    def write_node(state: ResearchState) -> dict[str, Any]:
        sources = list(state.get("sources", []))
        response = llm.invoke(
            [
                SystemMessage(content=prompts.WRITER_SYSTEM),
                HumanMessage(
                    content=prompts.writer_task(
                        state["topic"],
                        state.get("plan", {}),
                        sources,
                        build_evidence(state.get("messages", [])),
                        state.get("critique", {}),
                    )
                ),
            ]
        )
        report = _ensure_report_shape(message_text(response.content), state["topic"], sources)
        return {"final_report": report, "messages": [response]}

    def save_node(state: ResearchState) -> dict[str, Any]:
        path = write_report(
            topic=state["topic"],
            report=state.get("final_report", ""),
            output_dir=destination,
            model=model_name or state.get("model", ""),
            rounds=int(state.get("rounds", 0)),
            sources=list(state.get("sources", [])),
        )
        LOGGER.info("Wrote digest to %s", path)
        return {"output_path": str(path)}

    def route_after_research(state: ResearchState) -> str:
        messages = state.get("messages", [])
        if messages:
            last = messages[-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                if int(state.get("tool_turns", 0)) < max_tool_turns:
                    return "tools"
        return "critique"

    def route_after_critique(state: ResearchState) -> str:
        if int(state.get("rounds", 0)) >= max_iterations:
            return "write"
        if state.get("critique", {}).get("sufficient"):
            return "write"
        return "research" if state.get("pending_queries") else "write"

    builder = StateGraph(ResearchState)
    builder.add_node("plan", plan_node)
    builder.add_node("research", research_node)
    builder.add_node("tools", ToolNode(active_tools))
    builder.add_node("critique", critique_node)
    builder.add_node("write", write_node)
    builder.add_node("save", save_node)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "research")
    builder.add_conditional_edges(
        "research", route_after_research, {"tools": "tools", "critique": "critique"}
    )
    builder.add_edge("tools", "research")
    builder.add_conditional_edges(
        "critique", route_after_critique, {"research": "research", "write": "write"}
    )
    builder.add_edge("write", "save")
    builder.add_edge("save", END)

    return builder.compile(checkpointer=checkpointer)


def _aggregate_usage(messages: Sequence[Any]) -> dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for message in messages:
        usage = getattr(message, "usage_metadata", None) or {}
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
    return totals


def run_research(
    settings: Settings,
    *,
    llm: BaseChatModel | None = None,
    tools: list[BaseTool] | None = None,
    checkpointer: InMemorySaver | SqliteSaver | None = None,
    max_tool_turns: int = 3,
) -> RunResult:
    """Run the full graph for a topic and return a summary of the result."""
    if llm is None:
        llm = build_offline_llm(settings.topic) if settings.is_offline else build_llm(settings)
    if tools is None:
        tools = OFFLINE_TOOLS if settings.is_offline else DEFAULT_TOOLS
    if checkpointer is None:
        checkpointer = build_checkpointer(settings.checkpointer, settings.sqlite_path)

    graph = build_graph(
        llm=llm,
        tools=tools,
        checkpointer=checkpointer,
        max_iterations=settings.max_iterations,
        max_tool_turns=max_tool_turns,
        output_dir=settings.output_dir,
        model_name=settings.model,
    )
    thread_id = settings.thread_id or f"{slugify(settings.topic)}-{uuid4().hex[:8]}"
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.max_steps,
    }
    started = time.perf_counter()
    final_state = graph.invoke(
        {
            "topic": settings.topic,
            "model": settings.model,
            "messages": [],
            "sources": [],
            "rounds": 0,
            "tool_turns": 0,
            "pending_queries": [],
            "used_queries": [],
        },
        config,
    )
    elapsed = time.perf_counter() - started
    messages = final_state.get("messages", [])
    LOGGER.info("Run finished in %.1fs", elapsed)
    return RunResult(
        topic=settings.topic,
        model=settings.model,
        output_path=final_state.get("output_path", ""),
        report=final_state.get("final_report", ""),
        sources=list(final_state.get("sources", [])),
        rounds=int(final_state.get("rounds", 0)),
        usage=_aggregate_usage(messages),
        thread_id=thread_id,
        elapsed_seconds=elapsed,
    )
