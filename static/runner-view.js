const runnerState = {
  scope: null,
  excludedNames: new Set(),
  vars: {},
  varsSlug: "", // which collection `vars` actually belongs to — guards the background fetch below against a slug switch landing out of order
  csvPath: "",
  csvRowCount: 0,
  outputFolder: "",
  currentRunId: "",
  lastViewedRunId: "", // survives run completion / history reopen, unlike currentRunId — for Export
  stopRequested: false,
  retryCsvPath: "",
  failures: [],
  counters: { ok: 0, failed: 0, flagged: 0, errored: 0, current: 0, total: 0 },
};

// The scope picker (searchable combobox + "Requests in scope" checklist) and
// its state (runnerScopeIndex, fetchVarsFor) live in runner-scope-picker.js —
// split out to stay under this repo's 500-line limit. That file is loaded
// right after this one and shares runnerState above.

// --- CSV / output folder / iterations ---

async function chooseRunnerCsv() {
  const response = await fetch("/api/choose-csv");
  const data = await response.json();
  if (data.cancelled) return;
  if (!response.ok) throw new Error(data.error || "CSV selection failed");
  runnerState.csvPath = data.csvPath || "";
  runnerState.csvRowCount = data.rowCount || 0;
  $("runnerCsvLabel").textContent = runnerState.csvPath ? (runnerState.csvPath.split("/").pop() || "CSV selected") : "No CSV — runs once";
  $("runnerCsvMeta").textContent = runnerState.csvPath ? `${runnerState.csvRowCount} row(s)` : "";
  $("runnerPersistCapturesRow").classList.toggle("hidden", !runnerState.csvPath);
  // Output folder only ever affects the CSV-driven "retry failed
  // iterations" file (see runner_commands._retry_csv_path) — meaningless
  // without a CSV attached, so it self-hides the same way the
  // write-captures-back row already does.
  $("runnerOutputRow").classList.toggle("hidden", !runnerState.csvPath);
  $("runnerHint").textContent = runnerState.csvPath
    ? "An unresolved {{col}} in a header, URL or body fails the run up front — a typo'd column name, not a bug."
    : "No CSV attached — the sequence runs once. Attach a CSV to run once per row (an unresolved {{col}} fails up front, not silently).";
}

async function chooseRunnerOutputFolder() {
  const response = await fetch("/api/choose-output-folder");
  const data = await response.json();
  if (data.cancelled) return;
  if (!response.ok) throw new Error(data.error || "Output folder selection failed");
  runnerState.outputFolder = data.outputFolder || "";
  $("runnerOutputLabel").textContent = runnerState.outputFolder || "Default output folder";
}

// Number(value) || undefined would treat an explicit "0" the same as an
// empty field — typing 0 into Iterations (meaning "run zero times") must
// not silently fall back to the runner's default "auto" behavior.
function parseOptionalCount(value) {
  return value === "" ? undefined : Number(value);
}

function runnerSpec(runId) {
  const auth = authPayloadFields(runnerState.vars);
  return {
    ...auth,
    runId,
    scope: scopeWithExclusions(),
    environmentSlug: $("runnerEnvSelect").value,
    csvPath: runnerState.csvPath || undefined,
    outputFolder: runnerState.outputFolder || undefined,
    iterations: parseOptionalCount($("runnerIterationsInput").value),
    workers: Number($("runnerWorkersInput").value) || undefined,
    resetCapturesEachIteration: $("runnerResetCapturesCheck").checked,
    persistCaptures: $("runnerPersistCapturesCheck").checked,
    timeout: getRequestTimeoutSeconds(),
    proxySettings: getProxySettings(),
    insecure: getInsecureMode(),
    // ROADMAP Batch 4: was a fixed backend constant (RESPONSE_SNIPPET_LIMIT).
    responseSnippetLimit: parseOptionalCount($("runnerResponseCapInput").value),
    // Auth-retry-stability design §7 — read from runner-options-popover.js's
    // localStorage-backed getters, not the DOM directly, so Run and Preview
    // agree with whatever the popover last persisted.
    retries: getRunnerRetries(),
    // ctx.delay (run_execution_state.py) is consumed as SECONDS — the
    // popover stores/displays ms for finer-grained input, so convert here.
    delay: getRunnerRetryDelayMs() / 1000,
    maxTokenRefreshes: getRunnerMaxTokenRefreshes(),
    authBreakerEnabled: getRunnerAuthBreakerEnabled(),
    authRetryStatuses: getRunnerAuthRetryStatuses(),
    refreshTokenCookieName: getRunnerRefreshTokenCookieName(),
  };
}

// workers > 1 requires resetCapturesEachIteration (backend hard rejects
// otherwise, §8.8 — parallel iterations sharing one mutable capture dict
// would race). Force + lock the checkbox rather than let the user hit a
// 400 after already configuring everything else.
function syncRunnerWorkersConstraint() {
  const workers = Number($("runnerWorkersInput").value) || 1;
  const resetCheck = $("runnerResetCapturesCheck");
  if (workers > 1) {
    resetCheck.checked = true;
    resetCheck.disabled = true;
    $("runnerResetNote").textContent = "Required while running in parallel";
  } else {
    resetCheck.disabled = false;
    $("runnerResetNote").textContent = "";
  }
  $("runnerParallelLock").classList.toggle("hidden", workers <= 1);
}

// --- run / stop ---

async function runRunnerBatch(csvPathOverride) {
  if (runnerState.currentRunId) return;
  if (!runnerState.scope) {
    alert("Select a request, folder or collection first.");
    return;
  }
  // runnerState.vars is otherwise populated by a fire-and-forget background
  // fetch (see applyRunnerScopeInclusion) so that toggling checkboxes never
  // has to wait on a network round trip — that's fine for the picker UI, but
  // a run's auth payload (authPayloadFields below) needs the *correct*
  // collection's vars, not "whatever happened to resolve most recently".
  // Re-fetching here, awaited, is the actual guarantee; every other guard
  // around runnerState.vars is just keeping the in-between state honest.
  if (runnerState.varsSlug !== runnerState.scope.slug) {
    runnerState.vars = await fetchVarsFor(runnerState.scope.slug);
    runnerState.varsSlug = runnerState.scope.slug;
  }
  if (csvPathOverride) runnerState.csvPath = csvPathOverride;
  const runId = newRunnerRunId();
  runnerState.currentRunId = runId;
  runnerState.lastViewedRunId = runId;
  runnerState.stopRequested = false;
  runnerState.failures = [];
  runnerState.retryCsvPath = "";
  $("runnerRunBtn").disabled = true;
  $("runnerStopBtn").disabled = false;
  $("runnerClearBtn").disabled = true;
  $("runnerRetryBtn").classList.add("hidden");
  $("runnerExportBtn").disabled = true;
  $("runnerProgWrap").classList.remove("hidden");
  // A fresh run's results belong front and center — stale Preview/History
  // panels left open from a previous action would otherwise push the new
  // results table below the fold, exactly the clutter that made a 2000+
  // row preview and history list bury the actual run in the screenshot.
  $("runnerPreviewPanel").classList.add("hidden");
  $("runnerHistoryPanel").classList.add("hidden");
  resetRunnerCounters();
  $("runnerDot").className = "dot running";
  $("runnerStatusText").textContent = "Running";
  try {
    const response = await fetch("/api/run-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(runnerSpec(runId)),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "Run failed");
    }
    const summary = await streamRunnerOutput(response);
    const stopped = summary.exitCode === 130 || runnerState.stopRequested;
    $("runnerDot").className = `dot ${stopped || summary.exitCode !== 0 ? "bad" : ""}`;
    $("runnerStatusText").textContent = stopped ? "Stopped" : (summary.exitCode === 0 ? "Done" : `Exit ${summary.exitCode}`);
    // totalRequests/retriedRequests are only known once the run finishes —
    // emitted and persisted (run_orchestrator.execute()'s summary event) but
    // never shown until now.
    if (summary.totalRequests != null) {
      const retried = summary.retriedRequests || 0;
      $("runnerMeta").textContent += ` · ${summary.totalRequests} request(s)${retried ? `, ${retried} retried` : ""}`;
    }
    if (summary.retryCsv) {
      runnerState.retryCsvPath = summary.retryCsv;
      $("runnerRetryBtn").textContent = `Retry ${runnerState.failures.length} failed iteration(s)`;
      $("runnerRetryBtn").classList.remove("hidden");
    }
    renderRunnerFailureDigest();
  } catch (error) {
    $("runnerDot").className = "dot bad";
    $("runnerStatusText").textContent = `Failed: ${error.message}`;
  } finally {
    runnerState.currentRunId = "";
    runnerState.stopRequested = false;
    $("runnerRunBtn").disabled = false;
    $("runnerStopBtn").disabled = true;
    $("runnerClearBtn").disabled = false;
    $("runnerExportBtn").disabled = !runnerState.lastViewedRunId;
    $("runnerProgWrap").classList.add("hidden");
  }
}

async function exportRunnerResults() {
  if (!runnerState.lastViewedRunId) return;
  const runId = runnerState.lastViewedRunId;
  try {
    // Fetch + native Save As via save_bridge, instead of blob + a[download]
    // — the latter always lands in ~/Downloads with no chosen location.
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/export`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "Export failed");
    }
    const text = await response.text();
    await saveTextFile(`run-${runId}.csv`, text);
  } catch (error) {
    alert(`Export failed: ${error.message}`);
  }
}

async function stopRunnerBatch() {
  if (!runnerState.currentRunId) return;
  runnerState.stopRequested = true;
  $("runnerStopBtn").disabled = true;
  try {
    await postJson("/api/stop-run", { runId: runnerState.currentRunId });
  } catch {
    // best-effort — the stream will still end when the run notices cancel_event
  }
}

async function retryRunnerFailures() {
  if (!runnerState.retryCsvPath) return;
  await runRunnerBatch(runnerState.retryCsvPath);
}

// "Clear" in the main Runner toolbar — resets the results/output side only
// (log table, counters, failure digest, Preview/History panels, Export
// availability). Deliberately leaves scope/CSV/output-folder/iterations
// alone — those are setup you chose, not run output, and clearing them here
// too would silently undo a selection made just to look at old results.
function clearRunnerResults() {
  if (runnerState.currentRunId) return; // guarded by disabling the button too; belt and suspenders
  resetRunnerCounters();
  runnerState.failures = [];
  runnerState.lastViewedRunId = "";
  runnerState.retryCsvPath = "";
  $("runnerPreviewPanel").classList.add("hidden");
  $("runnerHistoryPanel").classList.add("hidden");
  $("runnerRetryBtn").classList.add("hidden");
  $("runnerExportBtn").disabled = true;
  $("runnerDot").className = "dot";
  $("runnerStatusText").textContent = "Idle";
}

// --- counters / list ---

function resetRunnerCounters() {
  runnerState.counters = { ok: 0, failed: 0, flagged: 0, errored: 0, current: 0, total: 0 };
  renderRunnerCounters();
  $("runnerListBody").innerHTML = "";
  $("runnerFailureDigest").textContent = "";
  resetRunnerListFilters();
}

function renderRunnerCounters() {
  const c = runnerState.counters;
  $("runnerOkCount").textContent = c.ok;
  $("runnerFailedCount").textContent = c.failed;
  $("runnerFlaggedCount").textContent = c.flagged;
  $("runnerErroredCount").textContent = c.errored;
  const label = runnerState.csvPath ? (runnerState.csvPath.split("/").pop() || "") : "no CSV";
  $("runnerMeta").textContent = `${label} · iteration ${c.current}/${c.total || "?"}`;
  $("runnerProgBar").style.width = c.total ? `${Math.min(100, (c.current / c.total) * 100)}%` : "0%";
}

// --- NDJSON stream (design §8.1) — replaces the old text-line regex parser ---

async function streamRunnerOutput(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let summary = { exitCode: 1, status: "COMPLETED" };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    pending += decoder.decode(value, { stream: true });
    const lines = pending.split(/\r?\n/);
    pending = lines.pop() || "";
    for (const line of lines) summary = handleRunnerEvent(line, summary) || summary;
  }
  if (pending) summary = handleRunnerEvent(pending, summary) || summary;
  return summary;
}

function handleRunnerEvent(line, summary) {
  if (!line.trim()) return summary;
  let event;
  try {
    event = JSON.parse(line);
  } catch {
    return summary; // defensive — never let one bad line kill the stream
  }
  if (event.type === "run_started") {
    runnerState.counters.total = event.totalIterations;
    renderRunnerCounters();
  } else if (event.type === "attempt") {
    appendRunnerAttemptRow(event);
  } else if (event.type === "result") {
    const c = runnerState.counters;
    c.current = Math.max(c.current, event.iteration);
    if (event.status === "OK") c.ok += 1;
    else if (event.status === "FAIL") c.failed += 1;
    else if (event.status === "FLAGGED") c.flagged += 1;
    else if (event.status === "ERROR") c.errored += 1;
    if (event.status !== "OK") runnerState.failures.push(event);
    renderRunnerCounters();
    appendRunnerRow(event);
  } else if (event.type === "summary") {
    return event;
  }
  return summary;
}

// Live, per-attempt evidence row — appended the instant each real HTTP try
// lands, before the request's own final appendRunnerRow summary. Exists
// because the aggregate "attempt X/Y" / "N retried" counts are not enough
// on their own for a user to trust a retry actually happened over the
// network; this is that proof, one row per real attempt, muted so the
// authoritative result row still reads as the answer.
function appendRunnerAttemptRow(event) {
  const row = document.createElement("div");
  row.className = "row row-attempt";
  row.dataset.requestName = event.requestName || "";
  const statusText = event.httpStatus != null ? String(event.httpStatus) : "ERR";
  const errorText = escapeHtml((event.error || "").split("\n")[0].slice(0, 160));
  const outcome = event.willRetry ? "retrying…" : "final";
  row.innerHTML = `
    <span class="pill err">${escapeHtml(statusText)}</span>
    <span class="bd">
      <span class="l1"><span class="nm">${escapeHtml(event.requestName || "")} — attempt ${event.attempt}/${event.attempts}</span></span>
      <span class="l2"><span class="w">${outcome}${errorText ? " · " : ""}</span>${errorText}</span>
    </span>
  `;
  $("runnerListBody").appendChild(row);
  $("runnerListBody").parentElement.scrollTop = $("runnerListBody").parentElement.scrollHeight;
  return row;
}

// Result-list row (ROADMAP §5.4: "one entry per result, no columns, no group
// rows"). Passing rows drop the reason/meta second line entirely (§5.4);
// Compact density (runner-list-filters.js) collapses both kinds to one line
// via CSS alone, not a second render path.
function appendRunnerRow(event) {
  const row = document.createElement("div");
  row.className = "row";
  row.dataset.status = event.status;
  row.dataset.requestName = event.requestName || "";
  row.dataset.search = `${event.requestName || ""} ${event.url || ""} ${event.error || ""} ${event.httpStatus || ""}`.toLowerCase();
  // Kept as a live property (not a stringified dataset attribute) so the
  // response pane (runner-row-detail.js) gets responseHeaders/tests back as
  // real objects/arrays on click, not JSON round-tripped twice.
  row.runnerEvent = event;

  const pillClass = event.status === "OK" ? "ok" : event.status === "FLAGGED" ? "flag" : event.status === "ERROR" ? "err" : "fail";
  const stepLabel = event.stepTotal ? `${event.step}/${event.stepTotal}` : String(event.step);
  const elapsedLabel = event.elapsedMs != null ? `${event.elapsedMs} ms` : "—";
  const testsLabel = event.testsTotal && event.testsPassed !== event.testsTotal ? ` · ${event.testsPassed}/${event.testsTotal} tests` : "";
  const attemptLabel = event.attempts > 1 ? ` · attempt ${event.attempt}/${event.attempts}` : "";
  const reasonParts = [];
  if (event.warnings && event.warnings.length) reasonParts.push(`<span class="status-fail">&#9888; ${escapeHtml(event.warnings[0])}</span>`);
  const errorText = escapeHtml((event.error || event.responseSnippet || "").split("\n")[0].slice(0, 160));
  if (errorText) reasonParts.push(errorText);
  const reason = reasonParts.join(" · ");
  const l2 = event.status === "OK" && !reason && !attemptLabel
    ? ""
    : `<span class="l2"><span class="w">iteration ${event.iteration} · step ${stepLabel}${attemptLabel}${testsLabel}${reason ? " · " : ""}</span>${reason}</span>`;

  row.innerHTML = `
    <span class="pill ${pillClass}">${event.httpStatus != null ? escapeHtml(String(event.httpStatus)) : "—"}</span>
    <span class="bd">
      <span class="l1"><span class="nm">${escapeHtml(event.requestName || "")}</span><span class="tm">${escapeHtml(elapsedLabel)}</span></span>
      ${l2}
    </span>
  `;
  $("runnerListBody").appendChild(row);
  $("runnerListBody").parentElement.scrollTop = $("runnerListBody").parentElement.scrollHeight;
  registerRunnerListRequestName(event.requestName);
  applyRunnerListFilterToRow(row);
  return row;
}

// --- failure digest (§12.1.4) — grouped by (status, httpStatus, first line of error) ---

function renderRunnerFailureDigest() {
  const el = $("runnerFailureDigest");
  if (!runnerState.failures.length) {
    el.textContent = "";
    return;
  }
  const groups = new Map();
  for (const f of runnerState.failures) {
    const reason = (f.error || f.responseSnippet || "").split("\n")[0].slice(0, 80);
    const key = `${f.status}|${f.httpStatus}|${reason}`;
    groups.set(key, (groups.get(key) || 0) + 1);
  }
  const parts = [...groups.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([key, count]) => {
      const [status, httpStatus, reason] = key.split("|");
      return `${escapeHtml(status)} ${escapeHtml(httpStatus)} — ${escapeHtml(reason)} ×${count}`;
    });
  el.innerHTML = `${runnerState.failures.length} failure(s), ${groups.size} distinct reason(s): ` + parts.join(" · ");
}

function newRunnerRunId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
  return `run-${Math.random().toString(16).slice(2)}`;
}

document.addEventListener("DOMContentLoaded", () => {
  const scopeInput = $("runnerRequestSelect");
  scopeInput.addEventListener("focus", focusRunnerScopeInputForSearch);
  // Picking a row (mousedown preventDefault, so the input never blurs) or
  // pressing Escape leaves the input focused with the dropdown closed — a
  // plain "focus" listener won't refire on a click that doesn't change
  // focus, so a "click" listener is the reopen path for both cases.
  scopeInput.addEventListener("click", focusRunnerScopeInputForSearch);
  scopeInput.addEventListener("input", openRunnerScopeDropdown);
  scopeInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeRunnerScopeDropdown();
  });
  scopeInput.addEventListener("blur", (event) => {
    // Focus moving into our own dropdown (checking a checkbox) must not
    // revert the typed text or close anything — the document click-outside
    // listener below owns closing; this only reverts stray typed text once
    // focus has genuinely left the whole widget.
    if (runnerScopeDropdownEl && runnerScopeDropdownEl.contains(event.relatedTarget)) return;
    setTimeout(() => {
      if (runnerScopeDropdownEl && runnerScopeDropdownEl.contains(document.activeElement)) return;
      scopeInput.value = scopeInput.dataset.label || "";
    }, 150);
  });
  document.addEventListener("click", (event) => {
    if (suppressNextRunnerScopeOutsideClick) {
      // A mousedown on "Select all"/"Clear" just removed the box those
      // buttons live in and rebuilt a new one — some browsers then dispatch
      // the trailing "click" for that same gesture on whatever ancestor
      // survived the removal (not on the new box), which would otherwise
      // read as a click outside and close the dropdown we just rebuilt.
      suppressNextRunnerScopeOutsideClick = false;
      return;
    }
    if (!runnerScopeDropdownEl) return;
    if (event.target === scopeInput || runnerScopeDropdownEl.contains(event.target)) return;
    closeRunnerScopeDropdown();
  });
  // Placeholder color alone didn't cover the real complaint: a placeholder
  // never clears on click, only once you start typing (true of every text
  // field everywhere) — a number field's up/down spinner arrows also count
  // as "starting" without ever placing a cursor to backspace from. Selecting
  // on focus means the very next keystroke (typed OR via the spinner)
  // replaces whatever was there outright, so there's nothing to manually
  // clear either way.
  [$("runnerIterationsInput"), $("runnerWorkersInput")].forEach((input) =>
    input.addEventListener("focus", (event) => event.target.select()));
  $("runnerWorkersInput").addEventListener("input", (event) => {
    if (Number(event.target.value) > 8) event.target.value = 8;
    syncRunnerWorkersConstraint();
  });
  $("runnerChooseCsvBtn").addEventListener("click", () => chooseRunnerCsv().catch((e) => alert(e.message)));
  $("runnerChooseOutputBtn").addEventListener("click", () => chooseRunnerOutputFolder().catch((e) => alert(e.message)));
  $("runnerRunBtn").addEventListener("click", () => runRunnerBatch());
  $("runnerStopBtn").addEventListener("click", stopRunnerBatch);
  $("runnerRetryBtn").addEventListener("click", () => retryRunnerFailures().catch((e) => alert(e.message)));
  $("runnerExportBtn").addEventListener("click", exportRunnerResults);
  $("runnerClearBtn").addEventListener("click", clearRunnerResults);
  // Preview and History are mutually exclusive — both open at once is what
  // buried a real run's results below the fold in the reported screenshot.
  $("runnerPreviewBtn").addEventListener("click", () => {
    $("runnerHistoryPanel").classList.add("hidden");
    showRunnerPreview();
  });
  $("runnerPreviewCloseBtn").addEventListener("click", () => $("runnerPreviewPanel").classList.add("hidden"));
  $("runnerHistoryBtn").addEventListener("click", () => {
    $("runnerPreviewPanel").classList.add("hidden");
    showRunnerHistory().catch((e) => alert(e.message));
  });
  $("runnerHistoryCloseBtn").addEventListener("click", () => $("runnerHistoryPanel").classList.add("hidden"));
  $("runnerHistoryClearBtn").addEventListener("click", () => clearRunnerHistory().catch((e) => alert(e.message)));
  $("runnerScopeSelectAllBtn").addEventListener("click", () => {
    runnerState.excludedNames = new Set();
    renderRunnerScopeSelectionSurfaces(); // not just the checklist — the search box's label
                                           // ("GET Loan Account") would otherwise go stale the
                                           // instant this button changes the real selection
  });
  $("runnerScopeSelectNoneBtn").addEventListener("click", () => {
    runnerState.excludedNames = new Set(requestNamesInScope(runnerState.scope));
    renderRunnerScopeSelectionSurfaces();
  });
  $("runnerScopeChecklistSearch").addEventListener("input", (event) =>
    applyRunnerScopeChecklistFilter(event.target.value));
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    parseOptionalCount, chooseRunnerCsv, chooseRunnerOutputFolder, appendRunnerRow, appendRunnerAttemptRow, runnerSpec,
  };
}
