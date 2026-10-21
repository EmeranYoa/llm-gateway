"""HTTP routes of the gateway."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the gateway process is up."""
    return {"status": "ok"}
