"""Tests for collection_io's source-collection-format auth translation and
collection/folder-level auth inheritance on import.

Split out of test_console.py (not merged into it) for the same reason
test_body_mode_collection_io.py was split out: test_console.py is already well
past the 500-line cap.
"""

import collection_io


def _collection(items, auth=None):
    info_and_items = {"info": {"name": "T", "schema": collection_io.SCHEMA_V21}, "item": items}
    if auth is not None:
        info_and_items["auth"] = auth
    return info_and_items


def test_request_own_bearer_auth_translates_to_the_shape_iris_reads():
    """Regression test: parse_collection used to copy the raw source-collection
    auth JSON shape ({type, bearer: [{key, value}]}) straight into the request's
    "auth" field, but every other part of Iris (e.g. collection_routes._apply_auth)
    reads the {mode, bearerToken} shape instead — so imported bearer auth
    silently never worked."""
    parsed = collection_io.parse_collection(_collection([{
        "name": "Get Loan",
        "request": {
            "method": "GET", "url": "u", "header": [],
            "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]},
        },
    }]))
    assert parsed["requests"][0]["auth"] == {"mode": "bearer", "bearerToken": "{{token}}"}


def test_request_own_basic_auth_translates_to_the_shape_iris_reads():
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {
            "method": "GET", "url": "u", "header": [],
            "auth": {"type": "basic", "basic": [
                {"key": "username", "value": "alice"},
                {"key": "password", "value": "hunter2"},
            ]},
        },
    }]))
    assert parsed["requests"][0]["auth"] == {
        "mode": "basic", "basicUser": "alice", "basicPassword": "hunter2",
    }


def test_request_own_apikey_auth_in_query_translates_to_the_shape_iris_reads():
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {
            "method": "GET", "url": "u", "header": [],
            "auth": {"type": "apikey", "apikey": [
                {"key": "key", "value": "X-Api-Key"},
                {"key": "value", "value": "the-real-key"},
                {"key": "in", "value": "query"},
            ]},
        },
    }]))
    assert parsed["requests"][0]["auth"] == {
        "mode": "apikey",
        "apiKeyName": "X-Api-Key",
        "apiKeyValue": "the-real-key",
        "apiKeyLocation": "query",
    }


def test_request_own_apikey_auth_defaults_to_header_location_when_in_is_absent():
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {
            "method": "GET", "url": "u", "header": [],
            "auth": {"type": "apikey", "apikey": [
                {"key": "key", "value": "X-Api-Key"},
                {"key": "value", "value": "the-real-key"},
            ]},
        },
    }]))
    assert parsed["requests"][0]["auth"]["apiKeyLocation"] == "header"


def test_request_with_no_own_auth_inherits_collection_level_bearer_auth():
    """Common real-world pattern: one bearer token set once at the collection
    level for every request. Previously _walk only ever looked at
    item["request"].get("auth") — the top-level collection.get("auth") was
    never read at all, so every request silently lost this auth on import."""
    parsed = collection_io.parse_collection(_collection(
        [{"name": "R", "request": {"method": "GET", "url": "u", "header": []}}],
        auth={"type": "bearer", "bearer": [{"key": "token", "value": "{{sharedToken}}"}]},
    ))
    assert parsed["requests"][0]["auth"] == {"mode": "bearer", "bearerToken": "{{sharedToken}}"}


def test_folder_level_noauth_stops_inheritance_but_sibling_folder_still_inherits():
    parsed = collection_io.parse_collection(_collection(
        [
            {
                "name": "Public",
                "auth": {"type": "noauth"},
                "item": [{"name": "R1", "request": {"method": "GET", "url": "u", "header": []}}],
            },
            {
                "name": "Private",
                "item": [{"name": "R2", "request": {"method": "GET", "url": "u", "header": []}}],
            },
        ],
        auth={"type": "bearer", "bearer": [{"key": "token", "value": "{{sharedToken}}"}]},
    ))
    by_name = {r["name"]: r for r in parsed["requests"]}
    assert "auth" not in by_name["R1"]
    assert by_name["R2"]["auth"] == {"mode": "bearer", "bearerToken": "{{sharedToken}}"}


def test_nested_folder_inherits_auth_through_a_folder_with_no_auth_of_its_own():
    """A folder-in-folder chain must thread inherited_auth all the way down,
    not just one level — mirrors how `folder_path` already recurses through
    every nesting depth."""
    parsed = collection_io.parse_collection(_collection(
        [{
            "name": "Outer",
            "item": [{
                "name": "Inner",
                "item": [{"name": "R", "request": {"method": "GET", "url": "u", "header": []}}],
            }],
        }],
        auth={"type": "bearer", "bearer": [{"key": "token", "value": "{{sharedToken}}"}]},
    ))
    assert parsed["requests"][0]["name"] == "R"
    assert parsed["requests"][0]["folderPath"] == ["Outer", "Inner"]
    assert parsed["requests"][0]["auth"] == {"mode": "bearer", "bearerToken": "{{sharedToken}}"}


def test_folder_level_auth_overrides_inherited_auth_with_its_own_type():
    parsed = collection_io.parse_collection(_collection(
        [{
            "name": "Basic Only",
            "auth": {"type": "basic", "basic": [
                {"key": "username", "value": "alice"}, {"key": "password", "value": "hunter2"},
            ]},
            "item": [{"name": "R", "request": {"method": "GET", "url": "u", "header": []}}],
        }],
        auth={"type": "bearer", "bearer": [{"key": "token", "value": "{{sharedToken}}"}]},
    ))
    assert parsed["requests"][0]["auth"] == {"mode": "basic", "basicUser": "alice", "basicPassword": "hunter2"}


def test_folder_level_unsupported_auth_type_is_reported_and_clears_inheritance():
    parsed = collection_io.parse_collection(_collection(
        [{
            "name": "Oauth Folder",
            "auth": {"type": "oauth2", "oauth2": []},
            "item": [{"name": "R", "request": {"method": "GET", "url": "u", "header": []}}],
        }],
        auth={"type": "bearer", "bearer": [{"key": "token", "value": "{{sharedToken}}"}]},
    ))
    assert "auth" not in parsed["requests"][0]
    assert {"request": "Oauth Folder", "type": "oauth2"} in parsed["unsupportedAuthTypes"]


def test_request_level_noauth_overrides_inherited_collection_auth():
    parsed = collection_io.parse_collection(_collection(
        [{
            "name": "R",
            "request": {"method": "GET", "url": "u", "header": [], "auth": {"type": "noauth"}},
        }],
        auth={"type": "bearer", "bearer": [{"key": "token", "value": "{{sharedToken}}"}]},
    ))
    assert "auth" not in parsed["requests"][0]


def test_unsupported_auth_type_is_reported_and_leaves_request_without_auth():
    """oauth2 (and any other type Iris doesn't implement) must not crash the
    import and must not leak the untranslatable source-collection auth shape
    into the request's "auth" field — it's reported in unsupportedAuthTypes
    instead, mirroring unsupportedBodyModes."""
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {
            "method": "GET", "url": "u", "header": [],
            "auth": {"type": "oauth2", "oauth2": [{"key": "accessToken", "value": "x"}]},
        },
    }]))
    assert "auth" not in parsed["requests"][0]
    assert parsed["unsupportedAuthTypes"] == [{"request": "R", "type": "oauth2"}]


def test_explicit_null_auth_inherits_rather_than_clearing():
    """An explicit `"auth": null` on a request is not the same as an explicit
    noauth/unsupported override — it just means this item didn't set its own,
    the same as the key being absent entirely."""
    parsed = collection_io.parse_collection(_collection(
        [{"name": "R", "request": {"method": "GET", "url": "u", "header": [], "auth": None}}],
        auth={"type": "bearer", "bearer": [{"key": "token", "value": "{{sharedToken}}"}]},
    ))
    assert parsed["requests"][0]["auth"] == {"mode": "bearer", "bearerToken": "{{sharedToken}}"}


def test_empty_dict_auth_is_reported_as_unsupported_and_clears_inheritance():
    """Unlike `null`, an explicitly present but empty/typeless auth block is a
    real (if malformed) override — it must be reported, not silently ignored,
    and must still clear whatever was inherited."""
    parsed = collection_io.parse_collection(_collection(
        [{"name": "R", "request": {"method": "GET", "url": "u", "header": [], "auth": {}}}],
        auth={"type": "bearer", "bearer": [{"key": "token", "value": "{{sharedToken}}"}]},
    ))
    assert "auth" not in parsed["requests"][0]
    assert parsed["unsupportedAuthTypes"] == [{"request": "R", "type": "unspecified"}]


def test_malformed_non_dict_auth_does_not_crash_the_import():
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {"method": "GET", "url": "u", "header": [], "auth": "not-a-dict"},
    }]))
    assert "auth" not in parsed["requests"][0]
    assert parsed["unsupportedAuthTypes"] == [{"request": "R", "type": "unspecified"}]


def test_parse_collection_does_not_flag_auth_when_none_present_anywhere():
    parsed = collection_io.parse_collection(_collection([
        {"name": "R", "request": {"method": "GET", "url": "u", "header": []}},
    ]))
    assert "auth" not in parsed["requests"][0]
    assert parsed.get("unsupportedAuthTypes", []) == []


def test_export_redacts_a_literal_secret_in_translated_auth_but_not_a_variable_reference():
    """Same redaction rule headers/body params already get must apply to the
    now-translated {mode, bearerToken} auth shape — a literal bearer token is
    exactly as exposed as one in a header."""
    original = [{
        "name": "R", "method": "GET", "url": "u", "headers": [], "body": "",
        "auth": {"mode": "bearer", "bearerToken": "eyJhbGciOiJIUzI1NiJ9.actual.jwt"},
    }]
    exported = collection_io.to_collection("T", original)
    assert exported["item"][0]["request"]["auth"]["bearerToken"] == "***"

    original_var_ref = [{
        "name": "R", "method": "GET", "url": "u", "headers": [], "body": "",
        "auth": {"mode": "bearer", "bearerToken": "{{token}}"},
    }]
    exported_var_ref = collection_io.to_collection("T", original_var_ref)
    assert exported_var_ref["item"][0]["request"]["auth"]["bearerToken"] == "{{token}}"


def test_export_redacts_literal_basic_password_and_apikey_value_but_not_their_names():
    """collection_store._SECRET_NAME_RE (token|secret|password|cookie) doesn't
    match "apiKeyValue", so a name-pattern-based redaction (as headers/body
    params use) would silently leave a literal API key value unredacted —
    these field names are fixed by our own schema, so they're redacted by an
    explicit allow-list instead."""
    original = [{
        "name": "R", "method": "GET", "url": "u", "headers": [], "body": "",
        "auth": {"mode": "basic", "basicUser": "alice", "basicPassword": "hunter2"},
    }]
    exported = collection_io.to_collection("T", original)
    assert exported["item"][0]["request"]["auth"] == {
        "mode": "basic", "basicUser": "alice", "basicPassword": "***",
    }

    original_apikey = [{
        "name": "R", "method": "GET", "url": "u", "headers": [], "body": "",
        "auth": {
            "mode": "apikey", "apiKeyName": "X-Api-Key", "apiKeyValue": "the-real-key",
            "apiKeyLocation": "header",
        },
    }]
    exported_apikey = collection_io.to_collection("T", original_apikey)
    assert exported_apikey["item"][0]["request"]["auth"] == {
        "mode": "apikey", "apiKeyName": "X-Api-Key", "apiKeyValue": "***", "apiKeyLocation": "header",
    }


def test_reimporting_iris_own_export_of_apikey_auth_round_trips():
    """Same idempotent-passthrough requirement as the bearer case
    (test_export_round_trips_tests_and_auth in test_console.py), but for
    apikey — to_collection doesn't reverse-translate back into the raw
    source-collection shape, so _translate_auth must recognize its own output
    shape directly."""
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {
            "method": "GET", "url": "u", "header": [],
            "auth": {
                "mode": "apikey", "apiKeyName": "X-Api-Key", "apiKeyValue": "the-real-key",
                "apiKeyLocation": "query",
            },
        },
    }]))
    assert parsed["requests"][0]["auth"] == {
        "mode": "apikey", "apiKeyName": "X-Api-Key", "apiKeyValue": "the-real-key", "apiKeyLocation": "query",
    }
