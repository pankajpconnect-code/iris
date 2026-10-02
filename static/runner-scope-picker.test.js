const test = require("node:test");
const assert = require("node:assert/strict");

global.escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
}[c]));
global.escapeAttr = global.escapeHtml;
global.document = { addEventListener: () => {} };
global.consoleState = {
  collectionsCache: [
    {
      slug: "lending",
      name: "Lending",
      // Real Folder records (post-Phase-3b data model: {id, name,
      // parentFolderId} + folderId on requests) — request names are no
      // longer "/"-joined folder paths, so folder scope must resolve via
      // folderId, not a name-prefix string match.
      folders: [
        { id: "f-loans", name: "Loans" },
        { id: "f-loans-sub", name: "Disbursement", parentFolderId: "f-loans" },
        { id: "f-loans-legacy", name: "Loans Legacy" },
      ],
      requests: [
        { name: "Fee Accrual", method: "POST" },
        { name: "Get Loan", method: "GET", folderId: "f-loans" },
        { name: "Approve Loan", method: "PUT", folderId: "f-loans" },
        { name: "Disburse Loan", method: "POST", folderId: "f-loans-sub" },
        { name: "Old Get Loan", method: "GET", folderId: "f-loans-legacy" },
      ],
    },
  ],
};

const {
  requestsInScope, requestNamesInScope, buildRunnerScopeCheckRowHtml, buildRunnerScopeDropdownRequestRowHtml,
} = require("./runner-scope-picker.js");

// The "Requests in scope" checklist needs each request's method to render a
// badge (see folders.js's sidebar rows) — requestNamesInScope() alone throws
// that away, so the checklist has never been able to show it.
test("requestsInScope: returns full request objects, not just names, so callers can read .method", () => {
  const scope = { type: "collection", slug: "lending", name: null };
  const requests = requestsInScope(scope);
  assert.deepEqual(
    requests.map((r) => r.name),
    ["Fee Accrual", "Get Loan", "Approve Loan", "Disburse Loan", "Old Get Loan"],
  );
  assert.equal(requests[0].method, "POST");
});

test("requestsInScope: a folder scope includes requests from nested descendant folders", () => {
  const scope = { type: "folder", slug: "lending", name: "Loans" };
  const requests = requestsInScope(scope);
  assert.deepEqual(requests.map((r) => r.name), ["Get Loan", "Approve Loan", "Disburse Loan"]);
});

// Regression-safety property: a childless folder's closure is just itself,
// so a single-level (non-nested) folder scope behaves exactly as before.
test("requestsInScope: a childless folder scope matches only its own requests", () => {
  const scope = { type: "folder", slug: "lending", name: "Loans Legacy" };
  const requests = requestsInScope(scope);
  assert.deepEqual(requests.map((r) => r.name), ["Old Get Loan"]);
});

// Regression test for the bug the old name-prefix matching had: "Loans
// Legacy" is a sibling folder, not a descendant of "Loans" — its requests
// must never leak into the "Loans" scope just because the folder names
// happen to overlap.
test("requestsInScope: a folder scope does not leak into an unrelated folder sharing a name prefix", () => {
  const scope = { type: "folder", slug: "lending", name: "Loans" };
  const requests = requestsInScope(scope);
  assert.ok(!requests.some((r) => r.name === "Old Get Loan"));
});

test("requestsInScope: a request scope returns just that one request", () => {
  const scope = { type: "request", slug: "lending", name: "Fee Accrual" };
  const requests = requestsInScope(scope);
  assert.deepEqual(requests.map((r) => r.name), ["Fee Accrual"]);
});

// requestNamesInScope() is still used by the checkbox-toggle/exclusion logic
// throughout this file — it must keep returning bare names.
test("requestNamesInScope: unchanged behaviour, still returns bare names", () => {
  const scope = { type: "collection", slug: "lending", name: null };
  assert.deepEqual(
    requestNamesInScope(scope),
    ["Fee Accrual", "Get Loan", "Approve Loan", "Disburse Loan", "Old Get Loan"],
  );
});

// The checklist previously had no method badge at all (a bare checkbox +
// name) — this mirrors folders.js's sidebar row convention (`.m ${method}`
// badge class, "DEL" shorthand) so a request's method is visible here too.
test("buildRunnerScopeCheckRowHtml: renders a colored method badge and the request name", () => {
  const html = buildRunnerScopeCheckRowHtml({ name: "Fee Accrual", method: "POST" }, true);
  assert.match(html, /class="m POST"/);
  assert.match(html, />POST</);
  assert.match(html, />Fee Accrual</);
  assert.match(html, /checked/);
});

test("buildRunnerScopeCheckRowHtml: DELETE shortens to DEL, matching the sidebar convention", () => {
  const html = buildRunnerScopeCheckRowHtml({ name: "Undo Event", method: "DELETE" }, true);
  assert.match(html, /class="m DELETE"/);
  assert.match(html, />DEL</);
});

test("buildRunnerScopeCheckRowHtml: an excluded request renders its checkbox unchecked", () => {
  const html = buildRunnerScopeCheckRowHtml({ name: "Prepayment", method: "POST" }, false);
  assert.doesNotMatch(html, /checked/);
});

// Bug: clicking a row to preview it, then clicking "All"/"None" or any
// checkbox that triggers a full re-render (renderRunnerScopeSelectionSurfaces
// -> renderRunnerScopeChecklist -> innerHTML = requests.map(buildRunnerScope
// CheckRowHtml...)) rebuilt every row from scratch with no memory of which
// one was selected, so the highlight vanished while the Response-card pane
// kept showing that request's now-orphaned preview — reported as "the older
// request details are shown" after deselecting it and picking others.
test("buildRunnerScopeCheckRowHtml: marks the currently-previewed row selected so it survives a re-render", () => {
  const html = buildRunnerScopeCheckRowHtml({ name: "Prepayment", method: "POST" }, false, true);
  assert.match(html, /class="runner-scope-check-row sel"/);
});

test("buildRunnerScopeCheckRowHtml: not the previewed row means no sel class", () => {
  const html = buildRunnerScopeCheckRowHtml({ name: "Prepayment", method: "POST" }, false, false);
  assert.doesNotMatch(html, /\bsel\b/);
});

// Bug: the scope picker's own dropdown (the "Search a request, folder or
// collection…" combobox — the first, primary place a user picks requests)
// never got a method badge at all; only the secondary "Requests in scope"
// checklist below it did. A user opening just the dropdown (as most do)
// still saw a bare checkbox + name, no POST/GET/etc in front of it.
test("buildRunnerScopeDropdownRequestRowHtml: renders a method badge alongside the checkbox and collection name", () => {
  const entry = { label: "Fee Accrual", collectionName: "Lending", method: "POST", scope: { slug: "lending", name: "Fee Accrual" } };
  const html = buildRunnerScopeDropdownRequestRowHtml(entry, true);
  assert.match(html, /class="m POST"/);
  assert.match(html, />POST</);
  assert.match(html, />Fee Accrual</);
  assert.match(html, />Lending</);
  assert.match(html, /checked/);
});

test("buildRunnerScopeDropdownRequestRowHtml: DELETE shortens to DEL, matching the sidebar convention", () => {
  const entry = { label: "Undo Event", collectionName: "Lending", method: "DELETE", scope: { slug: "lending", name: "Undo Event" } };
  const html = buildRunnerScopeDropdownRequestRowHtml(entry, false);
  assert.match(html, /class="m DELETE"/);
  assert.match(html, />DEL</);
});
