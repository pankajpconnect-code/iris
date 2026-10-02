const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
global.consoleState = { vars: {}, selectedCollection: null };
global.SECRET_NAME_PATTERN = /token|secret|password|cookie/i;
// highlightVarTokens is body-editor.js's; escapeHtml is shared.js's global,
// mirrored here the same way body-editor.test.js already does (shared.js
// itself isn't require()-able — it touches document.body at load time).
global.escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
global.highlightVarTokens = require("./body-editor.js").highlightVarTokens;

const { varValueLabel, renderVarHighlight } = require("./autocomplete.js");

test("varValueLabel: resolves a known var to its current value", () => {
  global.consoleState = { vars: { id: "54094" }, selectedCollection: null };
  assert.equal(varValueLabel("id"), "id = 54094");
});

test("varValueLabel: marks an unknown var as not set", () => {
  global.consoleState = { vars: {}, selectedCollection: null };
  assert.equal(varValueLabel("missing"), "missing = (not set)");
});

test("varValueLabel: masks a secret-named var instead of revealing it on hover", () => {
  global.consoleState = { vars: { authToken: "eyJhbGciOiJIUzI1NiJ9.real.secret" }, selectedCollection: null };
  assert.equal(varValueLabel("authToken"), "authToken = ••••••");
});

test("varValueLabel: truncates a long value the same way the autocomplete dropdown does", () => {
  global.consoleState = { vars: { id: "x".repeat(50) }, selectedCollection: null };
  assert.equal(varValueLabel("id"), `id = ${"x".repeat(30)}…`);
});

test("varValueLabel: prefers the active environment's value over a console var of the same name", (t) => {
  global.consoleState = { vars: { url: "console-value" }, selectedCollection: null };
  global.activeEnvironmentVars = () => ({ url: "https://api.example.com" });
  t.after(() => { delete global.activeEnvironmentVars; });
  assert.equal(varValueLabel("url"), "url = https://api.example.com");
});

test("renderVarHighlight: wraps {{var}} tokens in the overlay, mirroring the input's scroll position", () => {
  const el = { value: "{{url}}/x", scrollLeft: 12 };
  const overlay = { innerHTML: "", scrollLeft: 0 };
  renderVarHighlight(el, overlay);
  assert.equal(overlay.innerHTML, '<span class="body-var-token">{{url}}</span>/x');
  assert.equal(overlay.scrollLeft, 12);
});

test("renderVarHighlight: renders empty text as an empty overlay (the blank-URL-bar regression)", () => {
  const el = { value: "", scrollLeft: 0 };
  const overlay = { innerHTML: "should be cleared", scrollLeft: 0 };
  renderVarHighlight(el, overlay);
  assert.equal(overlay.innerHTML, "");
});
