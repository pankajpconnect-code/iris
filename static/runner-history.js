// Preview (§13) and run history (§7.3) panels for the Runner tab. Split out
// of runner-view.js to keep that file under the 500-line limit — depends on
// runnerState/runnerSpec/appendRunnerRow/etc. defined there.

// --- preview (§13) ---

async function showRunnerPreview() {
  if (!runnerState.scope) {
    alert("Select a request, folder or collection first.");
    return;
  }
  try {
    const spec = runnerSpec(undefined);
    delete spec.runId;
    const response = await fetch("/api/run-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Preview failed");
    renderRunnerPreview(data);
  } catch (error) {
    alert(error.message);
  }
}

function renderRunnerPreview(data) {
  $("runnerPreviewMeta").textContent = data.capped
    ? `showing first ${data.iterations.length} of ${data.totalIterations} iteration(s)`
    : `${data.totalIterations} iteration(s)`;
  const body = $("runnerPreviewBody");
  body.innerHTML = data.iterations.map((steps, i) => `
    <div class="runner-preview-step">
      <b>Iteration ${i + 1}</b>
      ${steps.map((step) => `
        <div class="pad" style="padding:6px 0">
          <div class="mono">${escapeHtml(step.method)} ${markUnresolved(step.url, step.unresolvedVars)}</div>
          ${step.headers.map((h) => `<div class="mono meta">${escapeHtml(h.key)}: ${markUnresolved(h.value, step.unresolvedVars)}</div>`).join("")}
          ${step.body ? `<pre>${markUnresolved(escapeHtml(step.body), step.unresolvedVars)}</pre>` : ""}
        </div>
      `).join("")}
    </div>
  `).join("");
  $("runnerPreviewPanel").classList.remove("hidden");
}

function markUnresolved(text, unresolvedVars) {
  let out = escapeHtml(text);
  for (const [name, note] of Object.entries(unresolvedVars || {})) {
    const token = escapeHtml(`{{${name}}}`);
    out = out.split(token).join(`<span class="unresolved-var" title="${escapeAttr(note)}">${token}</span>`);
  }
  return out;
}

// --- history (§7.3) ---

async function showRunnerHistory() {
  try {
    const response = await fetch("/api/runs");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load history");
    renderRunnerHistoryList(data.runs || []);
    $("runnerHistoryPanel").classList.remove("hidden");
  } catch (error) {
    alert(error.message);
  }
}

async function clearRunnerHistory() {
  if (!(await irisConfirm("Delete all run history? This cannot be undone."))) return;
  const response = await fetch("/api/runs", { method: "DELETE" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "Could not clear history");
  }
  renderRunnerHistoryList([]);
}

function renderRunnerHistoryList(runs) {
  const body = $("runnerHistoryBody");
  if (!runs.length) {
    body.innerHTML = '<div class="meta">No runs yet.</div>';
    return;
  }
  body.innerHTML = runs.map((r) => `
    <div class="runner-history-item" data-run-id="${escapeAttr(r.runId)}">
      <span class="st ${r.status === "COMPLETED" ? "ok" : "bad"}">${escapeHtml(r.status || "?")}</span>
      <span class="meta">${escapeHtml(r.startedAt || "")}</span>
      <span class="meta">${escapeHtml((r.csvFile || "no CSV"))}</span>
      <span class="meta">${r.summary ? `ok ${r.summary.ok} · failed ${r.summary.failed} · flagged ${r.summary.flagged} · errored ${r.summary.errored}` : ""}</span>
    </div>
  `).join("");
  for (const item of body.querySelectorAll(".runner-history-item")) {
    item.addEventListener("click", () => openRunnerHistoryItem(item.dataset.runId));
  }
}

async function openRunnerHistoryItem(runId) {
  const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
  const doc = await response.json();
  if (!response.ok) {
    alert(doc.error || "Could not load run");
    return;
  }
  resetRunnerCounters();
  runnerState.failures = [];
  runnerState.lastViewedRunId = runId;
  $("runnerExportBtn").disabled = false;
  runnerState.counters.total = doc.totalIterations || (doc.summary && doc.summary.totalIterations) || 0;
  for (const event of doc.events || []) {
    if (event.status === "OK") runnerState.counters.ok += 1;
    else if (event.status === "FAIL") runnerState.counters.failed += 1;
    else if (event.status === "FLAGGED") runnerState.counters.flagged += 1;
    else if (event.status === "ERROR") runnerState.counters.errored += 1;
    if (event.status !== "OK") runnerState.failures.push(event);
    appendRunnerRow(event);
  }
  renderRunnerCounters();
  renderRunnerFailureDigest();
  $("runnerStatusText").textContent = `${doc.status} (history — read only)`;
  $("runnerDot").className = `dot ${doc.status === "COMPLETED" ? "" : "bad"}`;
  runnerState.retryCsvPath = (doc.summary && doc.summary.retryCsv) || "";
  $("runnerRetryBtn").textContent = `Retry ${runnerState.failures.length} failed iteration(s)`;
  $("runnerRetryBtn").classList.toggle("hidden", !runnerState.retryCsvPath);
  $("runnerHistoryPanel").classList.add("hidden");
  applyRunnerHistoryScopeForRerun(doc);
}

function applyRunnerHistoryScopeForRerun(doc) {
  // Re-run re-derives auth from the collection's *current* vars, not the
  // historical run — the history file deliberately omits the auth block
  // (§8.3) — so this only restores scope/environment; csvPath isn't stored
  // in history (only the basename, for display), so a CSV run must be
  // re-attached manually before clicking Run again.
  if (!doc.scope) return;
  const match = runnerScopeIndex.find((e) =>
    e.scope.type === doc.scope.type && e.scope.slug === doc.scope.slug && e.scope.name === doc.scope.name
  );
  if (match) {
    selectRunnerScope(match);
  }
  if (doc.environmentSlug) $("runnerEnvSelect").value = doc.environmentSlug;
  if (doc.csvFile) {
    alert(`This run used CSV "${doc.csvFile}" — history doesn't store the full path; choose it again before running.`);
  }
}
