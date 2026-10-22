"""Check the gateway API key of each request."""

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.keys import KEY_PREFIX
from app.storage.tenants import KeyOwner, find_key_owner

logger = logging.getLogger(__name__)


class InvalidApiKey(Exception):
    """The request has no API key, or an unknown or revoked one."""


class AuthenticationUnavailable(Exception):
    """The key could not be checked because PostgreSQL is unavailable.

    The request is refused: an unchecked key is never accepted (ADR 0004).
    """


class Authenticator:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def authenticate(self, authorization: str | None) -> KeyOwner:
        """Return the owner of the key in an `Authorization: Bearer <key>` header.

        Raises `InvalidApiKey` or `AuthenticationUnavailable`.
        """
        key = _bearer_key(authorization)
        if key is None:
            raise InvalidApiKey
        try:
            owner = await find_key_owner(self._engine, key)
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            logger.warning(
                "cannot check API keys, PostgreSQL is unavailable (%s)", type(error).__name__
            )
            raise AuthenticationUnavailable from error
        if owner is None:
            raise InvalidApiKey
        return owner


def _bearer_key(authorization: str | None) -> str | None:
    """Extract a gateway key from an `Authorization` header value, or return None."""
    if authorization is None:
        return None
    scheme, _, key = authorization.partition(" ")
    key = key.strip()
    if scheme.lower() != "bearer" or not key.startswith(KEY_PREFIX):
        return None
    return key
