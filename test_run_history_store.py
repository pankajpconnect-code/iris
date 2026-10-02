"""Tests for run_history_store — PR4 of the Iris Runner redesign (design
§8.6, §10, §12.1.3). Flat-file persistence under runs/.
"""

import json
import os
import time

import pytest

import run_history_store


@pytest.fixture
def runs_dir(tmp_path):
    return str(tmp_path / "runs")


def _meta(**overrides):
    base = {
        "startedAt": "2026-08-24T12:00:00Z",
        "workers": 1,
        "scope": {"type": "collection", "slug": "c", "name": None},
        "environmentSlug": None,
        "csvFile": None,
        "outputFolder": None,
    }
    base.update(overrides)
    return base


def _read(runs_dir, run_id):
    with open(os.path.join(runs_dir, f"{run_id}.json")) as f:
        return json.load(f)


# --- runId validation ---


def test_validate_run_id_accepts_safe_id():
    assert run_history_store.validate_run_id("abc-123_XYZ.1") == "abc-123_XYZ.1"


@pytest.mark.parametrize("bad_id", ["../etc/passwd", "a/b", "", "a" * 65, None])
def test_validate_run_id_rejects_unsafe_ids(bad_id):
    with pytest.raises(run_history_store.InvalidRunId):
        run_history_store.validate_run_id(bad_id)


# --- RunRecorder: incremental checkpointing (§12.1.3) ---


def test_recorder_writes_running_status_immediately_on_start(runs_dir):
    run_history_store.RunRecorder(runs_dir, "run-1", _meta())
    doc = _read(runs_dir, "run-1")
    assert doc["status"] == "RUNNING"
    assert doc["events"] == []


def test_recorder_checkpoints_after_50_events_without_finish(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "run-2", _meta())
    for i in range(50):
        recorder.record({"type": "result", "iteration": i, "step": 1, "requestName": "A", "status": "OK"})
    doc = _read(runs_dir, "run-2")
    assert len(doc["events"]) == 50
    assert doc["status"] == "RUNNING"


def test_recorder_does_not_write_before_checkpoint_threshold(runs_dir, monkeypatch):
    monkeypatch.setattr(run_history_store, "CHECKPOINT_SECONDS", 9999)
    recorder = run_history_store.RunRecorder(runs_dir, "run-3", _meta())
    mtime_after_start = os.path.getmtime(os.path.join(runs_dir, "run-3.json"))
    for i in range(10):
        recorder.record({"type": "result", "iteration": i, "step": 1, "requestName": "A", "status": "OK"})
    assert os.path.getmtime(os.path.join(runs_dir, "run-3.json")) == mtime_after_start


def test_recorder_finish_writes_terminal_status_and_summary(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "run-4", _meta())
    recorder.record({"type": "result", "iteration": 1, "step": 1, "requestName": "A", "status": "OK"})
    summary = {"type": "summary", "exitCode": 0, "ok": 1, "failed": 0, "flagged": 0, "errored": 0}
    recorder.finish(summary, "COMPLETED")
    doc = _read(runs_dir, "run-4")
    assert doc["status"] == "COMPLETED"
    assert doc["summary"] == summary
    assert doc["finishedAt"] is not None
    assert isinstance(doc["durationMs"], int)


def test_recorder_truncates_beyond_2000_result_events_keeping_head_and_tail(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "run-5", _meta())
    for i in range(2500):
        recorder.record({"type": "result", "iteration": i, "step": 1, "requestName": "A", "status": "OK", "seq": i})
    recorder.finish({"type": "summary", "exitCode": 0}, "COMPLETED")
    doc = _read(runs_dir, "run-5")
    assert doc["eventsTruncated"] is True
    assert len(doc["events"]) == 2000
    assert doc["events"][0]["seq"] == 0
    assert doc["events"][-1]["seq"] == 2499


# --- RunRecorder: incremental result counters (independent of truncation) ---


def test_recorder_counts_tracks_result_statuses(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "run-counts-1", _meta())
    for status in ["OK", "OK", "FAIL", "FLAGGED", "ERROR"]:
        recorder.record({"type": "result", "iteration": 1, "step": 1, "requestName": "A", "status": status})
    assert recorder.counts() == {"ok": 2, "failed": 1, "flagged": 1, "errored": 1}


def test_recorder_counts_remain_correct_after_truncation(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "run-counts-2", _meta())
    for i in range(2500):
        recorder.record({"type": "result", "iteration": i, "step": 1, "requestName": "A", "status": "OK"})
    assert recorder.counts() == {"ok": 2500, "failed": 0, "flagged": 0, "errored": 0}


# --- list_runs / get_run ---


def test_list_runs_returns_newest_first(runs_dir):
    run_history_store.RunRecorder(runs_dir, "older", _meta(startedAt="2026-08-24T10:00:00Z"))
    time.sleep(0.01)
    run_history_store.RunRecorder(runs_dir, "newer", _meta(startedAt="2026-08-24T11:00:00Z"))
    runs = run_history_store.list_runs(runs_dir)
    assert [r["runId"] for r in runs] == ["newer", "older"]


def test_get_run_returns_full_stored_document(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "run-6", _meta())
    recorder.record({"type": "result", "iteration": 1, "step": 1, "requestName": "A", "status": "OK"})
    recorder.finish({"type": "summary", "exitCode": 0}, "COMPLETED")
    doc = run_history_store.get_run(runs_dir, "run-6")
    assert doc["runId"] == "run-6"
    assert len(doc["events"]) == 1


def test_get_run_raises_on_unknown_id(runs_dir):
    os.makedirs(runs_dir)
    with pytest.raises(run_history_store.RunNotFound):
        run_history_store.get_run(runs_dir, "nonexistent")


# --- retention & orphan detection ---


def test_prune_keeps_only_newest_50_runs(runs_dir):
    for i in range(55):
        run_history_store.RunRecorder(runs_dir, f"run-{i:03d}", _meta())
    run_history_store.prune(runs_dir, keep=50)
    remaining = [f for f in os.listdir(runs_dir) if f.endswith(".json")]
    assert len(remaining) == 50


def test_mark_orphans_incomplete_flips_running_status(runs_dir):
    run_history_store.RunRecorder(runs_dir, "crashed", _meta())
    run_history_store.mark_orphans_incomplete(runs_dir)
    doc = _read(runs_dir, "crashed")
    assert doc["status"] == "INCOMPLETE"


def test_mark_orphans_incomplete_leaves_completed_runs_alone(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "done", _meta())
    recorder.finish({"type": "summary", "exitCode": 0}, "COMPLETED")
    run_history_store.mark_orphans_incomplete(runs_dir)
    doc = _read(runs_dir, "done")
    assert doc["status"] == "COMPLETED"


def test_clear_all_removes_every_run(runs_dir):
    for i in range(3):
        run_history_store.RunRecorder(runs_dir, f"run-{i}", _meta())
    run_history_store.clear_all(runs_dir)
    assert run_history_store.list_runs(runs_dir) == []


def test_clear_all_on_missing_directory_is_a_noop(tmp_path):
    run_history_store.clear_all(str(tmp_path / "does-not-exist"))


# --- CSV export ---


def test_events_to_csv_includes_header_and_result_rows(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "run-csv", _meta())
    recorder.record({
        "type": "result", "iteration": 1, "step": 1, "requestName": "A",
        "url": "http://example.invalid/loans/9", "status": "OK", "httpStatus": 200,
        "elapsedMs": 234, "testsPassed": 1, "testsTotal": 1,
        "capturedVars": {"loanId": "9"}, "responseSnippet": "{}", "error": None,
    })
    recorder.finish({"type": "summary", "exitCode": 0}, "COMPLETED")
    doc = run_history_store.get_run(runs_dir, "run-csv")
    csv_text = run_history_store.events_to_csv(doc)
    lines = csv_text.strip().splitlines()
    assert lines[0].split(",")[:6] == ["iteration", "step", "requestName", "url", "status", "httpStatus"]
    assert "elapsedMs" in lines[0].split(",")
    assert "http://example.invalid/loans/9" in lines[1]
    assert "loanId=9" in lines[1]
    assert "234" in lines[1].split(",")


def test_events_to_csv_handles_no_events(runs_dir):
    recorder = run_history_store.RunRecorder(runs_dir, "run-empty", _meta())
    recorder.finish({"type": "summary", "exitCode": 0}, "COMPLETED")
    doc = run_history_store.get_run(runs_dir, "run-empty")
    csv_text = run_history_store.events_to_csv(doc)
    assert len(csv_text.strip().splitlines()) == 1
