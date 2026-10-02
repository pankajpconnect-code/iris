"""HTTP-agnostic route handlers for the API console's environment endpoints.

Kept separate from server.py and collection_routes.py for the same reason
those are split out — server.py is already over this repo's 500-line limit
and should only dispatch, not implement.
"""

import re
from urllib.parse import unquote

import environment_store

_LIST_RE = re.compile(r"^/api/environments$")
# Deliberately NOT nested under /api/environments/ — that prefix's
# _ITEM_RE below treats any single path segment as a slug, and slugify()
# can legally produce "divergence" from an environment literally named
# that. A flat, hyphenated sibling path can never collide with a slug.
_DIVERGENCE_RE = re.compile(r"^/api/environment-divergence$")
_ITEM_RE = re.compile(r"^/api/environments/([^/]+)$")
_VARS_RE = re.compile(r"^/api/environments/([^/]+)/vars$")
_VARS_STATE_RE = re.compile(r"^/api/environments/([^/]+)/vars-state$")
_VAR_ITEM_RE = re.compile(r"^/api/environments/([^/]+)/vars/([^/]+)$")
_VAR_ENABLED_RE = re.compile(r"^/api/environments/([^/]+)/vars/([^/]+)/enabled$")


def handle_get(store, path):
    if _LIST_RE.match(path):
        return 200, {"environments": store.list()}
    if _DIVERGENCE_RE.match(path):
        return 200, {"divergence": store.divergence()}
    match = _ITEM_RE.match(path)
    if match:
        return _get_environment(store, match.group(1))
    match = _VARS_STATE_RE.match(path)
    if match:
        return _get_vars_state(store, match.group(1))
    match = _VARS_RE.match(path)
    if match:
        return _get_vars(store, match.group(1))
    return None


def handle_post(store, path, data):
    if _LIST_RE.match(path):
        return _create_environment(store, data)
    return None


def handle_put(store, path, data):
    match = _VAR_ENABLED_RE.match(path)
    if match:
        return _set_var_enabled(store, match.group(1), unquote(match.group(2)), data)
    match = _VARS_RE.match(path)
    if match:
        return _set_vars(store, match.group(1), data)
    return None


def handle_delete(store, path):
    match = _VAR_ITEM_RE.match(path)
    if match:
        return _delete_var(store, match.group(1), unquote(match.group(2)))
    match = _ITEM_RE.match(path)
    if match:
        store.delete(match.group(1))
        return 200, {"deleted": True}
    return None


def _create_environment(store, data):
    name = str((data or {}).get("name") or "").strip()
    if not name:
        return 400, {"error": "Environment name is required"}
    try:
        slug = store.create(name)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, {"slug": slug, "name": name}


def _get_environment(store, slug):
    try:
        data = store.get(slug)
    except environment_store.EnvironmentNotFound as exc:
        return 404, {"error": str(exc)}
    except environment_store.EnvironmentCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"slug": slug, "name": data.get("name", slug), "vars": data.get("vars", {})}


def _get_vars(store, slug):
    try:
        variables = store.get_vars(slug)
    except environment_store.EnvironmentNotFound as exc:
        return 404, {"error": str(exc)}
    except environment_store.EnvironmentCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"variables": variables}


def _set_vars(store, slug, data):
    if not isinstance(data, dict):
        return 400, {"error": "Vars body must be a JSON object"}
    try:
        store.set_vars(slug, data)
        variables = store.get_vars(slug)
    except environment_store.EnvironmentNotFound as exc:
        return 404, {"error": str(exc)}
    except environment_store.EnvironmentCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"variables": variables}


def _get_vars_state(store, slug):
    try:
        variables = store.get_vars_state(slug)
    except environment_store.EnvironmentNotFound as exc:
        return 404, {"error": str(exc)}
    except environment_store.EnvironmentCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"variables": variables}


def _delete_var(store, slug, name):
    try:
        store.delete_var(slug, name)
        variables = store.get_vars_state(slug)
    except environment_store.EnvironmentNotFound as exc:
        return 404, {"error": str(exc)}
    except environment_store.EnvironmentCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"variables": variables}


def _set_var_enabled(store, slug, name, data):
    if not isinstance(data, dict) or "enabled" not in data:
        return 400, {"error": "Body must be a JSON object with an 'enabled' boolean"}
    try:
        store.set_var_enabled(slug, name, bool(data["enabled"]))
        variables = store.get_vars_state(slug)
    except environment_store.EnvironmentNotFound as exc:
        return 404, {"error": str(exc)}
    except environment_store.EnvironmentCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"variables": variables}
