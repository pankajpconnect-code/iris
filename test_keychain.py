"""Round-trip test against the real macOS Keychain via the `security` CLI.
Entirely local (no network, no live environment) — skipped off-darwin,
where keychain.py itself refuses to run. Always cleans up the item it
creates so repeated test runs don't accumulate Keychain entries.
"""
import sys

import pytest

import keychain

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Keychain is macOS-only")

TEST_SLUG = "iris-pytest"
TEST_NAME = "pytest-round-trip-var"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    try:
        keychain.delete_secret(TEST_SLUG, TEST_NAME)
    except keychain.KeychainUnavailable:
        pass


def test_set_then_get_round_trips():
    keychain.set_secret(TEST_SLUG, TEST_NAME, "round-trip-value")
    assert keychain.get_secret(TEST_SLUG, TEST_NAME) == "round-trip-value"


def test_set_twice_updates_in_place():
    keychain.set_secret(TEST_SLUG, TEST_NAME, "first-value")
    keychain.set_secret(TEST_SLUG, TEST_NAME, "second-value")
    assert keychain.get_secret(TEST_SLUG, TEST_NAME) == "second-value"


def test_get_missing_item_returns_none():
    assert keychain.get_secret(TEST_SLUG, "no-such-var") is None


def test_delete_then_get_returns_none():
    keychain.set_secret(TEST_SLUG, TEST_NAME, "to-be-deleted")
    keychain.delete_secret(TEST_SLUG, TEST_NAME)
    assert keychain.get_secret(TEST_SLUG, TEST_NAME) is None


def test_delete_missing_item_is_a_no_op():
    keychain.delete_secret(TEST_SLUG, "never-existed")  # must not raise
