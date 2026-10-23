"""One-time tokens printed in the admin API log: the setup token and the recovery token.

Such a token is random, works once, and only its hash is kept, in memory: it is
never stored in the database, and a restart generates a new one.
"""

import hmac
import secrets

from app.auth.keys import hash_key


class OneTimeToken:
    """A one-time token of this admin API instance. Only its hash is kept."""

    def __init__(self) -> None:
        self._hash: str | None = None

    @property
    def available(self) -> bool:
        """True from its generation until it is consumed."""
        return self._hash is not None

    def generate(self) -> str:
        """Generate a new token, replacing any previous one, and return it."""
        token = secrets.token_urlsafe(32)
        self._hash = hash_key(token)
        return token

    def matches(self, token: str) -> bool:
        """Return True when `token` is the current token. Constant-time comparison."""
        return self._hash is not None and hmac.compare_digest(self._hash, hash_key(token))

    def consume(self) -> None:
        """Stop accepting the token: it was used."""
        self._hash = None
