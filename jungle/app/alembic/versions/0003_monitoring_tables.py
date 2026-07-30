"""Monitoring tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("cpu_percent", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("memory_percent", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("memory_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("disk_percent", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("disk_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("disk_total_bytes", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_system_snapshots_timestamp", "system_snapshots", ["timestamp"])

    op.create_table(
        "cache_samples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("keyspace_hits", sa.BigInteger(), nullable=False),
        sa.Column("keyspace_misses", sa.BigInteger(), nullable=False),
        sa.Column("evicted_keys", sa.BigInteger(), nullable=False),
        sa.Column("expired_keys", sa.BigInteger(), nullable=False),
        sa.Column("used_memory_bytes", sa.BigInteger(), nullable=False),
        sa.Column("connected_clients", sa.Integer(), nullable=False),
        sa.Column("total_keys", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cache_samples_timestamp", "cache_samples", ["timestamp"])

    op.create_table(
        "query_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("collection", sa.String(length=256), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_query_logs_collection_timestamp", "query_logs", ["collection", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_query_logs_collection_timestamp", table_name="query_logs")
    op.drop_table("query_logs")
    op.drop_index("ix_cache_samples_timestamp", table_name="cache_samples")
    op.drop_table("cache_samples")
    op.drop_index("ix_system_snapshots_timestamp", table_name="system_snapshots")
    op.drop_table("system_snapshots")
