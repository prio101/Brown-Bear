"""Shared connector types and timing helper."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ServiceHealth:
    name: str
    healthy: bool
    latency_ms: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "error": self.error,
        }


async def timed_check(
    name: str, probe: Callable[[], Awaitable[dict[str, Any]]]
) -> ServiceHealth:
    """Run a probe, timing it and turning any failure into an unhealthy result.

    A health endpoint that raises is a health endpoint that cannot report on
    the other services, so every exception is captured rather than propagated.
    """
    start = time.perf_counter()
    try:
        detail = await probe()
    except Exception as exc:  # noqa: BLE001 - deliberate: report, never raise
        return ServiceHealth(
            name=name,
            healthy=False,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            error=f"{type(exc).__name__}: {exc}",
        )
    return ServiceHealth(
        name=name,
        healthy=True,
        latency_ms=round((time.perf_counter() - start) * 1000, 2),
        detail=detail,
    )
