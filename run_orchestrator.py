"""In-process Runner orchestration: scope expansion, variable precedence, and
the execute() loop (design §5, §8, §9, §12.1.2, §8.8).

resolve_request from the original draft is replaced by E1 (extra_vars on the
existing resolver) — a second resolver would recreate the duplication §3 rules
out. TokenCache lives in run_auth.py, the parallel (PR6) path lives in
run_parallel.py — both to keep this file under the 300-line soft target
(design §7 "New backend files"). _run_iteration/_run_request/_send_step are
shared verbatim by the sequential loop here and run_parallel.execute_parallel
so per-request behavior (retry, classification, capture) is identical either
way — see design §8.8 "What may and may not run in parallel".
"""

import os
import random
import time

import collection_routes
import collection_store
import run_auth
import runner_commands
# Re-exported (run_parallel.py and server.py call these as
# run_orchestrator._read_csv_input etc.) — see run_csv_io.py's own docstring.
from run_csv_io import _build_iteration_inputs, _persist_captures, _read_csv_input, _write_retry_csv
# Re-exported (run_parallel.py calls these as orch.Counters etc.) — see
# run_execution_state.py's own docstring.
from run_execution_state import Context, Counters, RetryRows, _RunAborted, _halt_reason_and_detail

SCOPE_TYPES = ("request", "folder", "collection")
IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}
BACKOFF_BASE_SECONDS = 0.5
CANCEL_POLL_SECONDS = 0.5


def _folder_closure_by_name(folders, name):
    """Resolves scope["name"] to a folder id (first match — the Runner scope
    only ever carries a folder name, not an id, so two folders sharing a name
    across different parents is an inherent ambiguity this can't resolve; not
    a regression, the old name-prefix matching had the same limitation), then
    walks parentFolderId children outward (BFS) to collect that folder's full
    descendant closure. A childless folder's closure is just itself. Returns
    an empty set if no folder named `name` exists."""
    root = next((f for f in folders if isinstance(f, dict) and f.get("name") == name), None)
    if root is None:
        return set()
    closure = {root["id"]}
    frontier = [root["id"]]
    while frontier:
        current = frontier.pop()
        for f in folders:
            child_id = f.get("id") if isinstance(f, dict) else None
            if child_id and child_id not in closure and f.get("parentFolderId") == current:
                closure.add(child_id)
                frontier.append(child_id)
    return closure


def expand_scope(store, scope):
    """scope = {"type": "request"|"folder"|"collection", "slug": str, "name": str|None,
                "excludedNames": [str]|None}

    - "request":    the one request whose name == scope["name"]
    - "folder":     every request whose folderId is in the descendant closure
                    of the folder named scope["name"] (folders carry a real
                    parentFolderId chain — see collection_store.py — so this
                    also matches nested children, without relying on request
                    names encoding folder paths)
    - "collection": every request in the collection

    "excludedNames" is a checklist: a folder/collection scope includes every
    request by default, but the UI lets the user uncheck specific ones
    without changing the scope type.

    Order is the collection's stored `requests` order (= import order).
    Raises ValueError when the scope resolves to zero requests.
    """
    scope_type = scope.get("type")
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f"Unknown scope type {scope_type!r}")
    name = scope.get("name")
    collection = store.get(scope.get("slug"))
    requests = collection.get("requests", [])

    if scope_type == "request":
        matched = [r for r in requests if r.get("name") == name]
    elif scope_type == "folder":
        folder_ids = _folder_closure_by_name(collection.get("folders", []), name)
        matched = [r for r in requests if r.get("folderId") in folder_ids]
    else:
        matched = list(requests)

    excluded = set(scope.get("excludedNames") or [])
    if excluded:
        matched = [r for r in matched if r.get("name") not in excluded]

    if not matched:
        raise ValueError(f"Scope resolved to zero requests: {scope!r}")
    return matched


def resolve_extra_vars(csv_row, captured):
    """Precedence, highest first: CSV row > captured-so-far > environment >
    collection. (env > collection is already handled by
    environment_store.merge_variables.) Passed to _send_one as extra_vars —
    CSV-beats-captured is preserved because extra_vars is merged last in E1.
    """
    return {**(captured or {}), **(csv_row or {})}


def _tests_all_passed(result):
    tests = result.get("tests")
    return bool(tests) and all(t.get("passed") for t in tests)


def _classify(send_code, result, auth_retry_statuses):
    """Maps _send_one's return onto a RunEvent status (design §8.4)."""
    if send_code == 200:
        http_status = result.get("status")
        tests = result.get("tests")
        # A row with explicit assertions is graded by them even on a
        # configured auth-retry status — e.g. a deliberate
        # negative-authorization test case asserting `status equals 403`.
        # Only fall back to the token-expiry FLAGGED behavior when there's
        # nothing else to grade this row by.
        if tests:
            passed = sum(1 for t in tests if t.get("passed"))
            return "OK" if passed == len(tests) else "FAIL"
        if http_status in auth_retry_statuses:
            return "FLAGGED"
        return "OK" if isinstance(http_status, int) and 200 <= http_status < 300 else "FAIL"
    if send_code == 502:
        # A real socket timeout raises requests.exceptions.ReadTimeout/
        # ConnectTimeout (subclasses of Timeout), not the bare Timeout class
        # E3 names literally — match the family, not just the exact string.
        return "FLAGGED" if str(result.get("errorType") or "").endswith("Timeout") else "ERROR"
    return "ERROR"  # 400/403(inline-python)/404/409 — resolution failed, abort the run


def _is_transient(send_code, result):
    """Transport failure or a 5xx with no test rows evaluated — never an
    assertion mismatch (§12.1.2 "never retry a FAIL")."""
    if result.get("tests"):
        return False
    if send_code == 502:
        return True
    if send_code == 200:
        status = result.get("status")
        return isinstance(status, int) and status >= 500
    return False


def _backoff_seconds(attempt):
    base = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    jitter = base * 0.25
    return base + random.uniform(-jitter, jitter)


def _interruptible_sleep(seconds, cancel_event):
    end = time.monotonic() + seconds
    while not cancel_event.is_set():
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, CANCEL_POLL_SECONDS))


def _redact_captured(new_captures):
    return {
        k: ("***" if collection_store._SECRET_NAME_RE.search(k) else v)
        for k, v in new_captures.items()
    }


def _resolved_url(store, data, env_store, extra_vars):
    request, _ = collection_routes._resolve_send_one_request(store, data, env_store, extra_vars)
    return collection_routes._strip_disabled_query_params(request.get("url") or "")


def _has_secret_capture(request_tests):
    return any(
        isinstance(t, dict) and t.get("type") == "capture" and collection_store._SECRET_NAME_RE.search(t.get("variable") or "")
        for t in (request_tests or [])
    )


# Same redaction as _redact_captured, applied to the Tests tab (Runner
# master-detail response pane) instead of capturedVars — a secret-named
# capture's "actual" value must not reopen the hole responseSnippet already
# closes for the same case.
def _redact_test_results(tests):
    return [
        {**t, "actual": "***"} if t.get("type") == "capture" and collection_store._SECRET_NAME_RE.search(t.get("variable") or "")
        else t
        for t in tests
    ]


def _send_step(ctx, req, extra_vars, captured):
    """Sends one request: unconditional 403-retry-once, plus opt-in transient
    retry for idempotent methods (§12.1.2). A generator — yields a dict per
    real HTTP attempt made (so a caller can stream live proof that a retry
    actually happened, not just a post-hoc count), then returns (send_code,
    result, classification, attempt, max_attempts) as its StopIteration
    value."""
    data = {
        "slug": ctx.slug, "requestName": req["name"], "environmentSlug": ctx.env_slug,
        "timeout": ctx.timeout, "insecure": ctx.insecure, "proxySettings": ctx.proxy,
    }
    max_attempts = 1 + max(0, ctx.retries)
    sequence_started = time.monotonic()
    try:
        epoch = ctx.token_cache.get()[1]
    except run_auth.TokenMintFailed as exc:
        return 502, {"status": None, "error": str(exc), "errorType": "TokenMintFailed"}, "ERROR", 1, max_attempts
    data["auth"] = ctx.token_cache.auth_for_send()

    method = str(req.get("method") or "GET").upper()
    attempt = 1
    while True:
        send_code, result = collection_routes._send_one(
            ctx.store, data, ctx.env_store, extra_vars=extra_vars,
            capture_sink=captured, extra_headers=ctx.extra_headers,
        )
        if (
            send_code == 200
            and result.get("status") in ctx.auth_retry_statuses
            and ctx.token_cache.requires_minting()
            and not _tests_all_passed(result)
        ):
            try:
                _, epoch = ctx.token_cache.refresh(epoch)
            except run_auth.TokenMintFailed as exc:
                return (
                    502,
                    {"status": None, "error": str(exc), "errorType": "TokenMintFailed"},
                    "ERROR",
                    attempt,
                    max_attempts,
                )
            else:
                data["auth"] = ctx.token_cache.auth_for_send()
                send_code, result = collection_routes._send_one(
                    ctx.store, data, ctx.env_store, extra_vars=extra_vars,
                    capture_sink=captured, extra_headers=ctx.extra_headers,
                )
        transient = _is_transient(send_code, result)
        can_retry_method = method in IDEMPOTENT_METHODS or ctx.retry_unsafe
        will_retry = transient and can_retry_method and attempt < max_attempts
        yield {
            "attempt": attempt, "attempts": max_attempts,
            "httpStatus": result.get("status"), "error": result.get("error"),
            "willRetry": will_retry,
        }
        if will_retry:
            ctx.counters.add_retry()
            _interruptible_sleep(_backoff_seconds(attempt), ctx.cancel_event)
            attempt += 1
            if ctx.cancel_event.is_set():
                break
            continue
        break

    # A retried request's real cost is the whole sequence — backoff sleeps
    # included — not just the last attempt's own network time, which would
    # under-report by seconds and read as if nothing was retried at all.
    if attempt > 1:
        result["elapsedMs"] = int((time.monotonic() - sequence_started) * 1000)
    return send_code, result, _classify(send_code, result, ctx.auth_retry_statuses), attempt, max_attempts


def _run_request(ctx, iteration_index, iteration_total, step_index, req, csv_row, captured):
    """Generator — yields ("attempt", RunEvent) for each real HTTP try, then
    returns (event, classification, abort) as its StopIteration value."""
    extra_vars = resolve_extra_vars(csv_row, captured)
    url_probe = {"slug": ctx.slug, "requestName": req["name"], "environmentSlug": ctx.env_slug}
    resolved_url = _resolved_url(ctx.store, url_probe, ctx.env_store, extra_vars)
    capture_snapshot = dict(captured)

    send_step = _send_step(ctx, req, extra_vars, captured)
    try:
        while True:
            attempt_info = next(send_step)
            yield "attempt", {
                "type": "attempt",
                "iteration": iteration_index, "iterationTotal": iteration_total,
                "step": step_index, "stepTotal": len(ctx.requests_seq),
                "requestName": req["name"], "method": req.get("method"),
                **attempt_info,
            }
    except StopIteration as stop:
        send_code, result, classification, attempt, max_attempts = stop.value
    ctx.counters.add(classification)

    new_captures = {k: v for k, v in captured.items() if capture_snapshot.get(k) != v}
    request_tests = req.get("tests") or []
    snippet = None if _has_secret_capture(request_tests) else (result.get("body") or "")[:ctx.response_snippet_limit]
    tests = result.get("tests") or []

    event = {
        "type": "result",
        "iteration": iteration_index,
        "iterationTotal": iteration_total,
        "step": step_index,
        "stepTotal": len(ctx.requests_seq),
        "requestName": req["name"],
        "method": req.get("method"),
        "status": classification,
        "httpStatus": result.get("status"),
        "elapsedMs": result.get("elapsedMs"),
        "url": resolved_url,
        "testsPassed": sum(1 for t in tests if t.get("passed")),
        "testsTotal": len(tests),
        "capturedVars": _redact_captured(new_captures),
        "responseSnippet": snippet,
        "responseHeaders": result.get("headers") or {},
        "tests": _redact_test_results(tests),
        "error": result.get("error"),
        "warnings": result.get("warnings") or [],
        "attempt": attempt,
        "attempts": max_attempts,
    }
    abort = classification == "ERROR" and send_code != 502
    return event, classification, abort


def _run_iteration(ctx, iteration_index, iteration_total, csv_row, captured):
    """Generator yielding ("attempt", RunEvent) as each real HTTP try
    happens, then ("event", RunEvent) once the request's retries are
    exhausted, then ("done", (failed_step, control)) — control is None |
    "CANCELLED" | "DEADLINE" | "ABORTED". Shared verbatim by the sequential
    loop below and run_parallel's per-iteration worker task."""
    failed_step = None
    for step_index, req in enumerate(ctx.requests_seq, start=1):
        if ctx.cancel_event.is_set():
            yield "done", (failed_step, "CANCELLED")
            return
        if time.monotonic() > ctx.deadline:
            yield "done", (failed_step, "DEADLINE")
            return

        run_request = _run_request(ctx, iteration_index, iteration_total, step_index, req, csv_row, captured)
        try:
            while True:
                yield next(run_request)
        except StopIteration as stop:
            event, classification, abort = stop.value
        except (run_auth.TokenCircuitOpen, run_auth.TokenRefreshExhausted):
            # Record which request was in flight before re-raising, so the
            # caller can still attribute this row's retry-CSV entry — same
            # "done" control-tuple shape as CANCELLED/DEADLINE/ABORTED.
            yield "done", (req["name"], "AUTH_HALT")
            raise
        yield "event", event

        if classification != "OK" and failed_step is None:
            failed_step = req["name"]
        if abort:
            yield "done", (failed_step, "ABORTED")
            return
        if ctx.delay:
            _interruptible_sleep(ctx.delay, ctx.cancel_event)
    yield "done", (failed_step, None)


def execute(run_id, spec, store, env_store, cancel_event):
    """Generator yielding RunEvent dicts. `spec` is the validated POST body."""
    if int(spec.get("workers") or 1) > 1:
        import run_parallel

        yield from run_parallel.execute_parallel(run_id, spec, store, env_store, cancel_event)
        return

    requests_seq = expand_scope(store, spec["scope"])
    csv_rows, csv_fieldnames, csv_path = _read_csv_input(spec)
    iteration_inputs = _build_iteration_inputs(spec, csv_rows)

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
    reset_each_iteration = spec.get("resetCapturesEachIteration", True)

    total_iterations = len(iteration_inputs)
    total_requests = total_iterations * len(requests_seq)
    deadline = time.monotonic() + runner_commands.process_timeout_for(
        total_requests, timeout=spec.get("timeout"), delay=spec.get("delay")
    )
    counters = Counters()
    ctx = Context(spec, store, env_store, requests_seq, token_cache, cancel_event, deadline, counters)

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

    captured = {}
    retry_rows = RetryRows()
    exit_code, status = 0, "COMPLETED"
    halt_reason, halt_detail = None, None
    iteration_index, csv_row, failed_step = None, None, None

    try:
        for iteration_index, csv_row in enumerate(iteration_inputs, start=1):
            failed_step, control = None, None
            if cancel_event.is_set():
                raise _RunAborted(130, "STOPPED")
            if time.monotonic() > deadline:
                raise _RunAborted(124, "TIMEOUT")
            if reset_each_iteration:
                captured.clear()
            if refresh_each_row:
                try:
                    token_cache.force_refresh()
                except run_auth.TokenMintFailed as exc:
                    yield {"type": "log", "message": f"Token refresh failed: {exc}"}
                    raise _RunAborted(1, "COMPLETED")
                except (run_auth.TokenCircuitOpen, run_auth.TokenRefreshExhausted):
                    # No request in this row was ever attempted, but the row
                    # still needs to land in the retry CSV — the outer
                    # except's retry_rows.add() is gated on failed_step.
                    failed_step = "(token refresh)"
                    raise

            for kind, payload in _run_iteration(ctx, iteration_index, total_iterations, csv_row, captured):
                if kind in ("event", "attempt"):
                    yield payload
                else:
                    failed_step, control = payload

            if csv_row is not None and failed_step is not None:
                retry_rows.add(iteration_index, csv_row, failed_step)
            if control == "CANCELLED":
                raise _RunAborted(130, "STOPPED")
            if control == "DEADLINE":
                raise _RunAborted(124, "TIMEOUT")
            if control == "ABORTED":
                raise _RunAborted(1, "COMPLETED")
    except _RunAborted as aborted:
        exit_code, status = aborted.exit_code, aborted.status
        halt_reason, halt_detail = aborted.halt_reason, aborted.halt_detail
    except (run_auth.TokenCircuitOpen, run_auth.TokenRefreshExhausted) as exc:
        if csv_row is not None and failed_step is not None:
            retry_rows.add(iteration_index, csv_row, failed_step)
        exit_code, status = 1, "STOPPED"
        halt_reason, halt_detail = _halt_reason_and_detail(exc, iteration_index)

    counts = counters.snapshot()
    if exit_code == 0 and (counts["FAIL"] or counts["FLAGGED"] or counts["ERROR"]):
        exit_code = 1

    capture_error = _persist_captures(
        captured, csv_path, bool(spec.get("persistCaptures")),
        spec["scope"].get("slug"), spec.get("environmentSlug"), store, env_store,
    )
    retry_csv_path = _write_retry_csv(retry_rows.sorted_rows(), csv_path, csv_fieldnames, spec.get("outputFolder"))

    summary_event = {
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
    if capture_error:
        summary_event["captureError"] = capture_error
    yield summary_event
