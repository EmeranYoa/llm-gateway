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
    """The cache keys of one request: SHA-256 hashes, never the text itself."""

    context: str
    exact: str


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
    return RequestKey(context=context, exact=_sha256({"context": context, "last": last_message}))


def _sha256(value: object) -> str:
    serialised = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()
