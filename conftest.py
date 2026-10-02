"""This directory has no runtime dependency on any sibling tool directory."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeAPIServer:
    """Minimal stdlib ThreadingHTTPServer fake for run_orchestrator integration
    tests — no pytest-httpserver / responses per requirements.txt constraints.

    set_responses(path, [{"status":, "body":, "delay":, "headers":}, ...]) queues
    canned responses consumed in order; the last one repeats once the queue drains.
    """

    def __init__(self):
        self.routes = {}
        self.requests = []
        self._lock = threading.Lock()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def set_responses(self, path, responses):
        with self._lock:
            self.routes[path] = list(responses)

    def _next_response(self, path):
        with self._lock:
            queue = self.routes.get(path)
            if not queue:
                return {"status": 404, "body": "{}"}
            return queue.pop(0) if len(queue) > 1 else queue[0]

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                with server._lock:
                    server.requests.append({
                        "method": self.command,
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": body.decode("utf-8"),
                    })
                spec = server._next_response(self.path)
                if spec.get("delay"):
                    time.sleep(spec["delay"])
                payload = spec.get("body", "{}")
                encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
                self.send_response(spec.get("status", 200))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                for key, value in (spec.get("headers") or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                self._handle()

            def do_POST(self):
                self._handle()

            def do_PUT(self):
                self._handle()

            def do_DELETE(self):
                self._handle()

            def log_message(self, *args):
                pass

        return Handler

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake_server():
    server = FakeAPIServer()
    yield server
    server.stop()
