const consoleState = {
  selectedRequest: null,
  selectedCollection: null,
  selectedCollectionSlug: "",
  vars: {},
  collectionsCache: [],
  collapsedCollections: new Set(),
};

// Tracks the currently-open floating method menu (there's ever only one) so
// other code — a sidebar re-render, or opening a second menu — can dismiss
// it deliberately instead of leaving it an orphan or relying on the next
// stray click to clean it up.
let activeFloatingMenuClose = null;

async function loadCollections(preserveSelection = true) {
  const tree = $("collectionTree");
  try {
    const listResponse = await fetch("/api/collections");
    const listData = await listResponse.json();
    if (!listResponse.ok) {
      throw new Error(listData.error || "Failed to list collections");
    }
    const collections = await Promise.all(
      (listData.collections || []).map((summary) =>
        fetch(`/api/collections/${encodeURIComponent(summary.slug)}`).then((response) => response.json())
      )
    );
    consoleState.collectionsCache = collections;
    renderCollectionTree(collections);
    if (preserveSelection && consoleState.selectedCollectionSlug) {
      const stillThere = collections.find((c) => c.slug === consoleState.selectedCollectionSlug);
      if (stillThere) consoleState.selectedCollection = stillThere;
    }
    if (typeof refreshRunnerRequestOptions === "function") refreshRunnerRequestOptions();
  } catch (error) {
    tree.innerHTML = `<div class="console-empty">Failed to load collections: ${escapeHtml(error.message)}</div>`;
  }
}

function renderCollectionTree(collections) {
  // Any open per-collection floating menu is anchored to a .coll-add-btn
  // that's about to be torn down and rebuilt below — dismiss it first so it
  // can't survive as an orphan pointing at a removed element.
  if (activeFloatingMenuClose) activeFloatingMenuClose();
  const tree = $("collectionTree");
  tree.innerHTML = "";
  if (!collections.length) {
    tree.innerHTML = '<div class="console-empty">No collections yet. Import a collection export or create one.</div>';
    return;
  }
  for (const collection of collections) {
    const requests = collection.requests || [];
    const collapsed = consoleState.collapsedCollections.has(collection.slug);
    const group = document.createElement("div");
    group.className = "coll-group";
    group.dataset.slug = collection.slug;

    const header = document.createElement("div");
    header.className = "coll";
    if (collection.slug === consoleState.selectedCollectionSlug) header.classList.add("active-collection");
    header.innerHTML = `<span class="coll-name"><span class="chev${collapsed ? " collapsed" : ""}" title="Expand/collapse">&#9662;</span> ${escapeHtml(collection.name)}</span>
      <span class="coll-right"><button class="coll-add-btn" type="button" title="Add request to ${escapeAttr(collection.name)}">+</button><span>${requests.length}</span></span>`;
    header.querySelector(".chev").addEventListener("click", (event) => {
      event.stopPropagation();
      toggleCollectionCollapsed(collection.slug);
    });
    header.querySelector(".coll-add-btn").addEventListener("click", (event) => {
      event.stopPropagation();
      showFloatingMethodMenu(event.currentTarget, (method) => openNewRequestTab(collection.slug, method));
    });
    header.addEventListener("click", () => selectCollection(collection.slug));
    header.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      showCollectionContextMenu(event, collection);
    });
    group.appendChild(header);

    // Folder grouping/rendering lives in folders.js (loaded before this
    // file) — split out to stay under this file's 500-line limit, the same
    // reasoning sidebar-context-menu.js was already split out for.
    const requestsBox = buildCollectionRequestsBox(collection);
    if (collapsed) requestsBox.classList.add("collapsed");
    group.appendChild(requestsBox);
    tree.appendChild(group);
  }
  // Re-render is triggered from many places (collapse toggle, tab switch,
  // collection select) that know nothing about the search box — re-apply the
  // active filter every time so it isn't silently dropped mid-search.
  const search = $("collectionSearch");
  if (search && search.value.trim()) filterCollectionTree(search.value);
  justToggledSlug = null;
}

// Set immediately before a manual chevron click's re-render, and consumed
// (see renderCollectionTree) by the very next filterCollectionTree pass — so
// a collection the user just explicitly collapsed/expanded during an active
// search isn't silently forced back open by that search's own
// reveal-matches behavior (see shouldForceSearchOpen below).
let justToggledSlug = null;

function toggleCollectionCollapsed(slug) {
  if (consoleState.collapsedCollections.has(slug)) {
    consoleState.collapsedCollections.delete(slug);
  } else {
    consoleState.collapsedCollections.add(slug);
  }
  justToggledSlug = slug;
  renderCollectionTree(consoleState.collectionsCache);
}

// Per-request actions — rename, duplicate, delete, copy-as-JSON/cURL,
// share-as-file, and reveal-in-sidebar (selectConsoleRequest,
// requestNamesInCollection, uniqueRequestName, promptDuplicateName,
// revealRequestInSidebar, duplicateRequestFromSidebar, startInlineRename,
// startInlineRenameForRow, renameSavedRequest, deleteRequestFromSidebar,
// removeCollectionFromSidebar, copyRequestAsJson, requestToCurl,
// copyRequestAsCurl, shareRequestAsJsonFile) — live in
// sidebar-request-actions.js, split out to stay under this file's 500-line
// limit, the same reasoning folders.js and sidebar-context-menu.js were
// already split out for. That file is loaded right after this one.

// Pure so it's unit-testable without jsdom (same reasoning as
// groupRequestsByFolder in folders.js). A collection the user just
// explicitly toggled via its chevron shouldn't be immediately overridden
// back open by the search's own reveal-matches behavior.
function shouldForceSearchOpen(needle, anyVisible, slug, justToggledSlug) {
  return !!needle && anyVisible && slug !== justToggledSlug;
}

function filterCollectionTree(query) {
  const needle = query.trim().toLowerCase();
  document.querySelectorAll(".coll-group").forEach((group) => {
    const header = group.querySelector(".coll");
    const requestsBox = group.querySelector(".coll-requests");
    let anyVisible = false;
    requestsBox.querySelectorAll(".req").forEach((row) => {
      const match = !needle || row.dataset.name.toLowerCase().includes(needle);
      row.classList.toggle("hidden", !match);
      if (match) anyVisible = true;
    });
    // A folder's own collapsed state is independent of its collection's —
    // force each one open individually if it still contains a visible match
    // after the loop above, same reasoning as the collection-level
    // "search-forced-open" below (and folders.js's buildFolderGroupElement
    // applies "collapsed" the same way renderCollectionTree does here).
    requestsBox.querySelectorAll(".coll-folder-group").forEach((folderGroup) => {
      const folderHeader = folderGroup.querySelector(".coll-folder");
      const folderBox = folderGroup.querySelector(".coll-folder-requests");
      const hasVisibleMatch = !!folderBox.querySelector(".req:not(.hidden)");
      folderBox.classList.toggle("search-forced-open", !!needle && hasVisibleMatch);
      folderHeader.classList.toggle("hidden", !!needle && !hasVisibleMatch);
    });
    // Same reasoning one level up: the "Uncategorized" label+rows are one
    // group (folders.js's buildCollectionRequestsBox) — hide the whole thing
    // together rather than leaving an orphan heading over zero visible rows.
    requestsBox.querySelectorAll(".coll-uncategorized-group").forEach((uncategorizedGroup) => {
      const hasVisibleMatch = !!uncategorizedGroup.querySelector(".req:not(.hidden)");
      uncategorizedGroup.classList.toggle("hidden", !!needle && !hasVisibleMatch);
    });
    header.classList.toggle("hidden", !!needle && !anyVisible);
    // While searching, force a collapsed collection open so its matches stay
    // visible; the collapsed state itself is untouched and resumes once the
    // search is cleared. Suppressed for one pass right after a manual
    // chevron toggle (justToggledSlug) so that action stays visible instead
    // of being immediately undone.
    requestsBox.classList.toggle(
      "search-forced-open",
      shouldForceSearchOpen(needle, anyVisible, group.dataset.slug, justToggledSlug)
    );
  });
}

// A collection with nothing to show shouldn't pop open an empty Overview
// tab — same "no affordance for no content" reasoning as this file used to
// apply to the (now-removed) info-icon button. Pure so it's unit-testable
// without the DOM-heavy renderCollectionTree call chain around it.
function shouldOpenOverviewTab(collection) {
  return !!(collection && collection.description);
}

// Shared by createCollection, ensureDefaultCollectionSlug, and the sidebar's
// collection-header click handler — all three need to switch the active
// collection and refresh every panel that depends on it.
function selectCollection(slug) {
  consoleState.selectedCollectionSlug = slug;
  consoleState.selectedCollection = consoleState.collectionsCache.find((c) => c.slug === slug) || null;
  renderCollectionTree(consoleState.collectionsCache);
  loadConsoleVars(slug);
  renderAuthTab();
  updateTopbarPills();
  if (shouldOpenOverviewTab(consoleState.selectedCollection)) {
    openCollectionOverviewTab(consoleState.selectedCollection);
  }
}

async function createCollection() {
  const name = ((await irisPrompt("New collection name:")) || "").trim();
  if (!name) return;
  try {
    const data = await postJson("/api/collections", { name });
    await loadCollections();
    selectCollection(data.slug);
  } catch (error) {
    alert(`Could not create collection: ${error.message}`);
  }
}

async function importCollectionFile(file) {
  const text = await file.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    alert("That file is not valid JSON.");
    return;
  }
  const rawName = (json.info && json.info.name) || file.name.replace(/\.json$/i, "");
  const slugGuess = slugify(rawName) || "import";
  try {
    const result = await postJson(`/api/collections/${encodeURIComponent(slugGuess)}/import`, json);
    await loadCollections();
    // loadCollections() re-fetches full per-collection data (including
    // description) via GET /api/collections/<slug> — the import response
    // itself carries only {slug, imported, ...}, no description.
    const imported = consoleState.collectionsCache.find((c) => c.slug === result.slug);
    if (shouldOpenOverviewTab(imported)) openCollectionOverviewTab(imported);
    if (result.untranslatedScripts && result.untranslatedScripts.length) {
      alert(`Imported ${result.imported} request(s). ${result.untranslatedScripts.length} script(s) could not be auto-translated into Tests rows and were skipped — check the original collection for those.`);
    }
    if (result.unsupportedBodyModes && result.unsupportedBodyModes.length) {
      const names = result.unsupportedBodyModes.map((u) => `${u.request} (${u.mode})`).join(", ");
      alert(`Imported ${result.imported} request(s). ${result.unsupportedBodyModes.length} request(s) use a body mode this app doesn't send yet and imported with an empty body: ${names}`);
    }
    if (result.unsupportedAuthTypes && result.unsupportedAuthTypes.length) {
      const names = result.unsupportedAuthTypes.map((u) => `${u.request} (${u.type})`).join(", ");
      alert(`Imported ${result.imported} request(s). ${result.unsupportedAuthTypes.length} request(s) use an auth type this app doesn't support yet and imported with no auth: ${names}`);
    }
  } catch (error) {
    alert(`Import failed: ${error.message}`);
  }
}

async function exportCollection() {
  const slug = consoleState.selectedCollectionSlug;
  if (!slug) {
    alert("Select a collection in the sidebar first.");
    return;
  }
  const response = await fetch(`/api/collections/${encodeURIComponent(slug)}/export`);
  const data = await response.json();
  if (!response.ok) {
    alert(data.error || "Export failed");
    return;
  }
  await saveTextFile(`${slug}.collection.json`, JSON.stringify(data, null, 2));
}

// Starting a new request with no collection open yet should not block the
// user with a prompt or alert — this data model requires every request to
// belong to a collection, so one is created automatically here instead.
async function ensureDefaultCollectionSlug() {
  if (consoleState.selectedCollectionSlug) return consoleState.selectedCollectionSlug;
  // Compare on slug, not display name — the backend's uniqueness check is on
  // the slugified name, so e.g. "New Collection" and "new  collection!" both
  // occupy the "new-collection" slug and would otherwise collide silently.
  const existingSlugs = new Set(consoleState.collectionsCache.map((c) => c.slug));
  let name = "New Collection";
  for (let n = 2; existingSlugs.has(slugify(name)); n++) name = `New Collection ${n}`;
  const data = await postJson("/api/collections", { name });
  await loadCollections();
  selectCollection(data.slug);
  return data.slug;
}

async function startNewRequest(method) {
  try {
    openNewRequestTab(await ensureDefaultCollectionSlug(), method);
  } catch (error) {
    alert(`Could not start a new request: ${error.message}`);
  }
}

// Floating context menus (openFloatingMenu, showFloatingMethodMenu,
// showRequestContextMenu, showCollectionContextMenu) live in
// sidebar-context-menu.js — split out to stay under this repo's 500-line
// limit. That file is loaded right after this one.

function setupNewMenu() {
  const menu = $("newMenu");
  const wrap = $("newMenuBtn").closest(".new-menu-wrap");
  $("newMenuBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    menu.classList.toggle("hidden");
  });
  menu.querySelectorAll(".new-menu-item").forEach((item) => {
    item.addEventListener("click", () => {
      menu.classList.add("hidden");
      if (item.dataset.action === "collection") createCollection();
      else startNewRequest(item.dataset.method);
    });
  });
  // Capture phase + explicit containment check, so this can't be defeated by
  // a stopPropagation() elsewhere in the app (e.g. the collection chevron or
  // a tab's close button) the way a bubble-phase document listener would be.
  document.addEventListener("click", (event) => {
    if (!wrap.contains(event.target)) menu.classList.add("hidden");
  }, true);
}

document.addEventListener("DOMContentLoaded", () => {
  setupNewMenu();
  $("importCollectionBtn").addEventListener("click", () => $("importCollectionFile").click());
  $("importCollectionFile").addEventListener("change", (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (file) importCollectionFile(file);
  });
  $("exportCollectionBtn").addEventListener("click", exportCollection);
  $("collectionSearch").addEventListener("input", (event) => filterCollectionTree(event.target.value));
  loadCollections();
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { shouldForceSearchOpen, shouldOpenOverviewTab };
}
