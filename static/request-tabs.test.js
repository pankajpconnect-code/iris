const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
// saveConsoleRequest/duplicateConsoleRequest's overview-tab guard is checked
// before any of their real dependencies run, so a minimal activeTab stub is
// enough — postJson staying uncalled is exactly what proves the guard fired.
global.activeTab = () => ({ kind: "overview" });
let postJsonCalled = false;
global.postJson = async () => { postJsonCalled = true; return {}; };
const {
  extractVarNames, requestVarNames, collectionVarNames,
  saveConsoleRequest, duplicateConsoleRequest,
} = require("./request-tabs.js");

test("extractVarNames: pulls every {{name}} token out of a string", () => {
  assert.deepEqual(extractVarNames("{{a}}/{{b}}/{{a}}"), new Set(["a", "b"]));
});

test("extractVarNames: empty set for no tokens or empty input", () => {
  assert.deepEqual(extractVarNames("plain text"), new Set());
  assert.deepEqual(extractVarNames(""), new Set());
  assert.deepEqual(extractVarNames(undefined), new Set());
});

test("requestVarNames: collects tokens from url, headers, body and bodyParams", () => {
  const request = {
    url: "https://api.example/{{host}}",
    headers: [{ value: "Bearer {{token}}" }],
    body: '{"id": "{{id}}"}',
    bodyParams: [{ value: "{{grant}}" }],
  };
  assert.deepEqual(requestVarNames(request), new Set(["host", "token", "id", "grant"]));
});

test("requestVarNames: tolerates missing headers/bodyParams", () => {
  assert.deepEqual(requestVarNames({ url: "{{only}}" }), new Set(["only"]));
});

test("collectionVarNames: unions var names across every request in the collection", () => {
  const collection = {
    requests: [
      { url: "{{a}}" },
      { url: "{{b}}", body: "{{a}}" },
    ],
  };
  assert.deepEqual(collectionVarNames(collection), new Set(["a", "b"]));
});

test("collectionVarNames: empty set when the collection has no requests", () => {
  assert.deepEqual(collectionVarNames({}), new Set());
  assert.deepEqual(collectionVarNames(null), new Set());
});

test("saveConsoleRequest: does nothing when the active tab is an overview tab, not a request", async () => {
  postJsonCalled = false;
  await saveConsoleRequest();
  assert.equal(postJsonCalled, false);
});

test("duplicateConsoleRequest: does nothing when the active tab is an overview tab, not a request", async () => {
  postJsonCalled = false;
  await duplicateConsoleRequest();
  assert.equal(postJsonCalled, false);
});
