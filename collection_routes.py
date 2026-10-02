"""HTTP-agnostic route handlers for the API console's collection endpoints.

Kept separate from server.py, which is already over this repo's 500-line
file-size limit — server.py should only dispatch to these, not implement.
"""

import base64
import re
import time
import types
from urllib.parse import unquote, urlencode, urlparse

import requests

import assertions
import collection_io
import collection_store
import environment_store
import oauth2_client_credentials
import proxy_resolver
import run_api_from_csv


class _InlinePythonTestRejected(ValueError):
    """Raised when a `type: "python"` test row arrives via an inline (unsaved)
    request body on /api/send-one rather than a saved collection request."""


_LIST_RE = re.compile(r"^/api/collections$")
_ITEM_RE = re.compile(r"^/api/collections/([^/]+)$")
_ARCHIVE_RE = re.compile(r"^/api/collections/([^/]+)/archive$")
_EXPORT_RE = re.compile(r"^/api/collections/([^/]+)/export$")
_REQUESTS_RE = re.compile(r"^/api/collections/([^/]+)/requests$")
_REQUEST_ITEM_RE = re.compile(r"^/api/collections/([^/]+)/requests/([^/]+)$")
_VARS_RE = re.compile(r"^/api/collections/([^/]+)/vars$")
_SEND_ONE_RE = re.compile(r"^/api/send-one$")


def handle_get(store, path):
    if _LIST_RE.match(path):
        return 200, {"collections": store.list()}
    match = _ITEM_RE.match(path)
    if match:
        return _get_collection(store, match.group(1))
    match = _EXPORT_RE.match(path)
    if match:
        return _export_collection(store, match.group(1))
    match = _VARS_RE.match(path)
    if match:
        return _get_vars(store, match.group(1))
    return None


def handle_post(store, path, data, env_store=None):
    if _LIST_RE.match(path):
        return _create_collection(store, data)
    match = _ARCHIVE_RE.match(path)
    if match:
        return _set_archived(store, match.group(1), data)
    match = _REQUESTS_RE.match(path)
    if match:
        return _save_request(store, match.group(1), data)
    if _SEND_ONE_RE.match(path):
        return _send_one(store, data, env_store)
    return None


def handle_put(store, path, data):
    match = _VARS_RE.match(path)
    if match:
        return _set_vars(store, match.group(1), data)
    match = _REQUEST_ITEM_RE.match(path)
    if match:
        return _rename_request(store, match.group(1), unquote(match.group(2)), data)
    return None


def handle_delete(store, path):
    match = _REQUEST_ITEM_RE.match(path)
    if match:
        try:
            store.delete_request(match.group(1), unquote(match.group(2)))
        except collection_store.CollectionNotFound as exc:
            return 404, {"error": str(exc)}
        except collection_store.CollectionCorrupted as exc:
            return 409, {"error": str(exc)}
        return 200, {"deleted": True}
    match = _ITEM_RE.match(path)
    if match:
        store.delete(match.group(1))
        return 200, {"deleted": True}
    return None


def _create_collection(store, data):
    name = str((data or {}).get("name") or "").strip()
    if not name:
        return 400, {"error": "Collection name is required"}
    try:
        slug = store.create(name)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, {"slug": slug, "name": name}


def _get_collection(store, slug):
    try:
        data = store.get(slug)
    except collection_store.CollectionNotFound as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    response = {
        "slug": slug,
        "name": data.get("name", slug),
        "requests": data.get("requests", []),
        "folders": data.get("folders", []),
    }
    if data.get("description"):
        response["description"] = data["description"]
    return 200, response


def _export_collection(store, slug):
    try:
        data = store.get(slug)
    except collection_store.CollectionNotFound as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, collection_io.to_collection(data.get("name", slug), data.get("requests", []))


def _set_archived(store, slug, data):
    archived = bool((data or {}).get("archived"))
    try:
        store.set_archived(slug, archived)
    except collection_store.CollectionNotFound as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"archived": archived}


def _rename_request(store, slug, old_name, data):
    if not isinstance(data, dict):
        return 400, {"error": "Request name is required"}
    new_name = str(data.get("name") or "").strip()
    if not new_name:
        return 400, {"error": "Request name is required"}
    try:
        store.rename_request(slug, old_name, new_name)
    except collection_store.CollectionNotFound as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"renamed": True}


def _save_request(store, slug, data):
    if not isinstance(data, dict) or not str(data.get("name") or "").strip():
        return 400, {"error": "Request name is required"}
    request = {
        "name": data["name"],
        "method": (data.get("method") or "GET").upper(),
        "url": data.get("url", ""),
        "headers": [
            {"key": h.get("key", ""), "value": h.get("value", ""), "enabled": bool(h.get("enabled", True))}
            for h in (data.get("headers") or [])
            if isinstance(h, dict) and h.get("key")
        ],
        "body": data.get("body", ""),
        "bodyMode": data.get("bodyMode") or "raw",
        "bodyParams": [
            {"key": p.get("key", ""), "value": p.get("value", ""), "enabled": bool(p.get("enabled", True))}
            for p in (data.get("bodyParams") or [])
            if isinstance(p, dict) and p.get("key")
        ],
        "tests": data.get("tests") or [],
    }
    # auth has no editor in the UI, so the save payload never carries it —
    # carry forward an imported request's existing auth rather than treating
    # its absence here as "auth removed".
    try:
        existing = store.get(slug)
    except (collection_store.CollectionNotFound, collection_store.CollectionCorrupted):
        existing = {}
    existing_request = next(
        (r for r in existing.get("requests", []) if r.get("name") == request["name"]), {}
    )
    if "auth" in existing_request:
        request["auth"] = existing_request["auth"]
    # Same reasoning as auth above: the request-panel Save button has no
    # folder editor either, so an edit-save must never silently un-assign a
    # request's folder just because the payload didn't mention it (or ignore
    # a stale one it does carry — see the "conflicting folderId" test). A
    # create (existing_request == {}) takes folderId from the payload
    # instead — that's how a folder's own "+" button assigns the new
    # request's folder. Either way, the id must belong to THIS collection:
    # a tab opened against a folder in one collection but saved into another
    # (e.g. the user switched collections before hitting Save) must not
    # persist a dangling cross-collection reference — it's dropped instead,
    # same as any other folderId group has() doesn't recognize.
    folder_id = existing_request.get("folderId") if existing_request else data.get("folderId")
    valid_folder_ids = {f.get("id") for f in existing.get("folders", []) if isinstance(f, dict)}
    if folder_id and folder_id in valid_folder_ids:
        request["folderId"] = folder_id
    try:
        store.save_request(slug, request)
    except collection_store.CollectionNotFound as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"saved": True, "request": request}


def _get_vars(store, slug):
    try:
        variables = store.get_vars(slug)
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"variables": variables}


def _set_vars(store, slug, data):
    if not isinstance(data, dict):
        return 400, {"error": "Vars body must be a JSON object"}
    try:
        store.set_vars(slug, data)
        variables = store.get_vars(slug)
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"variables": variables}


def _resolve_send_one_request(store, data, env_store=None, extra_vars=None):
    slug = data.get("slug")
    request_name = data.get("requestName")
    variables = store.get_vars(slug) if slug else {}
    env_slug = data.get("environmentSlug")
    if env_slug and env_store is not None:
        try:
            variables = environment_store.merge_variables(variables, env_store.get_vars(env_slug))
        except environment_store.EnvironmentNotFound:
            pass
    if extra_vars:
        variables = {**variables, **extra_vars}
    if slug and request_name:
        collection = store.get(slug)
        match = next(
            (r for r in collection.get("requests", []) if r.get("name") == request_name), None
        )
        if match is None:
            raise ValueError(f"Unknown request '{request_name}' in '{slug}'")
        return collection_io.resolve_request(match, variables), variables
    inline = data.get("request")
    if isinstance(inline, dict) and inline.get("url"):
        inline_tests = inline.get("tests") or []
        # The raw-Python escape hatch is only for requests already saved in a
        # collection (author-side) — never for a `tests`
        # list arriving inline in the POST body, which would let any caller of
        # this endpoint eval() arbitrary code with no save step required.
        if any(isinstance(t, dict) and t.get("type") == "python" for t in inline_tests):
            raise _InlinePythonTestRejected(
                "Raw-Python test rows are only allowed on requests saved in a "
                "collection — save this request first, then run it via slug/requestName."
            )
        request = {
            "method": (inline.get("method") or "GET").upper(),
            "url": inline["url"],
            "headers": inline.get("headers") or [],
            "body": inline.get("body") or "",
            "bodyMode": inline.get("bodyMode") or "raw",
            # Same defensive filter _save_request applies to a saved
            # request's bodyParams (isinstance/has-a-key) — an inline
            # (unsaved) send has no equivalent save-time cleanup, so a
            # malformed entry here would otherwise reach resolve_request's
            # direct param["key"] subscript as a raw KeyError/TypeError.
            "bodyParams": [
                p for p in (inline.get("bodyParams") or [])
                if isinstance(p, dict) and p.get("key")
            ],
            "tests": inline_tests,
        }
        return collection_io.resolve_request(request, variables), variables
    raise ValueError("Provide either {slug, requestName} or an inline {request}")


def _apply_auth(auth, headers, timeout, request):
    auth = auth or {}
    mode = auth.get("mode") or "none"
    if mode == "apikey":
        name = str(auth.get("apiKeyName") or "").strip()
        value = str(auth.get("apiKeyValue") or "")
        if not name:
            return
        if (auth.get("apiKeyLocation") or "header") == "query":
            separator = "&" if "?" in request["url"] else "?"
            request["url"] = f"{request['url']}{separator}{urlencode({name: value})}"
        else:
            headers[name] = value
        return
    if mode == "bearer":
        token = str(auth.get("bearerToken") or "").strip()
        if token:
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        tenant = str(auth.get("tenant") or "").strip()
        if tenant:
            headers.setdefault("x-tenant-identifier", tenant)
        return
    if mode == "basic":
        user = str(auth.get("basicUser") or "").strip()
        if user:
            password = str(auth.get("basicPassword") or "")
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        tenant = str(auth.get("tenant") or "").strip()
        if tenant:
            headers.setdefault("x-tenant-identifier", tenant)
        return
    if mode == "oauth2-client-credentials":
        token_url = str(auth.get("oauth2TokenUrl") or "").strip()
        if not token_url:
            return
        token = oauth2_client_credentials.mint_client_credentials_token(
            client_id=str(auth.get("oauth2ClientId") or ""),
            client_secret=str(auth.get("oauth2ClientSecret") or ""),
            token_url=token_url,
            scope=auth.get("oauth2Scope") or None,
            auth_style=auth.get("oauth2AuthStyle") or "basic-header",
            timeout=timeout,
        )
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        return
    if mode != "refresh-cookie":
        return
    token_url = str(auth.get("tokenUrl") or "").strip()
    if not token_url:
        return
    namespace = types.SimpleNamespace(
        refresh_token=auth.get("refreshToken") or "",
        refresh_token_env=auth.get("refreshTokenEnv") or "REFRESH_TOKEN",
        refresh_token_cookie_name=auth.get("refreshTokenCookieName") or "org.apache.fincn.refreshToken",
        token_url=token_url,
        tenant=auth.get("tenant") or "",
        token_field=auth.get("tokenField") or "accessToken",
        insecure=bool(auth.get("insecure")),
        timeout=timeout,
    )
    token = run_api_from_csv.generate_token(namespace)
    headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    if namespace.tenant:
        headers.setdefault("x-tenant-identifier", namespace.tenant)


def _outgoing_body_and_content_type(request):
    """Returns (body_bytes_or_None, default_content_type_or_None).
    "raw" (or no bodyMode at all, for back-compat with every request saved
    before this field existed) is unchanged: the body string as-is, no
    default Content-Type. "urlencoded" form-encodes the enabled, keyed
    bodyParams rows."""
    if request.get("bodyMode") == "urlencoded":
        pairs = [
            (p["key"], p.get("value", ""))
            for p in (request.get("bodyParams") or [])
            if p.get("enabled", True) and p.get("key")
        ]
        encoded = urlencode(pairs)
        if not encoded:
            return None, None
        return encoded.encode("utf-8"), "application/x-www-form-urlencoded"
    body = request.get("body")
    return (body.encode("utf-8") if body else None), None


def _strip_disabled_query_params(url):
    """Drops any `~`-prefixed query param (the Params tab's disabled-row
    marker, static/query-params.js's `~key` convention — mirrors the Headers
    tab's own `// `-prefix bulk-edit convention for "disabled but not
    discarded") before a URL reaches the wire or a display surface. Returns
    `url` byte-for-byte unchanged whenever nothing is disabled — the
    overwhelmingly common case — so this can never alter behavior for any
    existing collection with no `~` in its query string."""
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    if not query:
        return url
    segments = [s for s in query.split("&") if s]
    kept = [s for s in segments if not s.partition("=")[0].startswith("~")]
    if len(kept) == len(segments):
        return url
    return f"{base}?{'&'.join(kept)}" if kept else base


def _send_one(store, data, env_store=None, extra_vars=None, capture_sink=None, extra_headers=None):
    if not isinstance(data, dict):
        return 400, {"error": "Request body must be a JSON object"}
    try:
        request, variables = _resolve_send_one_request(store, data, env_store, extra_vars)
    except _InlinePythonTestRejected as exc:
        return 403, {"error": str(exc)}
    except (collection_store.CollectionCorrupted, environment_store.EnvironmentCorrupted) as exc:
        return 409, {"error": str(exc)}
    except ValueError as exc:
        return 404, {"error": str(exc)}
    headers = {h["key"]: h["value"] for h in request["headers"] if h.get("key") and h.get("enabled", True)}
    if extra_headers:
        headers.update(extra_headers)
    timeout = float(data.get("timeout") or 30)
    try:
        _apply_auth(data.get("auth"), headers, timeout, request)
    except (SystemExit, requests.RequestException, ValueError) as exc:
        return 502, {"error": str(exc) or "Token request failed"}
    body_bytes, default_content_type = _outgoing_body_and_content_type(request)
    if default_content_type and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = default_content_type
    target_host = urlparse(request["url"]).hostname
    proxies = proxy_resolver.resolve_proxy(data.get("proxySettings"), target_host)
    started = time.monotonic()
    try:
        response = requests.request(
            request["method"],
            _strip_disabled_query_params(request["url"]),
            headers=headers,
            data=body_bytes,
            timeout=timeout,
            verify=not bool(data.get("insecure")),
            proxies=proxies,
        )
    except requests.RequestException as exc:
        return 502, {"error": str(exc), "errorType": type(exc).__name__}
    elapsed_ms = int((time.monotonic() - started) * 1000)
    result = {
        "status": response.status_code,
        "elapsedMs": elapsed_ms,
        "sizeBytes": len(response.content),
        "headers": dict(response.headers),
        "body": response.text,
    }
    tests = request.get("tests") or []
    if tests:
        test_results, updated_variables = assertions.run_assertions(tests, result, variables)
        result["tests"] = test_results
        captured = {k: v for k, v in updated_variables.items() if variables.get(k) != v}
        if captured and capture_sink is not None:
            capture_sink.update(captured)
        elif captured:
            env_slug = data.get("environmentSlug")
            slug = data.get("slug")
            try:
                # A captured variable (e.g. a token pulled from a "Token
                # Generation" response) is meant to be usable across every
                # collection, not just the one it was captured in — so when an
                # environment is active, persist there (global scope). Only
                # fall back to the collection's own vars when no environment
                # is selected, so a capture always lands somewhere.
                if env_slug and env_store is not None:
                    env_store.set_vars(env_slug, captured)
                elif slug:
                    store.set_vars(slug, captured)
            except (
                collection_store.CollectionCorrupted,
                environment_store.EnvironmentCorrupted,
                environment_store.EnvironmentNotFound,
            ) as exc:
                # A capture already reported passed=True above (it did compute a
                # value) — surface the persistence failure so the UI doesn't show
                # a false "captured" with nothing actually saved.
                result.setdefault("warnings", []).append(
                    f"Captured variable(s) could not be saved: {exc}"
                )
    return 200, result
