"""Disk persistence for API console collections.

A collection is a v2.1-shaped JSON file (`<slug>.json`). Variables
live in a sibling `<slug>.env.json` so secrets never land in the exportable
collection file. Creation order is tracked in `_order.json` since directory
listing order is not guaranteed. Writes are atomic (temp file + os.replace)
so a crash mid-write can't leave a truncated/corrupt file on disk.
"""

import json
import os
import re
import tempfile
import uuid

_ORDER_FILE = "_order.json"
_SECRET_NAME_RE = re.compile(r"token|secret|password|cookie", re.IGNORECASE)
# A slug this long already can't happen from reasonable names, and stays well
# under the ~255-byte filename limit even after the ".json" suffix — this is
# what stands between a misplaced paste (e.g. a whole JSON blob typed into a
# name field) and an OSError crashing collection/environment creation.
_MAX_NAME_LENGTH = 200


class CollectionNotFound(ValueError):
    """Raised when a slug has no collection file on disk."""


class CollectionCorrupted(ValueError):
    """Raised when a collection/vars file exists but isn't valid JSON.

    Subclasses ValueError so existing `except ValueError` callers keep
    working, but callers should catch this separately to avoid reporting
    data corruption as a plain 404 "not found".
    """


class FolderNotFound(ValueError):
    """Raised when a folder id has no matching folder in the collection."""


def slugify(name):
    if len(name) > _MAX_NAME_LENGTH:
        raise ValueError(f"Name is too long (max {_MAX_NAME_LENGTH} characters)")
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _atomic_write_json(path, data):
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


class CollectionStore:
    def __init__(self, root_dir):
        self.root = root_dir
        os.makedirs(self.root, exist_ok=True)
        # Secret-named variables (token/secret/password/cookie) are kept here
        # only — never written to <slug>.env.json — by design, so they're
        # session-only and lost on process restart.
        self._secret_vars = {}

    def _collection_path(self, slug):
        return os.path.join(self.root, f"{slug}.json")

    def _vars_path(self, slug):
        return os.path.join(self.root, f"{slug}.env.json")

    def _order_path(self):
        return os.path.join(self.root, _ORDER_FILE)

    def _read_json(self, path, corrupt_message):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise CollectionCorrupted(corrupt_message.format(exc=exc)) from exc

    def _read_order(self):
        path = self._order_path()
        if not os.path.isfile(path):
            return []
        return self._read_json(path, "Collection index is corrupted: {exc}")

    def _write_order(self, order):
        _atomic_write_json(self._order_path(), order)

    def create(self, name):
        slug = slugify(name)
        path = self._collection_path(slug)
        if os.path.isfile(path):
            raise ValueError(f"Collection '{slug}' already exists")
        _atomic_write_json(path, {"name": name, "requests": []})
        order = self._read_order()
        order.append(slug)
        self._write_order(order)
        return slug

    def list(self):
        summaries = []
        for slug in self._read_order():
            path = self._collection_path(slug)
            if not os.path.isfile(path):
                continue
            try:
                data = self._read_json(path, f"Collection '{slug}' is corrupted: {{exc}}")
            except CollectionCorrupted as exc:
                summaries.append({"slug": slug, "name": slug, "error": str(exc)})
                continue
            if data.get("archived"):
                continue
            summary = {"slug": slug, "name": data.get("name", slug)}
            if data.get("description"):
                summary["description"] = data["description"]
            summaries.append(summary)
        return summaries

    def set_archived(self, slug, archived):
        """"Remove from Iris" without deleting: hides the collection from
        list() while leaving the file (and its requests) on disk, so
        re-importing the same export later brings it straight back."""
        data = self.get(slug)
        data["archived"] = bool(archived)
        _atomic_write_json(self._collection_path(slug), data)

    def set_description(self, slug, description):
        data = self.get(slug)
        data["description"] = description
        _atomic_write_json(self._collection_path(slug), data)

    def get(self, slug):
        path = self._collection_path(slug)
        if not os.path.isfile(path):
            raise CollectionNotFound(f"Unknown collection '{slug}'")
        return self._read_json(path, f"Collection '{slug}' is corrupted: {{exc}}")

    def save_request(self, slug, request):
        data = self.get(slug)
        requests = data.setdefault("requests", [])
        for index, existing in enumerate(requests):
            if existing.get("name") == request.get("name"):
                requests[index] = request
                break
        else:
            requests.append(request)
        _atomic_write_json(self._collection_path(slug), data)

    def rename_request(self, slug, old_name, new_name):
        """Updates the name in place instead of create-under-new-name-then-
        delete-old (the previous client-side approach) — that always appended
        the new entry at the end of the list, silently moving the row to the
        bottom and making a rename look like a brand new request."""
        data = self.get(slug)
        requests = data.get("requests", [])
        index = next((i for i, r in enumerate(requests) if r.get("name") == old_name), None)
        if index is None:
            raise CollectionNotFound(f"Unknown request '{old_name}' in collection '{slug}'")
        requests[index]["name"] = new_name
        # Renaming onto an existing name overwrites it, matching the sidebar's
        # confirm-to-overwrite prompt — the renamed request keeps ITS position
        # (i == index survives the filter), the row it overwrote disappears
        # entirely rather than the renamed one jumping into the overwritten
        # row's slot.
        data["requests"] = [r for i, r in enumerate(requests) if i == index or r.get("name") != new_name]
        _atomic_write_json(self._collection_path(slug), data)

    def delete_request(self, slug, request_name):
        data = self.get(slug)
        data["requests"] = [
            request for request in data.get("requests", [])
            if request.get("name") != request_name
        ]
        _atomic_write_json(self._collection_path(slug), data)

    def _find_folder(self, folders, folder_id):
        # Defensive against hand-edited JSON where "folders" isn't a list, or
        # a list entry isn't a dict — degrades to "not found" (the caller's
        # existing 404 path) rather than an AttributeError escaping as an
        # unhandled 500.
        if not isinstance(folders, list):
            return None
        return next((f for f in folders if isinstance(f, dict) and f.get("id") == folder_id), None)

    def create_folder(self, slug, name, parent_folder_id=None, import_key=None):
        """import_key, when given, is the ORIGINAL Postman folder name at
        this nesting level — set only by the importer, and distinct from
        the mutable `name` a user can rename in Iris. The importer matches
        re-imports against `import_key`, not `name`, so a folder renamed in
        Iris still resolves to the same id on the next re-import of the
        same source file."""
        data = self.get(slug)
        folders = data.get("folders")
        if not isinstance(folders, list):
            folders = []
            data["folders"] = folders
        if parent_folder_id and self._find_folder(folders, parent_folder_id) is None:
            raise FolderNotFound(f"Unknown folder '{parent_folder_id}' in collection '{slug}'")
        folder_id = uuid.uuid4().hex
        folder = {"id": folder_id, "name": name}
        if parent_folder_id:
            folder["parentFolderId"] = parent_folder_id
        if import_key is not None:
            folder["importKey"] = import_key
        folders.append(folder)
        _atomic_write_json(self._collection_path(slug), data)
        return folder_id

    def rename_folder(self, slug, folder_id, new_name):
        data = self.get(slug)
        folder = self._find_folder(data.get("folders", []), folder_id)
        if folder is None:
            raise FolderNotFound(f"Unknown folder '{folder_id}' in collection '{slug}'")
        folder["name"] = new_name
        _atomic_write_json(self._collection_path(slug), data)

    def _would_cycle(self, folders, folder_id, new_parent_id):
        """Walks new_parent_id's own parentFolderId chain — if it ever
        reaches folder_id, re-parenting folder_id under new_parent_id would
        make folder_id its own descendant."""
        current_id = new_parent_id
        seen = set()
        while current_id:
            if current_id == folder_id:
                return True
            if current_id in seen:
                return False
            seen.add(current_id)
            current = self._find_folder(folders, current_id)
            if current is None:
                return False
            current_id = current.get("parentFolderId")
        return False

    def move_folder(self, slug, folder_id, new_parent_id):
        data = self.get(slug)
        folders = data.get("folders", [])
        folder = self._find_folder(folders, folder_id)
        if folder is None:
            raise FolderNotFound(f"Unknown folder '{folder_id}' in collection '{slug}'")
        if new_parent_id:
            if self._find_folder(folders, new_parent_id) is None:
                raise FolderNotFound(f"Unknown folder '{new_parent_id}' in collection '{slug}'")
            if self._would_cycle(folders, folder_id, new_parent_id):
                raise ValueError(f"Cannot move folder '{folder_id}' under its own descendant")
            folder["parentFolderId"] = new_parent_id
        else:
            folder.pop("parentFolderId", None)
        _atomic_write_json(self._collection_path(slug), data)

    def delete_folder(self, slug, folder_id):
        """Removes the folder record only — every request that referenced it
        has its folderId cleared (moved to "Uncategorized"), never deleted.
        Same non-destructive principle for child folders: they're promoted
        to the deleted folder's own former parent, not orphaned or cascade-
        deleted."""
        data = self.get(slug)
        folders = data.get("folders", [])
        folder = self._find_folder(folders, folder_id)
        if folder is None:
            raise FolderNotFound(f"Unknown folder '{folder_id}' in collection '{slug}'")
        grandparent_id = folder.get("parentFolderId")
        for f in folders:
            if isinstance(f, dict) and f.get("id") != folder_id and f.get("parentFolderId") == folder_id:
                if grandparent_id:
                    f["parentFolderId"] = grandparent_id
                else:
                    f.pop("parentFolderId", None)
        data["folders"] = [f for f in folders if not (isinstance(f, dict) and f.get("id") == folder_id)]
        for request in data.get("requests", []):
            if request.get("folderId") == folder_id:
                request.pop("folderId", None)
        _atomic_write_json(self._collection_path(slug), data)

    def move_request_to_folder(self, slug, request_name, folder_id):
        """Sets the named request's folderId, or clears it entirely when
        folder_id is falsy — moving it to the implicit "Uncategorized" group."""
        data = self.get(slug)
        request = next((r for r in data.get("requests", []) if r.get("name") == request_name), None)
        if request is None:
            raise CollectionNotFound(f"Unknown request '{request_name}' in collection '{slug}'")
        if folder_id and self._find_folder(data.get("folders", []), folder_id) is None:
            raise FolderNotFound(f"Unknown folder '{folder_id}' in collection '{slug}'")
        if folder_id:
            request["folderId"] = folder_id
        else:
            request.pop("folderId", None)
        _atomic_write_json(self._collection_path(slug), data)

    def delete(self, slug):
        path = self._collection_path(slug)
        if os.path.isfile(path):
            os.remove(path)
        vars_path = self._vars_path(slug)
        if os.path.isfile(vars_path):
            os.remove(vars_path)
        self._secret_vars.pop(slug, None)
        order = self._read_order()
        if slug in order:
            order.remove(slug)
            self._write_order(order)

    def _persisted_vars(self, slug):
        path = self._vars_path(slug)
        if not os.path.isfile(path):
            return {}
        return self._read_json(path, f"Variables for '{slug}' are corrupted: {{exc}}")

    def get_vars(self, slug):
        merged = dict(self._persisted_vars(slug))
        merged.update(self._secret_vars.get(slug, {}))
        return merged

    def set_vars(self, slug, variables):
        # None means "no value" (e.g. an unresolved capture) — never persist it,
        # matching environment_store.set_vars's same guard.
        variables = {k: v for k, v in variables.items() if v is not None}
        secret_updates = {k: v for k, v in variables.items() if _SECRET_NAME_RE.search(k)}
        persist_updates = {k: v for k, v in variables.items() if k not in secret_updates}
        if secret_updates:
            self._secret_vars.setdefault(slug, {}).update(secret_updates)
        if persist_updates:
            current = self._persisted_vars(slug)
            current.update(persist_updates)
            _atomic_write_json(self._vars_path(slug), current)
