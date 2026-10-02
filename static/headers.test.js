const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
const { headersToBulkText, bulkTextToHeaders } = require("./headers.js");

test("headersToBulkText: one 'key: value' per line, skips rows with no key", () => {
  const text = headersToBulkText([
    { key: "Content-Type", value: "application/json", enabled: true },
    { key: "", value: "dropped", enabled: true },
    { key: "X-Disabled", value: "x", enabled: false },
  ]);
  assert.equal(text, "Content-Type: application/json\n// X-Disabled: x");
});

test("bulkTextToHeaders: parses 'key: value' lines and '// ' disabled prefix", () => {
  const headers = bulkTextToHeaders("Content-Type: application/json\n// X-Disabled: x\n\n  \n");
  assert.deepEqual(headers, [
    { key: "Content-Type", value: "application/json", enabled: true },
    { key: "X-Disabled", value: "x", enabled: false },
  ]);
});

test("bulkTextToHeaders: a line with no colon becomes key with empty value", () => {
  assert.deepEqual(bulkTextToHeaders("justakey"), [{ key: "justakey", value: "", enabled: true }]);
});

test("headersToBulkText -> bulkTextToHeaders round-trips enabled rows", () => {
  const original = [
    { key: "Authorization", value: "Bearer {{token}}", enabled: true },
    { key: "Accept", value: "application/json", enabled: true },
  ];
  assert.deepEqual(bulkTextToHeaders(headersToBulkText(original)), original);
});
