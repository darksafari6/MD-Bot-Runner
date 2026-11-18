from __future__ import annotations

import pytest

from wamanager.ai import AiClient, _is_local
from wamanager.config import Settings
from wamanager.errors import ValidationError


def client(base_url="", api_key="", model="gpt-4o-mini"):
    settings = Settings()
    object.__setattr__(settings, "ai_base_url", base_url)
    object.__setattr__(settings, "ai_api_key", api_key or None)
    object.__setattr__(settings, "ai_model", model)
    return AiClient(settings)


def test_local_detection():
    assert _is_local("http://127.0.0.1:11434/v1")
    assert _is_local("http://localhost:1234/v1")
    assert not _is_local("https://api.openai.com/v1")


def test_remote_provider_without_key_is_not_configured():
    assert client("https://api.openai.com/v1", "").configured() is False
    assert client("https://api.openai.com/v1", "sk-123").configured() is True


def test_local_provider_needs_no_key():
    assert client("http://127.0.0.1:11434/v1", "").configured() is True


def test_missing_model_is_not_configured():
    assert client("http://127.0.0.1:11434/v1", "", model="").configured() is False


def test_resolve_raises_actionable_errors():
    with pytest.raises(ValidationError, match="API key"):
        client("https://api.openai.com/v1", "").resolve({})
    with pytest.raises(ValidationError, match="No AI provider"):
        client("", "", model="x").resolve({})


def test_bot_config_overrides_defaults():
    resolved = client("https://api.openai.com/v1", "sk-1").resolve(
        {"ai_base_url": "http://127.0.0.1:11434/v1", "ai_model": "llama3.1"}
    )
    assert resolved[0] == "http://127.0.0.1:11434/v1"
    assert resolved[2] == "llama3.1"
