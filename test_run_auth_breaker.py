"""Tests for TokenCache's mint-failure circuit breaker (design §4). Unit-level:
drives TokenCache directly against fake_server, no orchestrator involved.
"""

import pytest

import run_auth


def _cache(fake_server, **overrides):
    cfg = {
        "mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
        "refreshToken": "x=r", "tenant": "t",
    }
    return run_auth.TokenCache(cfg, **overrides)


def test_breaker_opens_after_max_consecutive_mint_failures(fake_server):
    fake_server.set_responses("/token", [{"status": 401, "body": "nope"}])
    cache = _cache(fake_server, max_consecutive_mint_failures=3)

    with pytest.raises(run_auth.TokenMintFailed):
        cache.get()
    with pytest.raises(run_auth.TokenMintFailed):
        cache.force_refresh()
    with pytest.raises(run_auth.TokenCircuitOpen) as exc_info:
        cache.force_refresh()

    assert exc_info.value.consecutive_failures == 3


def test_breaker_resets_counter_on_intervening_success(fake_server):
    fake_server.set_responses("/token", [
        {"status": 401, "body": "nope"},
        {"status": 200, "body": '{"accessToken":"tok"}'},
        {"status": 401, "body": "nope"},
    ])
    cache = _cache(fake_server, max_consecutive_mint_failures=2)

    with pytest.raises(run_auth.TokenMintFailed):
        cache.force_refresh()  # failure 1
    cache.force_refresh()  # success — resets counter to 0
    with pytest.raises(run_auth.TokenMintFailed):
        cache.force_refresh()  # failure 1 again, not 2 — must not open


def test_breaker_disabled_keeps_todays_continue_and_flag_behaviour(fake_server):
    fake_server.set_responses("/token", [{"status": 401, "body": "nope"}])
    cache = _cache(fake_server, max_consecutive_mint_failures=1, breaker_enabled=False)

    for _ in range(5):
        with pytest.raises(run_auth.TokenMintFailed):
            cache.force_refresh()


def test_circuit_open_last_error_scrubs_refresh_token_value(fake_server):
    fake_server.set_responses("/token", [{"status": 500, "body": "x=r rejected upstream"}])
    cfg = {
        "mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
        "refreshToken": "x=r", "tenant": "t",
    }
    cache = run_auth.TokenCache(cfg, max_consecutive_mint_failures=1)

    with pytest.raises(run_auth.TokenCircuitOpen) as exc_info:
        cache.force_refresh()

    assert "x=r" not in exc_info.value.last_error


def test_token_refresh_exhausted_carries_a_descriptive_last_error(fake_server):
    fake_server.set_responses("/token", [{"status": 200, "body": '{"accessToken":"tok"}'}])
    cache = run_auth.TokenCache(
        {"mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"), "refreshToken": "x=r", "tenant": "t"},
        max_refreshes=0,
    )
    epoch = cache.get()[1]
    with pytest.raises(run_auth.TokenRefreshExhausted) as exc_info:
        cache.refresh(epoch)

    assert "0" in exc_info.value.last_error


def test_open_circuit_short_circuits_further_mint_attempts(fake_server):
    """Once the breaker has tripped, a caller still holding the lock queue
    (e.g. another parallel worker) must not make another real network call
    to a known-dead identity endpoint — it should fail fast instead."""
    fake_server.set_responses("/token", [{"status": 500, "body": "down"}])
    cache = _cache(fake_server, max_consecutive_mint_failures=2)

    with pytest.raises(run_auth.TokenMintFailed):
        cache.force_refresh()
    with pytest.raises(run_auth.TokenCircuitOpen):
        cache.force_refresh()

    token_calls_before = len(fake_server.requests)
    with pytest.raises(run_auth.TokenCircuitOpen):
        cache.force_refresh()
    assert len(fake_server.requests) == token_calls_before


def test_circuit_open_last_error_scrubs_env_var_fallback_refresh_token(fake_server, monkeypatch):
    """refreshToken can be left blank, relying on the documented
    REFRESH_TOKEN env-var fallback (run_api_from_csv.generate_token). The
    scrub must catch that resolved secret too, not just the config field."""
    monkeypatch.setenv("REFRESH_TOKEN", "env-secret-value")
    fake_server.set_responses("/token", [{"status": 500, "body": "env-secret-value rejected upstream"}])
    cfg = {
        "mode": "refresh-cookie", "tokenUrl": fake_server.url("/token"),
        "refreshToken": "", "tenant": "t",
    }
    cache = run_auth.TokenCache(cfg, max_consecutive_mint_failures=1)

    with pytest.raises(run_auth.TokenCircuitOpen) as exc_info:
        cache.force_refresh()

    assert "env-secret-value" not in exc_info.value.last_error
