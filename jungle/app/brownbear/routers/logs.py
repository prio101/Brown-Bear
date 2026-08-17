"""Streamed logs (BB-301).

The counterpart to the memory graph. Memory is a few dozen richly connected
documents and belongs in a graph; logs are tens of thousands of flat, ordered rows
and do not — `system_snapshots` and `cache_samples` alone add ~5,800 rows a day
each. Drawing those as nodes would bury the memory roughly a thousand to one, so
they stream instead.

Server-Sent Events rather than WebSockets: this is one-directional, and SSE is
plain HTTP — it passes the edge's default-deny allowlist as an ordinary GET, keeps
the same bearer-token auth as everything else, and reconnects on its own without
client code. A WebSocket would need an Upgrade path through nginx and Cloudflare
for no gain.

Two things make it work through the tunnel: `proxy_buffering off` in
`edge/proxy_common.conf`, without which nginx holds each event until its buffer
fills, and the heartbeat below, without which an idle connection is closed by an
intermediary that thinks it has stalled.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import anyio.to_thread
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from brownbear.db import session_scope
from brownbear.models.monitoring import QueryLog
from brownbear.models.tokens import TokenEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])

#: How often the tables are re-read. Logs are written by request handlers, not
#: streamed from them, so this is a poll — a second is well under human notice and
#: keeps the query rate trivial.
POLL_SECONDS = 1.0

#: Comment frames keep the connection open through nginx and Cloudflare while
#: nothing is being logged. A silent SSE stream looks stalled and gets closed.
HEARTBEAT_SECONDS = 15.0

#: Rows sent on connect, so a viewer opens onto content rather than an empty page.
BACKLOG_DEFAULT = 50
BACKLOG_MAX = 500

#: Prompts reach this table in full. The stream is authenticated, but a log line
#: is not the place to re-publish an entire prompt.
TEXT_CHARS = 300


def _truncate(value: str | None) -> str | None:
    if value is None:
        return None
    flat = " ".join(str(value).split())
    return flat if len(flat) <= TEXT_CHARS else flat[: TEXT_CHARS - 1] + "…"


def _query_row(row: QueryLog) -> dict[str, Any]:
    return {
        "kind": "query",
        "id": row.id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "collection": row.collection,
        "query_text": _truncate(row.query_text),
        "latency_ms": float(row.latency_ms) if row.latency_ms is not None else None,
        "result_count": row.result_count,
    }


def _token_row(row: TokenEvent) -> dict[str, Any]:
    return {
        "kind": "token",
        "id": row.id,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "model": row.model,
        "source": str(row.source),
        "endpoint": row.endpoint,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "total_tokens": row.total_tokens,
        "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
    }


def _read_backlog(limit: int) -> tuple[list[dict[str, Any]], int, int]:
    """The most recent rows from both tables, oldest first.

    Returns the high-water mark for each table as well, so the stream resumes from
    exactly where the backlog ended and cannot replay or skip a row.
    """
    with session_scope() as session:
        queries = list(
            session.scalars(select(QueryLog).order_by(QueryLog.id.desc()).limit(limit))
        )
        tokens = list(
            session.scalars(select(TokenEvent).order_by(TokenEvent.id.desc()).limit(limit))
        )

    rows = [_query_row(q) for q in queries] + [_token_row(t) for t in tokens]
    rows.sort(key=lambda r: (r["timestamp"] or "", r["id"]))
    return (
        rows[-limit:],
        max((q.id for q in queries), default=0),
        max((t.id for t in tokens), default=0),
    )


def _read_since(last_query: int, last_token: int) -> tuple[list[dict[str, Any]], int, int]:
    with session_scope() as session:
        queries = list(
            session.scalars(
                select(QueryLog).where(QueryLog.id > last_query).order_by(QueryLog.id).limit(200)
            )
        )
        tokens = list(
            session.scalars(
                select(TokenEvent).where(TokenEvent.id > last_token).order_by(TokenEvent.id).limit(200)
            )
        )

    rows = [_query_row(q) for q in queries] + [_token_row(t) for t in tokens]
    rows.sort(key=lambda r: (r["timestamp"] or "", r["id"]))
    return (
        rows,
        max([last_query, *(q.id for q in queries)]),
        max([last_token, *(t.id for t in tokens)]),
    )


def _frame(payload: dict[str, Any]) -> str:
    return f"event: {payload['kind']}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.get("/recent")
async def recent(
    limit: int = Query(BACKLOG_DEFAULT, ge=1, le=BACKLOG_MAX),
) -> dict[str, Any]:
    """The same rows the stream opens with, as one response.

    Exists so a client can render without holding a connection, and so the shape of
    a log row is testable without driving a stream.
    """
    rows, _, _ = await anyio.to_thread.run_sync(_read_backlog, limit)
    return {"rows": rows, "count": len(rows)}


async def event_stream(
    is_disconnected: Callable[[], Awaitable[bool]],
    backlog: int = BACKLOG_DEFAULT,
) -> AsyncIterator[str]:
    """The SSE frames themselves, as an independent generator.

    Takes a disconnect predicate rather than a Request so it can be driven directly
    by a test. An endless generator consumed through a test client cannot be closed
    from the client side, so a suite that drove this over HTTP would hang rather
    than fail — and a stream nobody can test is a stream nobody can change safely.

    Frames are typed: `query`, `token`, `ready`, `heartbeat`, `error`. A client that
    wants only one kind filters by event name instead of parsing every payload.
    """
    try:
        rows, last_query, last_token = await anyio.to_thread.run_sync(_read_backlog, backlog)
    except Exception:  # noqa: BLE001
        # The response has already begun, so a 500 is no longer available. The only
        # honest place left to report this is inside the stream.
        logger.exception("log stream could not read the backlog")
        yield f"event: error\ndata: {json.dumps({'error': 'log store unavailable'})}\n\n"
        return

    for row in rows:
        yield _frame(row)
    yield f"event: ready\ndata: {json.dumps({'backlog': len(rows)})}\n\n"

    since_beat = 0.0
    while True:
        # Checked every tick: without it a closed browser tab leaves this loop
        # polling the database forever.
        if await is_disconnected():
            return

        await asyncio.sleep(POLL_SECONDS)
        since_beat += POLL_SECONDS

        try:
            rows, last_query, last_token = await anyio.to_thread.run_sync(
                _read_since, last_query, last_token
            )
        except Exception:  # noqa: BLE001
            logger.exception("log stream poll failed")
            yield f"event: error\ndata: {json.dumps({'error': 'poll failed'})}\n\n"
            await asyncio.sleep(POLL_SECONDS * 5)
            continue

        for row in rows:
            yield _frame(row)

        if rows:
            since_beat = 0.0
        elif since_beat >= HEARTBEAT_SECONDS:
            since_beat = 0.0
            yield f"event: heartbeat\ndata: {json.dumps({'at': datetime.now(UTC).isoformat()})}\n\n"


@router.get("/stream")
async def stream(
    request: Request,
    backlog: int = Query(BACKLOG_DEFAULT, ge=0, le=BACKLOG_MAX),
) -> StreamingResponse:
    """Live query and token logs as Server-Sent Events."""
    return StreamingResponse(
        event_stream(request.is_disconnected, backlog),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Belt and braces alongside `proxy_buffering off` at the edge: this is
            # the header nginx honours when the config is not under our control.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
