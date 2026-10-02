// Outbound proxy configuration, applied to both the Console's single Send
// and each row the CSV Runner sends. /api/send-one (collection_routes.py,
// via proxy_resolver.resolve_proxy) and /api/run-stream (run_orchestrator.py)
// accept an optional "proxySettings" object matching the shape below.
const PROXY_SETTINGS_STORAGE_KEY = "iris.proxySettings";
const LEGACY_PROXY_URL_STORAGE_KEY = "iris.proxyUrl";

function defaultProxySettings() {
  return { mode: "system", url: "", username: "", password: "", bypassList: [] };
}

function isValidProxySettings(value) {
  return Boolean(value) && typeof value === "object" &&
    ["system", "env", "custom"].includes(value.mode) &&
    typeof value.url === "string" &&
    typeof value.username === "string" &&
    typeof value.password === "string" &&
    Array.isArray(value.bypassList);
}

// Duplicated from settings-panel.js's isValidUrl (plus the host check) —
// these are separate <script>-tag globals, not ES modules, so a tiny
// shared helper like this is duplicated per this codebase's convention
// rather than inventing a shared-module system for it.
function isValidProxyUrl(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) && Boolean(parsed.hostname);
  } catch (e) {
    return false;
  }
}

function migratedFromLegacyProxyUrl() {
  const legacy = localStorage.getItem(LEGACY_PROXY_URL_STORAGE_KEY);
  if (legacy === null) return null;
  if (!isValidProxyUrl(legacy)) return defaultProxySettings();
  return { ...defaultProxySettings(), mode: "custom", url: legacy };
}

// Reads the new-format key only if it's completely absent — legacy
// migration must never fire merely because the legacy key still exists.
// If the new key is present at all (valid or corrupted), it always wins:
// a valid value is returned as-is, a corrupted one falls straight to
// defaults, and the legacy key is never consulted either way.
function getProxySettings() {
  const stored = localStorage.getItem(PROXY_SETTINGS_STORAGE_KEY);
  if (stored !== null) {
    try {
      const parsed = JSON.parse(stored);
      if (isValidProxySettings(parsed)) return parsed;
    } catch (e) {
      // Corrupted JSON falls through to defaults below — never to legacy
      // migration, since the new key is present.
    }
    return defaultProxySettings();
  }
  return migratedFromLegacyProxyUrl() || defaultProxySettings();
}

function setProxySettings(settings) {
  if (!isValidProxySettings(settings)) return;
  localStorage.setItem(PROXY_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
}

function patchProxySettings(partial) {
  const next = { ...getProxySettings(), ...partial };
  setProxySettings(next);
  return next;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    getProxySettings, setProxySettings, patchProxySettings, defaultProxySettings,
    PROXY_SETTINGS_STORAGE_KEY, LEGACY_PROXY_URL_STORAGE_KEY,
  };
}
