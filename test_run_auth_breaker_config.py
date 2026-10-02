"""Guards that both the sequential and parallel paths read the breaker's
threshold and enabled-flag from the run spec identically (design §4), the
same way PR #28 fixed maxTokenRefreshes sequential/parallel drift.
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


def _save(store, slug, name, method, path, server=None):
    store.save_request(slug, {
        "name": name, "method": method,
        "url": server.url(path), "headers": [], "body": "", "tests": [],
    })


def _write_csv(tmp_path, n_rows):
    path = tmp_path / "data.csv"
    path.write_text("id\n" + "\n".join(str(i) for i in range(1, n_rows + 1)) + "\n")
    return str(path)


def _spy_token_cache_init(monkeypatch):
    captured = []
    real_init = run_auth.TokenCache.__init__

    def spy_init(self, auth_cfg, max_refreshes=run_auth.DEFAULT_MAX_REFRESHES,
                 max_consecutive_mint_failures=run_auth.DEFAULT_MAX_CONSECUTIVE_MINT_FAILURES,
                 breaker_enabled=True):
        captured.append((max_consecutive_mint_failures, breaker_enabled))
        real_init(self, auth_cfg, max_refreshes=max_refreshes,
                  max_consecutive_mint_failures=max_consecutive_mint_failures,
                  breaker_enabled=breaker_enabled)

    monkeypatch.setattr(run_auth.TokenCache, "__init__", spy_init)
    return captured


def test_sequential_reads_breaker_settings_from_spec(store, env_store, fake_server, cancel_event, monkeypatch):
    captured = _spy_token_cache_init(monkeypatch)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "maxConsecutiveMintFailures": 1, "authBreakerEnabled": False,
    }
    list(run_orchestrator.execute("run-cfg-1", spec, store, env_store, cancel_event))
    assert captured == [(1, False)]


def test_sequential_absent_breaker_settings_fall_back_to_defaults(store, env_store, fake_server, cancel_event, monkeypatch):
    captured = _spy_token_cache_init(monkeypatch)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    spec = {"scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"}}
    list(run_orchestrator.execute("run-cfg-2", spec, store, env_store, cancel_event))
    assert captured == [(run_auth.DEFAULT_MAX_CONSECUTIVE_MINT_FAILURES, True)]


def test_sequential_honours_explicit_zero_max_consecutive_mint_failures(store, env_store, fake_server, cancel_event, monkeypatch):
    """0 is a deliberate 'trip on the very first failure' choice — `x or
    DEFAULT` treats it the same as an absent field, silently tolerating 2
    more failures than requested (the same bug class PR #28 fixed for
    maxTokenRefreshes)."""
    captured = _spy_token_cache_init(monkeypatch)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}])
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "maxConsecutiveMintFailures": 0,
    }
    list(run_orchestrator.execute("run-cfg-zero", spec, store, env_store, cancel_event))
    assert captured == [(0, True)]


def test_parallel_reads_breaker_settings_from_spec(store, env_store, fake_server, cancel_event, tmp_path, monkeypatch):
    captured = _spy_token_cache_init(monkeypatch)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 2)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 2)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "csvPath": csv_path, "workers": 2,
        "maxConsecutiveMintFailures": 5, "authBreakerEnabled": False,
    }
    list(run_orchestrator.execute("run-cfg-3", spec, store, env_store, cancel_event))
    assert captured == [(5, False)]


def test_parallel_honours_explicit_zero_max_consecutive_mint_failures(store, env_store, fake_server, cancel_event, tmp_path, monkeypatch):
    captured = _spy_token_cache_init(monkeypatch)
    fake_server.set_responses("/a", [{"status": 200, "body": "{}"}] * 2)
    slug = "c"
    store.create(slug)
    _save(store, slug, "A", "GET", "/a", server=fake_server)
    csv_path = _write_csv(tmp_path, 2)
    spec = {
        "scope": {"type": "request", "slug": slug, "name": "A"}, "auth": {"mode": "none"},
        "csvPath": csv_path, "workers": 2, "maxConsecutiveMintFailures": 0,
    }
    list(run_orchestrator.execute("run-cfg-zero-parallel", spec, store, env_store, cancel_event))
    assert captured == [(0, True)]
