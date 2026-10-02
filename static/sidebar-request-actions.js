/* Per-request actions triggered from the sidebar row and its context menu:
 * rename (inline and via menu), duplicate, delete, copy-as-JSON/cURL,
 * share-as-standalone-file, and reveal-in-sidebar.
 *
 * Split out of sidebar.js, which was over this repo's 500-line limit — the
 * same reasoning folders.js and sidebar-context-menu.js were already split
 * out for. Relies on consoleState, $ (sidebar.js/shared.js), escapeHtml
 * (shared.js), irisPrompt/irisConfirm (modal.js), irisClipboardWrite,
 * saveTextFile (save_bridge.js), postJson/putJson (shared.js), slugify
 * (shared.js), filterCollectionTree/renderCollectionTree/loadCollections
 * (sidebar.js), and renameOpenTabs/closeTabsForRequest/closeTabsForCollection/
 * openRequestTab (tabs.js) — all defined in files loaded before this one.
 * Relied on in turn by folders.js's buildRequestRow (selectConsoleRequest,
 * startInlineRename, duplicateRequestFromSidebar) and
 * sidebar-context-menu.js's request/collection context menus — load this
 * file BEFORE both. */

// Opens the request as its own tab — see tabs.js for the tab
// state machine. Kept as a thin entry point since sidebar row clicks and the
// Runner's request picker both call this same name.
function selectConsoleRequest(row, collectionSlug, request) {
  openRequestTab(collectionSlug, request);
}

function requestNamesInCollection(collectionSlug) {
  const collection = consoleState.collectionsCache.find((c) => c.slug === collectionSlug);
  return new Set((collection?.requests || []).map((r) => r.name));
}

// Mirrors the " (n)" disambiguation collection_io/_import_collection already
// uses for same-named requests within one import batch — applied here so a
// duplicate's *suggested* name never silently overwrites an existing
// request (collection_store.save_request overwrites by name).
function uniqueRequestName(collectionSlug, baseName) {
  const existing = requestNamesInCollection(collectionSlug);
  if (!existing.has(baseName)) return baseName;
  let n = 2;
  while (existing.has(`${baseName} (${n})`)) n++;
  return `${baseName} (${n})`;
}

// Shared by duplicateRequestFromSidebar and duplicateConsoleRequest (in
// request-tabs.js) — prompts for a name pre-filled with a collision-free
// suggestion, but still allows an explicit overwrite if the user types (or
// keeps) a name that collides, after a confirmation. Safe to call with any
// `suggested` value, not just a pre-vetted collision-free one — the check
// below is against the live collection state, not against `suggested`.
async function promptDuplicateName(collectionSlug, suggested) {
  const name = ((await irisPrompt("Name for the duplicate:", suggested)) || "").trim();
  if (!name) return null;
  if (requestNamesInCollection(collectionSlug).has(name)) {
    if (!(await irisConfirm(`A request named "${name}" already exists in this collection — overwrite it?`))) return null;
  }
  return name;
}

// Called by the open tab's "Reveal in Sidebar" context menu item (tabs.js).
// Expands the owning collection and clears any active search filter first —
// either one would otherwise leave the matching row hidden — then scrolls to
// it and flashes it so it's easy to spot.
function revealRequestInSidebar(collectionSlug, requestName) {
  const search = $("collectionSearch");
  if (search && search.value.trim()) {
    search.value = "";
    filterCollectionTree("");
  }
  if (consoleState.collapsedCollections.has(collectionSlug)) {
    consoleState.collapsedCollections.delete(collectionSlug);
    renderCollectionTree(consoleState.collectionsCache);
  }
  const row = document.querySelector(
    `.req[data-collection-slug="${CSS.escape(collectionSlug)}"][data-name="${CSS.escape(requestName)}"]`
  );
  if (!row) return;
  row.scrollIntoView({ block: "nearest" });
  row.classList.add("req-reveal-flash");
  setTimeout(() => row.classList.remove("req-reveal-flash"), 1200);
}

async function duplicateRequestFromSidebar(collectionSlug, request) {
  const name = await promptDuplicateName(collectionSlug, uniqueRequestName(collectionSlug, `${request.name} copy`));
  if (!name) return;
  try {
    await postJson(`/api/collections/${encodeURIComponent(collectionSlug)}/requests`, { ...request, name });
    await loadCollections();
  } catch (error) {
    alert(`Duplicate failed: ${error.message}`);
  }
}

// Swaps a request row's name <span> for an inline <input> — triggered by
// double-clicking the name or by the context menu's
// Rename item. Enter/blur commits if the name actually changed; Escape
// cancels and puts the original span back without any network call.
function startInlineRename(nameSpan, collectionSlug, request) {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "nm-rename-input";
  input.value = request.name;
  nameSpan.replaceWith(input);
  input.focus();
  input.select();
  let cancelled = false;
  input.addEventListener("mousedown", (event) => event.stopPropagation());
  input.addEventListener("click", (event) => event.stopPropagation());
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); input.blur(); }
    else if (event.key === "Escape") { event.preventDefault(); cancelled = true; input.blur(); }
  });
  input.addEventListener("blur", async () => {
    if (cancelled) { renderCollectionTree(consoleState.collectionsCache); return; }
    const newName = input.value.trim();
    if (!newName || newName === request.name) { renderCollectionTree(consoleState.collectionsCache); return; }
    await renameSavedRequest(collectionSlug, request.name, newName);
  });
}

// Finds a row by (collectionSlug, name) via the data attributes set in
// renderCollectionTree — used by the context menu's Rename item, which
// (unlike the double-click handler) doesn't already have the row element in
// scope.
function startInlineRenameForRow(collectionSlug, request) {
  const row = document.querySelector(
    `.req[data-collection-slug="${CSS.escape(collectionSlug)}"][data-name="${CSS.escape(request.name)}"]`
  );
  const nameSpan = row && row.querySelector(".nm");
  // Row exists but has no .nm — it's already mid-rename (an inline <input>
  // sits there instead), reachable via double-click-to-rename → right-click
  // the same row before blurring → Rename from the menu.
  if (!nameSpan) return;
  startInlineRename(nameSpan, collectionSlug, request);
}

// Renames in place via PUT — collection_store.rename_request updates the
// name without touching the request's position in the list. Shared by the
// sidebar's inline rename and the open tab's own double-click-to-rename
// (tabs.js) so both stay consistent with each other and with whatever's
// currently open.
async function renameSavedRequest(collectionSlug, oldName, newName) {
  if (newName === oldName) return;
  if (requestNamesInCollection(collectionSlug).has(newName)) {
    if (!(await irisConfirm(`A request named "${newName}" already exists in this collection — overwrite it?`))) {
      renderCollectionTree(consoleState.collectionsCache);
      return;
    }
  }
  try {
    await putJson(
      `/api/collections/${encodeURIComponent(collectionSlug)}/requests/${encodeURIComponent(oldName)}`,
      { name: newName }
    );
    if (typeof renameOpenTabs === "function") renameOpenTabs(collectionSlug, oldName, newName);
    if (consoleState.selectedRequest && consoleState.selectedCollectionSlug === collectionSlug
        && consoleState.selectedRequest.name === oldName) {
      consoleState.selectedRequest.name = newName;
    }
    await loadCollections();
  } catch (error) {
    alert(`Rename failed: ${error.message}`);
    renderCollectionTree(consoleState.collectionsCache);
  }
}

async function deleteRequestFromSidebar(collectionSlug, request) {
  if (!(await irisConfirm(`Delete "${request.name}"? This cannot be undone.`))) return;
  try {
    await fetch(`/api/collections/${encodeURIComponent(collectionSlug)}/requests/${encodeURIComponent(request.name)}`, { method: "DELETE" });
    if (typeof closeTabsForRequest === "function") closeTabsForRequest(collectionSlug, request.name);
    await loadCollections();
  } catch (error) {
    alert(`Delete failed: ${error.message}`);
  }
}

async function removeCollectionFromSidebar(collection) {
  if (!(await irisConfirm(`Remove "${collection.name}" from Iris? It stays on disk — re-import the same export to bring it back.`))) return;
  try {
    await postJson(`/api/collections/${encodeURIComponent(collection.slug)}/archive`, { archived: true });
    if (typeof closeTabsForCollection === "function") closeTabsForCollection(collection.slug);
    if (consoleState.selectedCollectionSlug === collection.slug) {
      consoleState.selectedCollectionSlug = "";
      consoleState.selectedCollection = null;
    }
    await loadCollections();
  } catch (error) {
    alert(`Remove failed: ${error.message}`);
  }
}

async function copyRequestAsJson(request) {
  try {
    await irisClipboardWrite(JSON.stringify(request, null, 2));
  } catch (error) {
    alert(`Could not copy: ${error.message}`);
  }
}

// {{vars}} are left as literal placeholders (not resolved) — this is meant
// for sharing the request's shape, not a runnable-as-is command.
function requestToCurl(request) {
  const escapeSingleQuotes = (value) => String(value || "").replace(/'/g, "'\\''");
  const parts = [`curl -X ${request.method || "GET"} '${escapeSingleQuotes(request.url)}'`];
  for (const header of request.headers || []) {
    // enabled !== false, not a plain truthy check — headers saved before
    // the enabled flag existed have no such property at all and should
    // still count as enabled.
    if (!header.key || header.enabled === false) continue;
    parts.push(`-H '${escapeSingleQuotes(header.key)}: ${escapeSingleQuotes(header.value)}'`);
  }
  // A urlencoded-mode request has nothing useful in `body` (that field
  // belongs to raw mode) — reading it here would silently emit a cURL
  // command with no body at all instead of one that actually reproduces
  // the request.
  if (request.bodyMode === "urlencoded") {
    // encodeURIComponent emits %20 for a space vs. the real send path's
    // urlencode()'s "+" — both decode to a space, so this is cosmetic only.
    const encoded = (request.bodyParams || [])
      .filter((p) => p.key && p.enabled !== false)
      .map((p) => `${encodeURIComponent(p.key)}=${encodeURIComponent(p.value || "")}`)
      .join("&");
    if (encoded) parts.push(`-d '${escapeSingleQuotes(encoded)}'`);
  } else if (request.body) {
    parts.push(`-d '${escapeSingleQuotes(request.body)}'`);
  }
  return parts.join(" \\\n  ");
}

async function copyRequestAsCurl(request) {
  try {
    await irisClipboardWrite(requestToCurl(request));
  } catch (error) {
    alert(`Could not copy: ${error.message}`);
  }
}

// "Share" for a fully local tool with no cloud/team backend: export just
// this one request as a standalone .json file via a native Save As dialog,
// the same save_bridge pattern exportCollection() uses for a whole
// collection — so the file lands where the user points it, not ~/Downloads.
async function shareRequestAsJsonFile(request) {
  await saveTextFile(`${slugify(request.name) || "request"}.json`, JSON.stringify(request, null, 2));
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { requestNamesInCollection, uniqueRequestName, requestToCurl };
}
