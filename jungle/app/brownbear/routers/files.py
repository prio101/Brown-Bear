"""File endpoints (spec 007 §7.3).

Under `/ext/` so the edge publishes them with no nginx change — everything there is
authenticated by the same shared secret as the rest of the gateway.

The route that needs care is `/preview`. It is the only place in this stack that
serves attacker-supplied bytes back to a browser *inline* rather than as a
download, so it carries its own headers and a strict type allowlist. Everything
else is served as an attachment.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from brownbear import files as files_service
from brownbear import gateway
from brownbear.blobs import BlobTooLarge, DigestMismatch, is_sha256
from brownbear.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ext/files", tags=["files"])

CHUNK_BYTES = 1024 * 1024

#: Inline responses get these instead of the server block's defaults. nginx and
#: the app both set headers; the app's are the ones that survive a proxy_pass, so
#: the safety-critical pair is repeated here rather than assumed.
INLINE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # The one route that renders untrusted bytes. A PDF can carry JavaScript; the
    # browser viewer sandboxes it, and this makes sure nothing else is reachable.
    "Content-Security-Policy": "default-src 'none'; object-src 'none'; sandbox",
}


async def _stream_upload(upload: UploadFile, limit: int):
    """Yield an upload in chunks so nothing is ever fully buffered.

    A generator rather than `await upload.read()`: reading a 50MB file into memory
    to then check that it is under 50MB defeats the point of the limit.
    """
    while True:
        chunk = await upload.read(CHUNK_BYTES)
        if not chunk:
            return
        yield chunk


def _blocking_write(store, chunks: list[bytes], *, max_bytes: int, expected: str | None):
    return store.write(iter(chunks), max_bytes=max_bytes, expected_sha256=expected)


@router.get("/{digest}/exists")
async def exists(digest: str) -> dict[str, Any]:
    """Dedup precheck: is this content already here?

    Lets a client skip uploading a 40MB PDF that another machine already sent. The
    digest is the whole question, so this is cheap and needs no auth beyond the
    edge's — it reveals only whether a hash is known.
    """
    if not is_sha256(digest):
        raise HTTPException(status_code=422, detail="not a sha256 digest")

    record = await files_service.by_digest(digest.lower())
    present = files_service.blob_store().exists(digest.lower())
    return {
        "sha256": digest.lower(),
        "exists": record is not None and present,
        "blob_present": present,
        "indexed": record is not None and str(record.status) == "indexed",
        "file_id": record.id if record else None,
        "chunk_count": record.chunk_count if record else 0,
    }


@router.post("")
async def upload(
    file: Annotated[UploadFile, File(description="The original bytes")],
    project: Annotated[str, Form()] = "default",
    source: Annotated[str, Form()] = "",
    extraction: Annotated[str, Form(description="Text extracted on the client")] = "",
    extractor: Annotated[str, Form()] = "",
    extracted_by: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    sha256: Annotated[str, Form(description="Client's digest, verified here")] = "",
    preview: Annotated[UploadFile | None, File()] = None,
) -> JSONResponse:
    """Store a file and the text a client extracted from it.

    Synchronous: without server-side extraction there is no slow step. Embedding
    the text is the only work, and `nomic-embed-text` is 137M parameters.
    """
    settings = get_settings()
    store = files_service.blob_store()

    if sha256 and not is_sha256(sha256):
        raise HTTPException(status_code=422, detail="sha256 is not a digest")

    # Read in bounded chunks, then hand the list to the blocking writer off-loop.
    # The cap is checked here as well as in the store so an oversized body is cut
    # off during the read rather than after it.
    collected: list[bytes] = []
    total = 0
    async for chunk in _stream_upload(file, settings.max_upload_bytes):
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds the {settings.max_upload_bytes} byte limit",
            )
        collected.append(chunk)

    if total == 0:
        raise HTTPException(status_code=422, detail="empty upload")

    try:
        stored = await anyio.to_thread.run_sync(
            lambda: _blocking_write(
                store, collected, max_bytes=settings.max_upload_bytes, expected=sha256 or None
            )
        )
    except DigestMismatch as exc:
        # The bytes are the one thing that CAN be verified here, so a mismatch is a
        # hard failure rather than a warning.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BlobTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception("blob write failed")
        raise HTTPException(status_code=507, detail=f"could not store the file: {exc}") from exc

    head = collected[0][:512] if collected else b""
    media_type = files_service.sniff_media_type(head, file.filename or "")

    preview_digest: str | None = None
    if preview is not None:
        preview_bytes: list[bytes] = []
        size = 0
        async for chunk in _stream_upload(preview, settings.max_preview_bytes):
            size += len(chunk)
            if size > settings.max_preview_bytes:
                preview_bytes = []
                break
            preview_bytes.append(chunk)
        if preview_bytes:
            head_preview = preview_bytes[0][:512]
            # A "preview" that is not an image is not a preview; storing one would
            # give the browser something unexpected to render inline.
            if files_service.sniff_media_type(head_preview).startswith("image/"):
                try:
                    saved = await anyio.to_thread.run_sync(
                        lambda: _blocking_write(
                            store, preview_bytes, max_bytes=settings.max_preview_bytes, expected=None
                        )
                    )
                    preview_digest = saved.sha256
                except (OSError, BlobTooLarge):
                    logger.warning("preview rejected for %s", file.filename)

    result = await files_service.store(
        digest=stored.sha256,
        size_bytes=stored.size_bytes,
        filename=file.filename or stored.sha256[:12],
        media_type=media_type,
        project=gateway.normalise_project(project),
        source=(source or file.filename or stored.sha256[:12]),
        extraction=extraction,
        extractor=extractor or None,
        extracted_by=extracted_by or None,
        preview_sha256=preview_digest,
        tags=tags or None,
        deduplicated=not stored.created,
    )
    return JSONResponse(result, status_code=200)


@router.get("")
async def index(
    project: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List stored files, newest first."""
    rows, total = await files_service.listing(
        project=gateway.normalise_project(project) if project else None,
        status=status,
        limit=limit,
        offset=offset,
    )
    store = files_service.blob_store()
    return {
        "files": [
            # Reported live rather than trusted from the row: a volume can be pruned
            # underneath us, and a file listed as indexed whose bytes are gone is
            # exactly the kind of quiet lie worth catching.
            {**files_service.to_dict(row), "blob_present": store.exists(row.sha256)}
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "store_bytes": store.total_bytes(),
    }


@router.get("/{file_id}")
async def detail(file_id: str, download: bool = False) -> Any:
    """Metadata plus the full extracted text, or the original bytes.

    The extracted text is the point: it answers "what did the memory actually read
    out of this file", which nothing else in the stack can answer.
    """
    record = await files_service.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such file: {file_id}")

    store = files_service.blob_store()
    if not download:
        payload = files_service.to_dict(record, include_text=True)
        payload["blob_present"] = store.exists(record.sha256)
        if not payload["blob_present"]:
            payload["status"] = "missing"
        return payload

    if not store.exists(record.sha256):
        raise HTTPException(status_code=410, detail="the stored bytes are gone")

    return StreamingResponse(
        store.stream(record.sha256),
        # Always a download, always opaque: an uploaded .html served as text/html
        # from this origin would be stored XSS against the dashboard.
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{record.filename}"',
            "Content-Length": str(record.size_bytes),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{file_id}/preview")
async def preview(file_id: str, request: Request) -> Any:
    """Inline-renderable bytes for the browser.

    Three sources, in order: the client-supplied thumbnail, then the original when
    it is an image or a PDF, then nothing. Only types on the allowlist are served
    inline; SVG is excluded deliberately — it can carry script, and inline from this
    origin that script runs with the reader's session.
    """
    record = await files_service.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such file: {file_id}")

    store = files_service.blob_store()

    if record.preview_sha256 and store.exists(record.preview_sha256):
        digest = record.preview_sha256
        head = (store.read(digest) or b"")[:512]
        media_type = files_service.sniff_media_type(head)
    elif files_service.is_inline_renderable(record.media_type) and store.exists(record.sha256):
        digest = record.sha256
        media_type = record.media_type
    else:
        raise HTTPException(
            status_code=404,
            detail="no preview: this type is not rendered inline and no thumbnail was supplied",
        )

    if not files_service.is_inline_renderable(media_type):
        raise HTTPException(status_code=404, detail="not an inline-renderable type")

    return StreamingResponse(
        store.stream(digest),
        media_type=media_type,
        headers={
            **INLINE_HEADERS,
            "Content-Disposition": "inline",
            # SAMEORIGIN, not DENY: a PDF renders in a sandboxed iframe on the
            # dashboard, and the edge's blanket DENY would block it. Still not
            # ALLOWALL — nobody else may frame this.
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


class Extraction(BaseModel):
    """What a reader of the file sends back (spec 009).

    `text` is the English reading and is what gets indexed. `source_text` is the
    original language, stored beside it so the translation can be checked. Neither
    is produced here — Brown Bear still extracts nothing.
    """

    text: str
    source_text: str | None = None
    #: Language of `text`. English by default, because that is what the retrieval
    #: corpus is expected to be uniform in.
    language: str = "en"
    #: Language of `source_text`, when it differs.
    source_language: str | None = None
    #: Who read it — "claude-opus-5", "pdftotext 24.02". Recorded, never verified.
    extractor: str | None = None
    extracted_by: str | None = None
    tags: str | None = None


@router.post("/{file_id}/extraction")
async def attach_extraction(file_id: str, payload: Extraction) -> dict[str, Any]:
    """Attach an extraction to a file whose bytes are already here.

    Splits ingestion in two, which is what makes a read-time hook possible: the
    bytes go up the moment a file is touched, and the text follows from whoever
    actually read it. It also answers spec 007's open question about re-extraction —
    a better reading of an existing file no longer requires re-sending the bytes.

    Replaces the file's chunks rather than adding to them. Two readings of one
    document, both retrievable, is worse than one poor reading.
    """
    if len(payload.text) > files_service.MAX_EXTRACTION_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"extraction exceeds {files_service.MAX_EXTRACTION_CHARS} characters",
        )

    result = await files_service.reattach(
        file_id,
        text=payload.text,
        source_text=payload.source_text,
        language=payload.language,
        source_language=payload.source_language,
        extractor=payload.extractor,
        extracted_by=payload.extracted_by,
        tags=payload.tags,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"no such file: {file_id}. Send the bytes to POST /ext/files first.",
        )
    return result


@router.delete("/{file_id}")
async def remove(file_id: str) -> dict[str, Any]:
    """Delete the row, the blob and the chunks together.

    Without the chunks, retrieval keeps serving passages from a file that no longer
    exists — a corpus quietly disagreeing with itself.
    """
    result = await files_service.remove(file_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no such file: {file_id}")
    return result
