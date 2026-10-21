"""Tests for gateway startup with valid and invalid configurations."""

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from app.config import ConfigError, Settings
from app.main import create_app

WriteConfig = Callable[[str], Settings]


@pytest.mark.parametrize(
    "reference",
    ["ollama/unknown-model", "unknown-provider/llama3.2:3b", "no-slash"],
)
def test_startup_fails_when_route_references_unknown_model(
    write_config: WriteConfig, reference: str
) -> None:
    settings = write_config(f"""
        providers:
          ollama:
            base_url: http://ollama.test/v1
            api_key_env: null
            models:
              "llama3.2:3b": {{}}
        routes:
          chat-fast: [ "{reference}" ]
        """)

    with pytest.raises(ConfigError, match=f"chat-fast.*{reference}"):
        create_app(settings)


@pytest.mark.parametrize(
    ("case", "config_yaml"),
    [
        ("empty file", ""),
        ("malformed YAML", "providers: [unclosed"),
        ("missing base_url", "providers: {ollama: {api_key_env: null, models: {}}}\nroutes: {}"),
        ("unknown field", "providers: {}\nroutes: {}\nunknown: 1"),
        (
            "negative limit",
            """
            providers:
              ollama:
                base_url: http://ollama.test/v1
                api_key_env: null
                models: { m: { rpm: -1 } }
            routes: {}
            """,
        ),
    ],
)
def test_startup_fails_on_invalid_structure(
    write_config: WriteConfig, case: str, config_yaml: str
) -> None:
    with pytest.raises(ConfigError):
        create_app(write_config(config_yaml))


def test_startup_fails_when_config_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        create_app(Settings(gateway_config_path=tmp_path / "missing.yaml"))


def test_provider_without_api_key_is_disabled_with_a_warning(
    write_config: WriteConfig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings = write_config("""
        providers:
          groq:
            base_url: https://groq.test/openai/v1
            api_key_env: GROQ_API_KEY
            models:
              llama-3.3-70b-versatile: {}
        routes:
          chat-fast: [ groq/llama-3.3-70b-versatile ]
        """)

    with caplog.at_level(logging.WARNING):
        create_app(settings)

    assert "provider 'groq' disabled: GROQ_API_KEY is not set" in caplog.messages
