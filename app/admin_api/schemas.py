"""Response bodies of the admin API.

They are Pydantic models so that FastAPI publishes them in the OpenAPI schema,
from which the dashboard generates its TypeScript types.
"""

import datetime as dt

from pydantic import BaseModel


class Me(BaseModel):
    """The operator signed in with the session of the request."""

    username: str
    must_change_password: bool
    """True when the operator must choose a new password before anything else."""
    language: str | None
    """Language of the dashboard chosen by the operator; null: the browser's language."""


class Session(BaseModel):
    """A session just opened. This is the only time the `token` is shown.

    Send it as `Authorization: Bearer <token>` on every other admin request.
    """

    token: str
    username: str
    """As typed when the account was created."""
    expires_at: dt.datetime
    """The session ends then, 8 hours after sign-in, unless the operator signs out first."""


class SetupStatus(BaseModel):
    open: bool
    """True while no operator account exists: the first one can be created with the setup token."""


class Health(BaseModel):
    status: str
