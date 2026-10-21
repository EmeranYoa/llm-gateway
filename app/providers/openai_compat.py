"""Generic adapter for providers that expose an OpenAI-compatible API.

One class covers Groq, Gemini (OpenAI-compatible endpoint), OpenRouter and
Ollama: only the base URL and the API key change.
"""

from typing import Any

import httpx

from app.config import ProviderSettings
from app.providers.base import (
    ContextTooLarge,
    InvalidRequest,
    Provider,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    TargetMisconfigured,
)

# Lower-case fragments of known "request too large for this model" errors. Only
# these are treated as `ContextTooLarge`; anything else stays an `InvalidRequest`.
_CONTEXT_TOO_LARGE_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "exceeds the maximum number of tokens",
    "reduce the length of the messages",
)


class OpenAICompatibleProvider(Provider):
    def __init__(self, settings: ProviderSettings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client

    async def chat_completion(
        self,
        model: str,
        body: dict[str, Any],
        timeout: float,  # noqa: ASYNC109 (see Provider.chat_completion)
    ) -> ProviderResponse:
        try:
            response = await self._http_client.post(
                f"{self._settings.base_url}/chat/completions",
                json={**body, "model": model},
                headers=self._auth_headers(),
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout() from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"network error ({type(exc).__name__})") from exc
        if response.status_code == 429:
            raise RateLimited(retry_after=None)
        if response.status_code in (401, 403, 404):
            raise TargetMisconfigured(response.status_code)
        if response.status_code >= 500:
            raise ProviderUnavailable(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            error = _invalid_request(response)
            if _is_context_too_large(error):
                raise ContextTooLarge() from error
            raise error
        return ProviderResponse(body=response.json())

    def _auth_headers(self) -> dict[str, str]:
        if self._settings.api_key is None:
            return {}
        return {"Authorization": f"Bearer {self._settings.api_key.get_secret_value()}"}


def _invalid_request(response: httpx.Response) -> InvalidRequest:
    """Build an `InvalidRequest` from the error body of any OpenAI-compatible provider.

    Known shapes:
    - OpenAI, Groq, OpenRouter: `{"error": {"message", "type", "param", "code"}}`
    - Gemini: the same object wrapped in a list, with a numeric `code`
    - Ollama: `{"error": "message"}`
    """
    fallback = f"HTTP {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        return InvalidRequest(response.status_code, fallback)
    if isinstance(body, list) and body:
        body = body[0]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, str):
        return InvalidRequest(response.status_code, error or fallback)
    if not isinstance(error, dict):
        return InvalidRequest(response.status_code, fallback)
    return InvalidRequest(
        response.status_code,
        message=_text_or_none(error.get("message")) or fallback,
        error_type=_text_or_none(error.get("type")) or "invalid_request_error",
        param=_text_or_none(error.get("param")),
        code=_text_or_none(error.get("code")),
    )


def _is_context_too_large(error: InvalidRequest) -> bool:
    """Recognise "too large for this model" errors: HTTP 413 or a known message."""
    if error.status_code == 413:
        return True
    text = f"{error.code or ''} {error.message}".lower()
    return any(marker in text for marker in _CONTEXT_TOO_LARGE_MARKERS)


def _text_or_none(value: object) -> str | None:
    """Keep only string values: some providers use numbers where OpenAI uses strings."""
    return value if isinstance(value, str) and value else None
