"""File ingestion (spec 007 §7.4, §7.5).

Extraction happens on the machine that has the file. This module takes the bytes
and the text that machine produced, stores both, and puts the text through the
retrieval path that already exists — `gateway.ingest()`, unchanged.

Two things it is careful about:

**The bytes are verified; the extraction is not.** Re-hashing what arrived proves
the file is what the client said it was. Whether the text actually corresponds to
those bytes cannot be checked without doing the extraction here, which is the thing
this design removes. So the extractor is recorded and attributed instead — the same
posture as `/ext/exchange`, where the client reports its own token counts.

**A file is retrieval material, never an answer.** Everything here lands in the
`knowledge` collection. Nothing in this module writes to `conversations`, because a
paragraph of a PDF being served as though Brown Bear had said it is precisely the
failure the two-collection split exists to prevent.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import anyio.to_thread
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brownbear import gateway
from brownbear.blobs import BlobStore
from brownbear.config import get_settings
from brownbear.db import session_scope
from brownbear.models.files import FileRecord, FileStatus

logger = logging.getLogger(__name__)

#: Inline-renderable in a browser. Everything else is downloaded.
#:
#: SVG is deliberately absent. It is an image format that is also a document
#: format: an .svg can carry <script>, and served inline from this origin that
#: script runs with the reader's session. It is previewed as source text instead.
INLINE_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}
)

#: Types whose extraction is simply their own content, shown as text.
TEXTUAL_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "image/svg+xml",
        "text/html",
    }
)

#: Above this, two files are probably the same document under different names.
#: Deliberately far above the graph's edge floor (0.60) and above the cache cutoff
#: (0.95): this claims near-identity, which is a much stronger statement than
#: "related".
NEAR_DUPLICATE_MIN = 0.97

MAX_EXTRACTION_CHARS = 4_000_000


def file_id(sha256: str) -> str:
    """Key Based layer convention, extended to bytes."""
    return f"f_{sha256[:32]}"


#: (offset, magic bytes, media type). Order matters — the first match wins.
_MAGIC: tuple[tuple[int, bytes, str], ...] = (
    (0, b"\x89PNG\r\n\x1a\n", "image/png"),
    (0, b"\xff\xd8\xff", "image/jpeg"),
    (0, b"GIF87a", "image/gif"),
    (0, b"GIF89a", "image/gif"),
    (0, b"%PDF-", "application/pdf"),
    (0, b"PK\x03\x04", "application/zip"),
    (0, b"\x1f\x8b", "application/gzip"),
)


def sniff_media_type(head: bytes, filename: str = "") -> str:
    """Media type from the bytes themselves.

    Not from the client's Content-Type and not from the extension: both are
    attacker-controlled, and an .html file declared as text/plain that is then
    served back as text/html is a stored-XSS on the dashboard's own origin.

    The filename is consulted only to separate textual formats from each other —
    Markdown and JSON have no magic number, and getting that distinction wrong
    affects presentation rather than safety.
    """
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    for offset, magic, media_type in _MAGIC:
        if head[offset : offset + len(magic)] == magic:
            return media_type

    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"

    stripped = text.lstrip().lower()
    if stripped.startswith(("<?xml", "<svg")):
        return "image/svg+xml"
    if stripped.startswith(("<!doctype html", "<html")):
        return "text/html"

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "md": "text/markdown",
        "markdown": "text/markdown",
        "json": "application/json",
        "csv": "text/csv",
    }.get(suffix, "text/plain")


def is_inline_renderable(media_type: str) -> bool:
    return media_type in INLINE_TYPES


def blob_store() -> BlobStore:
    return BlobStore(get_settings().blob_dir)


_TAG_NOISE = re.compile(r"[^a-z0-9_-]+")


def normalise_tags(raw: str | None) -> str | None:
    if not raw:
        return None
    tags = [_TAG_NOISE.sub("-", t.strip().lower()).strip("-") for t in raw.split(",")]
    kept = sorted({t for t in tags if t})
    return ",".join(kept) or None


# --- persistence ------------------------------------------------------------
# Sync SQLAlchemy, run off the event loop by the router, matching the rest of the
# app (see db.py).


def _get_sync(identifier: str) -> FileRecord | None:
    with session_scope() as session:
        record = session.get(FileRecord, identifier)
        if record is not None:
            session.expunge(record)
        return record


def _by_digest_sync(digest: str) -> FileRecord | None:
    with session_scope() as session:
        record = session.scalars(
            select(FileRecord).where(FileRecord.sha256 == digest)
        ).one_or_none()
        if record is not None:
            session.expunge(record)
        return record


def _list_sync(
    *, project: str | None, status: str | None, limit: int, offset: int
) -> tuple[list[FileRecord], int]:
    with session_scope() as session:
        query = select(FileRecord)
        count_query = select(func.count()).select_from(FileRecord)
        if project:
            query = query.where(FileRecord.project == project)
            count_query = count_query.where(FileRecord.project == project)
        if status:
            query = query.where(FileRecord.status == status)
            count_query = count_query.where(FileRecord.status == status)

        total = session.scalar(count_query) or 0
        rows = list(
            session.scalars(
                query.order_by(FileRecord.created_at.desc()).limit(limit).offset(offset)
            )
        )
        for row in rows:
            session.expunge(row)
        return rows, total


def _upsert_sync(values: dict[str, Any]) -> FileRecord:
    with session_scope() as session:
        record = session.get(FileRecord, values["id"])
        if record is None:
            record = FileRecord(**values)
            session.add(record)
        else:
            for key, value in values.items():
                # A re-upload must not blank fields the first upload supplied — a
                # machine without an extractor should not erase another's text.
                if value is not None:
                    setattr(record, key, value)
        session.flush()
        session.expunge(record)
        return record


def _delete_sync(identifier: str) -> FileRecord | None:
    with session_scope() as session:
        record = session.get(FileRecord, identifier)
        if record is None:
            return None
        session.delete(record)
        # Flush BEFORE expunging. `expunge` evicts the instance from the session
        # and discards the pending delete with it, so expunging first left this
        # route removing the blob and the chunks, reporting success, and keeping
        # the row — a file that then reads as `missing` for ever. Flushing emits
        # the DELETE first, so the expunge only detaches.
        session.flush()
        session.expunge(record)
        return record


async def get(identifier: str) -> FileRecord | None:
    return await anyio.to_thread.run_sync(_get_sync, identifier)


async def by_digest(digest: str) -> FileRecord | None:
    return await anyio.to_thread.run_sync(_by_digest_sync, digest)


async def listing(
    *, project: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[FileRecord], int]:
    return await anyio.to_thread.run_sync(
        lambda: _list_sync(project=project, status=status, limit=limit, offset=offset)
    )


# --- ingest -----------------------------------------------------------------


async def index_extraction(
    *,
    record_id: str,
    text: str,
    source: str,
    project: str,
    media_type: str,
) -> dict[str, Any]:
    """Chunk and embed the client's extraction into `knowledge`.

    Each chunk carries `file_id` and `media_type`, so a retrieved passage can be
    traced back to the original bytes — which is what makes retrieval answerable
    rather than merely relevant.
    """
    collections = await gateway.ensure_collections()
    return await gateway.ingest(
        collections,
        text=text,
        source=source,
        project=project,
        metadata={"file_id": record_id, "media_type": media_type},
    )


async def near_duplicates(
    *, text: str, project: str, exclude_file_id: str
) -> list[dict[str, Any]]:
    """Other files whose content is near-identical to this one.

    Two exports of the same document under different filenames hash differently, so
    content addressing does not catch them; only the vectors do. Best-effort: a
    failure here must not fail an otherwise good ingest.
    """
    try:
        collections = await gateway.ensure_collections()
        probe = text[: get_settings().chunk_chars]
        if not probe.strip():
            return []
        embedding = await gateway.embeddings.embed_one(probe)
        hits = await gateway.chroma.query(
            collections.knowledge,
            embedding=embedding,
            n_results=5,
            where={"project": {"$eq": project}},
        )
    except Exception:  # noqa: BLE001
        logger.exception("near-duplicate probe failed for %s", exclude_file_id)
        return []

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        meta = hit.get("metadata") or {}
        other = meta.get("file_id")
        if not other or other == exclude_file_id or other in seen:
            continue
        score = gateway.similarity(hit.get("distance"), collections.knowledge_space)
        if score is None or score < NEAR_DUPLICATE_MIN:
            continue
        seen.add(str(other))
        found.append({"file_id": other, "score": score, "source": meta.get("source")})
    return found


async def store(
    *,
    digest: str,
    size_bytes: int,
    filename: str,
    media_type: str,
    project: str,
    source: str,
    extraction: str | None,
    extractor: str | None,
    extracted_by: str | None,
    preview_sha256: str | None,
    tags: str | None,
    deduplicated: bool,
) -> dict[str, Any]:
    """Persist the record and index its extraction.

    Ordered so a failure leaves something coherent: the row is written *before*
    embedding is attempted, so a crash during embedding leaves a downloadable file
    marked `failed` rather than orphaned bytes with nothing pointing at them.
    """
    identifier = file_id(digest)
    text = (extraction or "").strip()[:MAX_EXTRACTION_CHARS]

    base: dict[str, Any] = {
        "id": identifier,
        "sha256": digest,
        "filename": filename[:512],
        "media_type": media_type,
        "size_bytes": size_bytes,
        "project": project,
        "source": source[:512],
        "extracted_text": text or None,
        "extractor": extractor,
        "extracted_by": extracted_by,
        "has_preview": preview_sha256 is not None,
        "preview_sha256": preview_sha256,
        "tags": normalise_tags(tags),
        "status": FileStatus.stored,
        "error": None,
        "chunk_count": 0,
    }

    existing = await by_digest(digest)
    # Already indexed and no better extraction offered: nothing to redo. This is
    # what makes the same PDF from three machines cost one embedding pass.
    if existing is not None and existing.status == FileStatus.indexed and not text:
        return {
            "file_id": existing.id,
            "status": str(existing.status),
            "chunks_stored": existing.chunk_count,
            "deduplicated": True,
            "near_duplicates": [],
        }

    await anyio.to_thread.run_sync(_upsert_sync, base)

    if not text:
        return {
            "file_id": identifier,
            "status": FileStatus.stored.value,
            "chunks_stored": 0,
            "deduplicated": deduplicated,
            "near_duplicates": [],
            "note": "no extraction supplied; the file is stored and downloadable but not searchable",
        }

    try:
        result = await index_extraction(
            record_id=identifier,
            text=text,
            source=source,
            project=project,
            media_type=media_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("indexing failed for %s", identifier)
        await anyio.to_thread.run_sync(
            _upsert_sync,
            {
                **base,
                "status": FileStatus.failed,
                "error": f"{type(exc).__name__}: {exc}"[:2000],
            },
        )
        return {
            "file_id": identifier,
            "status": FileStatus.failed.value,
            "chunks_stored": 0,
            "deduplicated": deduplicated,
            "near_duplicates": [],
            "error": type(exc).__name__,
        }

    stored_chunks = int(result.get("chunks_stored", 0))
    await anyio.to_thread.run_sync(
        _upsert_sync,
        {
            **base,
            "status": FileStatus.indexed,
            "chunk_count": stored_chunks,
            "indexed_at": datetime.now(UTC),
        },
    )

    return {
        "file_id": identifier,
        "status": FileStatus.indexed.value,
        "chunks_stored": stored_chunks,
        "deduplicated": deduplicated,
        "near_duplicates": await near_duplicates(
            text=text, project=project, exclude_file_id=identifier
        ),
    }


async def remove(identifier: str) -> dict[str, Any] | None:
    """Delete a file, its blob and its chunks together.

    All three, or the corpus lies: chunks left behind keep being retrieved and
    served as context for a file that no longer exists, and a blob left behind
    consumes disk nothing references.
    """
    record = await anyio.to_thread.run_sync(_delete_sync, identifier)
    if record is None:
        return None

    removed_chunks = 0
    try:
        collections = await gateway.ensure_collections()
        removed_chunks = await gateway.delete_by_file(collections, identifier)
    except Exception:  # noqa: BLE001
        logger.exception("could not remove chunks for %s", identifier)

    store_ = blob_store()
    # Only if no other row shares the content. Rows are unique per digest today,
    # but a shared preview blob between two files is possible.
    blob_removed = store_.delete(record.sha256)
    if record.preview_sha256:
        store_.delete(record.preview_sha256)

    return {
        "file_id": identifier,
        "blob_removed": blob_removed,
        "chunks_removed": removed_chunks,
    }


def to_dict(record: FileRecord, *, include_text: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "file_id": record.id,
        "sha256": record.sha256,
        "filename": record.filename,
        "media_type": record.media_type,
        "size_bytes": record.size_bytes,
        "project": record.project,
        "source": record.source,
        "extractor": record.extractor,
        "extracted_by": record.extracted_by,
        "has_preview": record.has_preview,
        "status": str(record.status),
        "error": record.error,
        "chunk_count": record.chunk_count,
        "tags": record.tags.split(",") if record.tags else [],
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "indexed_at": record.indexed_at.isoformat() if record.indexed_at else None,
        "extracted_chars": len(record.extracted_text or ""),
        "inline_renderable": is_inline_renderable(record.media_type),
    }
    if include_text:
        payload["extracted_text"] = record.extracted_text
    return payload
