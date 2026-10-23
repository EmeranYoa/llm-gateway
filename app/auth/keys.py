"""Gateway API keys: generation and hashing.

A key looks like `gw_` + 32 random bytes in URL-safe base64. Only its SHA-256
hash is stored. A slow hash such as bcrypt is not needed: the key is a long
random secret, not a password a person chose, and a slow hash would add tens
of milliseconds to every request.
"""

import hashlib
import secrets

KEY_PREFIX = "gw_"

# Characters shown by `list-keys` to recognise a key without revealing it.
DISPLAY_PREFIX_LENGTH = len(KEY_PREFIX) + 6


def generate_key() -> str:
    """Return a new random gateway API key."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    """Return the SHA-256 hash of `key`, as stored in the database."""
    return hashlib.sha256(key.encode()).hexdigest()


def display_prefix(key: str) -> str:
    """Return the start of `key`, safe to show and to store in clear."""
    return key[:DISPLAY_PREFIX_LENGTH]
