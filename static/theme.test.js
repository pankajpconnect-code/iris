const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
const { resolveInitialTheme } = require("./theme.js");

test("resolveInitialTheme: an explicit stored choice wins over the OS preference", () => {
  assert.equal(resolveInitialTheme("light", false), "light");
  assert.equal(resolveInitialTheme("dark", true), "dark");
});

test("resolveInitialTheme: no stored choice follows the OS light preference", () => {
  assert.equal(resolveInitialTheme(null, true), "light");
});

test("resolveInitialTheme: no stored choice follows the OS dark preference", () => {
  assert.equal(resolveInitialTheme(null, false), "dark");
});

test("resolveInitialTheme: a corrupted stored value falls back to the OS preference", () => {
  assert.equal(resolveInitialTheme("neon", true), "light");
});
