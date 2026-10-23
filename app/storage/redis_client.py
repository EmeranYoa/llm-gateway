"""The Redis client of the gateway and of the admin API."""

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    """A Redis client with short timeouts and no retries.

    When Redis is down, the gateway must notice quickly and route without it
    (ADR 0002), instead of slowing every request down.
    """
    return Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_timeout,
        socket_connect_timeout=settings.redis_timeout,
        retry=Retry(NoBackoff(), retries=0),
    )
