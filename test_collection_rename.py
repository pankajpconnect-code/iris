"""Tests for renaming a saved collection request.

Split out of test_console.py (already over the repo's 500-line file-size
gate) rather than growing it further.
"""

import pytest

import collection_routes
import collection_store


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


def test_rename_request_keeps_its_position_in_the_list(store):
    """Renaming used to be implemented as create-under-new-name-then-delete-
    old, which silently moved the row to the bottom of the list (save_request
    appends unmatched names) — from the user's side that looked exactly like
    a brand new request had been created. A real rename must update the name
    in place instead."""
    store.create("C")
    for name in ("A", "B", "C-req"):
        store.save_request("c", {"name": name, "method": "GET", "url": "u", "headers": [], "body": ""})
    store.rename_request("c", "B", "B Renamed")
    assert [r["name"] for r in store.get("c")["requests"]] == ["A", "B Renamed", "C-req"]


def test_rename_request_preserves_the_whole_payload_including_auth(store):
    """The old create-then-delete rename dropped auth entirely — _save_request's
    auth carry-forward looks the request up by its NEW name, which doesn't
    exist yet at that point, so the lookup always missed."""
    store.create("C")
    original = {
        "name": "A",
        "method": "POST",
        "url": "u",
        "headers": [{"key": "k", "value": "v", "enabled": True}],
        "body": "{}",
        "tests": [{"type": "status", "expected": 200}],
        "auth": {"mode": "bearer", "bearerToken": "t"},
    }
    store.save_request("c", original)
    store.rename_request("c", "A", "B")
    assert store.get("c")["requests"] == [{**original, "name": "B"}]


def test_rename_request_onto_an_existing_name_overwrites_it_and_keeps_the_renamed_slot(store):
    store.create("C")
    store.save_request("c", {"name": "A", "method": "GET", "url": "u1", "headers": [], "body": ""})
    store.save_request("c", {"name": "B", "method": "GET", "url": "u2", "headers": [], "body": ""})
    store.rename_request("c", "A", "B")
    requests = store.get("c")["requests"]
    assert [r["name"] for r in requests] == ["B"]
    assert requests[0]["url"] == "u1"


def test_rename_onto_an_earlier_name_keeps_the_renamed_request_where_it_was(store):
    """The renamed request keeps ITS OWN position — the row it overwrites
    disappears entirely rather than the renamed one jumping into the
    overwritten row's slot."""
    store.create("C")
    for name in ("A", "B", "Z"):
        store.save_request("c", {"name": name, "method": "GET", "url": name, "headers": [], "body": ""})
    store.rename_request("c", "Z", "A")
    requests = store.get("c")["requests"]
    assert [r["name"] for r in requests] == ["B", "A"]
    assert requests[1]["url"] == "Z"


def test_rename_request_missing_name_raises(store):
    store.create("C")
    with pytest.raises(collection_store.CollectionNotFound):
        store.rename_request("c", "Missing", "New")


def test_rename_route_updates_name_without_moving_the_request(store):
    store.create("C")
    for name in ("A", "B"):
        store.save_request("c", {"name": name, "method": "GET", "url": "u", "headers": [], "body": ""})
    status, result = collection_routes.handle_put(store, "/api/collections/c/requests/A", {"name": "A Renamed"})
    assert status == 200
    assert result == {"renamed": True}
    assert [r["name"] for r in store.get("c")["requests"]] == ["A Renamed", "B"]


@pytest.mark.parametrize("body", [{}, {"name": "   "}, "not-a-dict"])
def test_rename_route_rejects_a_missing_new_name(store, body):
    store.create("C")
    store.save_request("c", {"name": "A", "method": "GET", "url": "u", "headers": [], "body": ""})
    status, _ = collection_routes.handle_put(store, "/api/collections/c/requests/A", body)
    assert status == 400
    assert [r["name"] for r in store.get("c")["requests"]] == ["A"]
