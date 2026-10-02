"""CSV file inspection and shared Runner helpers — path resolution, retry-CSV
naming, placeholder validation, header redaction, and the active-run
cancellation registry.

The subprocess CLI-invocation path (build_runner_args/run_command/
preview_command and friends) is gone: run_orchestrator.py drives the request
sequence in-process now, reusing collection_routes._send_one directly rather
than shelling out to run_api_from_csv.py. See docs/superpowers/specs (local)
§7 "Existing files changed" for the full list of what was removed here and
why each kept function still earns its place.
"""

import csv
import io
import os
import threading
import time

import run_api_from_csv

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_TIMEOUT_SECONDS = "30"
DEFAULT_DELAY_SECONDS = "0"
ACTIVE_RUNS = {}  # run_id -> threading.Event, guarded by ACTIVE_RUNS_LOCK
ACTIVE_RUNS_LOCK = threading.Lock()


def inspect_csv_path(raw_path):
    path = _resolve_path(raw_path)
    if not os.path.isfile(path):
        raise ValueError("CSV file was not found")
    fieldnames, rows = _read_csv(path)
    return {
        "csvPath": path,
        "fieldnames": fieldnames,
        "rowCount": len(rows),
        "sampleRows": rows[:5],
        "retryCsv": _retry_csv_path(path),
    }


def process_timeout_for(row_count, timeout=None, delay=None):
    """The stall/abort deadline for a run — must reflect its ACTUAL
    configured per-request timeout/delay, not the module defaults, or a
    legitimately slow (but healthy) run gets killed as "stalled" long
    before its own configured timeout would ever trip."""
    per_request_timeout = _float_or_default(timeout, _float_or_default(DEFAULT_TIMEOUT_SECONDS, 30.0))
    delay = _float_or_default(delay, _float_or_default(DEFAULT_DELAY_SECONDS, 0.0))
    return max(60.0, row_count * (per_request_timeout + delay + 3.0) + 30.0)


def _validate_double_brace_placeholders(csv_path, url, body):
    """Deliberately strict: a typo'd column name fails up front instead of
    silently sending a literal `{{col}}` in 100 rows of malformed requests."""
    csv_info = inspect_csv_path(csv_path)
    placeholders = set(run_api_from_csv.DOUBLE_BRACE_RE.findall(url)) | set(
        run_api_from_csv.DOUBLE_BRACE_RE.findall(body or "")
    )
    missing = sorted(placeholders - set(csv_info["fieldnames"]))
    if missing:
        available = ", ".join(csv_info["fieldnames"]) if csv_info["fieldnames"] else "(none)"
        raise ValueError(
            "Row placeholder(s) not found in CSV header: "
            + ", ".join(missing)
            + ". Available CSV columns: "
            + available
        )


def register_run(run_id, cancel_event):
    with ACTIVE_RUNS_LOCK:
        ACTIVE_RUNS[run_id] = cancel_event


def unregister_run(run_id, cancel_event=None):
    """Only removes the entry if it still belongs to this run's cancel_event.
    Without this identity check, two runs sharing a run_id (client retry,
    duplicate tab) would let the first to finish delete the second — still
    active — run's entry, silently breaking its Stop button."""
    with ACTIVE_RUNS_LOCK:
        if cancel_event is None or ACTIVE_RUNS.get(run_id) is cancel_event:
            ACTIVE_RUNS.pop(run_id, None)


def stop_run(data):
    run_id = clean(data.get("runId"))
    if not run_id:
        raise ValueError("Run id is required")
    with ACTIVE_RUNS_LOCK:
        cancel_event = ACTIVE_RUNS.get(run_id)
    if cancel_event is None:
        return {"stopped": False, "message": "No active run found"}
    cancel_event.set()
    return {"stopped": True, "message": "Stop requested"}


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        sample = handle.read()
    reader = csv.DictReader(io.StringIO(sample))
    fieldnames = [name.strip() for name in (reader.fieldnames or [])]
    reader.fieldnames = fieldnames
    return fieldnames, list(reader)


def _retry_csv_path(csv_path, output_folder=""):
    folder = clean(output_folder)
    if folder:
        path = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(path):
            raise ValueError("Output folder was not found")
        return _unique_retry_csv_path(os.path.join(path, "failed_rows.csv"))
    return _unique_retry_csv_path(os.path.join(os.path.dirname(_resolve_path(csv_path)), "failed_rows.csv"))


def _unique_retry_csv_path(base_path):
    if not os.path.exists(base_path):
        return base_path
    stem, ext = os.path.splitext(base_path)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    candidate = f"{stem}_{timestamp}{ext}"
    suffix = 2
    while os.path.exists(candidate):
        candidate = f"{stem}_{timestamp}_{suffix}{ext}"
        suffix += 1
    return candidate


def _resolve_path(path):
    if not path:
        raise ValueError("CSV path is required")
    expanded = os.path.abspath(os.path.expanduser(path))
    if os.path.exists(expanded):
        return expanded
    return os.path.abspath(os.path.join(PROJECT_ROOT, path))


def _clean(value):
    return str(value or "").strip()


clean = _clean


def _float_or_default(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def preview_body_text(request):
    """Human-readable preview of what a request will send — NOT the literal
    wire bytes collection_routes._outgoing_body_and_content_type produces
    for urlencoded mode (urlencode() percent-encodes any still-unresolved
    {{var}} braces, hiding exactly the token the Runner Preview panel needs
    to highlight)."""
    if request.get("bodyMode") == "urlencoded":
        return "\n".join(
            f"{p.get('key', '')}={p.get('value', '')}"
            for p in request.get("bodyParams") or []
            if p.get("enabled", True) and p.get("key")
        )
    return request.get("body") or ""


def _redact_header(key, value):
    lowered = key.lower()
    if "authorization" in lowered or "cookie" in lowered or "token" in lowered:
        return "<redacted>"
    return value
