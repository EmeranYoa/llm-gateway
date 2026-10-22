"""Fake upstream provider used by API tests."""

import json
from typing import Any

import httpx

CHAT_CONFIG = """
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      llama-3.3-70b-versatile: {}
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: GEMINI_API_KEY
    models:
      gemini-2.5-flash: {}
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile ]
  chat-offline: [ gemini/gemini-2.5-flash ]
"""

GROQ_URL = "https://groq.test/openai/v1/chat/completions"
GROQ_KEY = "test-groq-key"
CHAT_REQUEST = {"model": "chat-fast", "messages": [{"role": "user", "content": "Hi"}]}


def completion_body(model: str, content: str = "Hello!") -> dict[str, Any]:
    """A chat completion body as an OpenAI-compatible provider returns it."""
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }


FAILOVER_CONFIG = """
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      llama-3.3-70b-versatile: {}
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: GEMINI_API_KEY
    models:
      gemini-2.5-flash: {}
  ollama:
    base_url: http://ollama.test/v1
    api_key_env: null
    models:
      "llama3.2:3b": {}
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile, gemini/gemini-2.5-flash, ollama/llama3.2:3b ]
"""

GEMINI_URL = "https://gemini.test/v1beta/openai/chat/completions"
GEMINI_KEY = "test-gemini-key"
OLLAMA_URL = "http://ollama.test/v1/chat/completions"


def error_body(
    message: str, error_type: str = "invalid_request_error", code: str | None = None
) -> dict[str, Any]:
    """An error body in OpenAI format, as an OpenAI-compatible provider returns it."""
    return {"error": {"message": message, "type": error_type, "param": None, "code": code}}


# --- Streamed answers (Server-Sent Events) ---


def chunk(
    content: str | None = None,
    *,
    role: str | None = None,
    reasoning: str | None = None,
    model: str = "upstream",
) -> dict[str, Any]:
    """One chat completion chunk, as an OpenAI-compatible provider streams it."""
    delta: dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if reasoning is not None:
        delta["reasoning"] = reasoning
    if content is not None:
        delta["content"] = content
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 1_700_000_000,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }


def sse(*events: dict[str, Any] | str) -> bytes:
    """An SSE body: each event is a chunk (sent as JSON), a raw data string, or a comment."""
    lines = []
    for event in events:
        if isinstance(event, str) and event.startswith(":"):
            lines.append(f"{event}\n\n")
        elif isinstance(event, str):
            lines.append(f"data: {event}\n\n")
        else:
            lines.append(f"data: {json.dumps(event)}\n\n")
    return "".join(lines).encode()


def stream_response(*events: dict[str, Any] | str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(*events))
