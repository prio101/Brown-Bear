"""The memory graph (BB-301).

Chroma is faked throughout, like the rest of the suite: the assertions here are
about graph construction, not about whether a vector database happens to be up.

The properties worth pinning are the ones a wrong graph gets subtly wrong rather
than loudly — shared nodes actually being shared, similarity edges not being
duplicated in both directions, and a partial graph reporting that it is partial.
"""

import pytest

from brownbear import graph


def _exchange(doc_id, prompt, project="brownbear", model="claude-opus-5", answer="an answer"):
    return {
        "id": doc_id,
        "document": answer,
        "metadata": {
            "prompt": prompt,
            "project": project,
            "model": model,
            "created_at": "2026-08-01T00:00:00+00:00",
            "cacheable": True,
        },
    }


def _chunk(doc_id, text, source="DESIGN-BOOK.md", project="brownbear", index=0):
    return {
        "id": doc_id,
        "document": text,
        "metadata": {
            "source": source,
            "project": project,
            "chunk_index": index,
            "chunk_count": 3,
            "created_at": "2026-08-01T00:00:00+00:00",
        },
    }


@pytest.fixture
def fake_chroma(monkeypatch):
    """Install collections and documents; returns a setter for the documents."""
    state: dict[str, list] = {"conversations": [], "knowledge": []}

    async def _get_collection(name):
        if name not in state:
            return None
        return {
            "id": f"cid-{name}",
            "metadata": {"role": "cache" if name == "conversations" else "retrieval"},
            "configuration_json": {"hnsw": {"space": "cosine"}},
        }

    async def _get_documents(cid, *, limit=100, offset=0, where=None, ids=None, with_embeddings=False):
        name = cid.removeprefix("cid-")
        docs = list(state.get(name, []))
        if ids is not None:
            docs = [d for d in docs if d["id"] in ids]
        if where:
            key, clause = next(iter(where.items()))
            wanted = clause["$eq"]
            docs = [d for d in docs if (d.get("metadata") or {}).get(key) == wanted]
        if with_embeddings:
            docs = [{**d, "embedding": [0.1, 0.2, 0.3]} for d in docs]
        return docs[offset : offset + limit]

    monkeypatch.setattr(graph.chroma, "get_collection", _get_collection)
    monkeypatch.setattr(graph.chroma, "get_documents", _get_documents)

    def _set(conversations=(), knowledge=()):
        state["conversations"] = list(conversations)
        state["knowledge"] = list(knowledge)

    return _set


class TestOverview:
    async def test_builds_nodes_for_every_memory(self, fake_chroma):
        fake_chroma(
            conversations=[_exchange("x_1", "how does the cache scope work?")],
            knowledge=[_chunk("c_1", "Scopes are matched with $eq.")],
        )
        result = await graph.build_overview()

        kinds = {n["kind"] for n in result["nodes"]}
        assert {"collection", "project", "model", "exchange", "chunk", "source"} <= kinds

    async def test_shared_scope_is_one_node_not_many(self, fake_chroma):
        """The whole point of a graph: three exchanges in one project must meet at a
        single project node. One project node per exchange would draw a fan with no
        structure in it."""
        fake_chroma(
            conversations=[
                _exchange("x_1", "first"),
                _exchange("x_2", "second"),
                _exchange("x_3", "third"),
            ]
        )
        result = await graph.build_overview()

        projects = [n for n in result["nodes"] if n["kind"] == "project"]
        assert len(projects) == 1
        assert projects[0]["degree"] == 3

    async def test_distinct_projects_stay_distinct(self, fake_chroma):
        fake_chroma(
            conversations=[
                _exchange("x_1", "a", project="brownbear"),
                _exchange("x_2", "b", project="otherapp"),
            ]
        )
        result = await graph.build_overview()
        assert len({n["id"] for n in result["nodes"] if n["kind"] == "project"}) == 2

    async def test_a_project_and_a_model_of_the_same_name_do_not_merge(self, fake_chroma):
        """Node ids are typed for this reason. An untyped id would fuse these two
        into one node and invent a bridge between unrelated halves of the graph."""
        fake_chroma(conversations=[_exchange("x_1", "a", project="shared", model="shared")])
        result = await graph.build_overview()

        ids = {n["id"] for n in result["nodes"]}
        assert "project:shared" in ids
        assert "model:shared" in ids

    async def test_same_filename_in_two_projects_is_two_sources(self, fake_chroma):
        fake_chroma(
            knowledge=[
                _chunk("c_1", "x", source="README.md", project="brownbear"),
                _chunk("c_2", "y", source="README.md", project="otherapp"),
            ]
        )
        result = await graph.build_overview()
        assert len([n for n in result["nodes"] if n["kind"] == "source"]) == 2

    async def test_chunks_hang_off_their_source(self, fake_chroma):
        fake_chroma(knowledge=[_chunk(f"c_{i}", f"chunk {i}", index=i) for i in range(3)])
        result = await graph.build_overview()

        derived = [e for e in result["edges"] if e["kind"] == "derived_from"]
        assert len(derived) == 3

    async def test_overview_draws_no_similarity_edges(self, fake_chroma):
        """Structural only. One nearest-neighbour query per document would make
        opening the page cost a vector search per stored memory."""
        fake_chroma(conversations=[_exchange("x_1", "a"), _exchange("x_2", "b")])
        result = await graph.build_overview()

        assert all(e["kind"] != "similar_to" for e in result["edges"])
        assert all(e["weight"] is None for e in result["edges"])

    async def test_reports_truncation_rather_than_hiding_it(self, fake_chroma, monkeypatch):
        monkeypatch.setattr(graph, "MAX_NODES", 4)
        fake_chroma(conversations=[_exchange(f"x_{i}", f"prompt {i}") for i in range(20)])
        result = await graph.build_overview()

        assert result["truncated"] is True
        assert len(result["nodes"]) <= 4

    async def test_one_broken_collection_does_not_blank_the_graph(self, fake_chroma, monkeypatch):
        fake_chroma(conversations=[_exchange("x_1", "a")], knowledge=[_chunk("c_1", "b")])
        original = graph.chroma.get_documents

        async def _selective(cid, **kwargs):
            if cid.endswith("knowledge"):
                raise RuntimeError("chroma is unwell")
            return await original(cid, **kwargs)

        monkeypatch.setattr(graph.chroma, "get_documents", _selective)
        result = await graph.build_overview()

        assert any(n["kind"] == "exchange" for n in result["nodes"])
        assert not any(n["kind"] == "chunk" for n in result["nodes"])

    async def test_no_edge_points_at_a_missing_node(self, fake_chroma, monkeypatch):
        """A cap that drops nodes but keeps their edges draws lines into nothing."""
        monkeypatch.setattr(graph, "MAX_NODES", 5)
        fake_chroma(
            conversations=[_exchange(f"x_{i}", f"p{i}") for i in range(10)],
            knowledge=[_chunk(f"c_{i}", f"t{i}") for i in range(10)],
        )
        result = await graph.build_overview()

        ids = {n["id"] for n in result["nodes"]}
        for edge in result["edges"]:
            assert edge["source"] in ids and edge["target"] in ids


class TestExpand:
    async def test_similarity_edges_are_weighted_and_undirected(self, fake_chroma, monkeypatch):
        fake_chroma(conversations=[_exchange("x_1", "first"), _exchange("x_2", "second")])

        async def _query(cid, *, embedding, n_results=5, where=None):
            return [
                {"id": "x_1", "document": "a", "metadata": {"prompt": "first"}, "distance": 0.0},
                {"id": "x_2", "document": "b", "metadata": {"prompt": "second"}, "distance": 0.12},
            ]

        monkeypatch.setattr(graph.chroma, "query", _query)
        result = await graph.expand("exchange:x_1")

        similar = [e for e in result["edges"] if e["kind"] == "similar_to"]
        assert len(similar) == 1
        assert similar[0]["weight"] == pytest.approx(0.88)
        assert result["similar"][0]["id"] == "exchange:x_2"

    async def test_a_node_is_never_similar_to_itself(self, fake_chroma, monkeypatch):
        """Chroma always returns the query point as its own nearest neighbour."""
        fake_chroma(conversations=[_exchange("x_1", "only")])

        async def _query(cid, *, embedding, n_results=5, where=None):
            return [{"id": "x_1", "document": "a", "metadata": {"prompt": "only"}, "distance": 0.0}]

        monkeypatch.setattr(graph.chroma, "query", _query)
        result = await graph.expand("exchange:x_1")

        assert result["similar"] == []
        assert all(e["kind"] != "similar_to" for e in result["edges"])

    async def test_weak_similarity_is_dropped(self, fake_chroma, monkeypatch):
        fake_chroma(conversations=[_exchange("x_1", "a"), _exchange("x_2", "b")])

        async def _query(cid, *, embedding, n_results=5, where=None):
            # 0.4 similarity — related to nothing, and a line here would be noise.
            return [{"id": "x_2", "document": "b", "metadata": {"prompt": "b"}, "distance": 0.6}]

        monkeypatch.setattr(graph.chroma, "query", _query)
        result = await graph.expand("exchange:x_1")
        assert result["similar"] == []

    async def test_the_similarity_floor_is_caller_controlled(self, fake_chroma, monkeypatch):
        """The right floor is corpus- and model-dependent. A fixed constant here
        drew no edges at all on the real corpus, whose nearest genuine neighbours
        score around 0.66 — the graph looked unconnected when it was not.
        """
        fake_chroma(conversations=[_exchange("x_1", "a"), _exchange("x_2", "b")])

        async def _query(cid, *, embedding, n_results=5, where=None):
            # 0.66 similarity: a real neighbour on this corpus, not noise.
            return [{"id": "x_2", "document": "b", "metadata": {"prompt": "b"}, "distance": 0.34}]

        monkeypatch.setattr(graph.chroma, "query", _query)

        assert (await graph.expand("exchange:x_1", min_similarity=0.60))["similar"]
        assert not (await graph.expand("exchange:x_1", min_similarity=0.90))["similar"]

    async def test_structural_neighbours_survive_a_similarity_failure(
        self, fake_chroma, monkeypatch
    ):
        """A dead vector search must degrade to the structural graph, not 503."""
        fake_chroma(conversations=[_exchange("x_1", "a")])

        async def _boom(*args, **kwargs):
            raise RuntimeError("vector search unavailable")

        monkeypatch.setattr(graph.chroma, "query", _boom)
        result = await graph.expand("exchange:x_1")

        assert result["node"] is not None
        assert result["similar"] == []
        assert any(n["kind"] == "project" for n in result["nodes"])

    async def test_expanding_a_project_returns_its_members(self, fake_chroma):
        fake_chroma(
            conversations=[
                _exchange("x_1", "a", project="brownbear"),
                _exchange("x_2", "b", project="otherapp"),
            ]
        )
        result = await graph.expand("project:brownbear")

        exchanges = [n for n in result["nodes"] if n["kind"] == "exchange"]
        assert [n["id"] for n in exchanges] == ["exchange:x_1"]

    async def test_unknown_node_returns_no_node(self, fake_chroma):
        fake_chroma(conversations=[])
        result = await graph.expand("exchange:x_missing")
        assert result["node"] is None


class TestApi:
    def test_overview_is_served(self, client, fake_chroma):
        fake_chroma(conversations=[_exchange("x_1", "a")])
        response = client.get("/api/graph")

        assert response.status_code == 200
        body = response.json()
        assert body["nodes"] and "edges" in body
        assert body["limits"]["max_nodes"] == graph.MAX_NODES

    def test_node_requires_a_typed_id(self, client, fake_chroma):
        fake_chroma()
        assert client.get("/api/graph/node", params={"id": "nonsense"}).status_code == 422
        assert client.get("/api/graph/node", params={"id": "wrong:x"}).status_code == 422

    def test_missing_node_is_404_not_500(self, client, fake_chroma):
        fake_chroma(conversations=[])
        assert client.get("/api/graph/node", params={"id": "exchange:nope"}).status_code == 404

    def test_ids_containing_slashes_survive_the_round_trip(self, client, fake_chroma):
        """Why id is a query parameter: a source id carries a path."""
        fake_chroma(knowledge=[_chunk("c_1", "x", source="docs/DESIGN-BOOK.md")])
        response = client.get(
            "/api/graph/node", params={"id": "source:brownbear/docs/DESIGN-BOOK.md"}
        )

        assert response.status_code == 200
        assert any(n["kind"] == "chunk" for n in response.json()["nodes"])
