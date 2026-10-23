"""What must match for a stored answer to be reused.

A request has two parts for the cache:

- its **context**: every field of the body except the last message and the
  fields that do not change the answer (`stream`, `stream_options`, and `model`,
  since the alias is already part of the cache key);
- its **last message**, usually the question of the user.

The exact key covers both: an identical request. The context key alone lets the
semantic search compare last questions by meaning, within the same context.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Fields that change how the answer is delivered, not what it says.
_IGNORED_FIELDS = frozenset({"stream", "stream_options", "model"})


@dataclass(frozen=True)
class RequestKey:
    """The cache keys of one request: SHA-256 hashes, and the question to compare by meaning."""

    context: str
    exact: str
    question: str | None
    """The text of the last message when it comes from the user, for the semantic search.

    Kept in memory only, never stored. None when the last message is not a user
    question: the request then only gets exact hits.
    """


def request_key(body: Mapping[str, Any]) -> RequestKey:
    """Hash the request `body` into its context key and its exact key.

    The JSON is serialised with sorted keys, so the order of the fields in the
    request does not matter. Unknown fields count: a new parameter can never
    produce a stored answer meant for other settings.
    """
    fields = {name: value for name, value in body.items() if name not in _IGNORED_FIELDS}
    messages = list(fields.get("messages") or [])
    last_message = messages.pop() if messages else None
    context = _sha256({**fields, "messages": messages})
    return RequestKey(
        context=context,
        exact=_sha256({"context": context, "last": last_message}),
        question=_question(last_message),
    )


def _question(message: object) -> str | None:
    """The text of a user message: its content, or its text parts joined with spaces."""
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(part, dict) and part.get("type") == "text" for part in content
    ):
        return " ".join(str(part.get("text", "")) for part in content)
    return None


def _sha256(value: object) -> str:
    serialised = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()
