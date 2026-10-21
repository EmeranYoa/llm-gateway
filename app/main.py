"""FastAPI application factory."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.routes import router, validation_error_handler
from app.config import Settings, load_config
from app.providers.base import Provider
from app.providers.openai_compat import OpenAICompatibleProvider
from app.routing.router import Router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the gateway application.

    Raises `ConfigError` when the gateway configuration is invalid, so the
    gateway never starts with a broken config.
    """
    settings = settings or Settings()
    config = load_config(settings.gateway_config_path, os.environ)
    http_client = httpx.AsyncClient()

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

    app = FastAPI(title="LLM Gateway", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.router = Router(config.routes, providers)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router)
    return app
