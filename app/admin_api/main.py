"""Admin API application factory.

The admin API is a separate application from the gateway. It shares their
configuration, PostgreSQL and Redis, but runs in its own process, on an internal
port that Docker Compose never publishes:

    uvicorn app.admin_api.main:create_admin_app --factory --port 8001

So even a leaked admin key is useless from outside the internal network, and its
heavy statistics queries never slow down the chat traffic of the gateway.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.admin_api.routes import router
from app.api.routes import (
    authentication_unavailable_handler,
    invalid_api_key_handler,
    validation_error_handler,
)
from app.auth.authenticator import AuthenticationUnavailable, Authenticator, InvalidApiKey
from app.auth.keys import ADMIN_KEY_PREFIX
from app.config import Settings, load_config
from app.storage.admin_keys import find_admin
from app.storage.db import create_database_engine


def create_admin_app(settings: Settings | None = None) -> FastAPI:
    """Build the admin API application.

    Raises `ConfigError` when the gateway configuration is invalid, like the gateway.
    """
    settings = settings or Settings()
    config = load_config(settings.gateway_config_path, os.environ)
    database_engine = create_database_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await database_engine.dispose()

    app = FastAPI(title="LLM Gateway admin API", version="0.5.0", lifespan=lifespan)
    app.state.config = config
    app.state.admin_authenticator = Authenticator(
        database_engine,
        key_prefix=ADMIN_KEY_PREFIX,
        find_owner=find_admin,
        cache_ttl=settings.auth_cache_ttl,
        grace_period=settings.auth_grace_period,
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(InvalidApiKey, invalid_api_key_handler)
    app.add_exception_handler(AuthenticationUnavailable, authentication_unavailable_handler)
    app.include_router(router)
    return app
