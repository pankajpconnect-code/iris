const test = require("node:test");
const assert = require("node:assert/strict");

const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = v; },
  removeItem: (k) => { delete store[k]; },
};
global.document = { addEventListener: () => {} };
global.$ = () => ({});

function clearStore() {
  for (const key of Object.keys(store)) delete store[key];
}

const {
  getProxySettings, setProxySettings, patchProxySettings,
  PROXY_SETTINGS_STORAGE_KEY, LEGACY_PROXY_URL_STORAGE_KEY, defaultProxySettings,
} = require("./proxy-settings.js");

test("getProxySettings: returns defaults when nothing is stored", () => {
  clearStore();
  assert.deepEqual(getProxySettings(), defaultProxySettings());
});

test("getProxySettings: migrates a legacy iris.proxyUrl string into custom mode", () => {
  clearStore();
  store[LEGACY_PROXY_URL_STORAGE_KEY] = "http://127.0.0.1:8080";
  const result = getProxySettings();
  assert.equal(result.mode, "custom");
  assert.equal(result.url, "http://127.0.0.1:8080");
});

test("getProxySettings: a malformed legacy iris.proxyUrl (e.g. non-http scheme) falls back to defaults instead of being migrated as-is", () => {
  clearStore();
  store[LEGACY_PROXY_URL_STORAGE_KEY] = "javascript:alert(1)";
  assert.deepEqual(getProxySettings(), defaultProxySettings());
});

test("getProxySettings: an unparseable legacy iris.proxyUrl falls back to defaults instead of being migrated as-is", () => {
  clearStore();
  store[LEGACY_PROXY_URL_STORAGE_KEY] = "not a url";
  assert.deepEqual(getProxySettings(), defaultProxySettings());
});

test("getProxySettings: falls back to defaults when the new-format value is corrupted JSON", () => {
  clearStore();
  store[PROXY_SETTINGS_STORAGE_KEY] = "{not valid json";
  assert.deepEqual(getProxySettings(), defaultProxySettings());
});

test("getProxySettings: corrupted new-format value falls back to defaults even when a legacy key is present, never migrating the legacy value", () => {
  // Migration must fire only when the new key is completely absent —
  // never merely because the legacy key still exists. A present-but-
  // corrupted new key must go straight to defaults, not fall through to
  // legacy migration.
  clearStore();
  store[LEGACY_PROXY_URL_STORAGE_KEY] = "http://legacy-should-not-be-used:1234";
  store[PROXY_SETTINGS_STORAGE_KEY] = "{not valid json";
  assert.deepEqual(getProxySettings(), defaultProxySettings());
});

test("getProxySettings: a valid new-format value takes precedence over a still-present legacy key", () => {
  clearStore();
  store[LEGACY_PROXY_URL_STORAGE_KEY] = "http://old-value:1111";
  setProxySettings({ mode: "env", url: "", username: "", password: "", bypassList: [] });
  const result = getProxySettings();
  assert.equal(result.mode, "env");
});

test("setProxySettings: round-trips a full settings object", () => {
  clearStore();
  const settings = { mode: "env", url: "", username: "", password: "", bypassList: ["example.com"] };
  setProxySettings(settings);
  assert.deepEqual(getProxySettings(), settings);
});

test("setProxySettings: rejects an invalid shape and does not persist it", () => {
  clearStore();
  setProxySettings({ mode: "not-a-real-mode" });
  assert.deepEqual(getProxySettings(), defaultProxySettings());
});

test("patchProxySettings: merges a partial update onto the existing settings", () => {
  clearStore();
  setProxySettings({ mode: "custom", url: "http://a:1", username: "", password: "", bypassList: [] });
  const result = patchProxySettings({ url: "http://b:2" });
  assert.equal(result.url, "http://b:2");
  assert.equal(result.mode, "custom");
});
