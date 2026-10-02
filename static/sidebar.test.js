const test = require("node:test");
const assert = require("node:assert/strict");

// sidebar.js calls document.addEventListener at load time (DOMContentLoaded
// wiring) — stub it like body-editor.test.js does, rather than pulling in
// jsdom just to require() the module.
global.document = { addEventListener: () => {}, querySelector: () => null };

const { shouldForceSearchOpen, shouldOpenOverviewTab } = require("./sidebar.js");

test("shouldForceSearchOpen: forces open a matching collection while searching", () => {
  assert.equal(shouldForceSearchOpen("token", true, "lending", null), true);
});

test("shouldForceSearchOpen: no active search means no force-open", () => {
  assert.equal(shouldForceSearchOpen("", true, "lending", null), false);
});

test("shouldForceSearchOpen: no visible match means no force-open", () => {
  assert.equal(shouldForceSearchOpen("token", false, "lending", null), false);
});

test("shouldForceSearchOpen: a collection the user just manually toggled is not forced back open", () => {
  assert.equal(shouldForceSearchOpen("token", true, "lending", "lending"), false);
});

test("shouldForceSearchOpen: the manual-toggle suppression is scoped to that one collection", () => {
  assert.equal(shouldForceSearchOpen("token", true, "other-collection", "lending"), true);
});

test("shouldOpenOverviewTab: true when the collection has a description", () => {
  assert.equal(shouldOpenOverviewTab({ slug: "widgets", description: "notes" }), true);
});

test("shouldOpenOverviewTab: false when the collection has no description", () => {
  assert.equal(shouldOpenOverviewTab({ slug: "widgets" }), false);
});

test("shouldOpenOverviewTab: false when the collection has an empty-string description", () => {
  assert.equal(shouldOpenOverviewTab({ slug: "widgets", description: "" }), false);
});

test("shouldOpenOverviewTab: false when there is no collection at all (e.g. import lookup came up empty)", () => {
  assert.equal(shouldOpenOverviewTab(undefined), false);
});

