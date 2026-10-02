/* Runner response pane (ROADMAP §5.4 right pane / §Batch 4) — click a result
 * row in the list (runner-view.js) to inspect its Response/Headers/Request/
 * Tests here.
 *
 * Relies on $ / escapeHtml (shared.js) and highlightJson (body-editor.js),
 * all loaded as separate <script> tags before this one.
 */

// --- pure builders (testable without a DOM) ---

function buildRunnerResponseHtml(event) {
  const snippet = event.responseSnippet;
  if (snippet == null) {
    const reason = event.status === "ERROR"
      ? (event.error || "The request never completed.")
      : "Redacted — a captured variable in this request is named like a secret.";
    return { html: escapeHtml(reason), isJson: false };
  }
  try {
    const pretty = JSON.stringify(JSON.parse(snippet), null, 2);
    return { html: highlightJson(pretty), isJson: true };
  } catch {
    return { html: escapeHtml(snippet), isJson: false };
  }
}

function buildRunnerHeadersHtml(headers) {
  return highlightJson(JSON.stringify(headers || {}, null, 2));
}

// A stored request's headers are an array of {key, value, enabled} rows
// (headers.js's collectAllHeaders shape) — buildRunnerHeadersHtml wants
// the plain object shape a real HTTP response comes back as. `enabled !==
// false`, not a plain truthy check, matches sidebar.js's requestToCurl():
// headers saved before the enabled flag existed have no such property and
// should still count as enabled.
function headersArrayToObject(headers) {
  return Object.fromEntries(
    (headers || []).filter((h) => h.enabled !== false && h.key).map((h) => [h.key, h.value]),
  );
}

function buildRunnerRequestText(event) {
  return `${event.method || ""} ${event.url || ""}`.trim();
}

// Mirrors send.js's renderSingleTestResults row-for-row (same warning
// treatment, same assert/capture line shape) — not reused directly because
// that function is wired to the Console's #single* element ids.
function buildRunnerTestsHtml(tests, warnings) {
  const rows = [];
  if (warnings && warnings.length) {
    rows.push(...warnings.map((w) => `<div class="test-result-row status-fail">&#9888; ${escapeHtml(w)}</div>`));
  }
  if (tests && tests.length) {
    rows.push(...tests.map((t) => {
      const label = t.type === "capture"
        ? `capture ${escapeHtml(t.variable || "")} = ${escapeHtml(String(t.actual))}`
        : t.type === "python"
          ? `python: ${escapeHtml(t.expected || "")}`
          : `${escapeHtml(t.source)} ${escapeHtml(t.path || "")} ${escapeHtml(t.operator)} ${escapeHtml(String(t.expected))} (actual: ${escapeHtml(String(t.actual))})`;
      return `<div class="test-result-row ${t.passed ? "status-ok" : "status-fail"}">${t.passed ? "&#10003;" : "&#10007;"} ${label}</div>`;
    }));
  }
  return rows.join("");
}

// --- DOM glue ---

function showRunnerRowDetail(event) {
  $("runnerRespMethod").textContent = event.method || "";
  $("runnerRespUrl").textContent = event.url || "—";
  $("runnerRespMeta").textContent = event.httpStatus != null
    ? `${event.httpStatus} · ${event.elapsedMs != null ? `${event.elapsedMs} ms` : "—"} · iteration ${event.iteration}, step ${event.step}${event.stepTotal ? `/${event.stepTotal}` : ""}`
    : (event.error || "");

  const { html: bodyHtml } = buildRunnerResponseHtml(event);
  $("runnerRowDetailBody").classList.remove("none");
  $("runnerRowDetailBody").innerHTML = bodyHtml;
  $("runnerRowDetailHeaders").innerHTML = buildRunnerHeadersHtml(event.responseHeaders);
  $("runnerRowDetailRequest").textContent = buildRunnerRequestText(event);

  const testsHtml = buildRunnerTestsHtml(event.tests, event.warnings);
  $("runnerRowDetailTests").innerHTML = testsHtml;
  $("runnerRowDetailTestsTab").classList.toggle("hidden", !testsHtml);
  if (!testsHtml && $("runnerRowDetailTestsTab").classList.contains("active")) {
    selectRunnerDetailTab("body");
  }

  $("runnerSelectedEcho").textContent = `${event.requestName || ""} — iteration ${event.iteration}, step ${event.step}${event.stepTotal ? `/${event.stepTotal}` : ""}`;
}

// Previewing a request from the "Requests in scope" checklist (runner-scope-
// picker.js) before it's run — there's no response/tests yet, so this fills
// only the Request/Headers tabs instead of the run-result shape
// showRunnerRowDetail() expects, and hides the Tests tab entirely.
function showRunnerRequestPreview(request) {
  $("runnerRespMethod").textContent = request.method || "";
  $("runnerRespUrl").textContent = request.url || "—";
  $("runnerRespMeta").textContent = "Not run yet";

  $("runnerRowDetailBody").classList.remove("none");
  $("runnerRowDetailBody").textContent = "Run this request to see its response here.";
  $("runnerRowDetailHeaders").innerHTML = buildRunnerHeadersHtml(headersArrayToObject(request.headers));
  $("runnerRowDetailRequest").textContent = buildRunnerRequestText(request);

  $("runnerRowDetailTests").innerHTML = "";
  $("runnerRowDetailTestsTab").classList.add("hidden");
  if ($("runnerRowDetailTestsTab").classList.contains("active")) selectRunnerDetailTab("request");

  $("runnerSelectedEcho").textContent = request.name || "";
}

function selectRunnerDetailTab(tabName) {
  document.querySelectorAll("[data-runner-detail-tab]").forEach((b) => b.classList.remove("active"));
  const button = document.querySelector(`[data-runner-detail-tab="${tabName}"]`);
  if (button) button.classList.add("active");
  $("runnerRowDetailBody").classList.toggle("hidden", tabName !== "body");
  $("runnerRowDetailHeaders").classList.toggle("hidden", tabName !== "headers");
  $("runnerRowDetailRequest").classList.toggle("hidden", tabName !== "request");
  $("runnerRowDetailTests").classList.toggle("hidden", tabName !== "tests");
}

// Executed result rows (#runnerListBody) and pre-run checklist rows
// (#runnerScopeChecklistBody, runner-scope-picker.js) share one Response-card
// pane, so selecting in either list must clear the other's highlight too —
// otherwise the visibly-selected row stops matching what the pane shows, and
// the ↑/↓ handler below would resume from a stale row instead of the top.
function clearRunnerRowSelection() {
  for (const r of $("runnerListBody").querySelectorAll(".sel")) r.classList.remove("sel");
  for (const r of $("runnerScopeChecklistBody").querySelectorAll(".sel")) r.classList.remove("sel");
}

function selectRunnerListRow(row) {
  clearRunnerRowSelection();
  clearRunnerScopePreview();
  row.classList.add("sel");
  showRunnerRowDetail(row.runnerEvent);
}

document.addEventListener("DOMContentLoaded", () => {
  $("runnerListBody").addEventListener("click", (event) => {
    const row = event.target.closest(".row");
    if (row && row.runnerEvent) selectRunnerListRow(row);
  });
  document.querySelectorAll("[data-runner-detail-tab]").forEach((button) => {
    button.addEventListener("click", () => selectRunnerDetailTab(button.dataset.runnerDetailTab));
  });
  // §5.4 status-line key hints: ↑/↓ moves the selected row. Ignored while
  // typing in any text/number field so it doesn't hijack normal input.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    const rows = [...$("runnerListBody").querySelectorAll(".row")].filter((r) => !r.classList.contains("hidden"));
    if (!rows.length) return;
    event.preventDefault();
    const currentIndex = rows.findIndex((r) => r.classList.contains("sel"));
    const nextIndex = Math.max(0, Math.min(rows.length - 1, currentIndex + (event.key === "ArrowDown" ? 1 : -1)));
    selectRunnerListRow(rows[nextIndex]);
    rows[nextIndex].scrollIntoView({ block: "nearest" });
  });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    buildRunnerResponseHtml, buildRunnerHeadersHtml, buildRunnerRequestText, buildRunnerTestsHtml, headersArrayToObject,
  };
}
