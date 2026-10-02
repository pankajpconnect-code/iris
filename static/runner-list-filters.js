/* Runner result-list filter bar (ROADMAP §5.4 filter row) — text filter,
 * per-request-name filter, Failures only, Compact density, and the
 * "N of M results" / all-passed / no-match empty states. Split out of
 * runner-view.js (500-line limit) — depends on runnerState (declared there)
 * only indirectly, via the DOM (#runnerListBody's .row children), so it has
 * no direct coupling to it.
 */

let runnerListRequestNames = new Set();
let runnerListFilterState = { query: "", requestName: "", failuresOnly: false };

function resetRunnerListFilters() {
  runnerListRequestNames = new Set();
  runnerListFilterState = { query: "", requestName: "", failuresOnly: false };
  $("runnerFilterInput").value = "";
  $("runnerFilterRequestSelect").innerHTML = '<option value="">All requests</option>';
  $("runnerFailuresOnlyBtn").classList.remove("on");
  $("runnerCompactBtn").classList.remove("on");
  document.body.classList.remove("runner-compact");
  updateRunnerListResultCount();
}

function registerRunnerListRequestName(name) {
  if (!name || runnerListRequestNames.has(name)) return;
  runnerListRequestNames.add(name);
  const option = document.createElement("option");
  option.value = name;
  option.textContent = name;
  $("runnerFilterRequestSelect").appendChild(option);
}

// Pure so it's testable without a DOM — state is passed in rather than read
// from module-level runnerListFilterState directly.
function rowMatchesRunnerListFilters(row, state) {
  if (state.failuresOnly && row.dataset.status === "OK") return false;
  if (state.requestName && row.dataset.requestName !== state.requestName) return false;
  if (state.query && !row.dataset.search.includes(state.query)) return false;
  return true;
}

function applyRunnerListFilterToRow(row) {
  row.classList.toggle("hidden", !rowMatchesRunnerListFilters(row, runnerListFilterState));
  updateRunnerListResultCount();
}

function applyRunnerListFilters() {
  for (const row of $("runnerListBody").querySelectorAll(".row")) {
    row.classList.toggle("hidden", !rowMatchesRunnerListFilters(row, runnerListFilterState));
  }
  updateRunnerListResultCount();
}

// §5.4 states: "All-passed: an explicit 'All N results passed' rather than
// an empty list" — distinct from the plain "no matches" case, which fires
// whenever a filter (not just Failures only) hides everything.
function updateRunnerListEmptyState(total, visible) {
  const empty = $("runnerListEmpty");
  if (visible > 0) {
    empty.classList.add("hidden");
    return;
  }
  if (total === 0) {
    empty.classList.add("hidden"); // nothing has run yet — no message needed
    return;
  }
  const allPassed = runnerListFilterState.failuresOnly
    && ![...$("runnerListBody").querySelectorAll(".row")].some((r) => r.dataset.status !== "OK");
  empty.textContent = allPassed ? `All ${total} result(s) passed.` : "No results match this filter.";
  empty.classList.remove("hidden");
}

function updateRunnerListResultCount() {
  const rows = [...$("runnerListBody").querySelectorAll(".row")];
  const visible = rows.filter((r) => !r.classList.contains("hidden")).length;
  $("runnerResultCount").textContent = rows.length ? `${visible} of ${rows.length} results` : "";
  updateRunnerListEmptyState(rows.length, visible);
}

document.addEventListener("DOMContentLoaded", () => {
  $("runnerFilterInput").addEventListener("input", (event) => {
    runnerListFilterState.query = event.target.value.trim().toLowerCase();
    applyRunnerListFilters();
  });
  $("runnerFilterRequestSelect").addEventListener("change", (event) => {
    runnerListFilterState.requestName = event.target.value;
    applyRunnerListFilters();
  });
  $("runnerFailuresOnlyBtn").addEventListener("click", () => {
    runnerListFilterState.failuresOnly = !runnerListFilterState.failuresOnly;
    $("runnerFailuresOnlyBtn").classList.toggle("on", runnerListFilterState.failuresOnly);
    applyRunnerListFilters();
  });
  $("runnerCompactBtn").addEventListener("click", () => {
    const compact = document.body.classList.toggle("runner-compact");
    $("runnerCompactBtn").classList.toggle("on", compact);
  });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { rowMatchesRunnerListFilters };
}
