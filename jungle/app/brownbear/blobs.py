"""Content-addressed blob store (spec 007 §7.1).

Bytes on a volume, named by the SHA-256 of their own content. That single choice
does most of the work this feature needs:

  * **Dedup is free.** The same PDF uploaded from three machines writes one file.
  * **Blobs are immutable.** A path always names the same bytes, so nothing has to
    be invalidated, versioned or locked.
  * **Integrity is checkable.** Re-hashing a blob proves it is what it claims,
    which matters because the extraction that accompanies it cannot be verified.

Deliberately not a database column. Postgres `bytea` bloats a database that is
backed up as a unit and makes a 50 MB row a normal occurrence; object storage is a
whole service for one feature. A volume is the honest shape at this scale.

No FastAPI, no SQLAlchemy, no settings import beyond the root path — this is a
plain module so its edge cases can be tested without a request or a session.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

#: Two levels of two hex characters. One flat directory of 100k files is slow to
#: list and unpleasant on some filesystems; 256 × 256 buckets keeps any single
#: directory small without a deep tree.
FAN_OUT = 2


class BlobTooLarge(Exception):
    """Raised mid-stream, before the whole upload has been read.

    A size cap checked after reading the body is not a cap — the bytes are already
    in memory or on disk by then.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(f"upload exceeds the {limit} byte limit")
        self.limit = limit


class DigestMismatch(Exception):
    """The bytes received do not hash to the digest the client claimed."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(f"expected sha256 {expected}, received {actual}")
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    size_bytes: int
    #: False when the content was already present. The caller reports this as
    #: `deduplicated`, and skips re-embedding on the strength of it.
    created: bool


def is_sha256(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


class BlobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, digest: str) -> Path:
        """Bucketed path for a digest.

        Validated rather than trusted: a digest reaches this from a URL, and an
        unvalidated one containing `../` would escape the store entirely. Rejecting
        anything that is not 64 hex characters makes traversal impossible by
        construction rather than by sanitising.
        """
        if not is_sha256(digest):
            raise ValueError(f"not a sha256 digest: {digest!r}")
        lower = digest.lower()
        return self.root / lower[:FAN_OUT] / lower[FAN_OUT : FAN_OUT * 2] / lower

    def exists(self, digest: str) -> bool:
        try:
            return self.path_for(digest).is_file()
        except ValueError:
            return False

    def size_of(self, digest: str) -> int | None:
        path = self.path_for(digest)
        try:
            return path.stat().st_size
        except OSError:
            return None

    def write(
        self,
        chunks: Iterable[bytes],
        *,
        max_bytes: int,
        expected_sha256: str | None = None,
    ) -> StoredBlob:
        """Stream chunks to the store, hashing as they arrive.

        Written to a temporary file in the same directory and moved into place, so
        a blob is never observable half-written: `os.replace` is atomic within a
        filesystem, and a reader either sees the whole blob or no blob.

        The size cap is enforced per chunk, so an oversized upload is refused as
        soon as it crosses the line rather than after it has all arrived.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0

        handle = tempfile.NamedTemporaryFile(dir=self.root, delete=False, suffix=".part")
        temp = Path(handle.name)
        try:
            with handle:
                for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise BlobTooLarge(max_bytes)
                    digest.update(chunk)
                    handle.write(chunk)

            actual = digest.hexdigest()
            if expected_sha256 is not None and actual.lower() != expected_sha256.lower():
                raise DigestMismatch(expected_sha256, actual)

            target = self.path_for(actual)
            if target.is_file():
                # Already stored. The upload was still worth streaming — it is how
                # the digest was learned — but the bytes are redundant.
                temp.unlink(missing_ok=True)
                return StoredBlob(sha256=actual, size_bytes=size, created=False)

            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp, target)
            return StoredBlob(sha256=actual, size_bytes=size, created=True)
        except BaseException:
            # Includes the size and digest failures above: a rejected upload must
            # not leave a .part file behind to accumulate forever.
            temp.unlink(missing_ok=True)
            raise

    def read(self, digest: str) -> bytes | None:
        try:
            return self.path_for(digest).read_bytes()
        except (OSError, ValueError):
            return None

    def stream(self, digest: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """Yield a blob in chunks, so serving a 50 MB file costs 64 KB of memory."""
        path = self.path_for(digest)
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    return
                yield chunk

    def delete(self, digest: str) -> bool:
        """Remove a blob. Empty buckets are swept so the tree does not accumulate
        thousands of empty directories over a corpus's lifetime."""
        try:
            path = self.path_for(digest)
        except ValueError:
            return False
        if not path.is_file():
            return False
        path.unlink()
        for parent in (path.parent, path.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break  # not empty, which is the common case
        return True

    def total_bytes(self) -> int:
        """Disk consumed by the store. Blobs are the first thing in this stack to
        consume real disk and nothing prunes them yet, so the number is surfaced."""
        if not self.root.is_dir():
            return 0
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())


def disk_free_bytes(path: str | Path) -> int:
    try:
        return shutil.disk_usage(Path(path)).free
    except OSError:
        return 0
