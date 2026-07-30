"""Health aggregation (spec 001 §1.5)."""

from brownbear.connectors import chroma, ollama, postgres, redis_conn
from brownbear.connectors.base import ServiceHealth, timed_check


class TestTimedCheck:
    async def test_failure_becomes_an_unhealthy_result(self):
        async def boom() -> dict:
            raise ConnectionError("refused")

        result = await timed_check("ollama", boom)

        assert result.healthy is False
        assert "ConnectionError: refused" == result.error
        assert result.latency_ms is not None

    async def test_success_carries_detail(self):
        async def probe() -> dict:
            return {"model_count": 2}

        result = await timed_check("ollama", probe)

        assert result.healthy is True
        assert result.detail == {"model_count": 2}
        assert result.error is None


class TestHealthEndpoint:
    def test_live_never_depends_on_backing_services(self, client):
        assert client.get("/api/health/live").json() == {"status": "ok"}

    def test_reports_all_four_services(self, client, monkeypatch):
        for module, name in (
            (ollama, "ollama"),
            (chroma, "chromadb"),
            (redis_conn, "redis"),
            (postgres, "postgres"),
        ):

            async def healthy(_name=name) -> ServiceHealth:
                return ServiceHealth(name=_name, healthy=True, latency_ms=1.0)

            monkeypatch.setattr(module, "check", healthy)

        payload = client.get("/api/health").json()

        assert payload["healthy"] is True
        assert set(payload["services"]) == {"ollama", "chromadb", "redis", "postgres"}

    def test_one_bad_service_degrades_the_verdict_not_the_response(
        self, client, monkeypatch
    ):
        """A dead dependency must not make the app itself look dead."""

        async def healthy(_name="x") -> ServiceHealth:
            return ServiceHealth(name=_name, healthy=True)

        async def down() -> ServiceHealth:
            return ServiceHealth(name="redis", healthy=False, error="ConnectionError")

        monkeypatch.setattr(ollama, "check", lambda: healthy("ollama"))
        monkeypatch.setattr(chroma, "check", lambda: healthy("chromadb"))
        monkeypatch.setattr(postgres, "check", lambda: healthy("postgres"))
        monkeypatch.setattr(redis_conn, "check", down)

        resp = client.get("/api/health")

        assert resp.status_code == 200
        assert resp.json()["healthy"] is False
        assert resp.json()["services"]["redis"]["error"] == "ConnectionError"
