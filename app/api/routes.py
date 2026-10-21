"""HTTP routes of the gateway."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request

from app.config import GatewayConfig

router = APIRouter()


def get_config(request: Request) -> GatewayConfig:
    """Return the gateway configuration loaded at startup."""
    return cast(GatewayConfig, request.app.state.config)


@router.get("/health")
async def health(config: Annotated[GatewayConfig, Depends(get_config)]) -> dict[str, Any]:
    """Report that the gateway is up and which providers are usable."""
    return {
        "status": "ok",
        "providers": {
            "enabled": list(config.enabled_providers),
            "disabled": list(config.disabled_providers),
        },
        "routes": {
            alias: [target.name for target in targets] for alias, targets in config.routes.items()
        },
    }
