"""Response bodies of the admin API.

They are Pydantic models so that FastAPI publishes them in the OpenAPI schema,
from which the dashboard generates its TypeScript types.
"""

from pydantic import BaseModel


class Me(BaseModel):
    """The operator who owns the admin key of the request."""

    name: str


class Health(BaseModel):
    status: str
