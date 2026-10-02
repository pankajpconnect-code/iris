"""Tests for collection-level description support: reading it off a v2.1
collection's info.description on import, storing it via
collection_store.set_description, and the import route's create/re-import
wiring.

Split out into its own file rather than growing test_console.py, which is
already well past this repo's 500-line file-size gate — same reasoning as
test_import_nested_folders.py and test_auth_translation_collection_io.py.
"""

import pytest

import collection_io
import collection_routes
import collection_store
import import_routes


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


def _collection(items, description=None):
    info = {"name": "T", "schema": collection_io.SCHEMA_V21}
    if description is not None:
        info["description"] = description
    return {"info": info, "item": items}


def test_parse_collection_includes_description_when_present():
    parsed = collection_io.parse_collection(_collection([], description="Some **markdown** notes"))
    assert parsed["description"] == "Some **markdown** notes"


def test_parse_collection_omits_description_key_when_absent():
    parsed = collection_io.parse_collection(_collection([]))
    assert "description" not in parsed


def test_parse_collection_omits_description_key_when_empty_string():
    parsed = collection_io.parse_collection(_collection([], description=""))
    assert "description" not in parsed


def test_parse_collection_extracts_content_from_object_form_description():
    """The real v2.1 schema allows info.description to be EITHER a plain
    string OR an object {content, type, version?} — a real GoCardless-style
    export uses this object form. Storing the raw dict would flow untouched
    through collection_store/collection_routes and hit the sidebar's
    `textEl.textContent = collection.description`, which coerces a dict to
    the literal string "[object Object]" instead of showing the actual
    description."""
    parsed = collection_io.parse_collection(_collection(
        [], description={"content": "Some **markdown** notes", "type": "text/markdown"}
    ))
    assert parsed["description"] == "Some **markdown** notes"


def test_parse_collection_omits_description_key_when_object_form_content_is_absent():
    parsed = collection_io.parse_collection(_collection(
        [], description={"type": "text/markdown"}
    ))
    assert "description" not in parsed


def test_parse_collection_omits_description_key_when_object_form_content_is_empty():
    parsed = collection_io.parse_collection(_collection(
        [], description={"content": "", "type": "text/markdown"}
    ))
    assert "description" not in parsed


def test_store_set_description_is_retrievable_via_get(store):
    slug = store.create("Widgets")
    store.set_description(slug, "A widget collection")
    assert store.get(slug)["description"] == "A widget collection"


def test_import_stores_description_on_first_import_create_path(store):
    status, result = import_routes._import_collection(
        store, "widgets", _collection([], description="Widgets API")
    )
    assert status == 200
    assert store.get(result["slug"])["description"] == "Widgets API"


def test_import_without_description_stores_no_description_key(store):
    status, result = import_routes._import_collection(store, "widgets", _collection([]))
    assert status == 200
    assert "description" not in store.get(result["slug"])


def test_get_collection_route_includes_description_when_present(store):
    slug = store.create("Widgets")
    store.set_description(slug, "A widget collection")
    status, result = collection_routes.handle_get(store, f"/api/collections/{slug}")
    assert status == 200
    assert result["description"] == "A widget collection"


def test_get_collection_route_omits_description_key_when_absent(store):
    slug = store.create("Widgets")
    status, result = collection_routes.handle_get(store, f"/api/collections/{slug}")
    assert status == 200
    assert "description" not in result


def test_list_includes_description_when_present(store):
    """list()'s summary dict is an independent field allowlist from the
    singular _get_collection route's — PR #82 fixed _get_collection but left
    this same gap here. The sidebar tree actually renders from per-collection
    GET /api/collections/<slug> calls, not this list endpoint, so this keeps
    list() consistent with _get_collection rather than fixing a UI bug."""
    slug = store.create("Widgets")
    store.set_description(slug, "A widget collection")
    summaries = store.list()
    assert next(s for s in summaries if s["slug"] == slug)["description"] == "A widget collection"


def test_list_omits_description_key_when_absent(store):
    slug = store.create("Widgets")
    summaries = store.list()
    assert "description" not in next(s for s in summaries if s["slug"] == slug)


def test_reimport_that_removes_description_leaves_the_previously_stored_one(store):
    """Re-import decision: a fresh export with the description field removed
    does NOT clear the previously stored description — the same
    leave-it-alone-if-the-fresh-export-doesn't-say-otherwise choice already
    made for folderId carry-forward in _import_collection. A user editing a
    collection's requests in Postman and re-exporting shouldn't silently wipe
    documentation Iris already has stored just because that particular
    export's info block happened to omit it."""
    _, first = import_routes._import_collection(
        store, "widgets", _collection([], description="Widgets API")
    )
    slug = first["slug"]
    assert store.get(slug)["description"] == "Widgets API"

    import_routes._import_collection(store, slug, _collection([]))

    assert store.get(slug)["description"] == "Widgets API"
