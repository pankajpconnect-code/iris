const test = require("node:test");
const assert = require("node:assert/strict");

global.escapeAttr = (s) => String(s);

// addTestRow builds a row's <select>/<input> "selected"/"value" attributes
// from the `test` object it's given, and collectTests() reads them back via
// row.querySelector(".t-*").value — a real DOM isn't needed to prove that
// round-trip since the fake row's fields are seeded directly from the same
// `test` object addTestRow was called with, mirroring what a real <select>'s
// "selected" option would resolve to.
let nextTestSpec = {};
function makeRow() {
  const type = nextTestSpec.type || "assert";
  const subEls = {
    ".t-type": { value: type, addEventListener: () => {} },
    ".t-source": { value: nextTestSpec.source || "body", classList: { toggle: () => {} } },
    ".t-path": { value: nextTestSpec.path || "" },
    ".t-operator": { value: nextTestSpec.operator || "equals", classList: { toggle: () => {} } },
    ".t-expected": { value: nextTestSpec.expected || nextTestSpec.variable || "" },
    button: { addEventListener: () => {} },
  };
  return {
    className: "",
    dataset: {},
    innerHTML: "",
    querySelector: (sel) => subEls[sel],
  };
}

const rows = [];
global.$ = (id) => {
  if (id === "testsList") return { appendChild: (row) => rows.push(row), textContent: "" };
  return { textContent: "" };
};
global.document = {
  addEventListener: () => {},
  createElement: () => makeRow(),
  querySelectorAll: () => rows,
};

const { addTestRow, collectTests, TEST_OPERATORS } = require("./request-tests.js");

test.beforeEach(() => {
  rows.length = 0;
});

test("TEST_OPERATORS: covers every comparison operator the Tests tab offers", () => {
  assert.deepEqual(TEST_OPERATORS, [
    "equals", "notEquals", "exists", "notNull", "notEmpty", "contains", "matches", "gt", "gte", "lt", "lte",
  ]);
});

test("collectTests: an 'assert' row round-trips source/path/operator/expected", () => {
  nextTestSpec = { type: "assert", source: "status", path: "code", operator: "gte", expected: "200" };
  addTestRow(nextTestSpec);
  assert.deepEqual(collectTests(), [
    { type: "assert", source: "status", path: "code", operator: "gte", expected: "200" },
  ]);
});

test("collectTests: a 'capture' row round-trips source/path/variable, no operator/expected", () => {
  nextTestSpec = { type: "capture", source: "header", path: "X-Token", variable: "token" };
  addTestRow(nextTestSpec);
  assert.deepEqual(collectTests(), [
    { type: "capture", source: "header", path: "X-Token", variable: "token" },
  ]);
});

test("collectTests: a 'python' row round-trips only type/expected, no source/path/operator", () => {
  nextTestSpec = { type: "python", expected: "assert True" };
  addTestRow(nextTestSpec);
  assert.deepEqual(collectTests(), [{ type: "python", expected: "assert True" }]);
});

test("collectTests: defaults an untyped row to 'assert' with 'body' source and 'equals' operator", () => {
  nextTestSpec = {};
  addTestRow(nextTestSpec);
  assert.deepEqual(collectTests(), [
    { type: "assert", source: "body", path: "", operator: "equals", expected: "" },
  ]);
});

test("collectTests: reads multiple mixed-type rows in DOM order", () => {
  nextTestSpec = { type: "assert", source: "body", path: "ok", operator: "equals", expected: "true" };
  addTestRow(nextTestSpec);
  nextTestSpec = { type: "capture", source: "body", path: "id", variable: "newId" };
  addTestRow(nextTestSpec);
  assert.deepEqual(collectTests(), [
    { type: "assert", source: "body", path: "ok", operator: "equals", expected: "true" },
    { type: "capture", source: "body", path: "id", variable: "newId" },
  ]);
});
