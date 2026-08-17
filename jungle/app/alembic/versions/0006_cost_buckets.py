"""Bucketed input pricing and context events (spec 003 §3.5 rev 2)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17

Two problems, one migration.

**Cost was overstated.** Providers bill three input buckets at different rates —
fresh at par, cache writes above it, cache reads at a fraction — and every input
token was priced at the base rate. On this instance that reported $887 for a month
whose true figure is several times lower.

**Existing rows cannot be corrected.** The breakdown was never captured: the client
summed the three buckets into one integer before sending. So the rows already
written are marked `pricing_model='flat'` rather than restated. A number that was
computed under a different rule is not the same as a wrong number, and silently
rewriting history would be a fabrication.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- pricing multipliers ------------------------------------------------
    # Defaults are Anthropic's published figures. Applied to every existing row,
    # which is safe: they only take effect for events that carry a bucket
    # breakdown, and no existing event does.
    op.add_column(
        "model_pricing",
        sa.Column(
            "cache_write_multiplier", sa.Numeric(6, 4), nullable=False, server_default="1.25"
        ),
    )
    op.add_column(
        "model_pricing",
        sa.Column(
            "cache_read_multiplier", sa.Numeric(6, 4), nullable=False, server_default="0.10"
        ),
    )

    # --- the input breakdown ------------------------------------------------
    for column in ("tokens_in_fresh", "tokens_cache_write", "tokens_cache_read"):
        op.add_column(
            "token_events", sa.Column(column, sa.Integer(), nullable=False, server_default="0")
        )
    op.add_column(
        "token_events",
        sa.Column("pricing_model", sa.String(length=16), nullable=False, server_default="flat"),
    )

    # --- what the memory served --------------------------------------------
    op.create_table(
        "context_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("project", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("model", sa.String(length=128), nullable=False, server_default="unknown"),
        sa.Column("hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cache_mode", sa.String(length=16), nullable=False, server_default="inject"),
        sa.Column("score", sa.Numeric(8, 6), nullable=True),
        sa.Column("chunks_served", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_served", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_avoided", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_avoided_usd", sa.Numeric(14, 6), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_context_events_ts", "context_events", ["timestamp"])
    op.create_index("ix_context_events_project_ts", "context_events", ["project", "timestamp"])


def downgrade() -> None:
    op.drop_index("ix_context_events_project_ts", table_name="context_events")
    op.drop_index("ix_context_events_ts", table_name="context_events")
    op.drop_table("context_events")
    for column in ("pricing_model", "tokens_cache_read", "tokens_cache_write", "tokens_in_fresh"):
        op.drop_column("token_events", column)
    op.drop_column("model_pricing", "cache_read_multiplier")
    op.drop_column("model_pricing", "cache_write_multiplier")
