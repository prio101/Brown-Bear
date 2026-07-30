"""Cache, collection and system endpoints (spec 001 §1.5).

Redis reports counters that only ever climb, so a hit rate is meaningless
without a window: these endpoints turn stored samples into rates by
differencing the ends of a range, and expose a per-interval series so a chart
shows how the rate moved rather than one cumulative average since boot.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from brownbear.config import get_settings
from brownbear.connectors import chroma
from brownbear.db import get_db
from brownbear.models.monitoring import CacheSample, SystemSnapshot

router = APIRouter(prefix="/api", tags=["monitoring"])

DbSession = Annotated[Session, Depends(get_db)]


def _rate(hits: int, misses: int) -> float | None:
    total = hits + misses
    return round(hits / total, 4) if total else None


def _samples_in_window(db: Session, minutes: int) -> list[CacheSample]:
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    return list(
        db.execute(
            select(CacheSample)
            .where(CacheSample.timestamp >= since)
            .order_by(CacheSample.timestamp)
        ).scalars()
    )


@router.get("/cache")
def cache(
    db: DbSession,
    minutes: Annotated[int, Query(ge=1, le=10080)] = 60,
) -> dict[str, Any]:
    samples = _samples_in_window(db, minutes)
    if not samples:
        return {
            "window_minutes": minutes,
            "samples": 0,
            "current": None,
            "window": None,
            "series": [],
        }

    first, last = samples[0], samples[-1]

    # Redis counters reset to zero when it restarts. A negative delta means a
    # restart happened inside the window, so the newest value is the whole of
    # what we can attribute to it.
    def delta(attr: str) -> int:
        start, end = getattr(first, attr), getattr(last, attr)
        return end if end < start else end - start

    hits, misses = delta("keyspace_hits"), delta("keyspace_misses")

    series = []
    for previous, current in zip(samples, samples[1:], strict=False):
        step_hits = max(current.keyspace_hits - previous.keyspace_hits, 0)
        step_misses = max(current.keyspace_misses - previous.keyspace_misses, 0)
        series.append(
            {
                "timestamp": current.timestamp.isoformat(),
                "hits": step_hits,
                "misses": step_misses,
                "hit_rate": _rate(step_hits, step_misses),
                "used_memory_bytes": current.used_memory_bytes,
                "total_keys": current.total_keys,
                "connected_clients": current.connected_clients,
            }
        )

    return {
        "window_minutes": minutes,
        "samples": len(samples),
        "current": {
            "timestamp": last.timestamp.isoformat(),
            "used_memory_bytes": last.used_memory_bytes,
            "total_keys": last.total_keys,
            "connected_clients": last.connected_clients,
            "keyspace_hits": last.keyspace_hits,
            "keyspace_misses": last.keyspace_misses,
            # Since the Redis process started, not since the window opened.
            "lifetime_hit_rate": _rate(last.keyspace_hits, last.keyspace_misses),
        },
        "window": {
            "start": first.timestamp.isoformat(),
            "end": last.timestamp.isoformat(),
            "hits": hits,
            "misses": misses,
            "hit_rate": _rate(hits, misses),
            "evicted_keys": delta("evicted_keys"),
            "expired_keys": delta("expired_keys"),
        },
        "series": series,
    }


@router.get("/system")
def system(
    db: DbSession,
    minutes: Annotated[int, Query(ge=1, le=10080)] = 60,
) -> dict[str, Any]:
    """Host CPU, memory and disk over time.

    Host-scoped, not per-container — per-container statistics would require
    mounting the Docker socket into this app.
    """
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    rows = list(
        db.execute(
            select(SystemSnapshot)
            .where(SystemSnapshot.timestamp >= since)
            .order_by(SystemSnapshot.timestamp)
        ).scalars()
    )

    return {
        "scope": "host",
        "window_minutes": minutes,
        "samples": len(rows),
        "current": (
            {
                "timestamp": rows[-1].timestamp.isoformat(),
                "cpu_percent": float(rows[-1].cpu_percent),
                "memory_percent": float(rows[-1].memory_percent),
                "memory_used_bytes": rows[-1].memory_used_bytes,
                "memory_total_bytes": rows[-1].memory_total_bytes,
                "disk_percent": float(rows[-1].disk_percent),
                "disk_used_bytes": rows[-1].disk_used_bytes,
                "disk_total_bytes": rows[-1].disk_total_bytes,
            }
            if rows
            else None
        ),
        "series": [
            {
                "timestamp": row.timestamp.isoformat(),
                "cpu_percent": float(row.cpu_percent),
                "memory_percent": float(row.memory_percent),
                "disk_percent": float(row.disk_percent),
            }
            for row in rows
        ],
    }


@router.get("/collections")
async def collections() -> dict[str, Any]:
    """ChromaDB collections and their document counts."""
    try:
        entries = await chroma.collections_with_counts()
    except Exception as exc:  # noqa: BLE001 - report, do not blank the page
        return {"available": False, "error": f"{type(exc).__name__}: {exc}", "collections": []}

    counted = [entry["count"] for entry in entries if entry["count"] is not None]
    return {
        "available": True,
        "api_version": get_settings().chroma_api_version,
        "collection_count": len(entries),
        "document_count": sum(counted),
        "collections": entries,
    }
