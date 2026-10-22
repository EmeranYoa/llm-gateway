"""Add the per-tenant daily token budget.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL means "use tenants.default_limits.tokens_per_day from gateway.yaml".
    op.add_column("tenants", sa.Column("tokens_per_day", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "tokens_per_day")
