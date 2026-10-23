"""Remember when the failed sign-ins of an operator started to count.

`failed_attempts` counts the failures since `first_failure_at`. A failure more
than 15 minutes after it starts a new count, so old failures stop counting.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL while `failed_attempts` is 0.
    op.add_column(
        "operators",
        sa.Column("first_failure_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("operators", "first_failure_at")
