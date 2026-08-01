"""Initial built-in auth schema: users, roles, permissions, sessions.

Revision ID: 0001
Revises:
Create Date: 2026-07-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rakit_auth_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("username", sa.String(150), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rakit_auth_users_email", "rakit_auth_users", ["email"], unique=True)
    op.create_index("ix_rakit_auth_users_username", "rakit_auth_users", ["username"], unique=True)

    op.create_table(
        "rakit_auth_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False, unique=True),
    )

    op.create_table(
        "rakit_auth_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("group", sa.String(255), nullable=False),
        sa.Column("orphaned", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_rakit_auth_permissions_key", "rakit_auth_permissions", ["key"], unique=True)

    op.create_table(
        "rakit_auth_user_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("rakit_auth_users.id"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("rakit_auth_roles.id"), primary_key=True),
    )

    op.create_table(
        "rakit_auth_role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("rakit_auth_roles.id"), primary_key=True),
        sa.Column(
            "permission_id",
            sa.Integer(),
            sa.ForeignKey("rakit_auth_permissions.id"),
            primary_key=True,
        ),
    )

    op.create_table(
        "rakit_auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("rakit_auth_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_rakit_auth_sessions_token_hash"),
    )
    op.create_index("ix_rakit_auth_sessions_token_hash", "rakit_auth_sessions", ["token_hash"])
    op.create_index("ix_rakit_auth_sessions_user_id", "rakit_auth_sessions", ["user_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Rakit auth migrations are forward-only; downgrade is not supported."
    )
