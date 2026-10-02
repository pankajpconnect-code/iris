"""CSV row expansion and retry/capture persistence for a Runner execution
(split out of run_orchestrator.py, which was over this repo's 500-line
limit). Shared verbatim by the sequential loop in run_orchestrator.execute()
and run_parallel.execute_parallel — both import these by name (as
run_orchestrator._read_csv_input etc., re-exported there), so per-request
CSV/retry/capture behavior stays identical either way (design §8.8).
"""

import csv as csv_module
import os

import runner_commands


def _build_iteration_inputs(spec, csv_rows):
    requested_iterations = spec.get("iterations")
    if csv_rows is not None:
        if requested_iterations:
            n = min(int(requested_iterations), len(csv_rows))
            return csv_rows[:n]
        return csv_rows
    return [None] * (int(requested_iterations) if requested_iterations else 1)


def _read_csv_input(spec):
    csv_path = spec.get("csvPath")
    if not csv_path:
        return None, [], None
    resolved_csv = runner_commands._resolve_path(csv_path)
    if not os.path.isfile(resolved_csv):
        raise ValueError("CSV file was not found")
    csv_fieldnames, csv_rows = runner_commands._read_csv(resolved_csv)
    if not csv_rows:
        raise ValueError("CSV has no data rows")
    return csv_rows, csv_fieldnames, csv_path


def _persist_captures(captured, csv_path, persist_captures, slug, env_slug, store, env_store):
    """Returns an error message string on failure, None on success/no-op —
    callers must surface this rather than let a persistence failure look
    identical to a successful save."""
    if not captured:
        return None
    should_persist = csv_path is None or persist_captures
    if not should_persist:
        return None
    try:
        if env_slug and env_store is not None:
            env_store.set_vars(env_slug, captured)
        elif slug:
            store.set_vars(slug, captured)
    except Exception as exc:
        return str(exc)
    return None


def _write_retry_csv(rows, csv_path, csv_fieldnames, output_folder):
    if not rows or not csv_path:
        return None
    retry_csv_path = runner_commands._retry_csv_path(csv_path, output_folder)
    with open(retry_csv_path, "w", newline="") as handle:
        writer = csv_module.DictWriter(handle, fieldnames=list(csv_fieldnames) + ["__failedAtStep"])
        writer.writeheader()
        writer.writerows(rows)
    return retry_csv_path
