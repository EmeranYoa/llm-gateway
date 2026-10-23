"""What the routes of the admin API need: the session check, the database, Redis, the config."""

import logging
from typing import Annotated, cast

from fastapi import Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.authenticator import AuthenticationUnavailable
from app.auth.sessions import InvalidSession, bearer_session_token
from app.config import GatewayConfig
from app.storage.operators import OperatorIdentity, find_session_operator

logger = logging.getLogger(__name__)


def get_database(request: Request) -> AsyncEngine:
    """Return the PostgreSQL engine built at startup."""
    return cast(AsyncEngine, request.app.state.database_engine)


def get_redis(request: Request) -> Redis:
    """Return the Redis client built at startup (short timeouts, no retries)."""
    return cast(Redis, request.app.state.redis)


def get_config(request: Request) -> GatewayConfig:
    """Return the gateway configuration loaded at startup."""
    return cast(GatewayConfig, request.app.state.config)


Database = Annotated[AsyncEngine, Depends(get_database)]
RedisClient = Annotated[Redis, Depends(get_redis)]
Config = Annotated[GatewayConfig, Depends(get_config)]


async def authenticate_operator(
    request: Request,
    database: Database,
    authorization: Annotated[str | None, Header()] = None,
) -> OperatorIdentity:
    """Check the session token of the request (`Authorization: Bearer gws_...`).

    The session is looked up in PostgreSQL on every request, with no cache, so a
    sign-out or a disabled account takes effect at once. When PostgreSQL is
    unavailable the request is refused (fail closed): a session that cannot be
    checked is never accepted. Raises `InvalidSession` or `AuthenticationUnavailable`.
    """
    client_ip = request.client.host if request.client else "unknown address"
    token = bearer_session_token(authorization)
    if token is None:
        _log_refused(client_ip, "missing or malformed session token")
        raise InvalidSession
    try:
        operator = await find_session_operator(database, token)
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        logger.warning(
            "cannot check sessions, PostgreSQL is unavailable (%s)", type(error).__name__
        )
        raise AuthenticationUnavailable from error
    if operator is None:
        _log_refused(client_ip, "unknown or expired session, or disabled account")
        raise InvalidSession
    return operator


def _log_refused(client_ip: str, reason: str) -> None:
    """Log a refused request. Never log any part of the token, even of an invalid one."""
    logger.warning("refused an admin request from %s: %s", client_ip, reason)


Admin = Annotated[OperatorIdentity, Depends(authenticate_operator)]
"""The operator signed in on the request. Every route under `/admin/v1` needs one,
except the setup of the first account and the sign-in."""
