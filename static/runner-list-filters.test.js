const test = require("node:test");
const assert = require("node:assert/strict");

global.document = { addEventListener: () => {} };
const { rowMatchesRunnerListFilters } = require("./runner-list-filters.js");

function fakeRow({ status, requestName, search }) {
  return { dataset: { status, requestName, search } };
}

test("rowMatchesRunnerListFilters: failuresOnly hides OK rows", () => {
  const row = fakeRow({ status: "OK", requestName: "A", search: "a" });
  assert.equal(rowMatchesRunnerListFilters(row, { failuresOnly: true, requestName: "", query: "" }), false);
});

test("rowMatchesRunnerListFilters: failuresOnly keeps FAIL/FLAGGED/ERROR rows", () => {
  for (const status of ["FAIL", "FLAGGED", "ERROR"]) {
    const row = fakeRow({ status, requestName: "A", search: "a" });
    assert.equal(rowMatchesRunnerListFilters(row, { failuresOnly: true, requestName: "", query: "" }), true);
  }
});

test("rowMatchesRunnerListFilters: requestName filter is an exact match", () => {
  const row = fakeRow({ status: "OK", requestName: "Approve loan", search: "approve loan" });
  assert.equal(rowMatchesRunnerListFilters(row, { failuresOnly: false, requestName: "Create loan", query: "" }), false);
  assert.equal(rowMatchesRunnerListFilters(row, { failuresOnly: false, requestName: "Approve loan", query: "" }), true);
});

test("rowMatchesRunnerListFilters: text query matches against the row's precomputed search string", () => {
  const row = fakeRow({ status: "OK", requestName: "A", search: "approve loan https://x/loans/9 422" });
  assert.equal(rowMatchesRunnerListFilters(row, { failuresOnly: false, requestName: "", query: "422" }), true);
  assert.equal(rowMatchesRunnerListFilters(row, { failuresOnly: false, requestName: "", query: "999" }), false);
});
