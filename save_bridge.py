"""Native save dialogs, exposed to the frontend as pywebview's js_api. This
replaces `URL.createObjectURL` + `<a download>`, which always lands files in
~/Downloads with a browser-chosen name — never the folder the user actually
wants. Same osascript pattern as native_pickers.py.

Also carries the clipboard bridge: `navigator.clipboard` returns
NotAllowedError inside pywebview's WKWebView (no user-gesture context the
permission model recognizes), so writes go through `pbcopy` instead —
reliable, no extra dependency, no permission prompt.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAST_DIR_PATH = os.path.join(HERE, ".save_bridge_last_dir")


def _last_directory():
    try:
        with open(LAST_DIR_PATH, "r", encoding="utf-8") as handle:
            path = handle.read().strip()
        return path if path and os.path.isdir(path) else os.path.expanduser("~/Downloads")
    except OSError:
        return os.path.expanduser("~/Downloads")


def _remember_directory(path):
    try:
        with open(LAST_DIR_PATH, "w", encoding="utf-8") as handle:
            handle.write(path)
    except OSError:
        pass


class SaveBridgeApi:
    """Exposed to JS as `window.pywebview.api`. Every method takes and
    returns JSON-serializable values only, per pywebview's js_api contract."""

    def save_text_file(self, suggested_name, content):
        if sys.platform != "darwin":
            return {"saved": False, "error": "Native save is supported on macOS only"}
        default_dir = _last_directory()
        script = (
            f'POSIX path of (choose file name with prompt "Save As" '
            f'default name "{_escape(suggested_name)}" '
            f'default location (POSIX file "{_escape(default_dir)}"))'
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300,
        )
        if result.returncode != 0:
            return {"saved": False, "error": "Save was cancelled"}
        path = result.stdout.strip()
        if not path:
            return {"saved": False, "error": "Save was cancelled"}
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
        except OSError as exc:
            return {"saved": False, "error": str(exc)}
        _remember_directory(os.path.dirname(path))
        return {"saved": True, "path": path}

    def clipboard_write(self, text):
        try:
            subprocess.run(["pbcopy"], input=text, text=True, timeout=10, check=True)
            return {"ok": True}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": str(exc)}


def _escape(value):
    # json.dumps already produces a correctly quote/backslash-escaped
    # string-literal body (AppleScript and JSON agree on \" and \\) — a
    # trailing .replace('"', '\\"') here used to re-escape the quotes
    # json.dumps had already escaped, corrupting the generated osascript
    # command whenever the value contained a `"`.
    return json.dumps(value)[1:-1]
