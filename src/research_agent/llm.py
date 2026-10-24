"""Chat model factories: Google Gemini (free tier) or OpenRouter, plus a scripted offline model."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openrouter import ChatOpenRouter

from .config import Settings


def build_llm(settings: Settings) -> BaseChatModel:
    """Create the chat model used by every node in the graph."""
    if settings.provider == "google":
        return ChatGoogleGenerativeAI(
            model=settings.model,
            google_api_key=settings.api_key or None,
            temperature=0.2,
            max_output_tokens=4096,
            max_retries=2,
        )
    return ChatOpenRouter(
        model=settings.model,
        api_key=settings.api_key,
        temperature=0.2,
        max_tokens=4096,
        max_retries=2,
        # ChatOpenRouter's `timeout` alias is in milliseconds.
        timeout=90_000,
        app_title="sample-research-agent",
        session_id=settings.thread_id or None,
    )


class OfflineChatModel(BaseChatModel):
    """Replays a fixed script of AI messages so the graph runs without an API key."""

    responses: list[AIMessage]
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "offline-scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> OfflineChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.cursor >= len(self.responses):
            message = AIMessage(content="Offline script exhausted.")
        else:
            message = self.responses[self.cursor]
            self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def build_offline_llm(topic: str) -> OfflineChatModel:
    """Deterministic five-step script: plan, two research turns, critique, digest."""
    plan = AIMessage(
        content=(
            '{"questions": ["What is the current state of the topic?", '
            '"What are the main limitations and open questions?"], '
            '"search_queries": ["' + topic.replace('"', "") + ' overview", '
            '"' + topic.replace('"', "") + ' limitations"]}'
        )
    )
    tool_turn = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "web_search",
                "args": {"query": f"{topic} overview", "max_results": 3},
                "id": "call_search_1",
                "type": "tool_call",
            },
            {
                "name": "fetch_page",
                "args": {"url": "https://example.com/offline-overview", "max_chars": 4000},
                "id": "call_fetch_1",
                "type": "tool_call",
            },
        ],
    )
    research_summary = AIMessage(
        content=(
            f"- {topic} has seen steady progress recently "
            "(https://example.com/offline-overview).\n"
            f"- Coverage of {topic} is uneven and several claims remain contested "
            "(https://example.org/offline-critique)."
        )
    )
    critique = AIMessage(
        content=(
            '{"sufficient": true, "gaps": [], "follow_up_queries": [], '
            '"reason": "Two independent sources cover both plan questions."}'
        )
    )
    digest = AIMessage(
        content=(
            f"## TL;DR\n\n"
            f"- {topic} is advancing quickly, but the evidence base is uneven.\n"
            f"- Most sources agree on the direction of travel, not the timeline [1].\n"
            f"- The main open questions concern measurement and real-world limits [2].\n\n"
            f"## Key findings\n\n"
            f"- Recent overviews describe steady progress in {topic} [1].\n"
            f"- Independent analysis highlights contested claims and missing benchmarks [2].\n\n"
            f"## Uncertainties and conflicting claims\n\n"
            f"- Sources disagree on how mature the field is [1][2].\n"
            f"- No source offers a rigorous, comparable evaluation.\n\n"
            f"## Open questions\n\n"
            f"- Which benchmarks actually measure progress on {topic}?\n"
            f"- Where are the strongest independent evaluations?\n"
        )
    )
    return OfflineChatModel(responses=[plan, tool_turn, research_summary, critique, digest])
