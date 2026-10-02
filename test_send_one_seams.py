"""Tests for the Runner-orchestration seams on collection_routes._send_one:
extra_vars, capture_sink, errorType, extra_headers. See docs/superpowers/specs
(local, PR1 §3.1 for E1-E3; PR3 for E4 — the `User` header CLI-parity gap that
has no seam via extra_vars/auth, §5.1 row 7 and §8.3).

Split out of test_console.py to keep that file under the 500-line limit.
"""

import pytest

import collection_store
import environment_store


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


def test_send_one_extra_vars_resolve_in_url(store, monkeypatch):
    """The Runner needs to inject a CSV row (or an earlier capture) into a
    request with no seam for it today — extra_vars is that seam."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/{{loanId}}",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, **kwargs):
        seen["url"] = url
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {"slug": "c", "requestName": "Get Loan", "auth": {"mode": "none"}},
        None,
        extra_vars={"loanId": "9"},
    )
    assert status == 200
    assert seen["url"] == "http://example.invalid/loans/9"


def test_send_one_capture_sink_populates_dict_and_leaves_env_untouched(store, tmp_path, monkeypatch):
    """The Runner must not do 500 read-modify-writes on the shared environment
    file for a CSV run — capture_sink redirects captures into a plain dict."""
    import collection_routes

    env_store = environment_store.EnvironmentStore(str(tmp_path / "environments"))
    env_slug = env_store.create("Dev")
    store.create("C")
    store.save_request("c", {
        "name": "Login",
        "method": "POST",
        "url": "http://example.invalid/login",
        "headers": [],
        "body": "",
        "tests": [{"type": "capture", "source": "body", "path": "accessToken", "variable": "token"}],
    })

    class _FakeResponse:
        status_code = 200
        content = b'{"accessToken": "eyJ-captured"}'
        text = '{"accessToken": "eyJ-captured"}'
        headers = {}

    monkeypatch.setattr(collection_routes.requests, "request", lambda *a, **k: _FakeResponse())

    sink = {}
    status, result = collection_routes._send_one(
        store,
        {"slug": "c", "requestName": "Login", "environmentSlug": env_slug, "auth": {"mode": "none"}},
        env_store,
        capture_sink=sink,
    )
    assert status == 200
    assert sink["token"] == "eyJ-captured"
    assert "token" not in env_store.get_vars(env_slug)


def test_send_one_extra_vars_reach_assertion_expected_substitution(store, monkeypatch):
    """extra_vars must be folded into the same `variables` dict handed to
    run_assertions, not just the resolver — otherwise CSV/captured values
    resolve in the URL but stay literal `{{loanId}}` inside `expected`."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/9",
        "headers": [],
        "body": "",
        "tests": [{"type": "assert", "source": "body", "path": "loanId", "operator": "equals", "expected": "{{loanId}}"}],
    })

    class _FakeResponse:
        status_code = 200
        content = b'{"loanId": "9"}'
        text = '{"loanId": "9"}'
        headers = {}

    monkeypatch.setattr(collection_routes.requests, "request", lambda *a, **k: _FakeResponse())

    status, result = collection_routes._send_one(
        store,
        {"slug": "c", "requestName": "Get Loan", "auth": {"mode": "none"}},
        None,
        extra_vars={"loanId": "9"},
    )
    assert status == 200
    assert result["tests"][0]["passed"] is True


def test_send_one_timeout_reports_errortype_for_orchestrator_classification(store, monkeypatch):
    """The Runner needs `requests.Timeout` classified as FLAGGED and every
    other transport error as ERROR — both are flattened to one 502 today with
    no way to tell them apart."""
    import collection_routes
    import requests

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    def _fake_request(*a, **k):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store, {"slug": "c", "requestName": "Get Loan", "auth": {"mode": "none"}}, None
    )
    assert status == 502
    assert result["errorType"] == "Timeout"


def test_send_one_extra_headers_are_added_to_the_outgoing_request(store, monkeypatch):
    """The orchestrator needs to add a literal `User: <name>` header per send
    (CLI parity, run_api_from_csv.py:68) — _apply_auth ignores `user` entirely
    and no saved request pre-authors this header, so extra_headers is the seam."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, headers=None, **kwargs):
        seen["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {"slug": "c", "requestName": "Get Loan", "auth": {"mode": "none"}},
        None,
        extra_headers={"User": "pankaj.pandey"},
    )
    assert status == 200
    assert seen["headers"]["User"] == "pankaj.pandey"


def test_send_one_with_no_proxy_field_passes_proxies_none(store, monkeypatch):
    """Non-regression pin (ROADMAP §10 Phase 1): a payload with no `proxy`
    field must keep calling requests.request with proxies=None, exactly
    today's behaviour, once the proxy-set path below is added."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, proxies=None, **kwargs):
        seen["proxies"] = proxies
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {"slug": "c", "requestName": "Get Loan", "auth": {"mode": "none"}},
        None,
    )
    assert status == 200
    assert seen["proxies"] is None


def test_send_one_with_proxy_field_passes_proxies_dict(store, monkeypatch):
    """Nucleus Capture Tool parity (ROADMAP §10 Phase 1): proxySettings in
    the payload must route the request through that proxy for both
    http:// and https:// traffic, matching mitmdump's single-listener setup."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, proxies=None, **kwargs):
        seen["proxies"] = proxies
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {
            "slug": "c", "requestName": "Get Loan", "auth": {"mode": "none"},
            "proxySettings": {"mode": "custom", "url": "http://127.0.0.1:8080", "username": "", "password": "", "bypassList": []},
        },
        None,
    )
    assert status == 200
    assert seen["proxies"] == {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}


def test_send_one_basic_auth_sets_base64_authorization_header(store, monkeypatch):
    """Basic Auth mode encodes user:password into a standard `Authorization:
    Basic <base64>` header, matching Fineract's non-OAuth tenants — the other
    two modes (bearer, refresh-cookie) already had this seam covered; basic
    had none."""
    import base64

    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, headers=None, **kwargs):
        seen["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {
            "slug": "c",
            "requestName": "Get Loan",
            "auth": {"mode": "basic", "basicUser": "pankaj", "basicPassword": "s3cret"},
        },
        None,
    )
    assert status == 200
    expected = "Basic " + base64.b64encode(b"pankaj:s3cret").decode()
    assert seen["headers"]["Authorization"] == expected


def test_send_one_basic_auth_also_sets_the_tenant_header(store, monkeypatch):
    """The tenant var is shared across auth modes and already reaches
    x-tenant-identifier for bearer and refresh-cookie — the basic branch
    returned early right after setting Authorization, before ever touching
    it, so a multi-tenant Fineract instance rejected Basic Auth requests
    that worked fine under the other two modes with the same tenant."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, headers=None, **kwargs):
        seen["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {
            "slug": "c",
            "requestName": "Get Loan",
            "auth": {
                "mode": "basic", "basicUser": "pankaj", "basicPassword": "s3cret", "tenant": "acme",
            },
        },
        None,
    )
    assert status == 200
    assert seen["headers"]["x-tenant-identifier"] == "acme"


def test_send_one_basic_auth_with_no_username_sets_no_authorization_header(store, monkeypatch):
    """An empty/unconfigured Basic Auth mode must not send a bogus
    `Authorization: Basic <base64 of ':'>`  header — same "only set it if
    there's something to set" convention bearer mode already follows."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, headers=None, **kwargs):
        seen["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store, {"slug": "c", "requestName": "Get Loan", "auth": {"mode": "basic"}}, None
    )
    assert status == 200
    assert "Authorization" not in seen["headers"]


def test_send_one_apikey_auth_defaults_to_header_location(store, monkeypatch):
    """API Key auth is the only mode Fineract-adjacent third-party APIs
    commonly require that Iris had no auth-tab support for at all — header
    is the default location, matching the commercial clients' default."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, headers=None, **kwargs):
        seen["url"] = url
        seen["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {
            "slug": "c",
            "requestName": "Get Loan",
            "auth": {"mode": "apikey", "apiKeyName": "X-Api-Key", "apiKeyValue": "s3cret"},
        },
        None,
    )
    assert status == 200
    assert seen["headers"]["X-Api-Key"] == "s3cret"
    assert seen["url"] == "http://example.invalid/loans/1"


def test_send_one_apikey_auth_query_location_appends_to_url(store, monkeypatch):
    """apiKeyLocation: "query" must append the key as a query param instead
    of a header — some third-party APIs only accept the key that way."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "http://example.invalid/loans/1",
        "headers": [],
        "body": "",
        "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, headers=None, **kwargs):
        seen["url"] = url
        seen["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {
            "slug": "c",
            "requestName": "Get Loan",
            "auth": {
                "mode": "apikey", "apiKeyName": "api_key", "apiKeyValue": "s3cret",
                "apiKeyLocation": "query",
            },
        },
        None,
    )
    assert status == 200
    assert seen["url"] == "http://example.invalid/loans/1?api_key=s3cret"
    assert "api_key" not in seen["headers"]


def test_send_one_oauth2_client_credentials_sets_bearer_header(store, monkeypatch, fake_server):
    """OAuth2 Client Credentials mode mints a token from oauth2TokenUrl via
    oauth2_client_credentials.mint_client_credentials_token and applies it as
    a standard Authorization: Bearer header — same shape as bearer/basic/
    refresh-cookie above."""
    import collection_routes

    fake_server.set_responses("/token", [{"status": 200, "body": '{"access_token":"minted-token"}'}])
    store.create("C")
    store.save_request("c", {
        "name": "Get Loan", "method": "GET", "url": "http://example.invalid/loans/1",
        "headers": [], "body": "", "tests": [],
    })

    seen = {}

    class _FakeResponse:
        status_code = 200
        content = b"{}"
        text = "{}"
        headers = {}

    def _fake_request(method, url, headers=None, **kwargs):
        seen["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", _fake_request)

    status, result = collection_routes._send_one(
        store,
        {
            "slug": "c", "requestName": "Get Loan",
            "auth": {
                "mode": "oauth2-client-credentials",
                "oauth2ClientId": "cid",
                "oauth2ClientSecret": "csecret",
                "oauth2TokenUrl": fake_server.url("/token"),
                "oauth2AuthStyle": "basic-header",
            },
        },
        None,
    )
    assert status == 200
    assert seen["headers"]["Authorization"] == "Bearer minted-token"
