"""Token event recording (spec 003 §3.1).

Writes are best-effort by design: metering must never turn a working
inference call into a failed one. Every failure is logged and swallowed.
"""

import logging
from decimal import Decimal
from typing import Any

import anyio.to_thread
from sqlalchemy.exc import IntegrityError

from brownbear.db import session_scope
from brownbear.models.tokens import TokenEvent, TokenSource
from brownbear.pricing import calculate_bucketed_cost, calculate_cost, resolve

logger = logging.getLogger(__name__)


def record_token_event_sync(
    *,
    model: str,
    tokens_in: int,
    tokens_out: int,
    source: TokenSource = TokenSource.local_ollama,
    endpoint: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    cost_usd: Decimal | None = None,
    tokens_in_fresh: int | None = None,
    tokens_cache_write: int | None = None,
    tokens_cache_read: int | None = None,
) -> int | None:
    """Persist one token event. Returns its id, or None if it was a duplicate.

    ``cost_usd`` lets a caller that already knows the price report it — a remote
    client billed by its own provider knows the real figure, where the local
    pricing table may only have the ``*`` fallback that prices it at zero.
    """
    with session_scope() as session:
        rates = resolve(session, model)

        # A breakdown is present only when the client sent one. Without it every
        # input token is priced at the base rate, which is what "flat" records —
        # not a wrong number, a number computed under the older rule, and marked
        # so nobody later mistakes it for a bucketed one.
        buckets_supplied = any(
            value is not None
            for value in (tokens_in_fresh, tokens_cache_write, tokens_cache_read)
        )
        fresh = tokens_in_fresh or 0
        write = tokens_cache_write or 0
        read = tokens_cache_read or 0

        if buckets_supplied:
            # The buckets are authoritative; tokens_in is their sum. A client that
            # sends both and disagrees gets the breakdown, since that is the thing
            # cost is computed from.
            total_in = fresh + write + read
            pricing_model = "bucketed"
            computed = calculate_bucketed_cost(
                tokens_in_fresh=fresh,
                tokens_cache_write=write,
                tokens_cache_read=read,
                tokens_out=tokens_out,
                rates=rates,
            )
        else:
            total_in = tokens_in
            pricing_model = "flat"
            computed = calculate_cost(
                tokens_in, tokens_out, rates.input_per_1k, rates.output_per_1k
            )

        event = TokenEvent(
            model=model,
            tokens_in=total_in,
            tokens_out=tokens_out,
            total_tokens=total_in + tokens_out,
            tokens_in_fresh=fresh,
            tokens_cache_write=write,
            tokens_cache_read=read,
            pricing_model=pricing_model,
            source=source,
            endpoint=endpoint,
            session_id=session_id,
            user_id=user_id,
            request_id=request_id,
            # A client billed by its own provider knows the real figure; the local
            # table may only carry the `*` fallback, which prices it at zero.
            cost_usd=cost_usd if cost_usd is not None else computed,
            currency=rates.currency,
        )
        session.add(event)
        try:
            session.flush()
        except IntegrityError:
            # Unique request_id: a replayed remote batch (spec 003 §3.2).
            session.rollback()
            logger.info("duplicate token event ignored: request_id=%s", request_id)
            return None
        return event.id


async def record_token_event(**kwargs: Any) -> int | None:
    """Async wrapper: the engine is sync, so the write goes to a worker thread."""
    try:
        return await anyio.to_thread.run_sync(
            lambda: record_token_event_sync(**kwargs)
        )
    except Exception:  # noqa: BLE001 - metering must not break inference
        logger.exception("failed to record token event: %s", kwargs.get("model"))
        return None
