"""Shared test doubles: a scripted chat model and deterministic tools."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, tool


class ScriptedModel(BaseChatModel):
    """Returns pre-built messages in order, ignoring the prompt."""

    responses: list[AIMessage]
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-test-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.cursor >= len(self.responses):
            raise AssertionError(
                f"Scripted model ran out of responses after {self.cursor} calls; "
                "the graph made more model calls than expected."
            )
        message = self.responses[self.cursor]
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def scripted(*responses: AIMessage) -> ScriptedModel:
    return ScriptedModel(responses=list(responses))


def plan_message(queries: list[str] | None = None) -> AIMessage:
    queries = queries or ["test topic overview"]
    return AIMessage(
        content=json.dumps(
            {
                "questions": ["What is the state of the topic?"],
                "search_queries": queries,
            }
        )
    )


def tool_call_message(*calls: tuple[str, dict[str, Any]]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{index}", "type": "tool_call"}
            for index, (name, args) in enumerate(calls, start=1)
        ],
    )


def summary_message(text: str = "- A finding (https://example.com/a).") -> AIMessage:
    return AIMessage(content=text)


def critique_message(sufficient: bool = True, follow_ups: list[str] | None = None) -> AIMessage:
    return AIMessage(
        content=json.dumps(
            {
                "sufficient": sufficient,
                "gaps": [] if sufficient else ["more evidence needed"],
                "follow_up_queries": follow_ups or [],
                "reason": "scripted critique",
            }
        )
    )


def digest_message() -> AIMessage:
    return AIMessage(
        content=(
            "## TL;DR\n\n- A concise finding [1].\n\n"
            "## Key findings\n\n- Evidence supports the claim [1][2].\n\n"
            "## Uncertainties and conflicting claims\n\n- Sources disagree slightly [2].\n\n"
            "## Open questions\n\n- What comes next?\n"
        )
    )


@tool("web_search")
def stub_search(query: str, max_results: int = 5) -> str:
    """Search the web (test double)."""
    return json.dumps(
        [
            {
                "title": f"{query} overview",
                "url": "https://example.com/a",
                "snippet": "First result snippet.",
            },
            {
                "title": f"{query} critique",
                "url": "https://example.org/b",
                "snippet": "Second result snippet.",
            },
        ]
    )


@tool("fetch_page")
def stub_fetch(url: str, max_chars: int = 6000) -> str:
    """Read a page (test double)."""
    return json.dumps(
        {
            "url": url,
            "title": "Fetched page",
            "text": "Fetched body text with enough detail to be useful.",
            "truncated": False,
        }
    )


STUB_TOOLS: list[BaseTool] = [stub_search, stub_fetch]
