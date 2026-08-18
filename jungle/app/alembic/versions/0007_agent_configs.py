"""Agent tool configuration (spec 008)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False for the same reason as 0005: `op.create_table` would otherwise
# emit its own CREATE TYPE, colliding with the explicit idempotent creation below —
# and creating them explicitly is what lets `downgrade` drop them again.
CONTENT_KIND = postgresql.ENUM(
    "text", "binary", "too_large", name="agent_content_kind", create_type=False
)
CONFIG_STATUS = postgresql.ENUM(
    "synced", "removed", name="agent_config_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    CONTENT_KIND.create(bind, checkfirst=True)
    CONFIG_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "agent_configs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("machine", sa.String(length=128), nullable=False),
        # A validated String rather than a third enum: `global` cannot be a Python
        # enum member name, and the workaround (values_callable) is a mapping the
        # test suite cannot exercise, since every test fakes the database.
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        # Empty string, never null, when the scope is global: Postgres treats nulls
        # as distinct, so a nullable column here would not constrain the address.
        sa.Column("project", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("tool", sa.String(length=32), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        # Digest of the content as RECEIVED, before redaction — change detection has
        # to work on the machine's real bytes even though those are not what is kept.
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_kind", CONTENT_KIND, nullable=False, server_default="text"),
        sa.Column("redactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", CONFIG_STATUS, nullable=False, server_default="synced"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "machine", "scope_kind", "project", "tool", "path", name="uq_agent_configs_address"
        ),
    )
    op.create_index(
        "ix_agent_configs_branch", "agent_configs", ["machine", "scope_kind", "project", "tool"]
    )
    op.create_index("ix_agent_configs_synced", "agent_configs", ["last_synced_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_configs_synced", table_name="agent_configs")
    op.drop_index("ix_agent_configs_branch", table_name="agent_configs")
    op.drop_table("agent_configs")
    bind = op.get_bind()
    CONFIG_STATUS.drop(bind, checkfirst=True)
    CONTENT_KIND.drop(bind, checkfirst=True)
