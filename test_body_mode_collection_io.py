"""Tests for the body-mode feature's collection_io/collection_store surface:
{{var}} substitution in bodyParams, save/persist defaulting, and export/
import round-tripping of urlencoded bodies.

Split out of test_console.py (not merged into it) specifically to avoid
adding to that file's existing over-the-500-line-limit debt — test_console.py
was already at 650 lines on origin/main, before this feature touched it.
"""

import json

import pytest

import collection_io
import collection_store


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


def _collection(items):
    return {"info": {"name": "T", "schema": collection_io.SCHEMA_V21}, "item": items}


def test_substitute_is_applied_to_body_params():
    request = {
        "url": "https://a",
        "headers": [],
        "body": "",
        "bodyMode": "urlencoded",
        "bodyParams": [
            {"key": "token", "value": "{{token}}", "enabled": True},
            {"key": "static", "value": "unchanged", "enabled": False},
        ],
    }
    resolved = collection_io.resolve_request(request, {"token": "T"})
    assert resolved["bodyParams"][0]["value"] == "T"
    assert resolved["bodyParams"][1]["value"] == "unchanged"
    assert resolved["bodyParams"][1]["enabled"] is False


def test_resolve_request_defaults_missing_body_params_to_empty_list():
    resolved = collection_io.resolve_request(
        {"url": "https://a", "headers": [], "body": ""}, {}
    )
    assert resolved["bodyParams"] == []


def test_save_request_persists_body_mode_and_params(store):
    import collection_routes

    store.create("C")
    status, result = collection_routes._save_request(store, "c", {
        "name": "Post Form",
        "method": "POST",
        "url": "https://a",
        "headers": [],
        "body": "",
        "bodyMode": "urlencoded",
        "bodyParams": [
            {"key": "grant_type", "value": "client_credentials", "enabled": True},
            {"key": "", "value": "dropped-because-no-key", "enabled": True},
        ],
    })
    assert status == 200
    assert result["request"]["bodyMode"] == "urlencoded"
    assert result["request"]["bodyParams"] == [
        {"key": "grant_type", "value": "client_credentials", "enabled": True},
    ]

    saved = store.get("c")["requests"][0]
    assert saved["bodyMode"] == "urlencoded"


def test_save_request_with_no_body_mode_defaults_to_raw(store):
    import collection_routes

    store.create("C")
    status, result = collection_routes._save_request(store, "c", {
        "name": "Get", "method": "GET", "url": "https://a", "headers": [], "body": "",
    })
    assert status == 200
    assert result["request"]["bodyMode"] == "raw"
    assert result["request"]["bodyParams"] == []


def test_parse_collection_recognizes_native_urlencoded_body_and_does_not_flag_it():
    """Iris can now author and send urlencoded bodies itself — an imported
    v2.1 item using the standard {"mode": "urlencoded", "urlencoded": [...]}
    shape (the same shape Iris's own export now produces) must populate
    bodyMode/bodyParams, not be treated as an unsupported mode like formdata
    still is."""
    parsed = collection_io.parse_collection(_collection([{
        "name": "Post Form",
        "request": {
            "method": "POST", "url": "u", "header": [],
            "body": {"mode": "urlencoded", "urlencoded": [
                {"key": "grant_type", "value": "client_credentials"},
                {"key": "disabled_one", "value": "x", "disabled": True},
            ]},
        },
    }]))
    request = parsed["requests"][0]
    assert request["bodyMode"] == "urlencoded"
    assert request["bodyParams"] == [
        {"key": "grant_type", "value": "client_credentials", "enabled": True},
        {"key": "disabled_one", "value": "x", "enabled": False},
    ]
    assert parsed.get("unsupportedBodyModes", []) == []


def test_import_extracts_variables_from_urlencoded_body_params():
    parsed = collection_io.parse_collection(_collection([{
        "name": "A",
        "request": {
            "method": "POST", "url": "u", "header": [],
            "body": {"mode": "urlencoded", "urlencoded": [{"key": "token", "value": "{{apiToken}}"}]},
        },
    }]))
    assert parsed["variables"] == ["apiToken"]


def test_export_round_trips_urlencoded_body_params():
    """A urlencoded-mode request must survive export -> re-import, the same
    way a raw-mode request already does (test_export_round_trips_through_import
    in test_console.py) — previously to_collection() hardcoded
    {"mode": "raw", "raw": body}, silently dropping the entire body for a
    urlencoded-mode request."""
    original = [{
        "name": "R",
        "method": "POST",
        "url": "{{url}}/token",
        "headers": [],
        "body": "",
        "bodyMode": "urlencoded",
        "bodyParams": [
            {"key": "grant_type", "value": "client_credentials", "enabled": True},
            {"key": "disabled_one", "value": "x", "enabled": False},
        ],
    }]
    exported = collection_io.to_collection("T", original)
    assert exported["item"][0]["request"]["body"] == {
        "mode": "urlencoded",
        "urlencoded": [
            {"key": "grant_type", "value": "client_credentials", "disabled": False},
            {"key": "disabled_one", "value": "x", "disabled": True},
        ],
    }
    reparsed = collection_io.parse_collection(json.loads(json.dumps(exported)))
    assert reparsed["requests"] == original


def test_export_redacts_a_secret_named_body_param_with_a_literal_value():
    """Same redaction rule headers/auth already get (test_console.py's
    test_export_redacts_a_secret_named_header_with_a_literal_value) must
    apply to a urlencoded body param — a literal client secret in a form
    param is exactly as exposed as one in a header."""
    original = [{
        "name": "R", "method": "POST", "url": "u", "headers": [], "body": "",
        "bodyMode": "urlencoded",
        "bodyParams": [{"key": "client_secret", "value": "actual-real-secret", "enabled": True}],
    }]
    exported = collection_io.to_collection("T", original)
    assert exported["item"][0]["request"]["body"]["urlencoded"][0]["value"] == "***"
