"""The /ext gateway endpoints (spec 005 §5.3–5.5).

Chroma and Ollama are faked: the suite must not depend on an embedding model
being pulled, and must not be turned red by whether Ollama happens to be up.
"""

import pytest

from brownbear import gateway
from brownbear.routers import ext


@pytest.fixture
def fake_collections(monkeypatch):
    """Pretend both collections exist, in cosine space."""
    collections = gateway.Collections("conv-id", "know-id", "cosine", "cosine")

    async def _ensure():
        return collections

    monkeypatch.setattr(gateway, "ensure_collections", _ensure)
    return collections


@pytest.fixture
def fake_embed(monkeypatch):
    async def _embed(texts, model=None):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def _embed_one(text, model=None):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(ext.ollama, "embed_one", _embed_one)
    monkeypatch.setattr(gateway.ollama, "embed", _embed)
    monkeypatch.setattr(gateway.ollama, "embed_one", _embed_one)


@pytest.fixture
def captured_upserts(monkeypatch):
    calls: list[dict] = []

    async def _upsert(collection_id, **kwargs):
        calls.append({"collection": collection_id, **kwargs})

    monkeypatch.setattr(gateway.chroma, "upsert", _upsert)
    return calls


@pytest.fixture
def no_query_log(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(gateway, "log_query", _noop)


@pytest.fixture
def fake_query(monkeypatch):
    def _install(hits):
        async def _query(*args, **kwargs):
            return hits

        monkeypatch.setattr(gateway.chroma, "query", _query)

    return _install


class TestUnavailableGateway:
    def test_embedding_failure_is_503_not_500(self, client, monkeypatch):
        """A missing embedding model is an operational fact, not a bug."""

        async def _boom():
            raise RuntimeError("501 no embedding support")

        monkeypatch.setattr(gateway, "ensure_collections", _boom)
        response = client.post("/ext/context", json={"prompt": "hi"})
        assert response.status_code == 503
        # The message has to say what to fix.
        assert "embedding model" in response.json()["detail"]

    def test_health_reports_not_ready_rather_than_failing(self, client, monkeypatch):
        async def _boom():
            raise RuntimeError("chroma down")

        monkeypatch.setattr(gateway, "ensure_collections", _boom)
        body = client.get("/ext/health").json()
        assert body["ready"] is False
        assert "chroma down" in body["error"]


class TestDocuments:
    def test_ingest_stores_chunks_with_attribution(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        response = client.post(
            "/ext/documents",
            json={"text": "a sentence about bears", "source": "notes.md", "project": "repo"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["chunks_stored"] == 1

        stored = captured_upserts[0]
        assert stored["collection"] == "know-id"
        assert stored["metadatas"][0]["source"] == "notes.md"
        assert stored["metadatas"][0]["project"] == "repo"

    def test_reingest_reuses_ids(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        payload = {"text": "stable content", "source": "a.md", "project": "repo"}
        first = client.post("/ext/documents", json=payload).json()
        second = client.post("/ext/documents", json=payload).json()
        assert first["ids"] == second["ids"]

    def test_empty_text_is_rejected(self, client):
        assert client.post(
            "/ext/documents", json={"text": "", "source": "a.md"}
        ).status_code == 422

    def test_oversized_text_is_rejected(self, client):
        response = client.post(
            "/ext/documents",
            json={"text": "x" * (ext.MAX_DOCUMENT_CHARS + 1), "source": "a.md"},
        )
        assert response.status_code == 422


class TestContext:
    def test_miss_returns_chunks_with_sources(
        self, client, fake_collections, fake_embed, no_query_log, fake_query
    ):
        fake_query(
            [
                {
                    "id": "c1",
                    "document": "retrieved text",
                    "distance": 0.4,
                    "metadata": {"source": "notes.md", "project": "repo", "chunk_index": 0},
                }
            ]
        )
        body = client.post(
            "/ext/context", json={"prompt": "question", "project": "repo", "model": "m"}
        ).json()
        assert body["hit"] is False
        assert body["chunks"][0]["source"] == "notes.md"
        assert body["chunks"][0]["score"] == 0.6

    def test_hit_short_circuits_retrieval(
        self, client, fake_collections, fake_embed, no_query_log, fake_query
    ):
        fake_query(
            [
                {
                    "id": "x1",
                    "document": "the cached answer",
                    "distance": 0.0,
                    "metadata": {"prompt": "question", "cacheable": True},
                }
            ]
        )
        body = client.post(
            "/ext/context", json={"prompt": "question", "project": "repo", "model": "m"}
        ).json()
        assert body["hit"] is True
        assert body["answer"] == "the cached answer"
        # No point retrieving context for an answer we already have.
        assert body["chunks"] == []

    def test_skip_cache_forces_retrieval(
        self, client, fake_collections, fake_embed, no_query_log, fake_query
    ):
        fake_query(
            [{"id": "x1", "document": "cached", "distance": 0.0,
              "metadata": {"prompt": "question", "cacheable": True}}]
        )
        body = client.post(
            "/ext/context",
            json={"prompt": "question", "project": "repo", "model": "m", "skip_cache": True},
        ).json()
        assert body["hit"] is False
        assert body["reason"] == "skipped"

    def test_threshold_is_reported_so_a_client_can_judge(
        self, client, fake_collections, fake_embed, no_query_log, fake_query
    ):
        fake_query([])
        body = client.post("/ext/context", json={"prompt": "q"}).json()
        assert body["threshold"] == gateway.threshold()


class TestExchange:
    @pytest.fixture(autouse=True)
    def _recorded(self, monkeypatch):
        self.events: list[dict] = []

        async def _record(**kwargs):
            self.events.append(kwargs)
            return len(self.events)

        monkeypatch.setattr(ext, "record_token_event", _record)
        monkeypatch.setattr(ext.pricing, "has_explicit_price", lambda model: False)

    def test_stores_the_pair_and_records_usage(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        body = client.post(
            "/ext/exchange",
            json={
                "prompt": "a stable question",
                "response": "an answer",
                "project": "repo",
                "model": "claude-opus-5",
                "tokens_in": 100,
                "tokens_out": 20,
            },
        ).json()
        assert body["stored"] is True
        assert body["token_event_id"] == 1

        # The prompt is embedded and the answer stored as the document, so a
        # later lookup matches on what was asked.
        stored = captured_upserts[0]
        assert stored["collection"] == "conv-id"
        assert stored["documents"] == ["an answer"]
        assert stored["metadatas"][0]["prompt"] == "a stable question"

    def test_volatile_prompt_is_stored_but_flagged(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        body = client.post(
            "/ext/exchange",
            json={"prompt": "what is the disk usage today?", "response": "9%",
                  "project": "repo", "model": "m"},
        ).json()
        assert body["cached_entry"]["cacheable"] is False
        assert captured_upserts[0]["metadatas"][0]["cacheable"] is False

    def test_unpriced_paid_model_warns(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        body = client.post(
            "/ext/exchange",
            json={"prompt": "q", "response": "a", "model": "some-paid-model",
                  "tokens_in": 1000, "tokens_out": 500},
        ).json()
        # The `*` fallback would record this as free; that must not read as fact.
        assert any("should not be trusted" in w for w in body["warnings"])

    def test_supplied_cost_suppresses_the_warning(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        body = client.post(
            "/ext/exchange",
            json={"prompt": "q", "response": "a", "model": "some-paid-model",
                  "tokens_in": 1000, "tokens_out": 500, "cost_usd": "0.0225"},
        ).json()
        assert body["warnings"] == []
        assert str(self.events[0]["cost_usd"]) == "0.0225"

    def test_no_tokens_reported_means_no_event(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        body = client.post(
            "/ext/exchange", json={"prompt": "q", "response": "a"}
        ).json()
        assert body["token_event_id"] is None
        assert self.events == []

    def test_store_false_only_meters(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        body = client.post(
            "/ext/exchange",
            json={"prompt": "q", "response": "a", "tokens_in": 5, "tokens_out": 5,
                  "store": False},
        ).json()
        assert body["stored"] is False
        assert captured_upserts == []
        assert len(self.events) == 1

    def test_usage_is_attributed_to_the_remote_source(
        self, client, fake_collections, fake_embed, captured_upserts
    ):
        client.post(
            "/ext/exchange",
            json={"prompt": "q", "response": "a", "model": "claude-opus-5",
                  "tokens_in": 10, "tokens_out": 2, "request_id": "r-1"},
        )
        event = self.events[0]
        # The client called Anthropic, not this proxy: it must not look local.
        assert event["source"].value == "remote_api"
        assert event["request_id"] == "r-1"
