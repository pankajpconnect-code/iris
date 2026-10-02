"""Tests for the Params tab's backend support: stripping a disabled query
param (`~`-prefixed key, see static/query-params.js and the design doc at
docs/superpowers/specs/2026-09-14-query-params-tab-design.md) from a URL
before it reaches the wire or a display surface.
"""

import pytest

import collection_store
import collection_routes


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


def test_strip_disabled_query_params_no_query_string_is_unchanged():
    assert collection_routes._strip_disabled_query_params("http://x/y") == "http://x/y"


def test_strip_disabled_query_params_bare_trailing_question_mark_is_unchanged():
    assert collection_routes._strip_disabled_query_params("http://x/y?") == "http://x/y?"


def test_strip_disabled_query_params_nothing_disabled_is_unchanged():
    assert collection_routes._strip_disabled_query_params("http://x/y?a=1&b=2") == "http://x/y?a=1&b=2"


def test_strip_disabled_query_params_drops_one_disabled_param():
    assert collection_routes._strip_disabled_query_params("http://x/y?a=1&~b=2") == "http://x/y?a=1"


def test_strip_disabled_query_params_drops_a_disabled_param_in_the_middle():
    assert collection_routes._strip_disabled_query_params("http://x/y?~a=1&b=2&~c=3") == "http://x/y?b=2"


def test_strip_disabled_query_params_all_disabled_drops_the_question_mark_entirely():
    assert collection_routes._strip_disabled_query_params("http://x/y?~a=1&~b=2") == "http://x/y"


def test_strip_disabled_query_params_handles_a_valueless_disabled_param():
    assert collection_routes._strip_disabled_query_params("http://x/y?flag&~debug") == "http://x/y?flag"


def test_send_one_excludes_disabled_query_params_from_the_outgoing_url(store, fake_server):
    """A disabled Params-tab row must never reach the wire — the same job
    _send_one already does for a disabled header, via the real fake_server
    fixture (not a monkeypatched requests.request) so this proves what's
    actually sent, not just what's constructed."""
    store.create("C")
    store.save_request("c", {
        "name": "Get Loan", "method": "GET",
        "url": fake_server.url("/a") + "?keep=1&~drop=2",
        "headers": [], "body": "", "tests": [],
    })
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])

    status, result = collection_routes._send_one(
        store, {"slug": "c", "requestName": "Get Loan", "auth": {"mode": "none"}}, None,
    )
    assert status == 200
    assert fake_server.requests[0]["path"] == "/a?keep=1"


def test_run_stream_event_url_excludes_disabled_query_param(tmp_path, monkeypatch):
    """The Runner's per-row event `url` (what the result list/detail pane
    shows) must not show a param that was never actually sent — showing
    ~drop=2 there would actively mislead, not just look cosmetically odd."""
    import json
    import threading

    import requests

    import environment_store
    import server

    monkeypatch.setattr(server, "COLLECTION_STORE", collection_store.CollectionStore(str(tmp_path / "collections")))
    monkeypatch.setattr(server, "ENVIRONMENT_STORE", environment_store.EnvironmentStore(str(tmp_path / "environments")))
    monkeypatch.setattr(server, "RUNS_DIR", str(tmp_path / "runs"))
    port = server._find_free_port(15080)
    httpd = server.LocalThreadingHTTPServer(("127.0.0.1", port), server.IrisRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        run_store = server.COLLECTION_STORE
        run_store.create("c")
        run_store.save_request("c", {
            "name": "A", "method": "GET",
            # RFC 2606 reserved, guaranteed-unreachable host — no real
            # network call is made; the run legitimately fails to connect,
            # which is fine, since only the pre-send `url` field is checked.
            "url": "http://example.invalid/a?keep=1&~drop=2",
            "headers": [], "body": "", "tests": [],
        })
        spec = {"runId": "run-params-1", "scope": {"type": "request", "slug": "c", "name": "A"}}
        resp = requests.post(f"http://127.0.0.1:{port}/api/run-stream", json=spec, stream=True, timeout=10)
        events = [json.loads(line) for line in resp.iter_lines(decode_unicode=True) if line]
        result_events = [e for e in events if e["type"] == "result"]
        assert result_events[0]["url"] == "http://example.invalid/a?keep=1"
    finally:
        httpd.shutdown()
        httpd.server_close()
