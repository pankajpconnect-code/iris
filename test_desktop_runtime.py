"""Tests for desktop_runtime.py: Python interpreter resolution (a
Finder-launched .app inherits only /usr/bin:/bin:/usr/sbin:/sbin) and the
single-instance probe against a local stub server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import desktop_runtime


def test_find_python_raises_named_error_when_no_candidate_matches(monkeypatch):
    monkeypatch.setattr(desktop_runtime.glob, "glob", lambda pattern: [])
    with pytest.raises(desktop_runtime.NoSuitablePythonError, match="No python3"):
        desktop_runtime.find_python()


def test_find_python_skips_too_old_candidate(monkeypatch, tmp_path):
    old_python = tmp_path / "python3"
    old_python.write_text("#!/bin/sh\n")
    old_python.chmod(0o755)

    monkeypatch.setattr(desktop_runtime.glob, "glob", lambda pattern: [str(old_python)])
    monkeypatch.setattr(desktop_runtime, "_version_tuple", lambda path: (3, 9))

    with pytest.raises(desktop_runtime.NoSuitablePythonError):
        desktop_runtime.find_python()


def test_find_python_returns_first_candidate_meeting_min_version(monkeypatch, tmp_path):
    good_python = tmp_path / "python3"
    good_python.write_text("#!/bin/sh\n")
    good_python.chmod(0o755)

    monkeypatch.setattr(desktop_runtime.glob, "glob", lambda pattern: [str(good_python)])
    monkeypatch.setattr(desktop_runtime, "_version_tuple", lambda path: (3, 12))

    assert desktop_runtime.find_python() == str(good_python)


def test_find_python_never_falls_through_to_an_unlisted_interpreter(monkeypatch):
    """Regression guard for the PATH risk: even if every candidate is
    missing, find_python must not silently return /usr/bin/python3."""
    monkeypatch.setattr(desktop_runtime.glob, "glob", lambda pattern: [])
    with pytest.raises(desktop_runtime.NoSuitablePythonError):
        result = desktop_runtime.find_python()
        assert result != "/usr/bin/python3"


class _RunsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/runs":
            body = json.dumps({"runs": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def running_stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RunsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    server.server_close()


def test_probe_running_instance_true_when_server_answers(running_stub):
    assert desktop_runtime.probe_running_instance(running_stub) is True


def test_probe_running_instance_false_on_closed_port():
    # Port 1 is a privileged, essentially-never-bound port — nothing should
    # be listening there in any test environment.
    assert desktop_runtime.probe_running_instance(1, timeout=0.2) is False
