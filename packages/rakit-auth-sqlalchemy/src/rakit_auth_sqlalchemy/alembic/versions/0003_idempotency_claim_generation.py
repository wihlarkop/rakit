"""Fence idempotency leases against stale workers.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rakit_auth_idempotency",
        sa.Column("claim_generation", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    raise RuntimeError("Rakit auth migrations are forward-only; downgrade is not supported.")
