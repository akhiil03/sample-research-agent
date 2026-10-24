# sample-research-agent

[![research-digest](https://github.com/akhiil03/sample-research-agent/actions/workflows/agent.yml/badge.svg)](https://github.com/akhiil03/sample-research-agent/actions/workflows/agent.yml)

A small, complete example of an AI agent that ships: **Python + LangGraph** for the agent,
**Google Gemini** for the model (free tier by default), and **GitHub Actions** as the host. An
optional **Next.js + FastAPI** web UI runs the same agent interactively and shows live
progress.

Give it a topic. It plans sub-questions, searches the web, reads pages, critiques its own
coverage, and writes a cited Markdown digest to `reports/`. GitHub Actions runs it on a
schedule or on demand, uploads the digest as an artifact, and commits it back to `main`.

```text
                       ┌────────────────────────────────┐
                       │            LangGraph           │
START ──▶ plan ──▶ research ──▶ tools ──┐        │
              ▲        │            │   │        │
              │        │            └───┼────────┤  (tool calls loop back)
              │        │                │        │
              │        └──(no tool calls)──▶ critique
              │                                 │  │
              └──────── follow-ups ─────────────┘  │
                                      sufficient │ capped
                                                 ▼
                                        write ──▶ verify ──▶ save ──▶ END
                                            ▲        │
                                            └──revise┘ (one repair pass)
```

The `verify` node strips `[n]` citations that point beyond the source list, then asks the
model to flag claims no listed source supports; if it says "revise", the draft gets exactly
one repair pass through `write` before `save`.

## Why this exists

Most LangGraph demos end at `graph.invoke()` in a notebook. This one shows the rest of the
story: configuration, tool sandboxing, tests that never touch the network, a bounded
reasoning loop, a CLI, and a GitHub Actions workflow that produces a real artifact and
commits it back to the repo.

## Quickstart

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and a free
[Gemini API key](https://aistudio.google.com/apikey) for live runs. The optional web UI
also needs Node.js 24+.

```bash
uv sync --extra dev
cp .env.example .env          # then put your key in GEMINI_API_KEY
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
  -m, --model ID           Google Gemini or OpenRouter model id (default: $AGENT_MODEL)
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
| `research` | A tool-calling turn: binds `web_search` and `fetch_page`, executes any requested tools, then summarizes findings with source URLs. A fetch gate auto-requests one `fetch_page` when the model has search hits but no page-level evidence. |
| `tools` | LangGraph's `ToolNode`; runs the requested tools and appends `ToolMessage`s. |
| `critique` | Judges whether the plan's questions are answered. Returns JSON with `sufficient`, `gaps`, and up to 2 follow-up queries. |
| `write` | Writes the digest from a bounded evidence brief and a numbered source list, so citations are stable. |
| `verify` | Strips out-of-range `[n]` citations, then asks the model to flag unsupported claims. On "revise" the draft gets exactly one repair pass through `write`. |
| `save` | Adds frontmatter, guarantees a Sources section, and writes `reports/<date>-<slug>.md`. |

Plan and critique responses are parsed as JSON with Pydantic schemas when
`use_structured_outputs` is on (the default for live runs), falling back to plain JSON
extraction when a provider cannot honor schemas — so scripted and offline runs behave
identically.

The loop is bounded in four places: `--max-iterations` (critique rounds),
`--max-steps` (LangGraph recursion limit), a hard cap of three tool-calling turns per
research round (the fetch gate counts as a turn), and a cap on the evidence passed to the
writer. The critique also cannot stall: if it asks for more research but proposes no
follow-up queries, the graph proceeds to `write`.

State is persisted with LangGraph checkpointers. `--checkpointer sqlite` writes to
`.agent/checkpoints.sqlite`, so a failed or interrupted run can be inspected or resumed
with the same `--thread-id`.

## Web UI (Next.js + FastAPI)

The repo ships a two-tier UI: a FastAPI service that runs the same `run_research` graph and
a Next.js App Router frontend that starts runs and polls them for progress.

```text
Next.js (web/, :3000) ── JSON/HTTP ──▶ FastAPI (:8000) ── invoke ──▶ LangGraph
```

### Run it locally

Terminal 1 — API:

```bash
uv sync --extra dev
uv run uvicorn research_agent.api:app --reload --port 8000
```

Terminal 2 — web:

```bash
cd web
npm install
cp .env.example .env.local   # optional; defaults to http://localhost:8000
npm run dev
```

Open <http://localhost:3000>. To demo without a key, start the API with
`AGENT_FAKE_MODEL=1`; the UI shows an "Offline demo" badge and uses the scripted model.

### API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness, default model, offline/key state |
| `POST` | `/api/runs` | Start a run (`{topic, model?, max_iterations?}`), returns `202` |
| `GET` | `/api/runs` | Recent runs in this server process |
| `GET` | `/api/runs/{id}` | Status, stage, events, sources, report |
| `GET` | `/api/runs/{id}/report` | Markdown download (`409` until the report exists) |

```bash
curl -s localhost:8000/api/runs -H 'content-type: application/json' \
  -d '{"topic":"small language models","max_iterations":1}' | jq
```

The agent emits progress events (`plan`, `research`, `tools`, `fetch`, `critique`, `write`,
`verify`, `save`)
through an optional `event_sink`; the API stores them per run and the UI polls every 1.5 s.

Operational notes: run state is in memory (restarting the API clears history), agent work
executes in a two-worker thread pool, and there is no authentication — bind it to localhost
or add your own auth before exposing it. Use a single uvicorn worker, since state is
per-process. CORS defaults to `http://localhost:3000`; set `WEB_ORIGIN` (comma-separated) for
other origins.

Frontend: `web/app/page.tsx` owns state and polling; `ResearchForm`, `RunProgress`,
`DigestView`, and `RecentRuns` are the components; the typed API client is `web/lib/api.ts`.
Markdown is rendered with `react-markdown` + `remark-gfm` without raw HTML.

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

The workflow in `.github/workflows/agent.yml` has three jobs:

1. **`test`** runs on every push and pull request: `ruff check`, `ruff format --check`, and
   `pytest` with `AGENT_FAKE_MODEL=1`. It needs no secrets, so fork PRs are safe.
2. **`web`** runs on every push and pull request: `npm ci`, `tsc --noEmit`, and
   `next build` in `web/`.
3. **`digest`** runs on `workflow_dispatch` and the weekly `schedule` (Mondays 13:00 UTC),
   after `test` passes. It runs the agent with your Gemini key, uploads `reports/` as an
   artifact, and commits new digests to `main` with `[skip ci]`.

### One-time setup

```bash
# 1. Add the model key as a repository secret
gh secret set GEMINI_API_KEY --repo OWNER/REPO

# 2. Pick the topic used by the weekly schedule (optional)
gh variable set DIGEST_TOPIC --body "small language models" --repo OWNER/REPO
gh variable set DIGEST_MODEL --body "gemini-3.5-flash-lite" --repo OWNER/REPO
```

Then trigger a run:

```bash
gh workflow run agent.yml --repo OWNER/REPO -f topic="small language models"
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
| `GEMINI_API_KEY` | — | Required for live runs (or `GOOGLE_API_KEY`). |
| `AGENT_PROVIDER` | `google` | `google` (Gemini API) or `openrouter` (needs `OPENROUTER_API_KEY`). |
| `AGENT_MODEL` | `gemini-3.5-flash-lite` | Any Google Gemini or OpenRouter model id. |
| `AGENT_FAKE_MODEL` | unset | `1` runs the offline scripted model + fake tools. |
| `AGENT_MAX_ITERATIONS` | `2` | Default research/critique rounds (1-5). |
| `AGENT_MAX_STEPS` | `40` | Default recursion limit (10-200). |
| `AGENT_OUTPUT_DIR` | `reports` | Default output directory. |
| `AGENT_SQLITE_PATH` | `.agent/checkpoints.sqlite` | Default checkpoint database. |
| `OPENROUTER_API_KEY` | unset | Only needed when `AGENT_PROVIDER=openrouter`. |
| `LANGSMITH_API_KEY` / `LANGSMITH_TRACING` | unset | Optional LangSmith tracing. |
| `WEB_ORIGIN` | `http://localhost:3000,http://127.0.0.1:3000` | Allowed CORS origins for the API. |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | API base URL baked into the web build. |

### About free Gemini models

The free tier of the Gemini API gives you free input and output tokens with per-minute and
per-day rate limits. `gemini-3.5-flash-lite` is the recommended default for new projects;
`gemini-3.8-flash` and the `gemini-2.5-flash` family are also free-tier options with tool
calling (the agent needs it). Free tiers are rate-limited, can be slower than paid models,
and occasionally time out. The agent caps each request at 90 seconds with two retries,
bounds the tool loop, and fails the run cleanly if the provider stays unavailable. If you
hit `429`s or repeated timeouts, switch `AGENT_MODEL` to another free-tier model, a paid
model, or lower `--max-iterations`.

## Project layout

```text
src/research_agent/
  api.py       FastAPI app, run registry, progress events
  cli.py       argparse CLI, exit codes, logging
  config.py    settings resolution + validation
  graph.py     nodes, routing, checkpointers, report writing
  llm.py       Chat model factories (Gemini / OpenRouter) + offline scripted model
  prompts.py   stage prompts and task builders
  state.py     ResearchState, Source, RunResult
  tools.py     web_search, fetch_page, SSRF guard, offline tools
web/
  app/         App Router pages, layout, global styles, icon
  components/  ResearchForm, RunProgress, DigestView, RecentRuns
  lib/         typed API client and helpers
tests/
  test_api.py          FastAPI lifecycle, validation, failures, CORS-adjacent flow
  test_graph.py        end-to-end graph runs, iteration cap, SQLite checkpoints
  test_graph_limits.py tool-turn cap + progress events
  test_tools.py        SSRF, extraction, truncation, error handling
  test_parsing.py      JSON extraction, report shaping, evidence budget
  test_cli.py          exit codes, offline run, validation
  test_llm.py          timeout/retry config, offline model
```

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format .
uv run pytest -q
uv run pytest -q -m network   # optional live-network tests (none yet)

cd web
npm run typecheck
npm run build
```

## Example digest

See the files in `reports/` after your first run. To try the GitHub-hosted flow end to end:

```bash
gh workflow run agent.yml -f topic="retrieval augmented generation" -f max_iterations=2
```

## Ideas for extending this sample

- Add a `wikipedia_lookup` or Tavily tool and let the critic choose between providers.
- Swap the digest writer for a structured Pydantic output and render HTML/PDF.
- Publish digests as GitHub Issues or to a static site instead of committing Markdown.
- Replace the weekly topic with a list from a repo variable and fan out with a matrix job.
- Add LangSmith tracing or OpenTelemetry for production-grade observability.

## License

MIT
