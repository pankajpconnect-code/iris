import pytest

import proxy_resolver
from urllib.parse import urlparse


def test_resolve_proxy_none_settings_returns_none():
    assert proxy_resolver.resolve_proxy(None, "example.com") is None


def test_resolve_proxy_custom_mode_returns_url_for_both_schemes():
    settings = {"mode": "custom", "url": "http://127.0.0.1:8080", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(settings, "example.com") == {
        "http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080",
    }


def test_resolve_proxy_custom_mode_empty_url_returns_none():
    settings = {"mode": "custom", "url": "", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(settings, "example.com") == {"http": None, "https": None}


def test_resolve_proxy_custom_mode_whitespace_only_url_returns_none():
    settings = {"mode": "custom", "url": "   ", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(settings, "example.com") == {"http": None, "https": None}


def test_resolve_proxy_custom_mode_embeds_auth_in_url():
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "alice", "password": "s3cret", "bypassList": []}
    result = proxy_resolver.resolve_proxy(settings, "example.com")
    assert result == {
        "http": "http://alice:s3cret@proxy.local:8080",
        "https": "http://alice:s3cret@proxy.local:8080",
    }


def test_resolve_proxy_custom_mode_percent_encodes_special_characters_in_credentials():
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "al ice", "password": "p@ss:word", "bypassList": []}
    result = proxy_resolver.resolve_proxy(settings, "example.com")
    assert result["http"] == "http://al%20ice:p%40ss%3Aword@proxy.local:8080"


def test_resolve_proxy_custom_mode_username_without_password():
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "alice", "password": "", "bypassList": []}
    result = proxy_resolver.resolve_proxy(settings, "example.com")
    assert result["http"] == "http://alice@proxy.local:8080"


def test_resolve_proxy_custom_mode_percent_encodes_slash_in_password():
    """A '/' in the password must be percent-encoded (as %2F), not passed
    through raw — an unencoded '/' produces a malformed proxy URL that
    causes requests to raise InvalidURL with the plaintext password
    embedded in the exception text."""
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "alice", "password": "p/ss", "bypassList": []}
    result = proxy_resolver.resolve_proxy(settings, "example.com")
    assert result["http"] == "http://alice:p%2Fss@proxy.local:8080"


def test_resolve_proxy_custom_mode_percent_encodes_slash_in_username():
    """A '/' in the username must be percent-encoded so it isn't
    interpreted as a URL path separator, which would corrupt the proxy
    host."""
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "bob/x", "password": "", "bypassList": []}
    result = proxy_resolver.resolve_proxy(settings, "example.com")
    assert result["http"] == "http://bob%2Fx@proxy.local:8080"
    parsed = urlparse(result["http"])
    assert parsed.hostname == "proxy.local"
    assert parsed.port == 8080


def test_resolve_proxy_custom_mode_invalid_url_raises_value_error_without_leaking_credentials():
    settings = {
        "mode": "custom", "url": "not-a-url", "username": "secretuser", "password": "secretpass", "bypassList": [],
    }
    with pytest.raises(ValueError) as exc_info:
        proxy_resolver.resolve_proxy(settings, "example.com")
    message = str(exc_info.value)
    assert "secretuser" not in message
    assert "secretpass" not in message
    assert "not-a-url" not in message


def test_resolve_proxy_custom_mode_empty_host_raises_value_error():
    settings = {"mode": "custom", "url": "http://", "username": "", "password": "", "bypassList": []}
    with pytest.raises(ValueError):
        proxy_resolver.resolve_proxy(settings, "example.com")


def test_resolve_proxy_bypass_list_exact_match_returns_none():
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "", "password": "", "bypassList": ["example.com"]}
    assert proxy_resolver.resolve_proxy(settings, "example.com") == {"http": None, "https": None}


def test_resolve_proxy_bypass_list_is_case_insensitive():
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "", "password": "", "bypassList": ["Example.COM"]}
    assert proxy_resolver.resolve_proxy(settings, "example.com") == {"http": None, "https": None}


def test_resolve_proxy_bypass_list_suffix_match_returns_none():
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "", "password": "", "bypassList": [".internal.corp"]}
    assert proxy_resolver.resolve_proxy(settings, "foo.internal.corp") == {"http": None, "https": None}


def test_resolve_proxy_bypass_list_suffix_does_not_match_bare_domain():
    settings = {"mode": "custom", "url": "http://proxy.local:8080", "username": "", "password": "", "bypassList": [".internal.corp"]}
    result = proxy_resolver.resolve_proxy(settings, "internal.corp")
    assert result == {"http": "http://proxy.local:8080", "https": "http://proxy.local:8080"}


def test_resolve_proxy_system_mode_returns_none_lets_requests_use_system_config(monkeypatch):
    """System mode delegates entirely to requests' own proxies=None handling,
    which natively discovers system/env proxy config (and its NO_PROXY
    handling) — resolve_proxy must not duplicate that logic itself."""
    system_settings = {"mode": "system", "url": "", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(system_settings, "example.com") is None


def test_resolve_proxy_system_mode_no_proxies_returns_none(monkeypatch):
    system_settings = {"mode": "system", "url": "", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(system_settings, "example.com") is None


def test_resolve_proxy_env_mode_reads_env_vars(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:8080")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    settings = {"mode": "env", "url": "", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(settings, "example.com") == {"http": "http://env-proxy:8080"}


def test_resolve_proxy_env_mode_no_env_vars_returns_none(monkeypatch):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    settings = {"mode": "env", "url": "", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(settings, "example.com") == {"http": None, "https": None}


def test_resolve_proxy_env_mode_no_proxy_env_var_bypasses(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:8080")
    monkeypatch.setenv("NO_PROXY", "example.com")
    settings = {"mode": "env", "url": "", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(settings, "example.com") == {"http": None, "https": None}


def test_resolve_proxy_env_mode_no_proxy_star_bypasses_everything(monkeypatch):
    """NO_PROXY=* is curl/requests-standard shorthand for 'bypass all
    hosts' — the custom bypass-list matcher used for the UI's own
    bypassList field doesn't understand this, so env mode must delegate
    to urllib.request.proxy_bypass_environment instead."""
    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:8080")
    monkeypatch.setenv("NO_PROXY", "*")
    settings = {"mode": "env", "url": "", "username": "", "password": "", "bypassList": []}
    assert proxy_resolver.resolve_proxy(settings, "anyhost.example.com") == {"http": None, "https": None}
