const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
global.getRequestTimeoutSeconds = () => 120;
global.getProxySettings = () => ({ host: "proxy.example.com", port: 8080 });
global.getInsecureMode = () => true;

let capturedPostJsonBody = null;
global.postJson = async (url, body) => {
  if (url === "/api/send-one") {
    capturedPostJsonBody = body;
  }
  return { status: 200, body: "" };
};

global.$ = (id) => {
  const fakeEl = { classList: { toggle: () => {}, contains: () => false, remove: () => {}, add: () => {} }, textContent: "", innerHTML: "" };
  return fakeEl;
};
global.consoleState = { selectedCollectionSlug: "test-slug" };
global.activeTab = () => null;
global.activeEnvironmentSlug = () => "dev";
global.authPayloadFields = () => ({});
global.currentConsoleRequest = () => ({ name: "test" });
global.setBusy = () => {};
global.renderLineNumbered = () => {};
global.highlightJson = (s) => s;
global.formatSize = (s) => `${s}B`;
global.renderSingleTestResults = () => {};
global.renderSingleResponse = () => {};

const { shouldRenderSendResult, setSendPending, sendConsoleRequest } = require("./send.js");

function fakeElement() {
  const classes = new Set();
  return { classList: { toggle: (name, force) => classes[force ? "add" : "delete"](name), contains: (name) => classes.has(name) } };
}

test("shouldRenderSendResult: renders when the same tab is still active", () => {
  assert.equal(shouldRenderSendResult(5, { id: 5 }), true);
});

test("shouldRenderSendResult: bails when a different tab became active", () => {
  assert.equal(shouldRenderSendResult(5, { id: 7 }), false);
});

test("shouldRenderSendResult: bails when the tab was closed while in flight", () => {
  assert.equal(shouldRenderSendResult(5, null), false);
});

test("shouldRenderSendResult: renders when there was no tab before and still isn't one — the actual bug this guards against regressing", () => {
  assert.equal(shouldRenderSendResult(null, null), true);
});

test("shouldRenderSendResult: bails when a tab-less send is overtaken by a newly created tab", () => {
  assert.equal(shouldRenderSendResult(null, { id: 1 }), false);
});

test("setSendPending: adds the pending class", () => {
  const el = fakeElement();
  setSendPending(el, true);
  assert.equal(el.classList.contains("pending"), true);
});

test("setSendPending: removes the pending class", () => {
  const el = fakeElement();
  setSendPending(el, true);
  setSendPending(el, false);
  assert.equal(el.classList.contains("pending"), false);
});

test("send: payload includes proxySettings and insecure from settings modules", async () => {
  await sendConsoleRequest();
  assert.deepEqual(capturedPostJsonBody.proxySettings, getProxySettings());
  assert.equal(capturedPostJsonBody.insecure, getInsecureMode());
});

// Cmd+Enter/the Send button must not fire a real request off whatever stale
// values are sitting in the hidden request-form DOM while an Overview tab
// (collection documentation, not a request) is active — this app never
// sends without the user having a real request tab open.
test("send: does nothing when the active tab is an overview tab, not a request", async () => {
  const originalActiveTab = global.activeTab;
  global.activeTab = () => ({ kind: "overview" });
  capturedPostJsonBody = null;
  try {
    await sendConsoleRequest();
  } finally {
    global.activeTab = originalActiveTab;
  }
  assert.equal(capturedPostJsonBody, null);
});
