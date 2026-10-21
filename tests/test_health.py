"""Tests for the health endpoint."""

import pytest
from httpx import AsyncClient

from tests.conftest import ClientFactory

THREE_PROVIDERS = """
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      llama-3.3-70b-versatile: { rpm: 30, tpm: 6000, rpd: 1000 }
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: GEMINI_API_KEY
    models:
      gemini-2.5-flash: { rpm: 10, rpd: 250 }
  ollama:
    base_url: http://ollama.test/v1
    api_key_env: null
    models:
      "llama3.2:3b": { timeout: 120 }
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile, gemini/gemini-2.5-flash, ollama/llama3.2:3b ]
"""


async def test_health_reports_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_lists_enabled_and_disabled_providers(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    async with make_client(THREE_PROVIDERS) as client:
        response = await client.get("/health")

    assert response.json()["providers"] == {"enabled": ["groq", "ollama"], "disabled": ["gemini"]}


async def test_health_lists_routes_without_disabled_providers(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async with make_client(THREE_PROVIDERS) as client:
        response = await client.get("/health")

    assert response.json()["routes"] == {
        "chat-fast": ["groq/llama-3.3-70b-versatile", "ollama/llama3.2:3b"]
    }
