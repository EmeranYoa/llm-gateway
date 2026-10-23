"""Stored answers in Redis, one hash per entry, isolated per tenant and alias.

An entry keeps the response body and the target that generated it, never the
text of the messages: lookups only use the hashes of `keys.py`. Each entry
expires after the TTL of its alias; a hit does not extend it.
"""

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis

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


class ResponseCache:
    """The response cache of the aliases listed in the `cache` section of the config."""

    def __init__(self, redis: Redis, cached_aliases: Mapping[str, AliasCache]) -> None:
        self._redis = redis
        self._cached_aliases = cached_aliases

    def covers(self, alias: str) -> bool:
        """True when `alias` uses the cache."""
        return alias in self._cached_aliases

    async def lookup(self, tenant_id: int, alias: str, key: RequestKey) -> CachedAnswer | None:
        """Return the stored answer of an identical request of the tenant, or None."""
        # The Redis client returns bytes (no `decode_responses`).
        entry = cast(
            dict[bytes, bytes], await self._redis.hgetall(_entry_key(tenant_id, alias, key))
        )
        if not entry:
            return None
        body = json.loads(entry[b"body"])
        body["id"] = f"chatcmpl-{uuid.uuid4().hex}"
        body["created"] = int(time.time())
        return CachedAnswer(
            body=body, provider=entry[b"provider"].decode(), model=entry[b"model"].decode()
        )

    async def store(
        self,
        tenant_id: int,
        alias: str,
        key: RequestKey,
        body: Mapping[str, Any],
        target: Target,
    ) -> None:
        """Keep the answer `body` that `target` generated, until the TTL of `alias` runs out."""
        entry_key = _entry_key(tenant_id, alias, key)
        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.hset(
                entry_key,
                mapping={
                    "body": json.dumps(body, separators=(",", ":")),
                    "provider": target.provider.name,
                    "model": target.model,
                    "context": key.context,
                    "created_at": time.time(),
                },
            )
            pipeline.pexpire(entry_key, round(self._cached_aliases[alias].ttl * 1000))
            await pipeline.execute()


def _entry_key(tenant_id: int, alias: str, key: RequestKey) -> str:
    return f"cache:{tenant_id}:{alias}:{key.exact}"
