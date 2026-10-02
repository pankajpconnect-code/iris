// Global TLS-certificate-verification toggle, same shape as
// request-timeout.js. /api/send-one (collection_routes.py) and
// /api/run-stream (run_orchestrator.py) already accept an optional
// "insecure" field and default to verifying certificates (verify=True)
// when absent — this is just the missing UI to disable that.
const INSECURE_MODE_STORAGE_KEY = "iris.insecureMode";

function getInsecureMode() {
  return localStorage.getItem(INSECURE_MODE_STORAGE_KEY) === "true";
}

function setInsecureMode(value) {
  localStorage.setItem(INSECURE_MODE_STORAGE_KEY, value ? "true" : "false");
}

document.addEventListener("DOMContentLoaded", () => {
  const checkbox = $("insecureModeCheckbox");
  checkbox.checked = getInsecureMode();
  checkbox.addEventListener("change", () => {
    setInsecureMode(checkbox.checked);
  });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { getInsecureMode, setInsecureMode, INSECURE_MODE_STORAGE_KEY };
}
