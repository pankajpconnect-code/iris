// Tests tab: assert/capture/python test rows attached to a request — split
// out of static/request-tabs.js to keep that file under this repo's
// 500-line cap.

const TEST_OPERATORS = ["equals", "notEquals", "exists", "notNull", "notEmpty", "contains", "matches", "gt", "gte", "lt", "lte"];

function renderTestRows(tests) {
  const list = $("testsList");
  list.innerHTML = "";
  tests.forEach((test) => addTestRow(test));
  $("tabTestCount").textContent = tests.length || "";
}

function addTestRow(test = {}) {
  const type = test.type || "assert";
  const row = document.createElement("div");
  row.className = "test-row";
  row.dataset.type = type;
  const typeOptions = ["assert", "capture", "python"]
    .map((v) => `<option value="${v}" ${v === type ? "selected" : ""}>${v}</option>`).join("");
  const sourceOptions = ["body", "status", "header"]
    .map((v) => `<option value="${v}" ${v === (test.source || "body") ? "selected" : ""}>${v}</option>`).join("");
  const operatorOptions = TEST_OPERATORS
    .map((v) => `<option value="${v}" ${v === (test.operator || "equals") ? "selected" : ""}>${v}</option>`).join("");
  row.innerHTML = `
    <select class="t-type">${typeOptions}</select>
    <select class="t-source">${sourceOptions}</select>
    <input class="t-path" type="text" placeholder="path e.g. status.value" value="${escapeAttr(test.path || "")}">
    <select class="t-operator">${operatorOptions}</select>
    <input class="t-expected" type="text" placeholder="expected / variable / python snippet" value="${escapeAttr(test.expected || test.variable || "")}">
    <button class="icon-btn" type="button" title="Remove test">&times;</button>
  `;
  const updateVisibility = () => {
    const currentType = row.querySelector(".t-type").value;
    row.dataset.type = currentType;
    row.querySelector(".t-source").classList.toggle("hidden", currentType !== "assert");
    row.querySelector(".t-operator").classList.toggle("hidden", currentType !== "assert");
  };
  row.querySelector(".t-type").addEventListener("change", updateVisibility);
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    $("tabTestCount").textContent = collectTests().length || "";
    markActiveTabDirty();
  });
  updateVisibility();
  $("testsList").appendChild(row);
}

function collectTests() {
  return [...document.querySelectorAll("#testsList .test-row")].map((row) => {
    const type = row.querySelector(".t-type").value;
    const expectedOrVariable = row.querySelector(".t-expected").value.trim();
    const path = row.querySelector(".t-path").value.trim();
    if (type === "capture") {
      return { type, source: row.querySelector(".t-source").value, path, variable: expectedOrVariable };
    }
    if (type === "python") {
      return { type, expected: expectedOrVariable };
    }
    return { type, source: row.querySelector(".t-source").value, path, operator: row.querySelector(".t-operator").value, expected: expectedOrVariable };
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("addAssertBtn").addEventListener("click", () => { addTestRow({ type: "assert" }); $("tabTestCount").textContent = collectTests().length || ""; markActiveTabDirty(); });
  $("addCaptureBtn").addEventListener("click", () => { addTestRow({ type: "capture" }); $("tabTestCount").textContent = collectTests().length || ""; markActiveTabDirty(); });
  $("addPythonBtn").addEventListener("click", () => { addTestRow({ type: "python" }); $("tabTestCount").textContent = collectTests().length || ""; markActiveTabDirty(); });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { renderTestRows, addTestRow, collectTests, TEST_OPERATORS };
}
