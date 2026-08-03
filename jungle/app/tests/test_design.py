"""Public design documentation (sprint 1, BB-109).

This route is published unauthenticated, so the contract worth locking is not
"it renders" but "it renders and touches nothing". The tests below pin the three
properties that make it safe to expose: fixed allowlist, byte-identical raw
output, and no coupling to any backing service.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from brownbear.config import get_settings
from brownbear.main import create_app
from brownbear.routers import design

BOOK = "# Design Book\n\n## Overview\n\nSee [DESIGN-GUIDE.md](DESIGN-GUIDE.md).\n"
GUIDE = "# Design Guide\n\n## Overview\n\nSee [DESIGN-BOOK.md](DESIGN-BOOK.md).\n"


@pytest.fixture
def design_client(tmp_path, monkeypatch) -> TestClient:
    (tmp_path / "DESIGN-BOOK.md").write_text(BOOK, encoding="utf-8")
    (tmp_path / "DESIGN-GUIDE.md").write_text(GUIDE, encoding="utf-8")
    monkeypatch.setenv("BB_DESIGN_DIR", str(tmp_path))
    get_settings.cache_clear()
    design._page.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()
    design._page.cache_clear()


class TestPublicPage:
    def test_renders_without_credentials(self, design_client):
        response = design_client.get("/design")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Design Book" in response.text
        assert "Design Guide" in response.text

    def test_is_self_contained(self, design_client):
        """No external stylesheet, script, font or image — CSP-proof by construction."""
        body = design_client.get("/design").text

        for tag in ("<script", "<link", "<img", "<iframe"):
            assert tag not in body

    def test_cross_document_links_point_at_page_anchors(self, design_client):
        """A bare DESIGN-BOOK.md href would resolve to /DESIGN-BOOK.md and 403."""
        body = design_client.get("/design").text

        assert 'href="DESIGN-BOOK.md"' not in body
        assert 'href="DESIGN-GUIDE.md"' not in body
        assert 'href="#design-book"' in body
        assert 'id="design-guide"' in body

    def test_heading_anchors_are_namespaced_per_document(self, design_client):
        """Both documents have an "Overview"; unprefixed ids would collide."""
        body = design_client.get("/design").text

        assert 'id="design-book-overview"' in body
        assert 'id="design-guide-overview"' in body


class TestRawMarkdown:
    @pytest.mark.parametrize(
        ("slug", "expected"),
        [("design-book.md", BOOK), ("design-guide.md", GUIDE)],
    )
    def test_served_byte_for_byte(self, design_client, slug, expected):
        response = design_client.get(f"/design/{slug}")

        assert response.status_code == 200
        assert response.content == expected.encode("utf-8")
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"

    def test_only_the_allowlist_is_reachable(self, design_client, tmp_path):
        """A stray file in the mount is not published by accident."""
        (tmp_path / "SECRETS.md").write_text("do not publish", encoding="utf-8")

        assert design_client.get("/design/SECRETS.md").status_code == 404
        assert design_client.get("/design/secrets.md").status_code == 404

    def test_path_traversal_is_not_reachable(self, design_client):
        for slug in ("../config.py", "..%2Fconfig.py", "....//config.py"):
            assert design_client.get(f"/design/{slug}").status_code in (404, 400)


class TestInertness:
    def test_missing_mount_degrades_to_404_not_a_crash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BB_DESIGN_DIR", str(tmp_path / "absent"))
        get_settings.cache_clear()
        design._page.cache_clear()
        try:
            with TestClient(create_app()) as client:
                assert client.get("/design").status_code == 404
                assert client.get("/design/design-book.md").status_code == 404
                # The app itself is unaffected.
                assert client.get("/api/health/live").status_code == 200
        finally:
            get_settings.cache_clear()
            design._page.cache_clear()

    def test_module_imports_no_backing_service(self):
        """The page must serve with Postgres, Redis, ChromaDB and Ollama stopped.

        Asserted structurally rather than by stopping containers: the route
        cannot touch a service it never imports.
        """
        source = Path(design.__file__).read_text(encoding="utf-8")
        imports = [
            line
            for line in source.splitlines()
            if line.startswith(("import ", "from ")) and "brownbear" in line
        ]

        assert imports == ["from brownbear.config import get_settings"]
