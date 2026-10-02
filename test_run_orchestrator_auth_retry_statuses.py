"""Configurable auth-retry trigger status set (design §5). Default {401, 403}
— today's behaviour (403-only) is preserved by setting authRetryStatuses to
[403] explicitly. Two existing guards must survive untouched: a refresh is
only attempted when tokenUrl is set, and a row whose tests explicitly
asserted the observed status is graded by its own assertions, never retried.
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


def _save(store, slug, name, method, path, tests=None, server=None):
    store.save_request(slug, {
        "name": name, "method": method,
        "url": server.url(path), "headers": [], "body": "",
        "tests": tests or [],
    })


def _events_by_type(events, event_type):
    return [e for e in events if e["type"] == event_type]


def _refresh_cookie_auth(fake_server, **overrides):
    return {
        "mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
        "refreshToken": "x=r", "tenant": "t", **overrides,
    }


def test_401_triggers_refresh_and_retry_with_default_set(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/token", [
        {"status": 200, "body": '{"accessToken":"tok-1"}'},
        {"status": 200, "body": '{"accessToken":"tok-2"}'},
    ])
    fake_server.set_responses("/a", [{"status": 401, "body": "{}"}, {"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": _refresh_cookie_auth(fake_server)}
    events = list(run_orchestrator.execute("run-401-1", spec, store, env_store, cancel_event))

    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    a_calls = [r for r in fake_server.requests if r["path"] == "/a"]
    assert len(token_calls) == 2
    assert len(a_calls) == 2
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "OK"


def test_403_still_triggers_refresh_with_default_set(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/token", [
        {"status": 200, "body": '{"accessToken":"tok-1"}'},
        {"status": 200, "body": '{"accessToken":"tok-2"}'},
    ])
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}, {"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": _refresh_cookie_auth(fake_server)}
    events = list(run_orchestrator.execute("run-403-1", spec, store, env_store, cancel_event))

    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(token_calls) == 2
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "OK"


def test_configured_set_of_403_only_makes_401_a_plain_row_result(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok-1"}'}])
    fake_server.set_responses("/a", [{"status": 401, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "authRetryStatuses": [403],
    }
    events = list(run_orchestrator.execute("run-401-2", spec, store, env_store, cancel_event))

    a_calls = [r for r in fake_server.requests if r["path"] == "/a"]
    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(a_calls) == 1
    assert len(token_calls) == 1  # only the initial mint, no refresh attempt
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "FAIL"


def test_test_explicitly_asserting_401_suppresses_the_retry(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok-1"}'}])
    fake_server.set_responses("/a", [{"status": 401, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", tests=[
        {"type": "assert", "source": "status", "operator": "equals", "expected": 401},
    ], server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": _refresh_cookie_auth(fake_server)}
    events = list(run_orchestrator.execute("run-401-3", spec, store, env_store, cancel_event))

    a_calls = [r for r in fake_server.requests if r["path"] == "/a"]
    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(a_calls) == 1
    assert len(token_calls) == 1
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "OK"


def test_status_outside_the_set_never_triggers_a_refresh(store, env_store, fake_server, cancel_event):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok-1"}'}])
    fake_server.set_responses("/a", [{"status": 404, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": _refresh_cookie_auth(fake_server)}
    events = list(run_orchestrator.execute("run-404", spec, store, env_store, cancel_event))

    a_calls = [r for r in fake_server.requests if r["path"] == "/a"]
    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(a_calls) == 1
    assert len(token_calls) == 1
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "FAIL"


def test_explicitly_empty_auth_retry_statuses_disables_retry_entirely(store, env_store, fake_server, cancel_event):
    """An empty list is a deliberate choice (surfaced by the UI as both
    401/403 checkboxes unchecked) — distinct from the field being absent,
    which falls back to the default. Falling back on [] would silently
    ignore the user's choice to turn auth-retry off entirely."""
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok-1"}'}])
    fake_server.set_responses("/a", [{"status": 403, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)

    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"},
        "auth": _refresh_cookie_auth(fake_server), "authRetryStatuses": [],
    }
    events = list(run_orchestrator.execute("run-empty-set", spec, store, env_store, cancel_event))

    a_calls = [r for r in fake_server.requests if r["path"] == "/a"]
    token_calls = [r for r in fake_server.requests if r["path"] == "/token"]
    assert len(a_calls) == 1
    assert len(token_calls) == 1
    result = _events_by_type(events, "result")[0]
    assert result["status"] == "FAIL"
