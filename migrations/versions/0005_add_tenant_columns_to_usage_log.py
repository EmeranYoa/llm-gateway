"""Record which tenant and which API key each usage row belongs to.

`provider` and `model` become nullable: a request refused by a tenant quota is
logged without reaching any provider.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: rows written before v0.2.0 have no tenant.
    op.add_column(
        "usage_log",
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=True),
    )
    op.add_column(
        "usage_log",
        sa.Column("api_key_id", sa.BigInteger(), sa.ForeignKey("api_keys.id"), nullable=True),
    )
    # Per-tenant reports filter on the tenant and a time range.
    op.create_index("ix_usage_log_tenant_id_created_at", "usage_log", ["tenant_id", "created_at"])
    op.create_index("ix_usage_log_api_key_id", "usage_log", ["api_key_id"])
    op.alter_column("usage_log", "provider", existing_type=sa.Text(), nullable=True)
    op.alter_column("usage_log", "model", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # Rows without a provider cannot satisfy NOT NULL again: they are tenant quota refusals.
    op.execute("DELETE FROM usage_log WHERE provider IS NULL OR model IS NULL")
    op.alter_column("usage_log", "model", existing_type=sa.Text(), nullable=False)
    op.alter_column("usage_log", "provider", existing_type=sa.Text(), nullable=False)
    op.drop_index("ix_usage_log_api_key_id", table_name="usage_log")
    op.drop_index("ix_usage_log_tenant_id_created_at", table_name="usage_log")
    op.drop_column("usage_log", "api_key_id")
    op.drop_column("usage_log", "tenant_id")
