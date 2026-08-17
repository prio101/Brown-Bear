"""Streamed logs (BB-301).

The database is faked at the two read functions rather than mocked at the session,
so these test the streaming behaviour — framing, ordering, the high-water mark —
and not SQLAlchemy.

The stream is an endless generator, so every test that opens it reads a bounded
number of frames and closes. A test that iterates to exhaustion would hang the
suite rather than fail it.
"""

import json
from datetime import UTC, datetime

import pytest

from brownbear.routers import logs


def _query_payload(row_id, text="a prompt", collection="conversations", minute=0):
    return {
        "kind": "query",
        "id": row_id,
        "timestamp": datetime(2026, 8, 1, 12, minute, tzinfo=UTC).isoformat(),
        "collection": collection,
        "query_text": text,
        "latency_ms": 41.5,
        "result_count": 3,
    }


def _token_payload(row_id, model="claude-opus-5", minute=0):
    return {
        "kind": "token",
        "id": row_id,
        "timestamp": datetime(2026, 8, 1, 12, minute, tzinfo=UTC).isoformat(),
        "model": model,
        "source": "remote_api",
        "endpoint": "/ext/exchange",
        "tokens_in": 120,
        "tokens_out": 340,
        "total_tokens": 460,
        "cost_usd": 0.0131,
    }


async def _never_disconnected() -> bool:
    return False


async def _collect(*, stop_after="ready", cap=400, backlog=logs.BACKLOG_DEFAULT):
    """Drive the generator directly and close it at `stop_after`.

    Not over HTTP: the generator is endless by design, and a test client cannot
    close one from its side — the suite would hang instead of failing.
    """
    frames: list[str] = []
    generator = logs.event_stream(_never_disconnected, backlog)
    try:
        async for frame in generator:
            frames.append(frame)
            if frame.startswith(f"event: {stop_after}") or len(frames) >= cap:
                break
    finally:
        await generator.aclose()
    return frames


def _events(frames):
    """(event_name, payload) pairs from raw SSE frames."""
    out = []
    for frame in frames:
        name = frame.split("\n", 1)[0].removeprefix("event: ").strip()
        data = frame.split("data: ", 1)[1].strip()
        out.append((name, json.loads(data)))
    return out


class TestRowShaping:
    def test_long_query_text_is_truncated(self):
        assert logs._truncate("x" * 5000).endswith("…")
        assert len(logs._truncate("x" * 5000)) == logs.TEXT_CHARS

    def test_short_text_is_untouched(self):
        assert logs._truncate("a short prompt") == "a short prompt"

    def test_none_stays_none(self):
        assert logs._truncate(None) is None

    def test_whitespace_is_flattened(self):
        """A multi-line prompt would otherwise break the SSE frame: a bare newline
        inside `data:` terminates the event early."""
        assert "\n" not in logs._truncate("line one\nline two\n\nline three")

    def test_frame_is_well_formed_sse(self):
        frame = logs._frame(_query_payload(1))
        assert frame.startswith("event: query\ndata: ")
        assert frame.endswith("\n\n")
        assert json.loads(frame.split("data: ", 1)[1].strip())["id"] == 1


class TestRecent:
    def test_returns_rows(self, client, monkeypatch):
        monkeypatch.setattr(
            logs, "_read_backlog", lambda limit: ([_query_payload(1), _token_payload(2)], 1, 2)
        )
        body = client.get("/api/logs/recent").json()

        assert body["count"] == 2
        assert {r["kind"] for r in body["rows"]} == {"query", "token"}

    def test_limit_is_bounded(self, client, monkeypatch):
        monkeypatch.setattr(logs, "_read_backlog", lambda limit: ([], 0, 0))
        assert client.get("/api/logs/recent", params={"limit": 10_000}).status_code == 422
        assert client.get("/api/logs/recent", params={"limit": 0}).status_code == 422


class TestStream:
    @pytest.fixture(autouse=True)
    def _fast_poll(self, monkeypatch):
        monkeypatch.setattr(logs, "POLL_SECONDS", 0.01)
        monkeypatch.setattr(logs, "HEARTBEAT_SECONDS", 0.02)

    async def test_sends_backlog_then_ready(self, monkeypatch):
        monkeypatch.setattr(
            logs, "_read_backlog", lambda limit: ([_query_payload(1), _token_payload(2)], 1, 2)
        )
        monkeypatch.setattr(logs, "_read_since", lambda q, t: ([], q, t))

        events = _events(await _collect())

        assert [name for name, _ in events] == ["query", "token", "ready"]
        assert events[-1][1]["backlog"] == 2

    async def test_headers_defeat_buffering(self):
        """Without these an intermediary batches the stream and it looks stalled.

        Read off the response object rather than by consuming it: the headers are
        set before the first frame, so this needs no traffic and cannot hang.
        """

        class _Disconnected:
            async def is_disconnected(self):
                return True

        response = await logs.stream(_Disconnected(), backlog=0)

        assert response.media_type == "text/event-stream"
        assert response.headers["x-accel-buffering"] == "no"
        assert "no-cache" in response.headers["cache-control"]

    async def test_frames_are_typed_so_a_client_can_filter(self, monkeypatch):
        monkeypatch.setattr(
            logs, "_read_backlog", lambda limit: ([_query_payload(1), _token_payload(2)], 1, 2)
        )
        monkeypatch.setattr(logs, "_read_since", lambda q, t: ([], q, t))

        frames = await _collect()
        assert any(f.startswith("event: query") for f in frames)
        assert any(f.startswith("event: token") for f in frames)

    async def test_heartbeat_when_nothing_is_logged(self, monkeypatch):
        """A silent stream is indistinguishable from a dead one to an intermediary."""
        monkeypatch.setattr(logs, "_read_backlog", lambda limit: ([], 0, 0))
        monkeypatch.setattr(logs, "_read_since", lambda q, t: ([], q, t))

        frames = await _collect(stop_after="heartbeat")
        assert any(f.startswith("event: heartbeat") for f in frames)

    async def test_new_rows_arrive_after_ready(self, monkeypatch):
        monkeypatch.setattr(logs, "_read_backlog", lambda limit: ([], 0, 0))
        delivered = {"done": False}

        def _since(last_query, last_token):
            if delivered["done"]:
                return ([], last_query, last_token)
            delivered["done"] = True
            return ([_query_payload(7, text="a later query")], 7, last_token)

        monkeypatch.setattr(logs, "_read_since", _since)

        frames = await _collect(stop_after="query")
        payloads = [payload for name, payload in _events(frames) if name == "query"]

        assert payloads and payloads[0]["id"] == 7

    async def test_the_high_water_mark_advances(self, monkeypatch):
        """Otherwise every poll replays every row seen so far."""
        monkeypatch.setattr(logs, "_read_backlog", lambda limit: ([], 5, 9))
        seen: list[tuple[int, int]] = []

        def _since(last_query, last_token):
            seen.append((last_query, last_token))
            if len(seen) == 1:
                return ([_query_payload(6)], 6, 9)
            return ([], last_query, last_token)

        monkeypatch.setattr(logs, "_read_since", _since)
        await _collect(stop_after="heartbeat")

        assert seen[0] == (5, 9)
        assert seen[1] == (6, 9)

    async def test_a_dead_database_reports_in_band(self, monkeypatch):
        """Not a 500: the response has already begun, so the only honest place left
        to say so is inside the stream."""

        def _boom(limit):
            raise RuntimeError("postgres is unwell")

        monkeypatch.setattr(logs, "_read_backlog", _boom)

        events = _events(await _collect(stop_after="error"))
        assert events and events[0][0] == "error"


class TestSeparationFromTheGraph:
    def test_log_rows_are_not_graph_nodes(self):
        """The design decision this whole module rests on: ~39,500 log rows against
        a few dozen memories would bury the graph a thousand to one."""
        from brownbear import graph

        source = open(graph.__file__, encoding="utf-8").read()
        assert "QueryLog" not in source
        assert "TokenEvent" not in source
