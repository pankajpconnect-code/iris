/* Floating context menus for the collection sidebar — the shared
 * openFloatingMenu() shell plus the method-picker, request, and
 * collection context menus built on it.
 *
 * Split out of sidebar.js, which was over this repo's 500-line limit —
 * relies on activeFloatingMenuClose (declared in sidebar.js) and the
 * request/collection action functions defined in sidebar-request-actions.js
 * (renameSavedRequest, copyRequestAsJson, copyRequestAsCurl,
 * duplicateRequestFromSidebar, deleteRequestFromSidebar,
 * removeCollectionFromSidebar, shareRequestAsJsonFile,
 * startInlineRenameForRow) and curl-import.js (importRequestFromCurl), all
 * loaded before this one. */

// Shared floating-menu shell (reusing the .new-menu/.new-menu-item styling
// from the top toolbar's "+ New" menu): builds the menu from `items`
// ({render|label, onClick}), hands it to `place(menu)` to position, and wires
// the standard dismiss set every floating menu here needs — outside click,
// scroll, resize.
function openFloatingMenu(items, place) {
  if (activeFloatingMenuClose) activeFloatingMenuClose();
  const menu = document.createElement("div");
  menu.className = "new-menu floating";
  const closeMenu = () => {
    menu.remove();
    document.removeEventListener("click", closeOnOutsideClick, true);
    window.removeEventListener("scroll", closeMenu, true);
    window.removeEventListener("resize", closeMenu);
    if (activeFloatingMenuClose === closeMenu) activeFloatingMenuClose = null;
  };
  activeFloatingMenuClose = closeMenu;
  for (const entry of items) {
    if (entry.separator) {
      const sep = document.createElement("div");
      sep.className = "new-menu-sep";
      menu.appendChild(sep);
      continue;
    }
    const { label, render, onClick, danger } = entry;
    const item = document.createElement("div");
    item.className = "new-menu-item" + (danger ? " new-menu-item-danger" : "");
    if (render) item.innerHTML = render;
    else item.textContent = label;
    item.addEventListener("click", (event) => {
      event.stopPropagation();
      closeMenu();
      onClick();
    });
    menu.appendChild(item);
  }
  document.body.appendChild(menu);
  place(menu);
  const closeOnOutsideClick = (event) => {
    if (!menu.contains(event.target)) closeMenu();
  };
  document.addEventListener("click", closeOnOutsideClick, true);
  // The anchor's position is only valid for this render pass — scrolling or
  // resizing would leave the menu visually detached from its anchor, so
  // treat either as an implicit dismissal rather than tracking/repositioning.
  // Deferred past the current frame's scroll dispatch (not just a tick —
  // "run the scroll steps" precedes animation-frame callbacks in the same
  // update, so a single rAF is guaranteed to run after it, unlike a 0ms
  // timer): the click that opened this menu can itself be the tail of an
  // in-flight scroll (e.g. the browser auto-scrolling a partially-offscreen
  // "+" into view before delivering the click) — attaching these listeners
  // before that trailing scroll is dispatched would let it immediately close
  // the menu it just opened. The guard covers the menu having already been
  // closed (e.g. by a re-render) before this callback runs.
  requestAnimationFrame(() => {
    if (activeFloatingMenuClose !== closeMenu) return;
    window.addEventListener("scroll", closeMenu, true);
    window.addEventListener("resize", closeMenu);
  });
}

// Anchored method-picker menu for contexts — like the per-collection "+"
// button — where the target collection is already known, so "Collection"
// isn't offered as an option.
function showFloatingMethodMenu(anchor, onChoose) {
  const items = ["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => {
    const shortMethod = method === "DELETE" ? "DEL" : method;
    return {
      render: `<span class="m ${escapeAttr(method)}">${escapeHtml(shortMethod)}</span> Request`,
      onClick: () => onChoose(method),
    };
  });
  openFloatingMenu(items, (menu) => {
    const anchorRect = anchor.getBoundingClientRect();
    // Measured before `position:fixed` is applied below, while the menu is
    // still laid out per .new-menu's own position:absolute — relies on that
    // rule giving it a shrink-to-fit width; if that ever changes, this would
    // measure the full body width instead.
    const menuRect = menu.getBoundingClientRect();
    // Flip above the anchor if there isn't room below, and clamp
    // horizontally — position:fixed can't extend the document, so an
    // unclamped menu near the sidebar's bottom or a viewport edge would
    // otherwise render off-screen.
    const left = Math.max(8, Math.min(anchorRect.left, window.innerWidth - menuRect.width - 8));
    const top = anchorRect.bottom + menuRect.height + 4 > window.innerHeight
      ? anchorRect.top - menuRect.height - 4
      : anchorRect.bottom + 4;
    menu.style.position = "fixed";
    menu.style.top = `${Math.max(8, top)}px`;
    menu.style.left = `${left}px`;
  });
}

// Right-click context menu for a sidebar request row — Share /
// Rename / Copy / Duplicate / Delete, reachable via the standard right-click
// convention in addition to the existing hover Duplicate icon button.
function showRequestContextMenu(event, collectionSlug, request) {
  openFloatingMenu(
    [
      { label: "Share (export as .json)", onClick: () => shareRequestAsJsonFile(request) },
      { separator: true },
      { label: "Rename", onClick: () => startInlineRenameForRow(collectionSlug, request) },
      { label: "Copy as JSON", onClick: () => copyRequestAsJson(request) },
      { label: "Copy as cURL", onClick: () => copyRequestAsCurl(request) },
      { label: "Duplicate", onClick: () => duplicateRequestFromSidebar(collectionSlug, request) },
      { label: "Move to Folder", onClick: () => showMoveToFolderMenu(event, collectionSlug, request) },
      { separator: true },
      { label: "Delete", danger: true, onClick: () => deleteRequestFromSidebar(collectionSlug, request) },
    ],
    (menu) => {
      const menuRect = menu.getBoundingClientRect();
      const left = Math.max(8, Math.min(event.clientX, window.innerWidth - menuRect.width - 8));
      const top = Math.max(8, Math.min(event.clientY, window.innerHeight - menuRect.height - 8));
      menu.style.position = "fixed";
      menu.style.top = `${top}px`;
      menu.style.left = `${left}px`;
    }
  );
}

// Two spaces per depth level for indentation in a plain-text menu label —
// matches how deep the folder sits in the tree groupRequestsByFolder
// (folders.js) already builds, so a grandchild folder reads visibly deeper
// than its parent in the destination list.
const FOLDER_MENU_INDENT = "  ";

// Walks the nested folder tree groupRequestsByFolder (folders.js) builds,
// listing every folder in parent-before-children order with its depth —
// used for the request-move menu, where a folder's own children remain
// valid destinations even when the folder itself is filtered out below.
function listAllFolderGroups(groups, depth, out) {
  for (const group of groups) {
    out.push({ folder: group.folder, depth });
    listAllFolderGroups(group.children, depth + 1, out);
  }
  return out;
}

// Same walk, but stops descending the moment it reaches `excludeId`. A
// folder can never be moved into itself or one of its own descendants —
// that is what a cycle is — and pruning that one subtree during the same
// walk that already builds the tree is sufficient to guarantee it: no
// separate cycle-detection pass needed alongside collection_store.py's own
// _would_cycle guard on the backend, which stays as the last line of
// defense if this list is ever stale.
function listFolderGroupsExcludingSubtree(groups, depth, excludeId, out) {
  for (const group of groups) {
    if (group.folder.id === excludeId) continue;
    out.push({ folder: group.folder, depth });
    listFolderGroupsExcludingSubtree(group.children, depth + 1, excludeId, out);
  }
  return out;
}

// A second floating menu (opened from within showRequestContextMenu's own
// onClick, after the first menu has already closed itself) listing the
// collection's full folder tree, indented by depth, plus an "Uncategorized"
// option when the request is currently in one — reuses the same
// fixed-position-at-the-original-click shell every other context menu here
// uses.
function showMoveToFolderMenu(event, collectionSlug, request) {
  const collection = consoleState.collectionsCache.find((c) => c.slug === collectionSlug);
  const { folderGroups } = groupRequestsByFolder(collection || {});
  const items = [];
  if (request.folderId) {
    items.push({ label: "Uncategorized (remove from folder)", onClick: () => moveRequestToFolder(collectionSlug, request.name, null) });
  }
  for (const { folder, depth } of listAllFolderGroups(folderGroups, 0, [])) {
    if (folder.id === request.folderId) continue;
    items.push({ label: FOLDER_MENU_INDENT.repeat(depth) + folder.name, onClick: () => moveRequestToFolder(collectionSlug, request.name, folder.id) });
  }
  if (!items.length) {
    // No real action to offer — an inert menu item that looks clickable but
    // does nothing is its own silent-failure smell, so surface this as a
    // message instead of a fake menu entry.
    alert("No folders yet — right-click the collection to add one.");
    return;
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

// Same shell again, but for re-parenting a folder itself — lists the tree
// with the folder-being-moved's own subtree pruned (see
// listFolderGroupsExcludingSubtree above) plus a "Top level" option when it
// currently has a parent, and skips offering its current parent again (a
// no-op move, same reasoning showMoveToFolderMenu already applies to a
// request's current folder).
function showMoveFolderMenu(event, collectionSlug, folder) {
  const collection = consoleState.collectionsCache.find((c) => c.slug === collectionSlug);
  const { folderGroups } = groupRequestsByFolder(collection || {});
  const items = [];
  if (folder.parentFolderId != null) {
    items.push({ label: "Top level (remove from parent)", onClick: () => moveFolderToFolder(collectionSlug, folder.id, null) });
  }
  for (const { folder: destFolder, depth } of listFolderGroupsExcludingSubtree(folderGroups, 0, folder.id, [])) {
    if (destFolder.id === folder.parentFolderId) continue;
    items.push({ label: FOLDER_MENU_INDENT.repeat(depth) + destFolder.name, onClick: () => moveFolderToFolder(collectionSlug, folder.id, destFolder.id) });
  }
  if (!items.length) {
    alert("No other folders yet to move into.");
    return;
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

function showCollectionContextMenu(event, collection) {
  openFloatingMenu(
    [
      { label: "New Folder", onClick: () => createFolder(collection.slug) },
      { label: "Import from curl", onClick: () => importRequestFromCurl(collection.slug) },
      { separator: true },
      { label: "Remove from Iris", danger: true, onClick: () => removeCollectionFromSidebar(collection) },
    ],
    (menu) => {
      const menuRect = menu.getBoundingClientRect();
      const left = Math.max(8, Math.min(event.clientX, window.innerWidth - menuRect.width - 8));
      const top = Math.max(8, Math.min(event.clientY, window.innerHeight - menuRect.height - 8));
      menu.style.position = "fixed";
      menu.style.top = `${top}px`;
      menu.style.left = `${left}px`;
    }
  );
}

// Right-click context menu for a folder header row — Rename / Delete,
// same fixed-position-at-the-click shell as every other menu here.
function showFolderContextMenu(event, collectionSlug, folder) {
  openFloatingMenu(
    [
      { label: "Rename", onClick: () => renameFolderPrompt(collectionSlug, folder) },
      { label: "Move to Folder", onClick: () => showMoveFolderMenu(event, collectionSlug, folder) },
      { separator: true },
      { label: "Delete", danger: true, onClick: () => deleteFolderFromSidebar(collectionSlug, folder) },
    ],
    (menu) => {
      const menuRect = menu.getBoundingClientRect();
      const left = Math.max(8, Math.min(event.clientX, window.innerWidth - menuRect.width - 8));
      const top = Math.max(8, Math.min(event.clientY, window.innerHeight - menuRect.height - 8));
      menu.style.position = "fixed";
      menu.style.top = `${top}px`;
      menu.style.left = `${left}px`;
    }
  );
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { listAllFolderGroups, listFolderGroupsExcludingSubtree };
}
