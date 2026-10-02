// Global per-request timeout (seconds), applied to both the Console's
// single Send and each row the CSV Runner sends. Both /api/send-one
// (collection_routes.py) and /api/run-stream (run_orchestrator.py) already
// accept an optional "timeout" field on their request payload and fall back
// to a 30s default themselves — this is just the missing UI to set it,
// persisted the same way theme.js persists its own choice.
const REQUEST_TIMEOUT_STORAGE_KEY = "iris.requestTimeoutSeconds";
const DEFAULT_REQUEST_TIMEOUT_SECONDS = 120;

function getRequestTimeoutSeconds() {
  const stored = Number(localStorage.getItem(REQUEST_TIMEOUT_STORAGE_KEY));
  return stored > 0 ? stored : DEFAULT_REQUEST_TIMEOUT_SECONDS;
}

document.addEventListener("DOMContentLoaded", () => {
  const input = $("requestTimeoutInput");
  input.value = getRequestTimeoutSeconds();
  input.addEventListener("change", () => {
    const value = Number(input.value);
    if (Number.isFinite(value) && value > 0) {
      localStorage.setItem(REQUEST_TIMEOUT_STORAGE_KEY, String(value));
    } else {
      // Reject 0/negative/non-numeric input by reverting to whatever was
      // last valid, rather than silently sending a broken timeout value.
      input.value = getRequestTimeoutSeconds();
    }
  });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { getRequestTimeoutSeconds, REQUEST_TIMEOUT_STORAGE_KEY, DEFAULT_REQUEST_TIMEOUT_SECONDS };
}
