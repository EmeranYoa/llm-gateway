"""FastAPI application factory."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.routes import router, validation_error_handler
from app.config import Settings, load_config
from app.providers.base import Provider
from app.providers.openai_compat import OpenAICompatibleProvider
from app.routing.router import Router
from app.storage.usage import UsageLog


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the gateway application.

    Raises `ConfigError` when the gateway configuration is invalid, so the
    gateway never starts with a broken config.
    """
    settings = settings or Settings()
    config = load_config(settings.gateway_config_path, os.environ)
    http_client = httpx.AsyncClient()
    # The engine connects lazily: the gateway starts even when PostgreSQL is down.
    database_engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.database_timeout,
            "command_timeout": settings.database_timeout,
        },
    )

    providers: dict[str, Provider] = {}
    for targets in config.routes.values():
        for target in targets:
            providers.setdefault(
                target.provider.name, OpenAICompatibleProvider(target.provider, http_client)
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await http_client.aclose()
        await database_engine.dispose()

    app = FastAPI(title="LLM Gateway", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.router = Router(
        config.routes,
        providers,
        deadline=config.deadline,
        min_attempt_time=config.min_attempt_time,
    )
    app.state.usage_log = UsageLog(database_engine)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router)
    return app
