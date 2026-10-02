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

const { getRequestTimeoutSeconds, REQUEST_TIMEOUT_STORAGE_KEY, DEFAULT_REQUEST_TIMEOUT_SECONDS } = require("./request-timeout.js");

test("getRequestTimeoutSeconds: falls back to the default when nothing is stored", () => {
  assert.equal(getRequestTimeoutSeconds(), DEFAULT_REQUEST_TIMEOUT_SECONDS);
});

test("getRequestTimeoutSeconds: returns the stored value once set", () => {
  store[REQUEST_TIMEOUT_STORAGE_KEY] = "45";
  assert.equal(getRequestTimeoutSeconds(), 45);
  delete store[REQUEST_TIMEOUT_STORAGE_KEY];
});

test("getRequestTimeoutSeconds: falls back to the default for a corrupted/zero stored value", () => {
  store[REQUEST_TIMEOUT_STORAGE_KEY] = "not-a-number";
  assert.equal(getRequestTimeoutSeconds(), DEFAULT_REQUEST_TIMEOUT_SECONDS);
  store[REQUEST_TIMEOUT_STORAGE_KEY] = "0";
  assert.equal(getRequestTimeoutSeconds(), DEFAULT_REQUEST_TIMEOUT_SECONDS);
  delete store[REQUEST_TIMEOUT_STORAGE_KEY];
});
