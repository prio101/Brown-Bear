"""Prompt Palace (spec 012).

Chroma is faked, like the rest of the suite. What these pin are the properties a
wrong implementation gets quietly wrong rather than loudly:

  - the listing must not fetch the answers, or listing forty prompts transfers
    forty model responses to render text that lives in the metadata;
  - an unscoreable similarity must survive as `None` rather than being dropped or
    coerced to 0 — a 0 says "unrelated", which is a claim nobody made;
  - `machine` must be absent rather than invented when no client sent one;
  - three different counts (`total`, `scanned`, `matched`) must not collapse into
    one, because Chroma returns documents in no order and "newest" is only ever
    newest within what was read.
"""

import pytest

from brownbear import prompts


def _exchange(doc_id, prompt, *, answer="an answer", created="2026-08-01T00:00:00+00:00",
              project="brownbear", model="claude-opus-5", machine=None, cacheable=True):
    meta = {
        "prompt": prompt,
        "project": project,
        "model": model,
        "cacheable": cacheable,
        "embedding_model": "nomic-embed-text",
    }
    if created is not None:
        meta["created_at"] = created
    if machine is not None:
        meta["machine"] = machine
    return {"id": doc_id, "document": answer, "metadata": meta}


def _chunk(doc_id, text, *, source="DESIGN-BOOK.md", index=0):
    return {
        "id": doc_id,
        "document": text,
        "metadata": {
            "source": source,
            "project": "brownbear",
            "chunk_index": index,
            "chunk_count": 3,
            "file_id": "f_abc",
        },
    }


@pytest.fixture
def fake_chroma(monkeypatch):
    """Collections, documents and nearest-neighbour hits, all in memory.

    `reads` records the keyword arguments of every get_documents call, which is how
    the "the listing does not fetch answers" assertion is made without reaching for
    a mock framework.
    """
    state = {
        "conversations": [],
        "knowledge": [],
        "space": "cosine",
        "hits": {},
        "reads": [],
        "fail": set(),
    }

    async def _get_collection(name):
        if name not in {"conversations", "knowledge"}:
            return None
        if name == "conversations" and state.get("no_conversations"):
            return None
        return {
            "id": f"cid-{name}",
            "metadata": {"role": "cache" if name == "conversations" else "retrieval"},
            "configuration_json": {"hnsw": {"space": state["space"]}},
        }

    async def _collection_count(cid):
        return len(state[cid.removeprefix("cid-")])

    async def _get_documents(cid, *, limit=100, offset=0, where=None, ids=None,
                             with_embeddings=False, with_documents=True):
        name = cid.removeprefix("cid-")
        state["reads"].append({"with_documents": with_documents, "limit": limit, "offset": offset})
        docs = list(state[name])
        if ids is not None:
            docs = [d for d in docs if d["id"] in ids]
        if not with_documents:
            docs = [{**d, "document": None} for d in docs]
        if with_embeddings:
            docs = [{**d, "embedding": state.get("embedding", [0.1, 0.2, 0.3])} for d in docs]
        return docs[offset : offset + limit]

    async def _query(cid, *, embedding, n_results=5, where=None):
        name = cid.removeprefix("cid-")
        if name in state["fail"]:
            raise RuntimeError("chroma is unwell")
        return state["hits"].get(name, [])[:n_results]

    monkeypatch.setattr(prompts.chroma, "get_collection", _get_collection)
    monkeypatch.setattr(prompts.chroma, "get_documents", _get_documents)
    monkeypatch.setattr(prompts.chroma, "collection_count", _collection_count)
    monkeypatch.setattr(prompts.chroma, "query", _query)
    # Pinned rather than read from settings: these assertions are about the cutoff
    # being applied, not about what it currently is.
    monkeypatch.setattr(prompts.gateway, "threshold", lambda: 0.95)
    return state


class TestListing:
    async def test_newest_first(self, fake_chroma):
        fake_chroma["conversations"] = [
            _exchange("x_old", "asked first", created="2026-08-01T00:00:00+00:00"),
            _exchange("x_new", "asked last", created="2026-08-20T00:00:00+00:00"),
            _exchange("x_mid", "asked between", created="2026-08-10T00:00:00+00:00"),
        ]
        result = await prompts.listing()

        assert [p["id"] for p in result["prompts"]] == ["x_new", "x_mid", "x_old"]

    async def test_an_undated_exchange_sorts_last_not_first(self, fake_chroma):
        """Stored before created_at existed. Treating a missing date as the epoch
        would put it at the bottom too — but by claiming it is the oldest thing in
        the corpus, which is not known."""
        fake_chroma["conversations"] = [
            _exchange("x_undated", "no date", created=None),
            _exchange("x_dated", "dated", created="2026-01-01T00:00:00+00:00"),
        ]
        result = await prompts.listing()

        assert [p["id"] for p in result["prompts"]] == ["x_dated", "x_undated"]

    async def test_does_not_fetch_the_answers(self, fake_chroma):
        """The listing renders prompts, which live in the metadata. Fetching the
        documents would ship every model answer to draw a list of questions."""
        fake_chroma["conversations"] = [_exchange("x_1", "a prompt", answer="x" * 5000)]

        result = await prompts.listing()

        assert all(read["with_documents"] is False for read in fake_chroma["reads"])
        # And because it did not fetch them, there is no preview to show.
        assert result["prompts"][0]["response_preview"] is None

    async def test_machine_is_absent_not_invented(self, fake_chroma):
        fake_chroma["conversations"] = [
            _exchange("x_1", "from a named box", machine="mac-studio"),
            _exchange("x_2", "from before the field existed"),
        ]
        result = await prompts.listing()
        by_id = {p["id"]: p for p in result["prompts"]}

        assert by_id["x_1"]["machine"] == "mac-studio"
        # Not "unknown", not "localhost", not the server's own hostname.
        assert by_id["x_2"]["machine"] is None
        assert result["machines"] == ["mac-studio"]

    async def test_filters_by_machine(self, fake_chroma):
        fake_chroma["conversations"] = [
            _exchange("x_1", "a", machine="mac-studio"),
            _exchange("x_2", "b", machine="thinkpad"),
            _exchange("x_3", "c"),
        ]
        result = await prompts.listing(machine="thinkpad")

        assert [p["id"] for p in result["prompts"]] == ["x_2"]
        assert result["matched"] == 1

    async def test_unattributed_is_a_selectable_filter(self, fake_chroma):
        """How you find what predates the field, or a client that is not sending it."""
        fake_chroma["conversations"] = [
            _exchange("x_1", "a", machine="mac-studio"),
            _exchange("x_2", "b"),
        ]
        result = await prompts.listing(machine="unattributed")

        assert [p["id"] for p in result["prompts"]] == ["x_2"]

    async def test_filters_by_project_and_model(self, fake_chroma):
        # Distinct timestamps: with equal ones the order falls to the id
        # tiebreaker, and a test that leans on a tiebreaker is asserting an
        # implementation detail rather than the filter.
        fake_chroma["conversations"] = [
            _exchange("x_1", "a", project="brownbear", model="claude-opus-5",
                      created="2026-08-03T00:00:00+00:00"),
            _exchange("x_2", "b", project="otherapp", model="claude-opus-5",
                      created="2026-08-02T00:00:00+00:00"),
            _exchange("x_3", "c", project="brownbear", model="llama3",
                      created="2026-08-01T00:00:00+00:00"),
        ]

        assert [p["id"] for p in (await prompts.listing(project="brownbear"))["prompts"]] == [
            "x_1", "x_3",
        ]
        assert [p["id"] for p in (await prompts.listing(model="llama3"))["prompts"]] == ["x_3"]

    async def test_counts_stay_separate(self, fake_chroma):
        """total, scanned and matched answer different questions. Collapsing them
        into one number is how a filtered page of a partial scan comes to read as
        the whole corpus."""
        fake_chroma["conversations"] = [
            _exchange(f"x_{i}", "a", machine="mac-studio" if i < 3 else None) for i in range(10)
        ]
        result = await prompts.listing(limit=2, machine="mac-studio")

        assert result["total"] == 10
        assert result["scanned"] == 10
        assert result["matched"] == 3
        assert len(result["prompts"]) == 2
        assert result["truncated"] is False

    async def test_reports_a_capped_scan_rather_than_hiding_it(self, fake_chroma, monkeypatch):
        # Chroma returns documents in no order, so a capped scan means the newest
        # exchange may not be on the page at all. That has to be visible.
        monkeypatch.setattr(prompts, "PAGE_SIZE", 2)
        monkeypatch.setattr(prompts, "MAX_SCAN", 4)
        fake_chroma["conversations"] = [_exchange(f"x_{i}", "a") for i in range(10)]

        result = await prompts.listing()

        assert result["truncated"] is True
        assert result["scanned"] == 4
        assert result["total"] == 10

    async def test_an_empty_stack_is_not_an_error(self, fake_chroma):
        fake_chroma["no_conversations"] = True
        result = await prompts.listing()

        assert result["ready"] is False
        assert result["prompts"] == []


class TestDetail:
    async def test_returns_the_whole_answer(self, fake_chroma):
        fake_chroma["conversations"] = [_exchange("x_1", "a prompt", answer="the full answer")]
        found = await prompts.detail("x_1")

        assert found["response"] == "the full answer"
        assert found["response_chars"] == len("the full answer")

    async def test_unknown_id_is_none(self, fake_chroma):
        fake_chroma["conversations"] = []
        assert await prompts.detail("x_missing") is None


class TestRelated:
    async def test_scores_neighbours_and_excludes_itself(self, fake_chroma):
        fake_chroma["conversations"] = [_exchange("x_1", "the prompt")]
        fake_chroma["hits"]["conversations"] = [
            {**_exchange("x_1", "the prompt"), "distance": 0.0},
            {**_exchange("x_2", "a near neighbour"), "distance": 0.09},
        ]
        result = await prompts.related("x_1")

        assert [p["id"] for p in result["prompts"]] == ["x_2"]
        assert result["prompts"][0]["score"] == pytest.approx(0.91)

    async def test_drops_neighbours_below_the_floor(self, fake_chroma):
        fake_chroma["conversations"] = [_exchange("x_1", "the prompt")]
        fake_chroma["hits"]["conversations"] = [
            {**_exchange("x_2", "close"), "distance": 0.2},
            {**_exchange("x_3", "distant"), "distance": 0.8},
        ]
        result = await prompts.related("x_1", min_similarity=0.60)

        assert [p["id"] for p in result["prompts"]] == ["x_2"]

    async def test_an_unscoreable_neighbour_is_kept_with_a_null_score(self, fake_chroma):
        """DESIGN-GUIDE Part 3 rule 2. Only cosine converts to the 0.95-style
        cutoff; in any other space the honest answer is "cannot be scored". Coercing
        it to 0 would assert the two memories are unrelated, and dropping the row
        would hide that the corpus cannot be scored at all."""
        fake_chroma["space"] = "l2"
        fake_chroma["conversations"] = [_exchange("x_1", "the prompt")]
        fake_chroma["hits"]["conversations"] = [
            {**_exchange("x_2", "a neighbour"), "distance": 4.2},
        ]
        result = await prompts.related("x_1")

        assert result["scorable"] is False
        assert len(result["prompts"]) == 1
        assert result["prompts"][0]["score"] is None
        assert result["prompts"][0]["would_hit"] is False

    async def test_would_hit_needs_the_cutoff_and_a_cacheable_entry(self, fake_chroma):
        """A high score alone is not a hit: `cacheable: false` is exactly why a hit
        gets refused despite one, and the page has to be able to show that."""
        fake_chroma["conversations"] = [_exchange("x_1", "the prompt")]
        fake_chroma["hits"]["conversations"] = [
            {**_exchange("x_2", "above the cutoff"), "distance": 0.02},
            {**_exchange("x_3", "above it but volatile", cacheable=False), "distance": 0.01},
            {**_exchange("x_4", "related but below"), "distance": 0.30},
        ]
        result = await prompts.related("x_1")
        by_id = {p["id"]: p for p in result["prompts"]}

        assert by_id["x_2"]["would_hit"] is True
        assert by_id["x_3"]["would_hit"] is False
        assert by_id["x_4"]["would_hit"] is False

    async def test_knowledge_chunks_come_back_separately(self, fake_chroma):
        """Two lists, not one ranked set: a neighbouring prompt is a prior answer,
        a chunk is supporting context, and merging them invites reading a retrieved
        passage as an answer."""
        fake_chroma["conversations"] = [_exchange("x_1", "the prompt")]
        fake_chroma["hits"]["conversations"] = [{**_exchange("x_2", "a"), "distance": 0.1}]
        fake_chroma["hits"]["knowledge"] = [{**_chunk("c_1", "a passage"), "distance": 0.3}]
        result = await prompts.related("x_1")

        assert [p["id"] for p in result["prompts"]] == ["x_2"]
        assert [c["id"] for c in result["chunks"]] == ["c_1"]
        assert result["chunks"][0]["source"] == "DESIGN-BOOK.md"
        assert result["chunks"][0]["score"] == pytest.approx(0.7)

    async def test_one_failing_collection_does_not_blank_the_other(self, fake_chroma):
        # Panels fail independently (DESIGN-GUIDE Part 3 rule 8).
        fake_chroma["conversations"] = [_exchange("x_1", "the prompt")]
        fake_chroma["hits"]["knowledge"] = [{**_chunk("c_1", "a passage"), "distance": 0.3}]
        fake_chroma["fail"] = {"conversations"}

        result = await prompts.related("x_1")

        assert result["prompts"] == []
        assert [c["id"] for c in result["chunks"]] == ["c_1"]

    async def test_says_so_when_there_is_no_vector_to_compare(self, fake_chroma):
        fake_chroma["conversations"] = [_exchange("x_1", "the prompt")]
        fake_chroma["embedding"] = None

        result = await prompts.related("x_1")

        assert result["prompts"] == []
        assert "no stored embedding" in result["unavailable"]

    async def test_unknown_id_is_none(self, fake_chroma):
        fake_chroma["conversations"] = []
        assert await prompts.related("x_missing") is None
