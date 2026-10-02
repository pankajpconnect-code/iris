"""Flat-file persistence for Runner history under runs/ (design
§8.6 history file shape, §10 secrets/redaction, §12.1.3 incremental
checkpointing and orphan detection).

Redaction of capturedVars/responseSnippet happens upstream in
run_orchestrator.execute() before an event ever reaches this module — a
result event is persisted exactly as streamed, so "redacted on the wire"
and "redacted on disk" are the same guarantee, not two.
"""

import csv
import io
import json
import os
import re
import time
from datetime import datetime, timezone

import collection_store

CSV_COLUMNS = [
    "iteration", "step", "requestName", "url", "status", "httpStatus", "elapsedMs",
    "testsPassed", "testsTotal", "capturedVars", "responseSnippet", "error",
]

RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_RESULT_EVENTS = 2000
KEEP_HEAD = 1000
KEEP_TAIL = 1000
RETENTION_COUNT = 50
CHECKPOINT_EVENT_INTERVAL = 50
CHECKPOINT_SECONDS = 30

_COUNT_KEYS = {"OK": "ok", "FAIL": "failed", "FLAGGED": "flagged", "ERROR": "errored"}


class InvalidRunId(ValueError):
    pass


class RunNotFound(ValueError):
    pass


def validate_run_id(run_id):
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise InvalidRunId(f"Invalid run id: {run_id!r}")
    return run_id


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_path(runs_dir, run_id):
    return os.path.join(runs_dir, f"{run_id}.json")


class RunRecorder:
    """One instance per in-flight run. record() is called per event and
    checkpoints every 50 events or 30 seconds, whichever comes first — a
    3000-row run must not lose every result to a crash between writes."""

    def __init__(self, runs_dir, run_id, meta):
        validate_run_id(run_id)
        os.makedirs(runs_dir, exist_ok=True)
        self.runs_dir = runs_dir
        self.run_id = run_id
        self._path = _run_path(runs_dir, run_id)
        self._started_monotonic = time.monotonic()
        self._events = []
        self._truncated = False
        self._counts = {"ok": 0, "failed": 0, "flagged": 0, "errored": 0}
        self._pending_since_write = 0
        self._last_write = time.monotonic()
        self._doc = {
            "runId": run_id,
            "startedAt": meta.get("startedAt") or _now_iso(),
            "finishedAt": None,
            "durationMs": None,
            "status": "RUNNING",
            "workers": meta.get("workers", 1),
            "scope": meta.get("scope"),
            "environmentSlug": meta.get("environmentSlug"),
            "csvFile": meta.get("csvFile"),
            "outputFolder": meta.get("outputFolder"),
            "events": [],
            "eventsTruncated": False,
            "summary": None,
        }
        self._write()

    def record(self, event):
        if event.get("type") == "result":
            self._events.append(event)
            if len(self._events) > MAX_RESULT_EVENTS:
                self._events = self._events[:KEEP_HEAD] + self._events[-KEEP_TAIL:]
                self._truncated = True
            count_key = _COUNT_KEYS.get(event.get("status"))
            if count_key:
                self._counts[count_key] += 1
        self._pending_since_write += 1
        now = time.monotonic()
        if self._pending_since_write >= CHECKPOINT_EVENT_INTERVAL or (now - self._last_write) >= CHECKPOINT_SECONDS:
            self._write()

    def counts(self):
        return dict(self._counts)

    def finish(self, summary_event, status):
        self._doc["summary"] = summary_event
        self._doc["status"] = status
        self._doc["finishedAt"] = _now_iso()
        self._doc["durationMs"] = int((time.monotonic() - self._started_monotonic) * 1000)
        self._write()
        prune(self.runs_dir)

    def _write(self):
        self._doc["events"] = self._events
        self._doc["eventsTruncated"] = self._truncated
        collection_store._atomic_write_json(self._path, self._doc)
        self._pending_since_write = 0
        self._last_write = time.monotonic()


def list_runs(runs_dir):
    if not os.path.isdir(runs_dir):
        return []
    docs = []
    for name in os.listdir(runs_dir):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(runs_dir, name), encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        docs.append({
            "runId": doc.get("runId"),
            "startedAt": doc.get("startedAt"),
            "scope": doc.get("scope"),
            "csvFile": doc.get("csvFile"),
            "summary": doc.get("summary"),
            "status": doc.get("status"),
        })
    docs.sort(key=lambda d: d.get("startedAt") or "", reverse=True)
    return docs


def get_run(runs_dir, run_id):
    validate_run_id(run_id)
    path = _run_path(runs_dir, run_id)
    if not os.path.isfile(path):
        raise RunNotFound(f"Unknown run '{run_id}'")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def prune(runs_dir, keep=RETENTION_COUNT):
    if not os.path.isdir(runs_dir):
        return
    files = [f for f in os.listdir(runs_dir) if f.endswith(".json")]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(runs_dir, f)), reverse=True)
    for stale in files[keep:]:
        try:
            os.remove(os.path.join(runs_dir, stale))
        except OSError:
            pass


def clear_all(runs_dir):
    prune(runs_dir, keep=0)


def _pretty_response(snippet):
    """Renders a JSON response body multi-line/indented, same as the Console's
    Send tab already does for a live response — a CSV cell holds embedded
    newlines fine (the csv module quotes it), so exported responses don't
    have to stay a single compact line. Non-JSON bodies pass through as-is."""
    if not snippet:
        return snippet
    try:
        return json.dumps(json.loads(snippet), indent=2)
    except (TypeError, ValueError):
        return snippet


def events_to_csv(doc):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for event in doc.get("events") or []:
        captured = event.get("capturedVars") or {}
        writer.writerow([
            event.get("iteration"), event.get("step"), event.get("requestName"),
            event.get("url"), event.get("status"), event.get("httpStatus"), event.get("elapsedMs"),
            event.get("testsPassed"), event.get("testsTotal"),
            "; ".join(f"{k}={v}" for k, v in captured.items()),
            _pretty_response(event.get("responseSnippet")), event.get("error"),
        ])
    return buffer.getvalue()


def mark_orphans_incomplete(runs_dir):
    """A run file still RUNNING when the server starts is orphaned — the
    process died mid-run. Called once at server startup."""
    if not os.path.isdir(runs_dir):
        return
    for name in os.listdir(runs_dir):
        if not name.endswith(".json"):
            continue
        path = os.path.join(runs_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if doc.get("status") == "RUNNING":
            doc["status"] = "INCOMPLETE"
            collection_store._atomic_write_json(path, doc)
