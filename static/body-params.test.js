const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
const { bodyParamsToBulkText, bulkTextToBodyParams } = require("./body-params.js");

test("bodyParamsToBulkText: one 'key: value' per line, skips rows with no key", () => {
  const text = bodyParamsToBulkText([
    { key: "grant_type", value: "client_credentials", enabled: true },
    { key: "", value: "dropped", enabled: true },
    { key: "disabled_one", value: "x", enabled: false },
  ]);
  assert.equal(text, "grant_type: client_credentials\n// disabled_one: x");
});

test("bulkTextToBodyParams: parses 'key: value' lines and '// ' disabled prefix", () => {
  const params = bulkTextToBodyParams("grant_type: client_credentials\n// disabled_one: x\n\n  \n");
  assert.deepEqual(params, [
    { key: "grant_type", value: "client_credentials", enabled: true },
    { key: "disabled_one", value: "x", enabled: false },
  ]);
});

test("bulkTextToBodyParams: a line with no colon becomes key with empty value", () => {
  assert.deepEqual(bulkTextToBodyParams("justakey"), [{ key: "justakey", value: "", enabled: true }]);
});

test("bodyParamsToBulkText -> bulkTextToBodyParams round-trips enabled rows", () => {
  const original = [
    { key: "a", value: "1", enabled: true },
    { key: "b", value: "2", enabled: true },
  ];
  assert.deepEqual(bulkTextToBodyParams(bodyParamsToBulkText(original)), original);
});
