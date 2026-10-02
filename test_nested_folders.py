"""Tests for nested folders: a folder's parentFolderId, cycle prevention on
move, and child-promotion on delete.

Split out into its own file rather than growing test_folders.py, which is
already close to this repo's 500-line file-size gate.
"""

import pytest

import collection_store
import folder_routes


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


# --- collection_store.py --------------------------------------------------


def test_create_folder_with_valid_parent_sets_parent_folder_id(store):
    store.create("C")
    parent_id = store.create_folder("c", "Auth")
    child_id = store.create_folder("c", "Tokens", parent_folder_id=parent_id)
    folders = store.get("c")["folders"]
    child = next(f for f in folders if f["id"] == child_id)
    assert child["parentFolderId"] == parent_id


def test_create_folder_without_parent_has_no_parent_folder_id(store):
    store.create("C")
    store.create_folder("c", "Auth")
    folder = store.get("c")["folders"][0]
    assert folder.get("parentFolderId") is None


def test_create_folder_with_unknown_parent_raises(store):
    store.create("C")
    with pytest.raises(collection_store.FolderNotFound):
        store.create_folder("c", "Auth", parent_folder_id="nope")


def test_move_folder_reparents_it(store):
    store.create("C")
    folder_a = store.create_folder("c", "A")
    folder_b = store.create_folder("c", "B")
    store.move_folder("c", folder_b, folder_a)
    folders = store.get("c")["folders"]
    b = next(f for f in folders if f["id"] == folder_b)
    assert b["parentFolderId"] == folder_a


def test_move_folder_to_top_level_clears_parent_folder_id(store):
    store.create("C")
    folder_a = store.create_folder("c", "A")
    folder_b = store.create_folder("c", "B", parent_folder_id=folder_a)
    store.move_folder("c", folder_b, None)
    folders = store.get("c")["folders"]
    b = next(f for f in folders if f["id"] == folder_b)
    assert b.get("parentFolderId") is None


def test_move_folder_under_its_own_descendant_raises(store):
    store.create("C")
    grandparent = store.create_folder("c", "A")
    parent = store.create_folder("c", "B", parent_folder_id=grandparent)
    child = store.create_folder("c", "C", parent_folder_id=parent)
    with pytest.raises(ValueError):
        store.move_folder("c", grandparent, child)


def test_move_folder_under_itself_raises(store):
    store.create("C")
    folder_id = store.create_folder("c", "A")
    with pytest.raises(ValueError):
        store.move_folder("c", folder_id, folder_id)


def test_move_folder_unknown_folder_raises(store):
    store.create("C")
    with pytest.raises(collection_store.FolderNotFound):
        store.move_folder("c", "nope", None)


def test_move_folder_unknown_new_parent_raises(store):
    store.create("C")
    folder_id = store.create_folder("c", "A")
    with pytest.raises(collection_store.FolderNotFound):
        store.move_folder("c", folder_id, "nope")


def test_delete_folder_promotes_children_to_its_own_parent(store):
    store.create("C")
    grandparent = store.create_folder("c", "A")
    parent = store.create_folder("c", "B", parent_folder_id=grandparent)
    child = store.create_folder("c", "C", parent_folder_id=parent)
    store.delete_folder("c", parent)
    folders = store.get("c")["folders"]
    assert {f["id"] for f in folders} == {grandparent, child}
    promoted = next(f for f in folders if f["id"] == child)
    assert promoted["parentFolderId"] == grandparent


def test_delete_top_level_folder_promotes_children_to_top_level(store):
    store.create("C")
    parent = store.create_folder("c", "A")
    child = store.create_folder("c", "B", parent_folder_id=parent)
    store.delete_folder("c", parent)
    folders = store.get("c")["folders"]
    assert folders == [{"id": child, "name": "B"}]


# --- folder_routes.py ------------------------------------------------------


def test_create_folder_route_with_parent(store):
    store.create("C")
    parent_id = store.create_folder("c", "Auth")
    status, body = folder_routes.handle_post(
        store, "/api/collections/c/folders", {"name": "Tokens", "parentFolderId": parent_id}
    )
    assert status == 200
    child = next(f for f in store.get("c")["folders"] if f["id"] == body["id"])
    assert child["parentFolderId"] == parent_id


def test_create_folder_route_with_bogus_parent_returns_404(store):
    store.create("C")
    status, _ = folder_routes.handle_post(
        store, "/api/collections/c/folders", {"name": "Tokens", "parentFolderId": "nope"}
    )
    assert status == 404


def test_move_folder_route(store):
    store.create("C")
    folder_a = store.create_folder("c", "A")
    folder_b = store.create_folder("c", "B")
    status, body = folder_routes.handle_put(
        store, f"/api/collections/c/folders/{folder_b}/parent", {"parentFolderId": folder_a}
    )
    assert status == 200
    assert body == {"moved": True}
    moved = next(f for f in store.get("c")["folders"] if f["id"] == folder_b)
    assert moved["parentFolderId"] == folder_a


def test_move_folder_route_rejects_moving_under_own_descendant(store):
    store.create("C")
    parent = store.create_folder("c", "A")
    child = store.create_folder("c", "B", parent_folder_id=parent)
    status, body = folder_routes.handle_put(
        store, f"/api/collections/c/folders/{parent}/parent", {"parentFolderId": child}
    )
    assert status == 400
    assert body["error"]


def test_move_folder_route_unknown_folder(store):
    store.create("C")
    status, _ = folder_routes.handle_put(
        store, "/api/collections/c/folders/nope/parent", {"parentFolderId": None}
    )
    assert status == 404


def test_move_folder_route_rejects_non_dict_body(store):
    store.create("C")
    folder_id = store.create_folder("c", "A")
    status, _ = folder_routes.handle_put(store, f"/api/collections/c/folders/{folder_id}/parent", "not-a-dict")
    assert status == 400


def test_move_folder_route_unknown_collection(store):
    status, _ = folder_routes.handle_put(
        store, "/api/collections/missing/folders/nope/parent", {"parentFolderId": None}
    )
    assert status == 404
