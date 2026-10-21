"""Fake upstream provider used by API tests."""

from typing import Any

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
