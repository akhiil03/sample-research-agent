from __future__ import annotations

from research_agent.config import Settings
from research_agent.llm import build_llm, build_offline_llm


def _settings(**overrides):
    defaults = {"topic": "test", "api_key": "sk-test", "fake_model": False}
    defaults.update(overrides)
    return Settings(**defaults)


def test_build_llm_google_defaults():
    model = build_llm(_settings(model="gemini-3.5-flash-lite"))
    resolved = getattr(model, "model", None) or getattr(model, "model_name", None)
    assert resolved == "gemini-3.5-flash-lite"
    assert model.max_retries == 2
    assert model.temperature == 0.2


def test_build_llm_openrouter_keeps_millisecond_timeout():
    model = build_llm(_settings(provider="openrouter", model="openrouter/free"))
    assert model.request_timeout == 90_000
    assert model.max_retries == 2
    assert model.model_name == "openrouter/free"


def test_offline_model_has_fixed_script():
    model = build_offline_llm("topic")
    assert len(model.responses) == 5
    assert model.responses[1].tool_calls[0]["name"] == "web_search"
