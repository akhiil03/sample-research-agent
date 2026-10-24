# sample-research-agent

[![research-digest](https://github.com/akhiil03/sample-research-agent/actions/workflows/agent.yml/badge.svg)](https://github.com/akhiil03/sample-research-agent/actions/workflows/agent.yml)

A small, complete example of an AI agent that ships: **Python + LangGraph** for the agent,
**OpenRouter** for the model (free tier by default), and **GitHub Actions** as the host.

Give it a topic. It plans sub-questions, searches the web, reads pages, critiques its own
coverage, and writes a cited Markdown digest to `reports/`. GitHub Actions runs it on a
schedule or on demand, uploads the digest as an artifact, and commits it back to `main`.

```text
                 ┌──────────────────────────────┐
                 │           LangGraph          │
                 │                              │
START ──▶ plan ──▶ research ──▶ tools ──┐        │
              ▲        │               │        │
              │        └──(no tool calls)──▶ critique
              │                              │  │
              └──────── follow-ups ──────────┘  │
                                     sufficient │ capped
                                                ▼
                                        write ──▶ save ──▶ END
```

## Why this exists

Most LangGraph demos end at `graph.invoke()` in a notebook. This one shows the rest of the
story: configuration, tool sandboxing, tests that never touch the network, a bounded
reasoning loop, a CLI, and a GitHub Actions workflow that produces a real artifact and
commits it back to the repo.

## Quickstart

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and an
[OpenRouter API key](https://openrouter.ai/settings/keys) for live runs.

```bash
uv sync --extra dev
cp .env.example .env          # then put your key in OPENROUTER_API_KEY
uv run research-agent "small language models"
```

The digest lands in `reports/YYYY-MM-DD-small-language-models.md`, with YAML frontmatter,
sections for TL;DR / key findings / uncertainties / open questions, and a numbered source list.

### Offline demo (no key, no network)

```bash
AGENT_FAKE_MODEL=1 uv run research-agent "small language models" --out reports
```

This swaps in a scripted model and deterministic tools so you can see the full graph, CLI
output, and Markdown formatting without spending a request. It is also how CI tests run.

## CLI

```text
research-agent TOPIC [options]

  -o, --out DIR            Output directory (default: reports)
  -m, --model ID           OpenRouter model id (default: openrouter/free)
      --max-iterations N   Research/critique rounds, 1-5 (default: 2)
      --max-steps N        LangGraph recursion limit, 10-200 (default: 40)
      --checkpointer KIND  memory | sqlite (default: memory)
      --sqlite-path PATH   Checkpoint database path for sqlite mode
      --thread-id ID       Reuse a thread to resume/inspect a run
      --json               Print a machine-readable run summary
  -v, --verbose            Debug logging
```

Exit codes: `0` success, `2` configuration error, `3` run failure, `130` interrupted.

## How the graph works

| Node | What it does |
| --- | --- |
| `plan` | Asks the model for 2-4 sub-questions and 2-4 search queries as JSON (with a deterministic fallback if the model returns junk). |
| `research` | A tool-calling turn: binds `web_search` and `fetch_page`, executes any requested tools, then summarizes findings with source URLs. |
| `tools` | LangGraph's `ToolNode`; runs the requested tools and appends `ToolMessage`s. |
| `critique` | Judges whether the plan's questions are answered. Returns JSON with `sufficient`, `gaps`, and up to 2 follow-up queries. |
| `write` | Writes the digest from a bounded evidence brief and a numbered source list, so citations are stable. |
| `save` | Adds frontmatter, guarantees a Sources section, and writes `reports/<date>-<slug>.md`. |

The loop is bounded in three places: `--max-iterations` (critique rounds),
`--max-steps` (LangGraph recursion limit), and a hard cap on evidence passed to the writer.
The critique also cannot stall: if it asks for more research but proposes no follow-up
queries, the graph proceeds to `write`.

State is persisted with LangGraph checkpointers. `--checkpointer sqlite` writes to
`.agent/checkpoints.sqlite`, so a failed or interrupted run can be inspected or resumed
with the same `--thread-id`.

## Tools and safety

- `web_search` uses [ddgs](https://pypi.org/project/ddgs/) (DuckDuckGo) with retries and no
  API key, returning `{title, url, snippet}` JSON.
- `fetch_page` fetches HTML with `httpx`, extracts main text with `trafilatura`, caps the
  response at 2 MB, and truncates extracted text.
- **SSRF guard**: only `http`/`https` are allowed; hostnames are resolved and rejected if
  they map to private, loopback, link-local, reserved, or multicast addresses. Redirects
  are followed manually and every hop is re-validated. `localhost`, `*.local`, `*.internal`,
  and cloud metadata hostnames are blocked by name as well. DNS rebinding is out of scope
  for this sample.
- Tool failures are returned to the model as structured `{"error": ...}` JSON instead of
  crashing the run.

## GitHub Actions hosting

The workflow in `.github/workflows/agent.yml` has two jobs:

1. **`test`** runs on every push and pull request: `ruff check`, `ruff format --check`, and
   `pytest` with `AGENT_FAKE_MODEL=1`. It needs no secrets, so fork PRs are safe.
2. **`digest`** runs on `workflow_dispatch` and the weekly `schedule` (Mondays 13:00 UTC),
   after `test` passes. It runs the agent with your OpenRouter key, uploads `reports/` as an
   artifact, and commits new digests to `main` with `[skip ci]`.

### One-time setup

```bash
# 1. Add the model key as a repository secret
gh secret set OPENROUTER_API_KEY --repo OWNER/REPO

# 2. Pick the topic used by the weekly schedule (optional)
gh variable set DIGEST_TOPIC --body "small language models" --repo OWNER/REPO
gh variable set DIGEST_MODEL --body "openrouter/free" --repo OWNER/REPO
```

Then trigger a run:

```bash
gh workflow run research-digest.yml --repo OWNER/REPO -f topic="small language models"
gh run watch --repo OWNER/REPO
```

The workflow needs **Read and write permissions** for `GITHUB_TOKEN` to commit the digest
(Settings → Actions → General → Workflow permissions). If `main` is protected, allow the
`github-actions[bot]` to bypass the rule or switch the commit step to a pull request.

The workflow passes `--checkpointer sqlite`; the database lives in `.agent/`, which is
git-ignored, so each run starts from an empty checkpoint store unless you upload it as an
artifact or cache it yourself.

### Scheduled runs caveat

GitHub disables `schedule` triggers after roughly 60 days without repository activity, and
cron runs can be delayed during peak load. Use `workflow_dispatch` for anything important.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Required for live runs. |
| `AGENT_MODEL` | `openrouter/free` | Any OpenRouter model id. |
| `AGENT_FAKE_MODEL` | unset | `1` runs the offline scripted model + fake tools. |
| `AGENT_MAX_ITERATIONS` | `2` | Default research/critique rounds (1-5). |
| `AGENT_MAX_STEPS` | `40` | Default recursion limit (10-200). |
| `AGENT_OUTPUT_DIR` | `reports` | Default output directory. |
| `AGENT_SQLITE_PATH` | `.agent/checkpoints.sqlite` | Default checkpoint database. |
| `OPENROUTER_APP_TITLE` | unset | Attribution header on your OpenRouter dashboard. |
| `LANGSMITH_API_KEY` / `LANGSMITH_TRACING` | unset | Optional LangSmith tracing. |

### About `openrouter/free`

`openrouter/free` auto-routes to a free model that supports tool calling, which keeps the
demo free. Free tiers are rate-limited (roughly 50 requests/day without account credit) and
can be slower or less reliable than paid models. The agent makes a handful of calls per run,
and retries are handled by `langchain-openrouter` plus the search tool. If you hit `429`s,
switch `AGENT_MODEL` to a paid model id or lower `--max-iterations`.

## Project layout

```text
src/research_agent/
  cli.py       argparse CLI, exit codes, logging
  config.py    settings resolution + validation
  graph.py     nodes, routing, checkpointers, report writing
  llm.py       ChatOpenRouter factory + offline scripted model
  prompts.py   stage prompts and task builders
  state.py     ResearchState, Source, RunResult
  tools.py     web_search, fetch_page, SSRF guard, offline tools
tests/
  test_graph.py    end-to-end graph runs, iteration cap, SQLite checkpoints
  test_tools.py    SSRF, extraction, truncation, error handling
  test_parsing.py  JSON extraction, report shaping, evidence budget
  test_cli.py      exit codes, offline run, validation
```

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format .
uv run pytest -q
uv run pytest -q -m network   # optional live-network tests (none yet)
```

## Example digest

See the files in `reports/` after your first run. To try the GitHub-hosted flow end to end:

```bash
gh workflow run research-digest.yml -f topic="retrieval augmented generation" -f max_iterations=2
```

## Ideas for extending this sample

- Add a `wikipedia_lookup` or Tavily tool and let the critic choose between providers.
- Swap the digest writer for a structured Pydantic output and render HTML/PDF.
- Publish digests as GitHub Issues or to a static site instead of committing Markdown.
- Replace the weekly topic with a list from a repo variable and fan out with a matrix job.
- Add LangSmith tracing or OpenTelemetry for production-grade observability.

## License

MIT
