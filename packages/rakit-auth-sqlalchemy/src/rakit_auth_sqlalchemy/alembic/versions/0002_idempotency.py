"""Add database-backed idempotency receipts.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rakit_auth_idempotency",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_rakit_auth_idempotency_token_hash"),
    )
    op.create_index(
        "ix_rakit_auth_idempotency_token_hash",
        "rakit_auth_idempotency",
        ["token_hash"],
    )


def downgrade() -> None:
    raise RuntimeError("Rakit auth migrations are forward-only; downgrade is not supported.")
