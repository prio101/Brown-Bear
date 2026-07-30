"""Token usage read endpoints (spec 003 §3.6).

Two different sources on purpose:

``/summary`` reads **raw events** for the bucket currently in flight. The
aggregator only writes closed windows, so reading token_periods here would
show an empty or stale current hour — exactly the number a dashboard is
watching most closely.

Everything historical reads **token_periods**, which is what survives raw
event pruning (spec 003 §3.7). Asking history to read raw events would make
it silently start returning zeros once retention kicks in.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brownbear.aggregation import bucket_bounds, catch_up
from brownbear.db import get_db
from brownbear.models.aggregation import AggregationRun
from brownbear.models.tokens import PeriodType, TokenEvent, TokenPeriod, TokenSource

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

DbSession = Annotated[Session, Depends(get_db)]

# How far back history reaches when the caller gives no explicit range.
DEFAULT_BUCKETS = 30
MAX_ROWS = 5000


def _as_float(value: Decimal | float | None) -> float:
    return float(value or 0)


def _utc(moment: datetime) -> datetime:
    """Treat a naive query parameter as UTC rather than as host-local time."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _resolve_range(
    period: PeriodType, start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    resolved_end = _utc(end) if end else bucket_bounds(period, now)[1]
    if start:
        return _utc(start), resolved_end

    span = {
        PeriodType.hourly: timedelta(hours=DEFAULT_BUCKETS),
        PeriodType.daily: timedelta(days=DEFAULT_BUCKETS),
        PeriodType.weekly: timedelta(weeks=DEFAULT_BUCKETS),
        PeriodType.monthly: timedelta(days=30 * DEFAULT_BUCKETS),
    }[period]
    return resolved_end - span, resolved_end


def _period_totals(period: PeriodType, start: datetime, end: datetime):
    return (
        select(
            func.coalesce(func.sum(TokenPeriod.total_tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(TokenPeriod.total_tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(TokenPeriod.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(TokenPeriod.total_cost_usd), 0).label("cost"),
            func.coalesce(func.sum(TokenPeriod.request_count), 0).label("requests"),
        )
        .where(
            TokenPeriod.period_type == period,
            TokenPeriod.period_start >= start,
            TokenPeriod.period_start < end,
        )
    )


@router.get("/summary")
def summary(
    db: DbSession,
    period: PeriodType = PeriodType.daily,
) -> dict[str, Any]:
    """Live totals for the bucket currently in progress."""
    start, end = bucket_bounds(period, datetime.now(UTC))
    row = db.execute(
        select(
            func.coalesce(func.sum(TokenEvent.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(TokenEvent.tokens_out), 0).label("tokens_out"),
            func.coalesce(func.sum(TokenEvent.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(TokenEvent.cost_usd), 0).label("cost"),
            func.count(TokenEvent.id).label("requests"),
        ).where(TokenEvent.timestamp >= start, TokenEvent.timestamp < end)
    ).one()

    return {
        "period": period.value,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        # Flags that this window is still open, so the number will keep moving.
        "live": True,
        "source": "token_events",
        "tokens_in": int(row.tokens_in),
        "tokens_out": int(row.tokens_out),
        "total_tokens": int(row.total_tokens),
        "cost": _as_float(row.cost),
        "currency": "USD",
        "request_count": int(row.requests),
    }


@router.get("/history")
def history(
    db: DbSession,
    period: PeriodType = PeriodType.daily,
    start: datetime | None = None,
    end: datetime | None = None,
    model: str | None = None,
    source: TokenSource | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 500,
) -> dict[str, Any]:
    """Closed buckets over a range, newest first."""
    window_start, window_end = _resolve_range(period, start, end)

    statement = select(TokenPeriod).where(
        TokenPeriod.period_type == period,
        TokenPeriod.period_start >= window_start,
        TokenPeriod.period_start < window_end,
    )
    if model:
        statement = statement.where(TokenPeriod.model == model)
    if source:
        statement = statement.where(TokenPeriod.source == source)

    rows = db.execute(
        statement.order_by(TokenPeriod.period_start.desc()).limit(limit)
    ).scalars().all()

    return {
        "period": period.value,
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
        "count": len(rows),
        "truncated": len(rows) == limit,
        "results": [
            {
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "model": row.model,
                "source": row.source.value,
                "tokens_in": row.total_tokens_in,
                "tokens_out": row.total_tokens_out,
                "total_tokens": row.total_tokens,
                "cost": _as_float(row.total_cost_usd),
                "request_count": row.request_count,
            }
            for row in rows
        ],
    }


@router.get("/by-model")
def by_model(
    db: DbSession,
    period: PeriodType = PeriodType.daily,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    window_start, window_end = _resolve_range(period, start, end)
    rows = db.execute(
        _period_totals(period, window_start, window_end)
        .add_columns(TokenPeriod.model.label("model"))
        .group_by(TokenPeriod.model)
        .order_by(func.sum(TokenPeriod.total_tokens).desc())
    ).all()

    return {
        "period": period.value,
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
        "results": [
            {
                "model": row.model,
                "tokens_in": int(row.tokens_in),
                "tokens_out": int(row.tokens_out),
                "total_tokens": int(row.total_tokens),
                "cost": _as_float(row.cost),
                "request_count": int(row.requests),
            }
            for row in rows
        ],
    }


@router.get("/by-source")
def by_source(
    db: DbSession,
    period: PeriodType = PeriodType.daily,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Local inference versus paid remote APIs."""
    window_start, window_end = _resolve_range(period, start, end)
    rows = db.execute(
        _period_totals(period, window_start, window_end)
        .add_columns(TokenPeriod.source.label("source"))
        .group_by(TokenPeriod.source)
    ).all()

    return {
        "period": period.value,
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
        "results": [
            {
                "source": row.source.value,
                "tokens_in": int(row.tokens_in),
                "tokens_out": int(row.tokens_out),
                "total_tokens": int(row.total_tokens),
                "cost": _as_float(row.cost),
                "request_count": int(row.requests),
            }
            for row in rows
        ],
    }


@router.get("/aggregation")
def aggregation_status(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    """Recent aggregation runs, and the newest completed window per period."""
    recent = db.execute(
        select(AggregationRun).order_by(AggregationRun.started_at.desc()).limit(limit)
    ).scalars().all()

    newest = db.execute(
        select(
            AggregationRun.period_type,
            func.max(AggregationRun.window_start).label("window_start"),
        )
        .where(AggregationRun.status == "completed")
        .group_by(AggregationRun.period_type)
    ).all()

    return {
        "latest_completed": {
            row.period_type.value: row.window_start.isoformat() for row in newest
        },
        "recent_runs": [
            {
                "id": run.id,
                "period": run.period_type.value,
                "window_start": run.window_start.isoformat(),
                "window_end": run.window_end.isoformat(),
                "status": run.status.value,
                "rows_written": run.rows_written,
                "error": run.error,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
            for run in recent
        ],
    }


@router.post("/aggregate")
def trigger_aggregation(
    period: PeriodType = PeriodType.hourly,
    max_buckets: Annotated[int | None, Query(ge=1, le=10000)] = None,
) -> dict[str, Any]:
    """Run catch-up now instead of waiting for the schedule.

    Safe to call repeatedly: aggregation upserts, so a re-run recomputes a
    window rather than double-counting it.
    """
    return catch_up(period, max_buckets)
