from __future__ import annotations

import json

import pytest

from research_agent.cli import main


def test_cli_offline_run_writes_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_FAKE_MODEL", "1")
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "AGENT_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    out = tmp_path / "reports"

    code = main(["offline topic", "--out", str(out), "--json"])

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["topic"] == "offline topic"
    assert payload["source_count"] >= 1
    assert payload["rounds"] == 1
    assert (out / payload["output_path"].split("/")[-1]).exists()


def test_cli_requires_api_key_without_offline_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_FAKE_MODEL", raising=False)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "AGENT_PROVIDER"):
        monkeypatch.delenv(name, raising=False)

    code = main(["some topic", "--out", str(tmp_path / "reports")])

    captured = capsys.readouterr()
    assert code == 2
    assert "GEMINI_API_KEY" in captured.err


def test_cli_rejects_out_of_range_iterations(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_FAKE_MODEL", "1")

    code = main(["some topic", "--out", str(tmp_path / "reports"), "--max-iterations", "9"])

    captured = capsys.readouterr()
    assert code == 2
    assert "max_iterations" in captured.err


def test_cli_returns_three_on_run_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_FAKE_MODEL", "1")

    def boom(settings):
        raise RuntimeError("model exploded")

    monkeypatch.setattr("research_agent.cli.run_research", boom)

    code = main(["some topic", "--out", str(tmp_path / "reports")])

    captured = capsys.readouterr()
    assert code == 3
    assert "model exploded" in captured.err


def test_cli_rejects_unknown_checkpointer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_FAKE_MODEL", "1")

    with pytest.raises(SystemExit) as excinfo:
        main(["topic", "--out", str(tmp_path / "reports"), "--checkpointer", "redis"])

    assert excinfo.value.code == 2


def test_cli_rejects_out_of_range_steps(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_FAKE_MODEL", "1")

    code = main(["topic", "--out", str(tmp_path / "reports"), "--max-steps", "5"])

    captured = capsys.readouterr()
    assert code == 2
    assert "max_steps" in captured.err
