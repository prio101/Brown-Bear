"""Model registry.

Importing this package must register every table on ``Base.metadata`` —
Alembic's autogenerate depends on it. Add each new model module here.
"""

from brownbear.models.tokens import (
    ModelPricing,
    PeriodType,
    TokenEvent,
    TokenPeriod,
    TokenSource,
)

__all__ = [
    "ModelPricing",
    "PeriodType",
    "TokenEvent",
    "TokenPeriod",
    "TokenSource",
]
