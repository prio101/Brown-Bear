"""Token event recording (spec 003 §3.1).

Writes are best-effort by design: metering must never turn a working
inference call into a failed one. Every failure is logged and swallowed.
"""

import logging
from typing import Any

import anyio.to_thread
from sqlalchemy.exc import IntegrityError

from brownbear.db import session_scope
from brownbear.models.tokens import TokenEvent, TokenSource
from brownbear.pricing import calculate_cost, get_rates

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
) -> int | None:
    """Persist one token event. Returns its id, or None if it was a duplicate."""
    with session_scope() as session:
        input_rate, output_rate, currency = get_rates(session, model)
        event = TokenEvent(
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            total_tokens=tokens_in + tokens_out,
            source=source,
            endpoint=endpoint,
            session_id=session_id,
            user_id=user_id,
            request_id=request_id,
            cost_usd=calculate_cost(tokens_in, tokens_out, input_rate, output_rate),
            currency=currency,
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
