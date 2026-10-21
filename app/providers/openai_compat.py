"""Generic adapter for providers that expose an OpenAI-compatible API.

One class covers Groq, Gemini (OpenAI-compatible endpoint), OpenRouter and
Ollama: only the base URL and the API key change.
"""

from typing import Any

import httpx

from app.config import ProviderSettings
from app.providers.base import Provider, ProviderResponse


class OpenAICompatibleProvider(Provider):
    def __init__(self, settings: ProviderSettings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client

    async def chat_completion(self, model: str, body: dict[str, Any]) -> ProviderResponse:
        response = await self._http_client.post(
            f"{self._settings.base_url}/chat/completions",
            json={**body, "model": model},
            headers=self._auth_headers(),
        )
        return ProviderResponse(body=response.json())

    def _auth_headers(self) -> dict[str, str]:
        if self._settings.api_key is None:
            return {}
        return {"Authorization": f"Bearer {self._settings.api_key.get_secret_value()}"}
