"""Tests for per-variable delete and enable/disable on environments — key/value
editing, requested live during Runner testing. Split out of test_console.py
to keep that file under the 500-line limit.
"""

import json

import pytest

import environment_routes
import environment_store
import keychain


class FakeKeychain:
    """In-memory stand-in for keychain.py so these tests never touch the
    real macOS Keychain — see test_keychain.py for the real round-trip,
    gated to darwin only."""

    def __init__(self):
        self._items = {}

    def set_secret(self, slug, name, value):
        self._items[(slug, name)] = value

    def get_secret(self, slug, name):
        return self._items.get((slug, name))

    def delete_secret(self, slug, name):
        self._items.pop((slug, name), None)


@pytest.fixture
def env_store(tmp_path):
    return environment_store.EnvironmentStore(str(tmp_path), keychain_backend=FakeKeychain())


def test_environment_delete_var_removes_it_but_keeps_others(env_store):
    slug = env_store.create("Dev")
    env_store.set_vars(slug, {"url": "https://dev.example", "keep": "yes"})
    env_store.delete_var(slug, "url")
    assert env_store.get_vars(slug) == {"keep": "yes"}


def test_environment_delete_var_removes_secret_var_too(env_store):
    slug = env_store.create("Dev")
    env_store.set_vars(slug, {"token": "secret-value"})
    env_store.delete_var(slug, "token")
    assert "token" not in env_store.get_vars(slug)


def test_environment_disabled_var_excluded_from_get_vars_but_not_lost(env_store):
    """Enable/disable checkbox: unchecking a var must stop it resolving in
    requests without discarding its stored value."""
    slug = env_store.create("Dev")
    env_store.set_vars(slug, {"url": "https://dev.example"})
    env_store.set_var_enabled(slug, "url", False)
    assert "url" not in env_store.get_vars(slug)
    assert env_store.get_vars_state(slug)["url"] == {"value": "https://dev.example", "enabled": False}
    env_store.set_var_enabled(slug, "url", True)
    assert env_store.get_vars(slug)["url"] == "https://dev.example"


def test_environment_get_vars_state_defaults_to_enabled(env_store):
    slug = env_store.create("Dev")
    env_store.set_vars(slug, {"url": "https://dev.example"})
    assert env_store.get_vars_state(slug)["url"] == {"value": "https://dev.example", "enabled": True}


def test_secret_var_never_written_to_json_file(tmp_path):
    """The hard invariant from environment_store's design: secret-named
    values go to the Keychain (or memory if unavailable), never to disk."""
    store = environment_store.EnvironmentStore(str(tmp_path), keychain_backend=FakeKeychain())
    slug = store.create("Dev")
    store.set_vars(slug, {"token": "super-secret-value", "plainVar": "not-secret"})
    raw = (tmp_path / f"{slug}.json").read_text()
    assert "super-secret-value" not in raw
    assert "not-secret" in raw
    assert "token" not in raw or '"secretVarNames"' in raw  # only the name, not the value, may appear


class _UnavailableKeychain:
    """Every write fails, as if the Keychain were locked/denied."""

    def set_secret(self, slug, name, value):
        raise keychain.KeychainUnavailable("locked")

    def get_secret(self, slug, name):
        return None

    def delete_secret(self, slug, name):
        pass


def test_secret_var_not_recorded_as_keychain_backed_when_keychain_write_fails(tmp_path):
    """A keychain write failure must not be recorded as keychain-backed —
    secret_names.add(name) used to run unconditionally even when
    set_secret raised, so the on-disk secretVarNames list claimed a value
    that was never actually written to the Keychain. After a restart (the
    in-memory fallback is gone), that name silently resolves to nothing
    with no error, while the JSON still lied about it being keychain-backed."""
    store = environment_store.EnvironmentStore(str(tmp_path), keychain_backend=_UnavailableKeychain())
    slug = store.create("Dev")
    store.set_vars(slug, {"token": "secret-value"})

    # This session: still readable via the in-memory fallback.
    assert store.get_vars(slug)["token"] == "secret-value"
    # But never actually reached the Keychain, so it must not be recorded
    # as if it had been.
    assert "token" not in store.get(slug).get("secretVarNames", [])


def test_secret_var_survives_across_store_instances_via_keychain():
    """Simulates an app relaunch: a fresh EnvironmentStore backed by the
    same Keychain contents must still resolve the secret's value, proving
    the persisted secretVarNames + Keychain lookup round-trips correctly."""
    import tempfile

    shared_keychain = FakeKeychain()
    with tempfile.TemporaryDirectory() as tmp:
        first = environment_store.EnvironmentStore(tmp, keychain_backend=shared_keychain)
        slug = first.create("Dev")
        first.set_vars(slug, {"token": "secret-across-restart"})

        second = environment_store.EnvironmentStore(tmp, keychain_backend=shared_keychain)
        assert second.get_vars(slug)["token"] == "secret-across-restart"


# --- divergence ---


def test_divergence_flags_variable_that_differs_across_environments(env_store):
    dev = env_store.create("Dev")
    prod = env_store.create("Prod")
    env_store.set_vars(dev, {"tenant": "dev-tenant"})
    env_store.set_vars(prod, {"tenant": "prod-tenant"})

    result = env_store.divergence()

    assert result["tenant"]["secret"] is False
    assert result["tenant"]["environmentNames"] == ["Dev", "Prod"]


def test_divergence_omits_variable_with_same_value_everywhere(env_store):
    dev = env_store.create("Dev")
    prod = env_store.create("Prod")
    env_store.set_vars(dev, {"region": "eu-west-1"})
    env_store.set_vars(prod, {"region": "eu-west-1"})

    assert "region" not in env_store.divergence()


def test_divergence_omits_variable_present_in_only_one_environment(env_store):
    dev = env_store.create("Dev")
    env_store.set_vars(dev, {"onlyHere": "x"})

    assert "onlyHere" not in env_store.divergence()


def test_divergence_flags_secret_but_never_leaks_its_value(env_store):
    dev = env_store.create("Dev")
    prod = env_store.create("Prod")
    env_store.set_vars(dev, {"apiToken": "dev-secret-value-123"})
    env_store.set_vars(prod, {"apiToken": "prod-secret-value-456"})

    result = env_store.divergence()

    assert result["apiToken"]["secret"] is True
    assert result["apiToken"]["environmentNames"] == ["Dev", "Prod"]
    serialized = json.dumps(result)
    assert "dev-secret-value-123" not in serialized
    assert "prod-secret-value-456" not in serialized


def test_divergence_skips_corrupted_environment_but_reports_the_rest(env_store, tmp_path):
    dev = env_store.create("Dev")
    prod = env_store.create("Prod")
    env_store.set_vars(dev, {"tenant": "dev-tenant"})
    env_store.set_vars(prod, {"tenant": "prod-tenant"})
    (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")

    result = env_store.divergence()

    assert result["tenant"]["environmentNames"] == ["Dev", "Prod"]


# --- routes ---


def test_route_delete_var(env_store):
    slug = env_store.create("Dev")
    env_store.set_vars(slug, {"url": "https://dev.example", "keep": "yes"})
    status, body = environment_routes.handle_delete(env_store, f"/api/environments/{slug}/vars/url")
    assert status == 200
    assert body["variables"] == {"keep": {"value": "yes", "enabled": True}}


def test_route_set_var_enabled(env_store):
    slug = env_store.create("Dev")
    env_store.set_vars(slug, {"url": "https://dev.example"})
    status, body = environment_routes.handle_put(env_store, f"/api/environments/{slug}/vars/url/enabled", {"enabled": False})
    assert status == 200
    assert body["variables"]["url"] == {"value": "https://dev.example", "enabled": False}


def test_route_get_vars_state(env_store):
    slug = env_store.create("Dev")
    env_store.set_vars(slug, {"url": "https://dev.example"})
    status, body = environment_routes.handle_get(env_store, f"/api/environments/{slug}/vars-state")
    assert status == 200
    assert body["variables"]["url"] == {"value": "https://dev.example", "enabled": True}


def test_route_get_environment_divergence(env_store):
    dev = env_store.create("Dev")
    prod = env_store.create("Prod")
    env_store.set_vars(dev, {"tenant": "dev-tenant"})
    env_store.set_vars(prod, {"tenant": "prod-tenant"})

    status, body = environment_routes.handle_get(env_store, "/api/environment-divergence")

    assert status == 200
    assert body["divergence"]["tenant"]["environmentNames"] == ["Dev", "Prod"]


def test_route_get_environment_divergence_empty_when_nothing_diverges(env_store):
    status, body = environment_routes.handle_get(env_store, "/api/environment-divergence")

    assert status == 200
    assert body["divergence"] == {}
