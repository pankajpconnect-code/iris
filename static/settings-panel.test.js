// static/settings-panel.test.js
const test = require("node:test");
const assert = require("node:assert/strict");

const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = v; },
  removeItem: (k) => { delete store[k]; },
};
global.document = { addEventListener: () => {} };

const elements = {};
function mockElement() {
  return {
    value: "",
    checked: false,
    classList: {
      _hidden: false,
      add(cls) { if (cls === "hidden") this._hidden = true; },
      remove(cls) { if (cls === "hidden") this._hidden = false; },
      toggle(cls, force) { if (cls === "hidden") this._hidden = force; },
    },
    addEventListener() {},
  };
}
global.$ = (id) => elements[id] || (elements[id] = mockElement());

const proxySettingsModule = require("./proxy-settings.js");
const { getProxySettings, setProxySettings, patchProxySettings, defaultProxySettings } = proxySettingsModule;

// Make proxy functions globally available for settings-panel.js
global.getProxySettings = getProxySettings;
global.patchProxySettings = patchProxySettings;

const {
  renderProxyFields, updateProxyCustomFieldsVisibility, isValidUrl, parseBypassList, resolveProxyUrlInput,
  positionSettingsModal,
} = require("./settings-panel.js");

function clearStore() {
  for (const key of Object.keys(store)) delete store[key];
  for (const key of Object.keys(elements)) delete elements[key];
}

test("isValidUrl: accepts a well-formed URL", () => {
  assert.equal(isValidUrl("http://127.0.0.1:8080"), true);
});

test("isValidUrl: rejects a malformed URL", () => {
  assert.equal(isValidUrl("not a url"), false);
});

test("isValidUrl: rejects a non-http(s) scheme like javascript:", () => {
  assert.equal(isValidUrl("javascript:alert(1)"), false);
});

test("isValidUrl: rejects a scheme-less/host-less string", () => {
  assert.equal(isValidUrl("file:///etc/passwd"), false);
});

test("parseBypassList: splits lines, trims, and drops blanks", () => {
  assert.deepEqual(parseBypassList("example.com\n \n.internal.corp\n"), ["example.com", ".internal.corp"]);
});

test("resolveProxyUrlInput: accepts a valid URL", () => {
  assert.deepEqual(resolveProxyUrlInput("http://127.0.0.1:8080", ""), { valid: true, value: "http://127.0.0.1:8080" });
});

test("resolveProxyUrlInput: treats an empty value as valid (no proxy), not an error", () => {
  assert.deepEqual(resolveProxyUrlInput("", "http://old:1"), { valid: true, value: "" });
});

test("resolveProxyUrlInput: treats a whitespace-only value as valid (no proxy)", () => {
  assert.deepEqual(resolveProxyUrlInput("   ", "http://old:1"), { valid: true, value: "" });
});

test("resolveProxyUrlInput: rejects a malformed value and reverts to the previous URL", () => {
  assert.deepEqual(resolveProxyUrlInput("not a url", "http://old:1"), { valid: false, value: "http://old:1" });
});

test("positionSettingsModal: anchors the box top just below the settings button", () => {
  clearStore();
  elements.settingsBtn = { getBoundingClientRect: () => ({ bottom: 50, right: 900 }) };
  elements.settingsModalBox = { style: {} };
  positionSettingsModal();
  assert.equal(elements.settingsModalBox.style.top, "58px");
});

test("updateProxyCustomFieldsVisibility: shows custom fields only in custom mode", () => {
  clearStore();
  updateProxyCustomFieldsVisibility("system");
  assert.equal(elements["proxyCustomFields"].classList._hidden, true);
  updateProxyCustomFieldsVisibility("custom");
  assert.equal(elements["proxyCustomFields"].classList._hidden, false);
});

test("renderProxyFields: populates fields from stored settings", () => {
  clearStore();
  setProxySettings({ mode: "env", url: "http://a:1", username: "bob", password: "pw", bypassList: ["x.com", "y.com"] });
  renderProxyFields();
  assert.equal(elements["proxyModeEnv"].checked, true);
  assert.equal(elements["proxyUrlInput"].value, "http://a:1");
  assert.equal(elements["proxyUsernameInput"].value, "bob");
  assert.equal(elements["proxyPasswordInput"].value, "pw");
  assert.equal(elements["proxyBypassListInput"].value, "x.com\ny.com");
});

test("renderProxyFields: switching mode away and back preserves custom fields in storage", () => {
  clearStore();
  setProxySettings({ mode: "custom", url: "http://a:1", username: "bob", password: "pw", bypassList: [] });
  const { patchProxySettings } = require("./proxy-settings.js");
  patchProxySettings({ mode: "system" });
  patchProxySettings({ mode: "custom" });
  const result = getProxySettings();
  assert.equal(result.url, "http://a:1");
  assert.equal(result.username, "bob");
});
