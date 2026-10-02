"""Tests for collection_routes._send_one's body-mode serialization
(_outgoing_body_and_content_type) and the inline-request path's
bodyMode/bodyParams handling.

Split out of test_send_one_seams.py (not merged into it) to keep that file
under the 500-line limit — it was already at 327 lines before this feature,
and these tests alone would have pushed it to 535.
"""

import pytest

import collection_store


def _fake_response():
    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    return _FakeResponse()


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


def test_send_one_inline_request_carries_body_mode_and_params(store, monkeypatch):
    """An unsaved (inline) request sent from the Console must carry
    bodyMode/bodyParams through to the outgoing call, same as a saved one."""
    import collection_routes

    seen = {}

    def _fake_request(method, url, headers=None, data=None, **kwargs):
        seen["headers"] = headers
        seen["data"] = data
        return _fake_response()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {
            "request": {
                "method": "POST", "url": "http://example.invalid/token",
                "headers": [], "body": "", "tests": [],
                "bodyMode": "urlencoded",
                "bodyParams": [{"key": "grant_type", "value": "client_credentials", "enabled": True}],
            },
            "auth": {"mode": "none"},
        },
        None,
    )
    assert status == 200
    assert seen["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert seen["data"] == b"grant_type=client_credentials"


def test_send_one_inline_request_drops_malformed_body_params_instead_of_crashing(store, monkeypatch):
    """The inline (unsaved) send path never filters bodyParams the way
    _save_request does for a saved request — a malformed entry (missing
    'key', or not a dict at all) must be dropped, not raise a raw
    KeyError/TypeError out of resolve_request."""
    import collection_routes

    monkeypatch.setattr(collection_routes.requests, "request", lambda *a, **k: _fake_response())

    status, result = collection_routes._send_one(
        store,
        {
            "request": {
                "method": "POST", "url": "http://example.invalid/token",
                "headers": [], "body": "", "tests": [],
                "bodyMode": "urlencoded",
                "bodyParams": [{"value": "no-key"}, "not-a-dict", {"key": "ok", "value": "1"}],
            },
            "auth": {"mode": "none"},
        },
        None,
    )
    assert status == 200


def test_send_one_urlencoded_body_mode_encodes_params_and_sets_content_type(store, monkeypatch):
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Post Form", "method": "POST", "url": "http://example.invalid/token",
        "headers": [], "body": "", "tests": [],
        "bodyMode": "urlencoded",
        "bodyParams": [
            {"key": "grant_type", "value": "client_credentials", "enabled": True},
            {"key": "scope", "value": "read write", "enabled": True},
            {"key": "disabled_one", "value": "x", "enabled": False},
        ],
    })

    seen = {}

    def _fake_request(method, url, headers=None, data=None, **kwargs):
        seen["headers"] = headers
        seen["data"] = data
        return _fake_response()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store, {"slug": "c", "requestName": "Post Form", "auth": {"mode": "none"}}, None
    )
    assert status == 200
    assert seen["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    # "scope=read write" URL-escapes the space; the disabled param is excluded.
    assert seen["data"] == b"grant_type=client_credentials&scope=read+write"


def test_send_one_urlencoded_body_mode_does_not_override_explicit_content_type(store, monkeypatch):
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Post Form", "method": "POST", "url": "http://example.invalid/token",
        "headers": [{"key": "Content-Type", "value": "application/custom", "enabled": True}],
        "body": "", "tests": [],
        "bodyMode": "urlencoded",
        "bodyParams": [{"key": "a", "value": "1", "enabled": True}],
    })

    seen = {}

    def _fake_request(method, url, headers=None, **kwargs):
        seen["headers"] = headers
        return _fake_response()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store, {"slug": "c", "requestName": "Post Form", "auth": {"mode": "none"}}, None
    )
    assert status == 200
    assert seen["headers"]["Content-Type"] == "application/custom"


def test_send_one_urlencoded_body_mode_with_no_enabled_params_sends_no_body(store, monkeypatch):
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Post Form", "method": "POST", "url": "http://example.invalid/token",
        "headers": [], "body": "", "tests": [],
        "bodyMode": "urlencoded", "bodyParams": [],
    })

    seen = {}

    def _fake_request(method, url, headers=None, data=None, **kwargs):
        seen["headers"] = headers
        seen["data"] = data
        return _fake_response()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store, {"slug": "c", "requestName": "Post Form", "auth": {"mode": "none"}}, None
    )
    assert status == 200
    assert seen["data"] is None
    assert "Content-Type" not in seen["headers"]


def test_send_one_raw_body_mode_is_unchanged(store, monkeypatch):
    """Regression guard: raw mode (bodyMode absent, the pre-existing shape)
    must serialize byte-for-byte as it did before this feature."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Post Json", "method": "POST", "url": "http://example.invalid/a",
        "headers": [], "body": '{"a": 1}', "tests": [],
    })

    seen = {}

    def _fake_request(method, url, headers=None, data=None, **kwargs):
        seen["headers"] = headers
        seen["data"] = data
        return _fake_response()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store, {"slug": "c", "requestName": "Post Json", "auth": {"mode": "none"}}, None
    )
    assert status == 200
    assert seen["data"] == b'{"a": 1}'
    assert "Content-Type" not in seen["headers"]
