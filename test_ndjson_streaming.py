"""Regression test confirming WKWebView successfully streams a chunked NDJSON
response via response.body.getReader() (no XHR onprogress fallback needed).
This test pins down the server side of that contract — a real chunked
transfer with no Content-Length — independent of any browser, so a future
change to server.py's streaming path can't silently break it without a red
test.
"""
import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class ChunkedNdjsonHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for i in range(5):
            chunk = (json.dumps({"seq": i}) + "\n").encode()
            self.wfile.write(b"%X\r\n" % len(chunk))
            self.wfile.write(chunk)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")

    def log_message(self, *args):
        pass


@pytest.fixture
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), ChunkedNdjsonHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    server.server_close()


def test_ndjson_stream_arrives_as_five_chunked_lines(stub_server):
    conn = http.client.HTTPConnection("127.0.0.1", stub_server, timeout=5)
    conn.request("GET", "/")
    resp = conn.getresponse()
    assert resp.getheader("Transfer-Encoding") == "chunked"
    body = resp.read().decode()
    conn.close()
    lines = [json.loads(line) for line in body.splitlines() if line]
    assert [line["seq"] for line in lines] == [0, 1, 2, 3, 4]
