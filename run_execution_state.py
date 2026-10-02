"""Shared run-state primitives — Context, Counters, RetryRows, the abort
exception, and halt-reason translation. Split out of run_orchestrator.py
(design §7 "New backend files") purely to stay under the 500-line limit;
run_orchestrator.py re-exports these so run_parallel.py's existing
`orch.Counters` / `orch.RetryRows` / `orch.Context` references keep working
unchanged.
"""

import threading

import run_auth

RESPONSE_SNIPPET_LIMIT = 20000
DEFAULT_AUTH_RETRY_STATUSES = frozenset({401, 403})


class _RunAborted(Exception):
    def __init__(self, exit_code, status, halt_reason=None, halt_detail=None):
        self.exit_code = exit_code
        self.status = status
        self.halt_reason = halt_reason
        self.halt_detail = halt_detail


def _halt_reason_and_detail(exc, row):
    """Translates a TokenCircuitOpen/TokenRefreshExhausted into the summary
    event's machine-readable haltReason/haltDetail (design §4)."""
    if isinstance(exc, run_auth.TokenCircuitOpen):
        return "auth-circuit-open", {
            "row": row, "consecutiveMintFailures": exc.consecutive_failures, "lastError": exc.last_error,
        }
    return "auth-refresh-exhausted", {
        "row": row, "consecutiveMintFailures": None, "lastError": exc.last_error,
    }


class Counters:
    """Thread-safe classification/retry tallies — shared by the sequential
    loop and run_parallel's worker threads (PR6)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {"OK": 0, "FAIL": 0, "FLAGGED": 0, "ERROR": 0}
        self.retried_requests = 0

    def add(self, classification):
        with self._lock:
            self._counts[classification] += 1

    def add_retry(self):
        """Called once per actual retry attempt, not once per request — a
        request that burns 3 retries increments this 3 times, so the
        "N retried" summary reflects real retry volume, not row count."""
        with self._lock:
            self.retried_requests += 1

    def snapshot(self):
        with self._lock:
            return dict(self._counts)


class RetryRows:
    """Thread-safe collector, sorted by iteration index before writing so a
    parallel run's retry CSV has a deterministic row order (§8.8)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rows = []

    def add(self, iteration_index, csv_row, failed_step):
        with self._lock:
            self._rows.append((iteration_index, {**csv_row, "__failedAtStep": failed_step}))

    def sorted_rows(self):
        with self._lock:
            return [row for _, row in sorted(self._rows, key=lambda pair: pair[0])]


class Context:
    """Everything a single request-send needs, built once per run and shared
    (read-only after construction, except thread-safe counters) by every
    iteration — sequential or parallel."""

    def __init__(self, spec, store, env_store, requests_seq, token_cache, cancel_event, deadline, counters):
        self.store = store
        self.env_store = env_store
        self.requests_seq = requests_seq
        self.slug = spec["scope"].get("slug")
        self.env_slug = spec.get("environmentSlug")
        self.auth_cfg = spec.get("auth") or {}
        configured_auth_retry_statuses = spec.get("authRetryStatuses")
        self.auth_retry_statuses = frozenset(
            configured_auth_retry_statuses if configured_auth_retry_statuses is not None
            else DEFAULT_AUTH_RETRY_STATUSES
        )
        self.token_cache = token_cache
        user_header = str(self.auth_cfg.get("user") or "").strip()
        self.extra_headers = {"User": user_header} if user_header else None
        self.timeout = float(spec.get("timeout") or 30)
        self.insecure = spec.get("insecure")
        self.proxy = spec.get("proxySettings")
        self.retries = int(spec.get("retries") or 0)
        self.retry_unsafe = bool(spec.get("retryUnsafe"))
        self.delay = float(spec.get("delay") or 0)
        self.response_snippet_limit = int(spec.get("responseSnippetLimit") or RESPONSE_SNIPPET_LIMIT)
        self.cancel_event = cancel_event
        self.deadline = deadline
        self.counters = counters
