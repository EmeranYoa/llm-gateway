"""Record what each usage row cost, and what each cache hit saved.

`cost_usd` is computed from the real token usage and the price of the model in
`gateway.yaml` when the row is written. It is NULL when the model has no price
or the row has no token counts, and 0 for a cache hit. `saved_cost_usd` is set
on cache hits only: what the cached answer cost when a provider generated it.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usage_log", sa.Column("cost_usd", sa.Numeric(16, 8), nullable=True))
    op.add_column("usage_log", sa.Column("saved_cost_usd", sa.Numeric(16, 8), nullable=True))


def downgrade() -> None:
    op.drop_column("usage_log", "saved_cost_usd")
    op.drop_column("usage_log", "cost_usd")
