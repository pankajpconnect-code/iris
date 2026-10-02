"""Declarative test/assertion engine for the API console's Tests tab.

No JS engine — two row types (assert, capture) cover the real collection's
script usage. Kept dependency-free (no import of collection_io) so
run_api_from_csv.py can use this without losing its standalone-CLI property.
"""

import json
import re

_VAR_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
_PATH_SEGMENT = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _substitute(text, variables):
    def _replace(match):
        key = match.group(1)
        if key in variables:
            return str(variables[key])
        return match.group(0)

    return _VAR_PATTERN.sub(_replace, str(text or ""))


def _json_path_get(data, path):
    """Minimal JSON-path lookup: dot segments plus [n] array indices, e.g. 'data.items[0].id'."""
    if not path:
        return data
    current = data
    for match in _PATH_SEGMENT.finditer(path):
        key, index = match.groups()
        if current is None:
            return None
        if key is not None:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        else:
            idx = int(index)
            if isinstance(current, list) and -len(current) <= idx < len(current):
                current = current[idx]
            else:
                return None
    return current


def _parsed_body(response):
    body = response.get("body")
    if isinstance(body, (dict, list)):
        return body
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        return body


def _source_value(source, path, response):
    if source == "status":
        return response.get("status")
    if source == "header":
        headers = response.get("headers") or {}
        for key, value in headers.items():
            if key.lower() == str(path or "").lower():
                return value
        return None
    return _json_path_get(_parsed_body(response), path)


def _as_number(value):
    if isinstance(value, bool):
        return None  # bool is an int subclass in Python — never let True == 1 slip through here
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def _values_equal(actual, expected):
    """A response's JSON types don't always match the CSV/UI-authored
    expected value's type on the wire (a float `10.0` vs the string "10",
    a JSON boolean vs the literal string "true") — genuinely correct
    responses were failing this comparison on type alone."""
    actual_bool, expected_bool = _as_bool(actual), _as_bool(expected)
    if actual_bool is not None and expected_bool is not None:
        return actual_bool == expected_bool
    actual_num, expected_num = _as_number(actual), _as_number(expected)
    if actual_num is not None and expected_num is not None:
        return actual_num == expected_num
    return str(actual) == str(expected)


def _compare(operator, actual, expected):
    if operator == "equals":
        return _values_equal(actual, expected)
    if operator == "notEquals":
        return not _values_equal(actual, expected)
    if operator == "exists":
        return actual is not None
    if operator == "notNull":
        return actual is not None
    if operator == "notEmpty":
        if actual is None:
            return False
        try:
            return len(actual) > 0
        except TypeError:
            return True
    if operator == "contains":
        return str(expected) in str(actual)
    if operator == "matches":
        try:
            return re.search(str(expected), str(actual)) is not None
        except re.error:
            return False
    if operator in ("gt", "gte", "lt", "lte"):
        try:
            a, e = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {"gt": a > e, "gte": a >= e, "lt": a < e, "lte": a <= e}[operator]
    raise ValueError(f"Unknown operator '{operator}'")


def run_assertions(tests, response, variables):
    """Evaluate assert/capture/python test rows against one HTTP response.

    `response` is {"status", "headers", "body"} (body may be a raw string or
    already-parsed JSON). Returns (results, updated_variables) — captures are
    folded into updated_variables immediately so a later row's `expected` can
    reference an earlier capture in the same test list (request chaining).
    """
    results = []
    updated_variables = dict(variables or {})
    for test in tests or []:
        test_type = test.get("type", "assert")
        if test_type == "capture":
            value = _source_value(test.get("source") or "body", test.get("path", ""), response)
            variable = test.get("variable", "")
            if variable:
                updated_variables[variable] = value
            results.append({
                "type": "capture",
                "variable": variable,
                "actual": value,
                "passed": value is not None,
                "message": f"captured {variable} = {value!r}" if variable else "no variable name set",
            })
            continue
        if test_type == "python":
            # Trusted local-tool escape hatch — no sandbox by design; only
            # reachable for requests loaded from a saved
            # collection (collection_routes._resolve_send_one_request rejects this
            # test type on an inline/unsaved request body).
            snippet = test.get("expected") or test.get("path") or ""
            try:
                scope = {"response": {**response, "json": _parsed_body(response)}, "vars": updated_variables}
                passed = bool(eval(snippet, dict(scope)))
                results.append({"type": "python", "expected": snippet, "passed": passed, "actual": None, "message": ""})
            except Exception as exc:
                results.append({"type": "python", "expected": snippet, "passed": False, "actual": None, "message": str(exc)})
            continue
        source = test.get("source") or "body"
        path = test.get("path", "")
        operator = test.get("operator") or "exists"
        expected = _substitute(test.get("expected", ""), updated_variables)
        actual = _source_value(source, path, response)
        try:
            passed = _compare(operator, actual, expected)
        except ValueError as exc:
            passed = False
            actual = f"error: {exc}"
        results.append({
            "type": "assert",
            "source": source,
            "path": path,
            "operator": operator,
            "expected": expected,
            "actual": actual,
            "passed": passed,
        })
    return results, updated_variables
