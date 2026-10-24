"""Prompts for each stage of the research graph."""

from __future__ import annotations

import json
from typing import Any

from .state import Source

PLANNER_SYSTEM = """\
You are the planning stage of a careful research agent. Break the user's topic into a
small set of answerable sub-questions and the web search queries needed to answer them.

Return ONLY a JSON object, with no prose and no markdown fences:
{"questions": ["..."], "search_queries": ["..."]}

Rules:
- 2 to 4 questions, each focused and answerable from public sources.
- 2 to 4 search queries. Each must be a self-contained web search query, not a URL.
- Prefer queries that surface primary sources, recent reporting, and skeptical analysis.
"""

CRITIC_SYSTEM = """\
You are the critique stage of a research agent. You receive the plan, the evidence
gathered so far, and the researcher's findings. Decide whether the evidence is good
enough to write a trustworthy digest.

Return ONLY a JSON object, with no prose and no markdown fences:
{"sufficient": true|false, "gaps": ["..."], "follow_up_queries": ["..."], "reason": "..."}

Rules:
- Mark sufficient only when every planned question is addressed by concrete evidence.
- If something important is missing or only one source supports a claim, set
  sufficient to false and propose at most 2 follow_up_queries.
- Never invent facts; judge only the supplied evidence.
"""

WRITER_SYSTEM = """\
You are the writing stage of a research agent. Produce a compact, well-structured
Markdown digest using ONLY the numbered sources and evidence supplied. Cite claims as
[n] where n is a source number. Never invent URLs, statistics, or quotes.

Output Markdown only: no code fences, no preamble, no closing remarks.
Use exactly these sections:

## TL;DR
Three to five bullet points.

## Key findings
Grouped bullets. Every non-obvious claim carries one or more [n] citations.

## Uncertainties and conflicting claims
What the evidence does not settle, plus any disagreements between sources.

## Open questions
What a follow-up round of research should investigate.
"""

RESEARCHER_SYSTEM = """\
You are the research stage of a research agent. Work through the assigned queries by
calling tools:

1. Call `web_search` for a query and read the returned titles, URLs, and snippets.
2. Call `fetch_page` on the one or two most promising URLs to read the actual content.
3. Repeat for the remaining queries if needed.

Only use information returned by the tools. Do not rely on memory. When you have
enough evidence to answer the plan's questions, stop calling tools and reply with a
short evidence summary: one bullet per finding, each ending with its source URL.
"""


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def planner_task(topic: str) -> str:
    return f"Research topic: {topic}"


def research_task(
    topic: str,
    questions: list[str],
    queries: list[str],
    used_queries: list[str],
) -> str:
    if queries:
        assignment = "Search and read sources for these queries now:\n" + "\n".join(
            f"- {query}" for query in queries
        )
    else:
        assignment = (
            "No new queries are assigned. Summarize the evidence already collected and "
            "call tools only if a planned question is still unanswered."
        )
    return (
        f"Research topic: {topic}\n\n"
        f"Plan questions:\n{_json(questions)}\n\n"
        f"Queries already run:\n{_json(used_queries)}\n\n"
        f"{assignment}"
    )


def critique_task(
    topic: str,
    plan: dict[str, Any],
    sources: list[Source],
    findings: str,
    round_number: int,
    max_rounds: int,
) -> str:
    evidence = "\n".join(
        f"- {source['title']} ({source['url']}): {source['snippet']}" for source in sources
    )
    return (
        f"Research topic: {topic}\n"
        f"Round: {round_number} of {max_rounds}\n\n"
        f"Plan:\n{_json(plan)}\n\n"
        f"Sources gathered ({len(sources)}):\n{evidence or '(none)'}\n\n"
        f"Researcher findings:\n{findings or '(none)'}"
    )


def writer_task(
    topic: str,
    plan: dict[str, Any],
    sources: list[Source],
    evidence: str,
    critique: dict[str, Any],
) -> str:
    numbered = "\n".join(
        f"[{index}] {source['title']} - {source['url']}"
        for index, source in enumerate(sources, start=1)
    )
    return (
        f"Research topic: {topic}\n\n"
        f"Plan:\n{_json(plan)}\n\n"
        f"Numbered sources:\n{numbered or '(no sources)'}\n\n"
        f"Evidence excerpts:\n{evidence or '(no evidence)'}\n\n"
        f"Critique to address:\n{_json(critique)}\n\n"
        "Write the digest now."
    )
