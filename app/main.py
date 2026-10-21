"""FastAPI application factory."""

import os

from fastapi import FastAPI

from app.api.routes import router
from app.config import Settings, load_config


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the gateway application.

    Raises `ConfigError` when the gateway configuration is invalid, so the
    gateway never starts with a broken config.
    """
    settings = settings or Settings()
    config = load_config(settings.gateway_config_path, os.environ)

    app = FastAPI(title="LLM Gateway", version="0.1.0")
    app.state.config = config
    app.include_router(router)
    return app
