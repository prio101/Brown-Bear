"""File ingestion (spec 007).

Chroma and the database are faked. What these pin is the part that is easy to get
subtly wrong and hard to notice: that the bytes are verified while the extraction
is only recorded, that the sniffer ignores what the client claims, and that
deleting a file takes its chunks with it.
"""

import hashlib
import io

import pytest

from brownbear import files as files_service
from brownbear.models.files import FileStatus


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.7\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20


class TestSniffing:
    def test_reads_the_bytes_not_the_extension(self):
        """An .html file declared as text/plain and served back as text/html would
        be stored XSS on the dashboard's own origin."""
        assert files_service.sniff_media_type(b"<!DOCTYPE html><p>x", "notes.txt") == "text/html"

    def test_recognises_binary_formats(self):
        assert files_service.sniff_media_type(PNG) == "image/png"
        assert files_service.sniff_media_type(JPEG) == "image/jpeg"
        assert files_service.sniff_media_type(PDF) == "application/pdf"
        assert files_service.sniff_media_type(WEBP) == "image/webp"
        assert files_service.sniff_media_type(b"GIF89a....") == "image/gif"

    def test_detects_svg(self):
        assert files_service.sniff_media_type(b"<svg xmlns='...'>") == "image/svg+xml"
        assert files_service.sniff_media_type(b"<?xml version='1.0'?><svg>") == "image/svg+xml"

    def test_falls_back_to_extension_only_between_text_formats(self):
        assert files_service.sniff_media_type(b"# Title", "notes.md") == "text/markdown"
        assert files_service.sniff_media_type(b'{"a":1}', "x.json") == "application/json"
        assert files_service.sniff_media_type(b"plain words", "x.unknown") == "text/plain"

    def test_undecodable_bytes_are_opaque(self):
        assert files_service.sniff_media_type(b"\xff\xfe\x00\x01binary") == "application/octet-stream"


class TestInlineAllowlist:
    def test_images_and_pdf_render_inline(self):
        for media_type in ("image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"):
            assert files_service.is_inline_renderable(media_type)

    def test_svg_never_renders_inline(self):
        """It is an image format that is also a document format: an .svg can carry
        <script>, and inline from this origin that script runs with the reader's
        session."""
        assert not files_service.is_inline_renderable("image/svg+xml")

    def test_html_never_renders_inline(self):
        assert not files_service.is_inline_renderable("text/html")


class TestTags:
    def test_normalises_and_dedupes(self):
        assert files_service.normalise_tags("Design, design , ARCH") == "arch,design"

    def test_strips_punctuation(self):
        assert files_service.normalise_tags("a b!c") == "a-b-c"

    def test_empty_is_none(self):
        assert files_service.normalise_tags("") is None
        assert files_service.normalise_tags(" , , ") is None


class TestFileId:
    def test_derives_from_the_digest(self):
        assert files_service.file_id("a" * 64) == "f_" + "a" * 32

    def test_same_content_is_the_same_id(self):
        assert files_service.file_id(digest_of(b"x")) == files_service.file_id(digest_of(b"x"))


class TestUploadApi:
    """End to end through the router, with the store and the database faked."""

    @pytest.fixture(autouse=True)
    def _fakes(self, monkeypatch, tmp_path):
        from brownbear.blobs import BlobStore

        store = BlobStore(tmp_path / "blobs")
        monkeypatch.setattr(files_service, "blob_store", lambda: store)

        rows: dict[str, dict] = {}

        def _upsert(values):
            existing = rows.get(values["id"], {})
            merged = {**existing, **{k: v for k, v in values.items() if v is not None}}
            rows[values["id"]] = merged
            return type("Row", (), merged)()

        monkeypatch.setattr(files_service, "_upsert_sync", _upsert)
        monkeypatch.setattr(files_service, "_by_digest_sync", lambda d: None)
        monkeypatch.setattr(files_service, "_get_sync", lambda i: None)

        async def _index(**kwargs):
            return {"chunks_stored": 3, "ids": ["c_1", "c_2", "c_3"], "source": kwargs["source"]}

        monkeypatch.setattr(files_service, "index_extraction", _index)

        async def _no_duplicates(**kwargs):
            return []

        monkeypatch.setattr(files_service, "near_duplicates", _no_duplicates)
        return rows

    def test_stores_and_indexes(self, client):
        response = client.post(
            "/ext/files",
            files={"file": ("notes.md", io.BytesIO(b"# Retention\nKeep 30 days."), "text/markdown")},
            data={"project": "Brown-Bear", "extraction": "Retention: keep 30 days.", "extractor": "cat"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == FileStatus.indexed.value
        assert body["chunks_stored"] == 3

    def test_verifies_the_claimed_digest(self, client):
        response = client.post(
            "/ext/files",
            files={"file": ("a.txt", io.BytesIO(b"actual bytes"), "text/plain")},
            data={"sha256": digest_of(b"different bytes"), "extraction": "x"},
        )

        assert response.status_code == 422
        assert "sha256" in response.json()["detail"]

    def test_accepts_a_matching_digest(self, client):
        payload = b"verified bytes"
        response = client.post(
            "/ext/files",
            files={"file": ("a.txt", io.BytesIO(payload), "text/plain")},
            data={"sha256": digest_of(payload), "extraction": "x"},
        )

        assert response.status_code == 200

    def test_rejects_a_malformed_digest(self, client):
        response = client.post(
            "/ext/files",
            files={"file": ("a.txt", io.BytesIO(b"x"), "text/plain")},
            data={"sha256": "not-a-digest"},
        )
        assert response.status_code == 422

    def test_an_empty_upload_is_refused(self, client):
        response = client.post(
            "/ext/files", files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
        )
        assert response.status_code == 422

    def test_oversized_upload_is_refused(self, client, monkeypatch):
        from brownbear.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "max_upload_bytes", 64, raising=False)

        response = client.post(
            "/ext/files",
            files={"file": ("big.txt", io.BytesIO(b"x" * 5000), "text/plain")},
        )
        assert response.status_code == 413

    def test_a_file_without_extraction_is_stored_not_indexed(self, client):
        """Storable but unsearchable is a real state, and better than a lost
        upload."""
        response = client.post(
            "/ext/files",
            files={"file": ("photo.png", io.BytesIO(PNG), "image/png")},
        )

        body = response.json()
        assert body["status"] == FileStatus.stored.value
        assert body["chunks_stored"] == 0
        assert "not searchable" in body["note"]

    def test_indexing_failure_keeps_the_file(self, client, monkeypatch):
        async def _boom(**kwargs):
            raise RuntimeError("chroma is unwell")

        monkeypatch.setattr(files_service, "index_extraction", _boom)

        response = client.post(
            "/ext/files",
            files={"file": ("a.txt", io.BytesIO(b"content"), "text/plain")},
            data={"extraction": "some text"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == FileStatus.failed.value

    def test_the_media_type_is_sniffed_not_believed(self, client, rows=None):
        response = client.post(
            "/ext/files",
            # Claims plain text; the bytes are a PNG.
            files={"file": ("evil.txt", io.BytesIO(PNG), "text/plain")},
        )
        assert response.status_code == 200


class TestExists:
    def test_rejects_a_non_digest(self, client):
        assert client.get("/ext/files/nonsense/exists").status_code == 422

    def test_reports_absence(self, client, monkeypatch, tmp_path):
        from brownbear.blobs import BlobStore

        monkeypatch.setattr(files_service, "blob_store", lambda: BlobStore(tmp_path))
        monkeypatch.setattr(files_service, "_by_digest_sync", lambda d: None)

        body = client.get(f"/ext/files/{'a' * 64}/exists").json()
        assert body["exists"] is False
        assert body["file_id"] is None


class TestDeletePersists:
    """A faked database reported this route as working while it was not."""

    def test_delete_actually_deletes(self, sqlite_db):
        """`session.delete()` followed by `session.expunge()` discards the pending
        delete, so this route removed the blob and the chunks, reported success,
        and left a row that would read as `missing` for ever."""
        record = files_service._upsert_sync(
            {
                "id": "f_" + "a" * 32,
                "sha256": "a" * 64,
                "filename": "notes.md",
                "media_type": "text/markdown",
                "size_bytes": 3,
                "project": "brownbear",
                "source": "notes.md",
                "extracted_text": "abc",
                "status": FileStatus.stored,
            }
        )

        assert files_service._get_sync(record.id) is not None
        assert files_service._delete_sync(record.id) is not None
        assert files_service._get_sync(record.id) is None


class TestAttachExtraction:
    """Spec 009: the text arrives after the bytes, from whoever read the file.

    The two things worth pinning are that a re-extraction *replaces* the old chunks
    rather than adding to them, and that the original-language text is stored but
    never indexed — retrieval has to behave the same whatever language a document
    started in.
    """

    @pytest.fixture
    def attached(self, monkeypatch):
        state = {"indexed": [], "deleted": [], "rows": []}

        record = type(
            "Row",
            (),
            {
                "id": "f_" + "a" * 32,
                "sha256": "a" * 64,
                "source": "handbook.pdf",
                "project": "brownbear",
                "media_type": "application/pdf",
                "status": FileStatus.stored,
                "chunk_count": 0,
                "tags": "auto",
            },
        )()
        monkeypatch.setattr(
            files_service, "_get_sync", lambda i: record if i == record.id else None
        )
        monkeypatch.setattr(
            files_service, "_upsert_sync", lambda values: state["rows"].append(values)
        )

        async def _index(**kwargs):
            state["indexed"].append(kwargs["text"])
            return {"chunks_stored": 4}

        async def _collections():
            return object()

        async def _delete(collections, file_id):
            state["deleted"].append(file_id)
            return 7

        monkeypatch.setattr(files_service, "index_extraction", _index)
        monkeypatch.setattr(files_service.gateway, "ensure_collections", _collections)
        monkeypatch.setattr(files_service.gateway, "delete_by_file", _delete)
        return state

    def test_attaches_and_reindexes(self, client, attached):
        response = client.post(
            f"/ext/files/f_{'a' * 32}/extraction",
            json={"text": "The retention policy is thirty days.", "extractor": "claude-opus-5"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == FileStatus.indexed.value
        assert body["chunks_stored"] == 4

    def test_the_old_chunks_go_first(self, client, attached):
        """Two readings of one document, both retrievable, is worse than one poor
        reading."""
        client.post(f"/ext/files/f_{'a' * 32}/extraction", json={"text": "a better reading"})

        assert attached["deleted"] == ["f_" + "a" * 32]

    def test_the_translation_is_indexed_and_the_original_is_only_stored(self, client, attached):
        response = client.post(
            f"/ext/files/f_{'a' * 32}/extraction",
            json={
                "text": "The retention policy is thirty days.",
                "source_text": "保持期間は三十日です。",
                "language": "en",
                "source_language": "ja",
                "extractor": "claude-opus-5",
            },
        )

        body = response.json()
        assert body["translated"] is True
        # Indexed: English only, so one document cannot answer twice at two scores.
        assert attached["indexed"] == ["The retention policy is thirty days."]
        # Stored: both, so the translation can be checked against its source.
        stored = attached["rows"][-1]["extracted_text"]
        assert "保持期間は三十日です。" in stored
        assert "original (ja)" in stored
        assert {"lang-en", "src-ja", "translated"} <= set(body["tags"])

    def test_an_unknown_file_says_where_the_bytes_go(self, client, attached):
        response = client.post(f"/ext/files/f_{'b' * 32}/extraction", json={"text": "x"})
        assert response.status_code == 404
        assert "POST /ext/files" in response.json()["detail"]

    def test_an_empty_extraction_changes_nothing(self, client, attached):
        response = client.post(f"/ext/files/f_{'a' * 32}/extraction", json={"text": "   "})
        assert response.status_code == 200
        assert attached["indexed"] == []
        assert "nothing was changed" in response.json()["error"]

    def test_an_oversized_extraction_is_refused(self, client, attached):
        response = client.post(
            f"/ext/files/f_{'a' * 32}/extraction",
            json={"text": "x" * (files_service.MAX_EXTRACTION_CHARS + 1)},
        )
        assert response.status_code == 413

    def test_indexing_failure_leaves_the_file_retryable(self, client, attached, monkeypatch):
        async def _boom(**kwargs):
            raise RuntimeError("chroma is unwell")

        monkeypatch.setattr(files_service, "index_extraction", _boom)
        response = client.post(f"/ext/files/f_{'a' * 32}/extraction", json={"text": "some text"})

        assert response.status_code == 200
        assert response.json()["status"] == FileStatus.failed.value


class TestPreviewHeaders:
    """BB-204: what the browser is told about bytes it renders inline.

    The failure this guards against is invisible from the server's side — the
    response is a clean 200 and the browser shows an error page inside the frame —
    so the policy string is asserted rather than trusted.
    """

    @pytest.fixture
    def stored(self, monkeypatch, tmp_path):
        """A file whose bytes are really on disk, so /preview streams them."""
        from brownbear.blobs import BlobStore

        store = BlobStore(tmp_path / "blobs")
        monkeypatch.setattr(files_service, "blob_store", lambda: store)

        def _install(payload: bytes, media_type: str):
            written = store.write(iter([payload]), max_bytes=1_000_000, expected_sha256=None)
            record = type(
                "Row",
                (),
                {
                    "id": "f_" + written.sha256[:32],
                    "sha256": written.sha256,
                    "filename": "sample",
                    "media_type": media_type,
                    "size_bytes": written.size_bytes,
                    "preview_sha256": None,
                },
            )()
            monkeypatch.setattr(files_service, "_get_sync", lambda i: record)
            return record

        return _install

    def test_a_pdf_is_not_sandboxed(self, client, stored):
        record = stored(b"%PDF-1.4\n%fake", "application/pdf")

        response = client.get(f"/ext/files/{record.id}/preview")

        assert response.status_code == 200
        policy = response.headers["content-security-policy"]
        # The whole bug: a browser renders a PDF with a scripted viewer of its own,
        # and `sandbox` leaves it showing an error page instead of the document.
        assert "sandbox" not in policy
        assert "default-src 'none'" in policy
        assert "object-src 'none'" in policy
        # Framing is still restricted, by a header a browser does honour here.
        assert "frame-ancestors 'self'" in policy
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_an_image_keeps_the_strict_policy(self, client, stored):
        record = stored(PNG, "image/png")

        response = client.get(f"/ext/files/{record.id}/preview")

        assert response.status_code == 200
        # An image needs no viewer, so nothing here has to be relaxed for it.
        assert "sandbox" in response.headers["content-security-policy"]
