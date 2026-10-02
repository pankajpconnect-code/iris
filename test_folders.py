"""Tests for one-level folders within a collection: create/rename/delete a
folder, and move a request into/out of one.

Split out into its own file (following test_collection_rename.py's
precedent) rather than growing test_console.py, which is already over this
repo's 500-line file-size gate.
"""

import os
import threading

import pytest
import requests

import collection_routes
import collection_store
import environment_store
import folder_routes
import import_routes
import server


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


@pytest.fixture
def iris(tmp_path, monkeypatch):
    """Mirrors test_server_routes.py's `iris` fixture — a real server bound
    to a free port, isolated stores — used here only to prove folder_routes
    is actually wired into server.py's dispatch chain, not just callable in
    isolation."""
    monkeypatch.setattr(server, "COLLECTION_STORE", collection_store.CollectionStore(str(tmp_path / "collections")))
    monkeypatch.setattr(server, "ENVIRONMENT_STORE", environment_store.EnvironmentStore(str(tmp_path / "environments")))
    port = server._find_free_port(15080)
    httpd = server.LocalThreadingHTTPServer(("127.0.0.1", port), server.IrisRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", server.COLLECTION_STORE
    httpd.shutdown()
    httpd.server_close()


def test_server_dispatches_folder_routes(iris):
    base_url, coll_store = iris
    coll_store.create("C")
    resp = requests.post(f"{base_url}/api/collections/c/folders", json={"name": "Auth"}, timeout=5)
    assert resp.status_code == 200
    folder_id = resp.json()["id"]
    assert coll_store.get("c")["folders"] == [{"id": folder_id, "name": "Auth"}]


# --- collection_store.py -----------------------------------------------


def test_create_folder_appends_a_folder_with_a_generated_id(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    assert folder_id
    assert store.get("c")["folders"] == [{"id": folder_id, "name": "Auth"}]


def test_create_folder_on_unknown_collection_raises(store):
    with pytest.raises(collection_store.CollectionNotFound):
        store.create_folder("missing", "Auth")


def test_rename_folder_updates_name_in_place(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    store.rename_folder("c", folder_id, "Authentication")
    assert store.get("c")["folders"] == [{"id": folder_id, "name": "Authentication"}]


def test_rename_folder_unknown_id_raises(store):
    store.create("C")
    with pytest.raises(collection_store.FolderNotFound):
        store.rename_folder("c", "nope", "New Name")


def test_delete_folder_removes_it_and_uncategorizes_its_requests(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    store.save_request(
        "c", {"name": "R1", "method": "GET", "url": "u", "headers": [], "body": "", "folderId": folder_id}
    )
    store.save_request("c", {"name": "R2", "method": "GET", "url": "u", "headers": [], "body": ""})
    store.delete_folder("c", folder_id)
    data = store.get("c")
    assert data["folders"] == []
    assert "folderId" not in data["requests"][0]
    assert "folderId" not in data["requests"][1]


def test_delete_folder_unknown_id_raises(store):
    store.create("C")
    with pytest.raises(collection_store.FolderNotFound):
        store.delete_folder("c", "nope")


def test_move_request_to_folder_sets_folder_id(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    store.save_request("c", {"name": "R", "method": "GET", "url": "u", "headers": [], "body": ""})
    store.move_request_to_folder("c", "R", folder_id)
    assert store.get("c")["requests"][0]["folderId"] == folder_id


def test_move_request_to_folder_with_none_clears_it(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    store.save_request(
        "c", {"name": "R", "method": "GET", "url": "u", "headers": [], "body": "", "folderId": folder_id}
    )
    store.move_request_to_folder("c", "R", None)
    assert "folderId" not in store.get("c")["requests"][0]


def test_move_request_to_folder_unknown_request_raises(store):
    store.create("C")
    with pytest.raises(collection_store.CollectionNotFound):
        store.move_request_to_folder("c", "Missing", None)


def test_move_request_to_folder_unknown_folder_raises(store):
    store.create("C")
    store.save_request("c", {"name": "R", "method": "GET", "url": "u", "headers": [], "body": ""})
    with pytest.raises(collection_store.FolderNotFound):
        store.move_request_to_folder("c", "R", "nope")


# --- folder_routes.py ----------------------------------------------------


def test_create_folder_route(store):
    store.create("C")
    status, body = folder_routes.handle_post(store, "/api/collections/c/folders", {"name": "Auth"})
    assert status == 200
    assert body["name"] == "Auth"
    assert body["id"]


@pytest.mark.parametrize("body", [{}, {"name": "  "}, "not-a-dict"])
def test_create_folder_route_rejects_blank_name(store, body):
    store.create("C")
    status, _ = folder_routes.handle_post(store, "/api/collections/c/folders", body)
    assert status == 400


def test_create_folder_route_unknown_collection(store):
    status, _ = folder_routes.handle_post(store, "/api/collections/missing/folders", {"name": "Auth"})
    assert status == 404


def test_create_folder_route_rejects_an_overly_long_name(store):
    store.create("C")
    status, _ = folder_routes.handle_post(store, "/api/collections/c/folders", {"name": "x" * 201})
    assert status == 400


def test_rename_folder_route_rejects_an_overly_long_name(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    status, _ = folder_routes.handle_put(store, f"/api/collections/c/folders/{folder_id}", {"name": "x" * 201})
    assert status == 400


def test_find_folder_tolerates_a_non_list_folders_value(store):
    """Hand-edited JSON could leave "folders" as something other than a
    list — this must degrade to "not found" (the existing 404 path), not an
    AttributeError escaping as an unhandled 500."""
    store.create("C")
    data = store.get("c")
    data["folders"] = "not-a-list"
    collection_store._atomic_write_json(store._collection_path("c"), data)
    with pytest.raises(collection_store.FolderNotFound):
        store.rename_folder("c", "anything", "New Name")


def test_rename_folder_route(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    status, body = folder_routes.handle_put(store, f"/api/collections/c/folders/{folder_id}", {"name": "New"})
    assert status == 200
    assert body == {"renamed": True}


def test_rename_folder_route_unknown_folder(store):
    store.create("C")
    status, _ = folder_routes.handle_put(store, "/api/collections/c/folders/nope", {"name": "New"})
    assert status == 404


def test_delete_folder_route(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    status, body = folder_routes.handle_delete(store, f"/api/collections/c/folders/{folder_id}")
    assert status == 200
    assert body == {"deleted": True}


def test_delete_folder_route_unknown_folder(store):
    store.create("C")
    status, _ = folder_routes.handle_delete(store, "/api/collections/c/folders/nope")
    assert status == 404


def test_move_request_route(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    store.save_request("c", {"name": "R", "method": "GET", "url": "u", "headers": [], "body": ""})
    status, body = folder_routes.handle_put(
        store, "/api/collections/c/requests/R/folder", {"folderId": folder_id}
    )
    assert status == 200
    assert body == {"moved": True}
    assert store.get("c")["requests"][0]["folderId"] == folder_id


def test_move_request_route_unknown_request(store):
    store.create("C")
    status, _ = folder_routes.handle_put(store, "/api/collections/c/requests/Missing/folder", {"folderId": None})
    assert status == 404


def test_move_request_route_rejects_non_dict_body(store):
    store.create("C")
    store.save_request("c", {"name": "R", "method": "GET", "url": "u", "headers": [], "body": ""})
    status, _ = folder_routes.handle_put(store, "/api/collections/c/requests/R/folder", "not-a-dict")
    assert status == 400


def test_rename_folder_route_unknown_collection(store):
    status, _ = folder_routes.handle_put(store, "/api/collections/missing/folders/nope", {"name": "New"})
    assert status == 404


def test_delete_folder_route_unknown_collection(store):
    status, _ = folder_routes.handle_delete(store, "/api/collections/missing/folders/nope")
    assert status == 404


def test_move_request_route_unknown_collection(store):
    status, _ = folder_routes.handle_put(store, "/api/collections/missing/requests/R/folder", {"folderId": None})
    assert status == 404


def _corrupt(store, slug):
    with open(os.path.join(store.root, f"{slug}.json"), "w", encoding="utf-8") as handle:
        handle.write("{not valid json")


def test_create_folder_route_corrupted_collection(store):
    store.create("C")
    _corrupt(store, "c")
    status, _ = folder_routes.handle_post(store, "/api/collections/c/folders", {"name": "Auth"})
    assert status == 409


def test_rename_folder_route_corrupted_collection(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    _corrupt(store, "c")
    status, _ = folder_routes.handle_put(store, f"/api/collections/c/folders/{folder_id}", {"name": "New"})
    assert status == 409


def test_delete_folder_route_corrupted_collection(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    _corrupt(store, "c")
    status, _ = folder_routes.handle_delete(store, f"/api/collections/c/folders/{folder_id}")
    assert status == 409


def test_move_request_route_corrupted_collection(store):
    store.create("C")
    store.save_request("c", {"name": "R", "method": "GET", "url": "u", "headers": [], "body": ""})
    _corrupt(store, "c")
    status, _ = folder_routes.handle_put(store, "/api/collections/c/requests/R/folder", {"folderId": None})
    assert status == 409


# --- collection_routes.py: folders exposure + folderId carry-forward -----


def test_get_collection_route_includes_folders(store):
    store.create("C")
    store.create_folder("c", "Auth")
    status, body = collection_routes.handle_get(store, "/api/collections/c")
    assert status == 200
    assert body["folders"] == [{"id": body["folders"][0]["id"], "name": "Auth"}]


def test_save_request_route_accepts_folder_id_on_create(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    status, body = collection_routes.handle_post(
        store, "/api/collections/c/requests", {"name": "R", "method": "GET", "url": "u", "folderId": folder_id}
    )
    assert status == 200
    assert body["request"]["folderId"] == folder_id
    assert store.get("c")["requests"][0]["folderId"] == folder_id


def test_save_request_route_preserves_folder_id_on_edit_even_if_payload_omits_it(store):
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    store.save_request(
        "c", {"name": "R", "method": "GET", "url": "u1", "headers": [], "body": "", "folderId": folder_id}
    )
    status, body = collection_routes.handle_post(
        store, "/api/collections/c/requests", {"name": "R", "method": "GET", "url": "u2"}
    )
    assert status == 200
    assert body["request"]["folderId"] == folder_id


def test_save_request_route_edit_ignores_a_conflicting_folder_id_in_the_payload(store):
    """The request-panel Save button has no folder editor, so a payload that
    happens to carry a stale/different folderId (e.g. a tab opened against a
    folder that has since been reassigned) must never override the request's
    actual current folder on an edit-save."""
    store.create("C")
    original_folder = store.create_folder("c", "Auth")
    other_folder = store.create_folder("c", "Loans")
    store.save_request(
        "c", {"name": "R", "method": "GET", "url": "u1", "headers": [], "body": "", "folderId": original_folder}
    )
    status, body = collection_routes.handle_post(
        store, "/api/collections/c/requests", {"name": "R", "method": "GET", "url": "u2", "folderId": other_folder}
    )
    assert status == 200
    assert body["request"]["folderId"] == original_folder


def test_save_request_route_rejects_a_folder_id_from_another_collection_on_create(store):
    """A tab can be opened against folder f1 in collection A and then saved
    into collection B (e.g. the user switched the active collection before
    hitting Save) — collection B has no such folder, so the request must not
    be persisted with a dangling cross-collection folderId."""
    store.create("A")
    store.create("B")
    folder_id = store.create_folder("a", "Auth")
    status, body = collection_routes.handle_post(
        store, "/api/collections/b/requests", {"name": "R", "method": "GET", "url": "u", "folderId": folder_id}
    )
    assert status == 200
    assert "folderId" not in body["request"]
    assert "folderId" not in store.get("b")["requests"][0]


def test_save_request_route_overwrite_onto_existing_name_keeps_the_target_requests_folder(store):
    """Saving under a name that already exists in the collection is an
    overwrite (documented store.save_request behavior) — the OVERWRITTEN
    request's own folder assignment wins, not whatever folder the save
    payload happened to carry (e.g. from a folder's own "+" button)."""
    store.create("C")
    folder_a = store.create_folder("c", "Auth")
    folder_b = store.create_folder("c", "Loans")
    store.save_request(
        "c", {"name": "R", "method": "GET", "url": "u1", "headers": [], "body": "", "folderId": folder_a}
    )
    status, body = collection_routes.handle_post(
        store, "/api/collections/c/requests", {"name": "R", "method": "GET", "url": "u2", "folderId": folder_b}
    )
    assert status == 200
    assert body["request"]["folderId"] == folder_a


def test_import_collection_preserves_an_existing_requests_folder_id(store):
    """Re-importing an updated export into a collection the user has already
    organized into folders must not silently wipe every folderId — the
    import loop bypasses _save_request's own carry-forward, so this needs
    its own equivalent logic in _import_collection."""
    store.create("C")
    folder_id = store.create_folder("c", "Auth")
    store.save_request(
        "c", {"name": "Get Loan", "method": "GET", "url": "u1", "headers": [], "body": "", "folderId": folder_id}
    )
    export = {
        "info": {"name": "C", "schema": collection_routes.collection_io.SCHEMA_V21},
        "item": [{"name": "Get Loan", "request": {"method": "GET", "url": {"raw": "u2"}}}],
    }
    status, body = import_routes.handle_post(store, "/api/collections/c/import", export)
    assert status == 200
    saved = next(r for r in store.get("c")["requests"] if r["name"] == "Get Loan")
    assert saved["folderId"] == folder_id
    assert saved["url"] == "u2"
