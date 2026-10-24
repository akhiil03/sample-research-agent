"""Publish live run status to a GitHub branch for the static web UI.

GitHub Pages can only serve static files, so the Pages UI orchestrates the
research agent by dispatching the GitHub Actions workflow and polling the
JSON status files this module writes. The publisher is a no-op unless the
``STATUS_RUN_ID`` environment variable is set (the workflow sets it).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

LOGGER = logging.getLogger("research_agent.status")

MAX_EVENTS = 200
MIN_INTERVAL_SECONDS = 2.0
API_ROOT = "https://api.github.com"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def describe_event(event: dict[str, Any]) -> str:
    """Short human sentence for an agent event (mirrors the API server copy)."""

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
            return f"Gathering evidence ({calls} tool calls, {event.get('sources', 0)} sources)"
        return f"Reviewed evidence ({event.get('sources', 0)} sources)"
    if stage == "tools":
        return f"Read {event.get('results', 0)} tool results"
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
            return f"Cleaned {dropped} out-of-range citations"
        return "Verification passed"
    if stage == "save":
        return "Digest saved"
    return "Working"


class StatusPublisher:
    """Writes ``runs/<id>.json`` on a branch via the GitHub contents API."""

    def __init__(
        self,
        *,
        repository: str,
        token: str,
        run_id: str,
        topic: str,
        model: str,
        max_iterations: int,
        branch: str = "status",
    ) -> None:
        self.repository = repository
        self.token = token
        self.run_id = run_id
        self.branch = branch
        self._sha: str | None = None
        self._started = datetime.now(UTC)
        self._t0 = time.perf_counter()
        self._last_publish = 0.0
        self.data: dict[str, Any] = {
            "id": run_id,
            "topic": topic,
            "model": model,
            "max_iterations": max_iterations,
            "status": "running",
            "stage": "starting",
            "message": "Starting agent on GitHub Actions...",
            "created_at": _now(),
            "started_at": _now(),
            "finished_at": None,
            "rounds": 0,
            "source_count": 0,
            "sources": [],
            "events": [],
            "report": "",
            "output_path": "",
            "error": None,
            "elapsed_seconds": 0.0,
            "usage": {},
        }

    @classmethod
    def from_env(cls, *, topic: str, model: str, max_iterations: int) -> StatusPublisher | None:
        run_id = os.getenv("STATUS_RUN_ID", "").strip()
        repository = os.getenv("GITHUB_REPOSITORY", "").strip()
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if not run_id or not repository or not token:
            return None
        return cls(
            repository=repository,
            token=token,
            run_id=run_id,
            topic=topic,
            model=model,
            max_iterations=max_iterations,
            branch=os.getenv("STATUS_BRANCH", "status").strip() or "status",
        )

    def apply_event(self, event: dict[str, Any]) -> None:
        self.data["events"].append({**event, "at": _now()})
        if len(self.data["events"]) > MAX_EVENTS:
            self.data["events"] = self.data["events"][-MAX_EVENTS:]
        stage = event.get("stage")
        if isinstance(stage, str):
            self.data["stage"] = stage
        self.data["message"] = describe_event(event)
        rounds = event.get("rounds", event.get("round"))
        if isinstance(rounds, int):
            self.data["rounds"] = rounds
        sources = event.get("sources")
        if isinstance(sources, int):
            self.data["source_count"] = sources
        self.publish()

    def succeed(self, result: Any) -> None:
        self.data.update(
            {
                "status": "succeeded",
                "stage": "done",
                "message": "Digest ready",
                "finished_at": _now(),
                "rounds": result.rounds,
                "sources": list(result.sources),
                "source_count": len(result.sources),
                "report": result.report,
                "output_path": result.output_path,
                "usage": result.usage,
            }
        )
        self.publish(force=True)

    def fail(self, error: BaseException | str) -> None:
        self.data.update(
            {
                "status": "failed",
                "stage": "failed",
                "message": "Run failed",
                "error": str(error),
                "finished_at": _now(),
            }
        )
        self.publish(force=True)

    def publish(self, force: bool = False) -> None:
        elapsed = time.perf_counter() - self._t0
        self.data["elapsed_seconds"] = round(elapsed, 2)
        now = time.monotonic()
        if not force and now - self._last_publish < MIN_INTERVAL_SECONDS:
            return
        self._last_publish = now
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        body: dict[str, Any] = {
            "message": f"status: {self.run_id} {self.data['status']} [{skip(self.data['status'])}]",
            "content": base64.b64encode(payload.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
        }
        if self._sha:
            body["sha"] = self._sha
        try:
            response = self._request("PUT", self._content_path(), body)
            self._sha = response.get("content", {}).get("sha") or self._sha
        except urllib.error.HTTPError as exc:
            if exc.code in {409, 422} and self._refresh_sha():
                body["sha"] = self._sha
                try:
                    response = self._request("PUT", self._content_path(), body)
                    self._sha = response.get("content", {}).get("sha") or self._sha
                    return
                except Exception:  # noqa: BLE001 - status is best effort
                    LOGGER.warning("Could not publish status after sha refresh", exc_info=True)
                    return
            LOGGER.warning("Could not publish run status (HTTP %s)", exc.code)
        except Exception:  # noqa: BLE001 - status publishing must never fail a run
            LOGGER.warning("Could not publish run status", exc_info=True)

    def _refresh_sha(self) -> bool:
        try:
            response = self._request("GET", f"{self._content_path()}?ref={self.branch}")
        except Exception:  # noqa: BLE001 - best effort
            return False
        sha = response.get("sha")
        self._sha = sha if isinstance(sha, str) else None
        return self._sha is not None

    def _content_path(self) -> str:
        return f"{API_ROOT}/repos/{self.repository}/contents/runs/{self.run_id}.json"

    def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed host
            raw = response.read()
        return json.loads(raw) if raw else {}


def skip(status: str) -> str:
    """Commit message hint so status commits never trigger other workflows."""

    return "skip ci" if status in {"running", "succeeded", "failed"} else "status"
