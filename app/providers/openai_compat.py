"""Generic adapter for providers that expose an OpenAI-compatible API.

One class covers Groq, Gemini (OpenAI-compatible endpoint), OpenRouter and
Ollama: only the base URL and the API key change.
"""

import datetime as dt
import email.utils
import json
import re
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import httpx

from app.config import ProviderSettings
from app.providers.base import (
    ContextTooLarge,
    InvalidRequest,
    Provider,
    ProviderError,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    StreamChunk,
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


# Durations in rate-limit headers, for example "2m59.56s" or "250ms".
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_DURATION = re.compile(r"(?:\d+(?:\.\d+)?(?:ms|h|m|s))+")
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


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
        _raise_for_error_status(response)
        body = response.json()
        usage = body.get("usage") if isinstance(body, dict) else None
        if not isinstance(usage, dict):
            usage = {}
        return ProviderResponse(
            body=body,
            prompt_tokens=_int_or_none(usage.get("prompt_tokens")),
            completion_tokens=_int_or_none(usage.get("completion_tokens")),
        )

    async def stream_chat_completion(
        self,
        model: str,
        body: dict[str, Any],
        timeout: float,  # noqa: ASYNC109 (see Provider.chat_completion)
    ) -> AsyncGenerator[StreamChunk]:
        try:
            async with self._http_client.stream(
                "POST",
                f"{self._settings.base_url}/chat/completions",
                json={**body, "model": model},
                headers=self._auth_headers(),
                timeout=timeout,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    _raise_for_error_status(response)
                async for data in _sse_data(response.aiter_lines()):
                    if data == "[DONE]":
                        return
                    event = json.loads(data)
                    if isinstance(event, dict) and "error" in event:
                        raise _stream_error(event["error"])
                    yield StreamChunk(event)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout() from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"network error ({type(exc).__name__})") from exc

    def _auth_headers(self) -> dict[str, str]:
        if self._settings.api_key is None:
            return {}
        return {"Authorization": f"Bearer {self._settings.api_key.get_secret_value()}"}


def _raise_for_error_status(response: httpx.Response) -> None:
    """Translate an HTTP error status into one of the common provider error types."""
    if response.status_code == 429:
        raise RateLimited(retry_after=_retry_after(response))
    if response.status_code in (401, 403, 404):
        raise TargetMisconfigured(response.status_code)
    if response.status_code >= 500:
        raise ProviderUnavailable(f"HTTP {response.status_code}", response.status_code)
    if response.status_code >= 400:
        error = _invalid_request(response)
        if _is_context_too_large(error):
            raise ContextTooLarge(error.status_code) from error
        raise error


def _stream_error(error: object) -> ProviderError:
    """Translate an error event sent inside a stream into a common provider error type.

    Some providers (OpenRouter, for example) answer 200 and then send the error as
    an event, with an HTTP-like `code`. The upstream text is not reused, except for
    a client error, where the client needs it.
    """
    detail = error if isinstance(error, dict) else {}
    code = detail.get("code")
    status = code if isinstance(code, int) else None
    if status == 429:
        return RateLimited(retry_after=None)
    if status in (401, 403, 404):
        return TargetMisconfigured(status)
    if status is None or status < 400 or status >= 500:
        return ProviderUnavailable(f"error event in the stream (code {code})", status)
    invalid = InvalidRequest(
        status,
        message=_text_or_none(detail.get("message")) or f"HTTP {status}",
        error_type=_text_or_none(detail.get("type")) or "invalid_request_error",
        param=_text_or_none(detail.get("param")),
    )
    if _is_context_too_large(invalid):
        return ContextTooLarge(status)
    return invalid


async def _sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Yield the `data` of each Server-Sent Event. Comments (`: ...`) are keep-alives."""
    data_lines: list[str] = []
    async for line in lines:
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").removeprefix(" "))
        elif not line and data_lines:
            # A blank line ends the event.
            yield "\n".join(data_lines)
            data_lines = []
    if data_lines:
        yield "\n".join(data_lines)


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


def _retry_after(response: httpx.Response) -> float | None:
    """Read how long the provider asks to wait before the next call, in seconds.

    1. `Retry-After`, in seconds or as an HTTP date.
    2. Otherwise the `x-ratelimit-reset-requests` / `x-ratelimit-reset-tokens`
       headers (Groq, OpenAI): the reset time of the limit that is used up
       (its `x-ratelimit-remaining-*` header is 0), or the longest reset time
       when the headers do not say which limit is used up.

    Returns None when the response gives no usable delay.
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        return _parse_retry_after(retry_after)
    resets = {
        kind: _parse_duration(response.headers.get(f"x-ratelimit-reset-{kind}", ""))
        for kind in ("requests", "tokens")
    }
    used_up = [
        reset
        for kind, reset in resets.items()
        if reset is not None and response.headers.get(f"x-ratelimit-remaining-{kind}") == "0"
    ]
    known = used_up or [reset for reset in resets.values() if reset is not None]
    return max(known, default=None)


def _parse_retry_after(value: str) -> float | None:
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        retry_at = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max((retry_at - dt.datetime.now(dt.UTC)).total_seconds(), 0.0)


def _parse_duration(value: str) -> float | None:
    """Parse durations such as "2m59.56s", "7.66s", "250ms" or "1h" into seconds."""
    if not _DURATION.fullmatch(value):
        return None
    return sum(
        float(number) * _DURATION_UNITS[unit] for number, unit in _DURATION_PART.findall(value)
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


def _int_or_none(value: object) -> int | None:
    """Keep only integer values (`bool` is an `int` subclass in Python, so it is excluded)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None
