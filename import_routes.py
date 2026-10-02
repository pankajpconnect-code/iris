"""HTTP-agnostic route handler for importing a v2.1 collection export.

Split out of collection_routes.py, which is already close to this repo's
500-line file-size gate — the same reasoning that split collection_routes.py
out of server.py in the first place. Dispatched from server.py alongside
collection_routes and folder_routes.
"""

import re

import collection_io
import collection_store

_IMPORT_RE = re.compile(r"^/api/collections/([^/]+)/import$")


def handle_post(store, path, data):
    match = _IMPORT_RE.match(path)
    if match:
        return _import_collection(store, match.group(1), data)
    return None


def _find_imported_folder(folders, import_key, parent_folder_id):
    """Matches by importKey (the folder's original Postman name), not the
    current stored `name` — so a folder the user renamed inside Iris since
    the last import still resolves to the same id, rather than the rename
    causing a duplicate to spawn under the Postman-original name. A folder
    created by hand in Iris (no importKey) never accidentally matches an
    imported one that happens to share a name."""
    return next(
        (
            f for f in folders
            if isinstance(f, dict)
            and f.get("importKey") == import_key
            and f.get("parentFolderId") == parent_folder_id
        ),
        None,
    )


def _resolve_folder_id(store, slug, known_folders, folder_id_cache, folder_path):
    """Creates (or reuses) the chain of Iris folders matching a Postman
    folder path, returning the leaf folder's id. known_folders/folder_id_cache
    are mutated in place so sibling requests sharing ancestor folders within
    the same import reuse the same freshly-created ids instead of each
    re-creating the chain from scratch."""
    parent_id = None
    path_key = ()
    for segment_name in folder_path:
        path_key = path_key + (segment_name,)
        if path_key in folder_id_cache:
            parent_id = folder_id_cache[path_key]
            continue
        existing_folder = _find_imported_folder(known_folders, segment_name, parent_id)
        if existing_folder is not None:
            folder_id = existing_folder["id"]
        else:
            folder_id = store.create_folder(slug, segment_name, parent_folder_id=parent_id, import_key=segment_name)
            known_folders.append({
                "id": folder_id, "name": segment_name, "parentFolderId": parent_id, "importKey": segment_name,
            })
        folder_id_cache[path_key] = folder_id
        parent_id = folder_id
    return parent_id


def _import_collection(store, slug, data):
    if not isinstance(data, dict):
        return 400, {"error": "Import body must be a v2.1 collection"}
    try:
        parsed = collection_io.parse_collection(data)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    try:
        store.get(slug)
    except collection_store.CollectionNotFound:
        created_name = data.get("info", {}).get("name") or slug
        try:
            slug = store.create(created_name)
        except ValueError:
            # created_name's slug collides with an existing collection (e.g.
            # re-importing an export of a same-named collection) — fall back
            # to the caller's own URL slug as the name instead.
            slug = store.create(slug)
    except collection_store.CollectionCorrupted as exc:
        return 409, {"error": str(exc)}
    # A collection "removed from Iris" (archived, not deleted) must reappear
    # the moment its export is re-imported — that's the whole point of
    # archive-instead-of-delete.
    store.set_archived(slug, False)
    # Only overwrite when the fresh export actually has one — a re-import of
    # an update that happens to omit info.description (e.g. exported from a
    # view that strips it) must not wipe out documentation Iris already has
    # stored, mirroring the folderId carry-forward reasoning below.
    if parsed.get("description"):
        store.set_description(slug, parsed["description"])
    try:
        existing = store.get(slug)
    except (collection_store.CollectionNotFound, collection_store.CollectionCorrupted):
        existing = {}
    # collection_store.save_request keys a request by its name (overwriting an
    # existing same-named one is the documented, tested contract for editing a
    # saved request) — but a source collection export can genuinely contain
    # two DIFFERENT requests sharing a display name (the real Lending export
    # has 4). Importing them one by one would silently collapse each pair down
    # to whichever saved last. Disambiguate within this import batch only, so
    # every distinct source item survives without changing save_request's
    # overwrite-by-name behavior for the normal edit/re-import case.
    #
    # This loop calls store.save_request directly (not collection_routes'
    # _save_request), so it needs its own folderId carry-forward: re-importing
    # an updated export of a collection the user has already organized into
    # folders must not silently move every request back to "Uncategorized"
    # just because the fresh export (naturally) has no folderId of its own.
    existing_by_name = {r.get("name"): r for r in existing.get("requests", [])}
    seen_names = {}
    # Resolved/created once per distinct Postman folder path within this
    # import, then reused — matching collection_io._walk's per-request
    # folderPath (see _resolve_folder_id) against the collection's real
    # `folders` list, since _walk itself has no store access.
    existing_folders = existing.get("folders")
    known_folders = list(existing_folders) if isinstance(existing_folders, list) else []
    folder_id_cache = {}
    for request in parsed["requests"]:
        request = dict(request)
        folder_path = request.pop("folderPath", None)
        if folder_path:
            request["folderId"] = _resolve_folder_id(store, slug, known_folders, folder_id_cache, folder_path)
        raw_name = request["name"]
        if raw_name in seen_names:
            seen_names[raw_name] += 1
            request["name"] = f"{raw_name} ({seen_names[raw_name]})"
        else:
            seen_names[raw_name] = 1
        # Looked up by the final (post-disambiguation) name, not raw_name —
        # two different source items sharing a display name (e.g. "Get"
        # under two sibling folders) disambiguate to "Get"/"Get (2)" in the
        # same deterministic order on every import of the same file, so
        # this still finds each one's own prior stored folderId rather than
        # both matching whichever "Get" happened to save first.
        prior = existing_by_name.get(request["name"])
        if prior and prior.get("folderId"):
            request["folderId"] = prior["folderId"]
        store.save_request(slug, request)
    return 200, {
        "slug": slug,
        "imported": len(parsed["requests"]),
        "variables": parsed["variables"],
        "untranslatedScripts": parsed.get("untranslatedScripts", []),
        "unsupportedBodyModes": parsed.get("unsupportedBodyModes", []),
        "unsupportedAuthTypes": parsed.get("unsupportedAuthTypes", []),
    }
