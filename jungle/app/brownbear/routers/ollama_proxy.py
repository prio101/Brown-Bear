"""Token-capturing Ollama proxy (spec 003 §3.1).

Roadmap M3 chose the proxy over polling /api/ps: polling samples loaded models
and loses the per-call counts entirely. Clients point at this app instead of
Ollama, and once that migration is done Ollama's host port should be closed.

The whole upstream response is streamed through untouched. Token counts come
from the final JSON object Ollama emits (``prompt_eval_count`` / ``eval_count``),
which is only complete once the stream ends — so recording happens *after* the
last byte reaches the client, never in the request path.
"""

import json
import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from brownbear.config import get_settings
from brownbear.connectors import get_http_client
from brownbear.models.tokens import TokenSource
from brownbear.tracking import record_token_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ollama", tags=["ollama"])

# Endpoints that report token counts. Everything else is pure passthrough.
TRACKED_ENDPOINTS = {"api/chat", "api/generate", "api/embed", "api/embeddings"}

# Headers that describe a single hop and must not be forwarded.
_SKIP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "transfer-encoding",
    # Dropped so httpx hands us a decoded body to read counts from.
    "accept-encoding",
}
_SKIP_RESPONSE_HEADERS = {
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "connection",
}

# httpx decodes the body for us, so a huge embedding response would otherwise
# be buffered in full just to read a counter off the end of it.
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
TAIL_BYTES = 256 * 1024


def _normalise(path: str) -> str:
    return path.strip("/")


def _forward_request_headers(headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _SKIP_REQUEST_HEADERS}


def _forward_response_headers(headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _SKIP_RESPONSE_HEADERS}


def extract_usage(raw: bytes) -> dict | None:
    """Pull the usage object out of an Ollama response body.

    Handles both shapes with one pass: streaming endpoints emit NDJSON whose
    final line carries the counts, non-streaming ones emit a single object.
    Scanning from the end finds the counts in either case, and still works when
    only the tail of an oversized body was kept.
    """
    if not raw:
        return None
    text = raw.decode("utf-8", errors="ignore")
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and (
            "prompt_eval_count" in payload or "eval_count" in payload
        ):
            return payload
    return None


@router.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"]
)
async def proxy(path: str, request: Request) -> StreamingResponse:
    settings = get_settings()
    client = get_http_client()
    endpoint = _normalise(path)
    url = f"{settings.ollama_url.rstrip('/')}/{endpoint}"

    body = await request.body()
    upstream_request = client.build_request(
        request.method,
        url,
        content=body,
        headers=_forward_request_headers(request.headers),
        params=request.query_params,
    )

    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ollama unreachable: {exc}") from exc

    tracked = endpoint in TRACKED_ENDPOINTS and upstream.status_code < 400

    requested_model = None
    if tracked and body:
        try:
            requested_model = json.loads(body).get("model")
        except (json.JSONDecodeError, AttributeError):
            requested_model = None

    session_id = request.headers.get("x-bb-session-id")
    user_id = request.headers.get("x-bb-user-id")

    async def stream() -> AsyncIterator[bytes]:
        captured = bytearray()
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
                if tracked:
                    captured.extend(chunk)
                    if len(captured) > MAX_CAPTURE_BYTES:
                        del captured[:-TAIL_BYTES]
        finally:
            await upstream.aclose()

        if not tracked:
            return

        usage = extract_usage(bytes(captured))
        if usage is None:
            logger.warning("no token counts in %s response", endpoint)
            return

        model = usage.get("model") or requested_model
        if not model:
            logger.warning("token counts for %s had no model name", endpoint)
            return

        await record_token_event(
            model=model,
            tokens_in=int(usage.get("prompt_eval_count") or 0),
            tokens_out=int(usage.get("eval_count") or 0),
            source=TokenSource.local_ollama,
            endpoint=endpoint,
            session_id=session_id,
            user_id=user_id,
        )

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=_forward_response_headers(upstream.headers),
    )
