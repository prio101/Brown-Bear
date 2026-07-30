"""Background metric collection (spec 001 §1.4).

Collection is best-effort: a failed sample is logged and skipped. A monitoring
job that raises would be retried by the scheduler forever and, worse, could
mask the very outage it exists to record.

Both collectors write cumulative or point-in-time readings rather than derived
rates. Rates are computed at read time from the delta between two samples, so
changing how a rate is defined never requires re-collecting history.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import anyio.to_thread
import psutil
from sqlalchemy import delete, select

from brownbear.config import get_settings
from brownbear.connectors.redis_conn import info as redis_info
from brownbear.db import session_scope
from brownbear.models.monitoring import CacheSample, SystemSnapshot

logger = logging.getLogger(__name__)

# psutil needs a short window to compute a CPU percentage; the first call with
# interval=None always returns 0.0, which would poison the first sample.
CPU_SAMPLE_SECONDS = 0.5


def _system_snapshot_sync() -> int:
    cpu = psutil.cpu_percent(interval=CPU_SAMPLE_SECONDS)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    with session_scope() as session:
        snapshot = SystemSnapshot(
            cpu_percent=Decimal(str(round(cpu, 2))),
            memory_percent=Decimal(str(round(memory.percent, 2))),
            memory_used_bytes=memory.used,
            memory_total_bytes=memory.total,
            disk_percent=Decimal(str(round(disk.percent, 2))),
            disk_used_bytes=disk.used,
            disk_total_bytes=disk.total,
        )
        session.add(snapshot)
        session.flush()
        return snapshot.id


async def collect_system_snapshot() -> int | None:
    """Record host CPU, memory and disk.

    Host-scoped, not per-container — see the SystemSnapshot docstring.
    """
    try:
        return await anyio.to_thread.run_sync(_system_snapshot_sync)
    except Exception:  # noqa: BLE001 - monitoring must not crash the scheduler
        logger.exception("system snapshot failed")
        return None


def _write_cache_sample_sync(stats: dict) -> int:
    keyspace = sum(
        db_stats.get("keys", 0)
        for key, db_stats in stats.items()
        if key.startswith("db") and isinstance(db_stats, dict)
    )
    with session_scope() as session:
        sample = CacheSample(
            keyspace_hits=int(stats.get("keyspace_hits", 0)),
            keyspace_misses=int(stats.get("keyspace_misses", 0)),
            evicted_keys=int(stats.get("evicted_keys", 0)),
            expired_keys=int(stats.get("expired_keys", 0)),
            used_memory_bytes=int(stats.get("used_memory", 0)),
            connected_clients=int(stats.get("connected_clients", 0)),
            total_keys=keyspace,
        )
        session.add(sample)
        session.flush()
        return sample.id


async def collect_cache_sample() -> int | None:
    """Record Redis' cumulative counters."""
    try:
        stats = await redis_info()
        return await anyio.to_thread.run_sync(lambda: _write_cache_sample_sync(stats))
    except Exception:  # noqa: BLE001 - a Redis outage must not stop collection
        logger.exception("cache sample failed")
        return None


def _prune_monitoring_sync(days: int) -> dict[str, int]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with session_scope() as session:
        snapshots = session.execute(
            delete(SystemSnapshot).where(SystemSnapshot.timestamp < cutoff)
        ).rowcount
        samples = session.execute(
            delete(CacheSample).where(CacheSample.timestamp < cutoff)
        ).rowcount
    return {"system_snapshots": snapshots or 0, "cache_samples": samples or 0}


async def prune_monitoring() -> dict[str, int]:
    """Drop monitoring rows past the retention window.

    Not in spec 001, but at a 30 second interval these two tables grow by
    ~5,800 rows a day each and nothing else would ever remove them. Token
    retention (spec 003 §3.7) is separate and deliberately longer.
    """
    days = get_settings().monitoring_retention_days
    try:
        removed = await anyio.to_thread.run_sync(lambda: _prune_monitoring_sync(days))
        if any(removed.values()):
            logger.info("pruned monitoring rows older than %d days: %s", days, removed)
        return removed
    except Exception:  # noqa: BLE001
        logger.exception("monitoring prune failed")
        return {}


def latest_snapshot_sync() -> SystemSnapshot | None:
    with session_scope() as session:
        return session.execute(
            select(SystemSnapshot).order_by(SystemSnapshot.timestamp.desc()).limit(1)
        ).scalar_one_or_none()
