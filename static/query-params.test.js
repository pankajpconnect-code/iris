const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
const {
  escapeParamDelims, unescapeParamDelims, parseQueryString, paramsFromUrl,
  serializeQueryString, urlWithParams, paramsToBulkText, bulkTextToParams,
} = require("./query-params.js");

test("escapeParamDelims: escapes & and = only", () => {
  assert.equal(escapeParamDelims("a&b=c"), "a%26b%3Dc");
  assert.equal(escapeParamDelims("{{var}} plain text"), "{{var}} plain text");
});

test("unescapeParamDelims: inverse of escapeParamDelims, case-insensitive", () => {
  assert.equal(unescapeParamDelims("a%26b%3Dc"), "a&b=c");
  assert.equal(unescapeParamDelims("a%3dc"), "a=c");
});

test("escapeParamDelims/unescapeParamDelims: also escapes a literal ~ so it can't collide with the disabled-row marker", () => {
  assert.equal(escapeParamDelims("~legit"), "%7Elegit");
  assert.equal(unescapeParamDelims("%7Elegit"), "~legit");
  assert.equal(unescapeParamDelims("%7elegit"), "~legit");
});

test("parseQueryString: a real key starting with ~ is NOT treated as disabled once escaped on the wire", () => {
  // %7Elegit is what serializeQueryString produces for an enabled row whose
  // real key is "~legit" — parsing it back must not misread it as the
  // disabled marker (a literal, unescaped leading "~").
  assert.deepEqual(parseQueryString("%7Elegit=1"), [{ key: "~legit", value: "1", enabled: true }]);
});

test("serializeQueryString: escapes a literal leading ~ in a key so it can't be mistaken for the disabled marker", () => {
  assert.equal(serializeQueryString([{ key: "~legit", value: "1", enabled: true }]), "%7Elegit=1");
});

test("parseQueryString: empty query is no params", () => {
  assert.deepEqual(parseQueryString(""), []);
});

test("parseQueryString: parses multiple enabled params in order", () => {
  assert.deepEqual(parseQueryString("a=1&b=2"), [
    { key: "a", value: "1", enabled: true },
    { key: "b", value: "2", enabled: true },
  ]);
});

test("parseQueryString: a ~-prefixed key is disabled and stripped for display", () => {
  assert.deepEqual(parseQueryString("a=1&~b=2"), [
    { key: "a", value: "1", enabled: true },
    { key: "b", value: "2", enabled: false },
  ]);
});

test("parseQueryString: a valueless param gets an empty value", () => {
  assert.deepEqual(parseQueryString("flag"), [{ key: "flag", value: "", enabled: true }]);
});

test("parseQueryString: %26/%3D in a value decode to literal & and =", () => {
  assert.deepEqual(parseQueryString("a=1%262%3D3"), [{ key: "a", value: "1&2=3", enabled: true }]);
});

test("parseQueryString: a {{var}} token in a value is left completely untouched", () => {
  assert.deepEqual(parseQueryString("id={{loanId}}"), [{ key: "id", value: "{{loanId}}", enabled: true }]);
});

test("paramsFromUrl: splits at the first ? and parses the remainder", () => {
  assert.deepEqual(paramsFromUrl("http://x/y?a=1"), [{ key: "a", value: "1", enabled: true }]);
  assert.deepEqual(paramsFromUrl("http://x/y"), []);
});

test("serializeQueryString: round-trips parseQueryString's output", () => {
  const params = [{ key: "a", value: "1", enabled: true }, { key: "b", value: "2", enabled: false }];
  assert.equal(serializeQueryString(params), "a=1&~b=2");
});

test("serializeQueryString: escapes a literal & or = typed into a value", () => {
  assert.equal(serializeQueryString([{ key: "a", value: "1&2=3", enabled: true }]), "a=1%262%3D3");
});

test("serializeQueryString: drops a row with an empty key", () => {
  assert.equal(serializeQueryString([{ key: "", value: "x", enabled: true }]), "");
});

test("urlWithParams: rebuilds the URL from the base plus params", () => {
  assert.equal(urlWithParams("http://x/y?a=1", [{ key: "a", value: "9", enabled: true }]), "http://x/y?a=9");
});

test("urlWithParams: drops the ? entirely when there are no params", () => {
  assert.equal(urlWithParams("http://x/y?a=1", []), "http://x/y");
});

test("paramsToBulkText/bulkTextToParams: round-trip, // disables a line", () => {
  const params = [{ key: "a", value: "1", enabled: true }, { key: "b", value: "2", enabled: false }];
  const text = paramsToBulkText(params);
  assert.equal(text, "a=1\n// b=2");
  assert.deepEqual(bulkTextToParams(text), params);
});

test("bulkTextToParams: drops an empty-key line", () => {
  assert.deepEqual(bulkTextToParams("=novalue\n"), []);
});
