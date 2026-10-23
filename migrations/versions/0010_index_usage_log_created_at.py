"""Index the usage log by date.

The statistics of the admin API read every row of a period, for all tenants at
once. The index on (tenant_id, created_at) only helps the per-tenant reports.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_usage_log_created_at", "usage_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_log_created_at", table_name="usage_log")
