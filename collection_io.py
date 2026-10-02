"""Collection JSON parse/export (v2.1 schema) and {{var}} substitution."""

import copy
import re

import collection_redaction
import collection_script_translation

# _is_v21 below only checks for the "v2.1" substring, not this exact domain —
# so this only has to self-identify our own exports, not match any specific
# third-party schema registry.
SCHEMA_V21 = "https://schema.iris.internal/json/collection/v2.1.0/collection.json"

_VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def _is_v21(collection):
    schema = collection.get("info", {}).get("schema", "")
    return "v2.1" in schema and "item" in collection


def _url_of(request):
    url = request.get("url", "")
    if isinstance(url, dict):
        return url.get("raw", "")
    return url


def _headers_of(request):
    headers = []
    for header in request.get("header", []):
        if not isinstance(header, dict) or header.get("disabled"):
            continue
        headers.append({"key": header.get("key", ""), "value": header.get("value", "")})
    return headers


def _body_of(request):
    body = request.get("body")
    if not body:
        return ""
    mode = body.get("mode")
    if mode == "raw":
        return body.get("raw", "")
    return ""


def _body_mode_of(request):
    body = request.get("body")
    return "urlencoded" if body and body.get("mode") == "urlencoded" else "raw"


def _body_params_of(request):
    body = request.get("body")
    if not body or body.get("mode") != "urlencoded":
        return []
    return [
        {"key": p.get("key", ""), "value": p.get("value", ""), "enabled": not p.get("disabled")}
        for p in body.get("urlencoded") or []
        if isinstance(p, dict) and p.get("key")
    ]


# The only body modes _body_of()/_body_params_of() actually carry content
# for — anything else (formdata, file, graphql, or no mode at all on a
# non-empty body) silently becomes an empty string/list there, so _walk()
# below surfaces it the way collection_script_translation.translate_scripts()
# surfaces `untranslated`, rather than an imported request quietly ending up
# with no body.
# "urlencoded" is excluded here (unlike before this feature) — Iris can now
# author and send that mode itself, so it is no longer unsupported.
def _unsupported_body_mode(request):
    body = request.get("body")
    if not body:
        return None
    mode = body.get("mode")
    return None if mode in ("raw", "urlencoded") else mode


def _auth_entry_value(source_auth, auth_type, key, default=""):
    for entry in source_auth.get(auth_type) or []:
        if isinstance(entry, dict) and entry.get("key") == key:
            return entry.get("value", default)
    return default


_IRIS_AUTH_MODES = {"bearer", "basic", "apikey"}


def _translate_auth(source_auth):
    """Translates a raw source-collection-format auth block into the
    {mode, ...} shape every other part of Iris (collection_routes._apply_auth,
    the Auth tab) reads.
    Returns (iris_auth, unsupported_type) — unsupported_type is set whenever
    the block can't be translated (oauth2, digest, awsv4, ntlm, hawk,
    edgegrid, or no "type" at all) so the caller can surface it rather than
    silently dropping the request's real auth intent.

    Also accepts a block already in Iris's own {mode, ...} shape (no "type"
    key) and passes it through unchanged — otherwise re-importing a
    collection Iris itself just exported (to_collection writes auth out in
    this same shape) would misread every request's own auth as unsupported."""
    if not isinstance(source_auth, dict):
        return None, "unspecified"
    if "type" not in source_auth and source_auth.get("mode") in _IRIS_AUTH_MODES:
        return dict(source_auth), None
    auth_type = source_auth.get("type")
    if auth_type == "noauth":
        return None, None
    if auth_type == "bearer":
        return {"mode": "bearer", "bearerToken": _auth_entry_value(source_auth, "bearer", "token")}, None
    if auth_type == "basic":
        return {
            "mode": "basic",
            "basicUser": _auth_entry_value(source_auth, "basic", "username"),
            "basicPassword": _auth_entry_value(source_auth, "basic", "password"),
        }, None
    if auth_type == "apikey":
        location = "query" if _auth_entry_value(source_auth, "apikey", "in") == "query" else "header"
        return {
            "mode": "apikey",
            "apiKeyName": _auth_entry_value(source_auth, "apikey", "key"),
            "apiKeyValue": _auth_entry_value(source_auth, "apikey", "value"),
            "apiKeyLocation": location,
        }, None
    return None, auth_type or "unspecified"


def _walk(items, inherited_auth=None, folder_path=()):
    """folder_path threads the chain of ancestor Postman folder NAMES down
    to each leaf request, mirroring how inherited_auth threads down. It is
    never baked into a request's own `name` — instead each leaf request
    carries its ancestor chain as a separate `folderPath` list;
    _import_collection (import_routes.py) walks that list to create/reuse
    real Iris folders and set `folderId`.

    This keeps _walk a pure JSON-in/JSON-out function with no store access —
    resolving folder ids against the collection's current `folders` list
    needs the store, which belongs in import_routes.py, not here."""
    requests = []
    untranslated = []
    unsupported_body_modes = []
    unsupported_auth_types = []
    for item in items:
        if not isinstance(item, dict) or "name" not in item:
            location = " / ".join(folder_path) if folder_path else "root"
            raise ValueError(f"Malformed collection: an item under '{location}' has no 'name'")
        name = item["name"]
        if "item" in item:
            if not isinstance(item["item"], list):
                raise ValueError(f"Malformed collection: '{name}' has a non-list 'item' (folder contents)")
            # item.get("auth") rather than "auth" in item — an explicit
            # `"auth": null` is not the same as an explicit noauth/unsupported
            # override, it just means this folder didn't set its own and
            # should still inherit.
            if item.get("auth") is not None:
                folder_auth, unsupported_type = _translate_auth(item["auth"])
                if unsupported_type:
                    unsupported_auth_types.append({"request": name, "type": unsupported_type})
            else:
                folder_auth = inherited_auth
            nested_requests, nested_untranslated, nested_unsupported, nested_unsupported_auth = _walk(
                item["item"], folder_auth, folder_path + (name,)
            )
            requests.extend(nested_requests)
            untranslated.extend(nested_untranslated)
            unsupported_body_modes.extend(nested_unsupported)
            unsupported_auth_types.extend(nested_unsupported_auth)
        else:
            request = item.get("request")
            if not isinstance(request, dict) or "method" not in request:
                raise ValueError(f"Malformed collection: '{name}' has no valid 'request' object")
            parsed = {
                "name": name,
                "method": request["method"],
                "url": _url_of(request),
                "headers": _headers_of(request),
                "body": _body_of(request),
            }
            if folder_path:
                parsed["folderPath"] = list(folder_path)
            # Only set for urlencoded (mirroring how "tests"/"auth" below are
            # only added when present) — this keeps a plain raw-body import
            # producing the exact same shape it always has, with no new keys
            # a caller that pre-dates this feature would have to account for.
            if _body_mode_of(request) == "urlencoded":
                parsed["bodyMode"] = "urlencoded"
                parsed["bodyParams"] = _body_params_of(request)
            unsupported_mode = _unsupported_body_mode(request)
            if unsupported_mode:
                unsupported_body_modes.append({"request": name, "mode": unsupported_mode})
            # A "tests" field on request is our own export round-trip extension
            # (see to_collection) — not part of the standard v2.1 schema, so
            # other tools' exports never carry it and this is a no-op for them.
            custom_tests = request.get("tests") or []
            script_tests, item_untranslated = collection_script_translation.translate_scripts(item.get("event"))
            tests = custom_tests + script_tests
            if tests:
                parsed["tests"] = tests
            if request.get("auth") is not None:
                effective_auth, unsupported_type = _translate_auth(request["auth"])
                if unsupported_type:
                    unsupported_auth_types.append({"request": name, "type": unsupported_type})
            else:
                effective_auth = inherited_auth
            if effective_auth:
                parsed["auth"] = effective_auth
            for script in item_untranslated:
                untranslated.append({"request": name, "script": script})
            requests.append(parsed)
    return requests, untranslated, unsupported_body_modes, unsupported_auth_types


def _extract_variables(requests):
    variables = set()
    for request in requests:
        variables.update(_VAR_PATTERN.findall(request["url"]))
        for header in request["headers"]:
            variables.update(_VAR_PATTERN.findall(header["value"]))
        variables.update(_VAR_PATTERN.findall(request["body"]))
        for param in request.get("bodyParams") or []:
            variables.update(_VAR_PATTERN.findall(param.get("value", "")))
    return sorted(variables)


def parse_collection(collection):
    if not isinstance(collection, dict) or not _is_v21(collection):
        raise ValueError("Not a v2.1 collection")
    inherited_auth = None
    unsupported_auth_types = []
    if collection.get("auth") is not None:
        inherited_auth, unsupported_type = _translate_auth(collection["auth"])
        if unsupported_type:
            unsupported_auth_types.append({"request": "<collection>", "type": unsupported_type})
    requests, untranslated, unsupported_body_modes, nested_unsupported_auth = _walk(
        collection.get("item", []), inherited_auth=inherited_auth
    )
    unsupported_auth_types.extend(nested_unsupported_auth)
    result = {"requests": requests, "variables": _extract_variables(requests)}
    description = collection.get("info", {}).get("description")
    # The v2.1 schema allows info.description to be a plain string OR an
    # object {content, type, version?} — extract the text out of the object
    # form rather than storing the raw dict, which would otherwise reach the
    # sidebar's `textContent = description` as the literal "[object Object]".
    if isinstance(description, dict):
        description = description.get("content")
    if description:
        result["description"] = description
    if untranslated:
        result["untranslatedScripts"] = untranslated
    if unsupported_body_modes:
        result["unsupportedBodyModes"] = unsupported_body_modes
    if unsupported_auth_types:
        result["unsupportedAuthTypes"] = unsupported_auth_types
    return result


def _body_field_for_export(request):
    if request.get("bodyMode") == "urlencoded":
        # Standard v2.1 urlencoded shape — the same shape parse_collection's
        # _body_params_of already reads back on import, so this round-trips
        # through Iris (and is at least legible to any other v2.1-consuming
        # tool) instead of the previous hardcoded raw-mode shape silently
        # dropping the entire body for a urlencoded-mode request.
        return {
            "mode": "urlencoded",
            "urlencoded": collection_redaction.redact_body_params_for_export([
                {"key": p["key"], "value": p.get("value", ""), "disabled": not p.get("enabled", True)}
                for p in request.get("bodyParams") or []
            ]),
        }
    return {"mode": "raw", "raw": request.get("body", "")}


def to_collection(name, requests):
    items = []
    for request in requests:
        request_obj = {
            "method": request["method"],
            "url": {"raw": request["url"]},
            "header": collection_redaction.redact_headers_for_export([
                {"key": header["key"], "value": header["value"]}
                for header in request["headers"]
            ]),
            "body": _body_field_for_export(request),
        }
        # "tests" is a custom (non-standard) field carrying our declarative
        # Tests-tab rows, so export -> import round-trips them instead of
        # silently dropping that data; collection viewers generally tolerate
        # unknown fields on the request object.
        if request.get("tests"):
            request_obj["tests"] = request["tests"]
        if "auth" in request:
            request_obj["auth"] = collection_redaction.redact_auth_for_export(request["auth"])
        items.append({"name": request["name"], "request": request_obj})
    return {"info": {"name": name, "schema": SCHEMA_V21}, "item": items}


def substitute(text, variables):
    def _replace(match):
        key = match.group(1)
        if key in variables:
            return str(variables[key])
        return match.group(0)

    return _VAR_PATTERN.sub(_replace, text)


def resolve_request(request, variables):
    resolved = copy.deepcopy(request)
    resolved["url"] = substitute(resolved["url"], variables)
    resolved["headers"] = [
        {"key": header["key"], "value": substitute(header["value"], variables), "enabled": header.get("enabled", True)}
        for header in resolved["headers"]
    ]
    resolved["body"] = substitute(resolved.get("body", ""), variables)
    resolved["bodyParams"] = [
        {"key": param["key"], "value": substitute(param.get("value", ""), variables), "enabled": param.get("enabled", True)}
        for param in resolved.get("bodyParams") or []
    ]
    return resolved
