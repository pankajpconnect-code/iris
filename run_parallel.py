"""Parallel iteration execution — PR6, opt-in via `workers > 1` (design §8.8).

Iterations run concurrently; requests *within* an iteration never do — request
2 consumes request 1's captured value, so parallelising those would break
chaining outright. Workers never touch the socket: they push events onto a
queue.Queue(), and only the connection thread (this generator) drains and
yields, since http.server's wfile is not thread-safe.

Reuses run_orchestrator._run_iteration/_send_step/_classify verbatim — a
parallel run behaves identically to a sequential one per-request, just with
independent iterations in flight at once.
"""

import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import run_auth
import run_orchestrator as orch
import runner_commands

DEFAULT_WORKERS = 4
MAX_WORKERS = 8


class _OrEvent:
    """A read-only view over multiple threading.Events — is_set() is True if
    any of them is. Lets _run_iteration's single cancel_event check double as
    "stop everything" once one iteration discovers an abort condition,
    without conflating that with the user's own Stop button."""

    def __init__(self, *events):
        self._events = events

    def is_set(self):
        return any(e.is_set() for e in self._events)

    def set(self):
        # Only ever called via the real cancel_event reference held
        # elsewhere; present so _interruptible_sleep's interface is uniform.
        raise NotImplementedError("set() the underlying event directly")


def execute_parallel(run_id, spec, store, env_store, cancel_event):
    requests_seq = orch.expand_scope(store, spec["scope"])
    csv_rows, csv_fieldnames, csv_path = orch._read_csv_input(spec)
    iteration_inputs = orch._build_iteration_inputs(spec, csv_rows)

    reset_each_iteration = spec.get("resetCapturesEachIteration", True)
    if not reset_each_iteration:
        raise ValueError(
            "workers > 1 requires resetCapturesEachIteration — parallel iterations "
            "would otherwise share one mutable capture dict and race"
        )
    workers = max(1, min(int(spec.get("workers") or DEFAULT_WORKERS), MAX_WORKERS))

    auth_cfg = spec.get("auth") or {}
    max_refreshes = int(spec.get("maxTokenRefreshes") or run_auth.DEFAULT_MAX_REFRESHES)
    configured_max_consecutive_mint_failures = spec.get("maxConsecutiveMintFailures")
    max_consecutive_mint_failures = int(
        configured_max_consecutive_mint_failures if configured_max_consecutive_mint_failures is not None
        else run_auth.DEFAULT_MAX_CONSECUTIVE_MINT_FAILURES
    )
    breaker_enabled = bool(spec.get("authBreakerEnabled", True))
    token_cache = run_auth.TokenCache(
        auth_cfg, max_refreshes=max_refreshes,
        max_consecutive_mint_failures=max_consecutive_mint_failures, breaker_enabled=breaker_enabled,
    )
    refresh_each_row = bool(auth_cfg.get("refreshTokenEachRow")) and auth_cfg.get("mode") == "refresh-cookie"

    total_iterations = len(iteration_inputs)
    total_requests = total_iterations * len(requests_seq)
    # §8.8: divide the sequential deadline by workers, keeping the floor —
    # a hung parallel run must not sit for hours before tripping.
    deadline = time.monotonic() + max(
        60.0,
        runner_commands.process_timeout_for(total_requests, timeout=spec.get("timeout"), delay=spec.get("delay"))
        / workers,
    )

    counters = orch.Counters()
    internal_abort = threading.Event()
    combined_stop = _OrEvent(cancel_event, internal_abort)
    ctx = orch.Context(spec, store, env_store, requests_seq, token_cache, combined_stop, deadline, counters)

    if csv_rows is not None and spec.get("iterations") and int(spec["iterations"]) > len(csv_rows):
        yield {
            "type": "log",
            "message": f"requested {spec['iterations']} iterations, CSV has {len(csv_rows)} rows — running {len(csv_rows)}",
        }
    yield {
        "type": "run_started",
        "runId": run_id,
        "totalIterations": total_iterations,
        "requests": [r["name"] for r in requests_seq],
        "csvFile": os.path.basename(csv_path) if csv_path else None,
    }

    event_queue = queue.Queue()
    retry_rows = orch.RetryRows()

    def worker(iteration_index, csv_row):
        if combined_stop.is_set():
            return
        if refresh_each_row:
            try:
                token_cache.force_refresh()
            except run_auth.TokenMintFailed as exc:
                event_queue.put(("event", {"type": "log", "message": f"Token refresh failed: {exc}"}))
                internal_abort.set()
                return
            except (run_auth.TokenCircuitOpen, run_auth.TokenRefreshExhausted):
                # No request in this row was ever attempted, but the row
                # still needs to land in the retry CSV rather than vanish.
                if csv_row is not None:
                    retry_rows.add(iteration_index, csv_row, "(token refresh)")
                raise
        captured = {}
        for kind, payload in orch._run_iteration(ctx, iteration_index, total_iterations, csv_row, captured):
            if kind in ("event", "attempt"):
                event_queue.put(("event", payload))
            else:
                failed_step, control = payload
                if csv_row is not None and failed_step is not None:
                    retry_rows.add(iteration_index, csv_row, failed_step)
                if control == "ABORTED":
                    internal_abort.set()

    executor = ThreadPoolExecutor(max_workers=workers)
    future_iteration = {}
    futures = []
    for i, row in enumerate(iteration_inputs, start=1):
        future = executor.submit(worker, i, row)
        future_iteration[future] = i
        futures.append(future)
    for future in futures:
        future.add_done_callback(lambda f: event_queue.put(("iteration_done", f)))

    remaining = len(futures)
    worker_exceptions = []
    try:
        while remaining > 0:
            kind, payload = event_queue.get()
            if kind == "event":
                yield payload
                continue
            remaining -= 1
            exc = payload.exception()
            if exc is not None:
                worker_exceptions.append((future_iteration[payload], exc))
                internal_abort.set()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    # A crashed worker's iteration was never classified by anything above,
    # so its outcome would otherwise vanish from the counts entirely — and
    # re-raising here (the old behavior) discarded every OTHER worker's real
    # results too, since the caller's outer except only ever sees a crash,
    # not a partial summary. internal_abort is already set above, so the
    # status/exit_code logic below already reflects "not a clean run".
    #
    # TokenCircuitOpen/TokenRefreshExhausted are not "unexpected" crashes —
    # they're the same halt conditions the sequential path converts to
    # _RunAborted — so they get haltReason/haltDetail instead of the generic
    # crash log, and don't inflate the ERROR count for a row that was never
    # actually attempted.
    halt_reason, halt_detail = None, None
    for iteration_index, exc in worker_exceptions:
        if isinstance(exc, (run_auth.TokenCircuitOpen, run_auth.TokenRefreshExhausted)):
            if halt_reason is None:
                halt_reason, halt_detail = orch._halt_reason_and_detail(exc, iteration_index)
            continue
        counters.add("ERROR")
        yield {"type": "log", "message": f"A worker thread failed unexpectedly: {exc}"}

    counts = counters.snapshot()
    if cancel_event.is_set():
        exit_code, status = 130, "STOPPED"
    elif halt_reason:
        exit_code, status = 1, "STOPPED"
    elif internal_abort.is_set():
        exit_code, status = 1, "COMPLETED"
    elif time.monotonic() > deadline:
        exit_code, status = 124, "TIMEOUT"
    elif counts["FAIL"] or counts["FLAGGED"] or counts["ERROR"]:
        exit_code, status = 1, "COMPLETED"
    else:
        exit_code, status = 0, "COMPLETED"

    # Parallel iterations are independently captured (resetCapturesEachIteration
    # is mandatory here) — there is no single coherent end-of-run capture dict
    # to persist, unlike the sequential path (§9 point 3 assumes one). Parallel
    # runs are already documented as non-reproducible; skipping persistence
    # here is a deliberate, honest simplification, not an oversight.
    retry_csv_path = orch._write_retry_csv(retry_rows.sorted_rows(), csv_path, csv_fieldnames, spec.get("outputFolder"))

    yield {
        "type": "summary",
        "runId": run_id,
        "exitCode": exit_code,
        "status": status,
        "totalIterations": total_iterations,
        "totalRequests": total_requests,
        "ok": counts["OK"],
        "failed": counts["FAIL"],
        "flagged": counts["FLAGGED"],
        "errored": counts["ERROR"],
        "retryCsv": retry_csv_path,
        "retriedRequests": counters.retried_requests,
        "haltReason": halt_reason,
        "haltDetail": halt_detail,
    }
