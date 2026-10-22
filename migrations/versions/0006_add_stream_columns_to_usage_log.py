"""Record whether each request was streamed, and its time to first content.

`latency_ms` keeps its meaning: the total duration of the attempt, which for
a stream lasts until its end.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rows written before v0.3.0 were never streamed.
    op.add_column(
        "usage_log",
        sa.Column("stream", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # NULL for every row except the attempt that answered a streamed request.
    op.add_column("usage_log", sa.Column("first_token_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("usage_log", "first_token_ms")
    op.drop_column("usage_log", "stream")
