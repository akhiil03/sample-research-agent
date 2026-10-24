"""Command line entry point for the research agent."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence

from .config import ConfigError, Settings
from .graph import run_research
from .publish import StatusPublisher

LOGGER = logging.getLogger("research_agent")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description="Research a topic on the web and write a cited Markdown digest.",
    )
    parser.add_argument("topic", help="Topic to research, for example 'small language models'")
    parser.add_argument("-o", "--out", default=None, help="Output directory (default: reports)")
    parser.add_argument(
        "-m",
        "--model",
        default=None,
        help="Gemini or OpenRouter model id (default: $AGENT_MODEL or provider's free default)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum research/critique rounds, 1-5 (default: 2)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="LangGraph recursion limit, 10-200 (default: 40)",
    )
    parser.add_argument(
        "--checkpointer",
        choices=["memory", "sqlite"],
        default="memory",
        help="Where to persist graph checkpoints (default: memory)",
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        help="Checkpoint database path when --checkpointer=sqlite",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="Reuse a thread id to resume or inspect a previous run",
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON summary to stdout")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)

    try:
        settings = Settings.from_env(
            args.topic,
            model=args.model,
            max_iterations=args.max_iterations,
            max_steps=args.max_steps,
            output_dir=args.out,
            checkpointer=args.checkpointer,
            sqlite_path=args.sqlite_path,
            thread_id=args.thread_id,
            verbose=args.verbose,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    publisher = StatusPublisher.from_env(
        topic=settings.topic,
        model=settings.model,
        max_iterations=settings.max_iterations,
    )
    if publisher is not None:
        publisher.publish(force=True)

    try:
        if publisher is not None:
            result = run_research(settings, event_sink=publisher.apply_event)
        else:
            result = run_research(settings)
    except KeyboardInterrupt:
        if publisher is not None:
            publisher.fail("interrupted")
        print("error: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        if publisher is not None:
            publisher.fail(exc)
        if args.verbose:
            LOGGER.exception("Agent run failed")
        else:
            LOGGER.error("Agent run failed: %s", exc)
        print(f"error: agent run failed: {exc}", file=sys.stderr)
        return 3

    if publisher is not None:
        publisher.succeed(result)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 0

    print(f"Digest written to {result.output_path}")
    print(f"Topic: {result.topic}")
    print(f"Model: {result.model}")
    print(f"Sources: {len(result.sources)} | Rounds: {result.rounds} | Thread: {result.thread_id}")
    if result.usage.get("total_tokens"):
        print(
            "Tokens: "
            f"{result.usage['input_tokens']} in / "
            f"{result.usage['output_tokens']} out / "
            f"{result.usage['total_tokens']} total"
        )
    print(f"Elapsed: {result.elapsed_seconds:.1f}s")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
