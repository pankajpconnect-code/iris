const test = require("node:test");
const assert = require("node:assert/strict");

global.escapeHtml = (s) => String(s);
global.escapeAttr = (s) => String(s);
global.isAuthKey = (name) => name.startsWith("__auth");
global.requestVarNames = (request) => new Set(request.varNames || []);

// Minimal fake DOM: renderConsoleVars only ever touches $()-returned
// elements' .textContent/.classList, and treats document.createElement("tr")
// as an opaque row it can appendChild — same pattern as request-auth.test.js's
// makeFakeDom, since real DOM parsing of innerHTML isn't needed to prove the
// secret-masking/missing-var logic renders correctly.
function makeFakeDom() {
  const elements = new Map();
  const makeElement = () => ({
    value: "",
    textContent: "",
    innerHTML: "",
    children: [],
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    appendChild(el) { this.children.push(el); },
  });
  return (id) => {
    if (!elements.has(id)) elements.set(id, makeElement());
    return elements.get(id);
  };
}

global.document = {
  addEventListener: () => {},
  createElement: () => ({
    innerHTML: "",
    querySelector: () => ({ addEventListener: () => {} }),
  }),
};

const { renderConsoleVars, SECRET_NAME_PATTERN } = require("./console-vars.js");

test("SECRET_NAME_PATTERN: matches token/secret/password/cookie names case-insensitively", () => {
  ["apiToken", "clientSecret", "myPassword", "sessionCookie"].forEach((name) => {
    assert.equal(SECRET_NAME_PATTERN.test(name), true, `expected ${name} to match`);
  });
});

test("SECRET_NAME_PATTERN: does not match an ordinary variable name", () => {
  assert.equal(SECRET_NAME_PATTERN.test("environment"), false);
  assert.equal(SECRET_NAME_PATTERN.test("baseUrl"), false);
});

test("renderConsoleVars: masks a secret-named var as password and labels it 'session only'", () => {
  global.$ = makeFakeDom();
  global.consoleState = { vars: { apiToken: "s3cret" }, selectedRequest: { varNames: [] } };
  renderConsoleVars();
  const row = global.$("varsBody").children[0];
  assert.match(row.innerHTML, /type="password"/);
  assert.match(row.innerHTML, /session only/);
  delete global.consoleState;
  delete global.$;
});

test("renderConsoleVars: renders a plain var as a text input with no secret label", () => {
  global.$ = makeFakeDom();
  global.consoleState = { vars: { baseUrl: "https://example.com" }, selectedRequest: { varNames: [] } };
  renderConsoleVars();
  const row = global.$("varsBody").children[0];
  assert.match(row.innerHTML, /type="text"/);
  assert.doesNotMatch(row.innerHTML, /session only/);
  delete global.consoleState;
  delete global.$;
});

test("renderConsoleVars: filters out auth-tab keys (__auth-prefixed) from the Vars table", () => {
  global.$ = makeFakeDom();
  global.consoleState = {
    vars: { __authMode: "bearer", plainVar: "x" },
    selectedRequest: { varNames: [] },
  };
  renderConsoleVars();
  const body = global.$("varsBody");
  assert.equal(body.children.length, 1);
  assert.equal(global.$("tabVarCount").textContent, 1);
  delete global.consoleState;
  delete global.$;
});

test("renderConsoleVars: shows the missing-variable warning when a referenced var has no value anywhere", () => {
  global.$ = makeFakeDom();
  global.consoleState = { vars: {}, selectedRequest: { varNames: ["token"] } };
  const calls = [];
  const warning = global.$("varsWarning");
  warning.classList.remove = (cls) => calls.push(["remove", cls]);
  warning.classList.add = (cls) => calls.push(["add", cls]);
  renderConsoleVars();
  assert.match(warning.textContent, /1 variable\(s\) need a value.*token/);
  assert.deepEqual(calls, [["remove", "hidden"]]);
  delete global.consoleState;
  delete global.$;
});

test("renderConsoleVars: hides the missing-variable warning when every referenced var has a value", () => {
  global.$ = makeFakeDom();
  global.consoleState = { vars: { token: "abc" }, selectedRequest: { varNames: ["token"] } };
  const calls = [];
  const warning = global.$("varsWarning");
  warning.classList.remove = (cls) => calls.push(["remove", cls]);
  warning.classList.add = (cls) => calls.push(["add", cls]);
  renderConsoleVars();
  assert.deepEqual(calls, [["add", "hidden"]]);
  delete global.consoleState;
  delete global.$;
});
