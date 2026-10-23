"""Record what the response cache did for each request.

`cache` is `hit`, `miss`, `bypass` or `unavailable` on every row of a request
whose alias uses the cache, and NULL otherwise. A hit is one row with outcome
`cache_hit`; its `cache_similarity` is 1.0 for an identical request, or the
cosine similarity of the two questions.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usage_log", sa.Column("cache", sa.String(16), nullable=True))
    op.add_column("usage_log", sa.Column("cache_similarity", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("usage_log", "cache_similarity")
    op.drop_column("usage_log", "cache")
