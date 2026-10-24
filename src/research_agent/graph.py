"""The LangGraph research pipeline: plan -> research <-> tools -> critique -> write."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field, ValidationError, field_validator

from . import prompts
from .config import Settings
from .llm import build_llm, build_offline_llm
from .state import ResearchState, RunResult, Source
from .tools import DEFAULT_TOOLS, OFFLINE_TOOLS, collect_sources

LOGGER = logging.getLogger(__name__)
MAX_EVIDENCE_CHARS = 24_000
EventSink = Callable[[dict[str, Any]], None]


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


def _raw_text(raw: Any) -> str:
    """Best-effort textual view of whatever a stage invocation returned."""
    if isinstance(raw, str):
        return raw
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        return content
    return message_text(content)


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


def _string_list_value(value: Any) -> Any:
    """Pydantic mode="before" validator: accepts a bare string or a list of items."""
    return _string_list(value)


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class PlanResponse(BaseModel):
    """Structured plan returned by the planner stage."""

    questions: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)

    @field_validator("questions", "search_queries", mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        return _string_list(value)


class CritiqueResponse(BaseModel):
    """Structured verdict returned by the critique stage."""

    sufficient: bool = False
    gaps: list[str] = Field(default_factory=list)
    follow_up_queries: list[str] = Field(default_factory=list)
    reason: str = ""

    @field_validator("gaps", "follow_up_queries", mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        return _string_list(value)


class VerificationResponse(BaseModel):
    """Structured verdict returned by the verification stage."""

    verdict: Literal["pass", "revise"] = "pass"
    unsupported_claims: list[str] = Field(default_factory=list)
    citation_issues: list[str] = Field(default_factory=list)

    @field_validator("unsupported_claims", "citation_issues", mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        return _string_list(value)


def _coerce(schema: type[SchemaT], data: Any) -> SchemaT | None:
    """Validate a model instance or a (possibly messy) dict against the schema."""
    if isinstance(data, schema):
        return data
    if not isinstance(data, dict):
        return None
    try:
        return schema.model_validate(data)
    except (ValidationError, ValueError):
        return None


def _attempted_fetch_urls(messages: Sequence[Any]) -> set[str]:
    """URLs for which any AIMessage (model or fetch gate) already requested fetch_page."""
    attempted: set[str] = set()
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls or []:
            if call.get("name") != "fetch_page":
                continue
            url = str((call.get("args") or {}).get("url") or "").strip()
            if url:
                attempted.add(url)
    return attempted


def _gate_fetch_url(
    *,
    sources: list[Source],
    tool_turns: int,
    max_tool_turns: int,
    attempted_urls: set[str],
) -> str | None:
    """Pick a page to auto-fetch so the digest is grounded in page-level evidence."""
    if any(source["kind"] == "page" for source in sources):
        return None
    if tool_turns >= max_tool_turns:
        return None
    for source in sources:
        if source["kind"] == "search" and source["url"] not in attempted_urls:
            return source["url"]
    return None


def _strip_out_of_range_citations(text: str, total_sources: int) -> tuple[str, list[int]]:
    """Remove [n] citations that point beyond the source list; return cleaned text + numbers."""
    if not text:
        return "", []
    numbers = {int(match) for match in re.findall(r"\[(\d+)\]", text)}
    invalid = sorted(
        citation for citation in numbers if citation < 1 or citation > max(total_sources, 0)
    )
    if not invalid:
        return text, []
    invalid_set = set(invalid)

    def _drop(match: re.Match[str]) -> str:
        return "" if int(match.group(1)) in invalid_set else match.group(0)

    cleaned = re.sub(r"\[(\d+)\]", _drop, text)
    cleaned = re.sub(r"[ \t]+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned, invalid


def _invoke_schema(
    chain: Any,
    llm: BaseChatModel,
    messages: Sequence[Any],
    schema: type[SchemaT],
) -> tuple[SchemaT | None, Any]:
    """Invoke a schema-enforced chain with a plain-call fallback for messy models."""
    if chain is None:
        raw = llm.invoke(list(messages))
        return _coerce(schema, extract_json(_raw_text(raw))), raw
    try:
        result = chain.invoke(list(messages))
    except Exception:  # noqa: BLE001 - structured invocation must never kill a run
        LOGGER.warning(
            "Structured output failed for %s; falling back to plain JSON", schema.__name__
        )
        raw = llm.invoke(list(messages))
        return _coerce(schema, extract_json(_raw_text(raw))), raw
    if not isinstance(result, dict):
        return None, result
    raw = result.get("raw")
    parsed = result.get("parsed")
    if isinstance(parsed, schema):
        return parsed, raw
    coerced = _coerce(schema, extract_json(_raw_text(raw)))
    if coerced is not None:
        return coerced, raw
    return None, raw


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
    event_sink: EventSink | None = None,
    use_structured_outputs: bool = False,
) -> Any:
    """Compile the research graph. Nodes close over the model, tools, and limits."""
    active_tools = list(tools or DEFAULT_TOOLS)
    research_llm = llm.bind_tools(active_tools)
    destination = Path(output_dir)

    def schema_chain(schema: type[SchemaT]) -> Any:
        if not use_structured_outputs:
            return None
        try:
            return llm.with_structured_output(schema, include_raw=True)
        except Exception:  # noqa: BLE001 - some models cannot bind schemas
            LOGGER.warning(
                "with_structured_output unavailable for %s; using JSON parsing", schema.__name__
            )
            return None

    plan_schema_chain = schema_chain(PlanResponse)
    critique_schema_chain = schema_chain(CritiqueResponse)
    verify_schema_chain = schema_chain(VerificationResponse)

    def emit(event: dict[str, Any]) -> None:
        if event_sink is None:
            return
        try:
            event_sink(event)
        except Exception:  # noqa: BLE001 - progress reporting must never fail a run
            LOGGER.warning("Progress event sink raised", exc_info=True)

    def plan_node(state: ResearchState) -> dict[str, Any]:
        topic = state["topic"]
        parsed_model, _raw = _invoke_schema(
            plan_schema_chain,
            llm,
            [
                SystemMessage(content=prompts.PLANNER_SYSTEM),
                HumanMessage(content=prompts.planner_task(topic)),
            ],
            PlanResponse,
        )
        questions = _string_list(parsed_model.questions, limit=4) if parsed_model else []
        queries = _string_list(parsed_model.search_queries, limit=4) if parsed_model else []
        if not questions:
            questions = [
                f"What is the current state of {topic}?",
                f"What are the main limitations or open questions around {topic}?",
            ]
        if not queries:
            queries = [f"{topic} overview", f"{topic} limitations and criticism"]
        plan = {"questions": questions, "search_queries": queries}
        LOGGER.info("Planned %s questions and %s queries", len(questions), len(queries))
        emit(
            {
                "stage": "plan",
                "status": "complete",
                "questions": questions,
                "queries": queries,
            }
        )
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
        emit(
            {
                "stage": "research",
                "status": "started",
                "rounds": int(state.get("rounds", 0)),
                "queries": batch,
                "sources": len(state.get("sources", [])),
            }
        )
        original_messages = list(state.get("messages", []))
        response = research_llm.invoke(
            [
                SystemMessage(content=prompts.RESEARCHER_SYSTEM),
                *original_messages,
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
        messages = [*original_messages, response]
        sources = collect_sources(messages)
        tool_turns = int(state.get("tool_turns", 0)) + (1 if response.tool_calls else 0)
        LOGGER.info(
            "Research turn: %s tool call(s), %s source(s) collected",
            len(response.tool_calls),
            len(sources),
        )

        gate_url = None
        if not response.tool_calls:
            gate_url = _gate_fetch_url(
                sources=sources,
                tool_turns=tool_turns,
                max_tool_turns=max_tool_turns,
                attempted_urls=_attempted_fetch_urls(original_messages),
            )
        if gate_url is not None:
            LOGGER.info("Fetch gate: requesting fetch_page(%s)", gate_url)
            messages = [
                *messages,
                AIMessage(
                    content=f"(fetch gate) Reading {gate_url} to ground the digest in page text.",
                    additional_kwargs={"gate_fetch": True},
                    tool_calls=[
                        {
                            "name": "fetch_page",
                            "args": {"url": gate_url},
                            "id": f"gate_fetch_{uuid4().hex[:8]}",
                            "type": "tool_call",
                        }
                    ],
                ),
            ]
            tool_turns += 1
            emit(
                {
                    "stage": "fetch",
                    "status": "started",
                    "url": gate_url,
                    "sources": len(sources),
                    "rounds": int(state.get("rounds", 0)),
                }
            )

        update: dict[str, Any] = {
            "messages": messages[len(original_messages) :],
            "pending_queries": [],
            "used_queries": used,
            "sources": sources,
            "tool_turns": tool_turns,
        }
        if response.tool_calls or gate_url is not None:
            update["notes"] = "gathering evidence"
        emit(
            {
                "stage": "research",
                "status": "complete",
                "tool_calls": len(response.tool_calls),
                "sources": len(sources),
                "rounds": int(state.get("rounds", 0)),
            }
        )
        return update

    def critique_node(state: ResearchState) -> dict[str, Any]:
        rounds = int(state.get("rounds", 0)) + 1
        sources = list(state.get("sources", []))
        emit(
            {
                "stage": "critique",
                "status": "started",
                "round": rounds,
                "sources": len(sources),
            }
        )
        parsed_model, raw = _invoke_schema(
            critique_schema_chain,
            llm,
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
            ],
            CritiqueResponse,
        )
        if parsed_model is not None:
            sufficient = bool(parsed_model.sufficient)
            fallback_gaps = _string_list(parsed_model.gaps, limit=5)
            fallback_followups = _string_list(parsed_model.follow_up_queries, limit=2)
        else:
            sufficient = bool(sources)
            fallback_gaps = ["critique response was not valid JSON"]
            fallback_followups = []
            reason = _raw_text(raw)[:500] if raw is not None else ""
        follow_ups = [] if sufficient or rounds >= max_iterations else fallback_followups
        LOGGER.info("Critique round %s: sufficient=%s", rounds, sufficient)
        gaps = fallback_gaps
        emit(
            {
                "stage": "critique",
                "status": "complete",
                "round": rounds,
                "sufficient": sufficient,
                "gaps": gaps,
                "follow_up_queries": follow_ups,
            }
        )
        return {
            "critique": {
                "sufficient": sufficient,
                "gaps": gaps,
                "follow_up_queries": follow_ups,
                "reason": str(parsed_model.reason)[:800] if parsed_model else str(reason)[:800],
            },
            "rounds": rounds,
            "pending_queries": follow_ups,
            "tool_turns": 0,
        }

    def write_node(state: ResearchState) -> dict[str, Any]:
        sources = list(state.get("sources", []))
        emit(
            {
                "stage": "write",
                "status": "started",
                "sources": len(sources),
                "rounds": int(state.get("rounds", 0)),
                "write_passes": int(state.get("write_passes", 0)) + 1,
            }
        )
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
                        state.get("verification") or {},
                    )
                ),
            ]
        )
        report = _ensure_report_shape(message_text(response.content), state["topic"], sources)
        emit(
            {
                "stage": "write",
                "status": "complete",
                "write_passes": int(state.get("write_passes", 0)) + 1,
                "sources": len(sources),
                "chars": len(report),
            }
        )
        return {
            "final_report": report,
            "messages": [response],
            "write_passes": int(state.get("write_passes", 0)) + 1,
        }

    def verify_node(state: ResearchState) -> dict[str, Any]:
        sources = list(state.get("sources", []))
        report = state.get("final_report", "")
        emit(
            {
                "stage": "verify",
                "status": "started",
                "write_passes": int(state.get("write_passes", 0)),
                "sources": len(sources),
            }
        )
        cleaned, dropped = _strip_out_of_range_citations(report, len(sources))
        unsupported: list[str] = []
        citation_notes: list[str] = []
        verdict = "pass"
        if verify_schema_chain is not None and sources:
            parsed_model, _raw = _invoke_schema(
                verify_schema_chain,
                llm,
                [
                    SystemMessage(content=prompts.VERIFY_SYSTEM),
                    HumanMessage(
                        content=prompts.verify_task(
                            state["topic"],
                            cleaned,
                            build_numbered_sources(sources),
                        )
                    ),
                ],
                VerificationResponse,
            )
            if parsed_model is not None:
                unsupported = _string_list(parsed_model.unsupported_claims, limit=5)
                citation_notes = _string_list(parsed_model.citation_issues, limit=5)
                verdict = "revise" if parsed_model.verdict == "revise" else "pass"
        if verdict == "revise" and not unsupported and not citation_notes:
            verdict = "pass"
        revise = verdict == "revise" and int(state.get("write_passes", 0)) <= 1
        verification = {
            "verdict": verdict,
            "unsupported_claims": unsupported,
            "citation_issues": citation_notes,
            "dropped_citations": dropped,
            "repaired": bool(dropped),
            "revised": revise,
        }
        emit(
            {
                "stage": "verify",
                "status": "complete",
                "verdict": verdict,
                "unsupported": len(unsupported),
                "dropped": len(dropped),
                "revised": revise,
                "sources": len(sources),
            }
        )
        return {"final_report": cleaned, "verification": verification}

    def route_after_verify(state: ResearchState) -> str:
        if (
            state.get("verification", {}).get("verdict") == "revise"
            and int(state.get("write_passes", 0)) <= 1
        ):
            return "write"
        return "save"

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
        emit(
            {
                "stage": "save",
                "status": "complete",
                "output_path": str(path),
                "rounds": int(state.get("rounds", 0)),
                "sources": len(state.get("sources", [])),
            }
        )
        return {"output_path": str(path)}

    def route_after_research(state: ResearchState) -> str:
        messages = state.get("messages", [])
        if messages:
            last = messages[-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                if last.additional_kwargs.get("gate_fetch"):
                    return "tools"
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
    tool_executor = ToolNode(active_tools)

    def tools_node(state: ResearchState) -> dict[str, Any]:
        result = tool_executor.invoke(state)
        emit(
            {
                "stage": "tools",
                "status": "complete",
                "results": len(result.get("messages", [])),
            }
        )
        return result

    builder.add_node("plan", plan_node)
    builder.add_node("research", research_node)
    builder.add_node("tools", tools_node)
    builder.add_node("critique", critique_node)
    builder.add_node("write", write_node)
    builder.add_node("verify", verify_node)
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
    builder.add_edge("write", "verify")
    builder.add_conditional_edges("verify", route_after_verify, {"write": "write", "save": "save"})
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
    use_structured_outputs: bool | None = None,
    event_sink: EventSink | None = None,
) -> RunResult:
    """Run the full graph for a topic and return a summary of the result."""
    if llm is None:
        llm = build_offline_llm(settings.topic) if settings.is_offline else build_llm(settings)
    if tools is None:
        tools = OFFLINE_TOOLS if settings.is_offline else DEFAULT_TOOLS
    if checkpointer is None:
        checkpointer = build_checkpointer(settings.checkpointer, settings.sqlite_path)
    structured = (
        (not settings.is_offline) if use_structured_outputs is None else use_structured_outputs
    )

    graph = build_graph(
        llm=llm,
        tools=tools,
        checkpointer=checkpointer,
        max_iterations=settings.max_iterations,
        max_tool_turns=max_tool_turns,
        output_dir=settings.output_dir,
        model_name=settings.model,
        event_sink=event_sink,
        use_structured_outputs=structured,
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
            "write_passes": 0,
            "verification": {},
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
