"""Parallel-path halt behaviour for the mint-failure circuit breaker and
TokenRefreshExhausted (design §4) — mirrors
test_run_orchestrator_auth_halt.py's sequential coverage, plus the
concurrency-specific case the sequential path can't exercise.
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


def test_eight_workers_hitting_a_dead_token_endpoint_mint_once_and_halt_cleanly(
    store, env_store, fake_server, cancel_event, tmp_path,
):
    fake_server.set_responses("/token", [{"status": 500, "body": "down"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 8)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
        "workers": 8, "maxConsecutiveMintFailures": 1,
    }
    events = list(run_orchestrator.execute("run-p-halt-1", spec, store, env_store, cancel_event))

    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(token_calls) == 1
    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "STOPPED"
    assert summary["haltReason"] == "auth-circuit-open"


def test_parallel_refresh_exhausted_halts_with_reason(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}] * 5)
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}] * 5)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 4)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
        "workers": 2, "maxTokenRefreshes": 1,
    }
    events = list(run_orchestrator.execute("run-p-halt-2", spec, store, env_store, cancel_event))

    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "STOPPED"
    assert summary["haltReason"] == "auth-refresh-exhausted"


def test_parallel_row_403_after_successful_refresh_never_opens_breaker(
    store, env_store, fake_server, cancel_event, tmp_path,
):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}] * 20)
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}] * 20)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 6)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "csvPath": csv_path,
        "workers": 4, "maxConsecutiveMintFailures": 1,
    }
    events = list(run_orchestrator.execute("run-p-halt-3", spec, store, env_store, cancel_event))

    results = _events_by_type(events, "result")
    assert [r["status"] for r in results] == ["FLAGGED"] * 6
    summary = _events_by_type(events, "summary")[0]
    assert summary["status"] == "COMPLETED"
    assert summary["haltReason"] is None


def test_worker_crash_unrelated_to_auth_still_uses_generic_log(
    store, env_store, fake_server, cancel_event, tmp_path, monkeypatch,
):
    """A halt-unrelated worker exception must keep the existing generic
    handling (ERROR count + log message), not be mistaken for an auth halt."""
    import run_parallel

    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 10)
    csv_path = _write_csv(tmp_path, 4)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "csvPath": csv_path, "workers": 4,
    }
    real_run_iteration = run_parallel.orch._run_iteration

    def _flaky_run_iteration(ctx, iteration_index, total, csv_row, captured):
        if iteration_index == 2:
            raise RuntimeError("boom")
        yield from real_run_iteration(ctx, iteration_index, total, csv_row, captured)

    monkeypatch.setattr(run_parallel.orch, "_run_iteration", _flaky_run_iteration)

    events = list(run_orchestrator.execute("run-p-halt-4", spec, store, env_store, cancel_event))
    summary = _events_by_type(events, "summary")[0]
    assert summary["haltReason"] is None
    log_messages = [e["message"] for e in events if e["type"] == "log"]
    assert any("worker thread failed unexpectedly" in m for m in log_messages)


def test_parallel_refresh_token_each_row_halt_writes_the_halting_row_to_retry_csv(
    store, env_store, fake_server, cancel_event, tmp_path,
):
    fake_server.set_responses("/token", [{"status": 500, "body": "down"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", fake_server)
    csv_path = _write_csv(tmp_path, 3)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server, refreshTokenEachRow=True),
        "csvPath": csv_path, "workers": 2, "maxConsecutiveMintFailures": 1,
    }
    events = list(run_orchestrator.execute("run-p-halt-5", spec, store, env_store, cancel_event))

    summary = [e for e in events if e["type"] == "summary"][0]
    # Which worker(s) reach force_refresh() before combined_stop trips is a
    # genuine scheduling race (bounded by workers=2) — what must hold
    # deterministically is that at least the halting row isn't silently
    # dropped, unlike before this fix.
    assert summary["retryCsv"]
    with open(summary["retryCsv"]) as f:
        ids = [line.split(",")[0] for line in f.read().strip().splitlines()[1:]]
    assert len(ids) >= 1
