"""Tests de configuración (`app/core/settings.py`)."""

from app.core.settings import Settings


def test_anthropic_defaults() -> None:
    # `_env_file=None`: no leer `.env` (la API key local puede estar vacía).
    s = Settings(_env_file=None)
    assert s.ANTHROPIC_API_KEY is None
    assert s.AGENT_MODEL == "claude-haiku-4-5-20251001"
    assert s.AGENT_MAX_TOKENS == 1024
    assert s.AGENT_TEMPERATURE == 0.3


def test_anthropic_override_via_env(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("AGENT_MAX_TOKENS", "2048")
    monkeypatch.setenv("AGENT_TEMPERATURE", "0.5")
    s = Settings()
    assert s.ANTHROPIC_API_KEY == "sk-test"
    assert s.AGENT_MODEL == "claude-haiku-4-5"
    assert s.AGENT_MAX_TOKENS == 2048
    assert s.AGENT_TEMPERATURE == 0.5
