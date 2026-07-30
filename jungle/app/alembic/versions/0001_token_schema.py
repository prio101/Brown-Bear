"""Baseline: token accounting schema

Revision ID: 0001
Revises:
Create Date: 2026-07-30

"""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: the types are created once, explicitly, below. Without it
# every create_table referencing an enum re-issues CREATE TYPE and the second
# table fails with DuplicateObject.
token_source = postgresql.ENUM(
    "local_ollama", "remote_api", name="token_source", create_type=False
)
period_type = postgresql.ENUM(
    "hourly", "daily", "weekly", "monthly", name="period_type", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    token_source.create(bind, checkfirst=True)
    period_type.create(bind, checkfirst=True)

    op.create_table(
        "token_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("source", token_source, nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_token_events_request_id"),
    )
    op.create_index(
        "ix_token_events_ts_model_source", "token_events", ["timestamp", "model", "source"]
    )

    op.create_table(
        "token_periods",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("period_type", period_type, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("source", token_source, nullable=False),
        sa.Column("total_tokens_in", sa.BigInteger(), nullable=False),
        sa.Column("total_tokens_out", sa.BigInteger(), nullable=False),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_cost_usd", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "period_type", "period_start", "model", "source", name="uq_token_periods_bucket"
        ),
    )
    op.create_index("ix_token_periods_lookup", "token_periods", ["period_type", "period_start"])

    op.create_table(
        "model_pricing",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("input_cost_per_1k", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("output_cost_per_1k", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_name", "effective_date", name="uq_model_pricing_effective"),
    )
    op.create_index("ix_model_pricing_active", "model_pricing", ["model_name", "is_active"])

    # Defaults from spec 003 §3.5: local models are free, remote models are not.
    op.bulk_insert(
        sa.table(
            "model_pricing",
            sa.column("model_name", sa.String),
            sa.column("input_cost_per_1k", sa.Numeric),
            sa.column("output_cost_per_1k", sa.Numeric),
            sa.column("currency", sa.String),
            sa.column("effective_date", sa.Date),
            sa.column("is_active", sa.Boolean),
        ),
        [
            {
                "model_name": name,
                "input_cost_per_1k": inp,
                "output_cost_per_1k": out,
                "currency": "USD",
                "effective_date": date(2026, 1, 1),
                "is_active": True,
            }
            for name, inp, out in [
                ("*", "0", "0"),  # fallback: anything unpriced is free
                ("gpt-4", "0.03", "0.06"),
                ("gpt-4o", "0.005", "0.015"),
                ("claude-opus-5", "0.015", "0.075"),
                ("claude-sonnet-5", "0.003", "0.015"),
            ]
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_model_pricing_active", table_name="model_pricing")
    op.drop_table("model_pricing")
    op.drop_index("ix_token_periods_lookup", table_name="token_periods")
    op.drop_table("token_periods")
    op.drop_index("ix_token_events_ts_model_source", table_name="token_events")
    op.drop_table("token_events")
    bind = op.get_bind()
    period_type.drop(bind, checkfirst=True)
    token_source.drop(bind, checkfirst=True)
