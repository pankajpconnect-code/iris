"""Tests for desktop_app's quit-guard logic: it must name the in-flight run
and its current iteration, using only data already checkpointed to disk by
run_history_store (runs survive a hard quit up to the last checkpoint) and
the in-memory ACTIVE_RUNS registry runner_commands already maintains for
the Stop button. No real pywebview window or dialog is driven here — that
final native-dialog interaction (clicking "Quit Anyway") cannot be
automated headlessly and is called out in the verification report.
"""
import threading

import desktop_app
import run_history_store
import runner_commands


def test_active_run_summary_none_when_nothing_running():
    assert desktop_app._active_run_summary() is None


def test_active_run_summary_names_run_and_iteration(tmp_path, monkeypatch):
    import server as server_module

    monkeypatch.setattr(server_module, "RUNS_DIR", str(tmp_path))

    run_id = "quit-guard-test-run"
    cancel_event = threading.Event()
    runner_commands.register_run(run_id, cancel_event)
    try:
        recorder = run_history_store.RunRecorder(str(tmp_path), run_id, {})
        recorder.record({"type": "result", "iteration": 2, "iterationTotal": 5})
        recorder._write()  # force the checkpoint get_run() reads, rather than waiting for the interval

        summary = desktop_app._active_run_summary()
        assert summary is not None
        assert run_id in summary
        assert "iteration 2 of 5" in summary
    finally:
        runner_commands.unregister_run(run_id, cancel_event)


def test_active_run_summary_falls_back_to_run_id_with_no_iteration_yet(tmp_path, monkeypatch):
    import server as server_module

    monkeypatch.setattr(server_module, "RUNS_DIR", str(tmp_path))

    run_id = "quit-guard-test-run-no-events"
    cancel_event = threading.Event()
    runner_commands.register_run(run_id, cancel_event)
    try:
        run_history_store.RunRecorder(str(tmp_path), run_id, {})
        summary = desktop_app._active_run_summary()
        assert summary == f"run {run_id}"
    finally:
        runner_commands.unregister_run(run_id, cancel_event)
