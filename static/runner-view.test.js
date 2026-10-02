const test = require("node:test");
const assert = require("node:assert/strict");

global.escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
}[c]));
const fakeElements = {};
global.$ = (id) => fakeElements[id] || (fakeElements[id] = {
  classList: { add: () => {}, remove: () => {}, toggle: () => {} },
  children: [],
  parentElement: {},
  appendChild: (el) => fakeElements[id].children.push(el),
});
global.document = {
  addEventListener: () => {},
  createElement: () => ({ dataset: {}, classList: { add: () => {}, remove: () => {} } }),
};
// registerRunnerListRequestName/applyRunnerListFilterToRow live in the
// sibling runner-list-filters.js (500-line split) — not under test here.
global.registerRunnerListRequestName = () => {};
global.applyRunnerListFilterToRow = () => {};
// authPayloadFields/scopeWithExclusions/getRequestTimeoutSeconds and the
// runner-options-popover.js getters are all sibling-file globals in the
// browser — stubbed here so runnerSpec() is testable in isolation.
global.authPayloadFields = () => ({});
global.scopeWithExclusions = () => ({ type: "collection", slug: "c", name: null });
global.getRequestTimeoutSeconds = () => 120;
global.getProxySettings = () => ({ host: "proxy.example.com", port: 8080 });
global.getInsecureMode = () => true;
global.runnerState = {};
const {
  parseOptionalCount, chooseRunnerCsv, chooseRunnerOutputFolder, appendRunnerRow, appendRunnerAttemptRow, runnerSpec,
} = require("./runner-view.js");

// Caught by an independent review: runnerSpec() used
// `Number(value) || undefined`, which treats an explicit "0" the same as
// an empty field — typing 0 into Iterations (meaning "run zero times")
// silently fell back to the runner's default "auto" behavior instead.
test("runnerSpec: carries every retry/auth-retry-stability field from the options popover", () => {
  global.getRunnerRetries = () => 2;
  global.getRunnerRetryDelayMs = () => 250;
  global.getRunnerMaxTokenRefreshes = () => 7;
  global.getRunnerAuthBreakerEnabled = () => false;
  global.getRunnerAuthRetryStatuses = () => [403];
  global.getRunnerRefreshTokenCookieName = () => "custom.cookie.name";

  const spec = runnerSpec("run-1");

  assert.equal(spec.retries, 2);
  // ctx.delay is consumed as SECONDS by _interruptible_sleep on the backend
  // (run_execution_state.py) — the popover's field is labelled and stored in
  // ms for finer-grained input, so runnerSpec() must convert.
  assert.equal(spec.delay, 0.25);
  assert.equal(spec.maxTokenRefreshes, 7);
  assert.equal(spec.authBreakerEnabled, false);
  assert.deepEqual(spec.authRetryStatuses, [403]);
  assert.equal(spec.refreshTokenCookieName, "custom.cookie.name");
});

// retryUnsafe enables retrying POST/PUT/DELETE on 5xx/timeout — duplicate
// records on a row-generating run are unrecoverable, so it stays API-only
// (design §2). Guards against it resurfacing via runnerSpec() by accident.
test("runnerSpec: never includes retryUnsafe", () => {
  global.getRunnerRetries = () => 0;
  global.getRunnerRetryDelayMs = () => 0;
  global.getRunnerMaxTokenRefreshes = () => 10;
  global.getRunnerAuthBreakerEnabled = () => true;
  global.getRunnerAuthRetryStatuses = () => [401, 403];
  global.getRunnerRefreshTokenCookieName = () => "org.apache.fincn.refreshToken";

  const spec = runnerSpec("run-2");
  assert.equal("retryUnsafe" in spec, false);
});

test("runnerSpec: payload includes proxySettings and insecure from settings modules", () => {
  global.getRunnerRetries = () => 0;
  global.getRunnerRetryDelayMs = () => 0;
  global.getRunnerMaxTokenRefreshes = () => 10;
  global.getRunnerAuthBreakerEnabled = () => true;
  global.getRunnerAuthRetryStatuses = () => [];
  global.getRunnerRefreshTokenCookieName = () => "";

  const spec = runnerSpec("run-3");
  assert.deepEqual(spec.proxySettings, getProxySettings());
  assert.equal(spec.insecure, getInsecureMode());
});

test("parseOptionalCount: empty string is undefined (field left blank)", () => {
  assert.equal(parseOptionalCount(""), undefined);
});

test("parseOptionalCount: explicit 0 is 0, not undefined", () => {
  assert.equal(parseOptionalCount("0"), 0);
});

test("parseOptionalCount: a normal positive value parses as a number", () => {
  assert.equal(parseOptionalCount("5"), 5);
});

// A user dismissing the native "Choose CSV" dialog isn't an error — it
// previously surfaced the raw AppleScript "User cancelled. (-128)" text in
// an alert(). The server now reports {cancelled: true} and this must resolve
// quietly instead of throwing.
test("chooseRunnerCsv: resolves quietly when the server reports the picker was cancelled", async () => {
  global.fetch = async () => ({ ok: true, json: async () => ({ cancelled: true }) });
  await assert.doesNotReject(() => chooseRunnerCsv());
});

test("chooseRunnerCsv: still throws for a real selection failure", async () => {
  global.fetch = async () => ({ ok: false, json: async () => ({ error: "boom" }) });
  await assert.rejects(() => chooseRunnerCsv(), /boom/);
});

test("chooseRunnerOutputFolder: resolves quietly when the server reports the picker was cancelled", async () => {
  global.fetch = async () => ({ ok: true, json: async () => ({ cancelled: true }) });
  await assert.doesNotReject(() => chooseRunnerOutputFolder());
});

test("chooseRunnerOutputFolder: still throws for a real selection failure", async () => {
  global.fetch = async () => ({ ok: false, json: async () => ({ error: "boom" }) });
  await assert.rejects(() => chooseRunnerOutputFolder(), /boom/);
});

// Batch 2 "free wins" (ROADMAP §Release 1 tracked checklist) — elapsedMs,
// requestName and step/stepTotal are emitted by run_orchestrator.py and
// persisted, but the row never rendered them.
// FAIL (not OK) so the §5.4 second line — where step/iteration live — isn't
// dropped by the "passing rows drop the second line entirely" design rule.
test("appendRunnerRow: renders requestName, step/stepTotal and elapsedMs", () => {
  const row = appendRunnerRow({
    iteration: 3, step: 2, stepTotal: 5, requestName: "Approve",
    url: "http://x/loans/9", status: "FAIL", httpStatus: 422, elapsedMs: 234,
    testsPassed: 1, testsTotal: 1, capturedVars: {}, attempts: 1,
  });
  assert.match(row.innerHTML, /Approve/);
  assert.match(row.innerHTML, /2\/5/);
  assert.match(row.innerHTML, /234\s*ms/);
});

// ROADMAP: "the Console already renders [warnings], so follow that
// treatment" — Console prefixes each warning with a ⚠ and status-fail class.
test("appendRunnerRow: surfaces warnings the same way the Console does", () => {
  const row = appendRunnerRow({
    iteration: 1, step: 1, stepTotal: 1, requestName: "Create",
    url: "http://x/loans", status: "OK", httpStatus: 200, elapsedMs: 10,
    testsPassed: 0, testsTotal: 0, capturedVars: {}, attempts: 1,
    warnings: ["multipart/form-data body not supported — sent as-is"],
  });
  assert.match(row.innerHTML, /status-fail/);
  assert.match(row.innerHTML, /multipart\/form-data body not supported/);
});

// §5.4: "Passing rows drop the second line entirely and are half the
// height" — an OK row with no warnings/error must not show iteration/step.
test("appendRunnerRow: a passing row with nothing to say drops the second line", () => {
  const row = appendRunnerRow({
    iteration: 1, step: 1, stepTotal: 1, requestName: "Create",
    url: "http://x/loans", status: "OK", httpStatus: 200, elapsedMs: 10,
    testsPassed: 1, testsTotal: 1, capturedVars: {}, attempts: 1,
  });
  assert.doesNotMatch(row.innerHTML, /class="l2"/);
});

// A row that eventually passed after burning retries must still show that
// it retried — §5.4's "nothing to say" exemption is for a clean first-try
// pass, not for one that silently used up its retry budget before passing.
test("appendRunnerRow: a passing row that needed retries still shows the attempt count", () => {
  const row = appendRunnerRow({
    iteration: 1, step: 1, stepTotal: 1, requestName: "Create",
    url: "http://x/loans", status: "OK", httpStatus: 200, elapsedMs: 10,
    testsPassed: 1, testsTotal: 1, capturedVars: {}, attempt: 3, attempts: 4,
  });
  assert.match(row.innerHTML, /class="l2"/);
  assert.match(row.innerHTML, /attempt 3\/4/);
});

// The aggregate row alone was the whole complaint: a user can't tell "3
// retried" apart from a display bug without seeing each real try land as
// it happens. appendRunnerAttemptRow is that live, per-attempt evidence —
// distinct from the final appendRunnerRow summary, not a replacement for it.
test("appendRunnerAttemptRow: renders one visible row per real attempt, marking whether it will retry", () => {
  const willRetryRow = appendRunnerAttemptRow({
    requestName: "GET all Modified Loan Accounts", method: "GET",
    attempt: 1, attempts: 4, httpStatus: null, error: "NameResolutionError", willRetry: true,
  });
  assert.match(willRetryRow.innerHTML, /attempt 1\/4/);
  assert.match(willRetryRow.innerHTML, /retrying/);
  assert.match(willRetryRow.className, /row-attempt/);

  const finalRow = appendRunnerAttemptRow({
    requestName: "GET all Modified Loan Accounts", method: "GET",
    attempt: 4, attempts: 4, httpStatus: null, error: "NameResolutionError", willRetry: false,
  });
  assert.match(finalRow.innerHTML, /attempt 4\/4/);
  assert.doesNotMatch(finalRow.innerHTML, /retrying/);
});
