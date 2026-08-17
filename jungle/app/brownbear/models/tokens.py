"""Token accounting tables (spec 003 §3.3).

Roadmap decision D1: this schema supersedes the `token_usage` table sketched
in spec 001 §1.2. The dashboard reads these tables rather than defining its own.
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from brownbear.db import Base


class TokenSource(enum.StrEnum):
    """Where the tokens were spent."""

    local_ollama = "local_ollama"
    remote_api = "remote_api"


class PeriodType(enum.StrEnum):
    hourly = "hourly"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class TokenEvent(Base):
    """One raw AI call. Pruned after the retention window (spec 003 §3.7)."""

    __tablename__ = "token_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[TokenSource] = mapped_column(
        Enum(TokenSource, name="token_source", native_enum=True),
        nullable=False,
        default=TokenSource.local_ollama,
    )
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Unique so replayed webhook batches deduplicate (spec 003 §3.2).
    # NULL is allowed many times over — locally proxied calls need no id.
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The input breakdown, when the client supplied one. Their sum is tokens_in.
    # Stored so a cost is auditable rather than one opaque number — without these
    # a wrongly-priced row cannot be recomputed, which is exactly the position the
    # rows written before this change are in.
    tokens_in_fresh: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_cache_write: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_cache_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: "flat" — every input token priced at the base rate. "bucketed" — priced by
    #: bucket. Named rather than inferred: legacy rows are not wrong by accident,
    #: they were written under a different rule, and restating them silently would
    #: be a fabrication.
    pricing_model: Mapped[str] = mapped_column(String(16), nullable=False, default="flat")
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    endpoint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Every dashboard query is a time range filtered by model and/or source
        # (spec 003 implementation notes).
        Index("ix_token_events_ts_model_source", "timestamp", "model", "source"),
        UniqueConstraint("request_id", name="uq_token_events_request_id"),
    )


class TokenPeriod(Base):
    """Rolled-up totals. Outlives the raw events it was built from."""

    __tablename__ = "token_periods"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_type: Mapped[PeriodType] = mapped_column(
        Enum(PeriodType, name="period_type", native_enum=True), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[TokenSource] = mapped_column(
        Enum(TokenSource, name="token_source", native_enum=True), nullable=False
    )
    total_tokens_in: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_tokens_out: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal("0")
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Makes aggregation idempotent: re-running a period upserts one row
        # instead of duplicating it (spec 003 §3.4).
        UniqueConstraint(
            "period_type", "period_start", "model", "source", name="uq_token_periods_bucket"
        ),
        Index("ix_token_periods_lookup", "period_type", "period_start"),
    )


class ModelPricing(Base):
    """Per-model rates. History is kept; `is_active` selects the current row."""

    __tablename__ = "model_pricing"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_cost_per_1k: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal("0")
    )
    output_cost_per_1k: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    # Prompt-caching multipliers against input_cost_per_1k (spec 003 §3.5 rev 2).
    #
    # Providers do not bill the three input buckets alike: a cache *write* costs
    # more than fresh input because the entry must be created, and a cache *read*
    # costs a fraction because nothing is reprocessed. Anthropic's published
    # figures are 1.25x and 0.10x, which are the defaults here.
    #
    # Multipliers rather than three absolute rates: they track the base rate when
    # it changes, and a provider that bills cache reads at par needs one row edited
    # to 1.0 rather than three kept in sync.
    cache_write_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, default=Decimal("1.25")
    )
    cache_read_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, default=Decimal("0.10")
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("model_name", "effective_date", name="uq_model_pricing_effective"),
        Index("ix_model_pricing_active", "model_name", "is_active"),
    )
