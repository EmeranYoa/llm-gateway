"""Check the gateway API key of each request."""

import logging
import math
import time
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.keys import KEY_PREFIX, hash_key
from app.storage.tenants import KeyOwner, find_key_owner

logger = logging.getLogger(__name__)


class InvalidApiKey(Exception):
    """The request has no API key, or an unknown or revoked one."""


class AuthenticationUnavailable(Exception):
    """The key could not be checked because PostgreSQL is unavailable.

    The request is refused: an unchecked key is never accepted (ADR 0004).
    """


@dataclass(frozen=True)
class _VerifiedKey:
    """A key found valid in the database, and when (monotonic clock, in seconds)."""

    owner: KeyOwner
    verified_at: float


class Authenticator:
    """Check API keys against PostgreSQL, with an in-memory cache of verified keys.

    The cache belongs to one gateway instance. A key verified less than `cache_ttl`
    seconds ago is accepted without a database query. When PostgreSQL is unavailable,
    a key verified less than `grace_period` seconds ago is still accepted; any other
    key is refused (ADR 0004).
    """

    def __init__(self, engine: AsyncEngine, *, cache_ttl: float, grace_period: float) -> None:
        self._engine = engine
        self._cache_ttl = cache_ttl
        self._grace_period = grace_period
        # Keyed by the hash of the key: the cache never holds a key in clear.
        self._verified: dict[str, _VerifiedKey] = {}

    async def authenticate(self, authorization: str | None, client_ip: str) -> KeyOwner:
        """Return the owner of the key in an `Authorization: Bearer <key>` header.

        `client_ip` is only used to log refused requests. Raises `InvalidApiKey`
        or `AuthenticationUnavailable`.
        """
        key = _bearer_key(authorization)
        if key is None:
            _log_refused(client_ip, "missing or malformed API key")
            raise InvalidApiKey
        key_hash = hash_key(key)
        now = time.monotonic()
        cached = self._verified.get(key_hash)
        age = now - cached.verified_at if cached is not None else math.inf
        if cached is not None and age < self._cache_ttl:
            return cached.owner
        try:
            owner = await find_key_owner(self._engine, key)
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            reason = type(error).__name__
            if cached is not None and age < self._grace_period:
                logger.warning(
                    "cannot check API keys, PostgreSQL is unavailable (%s): accepting a key"
                    " verified %d s ago (grace period)",
                    reason,
                    age,
                )
                return cached.owner
            logger.warning("cannot check API keys, PostgreSQL is unavailable (%s)", reason)
            raise AuthenticationUnavailable from error
        if owner is None:
            # A key found revoked is never trusted again, even during a database outage.
            self._verified.pop(key_hash, None)
            _log_refused(client_ip, "unknown or revoked API key")
            raise InvalidApiKey
        self._verified[key_hash] = _VerifiedKey(owner, verified_at=now)
        return owner


def _log_refused(client_ip: str, reason: str) -> None:
    """Log a refused request. Never log any part of the key, even of an invalid one."""
    logger.warning("refused a request from %s: %s", client_ip, reason)


def _bearer_key(authorization: str | None) -> str | None:
    """Extract a gateway key from an `Authorization` header value, or return None."""
    if authorization is None:
        return None
    scheme, _, key = authorization.partition(" ")
    key = key.strip()
    if scheme.lower() != "bearer" or not key.startswith(KEY_PREFIX):
        return None
    return key
