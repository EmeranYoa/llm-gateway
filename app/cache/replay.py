"""Replay a stored answer as a stream, for a cache hit on a streamed request.

The cache stores normal (non-streamed) response bodies. A client that asked for
a stream gets the same answer as OpenAI-format chunks: the role, the content,
why it ended, then the usage only if the client asked for it.
"""

from typing import Any


def replayed_chunks(body: dict[str, Any], *, with_usage: bool) -> list[dict[str, Any]]:
    """The chunks of a stream that sends the answer `body` at once."""
    base = {
        "id": body.get("id"),
        "object": "chat.completion.chunk",
        "created": body.get("created"),
        "model": body.get("model"),
    }
    chunks = []
    for choice in body.get("choices") or []:
        index = choice.get("index", 0)
        message = dict(choice.get("message") or {})
        role = message.pop("role", "assistant")
        for delta, finish_reason in (
            ({"role": role, "content": ""}, None),
            (message, None),
            ({}, choice.get("finish_reason")),
        ):
            choices = [{"index": index, "delta": delta, "finish_reason": finish_reason}]
            chunks.append({**base, "choices": choices})
    if with_usage and "usage" in body:
        chunks.append({**base, "choices": [], "usage": body["usage"]})
    return chunks
