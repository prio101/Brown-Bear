"""What the memory served, and what it saved (spec 003 §3.5 rev 2).

`token_events` records what a provider was *paid* for. Nothing recorded what Brown
Bear *supplied* — so the one number this whole stack exists to produce, "what did
the shared memory save", could not be answered at all. The dashboard's cache page
shows Redis keyspace hits, which measure whether a vector was recomputed and are
routinely mistaken for token savings; they are not related.

Two quantities, kept apart deliberately, because conflating them is the easy lie:

  tokens_served    Content Brown Bear handed back — a cached answer, or retrieved
                   chunks. Always real, always measurable.
  tokens_avoided   Output tokens a provider did NOT generate. Only ever non-zero
                   for a hit the client actually served in place of a model call.

An `inject`-mode hit serves content and avoids nothing: the model still answers,
and the gain is grounding rather than spend. Retrieved chunks *add* input tokens.
Counting either as a saving would overstate the benefit in precisely the way the
flat input rate overstated the cost.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from brownbear.db import Base


class ContextEvent(Base):
    """One `/ext/context` lookup and what it produced."""

    __tablename__ = "context_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    project: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")

    hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: What the client said it would do with a hit: "inject" or "block". Declared
    #: by the caller, since only the caller knows — and recorded rather than
    #: assumed, because the saving is real in one mode and zero in the other.
    cache_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="inject")
    #: Similarity of the best candidate, hit or miss. Kept for misses too: the
    #: near-miss distribution is what the threshold should be tuned from.
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)

    chunks_served: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Estimated from characters — see `estimate_tokens`. Approximate and labelled
    #: as such everywhere it surfaces.
    tokens_served: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_avoided: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_avoided_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    __table_args__ = (
        Index("ix_context_events_ts", "timestamp"),
        Index("ix_context_events_project_ts", "project", "timestamp"),
    )
