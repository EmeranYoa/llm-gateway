"""Tests for default values of the gateway configuration."""

import datetime as dt
from collections.abc import Callable

from app.config import Settings, load_config

WriteConfig = Callable[[str], Settings]

NO_OPTIONAL_FIELDS = """
providers:
  ollama:
    base_url: http://ollama.test/v1
    api_key_env: null
    models:
      "llama3.2:3b": {}
routes:
  chat-fast: [ ollama/llama3.2:3b ]
"""


def test_defaults_apply_when_optional_fields_are_missing(write_config: WriteConfig) -> None:
    config = load_config(write_config(NO_OPTIONAL_FIELDS).gateway_config_path, environ={})

    (target,) = config.routes["chat-fast"]
    assert config.deadline == 60.0
    assert config.default_completion_tokens == 512
    assert target.limits.timeout == 30.0
    assert (target.limits.rpm, target.limits.tpm, target.limits.rpd) == (None, None, None)
    assert target.provider.daily_reset.time == dt.time(0, 0)
    assert target.provider.daily_reset.timezone == "UTC"


def test_configured_values_override_defaults(write_config: WriteConfig) -> None:
    settings = write_config("""
        gateway:
          deadline: 20
          default_completion_tokens: 256
        providers:
          gemini:
            base_url: https://gemini.test/v1beta/openai
            api_key_env: GEMINI_API_KEY
            daily_reset: { time: "08:00", timezone: "America/Los_Angeles" }
            models:
              gemini-2.5-flash: { rpm: 10, rpd: 250, timeout: 15 }
        routes:
          chat-fast: [ gemini/gemini-2.5-flash ]
        """)

    config = load_config(settings.gateway_config_path, environ={"GEMINI_API_KEY": "key"})

    (target,) = config.routes["chat-fast"]
    assert config.deadline == 20.0
    assert config.default_completion_tokens == 256
    assert (target.limits.rpm, target.limits.tpm, target.limits.rpd) == (10, None, 250)
    assert target.limits.timeout == 15.0
    assert target.provider.daily_reset.time == dt.time(8, 0)
    assert target.provider.daily_reset.timezone == "America/Los_Angeles"
