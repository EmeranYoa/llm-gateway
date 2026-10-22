"""Add the per-tenant requests-per-minute limit.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL means "use tenants.default_limits.rpm from gateway.yaml".
    op.add_column("tenants", sa.Column("rpm", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "rpm")
