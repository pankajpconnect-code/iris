const test = require("node:test");
const assert = require("node:assert/strict");

function fakeElement() {
  const classes = new Set();
  return {
    value: "", checked: false, textContent: "", innerHTML: "",
    classList: {
      toggle: (name, force) => { const on = force === undefined ? !classes.has(name) : force; classes[on ? "add" : "delete"](name); },
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

global.document = { addEventListener: () => {} };
// activateTab (called by openRequestTab) touches a wide surface of other
// modules' globals — stubbed here the same way send.test.js already stubs
// out its own dependencies. $("requestTabStrip") returns null so
// renderTabStrip's early-return skips the document.createElement calls this
// bare `document` stub can't serve. Elements are memoized by id (not a fresh
// object per call) so a hidden/toggle state set in one activateTab() call is
// still visible to assertions afterward, and to the NEXT activateTab() call.
const fakeElements = new Map();
global.$ = (id) => {
  if (id === "requestTabStrip") return null;
  if (!fakeElements.has(id)) fakeElements.set(id, fakeElement());
  return fakeElements.get(id);
};
global.currentUrlWithPendingParamEdits = () => "";
global.collectAllHeaders = () => [];
global.collectAllBodyParams = () => [];
global.collectTests = () => [];
global.renderBodyParamRows = () => {};
global.syncBodyModeVisibility = () => {};
global.renderHeaderRows = () => {};
global.renderParamsTabFromUrl = () => {};
global.renderTestRows = () => {};
global.resetSingleResponsePanel = () => {};
global.loadConsoleVars = () => {};
global.renderAuthTab = () => {};
global.updateTopbarPills = () => {};
global.renderCollectionTree = () => {};
global.consoleState = { collectionsCache: [], selectedRequest: null, selectedCollectionSlug: null, selectedCollection: null };
// renderMarkdownToHtml is normally a global from markdown.js (loaded before
// tabs.js in index.html) — stubbed here rather than requiring that unrelated
// module, same reasoning as every other global stub above.
global.renderMarkdownToHtml = (text) => text || "";

const { isDoubleTabClick, requestToDraft, openRequestTab, activateTab, openCollectionOverviewTab, markActiveTabSaved, tabState } = require("./tabs.js");

test("isDoubleTabClick: second click on the same tab within the threshold is a double-click", () => {
  assert.equal(isDoubleTabClick({ id: 3, time: 1000 }, 3, 1200), true);
});

test("isDoubleTabClick: second click on a different tab is not a double-click", () => {
  assert.equal(isDoubleTabClick({ id: 3, time: 1000 }, 7, 1200), false);
});

test("isDoubleTabClick: same tab but outside the threshold is not a double-click", () => {
  assert.equal(isDoubleTabClick({ id: 3, time: 1000 }, 3, 1600), false);
});

test("isDoubleTabClick: no prior click recorded is not a double-click", () => {
  assert.equal(isDoubleTabClick({ id: null, time: 0 }, 3, 100), false);
});

// A tab's draft feeds consoleState.selectedRequest verbatim (activateTab) —
// dropping a request's own `.auth` here silently breaks the Auth
// tab/Send fallback further downstream for every imported request, even
// though nothing downstream is "wrong" in isolation.
test("requestToDraft: carries the request's own auth through into the draft", () => {
  const draft = requestToDraft({ method: "GET", url: "https://x", auth: { mode: "bearer", bearerToken: "abc" } });
  assert.deepEqual(draft.auth, { mode: "bearer", bearerToken: "abc" });
});

test("requestToDraft: auth is undefined when the request has none of its own", () => {
  const draft = requestToDraft({ method: "GET", url: "https://x" });
  assert.equal(draft.auth, undefined);
});

// The live app bug this guards against: requestToDraft() gets `auth` into a
// tab's draft on its INITIAL open, but activateTab()'s own captureActiveDraft
// step (which runs on every subsequent switch, including switching to a
// second tab and back) used to rebuild that same tab's draft from scratch
// without `auth` — so the very first tab switch after opening a request
// silently erased its auth again, even though it looked fixed in isolation.
test("activateTab: a tab's own auth survives switching away to another tab and back", () => {
  openRequestTab("col", { name: "req-a", method: "GET", url: "https://a", auth: { mode: "bearer", bearerToken: "tok-a" } });
  const tabA = tabState.tabs.find((t) => t.requestName === "req-a");
  // Opening a second tab switches away from A, which is exactly the point
  // captureActiveDraft() recaptures A's (now-active-no-more) draft.
  openRequestTab("col", { name: "req-b", method: "GET", url: "https://b" });
  activateTab(tabA.id);
  assert.deepEqual(tabA.draft.auth, { mode: "bearer", bearerToken: "tok-a" });
  assert.deepEqual(consoleState.selectedRequest.auth, { mode: "bearer", bearerToken: "tok-a" });
});

test("openCollectionOverviewTab: opens a new tab carrying the collection's slug/name/description", () => {
  openCollectionOverviewTab({ slug: "widgets", name: "Widgets", description: "# Hello" });
  const tab = tabState.tabs.find((t) => t.kind === "overview" && t.collectionSlug === "widgets");
  assert.ok(tab);
  assert.equal(tab.collectionName, "Widgets");
  assert.equal(tab.description, "# Hello");
  assert.equal(tabState.activeId, tab.id);
});

test("openCollectionOverviewTab: calling it again for the same collection reuses the tab, no duplicate", () => {
  const before = tabState.tabs.filter((t) => t.kind === "overview" && t.collectionSlug === "widgets").length;
  openCollectionOverviewTab({ slug: "widgets", name: "Widgets", description: "# Hello" });
  const after = tabState.tabs.filter((t) => t.kind === "overview" && t.collectionSlug === "widgets").length;
  assert.equal(after, before);
});

test("openCollectionOverviewTab: reusing an existing tab refreshes its description instead of showing stale content", () => {
  openCollectionOverviewTab({ slug: "widgets", name: "Widgets", description: "# Old" });
  openCollectionOverviewTab({ slug: "widgets", name: "Widgets Renamed", description: "# New" });
  const tab = tabState.tabs.find((t) => t.kind === "overview" && t.collectionSlug === "widgets");
  assert.equal(tab.description, "# New");
  assert.equal(tab.collectionName, "Widgets Renamed");
});

test("activateTab: activating an overview tab clears selectedRequest rather than leaving a stale request selected", () => {
  openRequestTab("col", { name: "req-c", method: "GET", url: "https://c" });
  openCollectionOverviewTab({ slug: "widgets2", name: "Widgets2", description: "notes" });
  assert.equal(consoleState.selectedRequest, null);
  assert.equal(consoleState.selectedCollectionSlug, "widgets2");
});

test("activateTab: switching away from an overview tab never attaches a bogus .draft to it (captureActiveDraft skips overview tabs)", () => {
  openCollectionOverviewTab({ slug: "widgets3", name: "Widgets3", description: "notes" });
  const overviewTab = tabState.tabs.find((t) => t.collectionSlug === "widgets3");
  openRequestTab("col", { name: "req-d", method: "GET", url: "https://d" });
  assert.equal(overviewTab.draft, undefined);
});

// A hidden request form's stale contents shouldn't get saved as a new
// request onto whatever collection an open overview tab happens to belong
// to — Cmd+S while an overview tab is active must be a no-op, not a save.
test("markActiveTabSaved: does nothing when the active tab is an overview tab, not a request", () => {
  openCollectionOverviewTab({ slug: "widgets4", name: "Widgets4", description: "notes" });
  const overviewTab = tabState.tabs.find((t) => t.collectionSlug === "widgets4");
  markActiveTabSaved({ name: "should-not-apply", folderId: "f1" });
  assert.equal(overviewTab.requestName, undefined);
  assert.equal(overviewTab.folderId, undefined);
});

test("activateTab: switching overview -> request -> overview toggles which panes are hidden, both directions", () => {
  openCollectionOverviewTab({ slug: "widgets5", name: "Widgets5", description: "notes" });
  assert.equal($("requestUrlbar").classList.contains("hidden"), true);
  assert.equal($("requestSubTabs").classList.contains("hidden"), true);
  assert.equal($("requestEditor").classList.contains("hidden"), true);
  assert.equal($("respSingle").classList.contains("hidden"), true);
  assert.equal($("overviewPane").classList.contains("hidden"), false);

  openRequestTab("col", { name: "req-e", method: "GET", url: "https://e" });
  assert.equal($("requestUrlbar").classList.contains("hidden"), false);
  assert.equal($("requestSubTabs").classList.contains("hidden"), false);
  assert.equal($("requestEditor").classList.contains("hidden"), false);
  assert.equal($("overviewPane").classList.contains("hidden"), true);

  openCollectionOverviewTab({ slug: "widgets5", name: "Widgets5", description: "notes" });
  assert.equal($("requestUrlbar").classList.contains("hidden"), true);
  assert.equal($("overviewPane").classList.contains("hidden"), false);
});
