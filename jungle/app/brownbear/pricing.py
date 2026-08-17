"""Model pricing and cost calculation (spec 003 §3.5).

Cost is resolved and stored at write time, not at read time. Rates change;
what a call cost when it happened does not.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from brownbear.models.tokens import ModelPricing

FALLBACK_MODEL = "*"
CENT_PRECISION = Decimal("0.000001")

#: Characters per token, for estimating the size of text Brown Bear served.
#: A rough English average. Everything derived from it is labelled an estimate:
#: tokenising properly would mean shipping a tokeniser per provider, and the
#: number is used for reporting what was saved, never for billing anyone.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str | None) -> int:
    """Approximate token count for served text. Deliberately crude and labelled."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def _candidates(model: str) -> list[str]:
    """Names to try, most specific first.

    Ollama tags models as ``llama3:8b``; pricing may be set for the exact tag
    or for the family. The ``*`` row makes unpriced models free rather than
    untracked, so local inference still produces rows with cost 0.
    """
    names = [model]
    if ":" in model:
        names.append(model.split(":", 1)[0])
    names.append(FALLBACK_MODEL)
    return names


@dataclass(frozen=True)
class Rates:
    """Everything needed to price one call.

    A record rather than a widening tuple: this went from two values to five, and
    a five-tuple at four call sites is how a multiplier ends up in the currency
    position without anything failing.
    """

    input_per_1k: Decimal
    output_per_1k: Decimal
    currency: str
    #: None when only the `*` fallback matched. Callers reporting *paid* usage
    #: need that: the fallback prices an unknown model at zero, right for local
    #: inference and wrong for a remote API.
    matched: str | None
    cache_write_multiplier: Decimal = Decimal("1.25")
    cache_read_multiplier: Decimal = Decimal("0.10")


def resolve(session: Session, model: str) -> Rates:
    """Full rates for a model, most specific pricing row first."""
    for name in _candidates(model):
        row = session.execute(
            select(ModelPricing)
            .where(
                ModelPricing.model_name == name,
                ModelPricing.is_active.is_(True),
                ModelPricing.effective_date <= date.today(),
            )
            .order_by(ModelPricing.effective_date.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is not None:
            return Rates(
                input_per_1k=row.input_cost_per_1k,
                output_per_1k=row.output_cost_per_1k,
                currency=row.currency,
                matched=None if name == FALLBACK_MODEL else name,
                cache_write_multiplier=row.cache_write_multiplier,
                cache_read_multiplier=row.cache_read_multiplier,
            )
    return Rates(Decimal("0"), Decimal("0"), "USD", None)


def resolve_rates(session: Session, model: str) -> tuple[Decimal, Decimal, str, str | None]:
    """Rates plus the pricing row that produced them.

    The fourth element is the matched model name, or None when only the ``*``
    fallback applied. Callers reporting *paid* usage need that distinction: the
    fallback prices an unknown model at zero, which is right for local
    inference and wrong for a remote API (spec 005 §5.5).
    """
    rates = resolve(session, model)
    return rates.input_per_1k, rates.output_per_1k, rates.currency, rates.matched


def get_rates(session: Session, model: str) -> tuple[Decimal, Decimal, str]:
    """Return (input_per_1k, output_per_1k, currency) for a model."""
    input_rate, output_rate, currency, _ = resolve_rates(session, model)
    return input_rate, output_rate, currency


def has_explicit_price(model: str) -> bool:
    """Whether this model has its own pricing row rather than the ``*`` fallback."""
    from brownbear.db import session_scope

    with session_scope() as session:
        return resolve_rates(session, model)[3] is not None


def calculate_cost(
    tokens_in: int, tokens_out: int, input_per_1k: Decimal, output_per_1k: Decimal
) -> Decimal:
    cost = (Decimal(tokens_in) / 1000) * input_per_1k + (
        Decimal(tokens_out) / 1000
    ) * output_per_1k
    return cost.quantize(CENT_PRECISION, rounding=ROUND_HALF_UP)


def calculate_bucketed_cost(
    *,
    tokens_in_fresh: int,
    tokens_cache_write: int,
    tokens_cache_read: int,
    tokens_out: int,
    rates: Rates,
) -> Decimal:
    """Price each input bucket at its own effective rate.

    This is the correction. Pricing all input at the base rate overstates a
    cache-heavy session badly: a long Claude Code turn can be a few thousand fresh
    tokens against millions of cache reads, and reads are billed at a tenth. On
    this instance the flat rule reported $887 for a month, dominated by a single
    turn charged $248 for 15.7M input tokens — more than the context window holds,
    so almost all of it was reads.
    """
    base = rates.input_per_1k
    cost = (
        (Decimal(tokens_in_fresh) / 1000) * base
        + (Decimal(tokens_cache_write) / 1000) * base * rates.cache_write_multiplier
        + (Decimal(tokens_cache_read) / 1000) * base * rates.cache_read_multiplier
        + (Decimal(tokens_out) / 1000) * rates.output_per_1k
    )
    return cost.quantize(CENT_PRECISION, rounding=ROUND_HALF_UP)


def calculate_avoided_cost(tokens_avoided: int, rates: Rates) -> Decimal:
    """What a provider was not paid for output it did not generate.

    Priced at the OUTPUT rate, and only output. When a cached answer is served in
    place of a model call, the tokens certainly not generated are that answer's.
    What the call would have cost in *input* is unknowable here — Brown Bear never
    sees the context the client would have sent — so claiming it would be
    invention. This under-reports the saving, which is the safe direction.
    """
    cost = (Decimal(tokens_avoided) / 1000) * rates.output_per_1k
    return cost.quantize(CENT_PRECISION, rounding=ROUND_HALF_UP)
