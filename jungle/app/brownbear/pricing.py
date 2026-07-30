"""Model pricing and cost calculation (spec 003 §3.5).

Cost is resolved and stored at write time, not at read time. Rates change;
what a call cost when it happened does not.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from brownbear.models.tokens import ModelPricing

FALLBACK_MODEL = "*"
CENT_PRECISION = Decimal("0.000001")


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


def get_rates(session: Session, model: str) -> tuple[Decimal, Decimal, str]:
    """Return (input_per_1k, output_per_1k, currency) for a model."""
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
            return row.input_cost_per_1k, row.output_cost_per_1k, row.currency
    return Decimal("0"), Decimal("0"), "USD"


def calculate_cost(
    tokens_in: int, tokens_out: int, input_per_1k: Decimal, output_per_1k: Decimal
) -> Decimal:
    cost = (Decimal(tokens_in) / 1000) * input_per_1k + (
        Decimal(tokens_out) / 1000
    ) * output_per_1k
    return cost.quantize(CENT_PRECISION, rounding=ROUND_HALF_UP)
