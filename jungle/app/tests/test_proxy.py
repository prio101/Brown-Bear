"""Proxy behaviour: passthrough fidelity and token capture (spec 003 §3.1)."""

import json

import httpx

from brownbear.routers.ollama_proxy import MAX_CAPTURE_BYTES, TAIL_BYTES, extract_usage

STREAMING_BODY = (
    b'{"model":"llama3","message":{"content":"He"},"done":false}\n'
    b'{"model":"llama3","message":{"content":"llo"},"done":false}\n'
    b'{"model":"llama3","done":true,"prompt_eval_count":37,"eval_count":3}\n'
)

SINGLE_BODY = json.dumps(
    {"model": "llama3", "response": "hi", "done": True, "prompt_eval_count": 12, "eval_count": 5}
).encode()


class TestExtractUsage:
    def test_reads_final_line_of_stream(self):
        usage = extract_usage(STREAMING_BODY)
        assert usage["prompt_eval_count"] == 37
        assert usage["eval_count"] == 3

    def test_reads_single_object_response(self):
        usage = extract_usage(SINGLE_BODY)
        assert usage["prompt_eval_count"] == 12

    def test_returns_none_without_counts(self):
        assert extract_usage(b'{"model":"llama3","done":false}\n') is None

    def test_returns_none_for_empty_or_garbage(self):
        assert extract_usage(b"") is None
        assert extract_usage(b"not json at all") is None

    def test_survives_truncated_leading_data(self):
        """A trimmed capture starts mid-line; the final line must still parse."""
        truncated = b'del":"llama3","message":{"con\n' + STREAMING_BODY.splitlines()[-1]
        assert extract_usage(truncated)["eval_count"] == 3

    def test_tail_window_is_smaller_than_cap(self):
        assert TAIL_BYTES < MAX_CAPTURE_BYTES


class TestProxy:
    def test_streams_body_unchanged_and_records(self, client, mock_ollama, recorded):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/chat"
            # The caller's Host must not be forwarded; httpx sets the upstream one.
            assert request.headers["host"] == "ollama:11434"
            return httpx.Response(200, content=STREAMING_BODY)

        mock_ollama(handler)
        resp = client.post(
            "/ollama/api/chat",
            json={"model": "llama3", "messages": []},
            headers={"X-BB-Session-Id": "s1", "X-BB-User-Id": "u1"},
        )

        assert resp.status_code == 200
        assert resp.content == STREAMING_BODY, "proxy must not alter the body"
        assert len(recorded) == 1
        event = recorded[0]
        assert event["model"] == "llama3"
        assert event["tokens_in"] == 37
        assert event["tokens_out"] == 3
        assert event["endpoint"] == "api/chat"
        assert event["session_id"] == "s1"
        assert event["user_id"] == "u1"

    def test_falls_back_to_requested_model(self, client, mock_ollama, recorded):
        """Counts without a model name still attribute to the requested model."""
        body = b'{"done":true,"prompt_eval_count":9,"eval_count":1}\n'
        mock_ollama(lambda request: httpx.Response(200, content=body))

        client.post("/ollama/api/generate", json={"model": "mistral", "prompt": "x"})

        assert recorded[0]["model"] == "mistral"
        assert recorded[0]["tokens_in"] == 9

    def test_untracked_endpoint_is_not_recorded(self, client, mock_ollama, recorded):
        mock_ollama(lambda request: httpx.Response(200, json={"models": []}))

        resp = client.get("/ollama/api/tags")

        assert resp.status_code == 200
        assert recorded == []

    def test_upstream_error_is_not_recorded(self, client, mock_ollama, recorded):
        """A failed call cost no tokens; recording one would inflate usage."""
        mock_ollama(
            lambda request: httpx.Response(501, json={"error": "no embeddings"})
        )

        resp = client.post("/ollama/api/embed", json={"model": "llama3", "input": "x"})

        assert resp.status_code == 501
        assert recorded == []

    def test_missing_counts_do_not_record(self, client, mock_ollama, recorded):
        mock_ollama(
            lambda request: httpx.Response(200, content=b'{"model":"llama3"}\n')
        )

        client.post("/ollama/api/chat", json={"model": "llama3", "messages": []})

        assert recorded == []

    def test_unreachable_upstream_returns_502(self, client, mock_ollama, recorded):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        mock_ollama(handler)
        resp = client.post("/ollama/api/chat", json={"model": "llama3", "messages": []})

        assert resp.status_code == 502
        assert recorded == []

    def test_status_and_headers_propagate(self, client, mock_ollama, recorded):
        mock_ollama(
            lambda request: httpx.Response(
                404, json={"error": "model not found"}, headers={"X-Custom": "kept"}
            )
        )

        resp = client.post("/ollama/api/chat", json={"model": "ghost", "messages": []})

        assert resp.status_code == 404
        assert resp.headers["x-custom"] == "kept"
