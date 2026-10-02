"""Tests for run_orchestrator.execute() and TokenCache — PR3 of the Iris Runner
redesign (local design doc §5.1, §8, §9, §12.1.2). Headless: no route, no UI.
Driven against a real stdlib ThreadingHTTPServer fake (conftest.fake_server).
"""

import threading

import pytest

import collection_store
import environment_store
import run_auth
import run_orchestrator


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


@pytest.fixture
def env_store(tmp_path):
    return environment_store.EnvironmentStore(str(tmp_path / "environments"))


@pytest.fixture
def cancel_event():
    return threading.Event()


def _save(store, slug, name, method, path, tests=None, server=None):
    store.save_request(slug, {
        "name": name,
        "method": method,
        "url": (server.url(path) if server else f"http://example.invalid{path}"),
        "headers": [],
        "body": "",
        "tests": tests or [],
    })


def _events_by_type(events, event_type):
    return [e for e in events if e["type"] == event_type]


# --- TokenCache ---


def test_token_cache_get_mints_once_and_caches(fake_server):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok-1"}'}])
    cache = run_auth.TokenCache({
        "mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
        "refreshToken": "org.apache.fincn.refreshToken=r", "tenant": "t",
    })
    token1, epoch1 = cache.get()
    token2, epoch2 = cache.get()
    assert token1 == token2 == "tok-1"
    assert epoch1 == epoch2
    assert len(fake_server.requests) == 1


def test_token_cache_refresh_is_single_flight_across_stale_epoch(fake_server):
    fake_server.set_responses("/token", [
        {"status": 200, "body": '{"accessToken":"tok-1"}'},
        {"status": 200, "body": '{"accessToken":"tok-2"}'},
    ])
    cache = run_auth.TokenCache({
        "mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
        "refreshToken": "org.apache.fincn.refreshToken=r", "tenant": "t",
    })
    _, epoch0 = cache.get()
    token_a, epoch_a = cache.refresh(epoch0)
    # A second caller still holding the stale epoch0 must NOT mint again.
    token_b, epoch_b = cache.refresh(epoch0)
    assert token_a == token_b == "tok-2"
    assert epoch_a == epoch_b
    assert len(fake_server.requests) == 2


def test_token_cache_refresh_exhaustion_raises(fake_server):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}])
    cache = run_auth.TokenCache(
        {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"), "refreshToken": "x=r", "tenant": "t"},
        max_refreshes=1,
    )
    epoch = cache.get()[1]
    cache.refresh(epoch)  # consumes the one allowed refresh, epoch -> 1
    with pytest.raises(run_auth.TokenRefreshExhausted):
        cache.refresh(1)


def test_token_cache_mint_failure_wraps_systemexit(fake_server):
    fake_server.set_responses("/token", [{"status": 401, "body": "nope"}])
    cache = run_auth.TokenCache(
        {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"), "refreshToken": "x=r", "tenant": "t"}
    )
    with pytest.raises(run_auth.TokenMintFailed):
        cache.get()


# --- execute(): sequential happy path, chaining, capture reset ---


def test_execute_chains_capture_from_request_one_into_request_two(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/login", [{"status": 200, "body": '{"accessToken":"abc123"}'}])
    fake_server.set_responses("/loans", [{"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "Login", "POST", "/login", tests=[
        {"type": "capture", "source": "body", "path": "accessToken", "variable": "token"},
    ], server=fake_server)
    store.save_request(slug, {
        "name": "Get Loans", "method": "GET",
        "url": fake_server.url("/loans") + "?auth={{token}}",
        "headers": [], "body": "", "tests": [],
    })

    spec = {"scope": {"type": "collection", "slug": slug, "name": None}, "auth": {"mode": "none"}}
    events = list(run_orchestrator.execute("run-1", spec, store, env_store, cancel_event))

    results = _events_by_type(events, "result")
    assert results[1]["requestName"] == "Get Loans"
    loans_request = next(r for r in fake_server.requests if r["path"].startswith("/loans"))
    assert loans_request["path"] == "/loans?auth=abc123"


def test_execute_reset_captures_each_iteration_true_clears_between_iterations(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/loans", [
        {"status": 200, "body": '{"accessToken":"iter1"}'},
        {"status": 200, "body": '{"accessToken":"iter2"}'},
    ])
    slug = "c"
    store.create(slug)
    _save(store, slug, "Capture", "GET", "/loans", tests=[
        {"type": "capture", "source": "body", "path": "accessToken", "variable": "token"},
    ], server=fake_server)
    store.save_request(slug, {
        "name": "UseCaptured", "method": "GET",
        "url": fake_server.url("/echo") + "?token={{token}}",
        "headers": [], "body": "", "tests": [],
    })

    spec = {
        "scope": {"type": "collection", "slug": slug, "name": None},
        "auth": {"mode": "none"}, "iterations": 2,
        "resetCapturesEachIteration": True,
    }
    fake_server.set_responses("/echo", [{"status": 200, "body": "{}"}, {"status": 200, "body": "{}"}])
    list(run_orchestrator.execute("run-2", spec, store, env_store, cancel_event))

    echo_calls = [r for r in fake_server.requests if r["path"].startswith("/echo")]
    assert echo_calls[0]["path"] == "/echo?token=iter1"
    assert echo_calls[1]["path"] == "/echo?token=iter2"


# --- persistence (§9) ---


def test_execute_no_csv_run_persists_captures_exactly_once(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/login", [{"status": 200, "body": '{"accessToken":"once"}'}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "Login", "POST", "/login", tests=[
        {"type": "capture", "source": "body", "path": "accessToken", "variable": "sessionId"},
    ], server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "Login"}, "auth": {"mode": "none"}}
    list(run_orchestrator.execute("run-3", spec, store, env_store, cancel_event))

    assert store.get_vars(slug)["sessionId"] == "once"


def test_execute_csv_run_does_not_persist_captures_by_default(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/login", [{"status": 200, "body": '{"accessToken":"row-value"}'}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "Login", "POST", "/login", tests=[
        {"type": "capture", "source": "body", "path": "accessToken", "variable": "sessionId"},
    ], server=fake_server)

    csv_path = tmp_path / "data.csv"
    csv_path.write_text("id\n1\n")
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "Login"},
        "auth": {"mode": "none"}, "csvPath": str(csv_path),
    }
    list(run_orchestrator.execute("run-4", spec, store, env_store, cancel_event))

    assert "sessionId" not in store.get_vars(slug)


# --- token mint counts (§5.1, §14) ---


def test_execute_mints_token_once_for_n_requests_times_m_iterations(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}])
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 3)
    fake_server.set_responses("/b", [{"status": 200, "body": "{}"}] * 3)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    _save(store, slug, "B", "GET", "/b", server=fake_server)

    csv_path = tmp_path / "data.csv"
    csv_path.write_text("id\n1\n2\n3\n")
    spec = {
        "scope": {"type": "collection", "slug": slug, "name": None},
        "auth": {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
                 "refreshToken": "x=r", "tenant": "t"},
        "csvPath": str(csv_path),
    }
    list(run_orchestrator.execute("run-5", spec, store, env_store, cancel_event))

    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(token_calls) == 1


def test_execute_honours_max_token_refreshes_from_spec(store, env_store, fake_server, cancel_event):
    """run_parallel.py already reads spec["maxTokenRefreshes"]; sequential
    execute() must read it identically instead of always using TokenCache's
    hardcoded default of 10.

    Once the budget is exhausted the run now halts (design §4) rather than
    continuing with a stale token and a FLAGGED row — see
    test_run_orchestrator_auth_halt.py::test_refresh_exhausted_halts_the_run
    for the dedicated halt-behaviour coverage."""
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}] * 3)
    fake_server.set_responses("/a", [
        {"status": 403, "body": "{}"}, {"status": 200, "body": "{}"},
        {"status": 403, "body": "{}"}, {"status": 200, "body": "{}"},
        {"status": 403, "body": "{}"}, {"status": 200, "body": "{}"},
    ])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
                 "refreshToken": "x=r", "tenant": "t"},
        "iterations": 3,
        "maxTokenRefreshes": 2,
    }
    events = list(run_orchestrator.execute("run-max-refreshes", spec, store, env_store, cancel_event))

    results = _events_by_type(events, "result")
    assert [r["status"] for r in results] == ["OK", "OK"]
    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "STOPPED"
    assert summary["haltReason"] == "auth-refresh-exhausted"


def test_execute_absent_max_token_refreshes_falls_back_to_default(store, env_store, fake_server, cancel_event, monkeypatch):
    captured = []
    real_init = run_auth.TokenCache.__init__

    def spy_init(self, auth_cfg, max_refreshes=run_auth.DEFAULT_MAX_REFRESHES, **kwargs):
        captured.append(max_refreshes)
        real_init(self, auth_cfg, max_refreshes=max_refreshes, **kwargs)

    monkeypatch.setattr(run_auth.TokenCache, "__init__", spy_init)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 2)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    base_spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}}

    list(run_orchestrator.execute("run-mtr-1", {**base_spec, "maxTokenRefreshes": 2}, store, env_store, cancel_event))
    list(run_orchestrator.execute("run-mtr-2", dict(base_spec), store, env_store, cancel_event))

    assert captured == [2, run_auth.DEFAULT_MAX_REFRESHES]


def test_execute_refresh_token_each_row_mints_m_times(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}] * 3)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 3)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    csv_path = tmp_path / "data.csv"
    csv_path.write_text("id\n1\n2\n3\n")
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
                 "refreshToken": "x=r", "tenant": "t", "refreshTokenEachRow": True},
        "csvPath": str(csv_path),
    }
    list(run_orchestrator.execute("run-6", spec, store, env_store, cancel_event))

    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(token_calls) == 3


def test_execute_403_mints_one_extra_token_and_resends_once(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/token", [
        {"status": 200, "body": '{"accessToken":"tok-1"}'},
        {"status": 200, "body": '{"accessToken":"tok-2"}'},
    ])
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}, {"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
                 "refreshToken": "x=r", "tenant": "t"},
    }
    events = list(run_orchestrator.execute("run-7", spec, store, env_store, cancel_event))

    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    a_calls = [r for r in fake_server.requests if r["path"] == "/a"]
    assert len(token_calls) == 2
    assert len(a_calls) == 2
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "OK"


def test_execute_403_still_after_retry_is_flagged(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/token", [
        {"status": 200, "body": '{"accessToken":"tok-1"}'},
        {"status": 200, "body": '{"accessToken":"tok-2"}'},
    ])
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}, {"status": 403, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
                 "refreshToken": "x=r", "tenant": "t"},
    }
    events = list(run_orchestrator.execute("run-8", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "FLAGGED"


def test_execute_403_matching_expected_status_assertion_skips_retry_and_passes(store, env_store, fake_server, cancel_event):
    """A row that deliberately expects 403 (a negative-authorization test
    case) must be graded by its own assertions, not force-classified as
    FLAGGED before those assertions are even checked — and the unconditional
    403-retry-with-token-refresh must not fire either, since retrying would
    risk turning the deliberately-expected 403 into an unexpected 200."""
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok-1"}'}])
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", tests=[
        {"type": "assert", "source": "status", "operator": "equals", "expected": 403},
    ], server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
                 "refreshToken": "x=r", "tenant": "t"},
    }
    events = list(run_orchestrator.execute("run-403-expected", spec, store, env_store, cancel_event))

    a_calls = [r for r in fake_server.requests if r["path"] == "/a"]
    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(a_calls) == 1
    assert len(token_calls) == 1
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "OK"


# --- classification (§8.4) ---


def test_execute_classifies_timeout_as_flagged(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/slow", [{"status": 200, "body": "{}", "delay": 0.3}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "Slow", "GET", "/slow", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "Slow"}, "auth": {"mode": "none"}, "timeout": 0.05}
    events = list(run_orchestrator.execute("run-9", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "FLAGGED"


def test_execute_classifies_assertion_shortfall_as_fail(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": '{"loanId": "1"}'}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", tests=[
        {"type": "assert", "source": "body", "path": "loanId", "operator": "equals", "expected": "999"},
    ], server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}}
    events = list(run_orchestrator.execute("run-10", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "FAIL"


def test_execute_classifies_ok(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}}
    events = list(run_orchestrator.execute("run-11", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "OK"
    summary = _events_by_type(events, "summary")[0]
    assert summary["ok"] == 1 and summary["exitCode"] == 0


def test_execute_threads_proxy_field_into_the_outgoing_request(store, env_store, cancel_event, monkeypatch):
    """ROADMAP §10 Phase 1: Runner must thread spec["proxy"] through to the
    same requests.request call Console's Send already reaches, so a CSV run
    can be captured by the Nucleus Capture Tool exactly like a single Send."""
    import collection_routes

    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a")

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

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "proxySettings": {"mode": "custom", "url": "http://127.0.0.1:8080", "username": "", "password": "", "bypassList": []},
    }
    events = list(run_orchestrator.execute("run-proxy", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "OK"
    assert seen["proxies"] == {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}


# --- cancellation & deadline ---


def test_execute_cancellation_stops_before_next_request(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 5)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}, "iterations": 5}

    events = []
    for event in run_orchestrator.execute("run-12", spec, store, env_store, cancel_event):
        events.append(event)
        if event["type"] == "result":
            cancel_event.set()

    summary = _events_by_type(events, "summary")[0]
    assert summary["exitCode"] == 130
    assert summary["status"] == "STOPPED"
    assert len(_events_by_type(events, "result")) == 1


def test_execute_deadline_breach_reports_timeout_exit_code(store, env_store, fake_server, cancel_event, monkeypatch):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 3)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    import runner_commands
    monkeypatch.setattr(runner_commands, "process_timeout_for", lambda row_count, **kwargs: 0.0)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}, "iterations": 3}
    events = list(run_orchestrator.execute("run-13", spec, store, env_store, cancel_event))
    summary = _events_by_type(events, "summary")[0]
    assert summary["exitCode"] == 124
    assert summary["status"] == "TIMEOUT"


# --- retry CSV, __failedAtStep (§12.1.1) ---


def test_execute_writes_retry_csv_with_failed_at_step_column(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/create", [{"status": 200, "body": "{}"}])
    fake_server.set_responses("/disburse", [{"status": 500, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "Create", "POST", "/create", server=fake_server)
    _save(store, slug, "Disburse", "POST", "/disburse", server=fake_server)

    csv_path = tmp_path / "data.csv"
    csv_path.write_text("id\n1\n")
    spec = {
        "scope": {"type": "collection", "slug": slug, "name": None},
        "auth": {"mode": "none"}, "csvPath": str(csv_path),
    }
    events = list(run_orchestrator.execute("run-14", spec, store, env_store, cancel_event))
    summary = _events_by_type(events, "summary")[0]
    assert summary["retryCsv"]
    with open(summary["retryCsv"]) as f:
        content = f.read()
    assert "__failedAtStep" in content
    assert "Disburse" in content


# --- transient retry (§12.1.2) ---


def test_execute_retries_idempotent_timeout_when_retries_positive(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}", "delay": 0.2}, {"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "timeout": 0.05, "retries": 1,
    }
    events = list(run_orchestrator.execute("run-15", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "OK"
    assert result["attempt"] == 2
    assert result["attempts"] == 2


def test_execute_elapsed_ms_covers_the_whole_retry_sequence_not_just_the_last_attempt(
    store, env_store, fake_server, cancel_event,
):
    """elapsedMs is the only thing in the UI a user can use to independently
    sanity-check "did this actually retry" — if it only timed the last
    attempt, a request that visibly took >1s of real backoff sleep would
    misleadingly report a few milliseconds, undercutting the attempt/retried
    counts instead of corroborating them."""
    fake_server.set_responses("/a", [{"status": 500, "body": "{}", "delay": 0.05}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}, "retries": 2,
    }
    events = list(run_orchestrator.execute("run-19", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["attempt"] == 3
    assert result["elapsedMs"] >= 1000


def test_execute_streams_one_attempt_event_per_real_try(store, env_store, fake_server, cancel_event):
    """The aggregate counters (attempt X/Y, "N retried") are not enough on
    their own — a user who doesn't trust a number needs to see each actual
    try as it happens. Every real HTTP call _send_step makes must surface as
    its own "attempt" event, in order, before the final "result" event."""
    fake_server.set_responses("/a", [{"status": 500, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}, "retries": 3,
    }
    events = list(run_orchestrator.execute("run-20", spec, store, env_store, cancel_event))
    attempts = _events_by_type(events, "attempt")
    assert [a["attempt"] for a in attempts] == [1, 2, 3, 4]
    assert [a["attempts"] for a in attempts] == [4, 4, 4, 4]
    assert [a["httpStatus"] for a in attempts] == [500, 500, 500, 500]
    assert [a["willRetry"] for a in attempts] == [True, True, True, False]
    for a in attempts:
        assert a["requestName"] == "A"
        assert a["iteration"] == 1
    # attempt events must precede the final result event, not follow it —
    # a UI streaming these live needs them to arrive before the summary.
    result_index = next(i for i, e in enumerate(events) if e["type"] == "result")
    assert all(events.index(a) < result_index for a in attempts)


def test_execute_summary_counts_every_retry_attempt_not_just_the_request(store, env_store, fake_server, cancel_event):
    """A request that burns all 3 configured retries (4 attempts total) before
    permanently failing must report retriedRequests=3, not 1 — the bottom-bar
    "N retried" label is read as "how many retries happened," and a guard that
    only counted the first retry per request silently hid the other 2."""
    fake_server.set_responses("/a", [{"status": 500, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}, "retries": 3,
    }
    events = list(run_orchestrator.execute("run-18", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["attempt"] == 4
    assert result["attempts"] == 4
    summary = _events_by_type(events, "summary")[0]
    assert summary["retriedRequests"] == 3


def test_execute_does_not_retry_post_timeout_without_unsafe_opt_in(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}", "delay": 0.2}, {"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "POST", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "timeout": 0.05, "retries": 1,
    }
    events = list(run_orchestrator.execute("run-16", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "FLAGGED"
    assert result["attempt"] == 1
    # attempts must reflect the configured budget (1 + retries), not just
    # echo attempt — otherwise the UI's "attempt 1/1" looks like retries=0
    # was configured, hiding that retries=1 existed but didn't apply to POST.
    assert result["attempts"] == 2


def test_execute_never_retries_a_fail(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": '{"loanId":"1"}'}, {"status": 200, "body": '{"loanId":"999"}'}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", tests=[
        {"type": "assert", "source": "body", "path": "loanId", "operator": "equals", "expected": "999"},
    ], server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}, "retries": 3,
    }
    events = list(run_orchestrator.execute("run-17", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "FAIL"
    assert result["attempt"] == 1
    # 3 retries were configured (max_attempts=4) but a FAIL never retries —
    # attempts must still report 4 so the UI doesn't imply only 1 was ever
    # available, i.e. that the "3 retries" setting silently did nothing.
    assert result["attempts"] == 4
    assert len([r for r in fake_server.requests if r["path"] == "/a"]) == 1


# --- result event carries enough for the Runner's master-detail response pane
# to render Headers/Request/Tests tabs without a second fetch ---


def test_execute_result_event_carries_request_method(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}}
    events = list(run_orchestrator.execute("run-18", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["method"] == "GET"


def test_execute_result_event_carries_response_headers(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}", "headers": {"X-Custom": "abc"}}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}}
    events = list(run_orchestrator.execute("run-19", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["responseHeaders"].get("X-Custom") == "abc"


def test_execute_result_event_carries_full_test_results(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": '{"loanId": "1"}'}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", tests=[
        {"type": "assert", "source": "body", "path": "loanId", "operator": "equals", "expected": "1"},
    ], server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}}
    events = list(run_orchestrator.execute("run-20", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert len(result["tests"]) == 1
    assert result["tests"][0]["passed"] is True


def test_execute_result_event_redacts_captured_secret_from_full_test_results(store, env_store, fake_server, cancel_event):
    # _has_secret_capture already blanks responseSnippet for this case (a
    # secret-named capture implies the body itself is sensitive) — the new
    # full `tests` list must not reopen that hole via test.actual.
    fake_server.set_responses("/a", [{"status": 200, "body": '{"token": "shh-secret-value"}'}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", tests=[
        {"type": "capture", "source": "body", "path": "token", "variable": "authToken"},
    ], server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}}
    events = list(run_orchestrator.execute("run-21", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["responseSnippet"] is None
    assert result["tests"][0]["actual"] == "***"


# Was a fixed module constant (RESPONSE_SNIPPET_LIMIT) — now an optional
# per-run spec field so the Runner UI can offer it as a setting.
def test_execute_respects_a_custom_response_snippet_limit(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/a", [{"status": 200, "body": "0123456789"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}, "responseSnippetLimit": 4}
    events = list(run_orchestrator.execute("run-22", spec, store, env_store, cancel_event))
    result = _events_by_type(events, "result")[0]
    assert result["responseSnippet"] == "0123"
