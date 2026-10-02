"""Tests for importing nested Postman folders as real Iris folders (rather
than flattening folder paths into request names): re-import dedupe, manual
folder-move preservation, and rename-resilience.

Split out into its own file rather than growing test_console.py, which is
already well past this repo's 500-line file-size gate — same reasoning as
test_nested_folders.py and test_auth_translation_collection_io.py.
"""

import pytest

import collection_io
import collection_store
import import_routes


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


def _collection(items):
    return {"info": {"name": "T", "schema": collection_io.SCHEMA_V21}, "item": items}


def _nested_payload():
    """Two folder levels (Outer > Inner) with a single leaf request — the
    same shape a real 2-level nested Postman export has."""
    return _collection([{
        "name": "Outer",
        "item": [{
            "name": "Inner",
            "item": [{"name": "Leaf", "request": {"method": "GET", "url": "u", "header": []}}],
        }],
    }])


def test_first_import_creates_matching_nested_folders_with_correct_parent_chain(store):
    status, result = import_routes._import_collection(store, "nested", _nested_payload())
    assert status == 200

    data = store.get(result["slug"])
    folders_by_name = {f["name"]: f for f in data["folders"]}
    assert set(folders_by_name) == {"Outer", "Inner"}
    assert folders_by_name["Outer"].get("parentFolderId") is None
    assert folders_by_name["Inner"]["parentFolderId"] == folders_by_name["Outer"]["id"]

    request = data["requests"][0]
    assert request["name"] == "Leaf"
    assert request["folderId"] == folders_by_name["Inner"]["id"]


def test_reimporting_same_collection_does_not_create_duplicate_folders(store):
    payload = _nested_payload()
    _, first = import_routes._import_collection(store, "nested", payload)
    slug = first["slug"]
    first_folders = {f["name"]: f["id"] for f in store.get(slug)["folders"]}

    status, second = import_routes._import_collection(store, slug, payload)
    assert status == 200

    data = store.get(slug)
    assert len(data["folders"]) == 2
    second_folders = {f["name"]: f["id"] for f in data["folders"]}
    assert second_folders == first_folders
    assert data["requests"][0]["folderId"] == first_folders["Inner"]


def test_reimport_preserves_a_request_manually_moved_to_a_different_folder(store):
    payload = _nested_payload()
    _, first = import_routes._import_collection(store, "nested", payload)
    slug = first["slug"]

    manual_folder_id = store.create_folder(slug, "Manually Organized")
    store.move_request_to_folder(slug, "Leaf", manual_folder_id)

    import_routes._import_collection(store, slug, payload)

    data = store.get(slug)
    request = next(r for r in data["requests"] if r["name"] == "Leaf")
    assert request["folderId"] == manual_folder_id


def test_import_survives_a_null_folders_field_on_disk(store):
    """A collection file with an explicit "folders": null (hand-edited, or
    from a pre-nested-folders export) must not crash the import — degrade
    to "no folders yet" the same way collection_store's own folder helpers
    already do for a non-list "folders" value."""
    slug = store.create("Legacy")
    data = store.get(slug)
    data["folders"] = None
    collection_store._atomic_write_json(store._collection_path(slug), data)

    status, result = import_routes._import_collection(store, slug, _nested_payload())
    assert status == 200

    saved = store.get(slug)
    assert len(saved["folders"]) == 2
    assert saved["requests"][0]["name"] == "Leaf"


def test_reimport_keeps_same_named_requests_in_their_own_sibling_folders(store):
    """Two sibling folders each containing a request named "Get" — a common
    real-world layout (Get/List/Create repeated under every resource
    folder). The same-name disambiguation (Get, Get (2)) must not let the
    carry-forward lookup below match the wrong stored request and drag the
    second one into the first one's folder on re-import."""
    payload = _collection([
        {"name": "Users", "item": [{"name": "Get", "request": {"method": "GET", "url": "u1", "header": []}}]},
        {"name": "Orders", "item": [{"name": "Get", "request": {"method": "GET", "url": "u2", "header": []}}]},
    ])
    _, first = import_routes._import_collection(store, "siblings", payload)
    slug = first["slug"]
    folders_by_name = {f["name"]: f["id"] for f in store.get(slug)["folders"]}
    before = {r["name"]: r["folderId"] for r in store.get(slug)["requests"]}
    assert before == {"Get": folders_by_name["Users"], "Get (2)": folders_by_name["Orders"]}

    import_routes._import_collection(store, slug, payload)

    after = {r["name"]: r["folderId"] for r in store.get(slug)["requests"]}
    assert after == before


def test_folder_renamed_in_iris_since_last_import_still_resolves_to_the_same_id(store):
    """The folder-identity match uses the folder's original Postman name
    (stored as importKey), not its current display name — so renaming a
    folder inside Iris must not spawn a duplicate on the next re-import of
    the same source file."""
    payload = _nested_payload()
    _, first = import_routes._import_collection(store, "nested", payload)
    slug = first["slug"]
    inner_id = next(f["id"] for f in store.get(slug)["folders"] if f["name"] == "Inner")

    store.rename_folder(slug, inner_id, "My Renamed Folder")

    import_routes._import_collection(store, slug, payload)

    data = store.get(slug)
    assert len(data["folders"]) == 2
    renamed = next(f for f in data["folders"] if f["id"] == inner_id)
    assert renamed["name"] == "My Renamed Folder"
    request = next(r for r in data["requests"] if r["name"] == "Leaf")
    assert request["folderId"] == inner_id
