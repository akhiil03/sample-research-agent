"""Shared state and data shapes for the research graph."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class Source(TypedDict):
    """A single piece of evidence discovered during research."""

    title: str
    url: str
    snippet: str
    kind: Literal["search", "page"]


class ResearchState(TypedDict, total=False):
    """State threaded through the plan -> research -> critique -> write pipeline."""

    topic: str
    model: str
    messages: Annotated[list[AnyMessage], add_messages]
    plan: dict[str, Any]
    pending_queries: list[str]
    used_queries: list[str]
    rounds: int
    critique: dict[str, Any]
    sources: list[Source]
    final_report: str
    output_path: str
    notes: str


class RunResult:
    """Serializable summary of a completed run."""

    def __init__(
        self,
        *,
        topic: str,
        model: str,
        output_path: str,
        report: str,
        sources: list[Source],
        rounds: int,
        usage: dict[str, int],
        thread_id: str,
        elapsed_seconds: float,
    ) -> None:
        self.topic = topic
        self.model = model
        self.output_path = output_path
        self.report = report
        self.sources = sources
        self.rounds = rounds
        self.usage = usage
        self.thread_id = thread_id
        self.elapsed_seconds = elapsed_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "model": self.model,
            "output_path": self.output_path,
            "sources": self.sources,
            "source_count": len(self.sources),
            "rounds": self.rounds,
            "usage": self.usage,
            "thread_id": self.thread_id,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }
