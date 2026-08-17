"""Content-addressed blob store (spec 007 §7.1).

Real files in a tmp_path, no mocks: this module's whole job is filesystem
behaviour, and a mocked filesystem would test the mock.
"""

import hashlib

import pytest

from brownbear.blobs import BlobStore, BlobTooLarge, DigestMismatch, is_sha256


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def store(tmp_path):
    return BlobStore(tmp_path / "blobs")


class TestPathSafety:
    def test_rejects_anything_that_is_not_a_digest(self, store):
        """A digest arrives from a URL. Unvalidated, `../` escapes the store."""
        for bad in ("../../etc/passwd", "abc", "", "g" * 64, "a/b", "A" * 63):
            with pytest.raises(ValueError):
                store.path_for(bad)

    def test_accepts_either_case(self, store):
        upper = "A" * 64
        assert store.path_for(upper).name == "a" * 64

    def test_exists_is_false_for_a_bad_digest_rather_than_raising(self, store):
        assert store.exists("../../etc/passwd") is False

    def test_buckets_the_tree(self, store):
        path = store.path_for("ab" + "c" * 62)
        assert path.parent.name == "c" * 2 or path.parent.name == "c" * 2
        assert path.parent.parent.name == "ab"


class TestWrite:
    def test_stores_and_returns_the_digest(self, store):
        result = store.write([b"hello ", b"world"], max_bytes=1000)

        assert result.sha256 == digest_of(b"hello world")
        assert result.size_bytes == 11
        assert result.created is True
        assert store.read(result.sha256) == b"hello world"

    def test_identical_content_is_stored_once(self, store):
        first = store.write([b"same"], max_bytes=1000)
        second = store.write([b"same"], max_bytes=1000)

        assert first.sha256 == second.sha256
        assert first.created is True
        assert second.created is False

    def test_size_cap_is_enforced_mid_stream(self, store):
        """The cap must bite before the whole body has been read; a cap checked
        afterwards is not a cap."""
        seen: list[int] = []

        def chunks():
            for i in range(100):
                seen.append(i)
                yield b"x" * 100

        with pytest.raises(BlobTooLarge):
            store.write(chunks(), max_bytes=250)

        # Stopped after crossing 250 bytes, not after consuming all 10,000.
        assert len(seen) < 10

    def test_an_oversized_upload_leaves_nothing_behind(self, store):
        with pytest.raises(BlobTooLarge):
            store.write([b"x" * 500], max_bytes=100)

        assert list(store.root.rglob("*.part")) == []

    def test_digest_mismatch_is_rejected(self, store):
        """The bytes are the one thing that CAN be verified, so a lie about them
        is a hard failure."""
        with pytest.raises(DigestMismatch):
            store.write([b"actual"], max_bytes=1000, expected_sha256=digest_of(b"claimed"))

    def test_a_mismatched_upload_is_not_stored(self, store):
        with pytest.raises(DigestMismatch):
            store.write([b"actual"], max_bytes=1000, expected_sha256="a" * 64)

        assert store.exists(digest_of(b"actual")) is False
        assert list(store.root.rglob("*.part")) == []

    def test_matching_digest_passes(self, store):
        result = store.write([b"verified"], max_bytes=1000, expected_sha256=digest_of(b"verified"))
        assert result.created is True

    def test_empty_chunks_are_skipped(self, store):
        result = store.write([b"", b"a", b"", b"b"], max_bytes=100)
        assert store.read(result.sha256) == b"ab"


class TestRead:
    def test_missing_blob_reads_as_none(self, store):
        assert store.read("f" * 64) is None

    def test_bad_digest_reads_as_none_rather_than_raising(self, store):
        assert store.read("nonsense") is None

    def test_streams_in_chunks(self, store):
        result = store.write([b"x" * 5000], max_bytes=10_000)
        chunks = list(store.stream(result.sha256, chunk_size=1000))

        assert len(chunks) == 5
        assert b"".join(chunks) == b"x" * 5000

    def test_size_of_reports_none_when_absent(self, store):
        assert store.size_of("f" * 64) is None


class TestDelete:
    def test_removes_the_blob(self, store):
        result = store.write([b"doomed"], max_bytes=100)

        assert store.delete(result.sha256) is True
        assert store.exists(result.sha256) is False

    def test_deleting_twice_is_not_an_error(self, store):
        result = store.write([b"doomed"], max_bytes=100)
        store.delete(result.sha256)
        assert store.delete(result.sha256) is False

    def test_sweeps_empty_buckets(self, store):
        """Otherwise the tree accumulates empty directories for a corpus's life."""
        result = store.write([b"doomed"], max_bytes=100)
        bucket = store.path_for(result.sha256).parent
        store.delete(result.sha256)

        assert bucket.exists() is False

    def test_keeps_a_bucket_that_still_holds_something(self, store):
        a = store.write([b"one"], max_bytes=100)
        # Force a collision in the top bucket by writing until one shares a prefix.
        for i in range(500):
            b = store.write([f"probe-{i}".encode()], max_bytes=100)
            if b.sha256[:2] == a.sha256[:2] and b.sha256 != a.sha256:
                store.delete(b.sha256)
                assert store.exists(a.sha256) is True
                return
        pytest.skip("no prefix collision found in 500 probes")


class TestAccounting:
    def test_total_bytes_sums_the_store(self, store):
        store.write([b"x" * 100], max_bytes=1000)
        store.write([b"y" * 250], max_bytes=1000)

        assert store.total_bytes() == 350

    def test_total_is_zero_before_anything_is_written(self, store):
        assert store.total_bytes() == 0


def test_is_sha256():
    assert is_sha256("a" * 64)
    assert is_sha256("A" * 64)
    assert not is_sha256("a" * 63)
    assert not is_sha256("g" * 64)
    assert not is_sha256("")
