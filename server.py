"""
Iris — API console (collections, environments, tests, and a CSV batch
runner) for the lending APIs, packaged as a native macOS app.

Usage:
    python3 server.py
    open http://localhost:5090
"""

import json
import mimetypes
import os
import re
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))

import collection_routes
import collection_store
import environment_routes
import environment_store
import folder_routes
import import_routes
import native_pickers
import run_history_store
import run_orchestrator
import runner_commands

TEMPLATE_ROOT = os.path.join(HERE, "templates")
STATIC_ROOT = os.path.join(HERE, "static")
RUNS_DIR = os.path.join(HERE, "runs")
COLLECTION_STORE = collection_store.CollectionStore(os.path.join(HERE, "collections"))
ENVIRONMENT_STORE = environment_store.EnvironmentStore(os.path.join(HERE, "environments"))
RUN_ITEM_RE = re.compile(r"^/api/runs/([^/]+)$")
RUN_EXPORT_RE = re.compile(r"^/api/runs/([^/]+)/export$")
PREVIEW_ITERATION_LIMIT = 5


class ClientDisconnected(Exception):
    pass


class IrisRequestHandler(BaseHTTPRequestHandler):
    server_version = "Iris/1.0"

    def do_GET(self):
        request_path = urlparse(self.path).path
        if request_path in {"/", "/index.html"}:
            self._send_file(os.path.join(TEMPLATE_ROOT, "index.html"), "text/html; charset=utf-8")
            return
        if request_path.startswith("/static/"):
            rel = unquote(request_path[len("/static/"):])
            path = os.path.abspath(os.path.join(STATIC_ROOT, rel))
            if path.startswith(STATIC_ROOT + os.sep) and os.path.isfile(path):
                self._send_file(path, mimetypes.guess_type(path)[0] or "application/octet-stream")
                return
        if request_path == "/api/runs":
            self._send_json({"runs": run_history_store.list_runs(RUNS_DIR)})
            return
        export_match = RUN_EXPORT_RE.match(request_path)
        if export_match:
            self._send_run_export(unquote(export_match.group(1)))
            return
        run_item_match = RUN_ITEM_RE.match(request_path)
        if run_item_match:
            try:
                doc = run_history_store.get_run(RUNS_DIR, unquote(run_item_match.group(1)))
            except run_history_store.InvalidRunId as exc:
                self._send_json({"error": str(exc)}, status=400)
            except run_history_store.RunNotFound as exc:
                self._send_json({"error": str(exc)}, status=404)
            else:
                self._send_json(doc)
            return
        try:
            console_result = collection_routes.handle_get(COLLECTION_STORE, request_path)
            if console_result is None:
                console_result = environment_routes.handle_get(ENVIRONMENT_STORE, request_path)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        if console_result is not None:
            status, body = console_result
            self._send_json(body, status=status)
            return
        if request_path == "/api/choose-csv":
            try:
                self._send_json(native_pickers.choose_csv_file())
            except native_pickers.PickerCancelled:
                self._send_json({"cancelled": True})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        if request_path == "/api/choose-output-folder":
            try:
                self._send_json(native_pickers.choose_output_folder())
            except native_pickers.PickerCancelled:
                self._send_json({"cancelled": True})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"error": "Not found"}, status=404)

    def _same_origin(self):
        """Minimal CSRF guard: browsers send Origin on cross-origin state-changing
        requests, so a mismatch against our own Host means some other page's form/
        fetch is talking to this server, not our own UI. Non-browser clients (curl,
        tests) send no Origin at all and are allowed through."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlparse(origin).netloc == self.headers.get("Host", "")

    def do_POST(self):
        if not self._same_origin():
            self._send_json({"error": "Cross-origin requests are not allowed"}, status=403)
            return
        request_path = urlparse(self.path).path
        try:
            data = self._read_json_body()
            console_result = collection_routes.handle_post(
                COLLECTION_STORE, request_path, data, env_store=ENVIRONMENT_STORE
            )
            if console_result is None:
                console_result = folder_routes.handle_post(COLLECTION_STORE, request_path, data)
            if console_result is None:
                console_result = import_routes.handle_post(COLLECTION_STORE, request_path, data)
            if console_result is None:
                console_result = environment_routes.handle_post(ENVIRONMENT_STORE, request_path, data)
            if console_result is not None:
                status, body = console_result
                self._send_json(body, status=status)
                return
            if request_path == "/api/inspect-csv":
                self._send_json(runner_commands.inspect_csv_path(data.get("csvPath", "")))
                return
            if request_path == "/api/run-preview":
                self._send_json(self._run_preview(data))
                return
            if request_path == "/api/stop-run":
                self._send_json(runner_commands.stop_run(data))
                return
            if request_path == "/api/run-stream":
                self._stream_run_command(data)
                return
            self._send_json({"error": "Not found"}, status=404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def do_PUT(self):
        if not self._same_origin():
            self._send_json({"error": "Cross-origin requests are not allowed"}, status=403)
            return
        request_path = urlparse(self.path).path
        try:
            data = self._read_json_body()
            console_result = collection_routes.handle_put(COLLECTION_STORE, request_path, data)
            if console_result is None:
                console_result = folder_routes.handle_put(COLLECTION_STORE, request_path, data)
            if console_result is None:
                console_result = environment_routes.handle_put(ENVIRONMENT_STORE, request_path, data)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        if console_result is not None:
            status, body = console_result
            self._send_json(body, status=status)
            return
        self._send_json({"error": "Not found"}, status=404)

    def do_DELETE(self):
        if not self._same_origin():
            self._send_json({"error": "Cross-origin requests are not allowed"}, status=403)
            return
        request_path = urlparse(self.path).path
        if request_path == "/api/runs":
            run_history_store.clear_all(RUNS_DIR)
            self._send_json({"cleared": True})
            return
        try:
            console_result = collection_routes.handle_delete(COLLECTION_STORE, request_path)
            if console_result is None:
                console_result = folder_routes.handle_delete(COLLECTION_STORE, request_path)
            if console_result is None:
                console_result = environment_routes.handle_delete(ENVIRONMENT_STORE, request_path)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        if console_result is not None:
            status, body = console_result
            self._send_json(body, status=status)
            return
        self._send_json({"error": "Not found"}, status=404)

    def log_message(self, fmt, *args):
        return

    def _read_json_body(self):
        raw = self._read_raw_body().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _read_raw_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length > 0 else b""

    def _send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_run_export(self, run_id):
        try:
            doc = run_history_store.get_run(RUNS_DIR, run_id)
        except run_history_store.InvalidRunId as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except run_history_store.RunNotFound as exc:
            self._send_json({"error": str(exc)}, status=404)
            return
        payload = run_history_store.events_to_csv(doc).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="run-{run_id}.csv"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path, content_type):
        with open(path, "rb") as handle:
            payload = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # No cache headers here meant WKWebView's own persistent disk cache
        # (kept across separate app launches, unlike a typical dev server
        # story) could keep serving a stale index.html/JS/CSS after a
        # kill+relaunch during active development — the server had the fix,
        # curl proved it, but the window itself could still be running old
        # code. This tool is edited and relaunched constantly; never let a
        # cached asset silently outlive the process that served it.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _auth_spec_from_flat(self, data):
        """The Runner payload's auth fields are flat (authMode/tokenUrl/...)
        — request-tabs.js's authPayloadFields() produces that shape and §3
        puts request-tabs.js off limits, so the wire format stays flat
        (design §8.3). run_orchestrator.execute() wants the nested shape
        _apply_auth already expects, so the translation happens here, once,
        at the HTTP boundary."""
        return {
            "mode": data.get("authMode") or "none",
            "tokenUrl": data.get("tokenUrl") or "",
            "tenant": data.get("tenant") or "",
            "user": data.get("user") or "",
            "refreshToken": data.get("refreshToken") or "",
            "bearerToken": data.get("bearerToken") or "",
            "basicUser": data.get("basicUser") or "",
            "basicPassword": data.get("basicPassword") or "",
            "apiKeyName": data.get("apiKeyName") or "",
            "apiKeyValue": data.get("apiKeyValue") or "",
            "apiKeyLocation": data.get("apiKeyLocation") or "header",
            "refreshTokenEachRow": bool(data.get("refreshTokenEachRow")),
            "refreshTokenCookieName": data.get("refreshTokenCookieName") or "",
            "oauth2ClientId": data.get("oauth2ClientId") or "",
            "oauth2ClientSecret": data.get("oauth2ClientSecret") or "",
            "oauth2TokenUrl": data.get("oauth2TokenUrl") or "",
            "oauth2Scope": data.get("oauth2Scope") or "",
            "oauth2AuthStyle": data.get("oauth2AuthStyle") or "",
        }

    def _validated_scope_and_csv(self, data):
        """Shared by run-stream and run-preview. Raises ValueError — caller
        maps to 404 (bad scope) or 400 (bad CSV/iterations) per design §8.5."""
        requests_seq = run_orchestrator.expand_scope(COLLECTION_STORE, data.get("scope") or {})
        raw_csv_path = runner_commands.clean(data.get("csvPath")) or None
        csv_path = None
        if raw_csv_path:
            csv_info = runner_commands.inspect_csv_path(raw_csv_path)
            if csv_info["rowCount"] == 0:
                raise ValueError("CSV has no data rows")
            csv_path = csv_info["csvPath"]
            scope_slug = (data.get("scope") or {}).get("slug")
            env_slug = data.get("environmentSlug")
            for req in requests_seq:
                # Validate against the CSV header only after collection/env vars
                # are already resolved — {{url}} (an environment var) is never a
                # CSV column, and checking the raw stored template flagged it as
                # a missing placeholder even though it resolves fine at run time.
                resolve_data = {"slug": scope_slug, "requestName": req["name"], "environmentSlug": env_slug}
                partially_resolved, _ = collection_routes._resolve_send_one_request(
                    COLLECTION_STORE, resolve_data, ENVIRONMENT_STORE, None
                )
                if partially_resolved.get("bodyMode") == "urlencoded":
                    # A urlencoded body param can carry a {{col}} placeholder
                    # exactly like the URL or a raw body can — scan param
                    # values here so a typo'd column name there fails up
                    # front too, instead of silently sending a literal
                    # {{col}} in every row. The raw `body` field is retained
                    # (not cleared) when switched to this mode in case the
                    # user switches back, but it is never actually sent —
                    # scanning it here would fail a run over stale content
                    # that will never go over the wire.
                    body_text = " ".join(
                        p.get("value", "") for p in partially_resolved.get("bodyParams") or []
                    )
                else:
                    body_text = partially_resolved.get("body", "")
                runner_commands._validate_double_brace_placeholders(
                    csv_path, partially_resolved["url"], body_text
                )
        iterations = data.get("iterations")
        if iterations is not None and (not isinstance(iterations, int) or iterations <= 0):
            raise ValueError("iterations must be a positive integer")
        if int(data.get("workers") or 1) > 1 and not data.get("resetCapturesEachIteration", True):
            raise ValueError(
                "workers > 1 requires resetCapturesEachIteration — parallel iterations "
                "would otherwise share one mutable capture dict and race"
            )
        return requests_seq, csv_path

    def _run_preview(self, data):
        requests_seq, csv_path = self._validated_scope_and_csv(data)
        csv_rows = runner_commands._read_csv(csv_path)[1] if csv_path else None
        # Reuse the same iteration-count logic the real run uses, so Preview
        # can't disagree with what Run actually executes (e.g. iterations
        # requested with no CSV, or iterations capped below the CSV's row
        # count).
        iteration_inputs = run_orchestrator._build_iteration_inputs(data, csv_rows)
        total_iterations = len(iteration_inputs)
        limited_rows = iteration_inputs[:PREVIEW_ITERATION_LIMIT]

        captured_by = {}
        for req in requests_seq:
            for test in req.get("tests") or []:
                if isinstance(test, dict) and test.get("type") == "capture" and test.get("variable"):
                    captured_by.setdefault(test["variable"], req["name"])

        iterations_preview = []
        for csv_row in limited_rows:
            steps = []
            for req in requests_seq:
                extra_vars = run_orchestrator.resolve_extra_vars(csv_row, {})
                send_data = {
                    "slug": data.get("scope", {}).get("slug"),
                    "requestName": req["name"],
                    "environmentSlug": data.get("environmentSlug"),
                }
                request, variables = collection_routes._resolve_send_one_request(
                    COLLECTION_STORE, send_data, ENVIRONMENT_STORE, extra_vars
                )
                preview_body = runner_commands.preview_body_text(request)
                unresolved = {
                    var: f"resolved at run time (captured by {name})"
                    for var, name in captured_by.items()
                    if "{{" + var + "}}" in request["url"] or "{{" + var + "}}" in preview_body
                }
                steps.append({
                    "requestName": req["name"],
                    "method": request["method"],
                    "url": collection_routes._strip_disabled_query_params(request["url"]),
                    "headers": [
                        {"key": h["key"], "value": runner_commands._redact_header(h["key"], h["value"])}
                        for h in request["headers"]
                    ],
                    "body": preview_body,
                    "unresolvedVars": unresolved,
                })
            iterations_preview.append(steps)

        return {
            "iterations": iterations_preview,
            "totalIterations": total_iterations,
            "capped": total_iterations > PREVIEW_ITERATION_LIMIT,
        }

    @staticmethod
    def _terminal_summary(run_id, exit_code, status, counts, error=None):
        """A summary event for a run that ended abnormally (client
        disconnect, uncaught exception) — must carry the same keys a normal
        run_orchestrator summary does, since runner-history.js reads
        summary.ok/failed/flagged/errored unconditionally. `counts` comes
        from the recorder's incremental counters, not the (possibly
        truncated) stored event list."""
        event = {
            "type": "summary", "runId": run_id, "exitCode": exit_code, "status": status,
            "totalIterations": 0, "totalRequests": 0,
            "ok": counts["ok"], "failed": counts["failed"],
            "flagged": counts["flagged"], "errored": counts["errored"],
            "retryCsv": None, "retriedRequests": 0,
        }
        if error is not None:
            event["error"] = error
        return event

    def _stream_run_command(self, data):
        run_id = runner_commands.clean(data.get("runId")) or str(time.monotonic_ns())
        try:
            run_history_store.validate_run_id(run_id)
            _, csv_path = self._validated_scope_and_csv(data)
        except collection_store.CollectionNotFound as exc:
            self._send_json({"error": str(exc)}, status=404)
            return
        except ValueError as exc:
            status = 404 if "Scope resolved to zero requests" in str(exc) or "Unknown scope type" in str(exc) else 400
            self._send_json({"error": str(exc)}, status=status)
            return

        cancel_event = threading.Event()
        runner_commands.register_run(run_id, cancel_event)

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def write_event(event):
            try:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8", errors="replace"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                raise ClientDisconnected() from exc

        recorder = run_history_store.RunRecorder(RUNS_DIR, run_id, {
            "workers": int(data.get("workers") or 1),
            "scope": data.get("scope"),
            "environmentSlug": data.get("environmentSlug"),
            "csvFile": os.path.basename(csv_path) if csv_path else None,
            "outputFolder": data.get("outputFolder"),
        })
        run_spec = {**data, "auth": self._auth_spec_from_flat(data)}
        try:
            for event in run_orchestrator.execute(run_id, run_spec, COLLECTION_STORE, ENVIRONMENT_STORE, cancel_event):
                recorder.record(event)
                write_event(event)
                if event["type"] == "summary":
                    recorder.finish(event, event["status"])
        except ClientDisconnected:
            cancel_event.set()
            recorder.finish(self._terminal_summary(run_id, 130, "STOPPED", recorder.counts()), "STOPPED")
        except Exception as exc:
            # The 200 response + NDJSON headers are already flushed above, so
            # an exception here must not reach do_POST's outer handler — it
            # would try to send a second HTTP status line onto the same
            # connection and corrupt the response. Emit a terminal summary
            # instead, and make sure the run is never left stuck at RUNNING.
            cancel_event.set()
            error_event = self._terminal_summary(run_id, 1, "ERROR", recorder.counts(), error=str(exc))
            try:
                write_event(error_event)
            except ClientDisconnected:
                pass
            recorder.finish(error_event, "ERROR")
        finally:
            runner_commands.unregister_run(run_id, cancel_event)


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def server_bind(self):
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]


def _find_free_port(start):
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free port found")


def start_server():
    """Bind and return (server, port) without serving or opening a browser.
    The caller (CLI main() below, or desktop_app.py) decides how to run it."""
    run_history_store.mark_orphans_incomplete(RUNS_DIR)
    requested = int(os.environ.get("IRIS_PORT", "5090"))
    port = requested if os.environ.get("IRIS_STRICT_PORT") == "1" else _find_free_port(requested)
    server = LocalThreadingHTTPServer(("127.0.0.1", port), IrisRequestHandler)
    return server, port


def main():
    server, port = start_server()
    url = f"http://localhost:{port}/"
    print(f"Iris server running at {url}")
    if os.environ.get("IRIS_NO_BROWSER", "0") != "1":
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
