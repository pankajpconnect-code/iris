"""Single-flight token caching for the Runner orchestrator (design §5.1, §8.8).

Split out of run_orchestrator.py per the design doc's own guidance, to keep
that file under the 300-line soft target.
"""

import os
import threading
import types

import oauth2_client_credentials
import run_api_from_csv

DEFAULT_MAX_REFRESHES = 10
DEFAULT_MAX_CONSECUTIVE_MINT_FAILURES = 3


class TokenMintFailed(Exception):
    """generate_token raises SystemExit (BaseException, not Exception) on
    failure — a bare `except Exception` would not catch it, and
    `future.result()` would re-raise it on the connection thread under PR6's
    thread pool. Every mint site wraps and translates."""


class TokenRefreshExhausted(Exception):
    """A 403 does not always mean token expiry (permissions, wrong tenant);
    uncapped refreshing would hammer the identity endpoint. Raised once
    `max_refreshes` is reached — the caller keeps the stale token/FLAGGED."""

    def __init__(self, max_refreshes):
        self.last_error = f"Exceeded max token refreshes ({max_refreshes})"
        super().__init__(self.last_error)


class TokenCircuitOpen(Exception):
    """Identity endpoint has failed repeatedly; the run must not continue.
    Raised only from consecutive mint() failures — never from a row-level
    403/401, which stays a FLAGGED result (design §4's central guard)."""

    def __init__(self, consecutive_failures, last_error):
        self.consecutive_failures = consecutive_failures
        self.last_error = last_error
        super().__init__(
            f"Token mint failed {consecutive_failures} times consecutively: {last_error}"
        )


def _scrub_secret(text, secret):
    """lastError reaches the run summary and, from there, disk — the raw
    refresh-token value must never ride along."""
    if not secret:
        return text
    return text.replace(secret, "***")


class TokenCache:
    """Mints at most one token per run unless invalidated. Correct for
    workers=1 (PR3) and workers>1 (PR6) — refresh is compare-and-swap on an
    epoch counter so N workers hitting a stale token together mint exactly
    once; the rest reuse the fresh token for free."""

    def __init__(
        self, auth_cfg, max_refreshes=DEFAULT_MAX_REFRESHES,
        max_consecutive_mint_failures=DEFAULT_MAX_CONSECUTIVE_MINT_FAILURES,
        breaker_enabled=True,
    ):
        self._auth_cfg = auth_cfg or {}
        self._lock = threading.Lock()
        self._token = None
        self._epoch = 0
        self._refreshes = 0
        self._max_refreshes = max_refreshes
        self._minted = False
        self._max_consecutive_mint_failures = max_consecutive_mint_failures
        self._breaker_enabled = breaker_enabled
        self._consecutive_mint_failures = 0
        self._last_mint_error = None

    def _mint_once(self):
        if self._auth_cfg.get("mode") == "oauth2-client-credentials":
            mint = lambda: oauth2_client_credentials.mint_client_credentials_token(
                client_id=self._auth_cfg.get("oauth2ClientId") or "",
                client_secret=self._auth_cfg.get("oauth2ClientSecret") or "",
                token_url=self._auth_cfg.get("oauth2TokenUrl") or "",
                scope=self._auth_cfg.get("oauth2Scope") or None,
                auth_style=self._auth_cfg.get("oauth2AuthStyle") or "basic-header",
                timeout=float(self._auth_cfg.get("timeout") or 30),
            )
        else:
            namespace = types.SimpleNamespace(
                refresh_token=self._auth_cfg.get("refreshToken") or "",
                refresh_token_env=self._auth_cfg.get("refreshTokenEnv") or "REFRESH_TOKEN",
                refresh_token_cookie_name=self._auth_cfg.get("refreshTokenCookieName")
                or "org.apache.fincn.refreshToken",
                token_url=self._auth_cfg.get("tokenUrl") or "",
                tenant=self._auth_cfg.get("tenant") or "",
                token_field=self._auth_cfg.get("tokenField") or "accessToken",
                insecure=bool(self._auth_cfg.get("insecure")),
                timeout=float(self._auth_cfg.get("timeout") or 30),
            )
            mint = lambda: run_api_from_csv.generate_token(namespace)
        try:
            return mint()
        except SystemExit as exc:
            raise TokenMintFailed(str(exc)) from exc
        except Exception as exc:
            # Either mint path's own request to the identity/token endpoint
            # can also fail with a plain exception (connection error,
            # timeout, bad JSON) rather than the SystemExit both raise for
            # HTTP-level failures. Every mint site only expects
            # TokenMintFailed, so wrap this too instead of letting it escape
            # as a raw exception.
            raise TokenMintFailed(str(exc)) from exc

    def _mint(self):
        """Every call site already holds self._lock, so the counter below
        needs no locking of its own (design §4). Once the breaker is already
        open, further callers (e.g. other parallel workers queued on the
        same lock) fail fast instead of making another real request to a
        known-dead identity endpoint."""
        if self._breaker_enabled and self._consecutive_mint_failures >= self._max_consecutive_mint_failures:
            raise TokenCircuitOpen(self._consecutive_mint_failures, self._last_mint_error)
        try:
            token = self._mint_once()
        except TokenMintFailed as exc:
            self._consecutive_mint_failures += 1
            self._last_mint_error = _scrub_secret(str(exc), self._effective_refresh_token())
            if self._breaker_enabled and self._consecutive_mint_failures >= self._max_consecutive_mint_failures:
                raise TokenCircuitOpen(self._consecutive_mint_failures, self._last_mint_error) from exc
            raise
        else:
            self._consecutive_mint_failures = 0
            return token

    def _effective_refresh_token(self):
        """Mirrors generate_token's own resolution (run_api_from_csv.py) so
        the scrub below catches the secret regardless of whether it came
        from the config field or the env-var fallback."""
        return self._auth_cfg.get("refreshToken") or os.environ.get(
            self._auth_cfg.get("refreshTokenEnv") or "REFRESH_TOKEN", ""
        )

    def _requires_minting(self):
        mode = self._auth_cfg.get("mode")
        if mode == "refresh-cookie":
            return bool(self._auth_cfg.get("tokenUrl"))
        if mode == "oauth2-client-credentials":
            return bool(self._auth_cfg.get("oauth2TokenUrl"))
        return False

    def requires_minting(self):
        """Public alias — run_orchestrator's retry gate needs to know
        whether a mint-triggering auth mode is configured, without
        duplicating this mode/field logic a second time."""
        return self._requires_minting()

    def get(self):
        """(token, epoch). Mints on first call for refresh-cookie mode."""
        with self._lock:
            if not self._minted:
                if self._requires_minting():
                    self._token = self._mint()
                self._minted = True
            return self._token, self._epoch

    def refresh(self, seen_epoch):
        """Called by a caller that got a 403 while using `seen_epoch`."""
        with self._lock:
            if self._epoch != seen_epoch:
                return self._token, self._epoch  # someone already refreshed
            if self._refreshes >= self._max_refreshes:
                raise TokenRefreshExhausted(self._max_refreshes)
            self._token = self._mint()
            self._epoch += 1
            self._refreshes += 1
            return self._token, self._epoch

    def force_refresh(self):
        """refreshTokenEachRow: mint exactly once, unconditionally — does not
        share the CAS path with refresh() since "each row" is a deliberate
        per-iteration mint, not a storm-guarded reaction to a 403."""
        with self._lock:
            self._token = self._mint()
            self._epoch += 1
            self._minted = True
            return self._token, self._epoch

    def auth_for_send(self):
        mode = self._auth_cfg.get("mode") or "none"
        if mode == "bearer":
            return {"mode": "bearer", "bearerToken": self._auth_cfg.get("bearerToken") or ""}
        if mode == "basic":
            return {
                "mode": "basic",
                "basicUser": self._auth_cfg.get("basicUser") or "",
                "basicPassword": self._auth_cfg.get("basicPassword") or "",
                "tenant": self._auth_cfg.get("tenant") or "",
            }
        if mode == "refresh-cookie":
            token, _ = self.get()
            # Reported as `bearer` since the token is already minted (single-
            # flight caching lives in this class, not in _apply_auth) — but
            # the tenant still has to reach the request headers, so it must
            # ride along even though the wire mode is bearer.
            return {
                "mode": "bearer",
                "bearerToken": token or "",
                "tenant": self._auth_cfg.get("tenant") or "",
            }
        if mode == "oauth2-client-credentials":
            token, _ = self.get()
            return {"mode": "bearer", "bearerToken": token or ""}
        if mode == "apikey":
            return {
                "mode": "apikey",
                "apiKeyName": self._auth_cfg.get("apiKeyName") or "",
                "apiKeyValue": self._auth_cfg.get("apiKeyValue") or "",
                "apiKeyLocation": self._auth_cfg.get("apiKeyLocation") or "header",
            }
        return {"mode": "none"}
