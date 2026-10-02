const test = require("node:test");
const assert = require("node:assert/strict");

const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = v; },
  removeItem: (k) => { delete store[k]; },
};
global.document = { addEventListener: () => {} };
global.$ = () => ({ addEventListener: () => {} });

const { getInsecureMode, setInsecureMode, INSECURE_MODE_STORAGE_KEY } = require("./insecure-settings.js");

test("getInsecureMode: defaults to false when nothing is stored", () => {
  assert.equal(getInsecureMode(), false);
});

test("setInsecureMode: persists true and getInsecureMode reflects it", () => {
  setInsecureMode(true);
  assert.equal(getInsecureMode(), true);
  assert.equal(store[INSECURE_MODE_STORAGE_KEY], "true");
  delete store[INSECURE_MODE_STORAGE_KEY];
});

test("setInsecureMode: persists false explicitly", () => {
  setInsecureMode(true);
  setInsecureMode(false);
  assert.equal(getInsecureMode(), false);
  delete store[INSECURE_MODE_STORAGE_KEY];
});
