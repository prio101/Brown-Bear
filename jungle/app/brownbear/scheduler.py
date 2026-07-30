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

    settings = get_settings()
    # Collection jobs are coroutines and run on the event loop; each one does
    # its blocking database write in a worker thread.
    _scheduler.add_job(
        collect_system_snapshot,
        trigger=IntervalTrigger(seconds=settings.snapshot_interval_seconds),
        id="collect-system-snapshot",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    _scheduler.add_job(
        collect_cache_sample,
        trigger=IntervalTrigger(seconds=settings.cache_sample_interval_seconds),
        id="collect-cache-sample",
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
