const test = require("node:test");
const assert = require("node:assert/strict");

const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = v; },
  removeItem: (k) => { delete store[k]; },
};
global.document = { addEventListener: () => {} };
global.$ = () => ({ addEventListener: () => {}, classList: { toggle: () => {} } });

const {
  getRunnerRetries, setRunnerRetries, DEFAULT_RUNNER_RETRIES,
  getRunnerRetryDelayMs, setRunnerRetryDelayMs, DEFAULT_RUNNER_RETRY_DELAY_MS,
  getRunnerMaxTokenRefreshes, setRunnerMaxTokenRefreshes, DEFAULT_RUNNER_MAX_TOKEN_REFRESHES,
  getRunnerAuthBreakerEnabled, setRunnerAuthBreakerEnabled,
  getRunnerRefreshTokenCookieName, setRunnerRefreshTokenCookieName, DEFAULT_RUNNER_REFRESH_TOKEN_COOKIE_NAME,
  getRunnerAuthRetryStatuses, setRunnerAuthRetryStatuses, DEFAULT_RUNNER_AUTH_RETRY_STATUSES,
} = require("./runner-options-popover.js");

function clearStore() {
  for (const key of Object.keys(store)) delete store[key];
}

test("getRunnerRetries: falls back to the default when nothing is stored", () => {
  clearStore();
  assert.equal(getRunnerRetries(), DEFAULT_RUNNER_RETRIES);
});

test("getRunnerRetries: round-trips a valid value through localStorage", () => {
  clearStore();
  setRunnerRetries(3);
  assert.equal(getRunnerRetries(), 3);
});

test("getRunnerRetries: rejects a negative value rather than persisting it", () => {
  clearStore();
  setRunnerRetries(2);
  setRunnerRetries(-1);
  assert.equal(getRunnerRetries(), 2);
});

test("getRunnerRetries: rejects a non-numeric value rather than persisting it", () => {
  clearStore();
  setRunnerRetries(2);
  setRunnerRetries("abc");
  assert.equal(getRunnerRetries(), 2);
});

test("getRunnerRetryDelayMs: round-trips through localStorage, default 0", () => {
  clearStore();
  assert.equal(getRunnerRetryDelayMs(), DEFAULT_RUNNER_RETRY_DELAY_MS);
  setRunnerRetryDelayMs(500);
  assert.equal(getRunnerRetryDelayMs(), 500);
});

test("getRunnerMaxTokenRefreshes: round-trips through localStorage, default 10", () => {
  clearStore();
  assert.equal(getRunnerMaxTokenRefreshes(), DEFAULT_RUNNER_MAX_TOKEN_REFRESHES);
  setRunnerMaxTokenRefreshes(5);
  assert.equal(getRunnerMaxTokenRefreshes(), 5);
});

test("getRunnerMaxTokenRefreshes: rejects zero — spec requires integer >= 1", () => {
  clearStore();
  setRunnerMaxTokenRefreshes(5);
  setRunnerMaxTokenRefreshes(0);
  assert.equal(getRunnerMaxTokenRefreshes(), 5);
});

test("getRunnerAuthBreakerEnabled: defaults to true, round-trips false", () => {
  clearStore();
  assert.equal(getRunnerAuthBreakerEnabled(), true);
  setRunnerAuthBreakerEnabled(false);
  assert.equal(getRunnerAuthBreakerEnabled(), false);
  setRunnerAuthBreakerEnabled(true);
  assert.equal(getRunnerAuthBreakerEnabled(), true);
});

test("getRunnerRefreshTokenCookieName: falls back to the default when nothing is stored", () => {
  clearStore();
  assert.equal(getRunnerRefreshTokenCookieName(), DEFAULT_RUNNER_REFRESH_TOKEN_COOKIE_NAME);
});

test("getRunnerRefreshTokenCookieName: round-trips a custom value", () => {
  clearStore();
  setRunnerRefreshTokenCookieName("my.custom.cookie");
  assert.equal(getRunnerRefreshTokenCookieName(), "my.custom.cookie");
});

test("getRunnerRefreshTokenCookieName: a blank input yields the default, not an empty string", () => {
  clearStore();
  setRunnerRefreshTokenCookieName("my.custom.cookie");
  setRunnerRefreshTokenCookieName("");
  assert.equal(getRunnerRefreshTokenCookieName(), DEFAULT_RUNNER_REFRESH_TOKEN_COOKIE_NAME);
  assert.notEqual(getRunnerRefreshTokenCookieName(), "");
});

test("getRunnerRefreshTokenCookieName: whitespace-only input also falls back to the default", () => {
  clearStore();
  setRunnerRefreshTokenCookieName("   ");
  assert.equal(getRunnerRefreshTokenCookieName(), DEFAULT_RUNNER_REFRESH_TOKEN_COOKIE_NAME);
});

test("getRunnerAuthRetryStatuses: falls back to the default [401, 403] when nothing is stored", () => {
  clearStore();
  assert.deepEqual(getRunnerAuthRetryStatuses(), DEFAULT_RUNNER_AUTH_RETRY_STATUSES);
});

test("getRunnerAuthRetryStatuses: round-trips a custom set", () => {
  clearStore();
  setRunnerAuthRetryStatuses([403]);
  assert.deepEqual(getRunnerAuthRetryStatuses(), [403]);
});

test("getRunnerAuthRetryStatuses: an explicitly empty set round-trips as empty, not the default", () => {
  clearStore();
  setRunnerAuthRetryStatuses([]);
  assert.deepEqual(getRunnerAuthRetryStatuses(), []);
});

test("getRunnerAuthRetryStatuses: corrupted stored JSON falls back to the default", () => {
  clearStore();
  store["iris.runner.authRetryStatuses"] = "{not json";
  assert.deepEqual(getRunnerAuthRetryStatuses(), DEFAULT_RUNNER_AUTH_RETRY_STATUSES);
});
