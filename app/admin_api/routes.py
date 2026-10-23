"""HTTP routes of the admin API. Every route under `/admin/v1` needs an admin key."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, Request

from app.admin_api.schemas import Health, Me
from app.auth.authenticator import Authenticator
from app.storage.admin_keys import AdminIdentity

router = APIRouter()


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


Admin = Annotated[AdminIdentity, Depends(authenticate_admin)]


@router.get("/health")
async def health() -> Health:
    """Report that the admin API is up. Used by the Docker health check: no key needed."""
    return Health(status="ok")


@router.get("/admin/v1/me")
async def me(admin: Admin) -> Me:
    """Return the name of the operator who owns the admin key: the dashboard logs in with it."""
    return Me(name=admin.name)
