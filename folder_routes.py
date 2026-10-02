"""HTTP-agnostic route handlers for one-level folders within a collection.

Split out of collection_routes.py, which is already close to this repo's
500-line file-size gate — the same reasoning that split collection_routes.py
out of server.py in the first place. Dispatched from server.py alongside
collection_routes and environment_routes.
"""

import re
from urllib.parse import unquote

import collection_store

_FOLDERS_RE = re.compile(r"^/api/collections/([^/]+)/folders$")
_FOLDER_ITEM_RE = re.compile(r"^/api/collections/([^/]+)/folders/([^/]+)$")
_FOLDER_PARENT_RE = re.compile(r"^/api/collections/([^/]+)/folders/([^/]+)/parent$")
_REQUEST_FOLDER_RE = re.compile(r"^/api/collections/([^/]+)/requests/([^/]+)/folder$")

# Mirrors collection_store._MAX_NAME_LENGTH's rationale (a misplaced paste —
# e.g. a whole JSON blob typed into a name field — shouldn't be accepted
# silently) even though a folder name, unlike a collection name, is never
# slugified into a filename.
_MAX_FOLDER_NAME_LENGTH = 200


def handle_post(store, path, data):
    match = _FOLDERS_RE.match(path)
    if match:
        return _create_folder(store, match.group(1), data)
    return None


def handle_put(store, path, data):
    match = _FOLDER_PARENT_RE.match(path)
    if match:
        return _move_folder(store, match.group(1), unquote(match.group(2)), data)
    match = _FOLDER_ITEM_RE.match(path)
    if match:
        return _rename_folder(store, match.group(1), unquote(match.group(2)), data)
    match = _REQUEST_FOLDER_RE.match(path)
    if match:
        return _move_request_to_folder(store, match.group(1), unquote(match.group(2)), data)
    return None


def handle_delete(store, path):
    match = _FOLDER_ITEM_RE.match(path)
    if match:
        return _delete_folder(store, match.group(1), unquote(match.group(2)))
    return None


def _create_folder(store, slug, data):
    name = str((data or {}).get("name") or "").strip() if isinstance(data, dict) else ""
    if not name:
        return 400, {"error": "Folder name is required"}
    if len(name) > _MAX_FOLDER_NAME_LENGTH:
        return 400, {"error": f"Folder name is too long (max {_MAX_FOLDER_NAME_LENGTH} characters)"}
    parent_folder_id = (data.get("parentFolderId") or None) if isinstance(data, dict) else None
    try:
        folder_id = store.create_folder(slug, name, parent_folder_id)
    except (collection_store.CollectionNotFound, collection_store.FolderNotFound) as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"id": folder_id, "name": name}


def _move_folder(store, slug, folder_id, data):
    if not isinstance(data, dict):
        return 400, {"error": "Body must be a JSON object"}
    new_parent_id = data.get("parentFolderId") or None
    try:
        store.move_folder(slug, folder_id, new_parent_id)
    except (collection_store.CollectionNotFound, collection_store.FolderNotFound) as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, {"moved": True}


def _rename_folder(store, slug, folder_id, data):
    name = str((data or {}).get("name") or "").strip() if isinstance(data, dict) else ""
    if not name:
        return 400, {"error": "Folder name is required"}
    if len(name) > _MAX_FOLDER_NAME_LENGTH:
        return 400, {"error": f"Folder name is too long (max {_MAX_FOLDER_NAME_LENGTH} characters)"}
    try:
        store.rename_folder(slug, folder_id, name)
    except (collection_store.CollectionNotFound, collection_store.FolderNotFound) as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"renamed": True}


def _delete_folder(store, slug, folder_id):
    try:
        store.delete_folder(slug, folder_id)
    except (collection_store.CollectionNotFound, collection_store.FolderNotFound) as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"deleted": True}


def _move_request_to_folder(store, slug, request_name, data):
    if not isinstance(data, dict):
        return 400, {"error": "Body must be a JSON object"}
    folder_id = data.get("folderId") or None
    try:
        store.move_request_to_folder(slug, request_name, folder_id)
    except (collection_store.CollectionNotFound, collection_store.FolderNotFound) as exc:
        return 404, {"error": str(exc)}
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    return 200, {"moved": True}
