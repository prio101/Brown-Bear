"""Cached embeddings (BB-201).

The bug this closes: nothing in the app ever wrote a Redis key, so
``keyspace_hits`` was pinned at zero and the dashboard charted a metric for work
that never happened. These tests pin the two properties that make the cache safe
to rely on — model-scoped keys, and failure that degrades to recomputing.
"""

import pytest

from brownbear import embeddings
from brownbear.config import get_settings
from brownbear.connectors import ollama, redis_conn

VECTOR = [0.1, 0.2, 0.3]


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeCache:
    """In-memory stand-in, recording calls so hits can be distinguished from writes."""

    def __init__(self, *, read_fails: bool = False, write_fails: bool = False):
        self.store: dict[str, object] = {}
        self.reads: list[str] = []
        self.writes: list[tuple[str, int]] = []
        self.read_fails = read_fails
        self.write_fails = write_fails

    async def get(self, key: str):
        self.reads.append(key)
        if self.read_fails:
            return None
        return self.store.get(key)

    async def set(self, key: str, value, ttl_seconds: int) -> bool:
        self.writes.append((key, ttl_seconds))
        if self.write_fails:
            return False
        self.store[key] = value
        return True


@pytest.fixture
def cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(redis_conn, "cache_get", fake.get)
    monkeypatch.setattr(redis_conn, "cache_set", fake.set)
    return fake


@pytest.fixture
def embedder(monkeypatch):
    calls: list[str] = []

    async def fake_embed_one(text: str, model: str | None = None) -> list[float]:
        calls.append(text)
        return list(VECTOR)

    monkeypatch.setattr(ollama, "embed_one", fake_embed_one)
    return calls


class TestCacheKey:
    def test_model_is_part_of_the_key(self):
        """The one correctness constraint that matters.

        A nomic-embed-text vector is meaningless to another model, and serving one
        silently would corrupt every similarity score the gateway then compares to
        a 0.95 cutoff.
        """
        assert embeddings.cache_key("hello", "nomic-embed-text") != embeddings.cache_key(
            "hello", "some-other-model"
        )

    def test_same_text_and_model_is_the_same_key(self):
        assert embeddings.cache_key("hello", "m") == embeddings.cache_key("hello", "m")

    def test_different_text_is_a_different_key(self):
        assert embeddings.cache_key("hello", "m") != embeddings.cache_key("goodbye", "m")

    def test_key_is_digested_not_the_raw_prompt(self):
        # Prompts run to 32k characters; a key that size is wasteful and awkward.
        key = embeddings.cache_key("x" * 5000, "m")
        assert len(key) < 120
        assert "xxxx" not in key


class TestCaching:
    async def test_first_call_misses_and_writes(self, cache, embedder):
        vector = await embeddings.embed_one("a prompt")

        assert vector == VECTOR
        assert embedder == ["a prompt"]  # the model ran once
        assert len(cache.writes) == 1

    async def test_second_call_hits_and_does_not_run_the_model(self, cache, embedder):
        await embeddings.embed_one("a prompt")
        vector = await embeddings.embed_one("a prompt")

        assert vector == VECTOR
        # The point of the whole exercise: one model call for two requests.
        assert embedder == ["a prompt"]
        assert len(cache.writes) == 1

    async def test_write_carries_the_configured_ttl(self, cache, embedder):
        await embeddings.embed_one("a prompt")

        _, ttl = cache.writes[0]
        assert ttl == get_settings().embedding_cache_ttl_seconds
        # Mandatory: an embedding cache without expiry grows without bound on a
        # box that is also running a model server.
        assert ttl > 0

    async def test_disabled_bypasses_redis_entirely(self, cache, embedder, monkeypatch):
        monkeypatch.setenv("BB_EMBEDDING_CACHE_ENABLED", "false")
        get_settings.cache_clear()

        await embeddings.embed_one("a prompt")

        assert cache.reads == []
        assert cache.writes == []
        assert embedder == ["a prompt"]


class TestDegradation:
    """A cache that can break what it accelerates is worse than no cache."""

    async def test_unreachable_redis_still_returns_a_vector(self, monkeypatch, embedder):
        fake = FakeCache(read_fails=True, write_fails=True)
        monkeypatch.setattr(redis_conn, "cache_get", fake.get)
        monkeypatch.setattr(redis_conn, "cache_set", fake.set)

        vector = await embeddings.embed_one("a prompt")

        assert vector == VECTOR
        assert embedder == ["a prompt"]

    @pytest.mark.parametrize(
        "poison",
        [
            "not a list",
            [],
            ["not", "numbers"],
            [0.1, "mixed"],
            {"vector": [0.1]},
            None,
        ],
    )
    async def test_a_corrupt_entry_is_a_miss_not_a_crash(
        self, cache, embedder, monkeypatch, poison
    ):
        """A wrong-shaped payload must not reach Chroma, where it would fail far
        from its cause."""
        key = embeddings.cache_key("a prompt", get_settings().embedding_model)
        cache.store[key] = poison

        vector = await embeddings.embed_one("a prompt")

        assert vector == VECTOR
        assert embedder == ["a prompt"]


class TestRedisHelpers:
    async def test_cache_get_treats_every_failure_as_a_miss(self, monkeypatch):
        class Boom:
            async def get(self, key):
                raise ConnectionError("refused")

        monkeypatch.setattr(redis_conn, "get_redis", lambda: Boom())

        assert await redis_conn.cache_get("k") is None

    async def test_cache_get_survives_an_unparseable_value(self, monkeypatch):
        class Garbage:
            async def get(self, key):
                return "{not json"

        monkeypatch.setattr(redis_conn, "get_redis", lambda: Garbage())

        assert await redis_conn.cache_get("k") is None

    async def test_cache_set_returns_false_instead_of_raising(self, monkeypatch):
        class Boom:
            async def set(self, key, value, ex=None):
                raise ConnectionError("refused")

        monkeypatch.setattr(redis_conn, "get_redis", lambda: Boom())

        assert await redis_conn.cache_set("k", [0.1], 60) is False

    async def test_cache_set_round_trips_through_json(self, monkeypatch):
        written: dict[str, str] = {}

        class Recorder:
            async def set(self, key, value, ex=None):
                written[key] = value

            async def get(self, key):
                return written.get(key)

        monkeypatch.setattr(redis_conn, "get_redis", lambda: Recorder())

        assert await redis_conn.cache_set("k", [0.1, 0.2], 60) is True
        assert await redis_conn.cache_get("k") == [0.1, 0.2]

    async def test_ttl_floor_is_enforced(self, monkeypatch):
        seen: list[int] = []

        class Recorder:
            async def set(self, key, value, ex=None):
                seen.append(ex)

        monkeypatch.setattr(redis_conn, "get_redis", lambda: Recorder())

        await redis_conn.cache_set("k", [0.1], 0)

        # Never a zero or negative expiry, which Redis rejects outright.
        assert seen == [1]
