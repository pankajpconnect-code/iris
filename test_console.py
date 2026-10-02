"""Tests for the API console: collection persistence and import/export."""

import glob
import json
import os

import pytest

import collection_io
import collection_store
import environment_store

# Matched by glob, not a fixed name, so this doesn't have to assume which
# tool actually produced the real-world export sitting in ~/Downloads.
_REAL_COLLECTION_CANDIDATES = glob.glob(os.path.expanduser("~/Downloads/Lending*collection*.json"))
REAL_COLLECTION = _REAL_COLLECTION_CANDIDATES[0] if _REAL_COLLECTION_CANDIDATES else None
needs_real_collection = pytest.mark.skipif(
    REAL_COLLECTION is None,
    reason="No ~/Downloads/Lending*collection*.json export present locally",
)

# A second, separate real-world export used specifically to verify the
# script-translator coverage work (phase5d) — a payment-provider domain
# name, not a competing API-client product name.
_REAL_SCRIPT_COLLECTION_CANDIDATES = glob.glob(os.path.expanduser("~/Downloads/GoCardless*collection*.json"))
REAL_SCRIPT_COLLECTION = _REAL_SCRIPT_COLLECTION_CANDIDATES[0] if _REAL_SCRIPT_COLLECTION_CANDIDATES else None
needs_real_script_collection = pytest.mark.skipif(
    REAL_SCRIPT_COLLECTION is None,
    reason="No ~/Downloads/GoCardless*collection*.json export present locally",
)


@pytest.fixture
def store(tmp_path):
    return collection_store.CollectionStore(str(tmp_path))


@pytest.fixture
def env_store(tmp_path):
    return environment_store.EnvironmentStore(str(tmp_path / "environments"))


# --- environments ---


def test_environment_create_then_list_and_get(env_store):
    slug = env_store.create("Playground")
    assert slug == "playground"
    assert [e["name"] for e in env_store.list()] == ["Playground"]
    assert env_store.get(slug)["vars"] == {}


def test_environment_create_rejects_duplicate(env_store):
    env_store.create("Dup")
    with pytest.raises(ValueError):
        env_store.create("Dup")


def test_environment_unknown_slug_raises(env_store):
    with pytest.raises(environment_store.EnvironmentNotFound):
        env_store.get("nope")


def test_environment_vars_round_trip(env_store):
    slug = env_store.create("Dev")
    assert env_store.get_vars(slug) == {}
    env_store.set_vars(slug, {"url": "https://dev.example"})
    assert env_store.get_vars(slug)["url"] == "https://dev.example"


def test_environment_secret_vars_never_written_to_disk(env_store):
    """Mirrors test_vars_file_is_separate_from_collection_file for environments."""
    slug = env_store.create("Dev")
    env_store.set_vars(slug, {"token": "secret-value"})
    assert env_store.get_vars(slug)["token"] == "secret-value"
    with open(os.path.join(env_store.root, f"{slug}.json"), encoding="utf-8") as handle:
        assert "secret-value" not in handle.read()


def test_environment_delete_removes_it(env_store):
    slug = env_store.create("Temp")
    env_store.delete(slug)
    assert env_store.list() == []




def test_merge_variables_environment_overrides_collection():
    collection_vars = {"url": "https://collection.example", "loanId": "1"}
    environment_vars = {"url": "https://env.example"}
    merged = environment_store.merge_variables(collection_vars, environment_vars)
    assert merged == {"url": "https://env.example", "loanId": "1"}


def test_merge_variables_handles_none_inputs():
    assert environment_store.merge_variables(None, None) == {}
    assert environment_store.merge_variables({"a": "1"}, None) == {"a": "1"}
    assert environment_store.merge_variables(None, {"a": "1"}) == {"a": "1"}


def test_slug_is_filesystem_safe():
    assert collection_store.slugify("My Loans / Coll") == "my-loans-coll"
    assert collection_store.slugify("  spaces  ") == "spaces"
    assert collection_store.slugify("../escape") == "escape"


def test_slugify_rejects_names_over_filesystem_safe_length():
    with pytest.raises(ValueError, match="too long"):
        collection_store.slugify("x" * 201)


def test_create_then_list_and_get(store):
    store.create("Lending Smoke")
    assert [c["name"] for c in store.list()] == ["Lending Smoke"]
    assert store.get("lending-smoke")["requests"] == []


def test_create_rejects_duplicate(store):
    store.create("Dup")
    with pytest.raises(ValueError):
        store.create("Dup")


def test_save_request_round_trips_through_disk(store):
    store.create("C")
    store.save_request("c", {
        "name": "Get Loan",
        "method": "GET",
        "url": "{{url}}/api/loans/{{loanId}}",
        "headers": [{"key": "Accept", "value": "application/json"}],
        "body": "",
    })
    requests = store.get("c")["requests"]
    assert len(requests) == 1
    assert requests[0]["url"] == "{{url}}/api/loans/{{loanId}}"
    assert requests[0]["headers"][0]["key"] == "Accept"


def test_save_request_overwrites_same_name(store):
    store.create("C")
    for method in ("GET", "POST"):
        store.save_request("c", {"name": "R", "method": method, "url": "u", "headers": [], "body": ""})
    requests = store.get("c")["requests"]
    assert len(requests) == 1
    assert requests[0]["method"] == "POST"


def test_delete_request_and_collection(store):
    store.create("C")
    store.save_request("c", {"name": "R", "method": "GET", "url": "u", "headers": [], "body": ""})
    store.delete_request("c", "R")
    assert store.get("c")["requests"] == []
    store.delete("c")
    assert store.list() == []


def test_archived_collection_is_hidden_from_list_but_kept_on_disk(store):
    """"Remove from Iris" must not be the same as Delete — the file (and its
    requests) stay on disk so the collection can be brought back later, it
    just stops showing up in the sidebar."""
    store.create("C")
    store.set_archived("c", True)
    assert store.list() == []
    assert store.get("c")["requests"] == []  # still there, just hidden


def test_unarchiving_makes_it_visible_again(store):
    store.create("C")
    store.set_archived("c", True)
    store.set_archived("c", False)
    assert [c["slug"] for c in store.list()] == ["c"]


def test_variables_round_trip(store):
    store.create("C")
    assert store.get_vars("c") == {}
    store.set_vars("c", {"url": "https://nucleus.example", "token": "abc"})
    assert store.get_vars("c")["url"] == "https://nucleus.example"


def test_vars_file_is_separate_from_collection_file(store):
    """Secrets must not be written into the exportable collection file."""
    store.create("C")
    store.set_vars("c", {"token": "secret-value"})
    with open(os.path.join(store.root, "c.json"), encoding="utf-8") as handle:
        assert "secret-value" not in handle.read()


def test_unknown_collection_raises(store):
    with pytest.raises(ValueError):
        store.get("nope")


# --- collection import ---

def _collection(items):
    return {"info": {"name": "T", "schema": collection_io.SCHEMA_V21}, "item": items}


def test_v21_collection_from_any_schema_domain_is_accepted():
    """_is_v21 only checks for a "v2.1" substring, not our own SCHEMA_V21
    domain specifically — a real-world export from any tool that produces
    v2.1-shaped collections must still import. Uses a schema string that
    is neither our own nor any particular vendor's, so this pins the
    substring-tolerance behavior without hardcoding a third-party name."""
    collection = {
        "info": {"name": "T", "schema": "https://schema.example.com/json/collection/v2.1.0/collection.json"},
        "item": [{"name": "R", "request": {"method": "GET", "url": "u", "header": []}}],
    }
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["name"] == "R"


def test_legacy_capture_script_translates_regardless_of_global_object_name():
    """_CAPTURE_RE matches <identifier>.setEnvironmentVariable(...) rather than
    a hardcoded global object name — real legacy scripts always call this on
    their scripting environment's own global, whatever it's named."""
    collection = _collection([{
        "name": "Login",
        "request": {"method": "POST", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": ['legacyGlobal.setEnvironmentVariable("token", jsonData.access_token);']},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "capture", "source": "body", "path": "access_token", "variable": "token"}
    ]


def test_capture_translates_pm_environment_set_form_with_json_object():
    """Category A: `pm.environment.set("name", json.path)` — same shape as
    setEnvironmentVariable but a different method name and a response object
    named `json`, the idiom used by 71 of the real file's 98 previously
    untranslated scripts."""
    collection = _collection([{
        "name": "R",
        "request": {"method": "POST", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": [
                'var json = JSON.parse(responseBody);',
                'pm.environment.set("billing_request", json.billing_requests.id);',
            ]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "capture", "source": "body", "path": "billing_requests.id", "variable": "billing_request"}
    ]
    assert "untranslatedScripts" not in parsed


@pytest.mark.parametrize("method", ["collectionVariables.set", "variables.set", "globals.set"])
def test_capture_translates_all_pm_set_method_forms(method):
    """The other three pm.X.set(...) forms besides pm.environment.set must
    also translate — same capture shape, different method name."""
    collection = _collection([{
        "name": "R",
        "request": {"method": "POST", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": [f'pm.{method}("token", json.access_token);']},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "capture", "source": "body", "path": "access_token", "variable": "token"}
    ]


def test_capture_translates_array_index_path_segment():
    """Category B: an array index in the path, e.g. json.events[0].id — a
    subset (20 of 98) of Category A's pattern. assertions.py's
    _json_path_get already handles [n] segments; only the capture regex's
    path character class needs widening here."""
    collection = _collection([{
        "name": "R",
        "request": {"method": "POST", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": ['pm.environment.set("event", json.events[0].id);']},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "capture", "source": "body", "path": "events[0].id", "variable": "event"}
    ]


def test_visualizer_set_call_and_its_template_blob_are_stripped_not_left_untranslated():
    """Category C: a real capture (Category A shape) immediately followed by
    a pm.visualizer.set(template, data) call whose first argument is a
    variable holding a multi-hundred-line HTML/CSS template literal (the
    real file's actual shape — the template is assigned separately, then
    passed by name). Neither the call nor the template variable's giant
    backtick literal may leak into untranslatedScripts."""
    huge_template = "\n".join(f"<div>{i}</div>" for i in range(50))
    collection = _collection([{
        "name": "R",
        "request": {"method": "POST", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": [
                'var json = JSON.parse(responseBody);',
                'pm.environment.set("billing_request", json.billing_requests.id);',
                f'var template = `{huge_template}`;',
                'pm.visualizer.set(template, {',
                '    response: pm.response.json()',
                '});',
            ]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "capture", "source": "body", "path": "billing_requests.id", "variable": "billing_request"}
    ]
    assert "untranslatedScripts" not in parsed


def test_two_statement_json_parse_response_text_idiom_captures():
    """Category D: `let x = JSON.parse(pm.response.text()); pm.environment.set(
    "name", x.path);` — the variable is discovered per-script (not a global
    allow-list) so a same-named variable in a different request's script
    scope can't leak in."""
    collection = _collection([{
        "name": "R",
        "request": {"method": "POST", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": [
                'let responseJSON = JSON.parse(pm.response.text());',
                'pm.environment.set("outbound_payment", responseJSON.outbound_payments.id);',
            ]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "capture", "source": "body", "path": "outbound_payments.id", "variable": "outbound_payment"}
    ]
    assert "untranslatedScripts" not in parsed


def test_two_statement_idiom_variable_scoped_per_script_not_global():
    """A variable named the same as another request's Category D variable,
    but used directly (without its own JSON.parse(pm.response.text())
    assignment) in THIS script, must NOT be treated as a valid capture
    source — proves the collected-variable allow-list is per-script."""
    collection = _collection([
        {
            "name": "A",
            "request": {"method": "POST", "url": "u", "header": []},
            "event": [{
                "listen": "test",
                "script": {"exec": [
                    'let responseJSON = JSON.parse(pm.response.text());',
                    'pm.environment.set("a", responseJSON.id);',
                ]},
            }],
        },
        {
            "name": "B",
            "request": {"method": "POST", "url": "u", "header": []},
            "event": [{
                "listen": "test",
                "script": {"exec": [
                    'pm.environment.set("b", responseJSON.id);',
                ]},
            }],
        },
    ])
    parsed = collection_io.parse_collection(collection)
    by_name = {r["name"]: r for r in parsed["requests"]}
    assert by_name["A"]["tests"] == [
        {"type": "capture", "source": "body", "path": "id", "variable": "a"}
    ]
    assert "tests" not in by_name["B"]
    assert parsed["untranslatedScripts"] == [
        {"request": "B", "script": 'pm.environment.set("b", responseJSON.id);'}
    ]


def test_legacy_assert_exists_script_translates_regardless_of_global_object_name():
    """_ASSERT_EXISTS_RE matches <identifier>.expect(...) rather than a
    hardcoded global object name, mirroring _CAPTURE_RE's convention."""
    collection = _collection([{
        "name": "R",
        "request": {"method": "GET", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": ["legacyGlobal.expect(jsonData.access_token).to.exist;"]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "assert", "source": "body", "path": "access_token", "operator": "exists", "expected": ""}
    ]


def test_legacy_assert_not_null_script_translates_regardless_of_global_object_name():
    collection = _collection([{
        "name": "R",
        "request": {"method": "GET", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": ["legacyGlobal.expect(jsonData.access_token).to.not.be.null;"]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "assert", "source": "body", "path": "access_token", "operator": "notNull", "expected": ""}
    ]


def test_legacy_assert_not_empty_script_translates_regardless_of_global_object_name():
    collection = _collection([{
        "name": "R",
        "request": {"method": "GET", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": ["legacyGlobal.expect(jsonData.items.length).to.be.above(0);"]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "assert", "source": "body", "path": "items", "operator": "notEmpty", "expected": ""}
    ]


def test_legacy_assert_equals_script_translates_regardless_of_global_object_name():
    collection = _collection([{
        "name": "R",
        "request": {"method": "GET", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": ["legacyGlobal.expect(jsonData.status).to.eql('ok');"]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "assert", "source": "body", "path": "status", "operator": "equals", "expected": "ok"}
    ]


def test_legacy_assert_status_script_translates_regardless_of_global_object_name():
    """`pm.response.to.have.status(200)` is the commercial client's own
    auto-suggested boilerplate and the single most common assertion in real
    scripts — was not among the five originally-recognised patterns, so it
    fell into untranslated (ROADMAP.md §12)."""
    collection = _collection([{
        "name": "R",
        "request": {"method": "GET", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": ["legacyGlobal.response.to.have.status(200);"]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert parsed["requests"][0]["tests"] == [
        {"type": "assert", "source": "status", "path": "", "operator": "equals", "expected": "200"}
    ]


def test_legacy_assert_status_text_form_stays_untranslated():
    """`.status("OK")` checks the HTTP reason phrase, not the numeric code —
    a genuinely different thing from `.status(200)`. Iris's response object
    only ever carries the numeric status (collection_routes.py), so mapping
    this onto the same `source: "status"` row would produce an assertion
    that's always false. Left untranslated (safety net) rather than silently
    shipping a broken always-red test."""
    collection = _collection([{
        "name": "R",
        "request": {"method": "GET", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": ["pm.response.to.have.status('OK');"]},
        }],
    }])
    parsed = collection_io.parse_collection(collection)
    assert "tests" not in parsed["requests"][0]
    assert parsed["untranslatedScripts"] == [
        {"request": "R", "script": "pm.response.to.have.status('OK');"}
    ]


def test_import_reads_url_raw_and_ignores_host_path_arrays():
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {
            "method": "POST",
            "url": {"raw": "{{url}}/api/x", "host": ["ignored"], "path": ["ignored"]},
            "header": [],
        },
    }]))
    assert parsed["requests"][0]["url"] == "{{url}}/api/x"


def test_import_accepts_url_as_plain_string():
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {"method": "GET", "url": "https://example.com/x", "header": []},
    }]))
    assert parsed["requests"][0]["url"] == "https://example.com/x"


def test_import_skips_disabled_headers():
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {
            "method": "GET",
            "url": "u",
            "header": [
                {"key": "Accept", "value": "application/json"},
                {"key": "Stale", "value": "x", "disabled": True},
            ],
        },
    }]))
    keys = [h["key"] for h in parsed["requests"][0]["headers"]]
    assert keys == ["Accept"]


def test_import_preserves_duplicate_case_variant_header_keys():
    """x-tenant-identifier and X-Tenant-Identifier are distinct on the wire."""
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {
            "method": "GET",
            "url": "u",
            "header": [
                {"key": "x-tenant-identifier", "value": "a"},
                {"key": "X-Tenant-Identifier", "value": "b"},
            ],
        },
    }]))
    assert len(parsed["requests"][0]["headers"]) == 2


def test_import_raw_body_and_empty_formdata():
    parsed = collection_io.parse_collection(_collection([
        {"name": "Raw", "request": {"method": "POST", "url": "u", "header": [],
                                    "body": {"mode": "raw", "raw": '{"a":1}'}}},
        {"name": "Form", "request": {"method": "POST", "url": "u", "header": [],
                                     "body": {"mode": "formdata", "formdata": []}}},
    ]))
    by_name = {r["name"]: r for r in parsed["requests"]}
    assert by_name["Raw"]["body"] == '{"a":1}'
    assert by_name["Form"]["body"] == ""


def test_import_walks_nested_folders(store):
    """Nested Postman folders create real Iris folders with a correct
    parentFolderId chain. Re-import dedupe and rename-resilience are
    covered by test_import_nested_folders.py."""
    import import_routes

    status, result = import_routes._import_collection(store, "nested-test", _collection([
        {"name": "Folder", "item": [
            {"name": "Inner", "request": {"method": "GET", "url": "u", "header": []}},
        ]},
    ]))
    assert status == 200
    data = store.get(result["slug"])
    folders = data["folders"]
    assert len(folders) == 1
    assert folders[0]["name"] == "Folder"
    assert folders[0].get("parentFolderId") is None
    request = data["requests"][0]
    assert request["name"] == "Inner"
    assert request["folderId"] == folders[0]["id"]


def test_import_extracts_distinct_variables_verbatim():
    """Inconsistent casing (loanid/loanId) must NOT be normalised together."""
    parsed = collection_io.parse_collection(_collection([
        {"name": "A", "request": {"method": "GET", "url": "{{url}}/{{loanid}}", "header": [
            {"key": "X", "value": "{{token}}"}]}},
        {"name": "B", "request": {"method": "POST", "url": "{{url}}/x", "header": [],
                                  "body": {"mode": "raw", "raw": '{"id":"{{loanId}}"}'}}},
    ]))
    assert parsed["variables"] == ["loanId", "loanid", "token", "url"]


def test_import_preserves_absolute_host_urls():
    """34 of the real collection's requests bypass {{url}} — do not rewrite them."""
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {"method": "GET", "url": "https://cbuat-onb.oaknorth-it.com/api/x", "header": []},
    }]))
    assert parsed["requests"][0]["url"] == "https://cbuat-onb.oaknorth-it.com/api/x"


def test_import_rejects_non_v21_shape():
    with pytest.raises(ValueError):
        collection_io.parse_collection({"nope": True})


def test_export_round_trips_through_import():
    original = [{
        "name": "R",
        "method": "POST",
        "url": "{{url}}/api/x",
        "headers": [{"key": "Accept", "value": "application/json"}],
        "body": '{"a":1}',
    }]
    exported = collection_io.to_collection("T", original)
    reparsed = collection_io.parse_collection(json.loads(json.dumps(exported)))
    assert reparsed["requests"] == original


# --- substitution ---

def test_substitute_replaces_known_vars_and_leaves_unknown():
    out = collection_io.substitute("{{url}}/x/{{missing}}", {"url": "https://a"})
    assert out == "https://a/x/{{missing}}"


def test_substitute_is_applied_to_headers_and_body():
    request = {
        "method": "POST",
        "url": "{{url}}/x",
        "headers": [{"key": "Authorization", "value": "Bearer {{token}}"}],
        "body": '{"t":"{{token}}"}',
    }
    resolved = collection_io.resolve_request(request, {"url": "https://a", "token": "T"})
    assert resolved["url"] == "https://a/x"
    assert resolved["headers"][0]["value"] == "Bearer T"
    assert resolved["body"] == '{"t":"T"}'


def test_substitute_trims_whitespace_inside_braces_like_the_csv_runner():
    """{{ token }} (internal spaces) is a common authoring style —
    run_api_from_csv.py's DOUBLE_BRACE_RE already trims it; this path used
    to look up the literal key " token " and find nothing, leaving the
    placeholder unresolved, an inconsistent behavior difference between
    the two runners for the identical input."""
    out = collection_io.substitute("{{ token }}", {"token": "T"})
    assert out == "T"


# --- the real file ---

@needs_real_collection
def test_real_collection_imports_as_expected():
    with open(REAL_COLLECTION, encoding="utf-8") as handle:
        parsed = collection_io.parse_collection(json.load(handle))
    assert len(parsed["requests"]) == 94
    assert len(parsed["variables"]) == 11
    assert "url" in parsed["variables"] and "token" in parsed["variables"]
    absolute = [r for r in parsed["requests"] if r["url"].startswith("http")]
    assert len(absolute) == 34
    assert all(r["method"] for r in parsed["requests"])


@needs_real_script_collection
def test_real_gocardless_collection_untranslated_scripts_near_zero():
    """Phase5d: this real 189-request export had 98 previously-untranslated
    scripts across four idioms (pm.X.set(...) method variants, array-index
    paths, pm.visualizer.set(...) template blobs, and the two-statement
    JSON.parse(pm.response.text()) idiom). All four are now covered."""
    with open(REAL_SCRIPT_COLLECTION, encoding="utf-8") as handle:
        parsed = collection_io.parse_collection(json.load(handle))
    assert len(parsed.get("untranslatedScripts", [])) == 0


# --- regression tests added after the independent-review pass ---

def test_secret_named_var_never_persisted_to_disk(store):
    """token/secret/password/cookie-named vars stay in-memory only — never written
    to the collection file OR the vars file, matching the plan's "session only"
    design decision (previously they were written to <slug>.env.json in plaintext)."""
    store.create("C")
    store.set_vars("c", {"token": "eyJ-super-secret", "url": "https://a"})
    assert store.get_vars("c")["token"] == "eyJ-super-secret"
    assert store.get_vars("c")["url"] == "https://a"
    with open(os.path.join(store.root, "c.json"), encoding="utf-8") as handle:
        assert "eyJ-super-secret" not in handle.read()
    vars_path = os.path.join(store.root, "c.env.json")
    if os.path.isfile(vars_path):
        with open(vars_path, encoding="utf-8") as handle:
            assert "eyJ-super-secret" not in handle.read()


def test_corrupted_collection_file_raises_distinct_error(store):
    """A JSONDecodeError (subclass of ValueError) must not be mistaken for
    "collection doesn't exist" — corruption gets its own exception/status."""
    store.create("C")
    with open(os.path.join(store.root, "c.json"), "w", encoding="utf-8") as handle:
        handle.write("{not valid json")
    with pytest.raises(collection_store.CollectionCorrupted):
        store.get("c")
    # list() must not let one corrupted file take down the whole listing
    summaries = store.list()
    assert any(s["slug"] == "c" and "error" in s for s in summaries)


def test_export_round_trips_tests_and_auth():
    """Phase 4 additions (declarative tests, per-request auth) must survive an
    export -> re-import round trip, not just the original name/method/url/headers/body
    fields covered by test_export_round_trips_through_import.

    "auth" here is Iris's own translated {mode, ...} shape (not the raw
    source-collection-format shape a genuine external import carries) —
    to_collection writes it out as-is, and _translate_auth must recognize and
    pass through its own shape on re-import, or re-importing a file Iris
    itself just exported would silently drop every request's auth."""
    original = [{
        "name": "R",
        "method": "POST",
        "url": "{{url}}/api/x",
        "headers": [{"key": "Accept", "value": "application/json"}],
        "body": '{"a":1}',
        "tests": [{"type": "assert", "source": "status", "path": "", "operator": "equals", "expected": "200"}],
        "auth": {"mode": "bearer", "bearerToken": "{{token}}"},
    }]
    exported = collection_io.to_collection("T", original)
    reparsed = collection_io.parse_collection(json.loads(json.dumps(exported)))
    assert reparsed["requests"] == original


def test_export_redacts_a_secret_named_header_with_a_literal_value():
    original = [{
        "name": "R", "method": "GET", "url": "u",
        "headers": [{"key": "Cookie", "value": "org.apache.fincn.refreshToken=abc123realvalue"}],
    }]
    exported = collection_io.to_collection("T", original)
    assert exported["item"][0]["request"]["header"][0]["value"] == "***"


def test_translate_scripts_reports_unmatched_statement_mixed_with_matched_one():
    """A script block containing one recognised statement and one unrecognised one
    must not silently drop the unrecognised half just because something else in the
    same block matched (previously `matched_any` gated the entire block)."""
    parsed = collection_io.parse_collection(_collection([{
        "name": "R",
        "request": {"method": "GET", "url": "u", "header": []},
        "event": [{
            "listen": "test",
            "script": {"exec": [
                "pm.expect(res.someField).to.exist",
                "pm.response.to.have.jsonSchema(schema)",
            ]},
        }],
    }]))
    request = parsed["requests"][0]
    assert request["tests"] == [
        {"type": "assert", "source": "body", "path": "someField", "operator": "exists", "expected": ""}
    ]
    assert parsed["untranslatedScripts"] == [
        {"request": "R", "script": "pm.response.to.have.jsonSchema(schema)"}
    ]


def test_parse_collection_reports_unsupported_body_mode():
    """_body_of() silently returns "" for formdata (and any other non-raw
    mode) — the import must say so, the same way untranslated scripts are
    surfaced, instead of an imported request quietly having no body."""
    parsed = collection_io.parse_collection(_collection([{
        "name": "Upload",
        "request": {
            "method": "POST", "url": "u", "header": [],
            "body": {"mode": "formdata", "formdata": [{"key": "file", "type": "file"}]},
        },
    }]))
    assert parsed["requests"][0]["body"] == ""
    assert parsed["unsupportedBodyModes"] == [{"request": "Upload", "mode": "formdata"}]


def test_parse_collection_does_not_flag_a_raw_body_or_no_body_at_all():
    parsed = collection_io.parse_collection(_collection([
        {"name": "A", "request": {"method": "POST", "url": "u", "header": [], "body": {"mode": "raw", "raw": "{}"}}},
        {"name": "B", "request": {"method": "GET", "url": "u", "header": []}},
    ]))
    assert parsed.get("unsupportedBodyModes", []) == []


def test_malformed_collection_item_raises_clean_value_error():
    """A missing 'name' must surface as a clear ValueError, not a raw KeyError."""
    with pytest.raises(ValueError):
        collection_io.parse_collection(_collection([{"request": {"method": "GET", "url": "u", "header": []}}]))


def test_send_one_capture_persists_to_active_environment_not_collection(store, tmp_path, monkeypatch):
    """A Capture test row (e.g. pulling a token out of a Token Generation
    response) must land in the ACTIVE ENVIRONMENT when one is selected, so it's
    usable across every collection — not just the collection it was captured
    in. Previously it always wrote into the collection's own vars."""
    import collection_routes

    env_store = environment_store.EnvironmentStore(str(tmp_path / "environments"))
    env_slug = env_store.create("Dev")
    store.create("C")
    store.save_request("c", {
        "name": "Login",
        "method": "POST",
        "url": "http://example.invalid/login",
        "headers": [],
        "body": "",
        "tests": [{"type": "capture", "source": "body", "path": "accessToken", "variable": "token"}],
    })

    class _FakeResponse:
        status_code = 200
        content = b'{"accessToken": "eyJ-captured"}'
        text = '{"accessToken": "eyJ-captured"}'
        headers = {}

    monkeypatch.setattr(collection_routes.requests, "request", lambda *a, **k: _FakeResponse())

    status, result = collection_routes._send_one(
        store,
        {"slug": "c", "requestName": "Login", "environmentSlug": env_slug, "auth": {"mode": "none"}},
        env_store,
    )
    assert status == 200
    assert result["tests"][0]["passed"] is True
    assert env_store.get_vars(env_slug)["token"] == "eyJ-captured"
    assert "token" not in store.get_vars("c")


def test_import_disambiguates_duplicate_request_names(store):
    """The real Lending export has 4 pairs of requests sharing a display name
    (different content). Importing must not silently collapse them down to
    whichever saved last — every distinct source item must survive."""
    import import_routes

    payload = _collection([
        {"name": "Fee Accrual", "request": {"method": "GET", "url": "u1", "header": []}},
        {"name": "Fee Accrual", "request": {"method": "POST", "url": "u2", "header": []}},
        {"name": "Fee Accrual", "request": {"method": "PUT", "url": "u3", "header": []}},
    ])
    status, result = import_routes._import_collection(store, "dup-test", payload)
    assert status == 200
    assert result["imported"] == 3
    requests = store.get(result["slug"])["requests"]
    assert len(requests) == 3
    names = [r["name"] for r in requests]
    assert names == ["Fee Accrual", "Fee Accrual (2)", "Fee Accrual (3)"]
    methods = {r["name"]: r["method"] for r in requests}
    assert methods == {"Fee Accrual": "GET", "Fee Accrual (2)": "POST", "Fee Accrual (3)": "PUT"}


def test_archive_route_hides_collection_without_deleting_it(store):
    import collection_routes

    store.create("C")
    status, result = collection_routes.handle_post(store, "/api/collections/c/archive", {"archived": True})
    assert status == 200
    assert result == {"archived": True}
    assert store.list() == []
    assert store.get("c")["requests"] == []


def test_reimporting_an_archived_collection_makes_it_visible_again(store):
    """The whole point of "Remove from Iris" (archive, not delete) is that the
    user can bring a collection back by re-importing the same export — it
    must reappear rather than staying hidden."""
    import import_routes

    payload = _collection([{"name": "R", "request": {"method": "GET", "url": "u", "header": []}}])
    status, result = import_routes._import_collection(store, "reimport-test", payload)
    slug = result["slug"]
    store.set_archived(slug, True)
    assert store.list() == []

    status, result = import_routes._import_collection(store, slug, payload)
    assert status == 200
    assert [c["slug"] for c in store.list()] == [slug]


def test_save_request_preserves_imported_auth_on_unrelated_edit(store):
    """Editing an imported request's URL (or any UI-managed field) and saving
    must not silently drop its per-request auth — auth has no editor in the
    UI, so _save_request's payload never carries it, but the save must not
    treat that as "auth removed"."""
    import collection_routes
    import import_routes

    payload = _collection([{
        "name": "Get Loan",
        "request": {
            "method": "GET",
            "url": "{{url}}/api/loans",
            "header": [],
            "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}"}]},
        },
    }])
    status, result = import_routes._import_collection(store, "auth-test", payload)
    assert status == 200
    slug = result["slug"]

    status, _ = collection_routes._save_request(store, slug, {
        "name": "Get Loan",
        "method": "GET",
        "url": "{{url}}/api/loans/{{loanId}}",
        "headers": [],
        "body": "",
    })
    assert status == 200

    saved = store.get(slug)["requests"][0]
    assert saved["url"] == "{{url}}/api/loans/{{loanId}}"
    assert saved["auth"] == {"mode": "bearer", "bearerToken": "{{token}}"}


def test_send_one_capture_falls_back_to_collection_when_no_environment(store, monkeypatch):
    """Same capture, but with no active environment — must still persist
    somewhere (the collection's own vars), not silently disappear."""
    import collection_routes

    store.create("C")
    store.save_request("c", {
        "name": "Login",
        "method": "POST",
        "url": "http://example.invalid/login",
        "headers": [],
        "body": "",
        "tests": [{"type": "capture", "source": "body", "path": "accessToken", "variable": "sessionId"}],
    })

    class _FakeResponse:
        status_code = 200
        content = b'{"accessToken": "no-env-value"}'
        text = '{"accessToken": "no-env-value"}'
        headers = {}

    monkeypatch.setattr(collection_routes.requests, "request", lambda *a, **k: _FakeResponse())

    status, result = collection_routes._send_one(
        store, {"slug": "c", "requestName": "Login", "auth": {"mode": "none"}}, None
    )
    assert status == 200
    assert store.get_vars("c")["sessionId"] == "no-env-value"


def test_send_one_uses_proxy_resolver_for_custom_mode(store, monkeypatch):
    """When proxySettings.mode is 'custom', resolve_proxy should be called to
    build the proxies dict for the outgoing requests.request() call."""
    import collection_routes

    captured = {}

    def fake_request(method, url, **kwargs):
        captured["proxies"] = kwargs.get("proxies")
        class _FakeResponse:
            status_code = 200
            content = b'{}'
            text = '{}'
            headers = {}
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", fake_request)
    data = {
        "request": {"method": "GET", "url": "https://example.com", "headers": []},
        "proxySettings": {"mode": "custom", "url": "http://127.0.0.1:9999", "username": "", "password": "", "bypassList": []},
    }
    collection_routes._send_one(store, data)
    assert captured["proxies"] == {"http": "http://127.0.0.1:9999", "https": "http://127.0.0.1:9999"}


def test_send_one_bypasses_proxy_for_listed_host(store, monkeypatch):
    """When a host is in the proxySettings.bypassList, resolve_proxy should
    return None even if a custom proxy URL is configured."""
    import collection_routes

    captured = {}

    def fake_request(method, url, **kwargs):
        captured["proxies"] = kwargs.get("proxies")
        class _FakeResponse:
            status_code = 200
            content = b'{}'
            text = '{}'
            headers = {}
        return _FakeResponse()

    monkeypatch.setattr(collection_routes.requests, "request", fake_request)
    data = {
        "request": {"method": "GET", "url": "https://example.com", "headers": []},
        "proxySettings": {
            "mode": "custom", "url": "http://127.0.0.1:9999", "username": "", "password": "",
            "bypassList": ["example.com"],
        },
    }
    collection_routes._send_one(store, data)
    assert captured["proxies"] == {"http": None, "https": None}
