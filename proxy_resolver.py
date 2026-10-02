"""Resolves the effective outbound proxy configuration for one request,
given the user's iris.proxySettings object and the request's target host.
Kept separate from collection_routes.py, which is already over this repo's
500-line file-size limit.
"""

import os
import urllib.request
from urllib.parse import quote, urlparse


def _matches_bypass_pattern(target_host, pattern):
    pattern = pattern.strip().lower()
    target_host = (target_host or "").lower()
    if not pattern:
        return False
    if pattern.startswith("."):
        return target_host.endswith(pattern)
    return target_host == pattern


def _host_bypassed(target_host, patterns):
    return any(_matches_bypass_pattern(target_host, p) for p in patterns)


def _env_proxies():
    proxies = {}
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


def _env_no_proxy_bypassed(target_host):
    # Delegate to urllib's own NO_PROXY matcher rather than the UI's
    # bypassList matcher above: real NO_PROXY semantics (curl/requests)
    # include a bare "*" meaning "bypass everything", which the simple
    # exact/dot-prefix matcher doesn't understand.
    return urllib.request.proxy_bypass_environment(target_host or "")


def _validate_custom_proxy_url(url):
    # Deliberately excludes the raw url/username/password from the
    # exception message — this can surface in the Send response's error
    # field and get persisted to disk via the Runner's run history JSON.
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid proxy URL")


def _custom_proxy_url(settings):
    url = (settings.get("url") or "").strip()
    if not url:
        return None
    _validate_custom_proxy_url(url)
    username = settings.get("username") or ""
    password = settings.get("password") or ""
    if not username:
        return url
    parsed = urlparse(url)
    credentials = (
        f"{quote(username, safe='')}:{quote(password, safe='')}@"
        if password
        else f"{quote(username, safe='')}@"
    )
    return parsed._replace(netloc=credentials + parsed.netloc).geturl()


def _no_proxy():
    # Returned instead of None for "no proxy to use right now" outcomes.
    # requests treats proxies=None as "consult the environment/OS proxy
    # settings myself" — not "use no proxy" — which would silently defeat
    # the bypass-list feature and env mode's independence from OS config.
    # {"http": None, "https": None} is what actually forces requests to
    # skip proxying for both schemes. A fresh dict is returned each call
    # so callers can't accidentally mutate shared state.
    return {"http": None, "https": None}


def resolve_proxy(settings, target_host):
    if not settings:
        return None
    if _host_bypassed(target_host, settings.get("bypassList") or []):
        return _no_proxy()
    mode = settings.get("mode") or "custom"
    if mode == "system":
        # requests already natively discovers system/env proxy config
        # (including its own NO_PROXY handling) when given proxies=None —
        # duplicating that via urllib.request.getproxies() here would only
        # re-implement it with weaker bypass support.
        return None
    if mode == "env":
        if _env_no_proxy_bypassed(target_host):
            return _no_proxy()
        return _env_proxies() or _no_proxy()
    url = _custom_proxy_url(settings)
    return {"http": url, "https": url} if url else _no_proxy()
