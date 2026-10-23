"""HTTP routes of the admin API. Every route under `/admin/v1` needs a session,
except the setup of the first account and the sign-in (`setup.py`, `sessions.py`)."""

from fastapi import APIRouter

from app.admin_api.dependencies import SignedIn
from app.admin_api.schemas import Health, Me

router = APIRouter()


@router.get("/health")
async def health() -> Health:
    """Report that the admin API is up. Used by the Docker health check: no session needed."""
    return Health(status="ok")


@router.get("/admin/v1/me")
async def me(admin: SignedIn) -> Me:
    """Describe the operator signed in with the session of the request.

    Allowed during a forced password change: the dashboard reads it to know.
    """
    return Me(
        username=admin.username,
        must_change_password=admin.must_change_password,
        language=admin.language,
    )
