// request-tabs.js is the request-tab "shell": shared {{var}} extraction
// helpers, the top-level tab-switching wiring, and Save/Duplicate for the
// currently open request. Each request sub-tab's own rendering/editing logic
// lives in its own file, split out to keep this one under the repo's
// 500-line cap: static/headers.js (Headers tab), static/console-vars.js
// (Vars tab), static/request-tests.js (Tests tab), static/request-auth.js
// (Auth tab).

const VAR_PATTERN = /\{\{([^{}]+)\}\}/g;

function extractVarNames(text) {
  const names = new Set();
  for (const match of String(text || "").matchAll(VAR_PATTERN)) {
    names.add(match[1]);
  }
  return names;
}

function requestVarNames(request) {
  const names = new Set();
  extractVarNames(request.url).forEach((n) => names.add(n));
  (request.headers || []).forEach((h) => extractVarNames(h.value).forEach((n) => names.add(n)));
  extractVarNames(request.body).forEach((n) => names.add(n));
  (request.bodyParams || []).forEach((p) => extractVarNames(p.value).forEach((n) => names.add(n)));
  return names;
}

function collectionVarNames(collection) {
  const names = new Set();
  (collection?.requests || []).forEach((r) => requestVarNames(r).forEach((n) => names.add(n)));
  return names;
}

// --- tab switching ---

function setupTabs() {
  document.querySelectorAll(".tab[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab[data-tab]").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      ["body", "params", "headers", "vars", "tests", "auth"].forEach((id) =>
        $(`tab-${id}`).classList.toggle("hidden", id !== button.dataset.tab));
    });
  });
  document.querySelectorAll(".tab[data-response-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab[data-response-tab]").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      $("singleBody").classList.toggle("hidden", button.dataset.responseTab !== "body");
      $("singleHeaders").classList.toggle("hidden", button.dataset.responseTab !== "headers");
      $("singleRaw").classList.toggle("hidden", button.dataset.responseTab !== "raw");
      // renderSingleTestResults (send.js) hides the "Test Results" tab
      // button itself whenever there's nothing to show and forces the
      // active tab back to "body" in that case, so it's safe to assume here
      // that if this tab is clickable, it has content worth showing.
      $("singleTestResults").classList.toggle("hidden", button.dataset.responseTab !== "tests");
    });
  });
}

// --- request save/duplicate ---

function currentConsoleRequest() {
  return {
    name: consoleState.selectedRequest ? consoleState.selectedRequest.name : "",
    method: $("method").value,
    // currentUrlWithPendingParamEdits(), not $("url").value directly — folds
    // in an in-progress (not yet "Done"d) Params Bulk Edit the same way
    // collectAllHeaders() below already does for Headers' own bulk editor;
    // otherwise Save/Send would silently drop it, same failure class as the
    // header comment just below already guards against.
    url: currentUrlWithPendingParamEdits(),
    // Includes disabled headers (with enabled:false) — this is the full
    // request definition, used for both Save and Send. The backend is the
    // single point that strips disabled headers from an actual outgoing
    // HTTP call (collection_routes._send_one); collecting only the enabled
    // ones here would silently drop disabled headers from the saved
    // collection every time, which is exactly the bug that made "disable
    // this header" not actually stick.
    headers: collectAllHeaders(),
    body: $("bodyEditor").value,
    bodyMode: $("bodyModeSelect").value,
    // collectAllBodyParams(), not collectBodyParams() — same reason headers
    // above uses collectAllHeaders(): a disabled param must survive Save.
    bodyParams: collectAllBodyParams(),
    tests: collectTests(),
    // Carried through so Save (an edit) and Duplicate both preserve the
    // request's current folder — collection_routes._save_request only
    // actually applies this on a genuine create; an edit-save's copy of it
    // is ignored server-side in favor of the existing request's own value.
    folderId: consoleState.selectedRequest ? (consoleState.selectedRequest.folderId || null) : null,
  };
}

async function saveConsoleRequest() {
  // An Overview tab shows collection documentation, not a request — Save
  // must never write whatever a hidden, previously-active request tab left
  // sitting in the (still-present, just hidden) form fields as a new/edited
  // request.
  if (activeTab() && activeTab().kind === "overview") return;
  if (typeof flushPendingTabRename === "function") await flushPendingTabRename();
  const slug = consoleState.selectedCollectionSlug;
  if (!slug) {
    alert("Select or create a collection in the sidebar first.");
    return;
  }
  const request = currentConsoleRequest();
  if (!request.name) {
    request.name = ((await irisPrompt("Request name:")) || "").trim();
    if (!request.name) return;
  }
  try {
    const data = await postJson(`/api/collections/${encodeURIComponent(slug)}/requests`, request);
    consoleState.selectedRequest = data.request;
    markActiveTabSaved(data.request);
    await loadCollections();
  } catch (error) {
    alert(`Save failed: ${error.message}`);
  }
}

async function duplicateConsoleRequest() {
  // Same reasoning as saveConsoleRequest's overview guard above — nothing in
  // the hidden request form belongs to an active Overview tab.
  if (activeTab() && activeTab().kind === "overview") return;
  const slug = consoleState.selectedCollectionSlug;
  if (!slug) {
    alert("Select or create a collection in the sidebar first.");
    return;
  }
  const base = currentConsoleRequest();
  const name = await promptDuplicateName(slug, uniqueRequestName(slug, `${base.name || "Untitled"} copy`));
  if (!name) return;
  try {
    await postJson(`/api/collections/${encodeURIComponent(slug)}/requests`, { ...base, name });
    await loadCollections();
  } catch (error) {
    alert(`Duplicate failed: ${error.message}`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  $("duplicateBtn").addEventListener("click", duplicateConsoleRequest);
  $("saveBtn").addEventListener("click", saveConsoleRequest);
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    extractVarNames, requestVarNames, collectionVarNames,
    saveConsoleRequest, duplicateConsoleRequest,
  };
}
