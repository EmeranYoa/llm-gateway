"""Create the admin_actions table: the history of what operators changed.

One row per change made with the admin API or the admin CLI (keys created or
revoked, limits set, cached answers removed). Never a key value.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # The admin key of the operator; NULL when the action came from the admin CLI.
        sa.Column("admin_key_id", sa.BigInteger(), sa.ForeignKey("admin_keys.id"), nullable=True),
        # The name of that admin key, or `cli`.
        sa.Column("actor", sa.Text(), nullable=False),
        # Text, not a PostgreSQL enum, so new kinds of actions need no migration.
        sa.Column("action", sa.String(32), nullable=False),
        # Tenant name or key id; NULL when the action concerns every tenant.
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("admin_actions")
