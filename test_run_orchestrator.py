"""Tests for run_orchestrator.expand_scope and resolve_extra_vars — PR2 of the
Iris Runner redesign (local design doc, §8, §14 bullets 1-2). No HTTP, no routes.
"""

import pytest

import collection_store
import environment_store
import run_orchestrator


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


@pytest.fixture
def env_store(tmp_path):
    return environment_store.EnvironmentStore(str(tmp_path / "environments"))


def _make_collection(store):
    store.create("C")
    for name in ["Login", "Loans / Create", "Loans / Sub / Disburse", "Other"]:
        store.save_request("c", {
            "name": name,
            "method": "GET",
            "url": f"http://example.invalid/{name}",
            "headers": [],
            "body": "",
            "tests": [],
        })
    return "c"


# --- expand_scope ---


def test_expand_scope_request_returns_the_one_named_request(store):
    slug = _make_collection(store)
    result = run_orchestrator.expand_scope(store, {"type": "request", "slug": slug, "name": "Login"})
    assert [r["name"] for r in result] == ["Login"]


def _make_folder_collection(store):
    """Real Folder records (post-Phase-3b data model: {id, name,
    parentFolderId} + folderId on requests) instead of _make_collection's
    now-obsolete '/'-joined flattened names — expand_scope's folder branch
    resolves scope["name"] to a folder id and matches by folderId, not by
    string-prefix over request names."""
    store.create("C")
    slug = "c"
    loans_id = store.create_folder(slug, "Loans")
    sub_id = store.create_folder(slug, "Disbursement", parent_folder_id=loans_id)
    # Unrelated top-level folder whose name happens to share "Loans" as a
    # prefix — the old r.get("name").startswith(f"{name} / ") matching
    # depended entirely on request names accidentally colliding like this.
    legacy_id = store.create_folder(slug, "Loans Legacy")
    for name, folder_id in [
        ("Login", None),
        ("Get Loan", loans_id),
        ("Approve Loan", loans_id),
        ("Disburse Loan", sub_id),
        ("Old Get Loan", legacy_id),
        ("Other", None),
    ]:
        request = {
            "name": name, "method": "GET", "url": f"http://example.invalid/{name}",
            "headers": [], "body": "", "tests": [],
        }
        if folder_id:
            request["folderId"] = folder_id
        store.save_request(slug, request)
    return slug


def test_expand_scope_folder_includes_requests_from_nested_descendant_folders(store):
    slug = _make_folder_collection(store)
    result = run_orchestrator.expand_scope(store, {"type": "folder", "slug": slug, "name": "Loans"})
    assert [r["name"] for r in result] == ["Get Loan", "Approve Loan", "Disburse Loan"]


def test_expand_scope_folder_with_no_children_matches_only_its_own_requests(store):
    """Regression-safety property: a childless folder's closure is just
    itself, so a single-level (non-nested) folder scope behaves exactly as
    it always has."""
    slug = _make_folder_collection(store)
    result = run_orchestrator.expand_scope(store, {"type": "folder", "slug": slug, "name": "Loans Legacy"})
    assert [r["name"] for r in result] == ["Old Get Loan"]


def test_expand_scope_folder_does_not_leak_into_unrelated_folder_sharing_name_prefix(store):
    """Regression test for the bug the old name-prefix matching had: "Loans
    Legacy" is a sibling folder, not a descendant of "Loans" — its requests
    must never appear in the "Loans" scope just because the folder names
    happen to overlap."""
    slug = _make_folder_collection(store)
    result = run_orchestrator.expand_scope(store, {"type": "folder", "slug": slug, "name": "Loans"})
    assert "Old Get Loan" not in [r["name"] for r in result]


def test_expand_scope_collection_returns_every_request_in_stored_order(store):
    slug = _make_collection(store)
    result = run_orchestrator.expand_scope(store, {"type": "collection", "slug": slug, "name": None})
    assert [r["name"] for r in result] == ["Login", "Loans / Create", "Loans / Sub / Disburse", "Other"]


def test_expand_scope_zero_matches_raises_value_error(store):
    slug = _make_collection(store)
    with pytest.raises(ValueError):
        run_orchestrator.expand_scope(store, {"type": "request", "slug": slug, "name": "Nonexistent"})


def test_expand_scope_excluded_names_filters_out_deselected_requests(store):
    """A folder/collection scope runs every request by default, but the user
    can uncheck specific ones in the UI."""
    slug = _make_collection(store)
    result = run_orchestrator.expand_scope(
        store, {"type": "collection", "slug": slug, "name": None, "excludedNames": ["Other", "Login"]}
    )
    assert [r["name"] for r in result] == ["Loans / Create", "Loans / Sub / Disburse"]


def test_expand_scope_excluding_everything_still_raises_value_error(store):
    slug = _make_collection(store)
    with pytest.raises(ValueError):
        run_orchestrator.expand_scope(
            store, {"type": "request", "slug": slug, "name": "Login", "excludedNames": ["Login"]}
        )


# --- resolve_extra_vars precedence ---


def test_resolve_extra_vars_csv_row_beats_captured_so_far():
    result = run_orchestrator.resolve_extra_vars({"loanId": "csv-value"}, {"loanId": "captured-value"})
    assert result["loanId"] == "csv-value"


def test_resolve_extra_vars_captured_used_when_no_csv_value():
    result = run_orchestrator.resolve_extra_vars(None, {"loanId": "captured-value"})
    assert result["loanId"] == "captured-value"


def test_extra_vars_precedence_csv_beats_env_var(store, env_store):
    """Integration of resolve_extra_vars with E1's extra_vars merge (no HTTP) —
    a CSV column must beat a same-named environment variable."""
    import collection_routes

    env_slug = env_store.create("Dev")
    env_store.set_vars(env_slug, {"loanId": "env-value"})
    slug = _make_collection(store)

    extra_vars = run_orchestrator.resolve_extra_vars({"loanId": "csv-value"}, {})
    request, variables = collection_routes._resolve_send_one_request(
        store, {"slug": slug, "requestName": "Login", "environmentSlug": env_slug}, env_store, extra_vars
    )
    assert variables["loanId"] == "csv-value"


def test_extra_vars_precedence_captured_beats_env_but_loses_to_csv_row(store, env_store):
    import collection_routes

    env_slug = env_store.create("Dev")
    env_store.set_vars(env_slug, {"loanId": "env-value"})
    slug = _make_collection(store)
    captured = {"loanId": "captured-value"}

    no_csv_extra_vars = run_orchestrator.resolve_extra_vars(None, captured)
    _, no_csv_variables = collection_routes._resolve_send_one_request(
        store, {"slug": slug, "requestName": "Login", "environmentSlug": env_slug}, env_store, no_csv_extra_vars
    )
    assert no_csv_variables["loanId"] == "captured-value"

    with_csv_extra_vars = run_orchestrator.resolve_extra_vars({"loanId": "csv-value"}, captured)
    _, with_csv_variables = collection_routes._resolve_send_one_request(
        store, {"slug": slug, "requestName": "Login", "environmentSlug": env_slug}, env_store, with_csv_extra_vars
    )
    assert with_csv_variables["loanId"] == "csv-value"


# --- _send_step proxy threading ---


def test_send_step_threads_proxy_settings_through_to_send_one(store, env_store, monkeypatch):
    """_send_step must pass proxySettings (not proxy) to _send_one, so the
    Runner can be captured by Nucleus Capture Tool exactly like Console's Send."""
    import threading
    import run_auth

    captured = {}

    def fake_send_one(store, data, env_store=None, **kwargs):
        captured["proxySettings"] = data.get("proxySettings")
        return 200, {"status": 200}

    monkeypatch.setattr(run_orchestrator.collection_routes, "_send_one", fake_send_one)

    # Minimal context builder
    spec = {
        "scope": {"slug": "c"},
        "auth": {"mode": "none"},
        "proxySettings": {"mode": "custom", "url": "http://x:1", "username": "", "password": "", "bypassList": []},
    }
    token_cache = run_auth.TokenCache({"mode": "none"})
    counters = run_orchestrator.Counters()
    ctx = run_orchestrator.Context(spec, store, env_store, [], token_cache, threading.Event(), None, counters)

    # Call _send_step with a minimal request
    list(run_orchestrator._send_step(ctx, {"name": "r1", "method": "GET", "url": "https://example.com"}, {}, []))

    assert captured["proxySettings"]["url"] == "http://x:1"
