"""Context gateway logic (spec 005).

The cache safety rules are the point of these tests: a cache that serves a
confidently wrong answer is worse than no cache, so the refusals matter more
than the hits.
"""

from datetime import UTC, datetime, timedelta

import pytest

from brownbear import gateway


class TestChunking:
    def test_short_text_is_one_chunk(self):
        assert gateway.chunk_text("hello", 100, 20) == ["hello"]

    def test_empty_text_yields_nothing(self):
        assert gateway.chunk_text("   ", 100, 20) == []

    def test_long_text_splits(self):
        text = "word " * 500  # 2500 chars
        chunks = gateway.chunk_text(text, 500, 100)
        assert len(chunks) > 1
        assert all(len(chunk) <= 500 for chunk in chunks)

    def test_chunks_cover_the_whole_text(self):
        text = "".join(f"sentence {i}. " for i in range(200))
        chunks = gateway.chunk_text(text, 300, 50)
        # Every chunk's content appears in the source, and the tail is reached.
        assert all(chunk in text for chunk in chunks)
        assert text.strip().endswith(chunks[-1][-20:])

    def test_overlap_keeps_a_boundary_sentence_whole_somewhere(self):
        text = "A" * 280 + " the sentence that straddles a boundary. " + "B" * 280
        chunks = gateway.chunk_text(text, 300, 120)
        assert any("straddles a boundary" in chunk for chunk in chunks)

    def test_zero_overlap_still_terminates(self):
        chunks = gateway.chunk_text("x" * 1000, 100, 0)
        assert len(chunks) == 10


class TestVolatilePrompts:
    @pytest.mark.parametrize(
        "prompt",
        [
            "What is the disk usage today?",
            "What time is it right now?",
            "Show me the latest commit",
            "What did I do yesterday?",
            "Plans for tomorrow?",
            "What is the current branch?",
        ],
    )
    def test_time_dependent_prompts_are_volatile(self, prompt):
        assert gateway.is_volatile(prompt) is True

    @pytest.mark.parametrize(
        "prompt",
        [
            "Which database stores metadata?",
            "Explain how cosine similarity works",
            "What port does ChromaDB listen on?",
        ],
    )
    def test_stable_questions_are_cacheable(self, prompt):
        assert gateway.is_volatile(prompt) is False

    def test_pasted_file_is_volatile(self):
        assert gateway.is_volatile("x" * (gateway.PASTED_CONTENT_CHARS + 1)) is True


class TestSimilarity:
    def test_cosine_distance_becomes_similarity(self):
        assert gateway.similarity(0.0, "cosine") == 1.0
        assert gateway.similarity(0.05, "cosine") == 0.95

    def test_non_cosine_space_is_not_convertible(self):
        # l2 distances are unbounded, so they cannot be compared to a 0.95
        # cutoff. None means "cannot serve a hit" rather than a wrong guess.
        assert gateway.similarity(0.2, "l2") is None
        assert gateway.similarity(0.2, None) is None

    def test_missing_distance_is_none(self):
        assert gateway.similarity(None, "cosine") is None


class TestIdentity:
    def test_same_content_same_id(self):
        assert gateway.content_id("p", "text") == gateway.content_id("p", "text")

    def test_project_scopes_the_id(self):
        assert gateway.content_id("a", "text") != gateway.content_id("b", "text")

    def test_exchange_id_scoped_by_project_and_model(self):
        base = gateway.exchange_id("p", "m", "prompt")
        assert base != gateway.exchange_id("p2", "m", "prompt")
        assert base != gateway.exchange_id("p", "m2", "prompt")
        assert base == gateway.exchange_id("p", "m", "prompt")


class TestScopeFilter:
    def test_project_only(self):
        assert gateway._scope_filter("repo") == {"project": {"$eq": "repo"}}

    def test_project_and_model_are_both_required(self):
        where = gateway._scope_filter("repo", "claude-opus-5")
        assert where == {
            "$and": [
                {"project": {"$eq": "repo"}},
                {"model": {"$eq": "claude-opus-5"}},
            ]
        }


class TestExpiry:
    def test_absent_stale_after_never_expires(self):
        assert gateway._is_expired({}, datetime.now(UTC)) is False

    def test_future_stamp_is_live(self):
        now = datetime.now(UTC)
        meta = {"stale_after": (now + timedelta(days=1)).isoformat()}
        assert gateway._is_expired(meta, now) is False

    def test_past_stamp_is_expired(self):
        now = datetime.now(UTC)
        meta = {"stale_after": (now - timedelta(seconds=1)).isoformat()}
        assert gateway._is_expired(meta, now) is True

    def test_unparseable_stamp_is_treated_as_expired(self):
        # Refusing to serve is the safe direction for a cache.
        assert gateway._is_expired({"stale_after": "not-a-date"}, datetime.now(UTC)) is True


class TestCacheLookup:
    """lookup_cache's decisions, with Chroma and the query log faked out."""

    @pytest.fixture
    def collections(self):
        return gateway.Collections(
            conversations="conv-id",
            knowledge="know-id",
            conversations_space="cosine",
            knowledge_space="cosine",
        )

    @pytest.fixture(autouse=True)
    def _quiet_query_log(self, monkeypatch):
        async def _noop(*args, **kwargs):
            return None

        monkeypatch.setattr(gateway, "log_query", _noop)

    @pytest.fixture
    def fake_hits(self, monkeypatch):
        def _install(hits):
            async def _query(*args, **kwargs):
                return hits

            monkeypatch.setattr(gateway.chroma, "query", _query)

        return _install

    @pytest.fixture(autouse=True)
    def _fixed_threshold(self, monkeypatch):
        monkeypatch.setattr(gateway, "threshold", lambda: 0.95)

    async def _lookup(self, collections):
        return await gateway.lookup_cache(
            collections,
            prompt="a question",
            embedding=[0.1, 0.2],
            project="repo",
            model="claude-opus-5",
        )

    async def test_no_candidates_is_a_miss(self, collections, fake_hits):
        fake_hits([])
        result = await self._lookup(collections)
        assert result["hit"] is False
        assert result["score"] is None

    async def test_above_threshold_hits_and_returns_evidence(self, collections, fake_hits):
        fake_hits(
            [
                {
                    "distance": 0.01,
                    "document": "the answer",
                    "metadata": {"prompt": "a question", "cacheable": True},
                }
            ]
        )
        result = await self._lookup(collections)
        assert result["hit"] is True
        assert result["answer"] == "the answer"
        # Always returned, so a client can reject a hit it dislikes.
        assert result["score"] == 0.99
        assert result["matched_prompt"] == "a question"

    async def test_below_threshold_misses_but_still_reports_score(self, collections, fake_hits):
        fake_hits(
            [{"distance": 0.30, "document": "x", "metadata": {"prompt": "other"}}]
        )
        result = await self._lookup(collections)
        assert result["hit"] is False
        assert result["score"] == 0.70
        assert result["matched_prompt"] == "other"
        assert result["reason"] == "below threshold"

    async def test_near_miss_is_flagged(self, collections, fake_hits):
        # 0.93 is within NEAR_MISS_MARGIN of the 0.95 cutoff.
        fake_hits([{"distance": 0.07, "document": "x", "metadata": {"prompt": "p"}}])
        result = await self._lookup(collections)
        assert result["hit"] is False
        assert result["near_miss"] is True

    async def test_clear_miss_is_not_a_near_miss(self, collections, fake_hits):
        fake_hits([{"distance": 0.5, "document": "x", "metadata": {"prompt": "p"}}])
        result = await self._lookup(collections)
        assert result["near_miss"] is False

    async def test_non_cacheable_entry_is_never_served(self, collections, fake_hits):
        # Identical prompt, but it was flagged volatile when stored.
        fake_hits(
            [{"distance": 0.0, "document": "stale answer",
              "metadata": {"prompt": "p", "cacheable": False}}]
        )
        result = await self._lookup(collections)
        assert result["hit"] is False
        assert result["reason"] == "entry flagged non-cacheable"
        assert result["score"] == 1.0

    async def test_expired_entry_is_not_served(self, collections, fake_hits):
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        fake_hits(
            [{"distance": 0.0, "document": "old",
              "metadata": {"prompt": "p", "cacheable": True, "stale_after": past}}]
        )
        result = await self._lookup(collections)
        assert result["hit"] is False
        assert result["reason"] == "entry expired"

    async def test_best_of_several_candidates_wins(self, collections, fake_hits):
        fake_hits(
            [
                {"distance": 0.40, "document": "worse", "metadata": {"prompt": "b"}},
                {"distance": 0.02, "document": "better", "metadata": {"prompt": "a"}},
            ]
        )
        result = await self._lookup(collections)
        assert result["hit"] is True
        assert result["answer"] == "better"

    async def test_non_cosine_collection_cannot_produce_a_hit(self, fake_hits):
        # An l2 collection has no comparable similarity, so it must not serve.
        collections = gateway.Collections("c", "k", "l2", "l2")
        fake_hits([{"distance": 0.0, "document": "answer", "metadata": {"prompt": "p"}}])
        result = await gateway.lookup_cache(
            collections,
            prompt="q",
            embedding=[0.1],
            project="repo",
            model="m",
        )
        assert result["hit"] is False


class TestScopeNormalisation:
    """BB-202: every spelling of a project name must resolve to one cache.

    The bug these guard against: scopes are matched with Chroma `$eq`, the client
    sends the git root's basename, and documents had been stored under a
    hand-written variant. `Brown-Bear` and `brownbear` were two mutually
    invisible caches, so the semantic cache never served a single hit.
    """

    @pytest.mark.parametrize(
        "spelling",
        ["Brown-Bear", "brownbear", "brown_bear", "Brown Bear", "  BROWN-BEAR  ", "brown.bear"],
    )
    def test_every_spelling_collapses_to_one_scope(self, spelling):
        assert gateway.normalise_project(spelling) == "brownbear"

    def test_the_reported_failure_case(self):
        """The exact pair that disabled the cache: what the hook sent vs what was stored."""
        assert gateway.normalise_project("Brown-Bear") == gateway.normalise_project("brownbear")

    def test_distinct_projects_stay_distinct(self):
        assert gateway.normalise_project("brownbear") != gateway.normalise_project("otherrepo")

    def test_empty_or_punctuation_only_falls_back_to_default(self):
        for value in ["", "   ", "---", "___", "..."]:
            assert gateway.normalise_project(value) == "default"

    def test_model_normalisation_keeps_meaningful_punctuation(self):
        # smollm2:135m must not become smollm2135m -- the tag is part of the id,
        # and mangling it would merge models that are genuinely different.
        assert gateway.normalise_model("SmolLM2:135m") == "smollm2:135m"
        assert gateway.normalise_model("  claude-opus-5 ") == "claude-opus-5"
        assert gateway.normalise_model("") == "unknown"

    def test_normalised_scope_makes_the_stored_id_stable(self):
        """The id hashes the project, so normalisation has to reach it too.

        Otherwise the same exchange stored from two spellings gets two ids, and
        the dedup that `exchange_id` exists to provide silently stops working.
        """
        left = gateway.exchange_id(
            gateway.normalise_project("Brown-Bear"), "claude-opus-5", "same prompt"
        )
        right = gateway.exchange_id(
            gateway.normalise_project("brownbear"), "claude-opus-5", "same prompt"
        )
        assert left == right

    def test_scope_filter_does_not_normalise_for_its_caller(self):
        """Deliberate: a caller that forgets to normalise must fail visibly.

        Silently normalising here would hide a store path that wrote an
        un-normalised key, which is exactly how the original bug survived.
        """
        assert gateway._scope_filter("Brown-Bear") == {"project": {"$eq": "Brown-Bear"}}
