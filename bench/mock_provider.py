"""A fake OpenAI-compatible provider that answers after a fixed delay.

The benchmark sends its requests to this mock instead of a real provider, so that
it measures the gateway and not the network or the model.

Routes:
- `POST /ok/v1/chat/completions`: answers after `MOCK_DELAY_MS` (default 50 ms).
  With `stream: true`, it sends 10 content chunks 5 ms apart, then a finish chunk,
  a usage chunk and `data: [DONE]`.
- `POST /ok/v1/embeddings`: a deterministic vector for each text, so the same text
  always gets the same vector (used by the semantic cache).
- `POST /down/v1/chat/completions`: always 503, to measure a failover.
- `GET /health`: for the Docker Compose health check.

Run it with: `uvicorn mock_provider:app --port 9000`.
"""

import asyncio
import hashlib
import json
import os
import random
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

DELAY_SECONDS = float(os.environ.get("MOCK_DELAY_MS", "50")) / 1000
STREAM_CHUNKS = 10
STREAM_CHUNK_GAP_SECONDS = 0.005
# Same size as nomic-embed-text, the embedding model recommended for the cache,
# so the vector search in Redis does a realistic amount of work.
EMBEDDING_DIMENSIONS = 768
USAGE = {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}

app = FastAPI(title="Mock provider")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ok/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    body = await request.json()
    model = body.get("model", "mock-model")
    await asyncio.sleep(DELAY_SECONDS)
    if body.get("stream"):
        return StreamingResponse(_stream(model), media_type="text/event-stream")
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello" + " word" * 9},
                "finish_reason": "stop",
            }
        ],
        "usage": USAGE,
    }


async def _stream(model: str) -> AsyncIterator[str]:
    """The answer as OpenAI chunks: content, finish reason, usage, then [DONE]."""
    yield _event(model, [_choice({"role": "assistant", "content": "Hello"})])
    for _ in range(STREAM_CHUNKS - 1):
        await asyncio.sleep(STREAM_CHUNK_GAP_SECONDS)
        yield _event(model, [_choice({"content": " word"})])
    yield _event(model, [_choice({}, finish_reason="stop")])
    yield _event(model, [], usage=USAGE)
    yield "data: [DONE]\n\n"


def _choice(delta: dict[str, str], finish_reason: str | None = None) -> dict[str, Any]:
    return {"index": 0, "delta": delta, "finish_reason": finish_reason}


def _event(model: str, choices: list[dict[str, Any]], usage: dict[str, int] | None = None) -> str:
    chunk: dict[str, Any] = {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": choices,
    }
    if usage is not None:
        chunk["usage"] = usage
    return f"data: {json.dumps(chunk)}\n\n"


@app.post("/ok/v1/embeddings")
async def embeddings(request: Request) -> dict[str, Any]:
    body = await request.json()
    text = body["input"] if isinstance(body["input"], str) else body["input"][0]
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": _vector(text)}],
        "model": body["model"],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def _vector(text: str) -> list[float]:
    """A pseudo-random vector seeded by the text.

    Values are centred on 0, so two different texts are almost orthogonal: a unique
    prompt never looks similar enough to a stored one to become a semantic hit.
    """
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest())
    generator = random.Random(seed)
    return [generator.uniform(-1, 1) for _ in range(EMBEDDING_DIMENSIONS)]


@app.post("/down/v1/chat/completions")
async def down() -> JSONResponse:
    return JSONResponse(
        {"error": {"message": "mock outage", "type": "server_error", "param": None, "code": None}},
        status_code=503,
    )
