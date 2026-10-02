"""Thin wrapper around the macOS `security` CLI for storing environment
secrets outside any JSON file — no new dependency, following the osascript
subprocess precedent already set by native_pickers.py.

Guarded by sys.platform != "darwin": off-macOS, every call raises
KeychainUnavailable so callers fall back to the original in-memory-only
behaviour (secrets lost on restart) rather than crashing.
"""
import subprocess
import sys

SERVICE_PREFIX = "iris"


class KeychainUnavailable(RuntimeError):
    """Keychain is not usable here — wrong platform, or the `security` CLI
    call failed (denied, locked keychain, etc.). Callers should catch this
    and fall back to session-memory-only secrets."""


def _service_name(slug):
    return f"{SERVICE_PREFIX}:{slug}"


def _require_darwin():
    if sys.platform != "darwin":
        raise KeychainUnavailable("Keychain storage is only available on macOS")


def set_secret(slug, name, value):
    """Create or update (via -U, update-in-place) a generic password item
    keyed by (service=iris:<slug>, account=<name>)."""
    _require_darwin()
    service = _service_name(slug)
    result = subprocess.run(
        ["security", "add-generic-password", "-U", "-a", name, "-s", service, "-w", value],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise KeychainUnavailable(result.stderr.strip() or "security add-generic-password failed")


def get_secret(slug, name):
    """Returns the stored value, or None if no such item exists (not found
    is a normal, expected outcome — e.g. a var created this session that
    hasn't round-tripped through the Keychain yet)."""
    _require_darwin()
    service = _service_name(slug)
    result = subprocess.run(
        ["security", "find-generic-password", "-a", name, "-s", service, "-w"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def delete_secret(slug, name):
    """No-op if the item doesn't exist — deletion is idempotent by design
    (matches environment_store.delete_var's pop(..., None) semantics)."""
    _require_darwin()
    service = _service_name(slug)
    subprocess.run(
        ["security", "delete-generic-password", "-a", name, "-s", service],
        capture_output=True, text=True, timeout=10,
    )
