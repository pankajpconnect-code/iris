"""Integration tests for the Iris server's Runner routes — PR4 (design §7.2).
Starts a real LocalThreadingHTTPServer against tmp_path-isolated stores, and
a separate fake_server as the "external API" the orchestrator calls out to.
"""

import base64
import json
import threading
import time

import pytest
import requests

import collection_store
import environment_store
import native_pickers
import server


@pytest.fixture
def iris(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "COLLECTION_STORE", collection_store.CollectionStore(str(tmp_path / "collections")))
    monkeypatch.setattr(server, "ENVIRONMENT_STORE", environment_store.EnvironmentStore(str(tmp_path / "environments")))
    monkeypatch.setattr(server, "RUNS_DIR", str(tmp_path / "runs"))
    # LocalThreadingHTTPServer.server_bind() doesn't re-read the OS-assigned
    # port after binding (pre-existing behavior, out of scope here) — pick a
    # free port ourselves first, same as main() does, instead of passing 0.
    port = server._find_free_port(15080)
    httpd = server.LocalThreadingHTTPServer(("127.0.0.1", port), server.IrisRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", server.COLLECTION_STORE
    httpd.shutdown()
    httpd.server_close()


def _save_request(store, slug, name, method, url, tests=None):
    store.create(slug)
    store.save_request(slug, {
        "name": name, "method": method, "url": url,
        "headers": [], "body": "", "tests": tests or [],
    })


def _read_ndjson(response):
    events = []
    for line in response.iter_lines(decode_unicode=True):
        if line:
            events.append(json.loads(line))
    return events


def test_run_stream_happy_path_streams_events_and_persists_history(iris, fake_server):
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    spec = {"runId": "run-http-1", "scope": {"type": "request", "slug": "c", "name": "A"}}
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200
    events = _read_ndjson(resp)

    assert events[0]["type"] == "run_started"
    assert events[-1]["type"] == "summary"
    assert events[-1]["ok"] == 1

    history = requests.get(f"{base_url}/api/runs/run-http-1", timeout=5).json()
    assert history["status"] == "COMPLETED"
    assert history["summary"]["ok"] == 1


def test_run_stream_with_csv_resolves_environment_var_placeholder_first(iris, fake_server, tmp_path):
    """A request URL commonly mixes an environment var ({{url}}, the base
    host) with a CSV-row placeholder ({{loanId}}) — validating raw,
    unresolved placeholders against the CSV header flags {{url}} as a
    'missing' column even though it resolves fine from the environment."""
    base_url, store = iris
    fake_server.set_responses("/api/loanaccount/9", [{"status": 200, "body": "{}"}])
    store.create("c")
    store.save_request("c", {
        "name": "Get Loan", "method": "GET",
        "url": "{{url}}/api/loanaccount/{{loanId}}",
        "headers": [], "body": "", "tests": [],
    })
    env_store = server.ENVIRONMENT_STORE
    env_slug = env_store.create("Dev Playground")
    env_store.set_vars(env_slug, {"url": fake_server.url("")})

    csv_path = tmp_path / "loanid.csv"
    csv_path.write_text("loanId\n9\n")
    spec = {
        "runId": "run-envvar-1",
        "scope": {"type": "request", "slug": "c", "name": "Get Loan"},
        "environmentSlug": env_slug,
        "csvPath": str(csv_path),
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200
    events = _read_ndjson(resp)
    assert events[-1]["type"] == "summary"
    assert events[-1]["ok"] == 1


def test_run_stream_flags_missing_csv_column_referenced_only_in_body_params(iris, fake_server, tmp_path):
    """A urlencoded body param can reference a {{col}} placeholder same as
    the URL or raw body can — the CSV pre-flight check must catch a typo'd
    column name there too, not just in url/body, or it silently sends a
    literal {{col}} in every row."""
    base_url, store = iris
    store.create("c")
    store.save_request("c", {
        "name": "Post Form", "method": "POST", "url": fake_server.url("/a"),
        "headers": [], "body": "", "tests": [],
        "bodyMode": "urlencoded",
        "bodyParams": [{"key": "loanId", "value": "{{missingCol}}", "enabled": True}],
    })

    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("otherCol\n1\n")
    spec = {
        "runId": "run-bodyparam-missing-col",
        "scope": {"type": "request", "slug": "c", "name": "Post Form"},
        "csvPath": str(csv_path),
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, timeout=10)
    assert resp.status_code == 400
    assert "missingCol" in resp.json()["error"]


def test_run_stream_ignores_stale_raw_body_placeholder_in_urlencoded_mode(iris, fake_server, tmp_path):
    """The raw `body` field is retained (not cleared) when a request is
    switched to urlencoded mode, in case the user switches back — but it is
    never actually sent in that mode. The CSV pre-flight check must not scan
    it, or a stale {{col}} left over in the unused raw body would hard-fail
    a run for content that will never go over the wire."""
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    store.create("c")
    store.save_request("c", {
        "name": "Post Form", "method": "POST", "url": fake_server.url("/a"),
        "headers": [], "body": "{{staleColNotInCsv}}", "tests": [],
        "bodyMode": "urlencoded",
        "bodyParams": [{"key": "loanId", "value": "1", "enabled": True}],
    })

    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("otherCol\n1\n")
    spec = {
        "runId": "run-stale-raw-body-ignored",
        "scope": {"type": "request", "slug": "c", "name": "Post Form"},
        "csvPath": str(csv_path),
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200


def test_run_stream_translates_flat_auth_fields_to_bearer_header(iris, fake_server):
    """The wire payload's auth fields are flat (authMode/bearerToken/...) —
    request-tabs.js's authPayloadFields() shape, off limits per §3 — server.py
    must translate that into the nested auth dict _apply_auth expects."""
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    spec = {
        "runId": "run-http-auth", "scope": {"type": "request", "slug": "c", "name": "A"},
        "authMode": "bearer", "bearerToken": "secret-token-value",
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200
    _read_ndjson(resp)

    sent = next(r for r in fake_server.requests if r["path"] == "/a")
    assert sent["headers"]["Authorization"] == "Bearer secret-token-value"


def test_run_stream_translates_flat_basic_auth_fields_to_authorization_header(iris, fake_server):
    """Same translation as the bearer case above, for Basic Auth — covers the
    full round trip: server.py's _auth_spec_from_flat must forward
    basicUser/basicPassword into the nested auth dict, and
    run_auth.TokenCache.auth_for_send() must recognize mode "basic" instead
    of silently downgrading it to "none"."""
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    spec = {
        "runId": "run-http-basic-auth", "scope": {"type": "request", "slug": "c", "name": "A"},
        "authMode": "basic", "basicUser": "svc-account", "basicPassword": "hunter2",
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200
    _read_ndjson(resp)

    sent = next(r for r in fake_server.requests if r["path"] == "/a")
    expected = "Basic " + base64.b64encode(b"svc-account:hunter2").decode()
    assert sent["headers"]["Authorization"] == expected


def test_run_stream_translates_flat_apikey_auth_fields_to_header(iris, fake_server):
    """Same round trip as the basic-auth case above, for API Key auth: the
    single-Send path (collection_routes._apply_auth) already supported
    apikey, but the Runner path goes through run_auth.TokenCache.auth_for_send()
    instead, which had no apikey case and silently downgraded it to "none" —
    every row in a CSV batch run would go out unauthenticated with no error."""
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    spec = {
        "runId": "run-http-apikey-auth", "scope": {"type": "request", "slug": "c", "name": "A"},
        "authMode": "apikey", "apiKeyName": "X-Api-Key", "apiKeyValue": "s3cret",
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200
    _read_ndjson(resp)

    sent = next(r for r in fake_server.requests if r["path"] == "/a")
    assert sent["headers"]["X-Api-Key"] == "s3cret"


def test_run_stream_translates_flat_refresh_token_cookie_name(iris, fake_server):
    """refreshTokenCookieName lives inside the nested auth dict on the
    backend (run_auth.py) but arrives flat on the wire like every other
    auth field — server.py's _auth_spec_from_flat must forward it too."""
    base_url, store = iris
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}])
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    spec = {
        "runId": "run-http-cookie-name", "scope": {"type": "request", "slug": "c", "name": "A"},
        "authMode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
        "refreshToken": "x=r", "tenant": "t", "refreshTokenCookieName": "custom.cookie.name",
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200
    _read_ndjson(resp)

    token_request = next(r for r in fake_server.requests if r["path"] == "/token")
    assert token_request["headers"]["Cookie"].startswith("custom.cookie.name=")


def test_run_stream_invalid_run_id_returns_400_before_streaming(iris, fake_server):
    """runId must be validated BEFORE the 200 + ndjson headers are sent —
    RunRecorder.__init__ raising InvalidRunId after that point would try to
    send a second HTTP status line onto the same connection, corrupting the
    response (run_history_store.RUN_ID_RE only allows [A-Za-z0-9._-]{1,64})."""
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    spec = {"runId": "bad run id!", "scope": {"type": "request", "slug": "c", "name": "A"}}
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, timeout=5)
    assert resp.status_code == 400


def test_run_stream_unknown_scope_returns_404_before_streaming(iris, fake_server):
    base_url, store = iris
    store.create("c")
    spec = {"scope": {"type": "request", "slug": "c", "name": "Nope"}}
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, timeout=5)
    assert resp.status_code == 404


def test_run_preview_returns_resolved_requests_and_capped_flag(iris, fake_server, tmp_path):
    base_url, store = iris
    _save_request(store, "c", "A", "GET", fake_server.url("/loans/{{loanId}}"))
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("loanId\n1\n2\n3\n4\n5\n6\n")

    spec = {"scope": {"type": "request", "slug": "c", "name": "A"}, "csvPath": str(csv_path)}
    resp = requests.post(f"{base_url}/api/run-preview", json=spec, timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalIterations"] == 6
    assert body["capped"] is True
    assert len(body["iterations"]) == 5
    assert body["iterations"][0][0]["url"].endswith("/loans/1")


def test_run_preview_shows_urlencoded_body_params_not_a_blank_body(iris, tmp_path):
    """The preview builder read request.get("body") directly, which is
    irrelevant for a urlencoded-mode request — the actual run (_send_one)
    sends the form-encoded params, so Preview must show them too instead of
    misrepresenting the request as having no body."""
    base_url, store = iris
    store.create("c")
    store.save_request("c", {
        "name": "Post Form", "method": "POST", "url": "http://example.invalid/token",
        "headers": [], "body": "", "tests": [],
        "bodyMode": "urlencoded",
        "bodyParams": [{"key": "grant_type", "value": "client_credentials", "enabled": True}],
    })

    spec = {"scope": {"type": "request", "slug": "c", "name": "Post Form"}}
    resp = requests.post(f"{base_url}/api/run-preview", json=spec, timeout=5)
    assert resp.status_code == 200
    step = resp.json()["iterations"][0][0]
    assert "grant_type" in step["body"]
    assert "client_credentials" in step["body"]


def test_run_preview_flags_unresolved_captured_var_referenced_only_in_a_body_param(iris, tmp_path):
    """A {{var}} captured by an earlier step and referenced only inside a
    urlencoded body param must get the same "resolved at run time" preview
    annotation a URL/raw-body reference already gets — previously the scan
    only checked request["url"]/request["body"], missing bodyParams."""
    base_url, store = iris
    store.create("c")
    store.save_request("c", {
        "name": "Login", "method": "POST", "url": "http://example.invalid/login",
        "headers": [], "body": "", "tests": [
            {"type": "capture", "source": "body", "path": "accessToken", "variable": "token"},
        ],
    })
    store.save_request("c", {
        "name": "Use Token", "method": "POST", "url": "http://example.invalid/a",
        "headers": [], "body": "", "tests": [],
        "bodyMode": "urlencoded",
        "bodyParams": [{"key": "auth", "value": "{{token}}", "enabled": True}],
    })

    spec = {"scope": {"type": "collection", "slug": "c"}}
    resp = requests.post(f"{base_url}/api/run-preview", json=spec, timeout=5)
    assert resp.status_code == 200
    steps = resp.json()["iterations"][0]
    use_token_step = next(s for s in steps if s["requestName"] == "Use Token")
    assert "token" in use_token_step["unresolvedVars"]


def test_run_preview_excludes_disabled_query_param_from_step_url(iris, fake_server):
    """Preview must not show a param that Run itself would never actually
    send — same helper collection_routes._send_one uses (test_query_params.py)."""
    base_url, store = iris
    _save_request(store, "c", "A", "GET", fake_server.url("/a") + "?keep=1&~drop=2")

    spec = {"scope": {"type": "request", "slug": "c", "name": "A"}}
    resp = requests.post(f"{base_url}/api/run-preview", json=spec, timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert body["iterations"][0][0]["url"] == fake_server.url("/a") + "?keep=1"


def test_get_run_rejects_path_traversal_run_id(iris):
    base_url, _ = iris
    resp = requests.get(f"{base_url}/api/runs/..%2F..%2Fetc%2Fpasswd", timeout=5)
    assert resp.status_code == 400


def test_get_run_unknown_id_returns_404(iris):
    base_url, _ = iris
    resp = requests.get(f"{base_url}/api/runs/does-not-exist", timeout=5)
    assert resp.status_code == 404


def test_list_runs_returns_completed_run(iris, fake_server):
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))
    spec = {"runId": "run-list-1", "scope": {"type": "request", "slug": "c", "name": "A"}}
    requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10).close()

    resp = requests.get(f"{base_url}/api/runs", timeout=5)
    assert resp.status_code == 200
    run_ids = [r["runId"] for r in resp.json()["runs"]]
    assert "run-list-1" in run_ids


def test_export_run_returns_csv_attachment(iris, fake_server):
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))
    spec = {"runId": "run-export-1", "scope": {"type": "request", "slug": "c", "name": "A"}}
    _read_ndjson(requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10))

    resp = requests.get(f"{base_url}/api/runs/run-export-1/export", timeout=5)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in resp.headers["Content-Disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0].split(",")[:3] == ["iteration", "step", "requestName"]
    assert len(lines) == 2


def test_clear_all_history_removes_runs(iris, fake_server):
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))
    spec = {"runId": "run-clear-1", "scope": {"type": "request", "slug": "c", "name": "A"}}
    _read_ndjson(requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10))

    resp = requests.delete(f"{base_url}/api/runs", timeout=5)
    assert resp.status_code == 200
    assert requests.get(f"{base_url}/api/runs", timeout=5).json()["runs"] == []


def test_stop_run_cancels_an_in_flight_run(iris, fake_server):
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 10)
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))
    spec = {
        "runId": "run-stop-1", "scope": {"type": "request", "slug": "c", "name": "A"},
        "iterations": 10, "delay": 0.3,
    }

    def _stop_soon():
        time.sleep(0.2)
        requests.post(f"{base_url}/api/stop-run", json={"runId": "run-stop-1"}, timeout=5)

    threading.Thread(target=_stop_soon, daemon=True).start()
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=15)
    events = _read_ndjson(resp)
    summary = events[-1]
    assert summary["exitCode"] == 130
    assert summary["status"] == "STOPPED"
    assert len([e for e in events if e["type"] == "result"]) < 10


def test_run_stream_disconnect_records_real_counts_not_zeros(iris, fake_server):
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 6)
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))
    spec = {
        "runId": "run-disconnect-1", "scope": {"type": "request", "slug": "c", "name": "A"},
        "iterations": 6, "delay": 0.3,
    }

    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=15)
    seen_results = 0
    for line in resp.iter_lines(decode_unicode=True):
        if line and json.loads(line)["type"] == "result":
            seen_results += 1
        if seen_results >= 2:
            break
    resp.close()
    assert seen_results >= 1

    deadline = time.monotonic() + 5
    history = None
    while time.monotonic() < deadline:
        history = requests.get(f"{base_url}/api/runs/run-disconnect-1", timeout=5).json()
        if history["status"] != "RUNNING":
            break
        time.sleep(0.1)

    assert history["status"] == "STOPPED"
    # The server keeps processing rows until its next write hits the closed
    # socket, so it may run ahead of what the client observed before
    # disconnecting — assert real, non-zero counts rather than an exact
    # match to the client's read position.
    assert seen_results <= history["summary"]["ok"] < 6
    assert history["summary"]["retryCsv"] is None


def test_run_stream_escaped_exception_records_real_counts_plus_error(iris, fake_server, monkeypatch):
    base_url, store = iris
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 3)
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    original_execute = server.run_orchestrator.execute

    def _boom(*args, **kwargs):
        for i, event in enumerate(original_execute(*args, **kwargs)):
            yield event
            if event.get("type") == "result" and i >= 1:
                raise RuntimeError("boom")

    monkeypatch.setattr(server.run_orchestrator, "execute", _boom)

    spec = {
        "runId": "run-error-1", "scope": {"type": "request", "slug": "c", "name": "A"},
        "iterations": 3,
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    events = _read_ndjson(resp)
    summary = events[-1]
    assert summary["type"] == "summary"
    assert summary["status"] == "ERROR"
    assert summary["ok"] == 1
    assert "boom" in summary["error"]


def test_choose_csv_returns_cancelled_flag_not_an_error_when_user_dismisses_picker(iris, monkeypatch):
    base_url, _store = iris

    def _raise_cancelled():
        raise native_pickers.PickerCancelled()

    monkeypatch.setattr(native_pickers, "choose_csv_file", _raise_cancelled)
    resp = requests.get(f"{base_url}/api/choose-csv", timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}


def test_run_stream_oauth2_client_credentials_remints_on_401(iris, fake_server):
    """A 401 on the main API must trigger a re-mint for OAuth2 mode too —
    not just refresh-cookie mode. Guards against run_orchestrator's retry
    gate keying off the refresh-cookie-only `tokenUrl` field."""
    base_url, store = iris
    fake_server.set_responses("/token", [
        {"status": 200, "body": '{"access_token":"first-token"}'},
        {"status": 200, "body": '{"access_token":"second-token"}'},
    ])
    fake_server.set_responses("/a", [
        {"status": 401, "body": "{}"},
        {"status": 200, "body": "{}"},
    ])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    spec = {
        "runId": "run-http-oauth2-remint", "scope": {"type": "request", "slug": "c", "name": "A"},
        "authMode": "oauth2-client-credentials",
        "oauth2ClientId": "cid", "oauth2ClientSecret": "csecret",
        "oauth2TokenUrl": fake_server.url("/token"), "oauth2AuthStyle": "basic-header",
        "authRetryStatuses": [401],
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200
    events = _read_ndjson(resp)
    assert events[-1]["type"] == "summary"
    assert events[-1]["ok"] == 1

    token_requests = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(token_requests) == 2


def test_run_stream_translates_flat_oauth2_fields(iris, fake_server):
    """oauth2* fields arrive flat on the wire (authPayloadFields() shape) —
    _auth_spec_from_flat must forward all five into the nested auth dict,
    same as every other auth mode's fields."""
    base_url, store = iris
    fake_server.set_responses("/token", [{"status": 200, "body": '{"access_token":"minted-tok"}'}])
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    _save_request(store, "c", "A", "GET", fake_server.url("/a"))

    spec = {
        "runId": "run-http-oauth2-fields", "scope": {"type": "request", "slug": "c", "name": "A"},
        "authMode": "oauth2-client-credentials",
        "oauth2ClientId": "cid", "oauth2ClientSecret": "csecret",
        "oauth2TokenUrl": fake_server.url("/token"), "oauth2Scope": "read",
        "oauth2AuthStyle": "post-body",
    }
    resp = requests.post(f"{base_url}/api/run-stream", json=spec, stream=True, timeout=10)
    assert resp.status_code == 200
    _read_ndjson(resp)

    sent = next(r for r in fake_server.requests if r["path"] == "/a")
    assert sent["headers"]["Authorization"] == "Bearer minted-tok"
    token_req = next(r for r in fake_server.requests if r["path"] == "/token")
    assert "client_id=cid" in token_req["body"]
