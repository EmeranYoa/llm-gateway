"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.routes import router


def create_app() -> FastAPI:
    """Build the gateway application."""
    app = FastAPI(title="LLM Gateway", version="0.1.0")
    app.include_router(router)
    return app
