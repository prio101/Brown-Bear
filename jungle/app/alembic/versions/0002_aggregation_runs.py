"""Aggregation run tracking

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# period_type already exists from 0001 — reference it, never re-create it.
period_type = postgresql.ENUM(
    "hourly", "daily", "weekly", "monthly", name="period_type", create_type=False
)
run_status = postgresql.ENUM(
    "running", "completed", "failed", name="run_status", create_type=False
)


def upgrade() -> None:
    run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "aggregation_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("period_type", period_type, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_aggregation_runs_period_window",
        "aggregation_runs",
        ["period_type", "status", "window_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_aggregation_runs_period_window", table_name="aggregation_runs")
    op.drop_table("aggregation_runs")
    run_status.drop(op.get_bind(), checkfirst=True)
