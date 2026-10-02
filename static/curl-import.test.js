const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
const { parseCurlCommand } = require("./curl-import.js");

test("parseCurlCommand: plain GET with a quoted URL and no flags", () => {
  const result = parseCurlCommand("curl 'https://api.example.com/loans/1'");

  assert.equal(result.method, "GET");
  assert.equal(result.url, "https://api.example.com/loans/1");
  assert.deepEqual(result.headers, []);
  assert.equal(result.body, "");
});

test("parseCurlCommand: -X sets the method explicitly", () => {
  const result = parseCurlCommand("curl -X DELETE 'https://api.example.com/loans/1'");

  assert.equal(result.method, "DELETE");
});

test("parseCurlCommand: --request is the long-flag alias for -X", () => {
  const result = parseCurlCommand("curl --request PUT 'https://api.example.com/loans/1'");

  assert.equal(result.method, "PUT");
});

test("parseCurlCommand: -H headers are collected as key/value/enabled rows", () => {
  const result = parseCurlCommand(
    "curl 'https://api.example.com/loans/1' -H 'Authorization: Bearer abc' -H 'Accept: application/json'"
  );

  assert.deepEqual(result.headers, [
    { key: "Authorization", value: "Bearer abc", enabled: true },
    { key: "Accept", value: "application/json", enabled: true },
  ]);
});

test("parseCurlCommand: a header value containing a colon keeps everything after the first colon", () => {
  const result = parseCurlCommand("curl 'https://api.example.com' -H 'Referer: https://example.com/x'");

  assert.deepEqual(result.headers, [{ key: "Referer", value: "https://example.com/x", enabled: true }]);
});

test("parseCurlCommand: -d sets a raw JSON body and infers POST when no method was given", () => {
  const result = parseCurlCommand(
    "curl 'https://api.example.com/loans' -H 'Content-Type: application/json' -d '{\"amount\":100}'"
  );

  assert.equal(result.method, "POST");
  assert.equal(result.bodyMode, "raw");
  assert.equal(result.body, '{"amount":100}');
});

test("parseCurlCommand: an explicit -X is not overridden by -d's POST inference", () => {
  const result = parseCurlCommand("curl -X PATCH 'https://api.example.com/loans/1' -d '{\"amount\":50}'");

  assert.equal(result.method, "PATCH");
});

test("parseCurlCommand: --data-raw and --data-binary are accepted aliases for -d", () => {
  assert.equal(
    parseCurlCommand("curl 'https://api.example.com' --data-raw 'hello'").body,
    "hello"
  );
  assert.equal(
    parseCurlCommand("curl 'https://api.example.com' --data-binary 'hello'").body,
    "hello"
  );
});

test("parseCurlCommand: a urlencoded Content-Type switches body mode and splits the body into bodyParams", () => {
  const result = parseCurlCommand(
    "curl 'https://api.example.com' -H 'Content-Type: application/x-www-form-urlencoded' -d 'a=1&b=2'"
  );

  assert.equal(result.bodyMode, "urlencoded");
  assert.equal(result.body, "");
  assert.deepEqual(result.bodyParams, [
    { key: "a", value: "1", enabled: true },
    { key: "b", value: "2", enabled: true },
  ]);
});

test("parseCurlCommand: a urlencoded body value containing '=' (base64 padding) is not truncated", () => {
  const result = parseCurlCommand(
    "curl 'https://api.example.com' -H 'Content-Type: application/x-www-form-urlencoded' -d 'signature=YWJjZGVmZw=='"
  );

  assert.deepEqual(result.bodyParams, [{ key: "signature", value: "YWJjZGVmZw==", enabled: true }]);
});

test("parseCurlCommand: repeated -d flags concatenate with '&', matching real curl", () => {
  const result = parseCurlCommand("curl 'https://api.example.com' -d 'a=1' -d 'b=2'");

  assert.equal(result.body, "a=1&b=2");
});

test("parseCurlCommand: --data-urlencode URL-encodes the value half of name=value", () => {
  const result = parseCurlCommand("curl 'https://api.example.com' --data-urlencode 'q=a b&c'");

  assert.equal(result.body, "q=a%20b%26c");
});

test("parseCurlCommand: --form/-F and --cookie/-b are reported as unsupported instead of corrupting the URL", () => {
  const result = parseCurlCommand("curl -F 'file=@x.jpg' 'https://api.example.com/upload'");

  assert.equal(result.url, "https://api.example.com/upload");
  assert.deepEqual(result.unsupportedFlags, ["-F"]);
});

test("parseCurlCommand: -u/--user is translated into a Basic Authorization header", () => {
  const result = parseCurlCommand("curl 'https://api.example.com' -u 'pankaj:s3cret'");

  const expected = `Basic ${Buffer.from("pankaj:s3cret").toString("base64")}`;
  assert.deepEqual(result.headers, [{ key: "Authorization", value: expected, enabled: true }]);
});

test("parseCurlCommand: backslash line-continuations (multi-line curl paste) are handled", () => {
  const result = parseCurlCommand(
    "curl -X POST 'https://api.example.com/loans' \\\n  -H 'Content-Type: application/json' \\\n  -d '{}'"
  );

  assert.equal(result.method, "POST");
  assert.equal(result.url, "https://api.example.com/loans");
  assert.deepEqual(result.headers, [{ key: "Content-Type", value: "application/json", enabled: true }]);
});

test("parseCurlCommand: no-op flags (--compressed, -k, -L) are ignored without error", () => {
  const result = parseCurlCommand("curl -k -L --compressed 'https://api.example.com/loans/1'");

  assert.equal(result.url, "https://api.example.com/loans/1");
});

test("parseCurlCommand: input that doesn't start with curl is rejected", () => {
  assert.throws(() => parseCurlCommand("wget https://example.com"), /curl/i);
});

test("parseCurlCommand: a curl command with no URL is rejected", () => {
  assert.throws(() => parseCurlCommand("curl -X GET"), /url/i);
});

test("parseCurlCommand: blank input is rejected", () => {
  assert.throws(() => parseCurlCommand(""), /curl/i);
});
