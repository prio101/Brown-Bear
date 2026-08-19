"""Agent configuration endpoints (spec 008 §8.4).

Under `/ext/` so the edge publishes them with no nginx change — everything there is
authenticated by the same shared secret as the rest of the gateway.

Two write routes rather than one. A JSON body is what a shell script can build with
no dependency; a zip is what a forty-file directory walk should be. One route
branching on `Content-Type` would have to accept both shapes as `Any` and would
document as neither.

The read routes never return anything but redacted text — the pre-redaction content
is not stored, so there is nothing here that could leak it.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from brownbear import agents as agents_service
from brownbear import gateway
from brownbear.agents import Branch, ConfigRejected, ZipLimits, ZipRejected
from brownbear.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ext/agents", tags=["agent configuration"])

CHUNK_BYTES = 1024 * 1024


class IncomingFile(BaseModel):
    #: Relative to the tool directory: `settings.json`, `skills/run/SKILL.md`.
    path: str
    #: The file's text. A binary file has no place in a JSON body — send an archive.
    content: str = ""


class SyncRequest(BaseModel):
    machine: str = Field(description="What the machine calls itself; normalised here")
    #: "global" for ~/.claude, "project" for a checkout's own directory.
    scope: str = "project"
    project: str = ""
    tool: str = "claude"
    #: Opt-in, and deliberately not the default: a partial push must never be able
    #: to wipe a branch. True only when the client walked the whole directory.
    prune: bool = False
    files: list[IncomingFile] = Field(default_factory=list)


def _branch(machine: str, scope: str, project: str, tool: str) -> Branch:
    """Normalise an address, turning a client's mistake into a 422 rather than a
    fifth branch nobody notices."""
    try:
        scope_kind, normalised_project = agents_service.normalise_scope(scope, project)
        return Branch(
            machine=agents_service.normalise_machine(machine),
            scope_kind=scope_kind,
            project=normalised_project,
            tool=agents_service.normalise_tool(tool),
        )
    except ConfigRejected as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc


async def _read_capped(request: Request, limit: int) -> bytes:
    """Read a JSON body, refusing one that is too large or does not say how large.

    A cap that can only be applied after the body has been buffered is not a cap,
    and a JSON document cannot be parsed incrementally without a streaming parser
    this app has no other use for. So the declared length is required: `411` when
    it is absent, `413` when it is over. Every HTTP client in normal use sends it.
    """
    declared = request.headers.get("content-length")
    if declared is None:
        raise HTTPException(
            status_code=411,
            detail="send Content-Length; a chunked body cannot be size-checked before it is read",
        )
    try:
        length = int(declared)
    except ValueError as exc:
        raise HTTPException(status_code=411, detail="Content-Length is not a number") from exc
    if length > limit:
        raise HTTPException(status_code=413, detail=f"body exceeds the {limit} byte limit")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        # Belt and braces: the header is a claim, and this is the byte count.
        if len(body) > limit:
            raise HTTPException(status_code=413, detail=f"body exceeds the {limit} byte limit")
    return bytes(body)


@router.post("/sync")
async def sync_json(request: Request) -> dict[str, Any]:
    """Sync one branch from a JSON snapshot.

    The body is read and size-checked here rather than declared as a parameter, so
    an oversized document is refused before it is parsed. `SyncRequest` still
    validates the shape, and still describes it in the OpenAPI schema.
    """
    settings = get_settings()
    raw = await _read_capped(request, settings.max_sync_bytes)

    try:
        payload = SyncRequest.model_validate(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"body is not JSON: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"body does not match the schema: {exc}"
        ) from exc

    branch = _branch(payload.machine, payload.scope, payload.project, payload.tool)
    files = [(item.path, item.content.encode("utf-8")) for item in payload.files]
    return await agents_service.sync(branch, files, prune=payload.prune)


@router.post("/sync/archive")
async def sync_archive(
    archive: Annotated[UploadFile, File(description="A zip of the tool directory")],
    machine: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "project",
    project: Annotated[str, Form()] = "",
    tool: Annotated[str, Form()] = "claude",
    prune: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    """Sync one branch from a zip.

    Read in bounded chunks and refused mid-stream on the way past the cap, then
    unpacked in memory — nothing is ever written to a filesystem, so a malicious
    entry name cannot escape anything. It is still validated, because the name
    becomes a stored path.
    """
    settings = get_settings()
    branch = _branch(machine, scope, project, tool)

    collected = bytearray()
    while chunk := await archive.read(CHUNK_BYTES):
        collected.extend(chunk)
        if len(collected) > settings.max_sync_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"archive exceeds the {settings.max_sync_bytes} byte limit",
            )
    if not collected:
        raise HTTPException(status_code=422, detail="empty archive")

    limits = ZipLimits(
        max_entries=settings.max_sync_files,
        max_total_bytes=settings.max_sync_unpacked_bytes,
        max_entry_bytes=settings.max_config_file_bytes,
    )
    try:
        files = agents_service.unpack_zip(bytes(collected), limits)
    except ZipRejected as exc:
        # 422 rather than 400: the request was well-formed and the archive is not
        # something this endpoint will process, which is what 422 says.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return await agents_service.sync(branch, files, prune=prune)


@router.get("")
async def inventory() -> dict[str, Any]:
    """The tree: machine → Global/project → tool, with counts and sync ages.

    Aggregated in the database. A response whose size grew with the number of
    stored files would make the page slower exactly as it became useful.
    """
    return await agents_service.inventory()


@router.get("/files")
async def files(
    machine: str | None = None,
    scope: str | None = None,
    project: str | None = None,
    tool: str | None = None,
    status: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """One branch's files, without their content.

    Content is per-file on selection: a machine's whole configuration would be
    megabytes of payload for a list nobody reads in full.
    """
    rows, total = await agents_service.listing(
        # Normalised the same way the write path normalises them, or a caller asking
        # for `Brown-Bear` silently gets nothing while `brownbear` sits in the table.
        machine=agents_service.normalise_machine(machine) if machine else None,
        scope_kind=scope,
        project=gateway.normalise_project(project) if project else None,
        tool=tool,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "files": [agents_service.to_dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/pull")
async def pull(
    machine: str,
    tool: str,
    scope: str = "project",
    project: str = "",
    include_removed: bool = False,
) -> dict[str, Any]:
    """Everything needed to write one branch back onto a machine.

    On demand, and only that: nothing here pushes configuration anywhere, and this
    answers a question a machine asked. It is the one read path that returns
    content in bulk, so every entry says whether it can actually be written back —
    a masked value restored verbatim produces a file that looks right and does not
    work, and a client must be able to refuse it without knowing the masking rules.
    """
    return await agents_service.pull(
        _branch(machine, scope, project, tool), include_removed=include_removed
    )


@router.get("/files/{config_id}/revisions")
async def revisions(config_id: str) -> dict[str, Any]:
    """A file's history, newest first, without content.

    Content is per revision on request: a history of ten versions of every file in
    a branch is the one response that would grow without bound.
    """
    record = await agents_service.get(config_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such config file: {config_id}")

    rows = await agents_service.revisions(config_id)
    return {
        "config_id": config_id,
        "path": record.path,
        "branch": agents_service.branch_label(
            record.machine, record.scope_kind, record.project, record.tool
        ),
        "current_revision": record.revision,
        "kept": get_settings().config_revisions_kept,
        "revisions": [agents_service.revision_to_dict(row) for row in rows],
    }


@router.get("/files/{config_id}/revisions/{number}")
async def revision(config_id: str, number: int) -> dict[str, Any]:
    """One past content, with the text as it was stored — that is, redacted."""
    row = await agents_service.revision(config_id, number)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no revision {number} of {config_id}"
        )
    return agents_service.revision_to_dict(row, include_content=True)


@router.get("/files/{config_id}")
async def detail(config_id: str) -> dict[str, Any]:
    """One file with its stored — that is, redacted — content."""
    record = await agents_service.get(config_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no such config file: {config_id}")
    return agents_service.to_dict(record, include_content=True)


@router.delete("/files/{config_id}")
async def remove(config_id: str) -> dict[str, Any]:
    """Purge a row.

    The explicit counterpart to `prune`, which only marks. A file that vanished
    from a machine is kept and shown as removed; forgetting it entirely is a
    decision somebody has to make on purpose.
    """
    result = await agents_service.remove(config_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no such config file: {config_id}")
    return {**result, "deleted": True}
