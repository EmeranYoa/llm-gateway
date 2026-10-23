"""Stored answers in Redis, one hash per entry, isolated per tenant and alias.

An entry keeps the response body and the target that generated it, never the
text of the messages. Exact lookups use the hashes of `keys.py`. Semantic
lookups use Redis vector search: each entry may also hold the embedding of its
question, and a `scope` tag (tenant, alias, context and embedding model) that
limits the search to entries with the same context. Each entry expires after
the TTL of its alias; a hit does not extend it.
"""

import hashlib
import json
import re
import struct
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from redis.typing import EncodableT, FieldT

from app.cache.embeddings import EmbeddingClient
from app.cache.keys import RequestKey
from app.config import AliasCache, Target


@dataclass(frozen=True)
class CachedAnswer:
    """An answer read from the cache, ready to send to the client."""

    body: dict[str, Any]
    """The stored body, with a new `id` and `created`: each answer looks freshly generated."""
    provider: str
    """The provider that generated the answer."""
    model: str
    """The model that generated the answer."""
    similarity: float
    """1.0 for an identical request, the cosine similarity of the questions otherwise."""


@dataclass(frozen=True)
class CacheLookup:
    """The result of a lookup: the answer found, and the embedding computed on the way."""

    answer: CachedAnswer | None
    vector: list[float] | None
    """The embedding of the question, reused to store the answer after a miss."""


class ResponseCache:
    """The response cache of the aliases listed in the `cache` section of the config."""

    def __init__(
        self,
        redis: Redis,
        cached_aliases: Mapping[str, AliasCache],
        embedding: EmbeddingClient | None = None,
    ) -> None:
        """Without `embedding`, the cache only answers identical requests."""
        self._redis = redis
        self._cached_aliases = cached_aliases
        self._embedding = embedding
        self._created_indexes: set[str] = set()

    def covers(self, alias: str) -> bool:
        """True when `alias` uses the cache."""
        return alias in self._cached_aliases

    async def lookup(self, tenant_id: int, alias: str, key: RequestKey) -> CacheLookup:
        """Look for the answer of an identical request of the tenant, then of a similar one.

        The semantic search runs only for a user question of at most the configured
        number of characters. Raises `EmbeddingUnavailable` when the embedding model fails.
        """
        answer = await self._read(_entry_key(tenant_id, alias, key), similarity=1.0)
        if answer is not None or self._embedding is None or not self._embeds(key.question):
            return CacheLookup(answer, vector=None)
        assert key.question is not None  # checked by `_embeds`
        vector = await self._embedding.embed(key.question)
        answer = await self._nearest(tenant_id, alias, key, vector)
        return CacheLookup(answer, vector)

    async def store(
        self,
        tenant_id: int,
        alias: str,
        key: RequestKey,
        body: Mapping[str, Any],
        target: Target,
        vector: list[float] | None = None,
    ) -> None:
        """Keep the answer `body` that `target` generated, until the TTL of `alias` runs out.

        With the `vector` of the question, the entry can also answer similar questions.
        """
        entry_key = _entry_key(tenant_id, alias, key)
        entry: dict[FieldT, EncodableT] = {
            "body": json.dumps(body, separators=(",", ":")),
            "provider": target.provider.name,
            "model": target.model,
            "context": key.context,
            "created_at": time.time(),
        }
        if vector is not None and self._embedding is not None:
            await self._create_index(len(vector))
            entry["scope"] = self._scope(tenant_id, alias, key)
            entry["vector"] = _packed(vector)
        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.hset(entry_key, mapping=entry)
            pipeline.pexpire(entry_key, round(self._cached_aliases[alias].ttl * 1000))
            await pipeline.execute()

    async def clear(self, tenant_id: int | None, alias: str | None = None) -> int:
        """Remove stored answers and return how many were removed.

        `tenant_id` None removes the answers of every tenant; `alias` limits the
        removal to one alias of the tenant. Only cache entries are removed, never
        the routing or quota state kept in the same Redis.
        """
        if tenant_id is None:
            if alias is not None:
                raise ValueError("an alias can only be cleared for one tenant")
            pattern = "cache:*"
        elif alias is None:
            pattern = f"cache:{tenant_id}:*"
        else:
            pattern = f"cache:{tenant_id}:{_escape_pattern(alias)}:*"
        removed = 0
        batch: list[bytes] = []
        # SCAN walks the keys in small steps, so a large cache never blocks Redis
        # the way KEYS would. Keys are checked again in Python: an alias may
        # contain ":", and clearing `chat` must keep the entries of `chat:x`.
        async for key in self._redis.scan_iter(match=pattern, count=_CLEAR_BATCH_SIZE):
            if _is_entry_key(key, tenant_id, alias):
                batch.append(key)
            if len(batch) >= _CLEAR_BATCH_SIZE:
                removed += await self._redis.delete(*batch)
                batch.clear()
        if batch:
            removed += await self._redis.delete(*batch)
        return removed

    def _embeds(self, question: str | None) -> bool:
        """True when `question` is compared by meaning (not too long for the embedding model)."""
        return (
            question is not None
            and self._embedding is not None
            and len(question) <= self._embedding.max_chars
        )

    async def _nearest(
        self, tenant_id: int, alias: str, key: RequestKey, vector: list[float]
    ) -> CachedAnswer | None:
        """The answer whose question is the closest to `vector`, if similar enough."""
        scope = self._scope(tenant_id, alias, key)
        query = f"(@scope:{{{scope}}})=>[KNN 1 @vector $vector AS distance]"
        try:
            # redis-py has no typed method for vector search commands.
            found = await self._redis.execute_command(  # type: ignore[no-untyped-call]
                "FT.SEARCH", self._index_name(len(vector)), query,
                "PARAMS", "2", "vector", _packed(vector),
                "RETURN", "1", "distance", "DIALECT", "2",
            )  # fmt: skip
        except ResponseError as error:
            if "index not found" not in str(error).lower():
                raise
            # No answer stored yet (or Redis was emptied): the next write creates the index.
            self._created_indexes.discard(self._index_name(len(vector)))
            return None
        if not found[b"results"]:
            return None
        nearest = found[b"results"][0]
        similarity = 1 - float(nearest[b"extra_attributes"][b"distance"])
        if similarity < self._cached_aliases[alias].similarity_threshold:
            return None
        return await self._read(nearest[b"id"], similarity)

    async def _read(self, entry_key: str | bytes, similarity: float) -> CachedAnswer | None:
        # The Redis client returns bytes (no `decode_responses`).
        entry = cast(dict[bytes, bytes], await self._redis.hgetall(entry_key))
        if not entry:
            return None
        body = json.loads(entry[b"body"])
        body["id"] = f"chatcmpl-{uuid.uuid4().hex}"
        body["created"] = int(time.time())
        return CachedAnswer(
            body=body,
            provider=entry[b"provider"].decode(),
            model=entry[b"model"].decode(),
            similarity=similarity,
        )

    async def _create_index(self, dimensions: int) -> None:
        """Create the vector index of the embedding model, once."""
        name = self._index_name(dimensions)
        if name in self._created_indexes:
            return
        try:
            await self._redis.execute_command(  # type: ignore[no-untyped-call]
                "FT.CREATE", name, "ON", "HASH", "PREFIX", "1", _KEY_PREFIX,
                "SCHEMA", "scope", "TAG", "vector", "VECTOR", "HNSW", "6",
                "TYPE", "FLOAT32", "DIM", str(dimensions), "DISTANCE_METRIC", "COSINE",
            )  # fmt: skip
        except ResponseError as error:
            if "already exists" not in str(error).lower():
                raise
        self._created_indexes.add(name)

    def _index_name(self, dimensions: int) -> str:
        assert self._embedding is not None
        return f"cache-vectors:{self._embedding.model}:{dimensions}"

    def _scope(self, tenant_id: int, alias: str, key: RequestKey) -> str:
        """What a semantic hit must share: tenant, alias, context and embedding model.

        Hashed into one tag, so the query never has to escape alias or model names.
        """
        assert self._embedding is not None
        parts = [str(tenant_id), alias, key.context, self._embedding.model]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


_KEY_PREFIX = "cache:"


def _entry_key(tenant_id: int, alias: str, key: RequestKey) -> str:
    return f"{_KEY_PREFIX}{tenant_id}:{alias}:{key.exact}"


def _packed(vector: list[float]) -> bytes:
    """The vector as Redis vector search reads it: little-endian 32-bit floats."""
    return struct.pack(f"<{len(vector)}f", *vector)


# Keys removed per DEL command, and keys asked per SCAN step, by `ResponseCache.clear`.
_CLEAR_BATCH_SIZE = 500

# `cache:{tenant_id}:{alias}:{exact_hash}`; the alias may itself contain ":".
_ENTRY_KEY = re.compile(rb"cache:(\d+):(.+):[0-9a-f]{64}", re.DOTALL)


def _is_entry_key(key: bytes, tenant_id: int | None, alias: str | None) -> bool:
    """True when `key` is a cache entry of `tenant_id` (any tenant if None) and `alias`."""
    match = _ENTRY_KEY.fullmatch(key)
    if match is None:
        return False
    if tenant_id is not None and int(match[1]) != tenant_id:
        return False
    return alias is None or match[2] == alias.encode()


def _escape_pattern(text: str) -> str:
    """Escape the characters that have a meaning in a Redis SCAN pattern."""
    return "".join(f"\\{char}" if char in "*?[]\\" else char for char in text)
