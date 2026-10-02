/* Runner "Options" popover (ROADMAP §5.4) — holds genuinely set-once
 * settings (reset captures, persist captures, output folder, response cap)
 * plus the RETRY section (design 2026-09-10 §7): retries, delay,
 * maxTokenRefreshes, authBreakerEnabled, refreshTokenCookieName,
 * authRetryStatuses. `retryUnsafe` is deliberately NOT exposed here (§2) —
 * it enables retrying POST/PUT/DELETE on 5xx/timeout, which risks duplicate
 * records on a row-generating run; it stays API-only.
 * The trigger shows any non-default value inline so nothing is ever
 * silently in effect while hidden — rule 1 of the two that make collapsing
 * these into a popover safe (rule 2, the parallel-workers lock icon, is
 * handled by syncRunnerWorkersConstraint in runner-view.js).
 *
 * Persistence follows request-timeout.js's pattern (getter falls back to a
 * default on anything missing/invalid) under the `iris.runner.*` namespace —
 * Runner options aren't persisted anywhere else today.
 */

const RUNNER_STORAGE_PREFIX = "iris.runner.";
const DEFAULT_RUNNER_RETRIES = 0;
const DEFAULT_RUNNER_RETRY_DELAY_MS = 0;
const DEFAULT_RUNNER_MAX_TOKEN_REFRESHES = 10;
const DEFAULT_RUNNER_REFRESH_TOKEN_COOKIE_NAME = "org.apache.fincn.refreshToken";
const DEFAULT_RUNNER_AUTH_RETRY_STATUSES = [401, 403];

function _getRunnerNonNegativeInt(key, fallback) {
  const stored = localStorage.getItem(RUNNER_STORAGE_PREFIX + key);
  const n = Number(stored);
  return stored !== null && Number.isInteger(n) && n >= 0 ? n : fallback;
}

function _setRunnerNonNegativeInt(key, value) {
  const n = Number(value);
  if (Number.isInteger(n) && n >= 0) {
    localStorage.setItem(RUNNER_STORAGE_PREFIX + key, String(n));
  }
}

function getRunnerRetries() {
  return _getRunnerNonNegativeInt("retries", DEFAULT_RUNNER_RETRIES);
}
function setRunnerRetries(value) {
  _setRunnerNonNegativeInt("retries", value);
}

function getRunnerRetryDelayMs() {
  return _getRunnerNonNegativeInt("delay", DEFAULT_RUNNER_RETRY_DELAY_MS);
}
function setRunnerRetryDelayMs(value) {
  _setRunnerNonNegativeInt("delay", value);
}

function getRunnerMaxTokenRefreshes() {
  const stored = _getRunnerNonNegativeInt("maxTokenRefreshes", DEFAULT_RUNNER_MAX_TOKEN_REFRESHES);
  return stored >= 1 ? stored : DEFAULT_RUNNER_MAX_TOKEN_REFRESHES;
}
function setRunnerMaxTokenRefreshes(value) {
  const n = Number(value);
  if (Number.isInteger(n) && n >= 1) {
    localStorage.setItem(RUNNER_STORAGE_PREFIX + "maxTokenRefreshes", String(n));
  }
}

function getRunnerAuthBreakerEnabled() {
  const stored = localStorage.getItem(RUNNER_STORAGE_PREFIX + "authBreakerEnabled");
  return stored === null ? true : stored === "true";
}
function setRunnerAuthBreakerEnabled(checked) {
  localStorage.setItem(RUNNER_STORAGE_PREFIX + "authBreakerEnabled", checked ? "true" : "false");
}

function getRunnerRefreshTokenCookieName() {
  const stored = (localStorage.getItem(RUNNER_STORAGE_PREFIX + "refreshTokenCookieName") || "").trim();
  return stored || DEFAULT_RUNNER_REFRESH_TOKEN_COOKIE_NAME;
}
function setRunnerRefreshTokenCookieName(value) {
  const trimmed = (value || "").trim();
  if (trimmed) {
    localStorage.setItem(RUNNER_STORAGE_PREFIX + "refreshTokenCookieName", trimmed);
  } else {
    localStorage.removeItem(RUNNER_STORAGE_PREFIX + "refreshTokenCookieName");
  }
}

function getRunnerAuthRetryStatuses() {
  const stored = localStorage.getItem(RUNNER_STORAGE_PREFIX + "authRetryStatuses");
  if (stored === null) return DEFAULT_RUNNER_AUTH_RETRY_STATUSES.slice();
  try {
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed : DEFAULT_RUNNER_AUTH_RETRY_STATUSES.slice();
  } catch {
    return DEFAULT_RUNNER_AUTH_RETRY_STATUSES.slice();
  }
}
function setRunnerAuthRetryStatuses(statuses) {
  localStorage.setItem(RUNNER_STORAGE_PREFIX + "authRetryStatuses", JSON.stringify(statuses));
}

function syncRunnerOptionsBadge() {
  const nonDefault = [];
  if (!$("runnerResetCapturesCheck").checked) nonDefault.push("captures not reset");
  if ($("runnerPersistCapturesCheck").checked) nonDefault.push("persist captures");
  const cap = $("runnerResponseCapInput").value;
  if (cap !== "" && Number(cap) !== 20000) nonDefault.push(`${cap}-char cap`);
  if (getRunnerRetries() !== DEFAULT_RUNNER_RETRIES) nonDefault.push(`${getRunnerRetries()} retries`);
  if (getRunnerRetryDelayMs() !== DEFAULT_RUNNER_RETRY_DELAY_MS) nonDefault.push(`${getRunnerRetryDelayMs()}ms delay`);
  if (getRunnerMaxTokenRefreshes() !== DEFAULT_RUNNER_MAX_TOKEN_REFRESHES) {
    nonDefault.push(`${getRunnerMaxTokenRefreshes()} max refreshes`);
  }
  if (!getRunnerAuthBreakerEnabled()) nonDefault.push("auth breaker off");
  if (getRunnerRefreshTokenCookieName() !== DEFAULT_RUNNER_REFRESH_TOKEN_COOKIE_NAME) nonDefault.push("custom cookie name");
  const statuses = getRunnerAuthRetryStatuses();
  const isDefaultStatuses = statuses.length === DEFAULT_RUNNER_AUTH_RETRY_STATUSES.length
    && DEFAULT_RUNNER_AUTH_RETRY_STATUSES.every((s) => statuses.includes(s));
  if (!isDefaultStatuses) nonDefault.push(statuses.length ? `retry on ${statuses.join("/")}` : "auth retry off");
  const button = $("runnerOptionsBtn");
  button.innerHTML = `Options${nonDefault.length ? ` <span class="badge">${escapeHtml(nonDefault.join(" · "))}</span>` : ""}`;
  button.classList.toggle("on", nonDefault.length > 0);
}

document.addEventListener("DOMContentLoaded", () => {
  $("runnerOptionsBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    $("runnerOptionsPop").classList.toggle("hidden");
  });
  $("runnerOptionsPop").addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", () => $("runnerOptionsPop").classList.add("hidden"));

  $("runnerRetriesInput").value = getRunnerRetries();
  $("runnerRetryDelayInput").value = getRunnerRetryDelayMs();
  $("runnerMaxTokenRefreshesInput").value = getRunnerMaxTokenRefreshes();
  $("runnerAuthBreakerCheck").checked = getRunnerAuthBreakerEnabled();
  $("runnerRefreshCookieNameInput").value = getRunnerRefreshTokenCookieName();
  const initialStatuses = getRunnerAuthRetryStatuses();
  $("runnerAuthRetry401Check").checked = initialStatuses.includes(401);
  $("runnerAuthRetry403Check").checked = initialStatuses.includes(403);

  $("runnerRetriesInput").addEventListener("change", () => {
    setRunnerRetries($("runnerRetriesInput").value);
    $("runnerRetriesInput").value = getRunnerRetries();
    syncRunnerOptionsBadge();
  });
  $("runnerRetryDelayInput").addEventListener("change", () => {
    setRunnerRetryDelayMs($("runnerRetryDelayInput").value);
    $("runnerRetryDelayInput").value = getRunnerRetryDelayMs();
    syncRunnerOptionsBadge();
  });
  $("runnerMaxTokenRefreshesInput").addEventListener("change", () => {
    setRunnerMaxTokenRefreshes($("runnerMaxTokenRefreshesInput").value);
    $("runnerMaxTokenRefreshesInput").value = getRunnerMaxTokenRefreshes();
    syncRunnerOptionsBadge();
  });
  $("runnerAuthBreakerCheck").addEventListener("change", () => {
    setRunnerAuthBreakerEnabled($("runnerAuthBreakerCheck").checked);
    syncRunnerOptionsBadge();
  });
  $("runnerRefreshCookieNameInput").addEventListener("change", () => {
    setRunnerRefreshTokenCookieName($("runnerRefreshCookieNameInput").value);
    $("runnerRefreshCookieNameInput").value = getRunnerRefreshTokenCookieName();
    syncRunnerOptionsBadge();
  });
  const syncAuthRetryStatuses = () => {
    const statuses = [];
    if ($("runnerAuthRetry401Check").checked) statuses.push(401);
    if ($("runnerAuthRetry403Check").checked) statuses.push(403);
    setRunnerAuthRetryStatuses(statuses);
    syncRunnerOptionsBadge();
  };
  $("runnerAuthRetry401Check").addEventListener("change", syncAuthRetryStatuses);
  $("runnerAuthRetry403Check").addEventListener("change", syncAuthRetryStatuses);

  ["runnerResetCapturesCheck", "runnerPersistCapturesCheck", "runnerResponseCapInput"].forEach((id) =>
    $(id).addEventListener("input", syncRunnerOptionsBadge));
  syncRunnerOptionsBadge();
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    getRunnerRetries, setRunnerRetries, DEFAULT_RUNNER_RETRIES,
    getRunnerRetryDelayMs, setRunnerRetryDelayMs, DEFAULT_RUNNER_RETRY_DELAY_MS,
    getRunnerMaxTokenRefreshes, setRunnerMaxTokenRefreshes, DEFAULT_RUNNER_MAX_TOKEN_REFRESHES,
    getRunnerAuthBreakerEnabled, setRunnerAuthBreakerEnabled,
    getRunnerRefreshTokenCookieName, setRunnerRefreshTokenCookieName, DEFAULT_RUNNER_REFRESH_TOKEN_COOKIE_NAME,
    getRunnerAuthRetryStatuses, setRunnerAuthRetryStatuses, DEFAULT_RUNNER_AUTH_RETRY_STATUSES,
  };
}
