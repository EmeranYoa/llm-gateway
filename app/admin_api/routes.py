"""HTTP routes of the admin API. Every route under `/admin/v1` needs an admin key."""

from fastapi import APIRouter

from app.admin_api.dependencies import Admin
from app.admin_api.schemas import Health, Me

router = APIRouter()


@router.get("/health")
async def health() -> Health:
    """Report that the admin API is up. Used by the Docker health check: no key needed."""
    return Health(status="ok")


@router.get("/admin/v1/me")
async def me(admin: Admin) -> Me:
    """Return the name of the operator who owns the admin key: the dashboard logs in with it."""
    return Me(name=admin.name)
