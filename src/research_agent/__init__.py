"""Sample LangGraph research agent hosted on GitHub Actions."""

from .config import ConfigError, Settings
from .graph import build_graph, run_research
from .state import RunResult, Source

__version__ = "0.1.0"

__all__ = [
    "ConfigError",
    "RunResult",
    "Settings",
    "Source",
    "__version__",
    "build_graph",
    "run_research",
]
