"""Tests for run_parallel.execute_parallel — PR6, opt-in parallel iterations
(design §8.8). Iterations run concurrently; requests within an iteration
never do. Driven against the real fake_server (conftest.py).
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


def _write_csv(tmp_path, n_rows):
    path = tmp_path / "data.csv"
    path.write_text("id\n" + "\n".join(str(i) for i in range(1, n_rows + 1)) + "\n")
    return str(path)


def test_workers_greater_than_one_rejects_reset_captures_false(store, env_store, fake_server, cancel_event, tmp_path):
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 3)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "csvPath": csv_path, "workers": 4, "resetCapturesEachIteration": False,
    }
    with pytest.raises(ValueError):
        list(run_orchestrator.execute("run-p1", spec, store, env_store, cancel_event))


def test_all_iterations_complete_with_independent_captures(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 6)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 6)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "csvPath": csv_path, "workers": 4,
    }
    events = list(run_orchestrator.execute("run-p2", spec, store, env_store, cancel_event))
    results = _events_by_type(events, "result")
    assert len(results) == 6
    assert {r["iteration"] for r in results} == {1, 2, 3, 4, 5, 6}
    summary = _events_by_type(events, "summary")[0]
    assert summary["ok"] == 6
    assert summary["exitCode"] == 0


def test_parallel_passes_max_token_refreshes_to_token_cache(store, env_store, fake_server, cancel_event, tmp_path, monkeypatch):
    """Guards run_orchestrator.py:391's sequential fix against regressing the
    parallel path, which already reads spec["maxTokenRefreshes"] correctly."""
    captured = []
    real_init = run_auth.TokenCache.__init__

    def spy_init(self, auth_cfg, max_refreshes=run_auth.DEFAULT_MAX_REFRESHES, **kwargs):
        captured.append(max_refreshes)
        real_init(self, auth_cfg, max_refreshes=max_refreshes, **kwargs)

    monkeypatch.setattr(run_auth.TokenCache, "__init__", spy_init)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 4)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 2)
    base_spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "csvPath": csv_path, "workers": 2,
    }

    list(run_orchestrator.execute("run-p-mtr-1", {**base_spec, "maxTokenRefreshes": 2}, store, env_store, cancel_event))
    list(run_orchestrator.execute("run-p-mtr-2", dict(base_spec), store, env_store, cancel_event))

    assert captured == [2, run_auth.DEFAULT_MAX_REFRESHES]


def test_concurrent_403s_single_flight_mint_exactly_one_replacement(store, env_store, fake_server, cancel_event, tmp_path):
    """One genuine expiry event: the first wave of concurrently in-flight
    requests (bounded by workers=4) all hit the stale token's 403 together;
    single-flight must collapse that into exactly one refresh mint, and every
    retry (plus later iterations) then succeeds on the fresh token."""
    fake_server.set_responses("/token", [
        {"status": 200, "body": '{"accessToken":"tok-1"}'},
        {"status": 200, "body": '{"accessToken":"tok-2"}'},
    ])
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}] * 4 + [{"status": 200, "body": "{}"}] * 8)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 6)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"), "refreshToken": "x=r", "tenant": "t"},
        "csvPath": csv_path, "workers": 4,
    }
    events = list(run_orchestrator.execute("run-p3", spec, store, env_store, cancel_event))
    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(token_calls) == 2
    results = _events_by_type(events, "result")
    assert all(r["status"] == "OK" for r in results)


def test_stop_leaves_no_queued_iteration_running(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/a", [{"status": 200, "body": "{}", "delay": 0.2}] * 20)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 20)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "csvPath": csv_path, "workers": 2,
    }

    events = []
    for event in run_orchestrator.execute("run-p4", spec, store, env_store, cancel_event):
        events.append(event)
        if event["type"] == "result":
            cancel_event.set()

    summary = _events_by_type(events, "summary")[0]
    assert summary["exitCode"] == 130
    assert summary["status"] == "STOPPED"
    # 2 workers may each have one in-flight request when Stop lands; nothing
    # queued beyond that should ever start.
    assert len(fake_server.requests) <= 4


def test_retry_csv_rows_sorted_by_iteration_despite_completion_order(store, env_store, fake_server, cancel_event, tmp_path):
    fake_server.set_responses("/a", [
        {"status": 200, "body": "{}"},
        {"status": 500, "body": "{}", "delay": 0.2},  # iteration 2: fails, but slow
        {"status": 200, "body": "{}"},
        {"status": 500, "body": "{}"},  # iteration 4: fails, fast — completes before iteration 2
    ])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 4)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "csvPath": csv_path, "workers": 4,
    }
    events = list(run_orchestrator.execute("run-p5", spec, store, env_store, cancel_event))
    summary = _events_by_type(events, "summary")[0]
    assert summary["retryCsv"]
    with open(summary["retryCsv"]) as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    ids = [line.split(",")[0] for line in lines[1:]]
    assert ids == sorted(ids, key=int)


def test_token_mint_failure_ends_run_with_summary_not_a_crash(store, env_store, fake_server, cancel_event, tmp_path):
    """A dead identity endpoint used to let every one of the 4 concurrent
    workers independently fail-and-flag its own row (errored == 4). With the
    breaker now on by default (design §4), the 3rd consecutive mint failure
    halts the run instead — see test_run_parallel_auth_halt.py for the
    dedicated halt-behaviour coverage. Only the first
    (max_consecutive_mint_failures - 1) = 2 lock-serialized attempts still
    produce a plain ERROR row; the rest become the halt."""
    fake_server.set_responses("/token", [{"status": 401, "body": "nope"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 4)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"), "refreshToken": "x=r", "tenant": "t"},
        "csvPath": csv_path, "workers": 4,
    }
    events = list(run_orchestrator.execute("run-p6", spec, store, env_store, cancel_event))
    assert events[-1]["type"] == "summary"
    assert events[-1]["errored"] == 2
    assert events[-1]["status"] == "STOPPED"
    assert events[-1]["haltReason"] == "auth-circuit-open"


def test_worker_exception_yields_partial_summary_not_a_crash(store, env_store, fake_server, cancel_event, tmp_path, monkeypatch):
    """One worker's unhandled exception used to be re-raised after draining
    every future, discarding the real counters/retry CSV from every OTHER
    worker that succeeded — server.py's outer except then synthesized a
    zeroed-out summary for what might have been a mostly-successful run."""
    import run_parallel

    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
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

    events = list(run_orchestrator.execute("run-p6", spec, store, env_store, cancel_event))
    # Exactly how many of the OTHER iterations finish before the abort
    # cascades to them is a genuine thread-scheduling race (existing,
    # deliberate abort-propagation behavior) — not what this test is about.
    # What must hold deterministically: the crash didn't propagate out of
    # execute() as an exception (the old bug — this call would have raised),
    # it's reflected in the counts instead of silently vanishing, and it's
    # logged.
    assert events[-1]["type"] == "summary"
    assert events[-1]["errored"] >= 1
    log_messages = [e["message"] for e in events if e["type"] == "log"]
    assert any("worker thread failed unexpectedly" in m for m in log_messages)
