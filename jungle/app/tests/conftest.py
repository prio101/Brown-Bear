"""Test fixtures.

Nothing here touches a live service or a database. Connectors are faked, so
the suite runs in CI without the compose stack and cannot be made green or
red by whether Ollama happens to be up.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from brownbear.main import create_app


@pytest.fixture(autouse=True)
def _no_scheduler(monkeypatch):
    """Keep background aggregation out of the tests entirely."""
    monkeypatch.setattr("brownbear.scheduler.start_scheduler", lambda: None)
    monkeypatch.setattr("brownbear.scheduler.shutdown_scheduler", lambda: None)


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def mock_ollama(monkeypatch):
    """Point the proxy at an in-process fake Ollama.

    Returns a callable: pass the handler that should answer upstream requests.
    """

    def _install(handler):
        transport = httpx.MockTransport(handler)
        fake = httpx.AsyncClient(transport=transport)
        monkeypatch.setattr(
            "brownbear.routers.ollama_proxy.get_http_client", lambda: fake
        )
        return fake

    return _install


@pytest.fixture
def recorded(monkeypatch) -> list[dict]:
    """Capture token events instead of writing them to PostgreSQL."""
    events: list[dict] = []

    async def _record(**kwargs):
        events.append(kwargs)
        return len(events)

    monkeypatch.setattr("brownbear.routers.ollama_proxy.record_token_event", _record)
    return events


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Point the app's engine at a throwaway SQLite file.

    Almost everything here fakes the database, which is right: the suite must run
    without the compose stack. But a fake cannot catch a bug in the SQL or in the
    session bookkeeping — `session.delete()` followed by `session.expunge()`
    silently cancels the delete, and every faked test in the world reports that
    route as working. SQLite ships with Python, so a real round trip costs nothing
    in portability.

    Not a substitute for PostgreSQL: native enums and the migrations are
    PostgreSQL-only. It exercises the session, not the schema.
    """
    from brownbear import models  # noqa: F401  — registers every table
    from brownbear.config import get_settings
    from brownbear.db import Base, get_engine, reset_engine

    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", f"sqlite+pysqlite:///{tmp_path / 'test.sqlite'}")
    reset_engine()
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield engine
    reset_engine()
