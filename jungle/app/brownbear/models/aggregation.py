"""Aggregation run tracking (spec 003 §3.4).

History is kept rather than one row per bucket: when a rollup produces a
surprising number, the question is always "did that window run, and when" —
which a single mutable last_run column cannot answer.
"""

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from brownbear.db import Base
from brownbear.models.tokens import PeriodType


class RunStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"


class AggregationRun(Base):
    __tablename__ = "aggregation_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_type: Mapped[PeriodType] = mapped_column(
        Enum(PeriodType, name="period_type", native_enum=True), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status", native_enum=True),
        nullable=False,
        default=RunStatus.running,
    )
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Catch-up asks "what is the newest completed window for this period"
        # on every scheduler tick.
        Index("ix_aggregation_runs_period_window", "period_type", "status", "window_start"),
    )
