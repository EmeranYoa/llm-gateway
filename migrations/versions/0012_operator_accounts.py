"""Replace admin keys with operator accounts: a username, a password and sessions.

Creates `operators` and `operator_sessions`, links `admin_actions` to an operator
instead of an admin key, and drops `admin_keys`. Existing actions keep their
`actor` text; their link becomes NULL.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operators",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        # Stored as typed; unique whatever the case (index below).
        sa.Column("username", sa.Text(), nullable=False),
        # scrypt hash with its salt and parameters (app/auth/passwords.py). Never the password.
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Language of the dashboard chosen by the operator; NULL: the browser's language.
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "operators_username_lower_key", "operators", [sa.text("lower(username)")], unique=True
    )
    op.create_table(
        "operator_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        # SHA-256 of the session token, in hex. The token itself is never stored.
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "operator_id",
            sa.BigInteger(),
            sa.ForeignKey("operators.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.drop_column("admin_actions", "admin_key_id")
    # The operator who made the change; NULL for the admin CLI, the first setup and
    # the actions recorded with admin keys before this migration.
    op.add_column(
        "admin_actions",
        sa.Column(
            "operator_id",
            sa.BigInteger(),
            sa.ForeignKey("operators.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.drop_table("admin_keys")


def downgrade() -> None:
    # Admin keys cannot be brought back: the table returns empty, and operators,
    # their sessions and the link of actions to them are lost.
    op.create_table(
        "admin_keys",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column("admin_actions", "operator_id")
    op.add_column(
        "admin_actions",
        sa.Column("admin_key_id", sa.BigInteger(), sa.ForeignKey("admin_keys.id"), nullable=True),
    )
    op.drop_table("operator_sessions")
    op.drop_index("operators_username_lower_key", table_name="operators")
    op.drop_table("operators")
