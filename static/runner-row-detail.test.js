const test = require("node:test");
const assert = require("node:assert/strict");

global.escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
}[c]));
global.highlightJson = (text) => escapeHtml(text); // real highlighter lives in body-editor.js; identity here is enough to test structure
global.document = { addEventListener: () => {} };

const {
  buildRunnerResponseHtml, buildRunnerRequestText, buildRunnerTestsHtml, headersArrayToObject,
} = require("./runner-row-detail.js");

test("buildRunnerResponseHtml: pretty-prints and highlights a JSON responseSnippet", () => {
  const { html, isJson } = buildRunnerResponseHtml({ responseSnippet: '{"loanId":"9"}' });
  assert.equal(isJson, true);
  assert.match(html, /loanId/);
});

test("buildRunnerResponseHtml: falls back to the raw snippet when it isn't JSON", () => {
  const { html, isJson } = buildRunnerResponseHtml({ responseSnippet: "not json" });
  assert.equal(isJson, false);
  assert.match(html, /not json/);
});

test("buildRunnerResponseHtml: an ERROR row with no response explains why, instead of showing an empty pane", () => {
  const { html } = buildRunnerResponseHtml({ status: "ERROR", error: "connection reset by peer", responseSnippet: null });
  assert.match(html, /connection reset by peer/);
});

// A secret-named capture blanks responseSnippet server-side (run_orchestrator
// _has_secret_capture) — the detail pane must say why, not look broken.
test("buildRunnerResponseHtml: a redacted-for-secrets OK row explains the blank body", () => {
  const { html } = buildRunnerResponseHtml({ status: "OK", responseSnippet: null });
  assert.match(html, /redacted/i);
});

test("buildRunnerRequestText: method + resolved URL", () => {
  assert.equal(buildRunnerRequestText({ method: "POST", url: "http://x/loans/9/approve" }), "POST http://x/loans/9/approve");
});

test("buildRunnerTestsHtml: renders warnings the same way the Console does, ahead of assertion rows", () => {
  const html = buildRunnerTestsHtml(
    [{ type: "assert", source: "body", path: "state", operator: "equals", expected: "ACTIVE", actual: "PENDING", passed: false }],
    ["multipart/form-data body not supported — sent as-is"],
  );
  assert.match(html, /status-fail.*multipart\/form-data/);
  assert.match(html, /status-fail/);
});

test("buildRunnerTestsHtml: a capture row shows the captured value", () => {
  const html = buildRunnerTestsHtml([{ type: "capture", variable: "loanId", actual: "9", passed: true }], []);
  assert.match(html, /loanId/);
  assert.match(html, /9/);
});

// A stored request's headers are an array of {key, value, enabled} rows
// (headers.js's collectAllHeaders shape), not the plain object
// buildRunnerHeadersHtml expects (it mirrors a real HTTP response's headers).
// Previewing an un-run request's headers needs this conversion, which didn't
// exist anywhere in the codebase before.
test("headersArrayToObject: keeps only enabled, keyed rows and drops the enabled flag", () => {
  const headers = [
    { key: "Authorization", value: "{{token}}", enabled: true },
    { key: "X-Off", value: "nope", enabled: false },
    { key: "", value: "no-key", enabled: true },
  ];
  assert.deepEqual(headersArrayToObject(headers), { Authorization: "{{token}}" });
});

// Headers saved before the "enabled" flag existed have no such property at
// all — sidebar.js's requestToCurl() treats that as enabled (`!== false`),
// and this must match that convention.
test("headersArrayToObject: a missing enabled flag counts as enabled", () => {
  assert.deepEqual(headersArrayToObject([{ key: "Content-Type", value: "application/json" }]), { "Content-Type": "application/json" });
});

test("headersArrayToObject: no headers at all yields an empty object", () => {
  assert.deepEqual(headersArrayToObject(undefined), {});
});
