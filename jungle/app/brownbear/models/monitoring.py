"""Monitoring tables (spec 001 §1.2).

Two deliberate departures from the spec text, both because the spec assumes
traffic that does not exist yet:

``cache_samples`` replaces the spec's ``cache_events``. An event-shaped table
(hit/miss, key_pattern) presumes the app sits in the path of Redis traffic; it
does not. Redis reports cumulative counters, so the honest shape is a periodic
sample, with rates derived from the delta between two of them.

``query_logs`` matches the spec exactly but stays empty until spec 002's
``/ext/query`` gives the app ChromaDB queries to log.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from brownbear.db import Base


class SystemSnapshot(Base):
    """Point-in-time resource usage.

    Scope is host-level, not per-container: per-container statistics require
    mounting the Docker socket into this app, which grants root-equivalent
    access to the host and is not worth it for a resource gauge.
    """

    __tablename__ = "system_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cpu_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    memory_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    memory_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memory_total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    disk_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    disk_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    disk_total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (Index("ix_system_snapshots_timestamp", "timestamp"),)


class CacheSample(Base):
    """A reading of Redis' cumulative counters.

    Values only ever increase (until Redis restarts), so a rate means the
    difference between two samples divided by the time between them.
    """

    __tablename__ = "cache_samples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    keyspace_hits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    keyspace_misses: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    evicted_keys: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expired_keys: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    used_memory_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    connected_clients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_keys: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (Index("ix_cache_samples_timestamp", "timestamp"),)


class QueryLog(Base):
    """One ChromaDB query (spec 001 §1.2).

    Populated by spec 002's external query endpoint; empty until then.
    Spec 004's access-based pruning rule reads this table, so it cannot
    detect stale documents until queries actually flow through the app.
    """

    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    collection: Mapped[str] = mapped_column(String(256), nullable=False)
    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_query_logs_collection_timestamp", "collection", "timestamp"),)
