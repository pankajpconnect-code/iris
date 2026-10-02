/* One-level folders within a collection: grouping/rendering, per-folder
 * collapse persistence, and folder CRUD + move-request actions.
 *
 * Split out of sidebar.js, which was already at this repo's 500-line limit —
 * the same reasoning sidebar-context-menu.js was split out for. Relies on
 * consoleState, $, escapeHtml, escapeAttr, postJson, putJson, irisPrompt
 * (all defined in sidebar.js/shared.js/modal.js, loaded before this file),
 * and is itself relied on by sidebar.js's renderCollectionTree and
 * sidebar-context-menu.js's folder/move menus — load this file BEFORE both.
 */

const FOLDER_COLLAPSE_PREFIX = "iris.folderCollapsed.";

// Mirrors resize.js's RESIZE_STORAGE_PREFIX + target.id convention (a
// per-target-id prefixed key) and runner-options-popover.js's
// boolean-flag-as-string convention — no new persistence pattern here.
function isFolderCollapsed(collectionSlug, folderId) {
  return localStorage.getItem(FOLDER_COLLAPSE_PREFIX + collectionSlug + "." + folderId) !== "false";
}

function setFolderCollapsed(collectionSlug, folderId, collapsed) {
  const key = FOLDER_COLLAPSE_PREFIX + collectionSlug + "." + folderId;
  if (collapsed) localStorage.removeItem(key);
  else localStorage.setItem(key, "false");
}

// Pure data-shaping: builds a tree of folder groups keyed by parentFolderId
// (collection_store.py omits the key entirely for a top-level folder rather
// than storing it as null, so `== null` catches both), each carrying its own
// direct `requests` (in `collection.requests` order) plus a `children`
// array of nested folder groups (in `collection.folders` order) — plus an
// "uncategorized" bucket for every request whose folderId doesn't match any
// real folder (self-healing display rather than a hard error; see design
// doc §4). A folder whose parentFolderId points nowhere gets the same
// self-healing treatment: it surfaces as a root rather than vanishing.
function groupRequestsByFolder(collection) {
  const folders = collection.folders || [];
  const requests = collection.requests || [];
  const groupById = new Map(folders.map((folder) => [folder.id, { folder, requests: [], children: [] }]));
  const folderGroups = [];
  for (const folder of folders) {
    const group = groupById.get(folder.id);
    const parentGroup = folder.parentFolderId == null ? undefined : groupById.get(folder.parentFolderId);
    if (parentGroup) parentGroup.children.push(group);
    else folderGroups.push(group);
  }
  const uncategorized = [];
  for (const request of requests) {
    const group = request.folderId ? groupById.get(request.folderId) : undefined;
    if (group) group.requests.push(request);
    else uncategorized.push(request);
  }
  return { folderGroups, uncategorized };
}

// Builds one `.req` row — extracted verbatim (same DOM shape and event
// wiring) from renderCollectionTree's old inline loop, so it can be reused
// for both folder-grouped and uncategorized requests.
function buildRequestRow(collection, request) {
  const row = document.createElement("div");
  const isActiveTab = typeof activeTab === "function" && (() => {
    const tab = activeTab();
    return tab && tab.collectionSlug === collection.slug && tab.requestName === request.name;
  })();
  row.className = "req" + (isActiveTab ? " active" : "");
  row.dataset.name = request.name;
  row.dataset.collectionSlug = collection.slug;
  const shortMethod = request.method === "DELETE" ? "DEL" : request.method;
  row.innerHTML = `<span class="m ${escapeAttr(request.method)}">${escapeHtml(shortMethod)}</span><span class="nm">${escapeHtml(request.name)}</span>
    <button class="req-dup-btn" type="button" title="Duplicate">&#10697;</button>`;
  row.addEventListener("click", () => selectConsoleRequest(row, collection.slug, request));
  row.querySelector(".nm").addEventListener("dblclick", (event) => {
    event.stopPropagation();
    startInlineRename(event.currentTarget, collection.slug, request);
  });
  row.querySelector(".req-dup-btn").addEventListener("click", (event) => {
    event.stopPropagation();
    duplicateRequestFromSidebar(collection.slug, request);
  });
  row.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    showRequestContextMenu(event, collection.slug, request);
  });
  return row;
}

// A folder's badge must reflect every request nested under it, not just the
// ones directly assigned to it — a pure container folder (e.g. Postman's
// "Core Endpoints", holding only subfolders) would otherwise always show 0.
function countRequestsInGroup(group) {
  let count = group.requests.length;
  for (const child of group.children) count += countRequestsInGroup(child);
  return count;
}

// Renders one folder group and recurses into its `children` — each child's
// element is appended inside this folder's own `.coll-folder-requests` box,
// so the existing `.coll-folder-requests{padding-left:10px}` rule (sidebar.css)
// stacks once per nesting level and indentation falls out of the box model
// rather than needing a new depth-based CSS rule.
function buildFolderGroupElement(collection, group) {
  const { folder, requests, children } = group;
  const collapsed = isFolderCollapsed(collection.slug, folder.id);
  const wrap = document.createElement("div");
  wrap.className = "coll-folder-group";

  const header = document.createElement("div");
  header.className = "coll-folder";
  header.innerHTML = `<span class="coll-name"><span class="chev${collapsed ? " collapsed" : ""}" title="Expand/collapse">&#9662;</span> ${escapeHtml(folder.name)}</span>
    <span class="coll-right"><button class="coll-add-btn" type="button" title="Add request to ${escapeAttr(folder.name)}">+</button><span>${countRequestsInGroup(group)}</span></span>`;
  header.querySelector(".chev").addEventListener("click", (event) => {
    event.stopPropagation();
    setFolderCollapsed(collection.slug, folder.id, !isFolderCollapsed(collection.slug, folder.id));
    renderCollectionTree(consoleState.collectionsCache);
  });
  header.querySelector(".coll-add-btn").addEventListener("click", (event) => {
    event.stopPropagation();
    showFloatingMethodMenu(event.currentTarget, (method) => openNewRequestTab(collection.slug, method, folder.id));
  });
  header.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    showFolderContextMenu(event, collection.slug, folder);
  });
  wrap.appendChild(header);

  const rowsBox = document.createElement("div");
  rowsBox.className = "coll-folder-requests" + (collapsed ? " collapsed" : "");
  for (const request of requests) rowsBox.appendChild(buildRequestRow(collection, request));
  for (const childGroup of children) rowsBox.appendChild(buildFolderGroupElement(collection, childGroup));
  wrap.appendChild(rowsBox);
  return wrap;
}

// Replaces renderCollectionTree's old inline per-request loop: returns the
// full `.coll-requests` element for one collection, with folder groups (if
// any) rendered above an "Uncategorized" section — or, when the collection
// has never used folders, the exact same flat list as before (no
// "Uncategorized" label noise for collections that don't use this feature).
// The label+rows are wrapped together in one `.coll-uncategorized-group` so
// filterCollectionTree (sidebar.js) can hide the whole thing at once when a
// search matches nothing in it — an orphan heading over zero rows is the
// same defect the per-folder header hiding exists to avoid, one level up.
function buildCollectionRequestsBox(collection) {
  const requestsBox = document.createElement("div");
  requestsBox.className = "coll-requests";
  const { folderGroups, uncategorized } = groupRequestsByFolder(collection);

  for (const group of folderGroups) {
    requestsBox.appendChild(buildFolderGroupElement(collection, group));
  }
  if (folderGroups.length && uncategorized.length) {
    const uncategorizedGroup = document.createElement("div");
    uncategorizedGroup.className = "coll-uncategorized-group";
    const label = document.createElement("div");
    label.className = "coll-uncategorized-label";
    label.textContent = "Uncategorized";
    uncategorizedGroup.appendChild(label);
    for (const request of uncategorized) uncategorizedGroup.appendChild(buildRequestRow(collection, request));
    requestsBox.appendChild(uncategorizedGroup);
  } else {
    for (const request of uncategorized) requestsBox.appendChild(buildRequestRow(collection, request));
  }
  return requestsBox;
}

async function createFolder(collectionSlug) {
  const name = ((await irisPrompt("New folder name:")) || "").trim();
  if (!name) return;
  try {
    await postJson(`/api/collections/${encodeURIComponent(collectionSlug)}/folders`, { name });
    await loadCollections();
  } catch (error) {
    alert(`Could not create folder: ${error.message}`);
  }
}

async function renameFolderPrompt(collectionSlug, folder) {
  const name = ((await irisPrompt("Rename folder:", folder.name)) || "").trim();
  if (!name || name === folder.name) return;
  try {
    await putJson(`/api/collections/${encodeURIComponent(collectionSlug)}/folders/${encodeURIComponent(folder.id)}`, { name });
    await loadCollections();
  } catch (error) {
    alert(`Rename failed: ${error.message}`);
  }
}

async function deleteFolderFromSidebar(collectionSlug, folder) {
  if (!(await irisConfirm(`Delete folder "${folder.name}"? Its requests move to Uncategorized — they are not deleted.`))) return;
  try {
    await deleteJson(`/api/collections/${encodeURIComponent(collectionSlug)}/folders/${encodeURIComponent(folder.id)}`);
    // The folder id is gone for good (uuid4, never reused) — drop its
    // collapse-state key too rather than leaving it to accumulate forever.
    // (collapsed=true is what removes the key now that collapsed is the
    // default, no-key state.)
    setFolderCollapsed(collectionSlug, folder.id, true);
    await loadCollections();
  } catch (error) {
    alert(`Delete failed: ${error.message}`);
  }
}

async function moveRequestToFolder(collectionSlug, requestName, folderId) {
  try {
    await putJson(
      `/api/collections/${encodeURIComponent(collectionSlug)}/requests/${encodeURIComponent(requestName)}/folder`,
      { folderId }
    );
    await loadCollections();
  } catch (error) {
    alert(`Move failed: ${error.message}`);
  }
}

// Re-parents a folder — hits the same /parent route collection_store.py's
// move_folder (and its _would_cycle guard) already backs; sidebar-context-menu.js
// keeps its own destination menu cycle-free by never offering the folder's own
// subtree, so this never actually needs to hit that guard in practice.
async function moveFolderToFolder(collectionSlug, folderId, parentFolderId) {
  try {
    await putJson(
      `/api/collections/${encodeURIComponent(collectionSlug)}/folders/${encodeURIComponent(folderId)}/parent`,
      { parentFolderId }
    );
    await loadCollections();
  } catch (error) {
    alert(`Move failed: ${error.message}`);
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { groupRequestsByFolder, countRequestsInGroup, isFolderCollapsed, setFolderCollapsed };
}
