"""Session tokens of operators, which open the admin API.

An operator signs in with a username and a password and gets a session token:
`gws_` + 32 random bytes in URL-safe base64. The prefixes `gws_` and `gw_` (tenant
keys) never overlap, and each side only looks up its own prefix: a session token
never opens the gateway, and a tenant key never opens the admin API.

Like API keys, only the SHA-256 hash of a token is stored (`app/auth/keys.py`):
the token is a long random secret, so a slow hash is not needed.
"""

import datetime as dt
import secrets

SESSION_TOKEN_PREFIX = "gws_"

SESSION_LIFETIME = dt.timedelta(hours=8)
"""A session ends 8 hours after sign-in, or earlier when the operator signs out."""


class InvalidSession(Exception):
    """The request has no session token, or an unknown or expired one, or the
    operator's account is disabled."""


def generate_session_token() -> str:
    """Return a new random session token."""
    return SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)


def bearer_session_token(authorization: str | None) -> str | None:
    """Extract a session token from an `Authorization: Bearer <token>` header, or return None."""
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith(SESSION_TOKEN_PREFIX):
        return None
    return token
