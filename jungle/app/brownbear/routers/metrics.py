"""Prometheus metrics (spec 001 §1.5).

Hand-rolled exposition format rather than a client library: the app exports a
few dozen series computed from SQL on each scrape, with no in-process counters
to register, so a library would add a dependency and a second source of truth
without removing any work.

Counter caveat: token totals are summed from raw ``token_events``, which
retention prunes (spec 003 §3.7). Prometheus reads a decrease as a counter
reset, so long-range totals belong in Prometheus' own recording rules or in
/api/tokens/history, which reads the retained aggregates.
"""

import asyncio
from typing import Any

import anyio.to_thread
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from brownbear.connectors import chroma, ollama, postgres, redis_conn
from brownbear.db import session_scope
from brownbear.models.aggregation import AggregationRun, RunStatus
from brownbear.models.monitoring import CacheSample, SystemSnapshot
from brownbear.models.tokens import TokenEvent

router = APIRouter(tags=["metrics"])

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(pairs: dict[str, Any]) -> str:
    if not pairs:
        return ""
    inner = ",".join(f'{key}="{_escape(str(value))}"' for key, value in pairs.items())
    return "{" + inner + "}"


class MetricWriter:
    """Accumulates exposition-format lines, emitting HELP/TYPE once per metric."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._declared: set[str] = set()

    def add(
        self,
        name: str,
        value: float | int | None,
        *,
        help_text: str,
        metric_type: str = "gauge",
        labels: dict[str, Any] | None = None,
    ) -> None:
        if value is None:
            return
        if name not in self._declared:
            self._lines.append(f"# HELP {name} {help_text}")
            self._lines.append(f"# TYPE {name} {metric_type}")
            self._declared.add(name)
        self._lines.append(f"{name}{_labels(labels or {})} {value}")

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"


def _database_metrics(writer: MetricWriter) -> None:
    with session_scope() as session:
        token_rows = session.execute(
            select(
                TokenEvent.model,
                TokenEvent.source,
                func.sum(TokenEvent.tokens_in),
                func.sum(TokenEvent.tokens_out),
                func.sum(TokenEvent.cost_usd),
                func.count(TokenEvent.id),
            ).group_by(TokenEvent.model, TokenEvent.source)
        ).all()

        for model, source, tokens_in, tokens_out, cost, requests in token_rows:
            base = {"model": model, "source": source.value}
            writer.add(
                "brownbear_tokens_total",
                int(tokens_in or 0),
                help_text="Tokens consumed, by model, source and direction.",
                metric_type="counter",
                labels={**base, "direction": "in"},
            )
            writer.add(
                "brownbear_tokens_total",
                int(tokens_out or 0),
                help_text="Tokens consumed, by model, source and direction.",
                metric_type="counter",
                labels={**base, "direction": "out"},
            )
            writer.add(
                "brownbear_cost_usd_total",
                float(cost or 0),
                help_text="Estimated cost in USD, by model and source.",
                metric_type="counter",
                labels=base,
            )
            writer.add(
                "brownbear_requests_total",
                int(requests or 0),
                help_text="AI requests recorded, by model and source.",
                metric_type="counter",
                labels=base,
            )

        snapshot = session.execute(
            select(SystemSnapshot).order_by(SystemSnapshot.timestamp.desc()).limit(1)
        ).scalar_one_or_none()
        if snapshot is not None:
            writer.add(
                "brownbear_host_cpu_percent",
                float(snapshot.cpu_percent),
                help_text="Host CPU utilisation percent from the newest snapshot.",
            )
            writer.add(
                "brownbear_host_memory_percent",
                float(snapshot.memory_percent),
                help_text="Host memory utilisation percent from the newest snapshot.",
            )
            writer.add(
                "brownbear_host_disk_percent",
                float(snapshot.disk_percent),
                help_text="Host disk utilisation percent from the newest snapshot.",
            )

        sample = session.execute(
            select(CacheSample).order_by(CacheSample.timestamp.desc()).limit(1)
        ).scalar_one_or_none()
        if sample is not None:
            writer.add(
                "brownbear_redis_keyspace_hits_total",
                sample.keyspace_hits,
                help_text="Redis keyspace hits since the Redis process started.",
                metric_type="counter",
            )
            writer.add(
                "brownbear_redis_keyspace_misses_total",
                sample.keyspace_misses,
                help_text="Redis keyspace misses since the Redis process started.",
                metric_type="counter",
            )
            writer.add(
                "brownbear_redis_memory_bytes",
                sample.used_memory_bytes,
                help_text="Redis memory in use.",
            )
            writer.add(
                "brownbear_redis_keys",
                sample.total_keys,
                help_text="Keys currently stored in Redis.",
            )

        run_rows = session.execute(
            select(AggregationRun.period_type, func.max(AggregationRun.window_start))
            .where(AggregationRun.status == RunStatus.completed)
            .group_by(AggregationRun.period_type)
        ).all()
        for period, window_start in run_rows:
            writer.add(
                "brownbear_aggregation_latest_window_timestamp_seconds",
                window_start.timestamp(),
                help_text="Start of the newest successfully aggregated window, per period.",
                labels={"period": period.value},
            )


@router.get("/api/metrics", response_class=PlainTextResponse)
@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    writer = MetricWriter()
    writer.add("brownbear_up", 1, help_text="Brown Bear app is serving requests.")

    checks = await asyncio.gather(
        ollama.check(), chroma.check(), redis_conn.check(), postgres.check()
    )
    for result in checks:
        writer.add(
            "brownbear_service_up",
            1 if result.healthy else 0,
            help_text="Backing service reachable (1) or not (0).",
            labels={"service": result.name},
        )
        writer.add(
            "brownbear_service_check_duration_ms",
            result.latency_ms,
            help_text="How long the health probe took.",
            labels={"service": result.name},
        )

    chroma_result = next((r for r in checks if r.name == "chromadb"), None)
    if chroma_result is not None and chroma_result.healthy:
        writer.add(
            "brownbear_chroma_collections",
            chroma_result.detail.get("collection_count"),
            help_text="ChromaDB collections.",
        )

    await anyio.to_thread.run_sync(lambda: _database_metrics(writer))

    return PlainTextResponse(writer.render(), media_type=CONTENT_TYPE)
