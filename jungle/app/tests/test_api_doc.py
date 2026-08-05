"""API documentation at /api-doc/v1 (spec 006).

The cross-file drift check — declaration versus `edge/nginx.conf.template` — lives
in `scripts/check_edge_contract.py` and runs on the host, because the test image is
built from `jungle/app` and Docker cannot COPY the edge config from outside that
build context. A test that skipped when the file was missing would look like
coverage without being any, so it is a script instead.

What this suite *can* enforce: that the contract covers every route the app
actually serves, that the page is inert and self-contained, and that it leaks
nothing.
"""

import pytest

from brownbear.api_contract import CONTRACT, GROUPS, Reach, by_group, reach_of
from brownbear.routers import api_doc

# FastAPI reports one `/ollama/{path}` catch-all accepting every method. The edge
# publishes four named routes, so the contract expands it deliberately — rendering
# the catch-all verbatim would be the most misleading line on the page. Any other
# undeclared path is a genuine gap.
EXPANDED_IN_CONTRACT = {"/ollama/{path}"}


@pytest.fixture
def schema(client):
    return client.app.openapi()


class TestContractCoversTheApp:
    def test_every_served_route_is_declared(self, schema):
        """A new endpoint cannot land undocumented."""
        missing = []
        for path, operations in schema["paths"].items():
            if path in EXPANDED_IN_CONTRACT:
                continue
            for method in operations:
                if method.upper() in {"HEAD", "OPTIONS"}:
                    continue
                if reach_of(method, path) is None:
                    missing.append(f"{method.upper()} {path}")

        assert missing == [], f"undeclared routes: {missing}"

    def test_the_ollama_catchall_is_expanded_not_copied(self, schema):
        assert "/ollama/{path}" in schema["paths"]
        for path in ("/ollama/api/chat", "/ollama/api/generate", "/ollama/api/embed", "/ollama/api/tags"):
            assert reach_of("POST", path) or reach_of("GET", path), path
        # And the destructive one is documented as denied rather than left out.
        assert reach_of("POST", "/ollama/api/pull") is Reach.DENIED

    def test_write_paths_are_declared_denied(self):
        """Named, not omitted: silence would read as an oversight and invite a try."""
        assert reach_of("PUT", "/api/settings") is Reach.DENIED
        assert reach_of("POST", "/api/tokens/aggregate") is Reach.DENIED
        assert reach_of("GET", "/metrics") is Reach.DENIED

    def test_only_two_routes_are_public(self):
        public = {(e.method, e.path) for e in CONTRACT if e.reach is Reach.PUBLIC}
        assert public == {
            ("GET", "/api/health/live"),
            ("GET", "/design"),
            ("GET", "/design/{slug}"),
        }

    def test_the_doc_itself_is_authenticated(self):
        # An endpoint inventory describes the attack surface; design tokens do not.
        assert reach_of("GET", "/api-doc/v1") is Reach.AUTHENTICATED
        assert reach_of("GET", "/api-doc/v1/openapi.json") is Reach.AUTHENTICATED

    def test_every_endpoint_has_a_group_and_a_summary(self):
        for endpoint in CONTRACT:
            assert endpoint.group in GROUPS, endpoint.path
            assert endpoint.summary.strip(), endpoint.path

    def test_groups_render_in_declared_order(self):
        rendered = list(by_group())
        assert rendered == [g for g in GROUPS if g in rendered]


class TestPage:
    def test_renders_html(self, client):
        response = client.get("/api-doc/v1")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_is_self_contained(self, client):
        """No CDN. FastAPI's own /docs pulls Swagger UI from jsdelivr, which is a
        blank page on a machine with no internet — the reason this page exists."""
        body = client.get("/api-doc/v1").text

        for tag in ("<script", "<link", "<img", "<iframe"):
            assert tag not in body
        assert "cdn.jsdelivr.net" not in body
        assert "fastapi.tiangolo.com" not in body

    def test_lists_every_endpoint(self, client):
        body = client.get("/api-doc/v1").text

        for endpoint in CONTRACT:
            assert endpoint.path in body, endpoint.path

    def test_denied_routes_are_shown_and_labelled(self, client):
        body = client.get("/api-doc/v1").text

        assert "Denied through the tunnel" in body
        assert "/api/tokens/aggregate" in body
        assert "/metrics" in body

    def test_reach_is_never_colour_alone(self, client):
        """Colour plus glyph plus label, per DESIGN-BOOK.md §2.4."""
        body = client.get("/api-doc/v1").text

        for label in ("Public", "Token required", "Denied through the tunnel"):
            assert label in body

    def test_names_the_auth_header_but_no_value(self, client):
        body = client.get("/api-doc/v1").text

        assert "Authorization: Bearer" in body
        assert "$BB_EDGE_TOKEN" in body  # the variable, never a value
        assert "561b" not in body

    def test_is_cached_not_re_rendered(self, client):
        api_doc._page.cache_clear()
        first = client.get("/api-doc/v1").text
        second = client.get("/api-doc/v1").text

        assert first == second
        assert api_doc._page.cache_info().hits >= 1


class TestSchema:
    def test_returns_the_openapi_document(self, client):
        body = client.get("/api-doc/v1/openapi.json").json()

        assert body["info"]["title"]
        assert body["paths"]

    def test_annotates_reachability_for_machines(self, client):
        body = client.get("/api-doc/v1/openapi.json").json()

        assert body["x-brownbear-contract-version"] == "v1"
        assert len(body["x-brownbear-contract"]) == len(CONTRACT)
        # The same contract the page shows, so a machine consumer need not infer it.
        assert body["paths"]["/ext/context"]["post"]["x-brownbear-reach"] == "authenticated"
        assert body["paths"]["/api/settings"]["put"]["x-brownbear-reach"] == "denied"
        assert body["paths"]["/api/health/live"]["get"]["x-brownbear-reach"] == "public"

    def test_leaves_unannotated_what_it_cannot_place(self, client):
        """The catch-all gets no reach rather than a guessed one — an absent
        annotation is the signal the contract has not caught up."""
        body = client.get("/api-doc/v1/openapi.json").json()

        catchall = body["paths"]["/ollama/{path}"]
        assert all("x-brownbear-reach" not in op for op in catchall.values())


class TestInertness:
    def test_module_touches_no_backing_service(self):
        """The page must serve while the stack is degraded, so it cannot import a
        service it would then be tempted to call."""
        source = open(api_doc.__file__, encoding="utf-8").read()
        imports = [
            line
            for line in source.splitlines()
            if line.startswith(("import ", "from ")) and "brownbear" in line
        ]

        assert imports == ["from brownbear.api_contract import CONTRACT, Reach, by_group"]

    def test_contract_module_is_pure_data(self):
        source = open("brownbear/api_contract.py", encoding="utf-8").read()
        assert "brownbear.db" not in source
        assert "connectors" not in source
