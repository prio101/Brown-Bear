"""Analytics export (spec 001 §1.5).

Rows are streamed, and each dataset is fetched with ``yield_per`` inside the
generator's own session. Building the whole export in memory first would make
a year of token events an out-of-memory risk on the machine that is also
running the models.
"""

import csv
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, select

from brownbear.db import session_scope
from brownbear.models.monitoring import CacheSample, SystemSnapshot
from brownbear.models.tokens import PeriodType, TokenEvent, TokenPeriod

router = APIRouter(prefix="/api", tags=["export"])

CHUNK_ROWS = 1000


class Dataset(StrEnum):
    token_periods = "token_periods"
    token_events = "token_events"
    system_snapshots = "system_snapshots"
    cache_samples = "cache_samples"


class ExportFormat(StrEnum):
    csv = "csv"
    json = "json"


_MODEL = {
    Dataset.token_periods: TokenPeriod,
    Dataset.token_events: TokenEvent,
    Dataset.system_snapshots: SystemSnapshot,
    Dataset.cache_samples: CacheSample,
}

_TIME_COLUMN = {
    Dataset.token_periods: TokenPeriod.period_start,
    Dataset.token_events: TokenEvent.timestamp,
    Dataset.system_snapshots: SystemSnapshot.timestamp,
    Dataset.cache_samples: CacheSample.timestamp,
}


def _serialise(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # StrEnum-backed columns
        return value.value
    if isinstance(value, int | float | str | bool) or value is None:
        return value
    return str(value)


def _columns(dataset: Dataset) -> list[str]:
    return [column.name for column in _MODEL[dataset].__table__.columns]


def _build_query(
    dataset: Dataset,
    start: datetime | None,
    end: datetime | None,
    period: PeriodType | None,
) -> Select:
    query = select(_MODEL[dataset])
    time_column = _TIME_COLUMN[dataset]
    if start:
        query = query.where(time_column >= start)
    if end:
        query = query.where(time_column < end)
    if period is not None:
        query = query.where(TokenPeriod.period_type == period)
    return query.order_by(time_column)


def _rows(
    dataset: Dataset,
    start: datetime | None,
    end: datetime | None,
    period: PeriodType | None,
) -> Iterator[dict]:
    columns = _columns(dataset)
    with session_scope() as session:
        result = session.execute(
            _build_query(dataset, start, end, period).execution_options(yield_per=CHUNK_ROWS)
        )
        for row in result.scalars():
            yield {name: _serialise(getattr(row, name)) for name in columns}


def _csv_stream(
    dataset: Dataset,
    start: datetime | None,
    end: datetime | None,
    period: PeriodType | None,
) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_columns(dataset))
    writer.writeheader()
    yield _drain(buffer)

    for row in _rows(dataset, start, end, period):
        writer.writerow(row)
        yield _drain(buffer)


def _drain(buffer: io.StringIO) -> str:
    value = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return value


def _json_stream(
    dataset: Dataset,
    start: datetime | None,
    end: datetime | None,
    period: PeriodType | None,
) -> Iterator[str]:
    yield "["
    first = True
    for row in _rows(dataset, start, end, period):
        yield ("" if first else ",") + json.dumps(row)
        first = False
    yield "]"


@router.get("/export")
def export(
    dataset: Dataset = Dataset.token_periods,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.csv,
    start: datetime | None = None,
    end: datetime | None = None,
    period: PeriodType | None = None,
) -> StreamingResponse:
    """Stream a dataset as CSV or JSON.

    token_periods defaults to daily granularity. Exporting it unfiltered would
    mix hourly, daily, weekly and monthly rows describing the same usage, which
    silently double counts the moment anyone sums the file.
    """
    if period is not None and dataset is not Dataset.token_periods:
        raise HTTPException(
            status_code=400, detail="period only applies to the token_periods dataset"
        )
    if dataset is Dataset.token_periods and period is None:
        period = PeriodType.daily

    if start and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)

    stream = _csv_stream if export_format is ExportFormat.csv else _json_stream
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = export_format.value
    media = "text/csv" if export_format is ExportFormat.csv else "application/json"

    return StreamingResponse(
        stream(dataset, start, end, period),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{dataset.value}_{stamp}.{suffix}"'
        },
    )
