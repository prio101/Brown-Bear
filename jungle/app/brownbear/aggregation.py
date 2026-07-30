"""Period aggregation (spec 003 §3.4).

Three properties this module is built around:

**Idempotent.** Every bucket is an upsert keyed on the token_periods unique
constraint, so re-running a window overwrites it instead of double-counting.
Re-runs are therefore safe after a crash, a clock change, or a manual trigger.

**Complete buckets only.** Nothing is aggregated until its window has closed.
A half-finished hour written as a final total is worse than no row at all —
the dashboard reads live numbers for the current bucket from raw events.

**Self-healing.** The scheduler does not aggregate "the last hour"; it asks
what the newest completed window is and fills forward from there. A container
that was down for a day catches up on its next tick with no manual step.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from brownbear.db import session_scope
from brownbear.models.aggregation import AggregationRun, RunStatus
from brownbear.models.tokens import PeriodType, TokenEvent, TokenPeriod

logger = logging.getLogger(__name__)

# Hourly and daily are computed from raw events; weekly and monthly roll up
# from daily rows so they outlive the raw retention window (spec 003 §3.7).
RAW_PERIODS = frozenset({PeriodType.hourly, PeriodType.daily})
ROLLUP_PERIODS = frozenset({PeriodType.weekly, PeriodType.monthly})

# Caps on a single catch-up pass, so a long outage cannot produce an unbounded
# run. Whatever is left over is picked up by the next tick, and being capped is
# logged rather than passing silently as "up to date".
MAX_BUCKETS_PER_RUN: dict[PeriodType, int] = {
    PeriodType.hourly: 168,  # one week
    PeriodType.daily: 90,
    PeriodType.weekly: 53,
    PeriodType.monthly: 24,
}


def bucket_bounds(period: PeriodType, moment: datetime) -> tuple[datetime, datetime]:
    """The [start, end) window of the given period containing ``moment``.

    Always computed in UTC: bucket edges must not move when the host timezone
    or DST does, or the same window would aggregate differently across runs.
    """
    m = moment.astimezone(UTC)
    midnight = m.replace(hour=0, minute=0, second=0, microsecond=0)

    if period is PeriodType.hourly:
        start = m.replace(minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=1)
    if period is PeriodType.daily:
        return midnight, midnight + timedelta(days=1)
    if period is PeriodType.weekly:
        start = midnight - timedelta(days=midnight.weekday())  # ISO weeks start Monday
        return start, start + timedelta(weeks=1)

    start = midnight.replace(day=1)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def _raw_groups(session: Session, start: datetime, end: datetime) -> list[Any]:
    return session.execute(
        select(
            TokenEvent.model.label("model"),
            TokenEvent.source.label("source"),
            func.coalesce(func.sum(TokenEvent.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(TokenEvent.tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(TokenEvent.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(TokenEvent.cost_usd), 0).label("cost"),
            func.count(TokenEvent.id).label("requests"),
        )
        .where(TokenEvent.timestamp >= start, TokenEvent.timestamp < end)
        .group_by(TokenEvent.model, TokenEvent.source)
    ).all()


def _daily_groups(session: Session, start: datetime, end: datetime) -> list[Any]:
    return session.execute(
        select(
            TokenPeriod.model.label("model"),
            TokenPeriod.source.label("source"),
            func.coalesce(func.sum(TokenPeriod.total_tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(TokenPeriod.total_tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(TokenPeriod.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(TokenPeriod.total_cost_usd), 0).label("cost"),
            func.coalesce(func.sum(TokenPeriod.request_count), 0).label("requests"),
        )
        .where(
            TokenPeriod.period_type == PeriodType.daily,
            TokenPeriod.period_start >= start,
            TokenPeriod.period_start < end,
        )
        .group_by(TokenPeriod.model, TokenPeriod.source)
    ).all()


def _upsert_bucket(
    session: Session, period: PeriodType, start: datetime, end: datetime, groups: list[Any]
) -> int:
    seen: list[tuple[str, Any]] = []
    for group in groups:
        values = {
            "period_type": period,
            "period_start": start,
            "period_end": end,
            "model": group.model,
            "source": group.source,
            "total_tokens_in": int(group.tokens_in),
            "total_tokens_out": int(group.tokens_out),
            "total_tokens": int(group.total_tokens),
            "total_cost_usd": Decimal(group.cost),
            "request_count": int(group.requests),
        }
        statement = pg_insert(TokenPeriod).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_token_periods_bucket",
                set_={
                    "period_end": statement.excluded.period_end,
                    "total_tokens_in": statement.excluded.total_tokens_in,
                    "total_tokens_out": statement.excluded.total_tokens_out,
                    "total_tokens": statement.excluded.total_tokens,
                    "total_cost_usd": statement.excluded.total_cost_usd,
                    "request_count": statement.excluded.request_count,
                    "updated_at": func.now(),
                },
            )
        )
        seen.append((group.model, group.source))

    # A re-run over a window whose events were deleted must not leave the old
    # totals behind claiming to be current.
    stale = delete(TokenPeriod).where(
        TokenPeriod.period_type == period, TokenPeriod.period_start == start
    )
    if seen:
        stale = stale.where(tuple_(TokenPeriod.model, TokenPeriod.source).notin_(seen))
    session.execute(stale)

    return len(seen)


def aggregate_bucket(period: PeriodType, start: datetime, end: datetime) -> int:
    """Aggregate one closed window. Returns the number of (model, source) rows."""
    with session_scope() as session:
        run = AggregationRun(
            period_type=period, window_start=start, window_end=end, status=RunStatus.running
        )
        session.add(run)
        session.flush()
        run_id = run.id

    try:
        with session_scope() as session:
            groups = (
                _raw_groups(session, start, end)
                if period in RAW_PERIODS
                else _daily_groups(session, start, end)
            )
            written = _upsert_bucket(session, period, start, end, groups)
            session.execute(
                update(AggregationRun)
                .where(AggregationRun.id == run_id)
                .values(
                    status=RunStatus.completed,
                    rows_written=written,
                    completed_at=func.now(),
                )
            )
        return written
    except Exception as exc:
        # Separate transaction: the failure record must survive the rollback
        # that just discarded the aggregation itself.
        with session_scope() as session:
            session.execute(
                update(AggregationRun)
                .where(AggregationRun.id == run_id)
                .values(
                    status=RunStatus.failed,
                    error=f"{type(exc).__name__}: {exc}"[:2000],
                    completed_at=func.now(),
                )
            )
        logger.exception("aggregation failed for %s bucket %s", period, start)
        raise


def _earliest_source_moment(session: Session, period: PeriodType) -> datetime | None:
    if period in RAW_PERIODS:
        return session.execute(select(func.min(TokenEvent.timestamp))).scalar()
    return session.execute(
        select(func.min(TokenPeriod.period_start)).where(
            TokenPeriod.period_type == PeriodType.daily
        )
    ).scalar()


def catch_up(period: PeriodType, max_buckets: int | None = None) -> dict[str, Any]:
    """Aggregate every closed bucket not yet covered by a completed run."""
    limit = max_buckets or MAX_BUCKETS_PER_RUN[period]
    current_start, _ = bucket_bounds(period, datetime.now(UTC))

    with session_scope() as session:
        newest_done = session.execute(
            select(func.max(AggregationRun.window_start)).where(
                AggregationRun.period_type == period,
                AggregationRun.status == RunStatus.completed,
            )
        ).scalar()

        if newest_done is not None:
            cursor = bucket_bounds(period, newest_done)[1]
        else:
            earliest = _earliest_source_moment(session, period)
            if earliest is None:
                return {
                    "period": period.value,
                    "buckets": 0,
                    "rows": 0,
                    "capped": False,
                    "next_window": None,
                }
            cursor = bucket_bounds(period, earliest)[0]

    buckets = 0
    rows = 0
    capped = False
    while cursor < current_start:
        if buckets >= limit:
            capped = True
            break
        start, end = bucket_bounds(period, cursor)
        rows += aggregate_bucket(period, start, end)
        buckets += 1
        cursor = end

    if capped:
        logger.warning(
            "%s catch-up stopped at its %d bucket cap; %s onward is still unaggregated",
            period.value,
            limit,
            cursor.isoformat(),
        )

    return {
        "period": period.value,
        "buckets": buckets,
        "rows": rows,
        "capped": capped,
        "next_window": cursor.isoformat() if cursor < current_start else None,
    }


def catch_up_all() -> list[dict[str, Any]]:
    """Run every period in dependency order: weekly and monthly need daily first."""
    return [
        catch_up(period)
        for period in (
            PeriodType.hourly,
            PeriodType.daily,
            PeriodType.weekly,
            PeriodType.monthly,
        )
    ]
