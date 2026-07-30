"""Runtime-editable settings (spec 001 §1.6).

Every setting declares its own bounds, so an operator cannot set a one-second
polling interval that hammers the database, and cannot type a value the app
will later choke on.

Each setting also declares *when it takes effect*. Collection intervals
reschedule their jobs immediately; alert thresholds are stored for the
alerting work in H2 to consume and do nothing on their own. The dashboard
shows that status rather than implying every change is live.
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from brownbear.config import get_settings
from brownbear.db import session_scope
from brownbear.models.settings import AppSetting

logger = logging.getLogger(__name__)

Effect = Literal["live", "restart", "alerting"]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    kind: type
    minimum: float
    maximum: float
    unit: str
    help: str
    effect: Effect
    config_attr: str | None = None
    fallback: float | None = None

    def default(self) -> float:
        if self.config_attr:
            return getattr(get_settings(), self.config_attr)
        return self.fallback if self.fallback is not None else 0

    def parse(self, raw: Any) -> float:
        try:
            value = self.kind(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{self.key} must be {self.kind.__name__}") from exc
        if not (self.minimum <= value <= self.maximum):
            raise ValueError(
                f"{self.key} must be between {self.minimum} and {self.maximum} {self.unit}".strip()
            )
        return value


SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        key="snapshot_interval_seconds",
        label="System snapshot interval",
        kind=int,
        minimum=5,
        maximum=3600,
        unit="seconds",
        help="How often host CPU, memory and disk are sampled.",
        effect="live",
        config_attr="snapshot_interval_seconds",
    ),
    SettingSpec(
        key="cache_sample_interval_seconds",
        label="Cache sample interval",
        kind=int,
        minimum=5,
        maximum=3600,
        unit="seconds",
        help="How often Redis counters are read.",
        effect="live",
        config_attr="cache_sample_interval_seconds",
    ),
    SettingSpec(
        key="monitoring_retention_days",
        label="Monitoring retention",
        kind=int,
        minimum=1,
        maximum=365,
        unit="days",
        help="Age at which snapshots and cache samples are pruned.",
        effect="live",
        config_attr="monitoring_retention_days",
    ),
    SettingSpec(
        key="daily_token_budget_usd",
        label="Daily cost budget",
        kind=float,
        minimum=0,
        maximum=100000,
        unit="USD",
        help="Spend per UTC day that should raise an alert. 0 disables it.",
        effect="alerting",
        fallback=0.0,
    ),
    SettingSpec(
        key="cache_hit_rate_floor",
        label="Cache hit rate floor",
        kind=float,
        minimum=0,
        maximum=1,
        unit="ratio",
        help="Hit rate below which the cache should raise an alert. 0 disables it.",
        effect="alerting",
        fallback=0.0,
    ),
    SettingSpec(
        key="disk_percent_ceiling",
        label="Disk usage ceiling",
        kind=float,
        minimum=0,
        maximum=100,
        unit="percent",
        help="Host disk usage above which an alert should fire. 0 disables it.",
        effect="alerting",
        fallback=0.0,
    ),
    # --- context gateway (spec 005 §5.4) ---
    SettingSpec(
        key="cache_similarity_threshold",
        label="Cache hit threshold",
        kind=float,
        # Floor of 0.5: below that, "similar" stops meaning anything and the
        # cache would serve unrelated answers with confidence.
        minimum=0.5,
        maximum=1.0,
        unit="cosine",
        help="Cosine similarity required to serve a cached answer. Higher is stricter.",
        effect="live",
        config_attr="cache_similarity_threshold",
    ),
    SettingSpec(
        key="context_top_k",
        label="Retrieved chunks",
        kind=int,
        minimum=1,
        maximum=50,
        unit="chunks",
        help="How many knowledge chunks a context request returns.",
        effect="live",
        config_attr="context_top_k",
    ),
    SettingSpec(
        key="cache_ttl_days",
        label="Cached answer lifetime",
        kind=int,
        minimum=0,
        maximum=3650,
        unit="days",
        help="Age at which a cached answer stops being served. 0 disables expiry.",
        effect="live",
        config_attr="cache_ttl_days",
    ),
)

BY_KEY = {spec.key: spec for spec in SPECS}


def _stored() -> dict[str, str]:
    with session_scope() as session:
        return {row.key: row.value for row in session.execute(select(AppSetting)).scalars()}


def effective() -> dict[str, dict[str, Any]]:
    """Every setting with its current value, default, and where it came from."""
    stored = _stored()
    result: dict[str, dict[str, Any]] = {}
    for spec in SPECS:
        default = spec.default()
        value = default
        source = "default"
        raw = stored.get(spec.key)
        if raw is not None:
            try:
                value = spec.parse(raw)
                source = "database"
            except ValueError:
                # A stored value that no longer validates must not take the app
                # down; fall back to the default and say so.
                logger.warning("ignoring invalid stored setting %s=%r", spec.key, raw)
                source = "invalid-ignored"
        result[spec.key] = {
            "key": spec.key,
            "label": spec.label,
            "value": value,
            "default": default,
            "source": source,
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "unit": spec.unit,
            "help": spec.help,
            "effect": spec.effect,
            "type": spec.kind.__name__,
        }
    return result


def value_of(key: str) -> float:
    return effective()[key]["value"]


def update(values: dict[str, Any]) -> dict[str, float]:
    """Validate and persist overrides. Rejects the whole batch on any error."""
    unknown = set(values) - set(BY_KEY)
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(sorted(unknown))}")

    parsed = {key: BY_KEY[key].parse(raw) for key, raw in values.items()}

    with session_scope() as session:
        for key, value in parsed.items():
            statement = pg_insert(AppSetting).values(key=key, value=str(value))
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[AppSetting.key],
                    set_={"value": statement.excluded.value, "updated_at": func.now()},
                )
            )
    return parsed
