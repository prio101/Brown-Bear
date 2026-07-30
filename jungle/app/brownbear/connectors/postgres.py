"""PostgreSQL connector (spec 001 §1.3).

The engine is sync, so probes hop to a worker thread rather than blocking
the event loop and stalling every other health check.
"""

from typing import Any

import anyio.to_thread
from sqlalchemy import text

from brownbear.connectors.base import ServiceHealth, timed_check
from brownbear.db import get_engine


def _probe_sync() -> dict[str, Any]:
    engine = get_engine()
    with engine.connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar_one()
        database = conn.execute(text("SELECT current_database()")).scalar_one()
    pool = engine.pool
    return {
        "server_version": version,
        "database": database,
        "pool_size": pool.size(),
        "checked_out": pool.checkedout(),
    }


async def check() -> ServiceHealth:
    async def probe() -> dict[str, Any]:
        return await anyio.to_thread.run_sync(_probe_sync)

    return await timed_check("postgres", probe)
