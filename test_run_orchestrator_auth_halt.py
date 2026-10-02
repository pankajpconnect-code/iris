"""Sequential halt behaviour for the mint-failure circuit breaker and
TokenRefreshExhausted (design §4). The critical regression this file guards:
a row-level 403 that follows a *successful* refresh must never count toward
the breaker — see test_row_403_after_successful_refresh_never_opens_breaker.
"""

import threading

import pytest

import collection_store
import environment_store
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


def _save(store, slug, name, method, path, server):
    store.save_request(slug, {
        "name": name, "method": method,
        "url": server.url(path), "headers": [], "body": "", "tests": [],
    })


def _write_csv(tmp_path, n_rows):
    path = tmp_path / "data.csv"
    path.write_text("id\n" + "\n".join(str(i) for i in range(1, n_rows + 1)) + "\n")
    return str(path)


def _events_by_type(events, event_type):
    return [e for e in events if e["type"] == event_type]


def _refresh_cookie_auth(fake_server, **overrides):
    return {
        "mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
        "refreshToken": "x=r", "tenant": "t", **overrides,
    }


def test_three_consecutive_mint_failures_halt_the_run(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/token", [{"status": 500, "body": "down"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 5)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
    }
    events = list(run_orchestrator.execute("run-halt-1", spec, store, env_store, cancel_event))

    results = _events_by_type(events, "result")
    assert [r["status"] for r in results] == ["ERROR", "ERROR"]
    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "STOPPED"
    assert summary["haltReason"] == "auth-circuit-open"
    assert summary["haltDetail"]["consecutiveMintFailures"] == 3


def test_row_403_after_successful_refresh_never_opens_breaker(store, env_store, fake_server, cancel_event, tmp_path):
    """The central guard (design §4): row-level 403s are never mint failures.
    Threshold is set to the most adversarial value (1) on purpose — if row
    403s were wrongly counted, this would halt after the first row."""
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}] * 10)
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}] * 10)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 5)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
        "maxConsecutiveMintFailures": 1,
    }
    events = list(run_orchestrator.execute("run-halt-2", spec, store, env_store, cancel_event))

    results = _events_by_type(events, "result")
    assert [r["status"] for r in results] == ["FLAGGED"] * 5
    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "COMPLETED"
    assert summary["haltReason"] is None


def test_mint_failure_then_success_then_failure_does_not_halt(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/token", [
        {"status": 200, "body": '{"accessToken":"tok-0"}'},  # priming get()
        {"status": 500, "body": "down"},                      # row 1 refresh: fail (1)
        {"status": 200, "body": '{"accessToken":"tok-1"}'},   # row 2 refresh: success (reset)
        {"status": 500, "body": "down"},                      # row 3 refresh: fail (1, not 2)
    ])
    fake_server.set_responses("/a", [
        {"status": 403, "body": "{}"},  # row 1 first send
        {"status": 403, "body": "{}"},  # row 2 first send
        {"status": 200, "body": "{}"},  # row 2 resend after successful refresh
        {"status": 403, "body": "{}"},  # row 3 first send
    ])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 3)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
        "maxConsecutiveMintFailures": 2,
    }
    events = list(run_orchestrator.execute("run-halt-3", spec, store, env_store, cancel_event))

    results = _events_by_type(events, "result")
    assert [r["status"] for r in results] == ["ERROR", "OK", "ERROR"]
    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "COMPLETED"
    assert summary["haltReason"] is None


def test_halted_run_still_writes_a_complete_retry_csv(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/token", [{"status": 500, "body": "down"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 5)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
    }
    events = list(run_orchestrator.execute("run-halt-4", spec, store, env_store, cancel_event))

    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "STOPPED"
    assert summary["retryCsv"]
    with open(summary["retryCsv"]) as f:
        content = f.read()
    assert "__failedAtStep" in content
    # Rows 1-3 were all attempted (2 got a row result, the 3rd tripped the
    # breaker before one) — all three belong in the retry set.
    ids = [line.split(",")[0] for line in content.strip().splitlines()[1:]]
    assert ids == ["1", "2", "3"]


def test_breaker_disabled_restores_continue_and_flag_behaviour(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/token", [{"status": 500, "body": "down"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 5)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
        "authBreakerEnabled": False,
    }
    events = list(run_orchestrator.execute("run-halt-5", spec, store, env_store, cancel_event))

    results = _events_by_type(events, "result")
    assert [r["status"] for r in results] == ["ERROR"] * 5
    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "COMPLETED"
    assert summary["haltReason"] is None


def test_refresh_exhausted_halts_the_run(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}] * 5)
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}] * 5)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 3)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
        "maxTokenRefreshes": 1,
    }
    events = list(run_orchestrator.execute("run-halt-6", spec, store, env_store, cancel_event))

    results = _events_by_type(events, "result")
    assert [r["status"] for r in results] == ["FLAGGED"]
    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "STOPPED"
    assert summary["haltReason"] == "auth-refresh-exhausted"


def test_refresh_token_each_row_halt_still_writes_the_halting_row_to_retry_csv(
    store, env_store, fake_server, cancel_event, tmp_path,
):
    """refreshTokenEachRow's force_refresh() call sits before any request in
    the iteration — when it's the one that trips the breaker, failed_step
    was never set, so the row was silently dropped from the retry CSV even
    though it was never actually attempted."""
    fake_server.set_responses("/token", [{"status": 500, "body": "down"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 3)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server, refreshTokenEachRow=True),
        "csvPath": csv_path, "maxConsecutiveMintFailures": 1,
    }
    events = list(run_orchestrator.execute("run-halt-7", spec, store, env_store, cancel_event))

    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "STOPPED"
    assert summary["haltReason"] == "auth-circuit-open"
    assert summary["retryCsv"]
    with open(summary["retryCsv"]) as f:
        ids = [line.split(",")[0] for line in f.read().strip().splitlines()[1:]]
    assert ids == ["1"]
