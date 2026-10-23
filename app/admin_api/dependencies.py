"""What the routes of the admin API need: the admin key check, the database, Redis, the config."""

from typing import Annotated, cast

from fastapi import Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.authenticator import Authenticator
from app.config import GatewayConfig
from app.storage.admin_keys import AdminIdentity


def get_admin_authenticator(request: Request) -> Authenticator[AdminIdentity]:
    """Return the admin key checker built at startup."""
    return cast(Authenticator[AdminIdentity], request.app.state.admin_authenticator)


async def authenticate_admin(
    request: Request,
    authenticator: Annotated[Authenticator[AdminIdentity], Depends(get_admin_authenticator)],
    authorization: Annotated[str | None, Header()] = None,
) -> AdminIdentity:
    """Check the admin key of the request (`Authorization: Bearer gwa_...`)."""
    client_ip = request.client.host if request.client else "unknown address"
    return await authenticator.authenticate(authorization, client_ip)


def get_database(request: Request) -> AsyncEngine:
    """Return the PostgreSQL engine built at startup."""
    return cast(AsyncEngine, request.app.state.database_engine)


def get_redis(request: Request) -> Redis:
    """Return the Redis client built at startup (short timeouts, no retries)."""
    return cast(Redis, request.app.state.redis)


def get_config(request: Request) -> GatewayConfig:
    """Return the gateway configuration loaded at startup."""
    return cast(GatewayConfig, request.app.state.config)


Admin = Annotated[AdminIdentity, Depends(authenticate_admin)]
Database = Annotated[AsyncEngine, Depends(get_database)]
RedisClient = Annotated[Redis, Depends(get_redis)]
Config = Annotated[GatewayConfig, Depends(get_config)]
