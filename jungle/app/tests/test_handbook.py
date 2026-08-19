"""The memory handbook at /api-doc/v1/handbook.

The handbook exists so a client on another machine can tell a miss from a fault
and a grounded answer from a cached one. The risk it carries is drift: it is prose
about behaviour defined elsewhere, and prose does not fail a build when the
behaviour moves under it.

So the assertions here are mostly structural rather than textual — that the layer
count and order match the code path, that exactly one layer is allowed to return an
answer, and that the three renderings come from one source. Wording is left free.
"""

import pytest

from brownbear import handbook
from brownbear.api_contract import Reach, reach_of
from brownbear.routers import handbook as handbook_router


@pytest.fixture(autouse=True)
def _clear_render_cache():
    """The page is memoised for the process; tests must not see each other's."""
    handbook_router._rendered.cache_clear()
    handbook_router._page.cache_clear()


class TestStructure:
    def test_four_layers_numbered_one_to_four(self):
        assert sorted(layer.ordinal for layer in handbook.LAYERS) == [1, 2, 3, 4]

    def test_catalogue_order_is_the_declared_one(self):
        """Quick cache, hard memory, key based, RAG — the numbering the stack is
        specified in, which deliberately differs from the runtime path below."""
        assert [layer.key for layer in handbook.ordered()] == [
            "quick_cache",
            "hard_memory",
            "key_based",
            "rag",
        ]

    def test_catalogue_order_is_not_the_lookup_order(self):
        """Both are published because they differ: the Key Based Layer is numbered
        third and runs last, since it acts on write rather than on read. A reader
        who assumes one order is the other will misjudge what produced a result."""
        assert [l.key for l in handbook.ordered()] != [
            s.layer for s in handbook.LOOKUP_ORDER
        ]

    def test_only_hard_memory_may_return_an_answer(self):
        """The central claim of the document, and of spec 005.

        A paragraph from the knowledge corpus being served as though it were a
        prior answer is the failure the two-collection split exists to prevent, so
        every other layer must say so in its `never`.
        """
        for layer in handbook.LAYERS:
            if layer.key == "hard_memory":
                assert "prior answer" in layer.returns
            else:
                assert layer.never, layer.key

    def test_lookup_order_references_real_layers(self):
        keys = {layer.key for layer in handbook.LAYERS}
        for step in handbook.LOOKUP_ORDER:
            assert step.layer in keys, step.layer

    def test_lookup_order_matches_the_request_path(self):
        """Quick cache, then hard memory, then RAG, then the write-side ids.

        This is the order `POST /ext/context` actually runs in; a reader who gets it
        wrong will assume retrieval happens on a hit, which it does not.
        """
        assert [step.layer for step in handbook.LOOKUP_ORDER] == [
            "quick_cache",
            "hard_memory",
            "rag",
            "key_based",
        ]

    def test_every_layer_states_its_failure_mode(self):
        """Each layer degrades rather than fails; a layer that does not say how is
        the one a caller will misread as an outage."""
        for layer in handbook.LAYERS:
            assert layer.on_failure.strip(), layer.key
            assert layer.scope.strip(), layer.key


class TestDeclaredValuesTrackTheCode:
    """The numbers are duplicated from config; pin the ones that carry meaning."""

    def test_threshold_and_ttl_match_settings(self):
        from brownbear.config import Settings

        settings = Settings()
        hard = next(l for l in handbook.LAYERS if l.key == "hard_memory")
        rag = next(l for l in handbook.LAYERS if l.key == "rag")
        quick = next(l for l in handbook.LAYERS if l.key == "quick_cache")

        assert hard.declared_defaults["cache_similarity_threshold"] == settings.cache_similarity_threshold
        assert hard.declared_defaults["cache_ttl_days"] == settings.cache_ttl_days
        assert rag.declared_defaults["context_top_k"] == settings.context_top_k
        assert rag.declared_defaults["chunk_chars"] == settings.chunk_chars
        assert quick.declared_defaults["embedding_cache_ttl_seconds"] == settings.embedding_cache_ttl_seconds

    def test_near_miss_margin_matches_the_gateway(self):
        from brownbear import gateway

        hard = next(l for l in handbook.LAYERS if l.key == "hard_memory")
        assert hard.declared_defaults["near_miss_margin"] == gateway.NEAR_MISS_MARGIN

    def test_values_are_labelled_as_declared_not_live(self):
        """Config is overridable at runtime, so the document must point at
        /ext/health rather than present its own numbers as fact."""
        payload = handbook.to_json()
        assert payload["live_values_endpoint"] == "/ext/health"
        assert "declared defaults" in payload["values_are"]


class TestRenderings:
    def test_all_three_are_served(self, client):
        for path, content_type in (
            ("/api-doc/v1/handbook", "text/html"),
            ("/api-doc/v1/handbook.md", "text/markdown"),
            ("/api-doc/v1/handbook.json", "application/json"),
        ):
            response = client.get(path)
            assert response.status_code == 200, path
            assert content_type in response.headers["content-type"], path

    def test_markdown_names_every_layer(self, client):
        body = client.get("/api-doc/v1/handbook.md").text
        for layer in handbook.LAYERS:
            assert layer.name in body, layer.name

    def test_json_carries_the_whole_structure(self, client):
        payload = client.get("/api-doc/v1/handbook.json").json()

        assert payload["handbook_version"] == handbook.HANDBOOK_VERSION
        assert len(payload["layers"]) == len(handbook.LAYERS)
        assert len(payload["lookup_order"]) == len(handbook.LOOKUP_ORDER)
        assert len(payload["controls"]) == len(handbook.KNOBS)
        assert payload["guarantees"]
        # The fields a consumer actually branches on.
        first = payload["layers"][0]
        for key in ("ordinal", "key", "name", "store", "returns", "never", "on_failure"):
            assert key in first, key

    def test_html_is_self_contained(self, client):
        """No CDN, for the reason /api-doc/v1 has none: this stack is built to run
        on a machine with no internet, and a docs page that needs one is blank
        exactly when it is most needed."""
        body = client.get("/api-doc/v1/handbook").text

        for tag in ("<script", "<link", "<img", "<iframe"):
            assert tag not in body
        assert "cdn.jsdelivr.net" not in body

    def test_html_points_a_model_at_the_markdown(self, client):
        body = client.get("/api-doc/v1/handbook").text
        assert "/api-doc/v1/handbook.md" in body

    def test_renderings_share_one_source(self, client):
        """Markdown and JSON must not be authored separately — that is how a
        handbook starts lying about the system it documents."""
        markdown_body = client.get("/api-doc/v1/handbook.md").text
        payload = client.get("/api-doc/v1/handbook.json").json()

        for layer in payload["layers"]:
            assert layer["name"] in markdown_body

    def test_states_what_is_stored_that_is_not_memory(self, client):
        """Spec 008 added a store that belongs to none of the four layers. A reader
        deciding how much to trust an /ext/context response has to be able to learn
        that configuration exists and can never come back from it — otherwise the
        handbook is complete about the memory and silent about the stack."""
        body = client.get("/api-doc/v1/handbook.md").text
        assert "/ext/agents/sync" in body
        assert "never come back from /ext/context" in body

    def test_the_identity_rule_covers_every_prefix_in_use(self, client):
        """A reader meeting an `f_…` or `a_…` id must find it here rather than by
        grepping the source."""
        defaults = next(
            layer for layer in handbook.LAYERS if layer.key == "key_based"
        ).declared_defaults
        assert set(defaults.values()) >= {"x_", "c_", "f_", "a_"}

    def test_names_no_secret(self, client):
        for path in ("/api-doc/v1/handbook", "/api-doc/v1/handbook.md"):
            body = client.get(path).text
            assert "561b" not in body
            assert "your_strong_password" not in body


class TestContract:
    def test_declared_authenticated(self):
        """The handbook describes scoping rules and thresholds — that is attack
        surface in a way design tokens are not."""
        for path in (
            "/api-doc/v1/handbook",
            "/api-doc/v1/handbook.md",
            "/api-doc/v1/handbook.json",
        ):
            assert reach_of("GET", path) is Reach.AUTHENTICATED, path

    def test_linked_from_the_api_doc_page(self, client):
        """An unlinked page is an unread page."""
        body = client.get("/api-doc/v1").text
        assert "/api-doc/v1/handbook" in body


class TestInertness:
    def test_touches_no_backing_service(self):
        """Like /design and /api-doc/v1, the handbook must render while the stack is
        degraded — so it may import pure data and a Markdown renderer, nothing more."""
        source = open(handbook_router.__file__, encoding="utf-8").read()
        imports = [
            line
            for line in source.splitlines()
            if line.startswith(("import ", "from ")) and "brownbear" in line
        ]

        assert imports == [
            "from brownbear.handbook import HANDBOOK_VERSION, to_json, to_markdown"
        ]

    def test_content_module_is_pure_data(self):
        source = open("brownbear/handbook.py", encoding="utf-8").read()
        assert "brownbear.db" not in source
        assert "connectors" not in source
