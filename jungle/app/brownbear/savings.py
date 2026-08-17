"""What the shared memory served, and what it saved (spec 003 §3.5 rev 2).

The number this stack exists to produce and could not previously report. The cache
page shows Redis keyspace hit rate, which measures whether an *embedding vector*
was recomputed — unrelated to tokens, and routinely mistaken for this.

Three quantities, kept apart because merging them is the easy overstatement:

  served     Content Brown Bear handed back: cached answers plus retrieved chunks.
             Always real. Not a saving on its own — retrieved chunks are *added*
             to a prompt and cost input tokens.
  avoided    Output tokens a provider did not generate, counted only when a hit
             actually replaced a model call. In `inject` mode — the default — a hit
             is added as context and the model still answers, so the saving is
             zero and the gain is grounding.
  cost       `avoided` priced at the model's output rate.

The honest summary is therefore usually "served a lot, avoided little", and the
card says so rather than presenting served volume as money saved.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import anyio.to_thread
from sqlalchemy import Integer, func, select

from brownbear.db import session_scope
from brownbear.models.context import ContextEvent
from brownbear.pricing import calculate_avoided_cost, estimate_tokens, resolve

logger = logging.getLogger(__name__)

#: Modes in which a hit genuinely replaces a provider call. `inject` is absent on
#: purpose: it adds the cached answer as context and the model still runs.
BLOCKING_MODES = frozenset({"block"})


def _record_sync(values: dict[str, Any]) -> None:
    with session_scope() as session:
        session.add(ContextEvent(**values))


async def record_context_event(
    *,
    project: str,
    model: str,
    hit: bool,
    cache_mode: str,
    score: float | None,
    answer: str | None,
    chunks: list[dict[str, Any]],
) -> None:
    """Record one lookup. Best-effort: reporting must never fail a retrieval.

    Sizes are estimated from characters rather than tokenised. Tokenising properly
    would mean a tokeniser per provider inside the hot path, and this number is
    used to report a saving, never to bill anyone.
    """
    served_text = answer or ""
    chunk_text = "".join(str(chunk.get("text") or "") for chunk in chunks)
    tokens_served = estimate_tokens(served_text) + estimate_tokens(chunk_text)

    avoided = 0
    cost_avoided = Decimal("0")
    currency = "USD"
    if hit and cache_mode in BLOCKING_MODES:
        avoided = estimate_tokens(served_text)

    try:
        if avoided:
            def _price() -> tuple[Decimal, str]:
                with session_scope() as session:
                    rates = resolve(session, model)
                    return calculate_avoided_cost(avoided, rates), rates.currency

            cost_avoided, currency = await anyio.to_thread.run_sync(_price)

        await anyio.to_thread.run_sync(
            _record_sync,
            {
                "project": project,
                "model": model,
                "hit": hit,
                "cache_mode": cache_mode,
                "score": Decimal(str(round(score, 6))) if score is not None else None,
                "chunks_served": len(chunks),
                "tokens_served": tokens_served,
                "tokens_avoided": avoided,
                "cost_avoided_usd": cost_avoided,
                "currency": currency,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to record context event for project=%s", project)


def _summary_sync(days: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    with session_scope() as session:
        row = session.execute(
            select(
                func.count().label("lookups"),
                func.coalesce(func.sum(func.cast(ContextEvent.hit, Integer)), 0).label("hits"),
                func.coalesce(func.sum(ContextEvent.tokens_served), 0).label("served"),
                func.coalesce(func.sum(ContextEvent.tokens_avoided), 0).label("avoided"),
                func.coalesce(func.sum(ContextEvent.cost_avoided_usd), 0).label("cost"),
                func.coalesce(func.sum(ContextEvent.chunks_served), 0).label("chunks"),
            ).where(ContextEvent.timestamp >= since)
        ).one()

        blocking = session.scalar(
            select(func.count())
            .select_from(ContextEvent)
            .where(
                ContextEvent.timestamp >= since,
                ContextEvent.hit.is_(True),
                ContextEvent.cache_mode.in_(BLOCKING_MODES),
            )
        ) or 0

    lookups = int(row.lookups or 0)
    hits = int(row.hits or 0)
    return {
        "window_days": days,
        "lookups": lookups,
        "hits": hits,
        # Null rather than 0 when nothing was looked up: no data is not a 0% hit
        # rate, and the dashboard already distinguishes those everywhere else.
        "hit_rate": (hits / lookups) if lookups else None,
        "chunks_served": int(row.chunks or 0),
        "tokens_served": int(row.served or 0),
        "tokens_avoided": int(row.avoided or 0),
        "cost_avoided_usd": float(row.cost or 0),
        "blocking_hits": int(blocking),
        "estimated": True,
        "basis": (
            "Served is content Brown Bear returned; it is not a saving on its own "
            "because retrieved chunks are added to a prompt and cost input tokens. "
            "Avoided counts output tokens only, and only for hits served in place "
            "of a model call (BB_CACHE_MODE=block). Sizes are estimated at "
            "~4 characters per token."
        ),
    }


async def summary(days: int = 30) -> dict[str, Any]:
    return await anyio.to_thread.run_sync(_summary_sync, days)
