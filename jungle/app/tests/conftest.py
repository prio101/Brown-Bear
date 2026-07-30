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
