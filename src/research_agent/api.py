"""FastAPI backend that exposes the research agent to the Next.js UI."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from .config import (
    DEFAULT_GOOGLE_MODEL,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_OPENROUTER_MODEL,
    PROVIDERS,
    ConfigError,
    Settings,
)
from .graph import run_research
from .state import RunResult

# Load the developer-facing .env from the working directory so /api/health and
# run resolution see OPENROUTER_API_KEY without waiting for the first run.
load_dotenv(dotenv_path=Path(".env"))

LOGGER = logging.getLogger(__name__)

RunStatus = Literal["queued", "running", "succeeded", "failed"]
Runner = Callable[..., RunResult]

MAX_EVENTS = 40
MAX_HISTORY = 50
DEFAULT_MAX_WORKERS = 2


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ResearchRequest(BaseModel):
    """Validated payload accepted by POST /api/runs."""

    topic: str = Field(min_length=3, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    max_iterations: int = Field(default=DEFAULT_MAX_ITERATIONS, ge=1, le=5)

    @field_validator("topic")
    @classmethod
    def _clean_topic(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("topic must be at least 3 characters")
        return cleaned

    @field_validator("model")
    @classmethod
    def _clean_model(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


@dataclass
class Run:
    """Mutable server-side state for one research run."""

    id: str
    topic: str
    model: str
    max_iterations: int
    status: RunStatus = "queued"
    stage: str = "queued"
    message: str = "Queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    rounds: int = 0
    source_count: int = 0
    sources: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    report: str = ""
    output_path: str = ""
    error: str | None = None
    elapsed_seconds: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)

    def snapshot(self, *, include_content: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "topic": self.topic,
            "model": self.model,
            "max_iterations": self.max_iterations,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "rounds": self.rounds,
            "source_count": self.source_count,
            "elapsed_seconds": self.elapsed_seconds,
        }
        if include_content:
            data.update(
                {
                    "sources": self.sources,
                    "events": self.events,
                    "report": self.report,
                    "output_path": self.output_path,
                    "error": self.error,
                    "usage": self.usage,
                }
            )
        return data


def _describe_event(event: dict[str, Any]) -> str:
    stage = event.get("stage", "")
    status = event.get("status", "")
    if stage == "plan":
        if status == "started":
            return "Planning research questions..."
        return f"Planned {len(event.get('queries', []))} search queries"
    if stage == "research":
        if status == "started":
            return "Researching the web..."
        calls = int(event.get("tool_calls", 0))
        if calls:
            return f"Gathering evidence ({calls} tool call(s), {event.get('sources', 0)} sources)"
        return f"Reviewed evidence ({event.get('sources', 0)} sources)"
    if stage == "tools":
        return f"Read {event.get('results', 0)} tool result(s)"
    if stage == "critique":
        if status == "started":
            return "Critiquing the evidence..."
        if event.get("sufficient"):
            return "Critic is satisfied with the evidence"
        return "Critic found gaps; deciding whether to research more"
    if stage == "write":
        if status == "started":
            return "Writing the digest..."
        return "Draft complete"
    if stage == "verify":
        if status == "started":
            return "Verifying the draft against sources..."
        dropped = int(event.get("dropped", 0))
        if event.get("revised"):
            return "Verification found issues; rewriting the draft"
        if dropped:
            return f"Cleaned {dropped} out-of-range citation(s)"
        return "Verification passed"
    if stage == "save":
        return "Digest saved"
    return "Working"


class ResearchService:
    """Owns the thread pool, the in-memory run registry, and progress updates."""

    def __init__(
        self,
        runner: Runner = run_research,
        *,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        self._runner = runner
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="research-run"
        )
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._order: deque[str] = deque()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def start(self, request: ResearchRequest) -> Run:
        run_id = f"run_{datetime.now(UTC).strftime('%H%M%S')}_{os.urandom(3).hex()}"
        run = Run(
            id=run_id,
            topic=request.topic,
            model=request.model or os.getenv("AGENT_MODEL") or DEFAULT_GOOGLE_MODEL,
            max_iterations=request.max_iterations,
        )
        with self._lock:
            self._runs[run_id] = run
            self._order.appendleft(run_id)
            while len(self._order) > MAX_HISTORY:
                stale = self._order[-1]
                stale_run = self._runs.get(stale)
                if stale_run is not None and stale_run.status not in {"succeeded", "failed"}:
                    break
                self._order.pop()
                self._runs.pop(stale, None)
        self._executor.submit(self._execute, run_id, request)
        return run

    def get(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def list(self, limit: int = 20) -> list[Run]:
        with self._lock:
            ids = list(self._order)[:limit]
            return [self._runs[run_id] for run_id in ids if run_id in self._runs]

    def _update(self, run_id: str, **fields: Any) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            for key, value in fields.items():
                setattr(run, key, value)

    def _on_event(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.events.append({**event, "at": _now()})
            if len(run.events) > MAX_EVENTS:
                run.events = run.events[-MAX_EVENTS:]
            stage = event.get("stage")
            if isinstance(stage, str):
                run.stage = stage
            run.message = _describe_event(event)
            if stage in {"research", "critique", "save"}:
                rounds = event.get("rounds", event.get("round"))
                if isinstance(rounds, int):
                    run.rounds = max(run.rounds, rounds)
                if isinstance(event.get("sources"), int):
                    run.source_count = max(run.source_count, int(event["sources"]))

    def _execute(self, run_id: str, request: ResearchRequest) -> None:
        started = time.perf_counter()
        self._update(run_id, status="running", started_at=_now(), message="Starting agent...")
        try:
            settings = Settings.from_env(
                request.topic,
                model=request.model,
                max_iterations=request.max_iterations,
                checkpointer="memory",
            )
        except ConfigError as exc:
            self._fail(run_id, started, str(exc))
            return

        self._update(run_id, model=settings.model)

        def sink(event: dict[str, Any]) -> None:
            self._on_event(run_id, event)

        try:
            result = self._runner(settings, event_sink=sink)
        except Exception as exc:  # noqa: BLE001 - surface any agent failure to the client
            LOGGER.exception("Research run %s failed", run_id)
            self._fail(run_id, started, f"{type(exc).__name__}: {exc}")
            return

        elapsed = round(time.perf_counter() - started, 2)
        self._update(
            run_id,
            status="succeeded",
            stage="done",
            message="Digest ready",
            finished_at=_now(),
            rounds=result.rounds,
            source_count=len(result.sources),
            sources=list(result.sources),
            report=result.report,
            output_path=result.output_path,
            elapsed_seconds=elapsed,
            usage=result.usage,
        )

    def _fail(self, run_id: str, started: float, message: str) -> None:
        self._update(
            run_id,
            status="failed",
            stage="failed",
            message="Run failed",
            error=message,
            finished_at=_now(),
            elapsed_seconds=round(time.perf_counter() - started, 2),
        )


def create_app(service: ResearchService | None = None) -> FastAPI:
    """Build the API app. Tests inject a service with a scripted runner."""
    active_service = service or ResearchService()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            active_service.shutdown()

    app = FastAPI(
        title="Sample Research Agent API",
        version="0.1.0",
        description="Run the LangGraph research/digest agent over HTTP.",
        lifespan=lifespan,
    )
    app.state.service = active_service

    origins = [
        origin.strip()
        for origin in os.getenv(
            "WEB_ORIGIN",
            "http://localhost:3000,http://127.0.0.1:3000,https://akhiil03.github.io",
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
    )

    def _service(request: Request) -> ResearchService:
        return request.app.state.service

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        provider = (os.getenv("AGENT_PROVIDER") or "google").strip().lower()
        if provider not in PROVIDERS:
            provider = "google"
        if provider == "google":
            has_key = bool(
                os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
            )
            default_model = DEFAULT_GOOGLE_MODEL
        else:
            has_key = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
            default_model = DEFAULT_OPENROUTER_MODEL
        return {
            "status": "ok",
            "provider": provider,
            "default_model": os.getenv("AGENT_MODEL") or default_model,
            "fake_model": os.getenv("AGENT_FAKE_MODEL", "").strip().lower()
            in {"1", "true", "yes", "on"},
            "has_api_key": has_key,
        }

    @app.post("/api/runs", status_code=202)
    def create_run(payload: ResearchRequest, request: Request) -> dict[str, Any]:
        run = _service(request).start(payload)
        return run.snapshot()

    @app.get("/api/runs")
    def list_runs(request: Request, limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(limit, MAX_HISTORY))
        runs = _service(request).list(limit)
        return {"runs": [run.snapshot(include_content=False) for run in runs]}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, request: Request) -> dict[str, Any]:
        try:
            return _service(request).get(run_id).snapshot()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse)
    def get_report(run_id: str, request: Request) -> PlainTextResponse:
        try:
            run = _service(request).get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        if not run.report:
            raise HTTPException(status_code=409, detail="Report is not ready yet")
        return PlainTextResponse(
            run.report,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{run.id}-digest.md"',
            },
        )

    return app


app = create_app()
