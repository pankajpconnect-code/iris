// Multi-tab request opening: each clicked sidebar request opens
// as its own tab, side by side, so switching between them doesn't lose edits.
const tabState = { tabs: [], activeId: null, nextId: 1 };

function findTab(collectionSlug, requestName) {
  return tabState.tabs.find((t) => t.collectionSlug === collectionSlug && t.requestName === requestName);
}

function findOverviewTab(collectionSlug) {
  return tabState.tabs.find((t) => t.kind === "overview" && t.collectionSlug === collectionSlug);
}

// A request's own `.auth` (set at import time — see AGENTS.md Phase 0, no
// editor of its own) must survive into the tab draft that becomes
// consoleState.selectedRequest (activateTab, below) — otherwise the Auth
// tab/Send fallback in request-tabs.js has nothing to fall back to, even
// though the request object it was handed had auth all along.
function requestToDraft(request) {
  return {
    method: request.method,
    url: request.url,
    headers: JSON.parse(JSON.stringify(request.headers || [])),
    body: request.body || "",
    bodyMode: request.bodyMode || "raw",
    bodyParams: JSON.parse(JSON.stringify(request.bodyParams || [])),
    tests: JSON.parse(JSON.stringify(request.tests || [])),
    auth: request.auth ? JSON.parse(JSON.stringify(request.auth)) : undefined,
  };
}

function openRequestTab(collectionSlug, request) {
  const existing = findTab(collectionSlug, request.name);
  if (existing) {
    activateTab(existing.id);
    return;
  }
  const id = tabState.nextId++;
  tabState.tabs.push({
    id,
    collectionSlug,
    requestName: request.name,
    folderId: request.folderId || null,
    draft: requestToDraft(request),
    dirty: false,
    response: null,
  });
  activateTab(id);
}

// Opens (or reuses/activates) a collection's Overview tab, showing its
// stored description. Keyed on collectionSlug alone — unlike a request tab,
// it has no requestName, so it can't reuse findTab and gets its own kind
// discriminator (findOverviewTab) instead.
function openCollectionOverviewTab(collection) {
  const existing = findOverviewTab(collection.slug);
  if (existing) {
    existing.collectionName = collection.name;
    existing.description = collection.description;
    activateTab(existing.id);
    return;
  }
  const id = tabState.nextId++;
  tabState.tabs.push({
    id,
    kind: "overview",
    collectionSlug: collection.slug,
    collectionName: collection.name,
    description: collection.description,
  });
  activateTab(id);
}

// Starts a blank, unsaved request of the given method as its own new tab —
// always creates a fresh tab (no dedup against other unsaved tabs) — several
// Untitled tabs can be open at once. Naming happens on Save.
function openNewRequestTab(collectionSlug, method, folderId = null) {
  const id = tabState.nextId++;
  tabState.tabs.push({
    id,
    collectionSlug,
    requestName: "",
    folderId,
    draft: { method, url: "", headers: [], body: "", bodyMode: "raw", bodyParams: [], tests: [] },
    dirty: true,
    response: null,
  });
  activateTab(id);
}

function activeTab() {
  return tabState.tabs.find((t) => t.id === tabState.activeId) || null;
}

function captureActiveDraft() {
  const tab = activeTab();
  if (!tab || tab.kind === "overview") return;
  tab.draft = {
    method: $("method").value,
    // currentUrlWithPendingParamEdits(), not $("url").value directly — folds
    // in an in-progress (not yet "Done"d) Params Bulk Edit, the same way
    // collectAllHeaders() below already does for Headers' own bulk editor.
    url: currentUrlWithPendingParamEdits(),
    // collectAllHeaders(), not collectHeaders() — a disabled header must
    // survive being captured into an inactive tab's draft, same reasoning as
    // currentConsoleRequest() in request-tabs.js.
    headers: collectAllHeaders(),
    body: $("bodyEditor").value,
    bodyMode: $("bodyModeSelect").value,
    bodyParams: collectAllBodyParams(),
    tests: collectTests(),
    // auth has no editor of its own (same reasoning as collection_routes.py's
    // _save_request carrying it forward) — this rebuild used to silently
    // drop it on every single tab switch (including re-clicking the same
    // tab, since activateTab() always calls this first), even though
    // requestToDraft() above got it right on the initial open.
    auth: tab.draft.auth,
  };
}

// An overview tab shows collection documentation instead of a request form —
// toggles which half of the console pane is visible. `respSingle` is
// included here (forced hidden in overview mode) even though it also has its
// own response-presence-based hidden toggle (activateTab's request branch,
// below) — those two concerns are independent and this one must always win
// while an overview tab is active.
function setRequestPanesHidden(hidden) {
  $("requestUrlbar").classList.toggle("hidden", hidden);
  $("requestSubTabs").classList.toggle("hidden", hidden);
  $("requestEditor").classList.toggle("hidden", hidden);
  $("respSingle").classList.toggle("hidden", hidden);
  $("overviewPane").classList.toggle("hidden", !hidden);
}

function activateTab(id) {
  captureActiveDraft();
  tabState.activeId = id;
  const tab = activeTab();
  if (!tab) {
    clearRequestPanel();
    renderTabStrip();
    return;
  }
  if (tab.kind === "overview") {
    consoleState.selectedRequest = null;
    consoleState.selectedCollectionSlug = tab.collectionSlug;
    consoleState.selectedCollection = consoleState.collectionsCache.find((c) => c.slug === tab.collectionSlug) || null;
    setRequestPanesHidden(true);
    const overviewPane = $("overviewPane");
    overviewPane.innerHTML = `<div class="overview-content">${renderMarkdownToHtml(tab.description)}</div>`;
    overviewPane.scrollTop = 0;
    overviewPane.scrollLeft = 0;
    loadConsoleVars(tab.collectionSlug);
    renderAuthTab();
    updateTopbarPills();
    renderCollectionTree(consoleState.collectionsCache);
    renderTabStrip();
    return;
  }
  setRequestPanesHidden(false);
  consoleState.selectedRequest = { name: tab.requestName, folderId: tab.folderId || null, ...tab.draft };
  consoleState.selectedCollectionSlug = tab.collectionSlug;
  consoleState.selectedCollection = consoleState.collectionsCache.find((c) => c.slug === tab.collectionSlug) || null;
  $("method").value = tab.draft.method;
  $("url").value = tab.draft.url;
  if (typeof renderUrlHighlight === "function") renderUrlHighlight();
  $("bodyEditor").value = tab.draft.body;
  if (typeof renderBodyHighlight === "function") renderBodyHighlight();
  $("bodyModeSelect").value = tab.draft.bodyMode || "raw";
  renderBodyParamRows(tab.draft.bodyParams);
  syncBodyModeVisibility();
  renderHeaderRows(tab.draft.headers);
  renderParamsTabFromUrl();
  renderTestRows(tab.draft.tests);
  // Each tab remembers its own last response (set in sendConsoleRequest,
  // send.js) so switching away and back doesn't lose it — only a tab that's
  // never been sent, or was just closed, falls back to a cleared panel.
  if (tab.response) {
    $("respSingle").classList.remove("hidden");
    renderSingleResponse(tab.response);
  } else {
    resetSingleResponsePanel();
  }
  loadConsoleVars(tab.collectionSlug);
  renderAuthTab();
  updateTopbarPills();
  renderCollectionTree(consoleState.collectionsCache);
  renderTabStrip();
}

function closeTab(id, event) {
  if (event) event.stopPropagation();
  const idx = tabState.tabs.findIndex((t) => t.id === id);
  if (idx === -1) return;
  const wasActive = tabState.activeId === id;
  tabState.tabs.splice(idx, 1);
  if (!wasActive) {
    renderTabStrip();
    return;
  }
  const next = tabState.tabs[idx] || tabState.tabs[idx - 1];
  if (next) {
    tabState.activeId = null; // avoid capturing a draft for the tab we just removed
    activateTab(next.id);
  } else {
    tabState.activeId = null;
    clearRequestPanel();
    renderTabStrip();
  }
}

function clearRequestPanel() {
  setRequestPanesHidden(false);
  consoleState.selectedRequest = null;
  $("method").value = "GET";
  $("url").value = "";
  if (typeof renderUrlHighlight === "function") renderUrlHighlight();
  $("bodyEditor").value = "";
  if (typeof renderBodyHighlight === "function") renderBodyHighlight();
  $("bodyModeSelect").value = "raw";
  renderBodyParamRows([]);
  syncBodyModeVisibility();
  renderHeaderRows([]);
  renderParamsTabFromUrl();
  renderTestRows([]);
  resetSingleResponsePanel();
  renderCollectionTree(consoleState.collectionsCache);
}

function markActiveTabDirty() {
  const tab = activeTab();
  if (tab && !tab.dirty) {
    tab.dirty = true;
    renderTabStrip();
  }
}

// Called after a successful Save so the tab stops showing the unsaved dot and
// (for a brand-new request that just got named via the Save prompt) tracks
// the assigned name so re-clicking it in the sidebar activates this same tab.
function markActiveTabSaved(savedRequest) {
  const tab = activeTab();
  if (!tab || tab.kind === "overview") return;
  tab.requestName = savedRequest.name;
  tab.folderId = savedRequest.folderId || null;
  tab.dirty = false;
  renderTabStrip();
}

// Native `dblclick` is unreliable here: activateTab() re-renders the whole
// strip (innerHTML = "") on the FIRST click of the gesture, destroying the
// `.req-tab-name` node the browser was tracking for the second click — some
// engines then fail to fire `dblclick` at all since the node identity changed
// mid-gesture. Tracking double-clicks ourselves via a plain module-level
// timestamp sidesteps that entirely: it only depends on the tab's `id`
// surviving the re-render, which it does (tabState.tabs isn't rebuilt).
const TAB_DOUBLE_CLICK_MS = 500;
let lastTabStripClick = { id: null, time: 0 };

function isDoubleTabClick(lastClick, tabId, now, thresholdMs = TAB_DOUBLE_CLICK_MS) {
  return lastClick.id === tabId && now - lastClick.time < thresholdMs;
}

function renderTabStrip() {
  const strip = $("requestTabStrip");
  if (!strip) return;
  strip.innerHTML = "";
  for (const tab of tabState.tabs) {
    const el = document.createElement("div");
    el.className = "req-tab" + (tab.id === tabState.activeId ? " active" : "");
    if (tab.kind === "overview") {
      el.innerHTML = `
        <span class="req-tab-name">${escapeHtml(tab.collectionName)}</span>
        <span class="req-tab-close" title="Close">&times;</span>
      `;
      el.addEventListener("click", () => activateTab(tab.id));
      el.querySelector(".req-tab-close").addEventListener("click", (event) => closeTab(tab.id, event));
      strip.appendChild(el);
      continue;
    }
    const shortMethod = tab.draft.method === "DELETE" ? "DEL" : tab.draft.method;
    el.innerHTML = `
      <span class="m ${escapeAttr(tab.draft.method)}">${escapeHtml(shortMethod)}</span>
      <span class="req-tab-name">${escapeHtml(tab.requestName || "Untitled")}</span>
      ${tab.dirty ? '<span class="req-tab-dirty" title="Unsaved changes">&#9679;</span>' : ""}
      <span class="req-tab-close" title="Close">&times;</span>
    `;
    el.addEventListener("click", (event) => {
      const nameEl = event.target.closest(".req-tab-name");
      const now = Date.now();
      if (nameEl && isDoubleTabClick(lastTabStripClick, tab.id, now)) {
        lastTabStripClick = { id: null, time: 0 };
        startTabInlineRename(tab, nameEl);
        return;
      }
      lastTabStripClick = { id: tab.id, time: now };
      activateTab(tab.id);
    });
    el.querySelector(".req-tab-close").addEventListener("click", (event) => closeTab(tab.id, event));
    el.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      showTabContextMenu(event, tab);
    });
    strip.appendChild(el);
  }
}

// Set while a tab's inline rename is committing, so Save (button or Cmd+S)
// can wait for it instead of racing it — see flushPendingTabRename below.
let pendingTabRenamePromise = null;

// Double-click-to-rename on the tab itself, not just the sidebar row — an
// unsaved ("Untitled") tab has nothing saved yet to rename, so this is a
// no-op until the first Save. Shares renameSavedRequest (sidebar-request-actions.js) so a
// rename from either surface stays consistent with the other.
function startTabInlineRename(tab, nameSpan) {
  if (!tab.requestName) return;
  const input = document.createElement("input");
  input.type = "text";
  input.className = "req-tab-rename-input";
  input.value = tab.requestName;
  nameSpan.replaceWith(input);
  input.focus();
  input.select();
  let cancelled = false;
  let settled = false;
  input.addEventListener("mousedown", (event) => event.stopPropagation());
  input.addEventListener("click", (event) => event.stopPropagation());
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); input.blur(); }
    else if (event.key === "Escape") { event.preventDefault(); cancelled = true; input.blur(); }
  });
  input.addEventListener("blur", () => {
    if (settled) return;
    settled = true;
    pendingTabRenamePromise = (async () => {
      if (cancelled) { renderTabStrip(); return; }
      const newName = input.value.trim();
      if (!newName || newName === tab.requestName) { renderTabStrip(); return; }
      await renameSavedRequest(tab.collectionSlug, tab.requestName, newName);
    })();
  });
}

// Cmd+S/Ctrl+S and the visible Save button both funnel into
// saveConsoleRequest (request-tabs.js), which reads the request's name off
// consoleState.selectedRequest — but that isn't updated until the tab
// rename's blur handler finishes its network round-trip. Firing Save while
// the rename input still has focus (a plain button .click() doesn't blur it
// the way a real mouse click would) used to save under the stale old name
// with no visible sign anything went wrong. Blurring here forces the commit
// to start, then this awaits the same in-flight promise before Save reads
// the request's current name.
async function flushPendingTabRename() {
  const active = document.activeElement;
  if (active && active.classList.contains("req-tab-rename-input")) {
    active.blur();
  }
  if (pendingTabRenamePromise) {
    await pendingTabRenamePromise;
    pendingTabRenamePromise = null;
  }
}

// renameSavedRequest (sidebar-request-actions.js) calls this after a successful rename so
// every open tab pointing at the old name — active or not — tracks the new
// one instead of silently going stale.
function renameOpenTabs(collectionSlug, oldName, newName) {
  let changed = false;
  for (const tab of tabState.tabs) {
    if (tab.collectionSlug === collectionSlug && tab.requestName === oldName) {
      tab.requestName = newName;
      changed = true;
    }
  }
  if (changed) renderTabStrip();
}

// deleteRequestFromSidebar (sidebar-request-actions.js) calls this so a tab left open on a
// now-deleted request gets closed instead of pointing at nothing.
function closeTabsForRequest(collectionSlug, name) {
  for (const tab of tabState.tabs.filter((t) => t.collectionSlug === collectionSlug && t.requestName === name)) {
    closeTab(tab.id);
  }
}

function closeTabsForCollection(collectionSlug) {
  for (const tab of tabState.tabs.filter((t) => t.collectionSlug === collectionSlug)) {
    closeTab(tab.id);
  }
}

// Opens a new unsaved tab pre-filled with `id`'s current draft — a
// "Duplicate Tab". Left untitled (like openNewRequestTab) rather
// than auto-named: unlike sidebar Duplicate, this never touches the backend
// until the user explicitly saves it.
function duplicateTab(id) {
  if (id === tabState.activeId) captureActiveDraft();
  const source = tabState.tabs.find((t) => t.id === id);
  if (!source) return;
  const newId = tabState.nextId++;
  tabState.tabs.push({
    id: newId,
    collectionSlug: source.collectionSlug,
    requestName: "",
    folderId: source.folderId || null,
    draft: JSON.parse(JSON.stringify(source.draft)),
    dirty: true,
    response: null,
  });
  activateTab(newId);
}

function closeOtherTabs(id) {
  const keep = tabState.tabs.find((t) => t.id === id);
  if (!keep) return;
  tabState.tabs = [keep];
  if (tabState.activeId === id) {
    renderTabStrip();
  } else {
    tabState.activeId = null; // avoid capturing a draft for a tab we just removed
    activateTab(id);
  }
}

function closeAllTabs() {
  tabState.tabs = [];
  tabState.activeId = null;
  clearRequestPanel();
  renderTabStrip();
}

// Right-click context menu for an open tab — New Request /
// Duplicate Tab / Close (Other/All) / Reveal in Sidebar. "Reveal in Sidebar"
// only makes sense for a tab backed by a saved request, so it's omitted for
// an untitled ("Untitled") tab that has nothing in the sidebar yet.
function showTabContextMenu(event, tab) {
  const items = [
    { label: "New Request", onClick: () => openNewRequestTab(tab.collectionSlug, "GET") },
    { label: "Duplicate Tab", onClick: () => duplicateTab(tab.id) },
    { separator: true },
    { label: "Close Tab", onClick: () => closeTab(tab.id) },
    { label: "Close Other Tabs", onClick: () => closeOtherTabs(tab.id) },
    { label: "Close All Tabs", onClick: () => closeAllTabs() },
  ];
  if (tab.requestName) {
    items.push({ separator: true });
    items.push({ label: "Reveal in Sidebar", onClick: () => revealRequestInSidebar(tab.collectionSlug, tab.requestName) });
  }
  openFloatingMenu(items, (menu) => {
    const menuRect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(event.clientX, window.innerWidth - menuRect.width - 8));
    const top = Math.max(8, Math.min(event.clientY, window.innerHeight - menuRect.height - 8));
    menu.style.position = "fixed";
    menu.style.top = `${top}px`;
    menu.style.left = `${left}px`;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  ["method", "url", "bodyEditor"].forEach((id) => {
    $(id).addEventListener("input", markActiveTabDirty);
    $(id).addEventListener("change", markActiveTabDirty);
  });
  $("headersList").addEventListener("input", markActiveTabDirty);
  $("bodyParamsList").addEventListener("input", markActiveTabDirty);
  $("testsList").addEventListener("input", markActiveTabDirty);
  $("testsList").addEventListener("change", markActiveTabDirty);
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { isDoubleTabClick, requestToDraft, openRequestTab, openCollectionOverviewTab, activateTab, markActiveTabSaved, tabState };
}
