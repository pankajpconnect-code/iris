"""Tests for assertions._compare's equals/notEquals coercion — caught by an
independent review: plain str(actual) == str(expected) meant a genuinely
correct API response could still grade FAIL (10.0 vs "10", true vs "true").
"""

import assertions


def test_equals_numeric_float_and_string_int_are_equal():
    assert assertions._compare("equals", 10.0, "10") is True


def test_equals_numeric_string_and_int_are_equal():
    assert assertions._compare("equals", "10", 10) is True


def test_equals_json_true_and_string_true_case_insensitive():
    assert assertions._compare("equals", True, "true") is True
    assert assertions._compare("equals", True, "TRUE") is True
    assert assertions._compare("equals", False, "false") is True


def test_not_equals_mirrors_equals_coercion():
    assert assertions._compare("notEquals", 10.0, "10") is False
    assert assertions._compare("notEquals", True, "true") is False


def test_equals_still_fails_on_genuinely_different_values():
    assert assertions._compare("equals", "10", "11") is False
    assert assertions._compare("equals", True, "false") is False


def test_equals_non_numeric_non_boolean_falls_back_to_string_comparison():
    assert assertions._compare("equals", "abc", "abc") is True
    assert assertions._compare("equals", "abc", "abd") is False


def test_equals_bool_is_not_treated_as_the_number_one():
    """bool is a subclass of int in Python — True must not equal "1" via
    numeric coercion, only via the boolean-aware path (which "1" doesn't
    match either, since it's not "true"/"false")."""
    assert assertions._compare("equals", True, "1") is False
