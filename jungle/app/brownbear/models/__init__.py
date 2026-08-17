"""Model registry.

Importing this package must register every table on ``Base.metadata`` —
Alembic's autogenerate depends on it. Add each new model module here.
"""

from brownbear.models.aggregation import AggregationRun, RunStatus
from brownbear.models.files import FileRecord, FileStatus
from brownbear.models.monitoring import CacheSample, QueryLog, SystemSnapshot
from brownbear.models.settings import AppSetting
from brownbear.models.tokens import (
    ModelPricing,
    PeriodType,
    TokenEvent,
    TokenPeriod,
    TokenSource,
)

__all__ = [
    "AggregationRun",
    "AppSetting",
    "CacheSample",
    "FileRecord",
    "FileStatus",
    "ModelPricing",
    "PeriodType",
    "QueryLog",
    "RunStatus",
    "SystemSnapshot",
    "TokenEvent",
    "TokenPeriod",
    "TokenSource",
]
