"""Environment-driven configuration for the research agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "openrouter/free"
DEFAULT_MAX_ITERATIONS = 2
DEFAULT_MAX_STEPS = 40
MAX_ITERATIONS_LIMIT = 5


class ConfigError(RuntimeError):
    """Raised when the environment is not usable for a run."""


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Everything a single run needs, resolved once at startup."""

    topic: str
    model: str = DEFAULT_MODEL
    api_key: str = field(default="", repr=False)
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_steps: int = DEFAULT_MAX_STEPS
    output_dir: Path = Path("reports")
    checkpointer: str = "memory"
    sqlite_path: Path = Path(".agent/checkpoints.sqlite")
    thread_id: str = ""
    fake_model: bool = False
    verbose: bool = False

    @property
    def is_offline(self) -> bool:
        return self.fake_model

    @classmethod
    def from_env(
        cls,
        topic: str,
        *,
        model: str | None = None,
        max_iterations: int | None = None,
        max_steps: int | None = None,
        output_dir: str | Path | None = None,
        checkpointer: str = "memory",
        sqlite_path: str | Path | None = None,
        thread_id: str | None = None,
        verbose: bool = False,
    ) -> Settings:
        """Build settings from CLI arguments, environment variables, and .env."""
        # Only read the .env in the working directory, never one from a parent
        # directory: tests and CI must not pick up a developer's local secrets.
        load_dotenv(dotenv_path=Path(".env"))

        clean_topic = " ".join(topic.split())
        if not clean_topic:
            raise ConfigError("Topic must not be empty.")

        fake_model = _env_flag("AGENT_FAKE_MODEL")
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        selected_model = (model or os.getenv("AGENT_MODEL") or DEFAULT_MODEL).strip()

        if not fake_model and not api_key:
            raise ConfigError(
                "OPENROUTER_API_KEY is not set. Add it to your environment (or .env), "
                "or run with AGENT_FAKE_MODEL=1 for an offline demo."
            )

        iterations = (
            max_iterations
            if max_iterations is not None
            else _env_int("AGENT_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS)
        )
        steps = (
            max_steps if max_steps is not None else _env_int("AGENT_MAX_STEPS", DEFAULT_MAX_STEPS)
        )
        if not 1 <= iterations <= MAX_ITERATIONS_LIMIT:
            raise ConfigError(
                f"max_iterations must be between 1 and {MAX_ITERATIONS_LIMIT}, got {iterations}"
            )
        if not 10 <= steps <= 200:
            raise ConfigError(f"max_steps must be between 10 and 200, got {steps}")

        if checkpointer not in {"memory", "sqlite"}:
            raise ConfigError(f"checkpointer must be 'memory' or 'sqlite', got {checkpointer!r}")

        destination = Path(output_dir or os.getenv("AGENT_OUTPUT_DIR") or "reports").expanduser()
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"Cannot create output directory {destination}: {exc}") from exc

        sqlite_path = Path(
            sqlite_path or os.getenv("AGENT_SQLITE_PATH") or Path(".agent") / "checkpoints.sqlite"
        ).expanduser()

        return cls(
            topic=clean_topic,
            model=selected_model,
            api_key=api_key,
            max_iterations=iterations,
            max_steps=steps,
            output_dir=destination,
            checkpointer=checkpointer,
            sqlite_path=sqlite_path,
            thread_id=(thread_id or "").strip(),
            fake_model=fake_model,
            verbose=verbose,
        )
