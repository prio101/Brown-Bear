"""Shared background scheduler (roadmap F7).

One scheduler for the whole app. Specs 001, 002, 003 and 004 each introduce a
background job runner; they all use this one.

Jobs run in UTC to match the aggregation bucket edges, and are ordered so a
rollup never runs before the daily rows it reads: daily at 00:15, weekly at
00:30, monthly at 00:45.

Job state is deliberately *not* persisted. Aggregation derives what still needs
doing from the aggregation_runs table on every tick, so a persistent job store
would add an Alembic-unmanaged table and a second source of truth without
answering any question the database cannot already answer. That changes when
spec 004 adds user-configured maintenance schedules, or when a second replica
makes a distributed lock necessary.
"""

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from brownbear.aggregation import catch_up, catch_up_all
from brownbear.collector import collect_cache_sample, collect_system_snapshot, prune_monitoring
from brownbear.config import get_settings
from brownbear.models.tokens import PeriodType

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Schedules are late enough in each window that a slow write from the previous
# period has landed, and ordered so rollups follow their inputs.
_JOBS: list[tuple[str, PeriodType, CronTrigger]] = [
    ("aggregate-hourly", PeriodType.hourly, CronTrigger(minute=5, timezone=UTC)),
    ("aggregate-daily", PeriodType.daily, CronTrigger(hour=0, minute=15, timezone=UTC)),
    (
        "aggregate-weekly",
        PeriodType.weekly,
        CronTrigger(day_of_week="mon", hour=0, minute=30, timezone=UTC),
    ),
    (
        "aggregate-monthly",
        PeriodType.monthly,
        CronTrigger(day=1, hour=0, minute=45, timezone=UTC),
    ),
]


SNAPSHOT_JOB_ID = "collect-system-snapshot"
CACHE_JOB_ID = "collect-cache-sample"

_INTERVAL_JOBS = {
    "snapshot_interval_seconds": SNAPSHOT_JOB_ID,
    "cache_sample_interval_seconds": CACHE_JOB_ID,
}


def _interval(key: str) -> int:
    """Interval from the settings store, falling back to configuration.

    Reading the store touches the database. If that fails at boot the app must
    still come up collecting at its configured rate rather than not at all.
    """
    from brownbear import settings_store

    try:
        return int(settings_store.value_of(key))
    except Exception:  # noqa: BLE001
        fallback = getattr(get_settings(), key)
        logger.warning("could not read %s from the settings store; using %s", key, fallback)
        return int(fallback)


def apply_collection_intervals() -> dict[str, int]:
    """Reschedule collection jobs against the current settings, live."""
    applied: dict[str, int] = {}
    if _scheduler is None or not _scheduler.running:
        return applied
    for key, job_id in _INTERVAL_JOBS.items():
        seconds = _interval(key)
        applied[key] = seconds
        if _scheduler.get_job(job_id):
            _scheduler.reschedule_job(job_id, trigger=IntervalTrigger(seconds=seconds))
    logger.info("collection intervals applied: %s", applied)
    return applied


def _run_catch_up(period: PeriodType) -> None:
    result = catch_up(period)
    if result["buckets"]:
        logger.info(
            "aggregated %d %s bucket(s), %d row(s)",
            result["buckets"],
            period.value,
            result["rows"],
        )


def _run_startup_catch_up() -> None:
    """Fill anything missed while the container was down."""
    for result in catch_up_all():
        if result["buckets"]:
            logger.info("startup catch-up: %s", result)


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not get_settings().scheduler_enabled:
        logger.info("scheduler disabled by configuration")
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone=UTC)
    for job_id, period, trigger in _JOBS:
        _scheduler.add_job(
            _run_catch_up,
            trigger=trigger,
            args=[period],
            id=job_id,
            replace_existing=True,
            # A restart during a scheduled minute must not double-run, and a
            # backlog of missed fires collapses into one catch-up rather than
            # queueing dozens.
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )

    # Collection jobs are coroutines and run on the event loop; each one does
    # its blocking database write in a worker thread.
    _scheduler.add_job(
        collect_system_snapshot,
        trigger=IntervalTrigger(seconds=_interval("snapshot_interval_seconds")),
        id=SNAPSHOT_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    _scheduler.add_job(
        collect_cache_sample,
        trigger=IntervalTrigger(seconds=_interval("cache_sample_interval_seconds")),
        id=CACHE_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    _scheduler.add_job(
        prune_monitoring,
        trigger=CronTrigger(hour=3, minute=0, timezone=UTC),
        id="prune-monitoring",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    _scheduler.add_job(
        _run_startup_catch_up,
        trigger=DateTrigger(run_date=datetime.now(UTC) + timedelta(seconds=5), timezone=UTC),
        id="startup-catch-up",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("scheduler started with %d job(s)", len(_scheduler.get_jobs()))
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
