/* Runner scope picker — the searchable multi-select combobox for choosing
 * which request(s)/folder/collection a run targets, plus the "Requests in
 * scope" checklist panel.
 *
 * Split out of runner-view.js, which was over this repo's 500-line limit —
 * this is self-contained enough to live on its own, relying on the $ /
 * escapeHtml / escapeAttr helpers (shared.js) and runnerState (declared in
 * runner-view.js, loaded before this one).
 */

let runnerScopeIndex = [];
async function fetchVarsFor(slug) {
  if (!slug) return {};
  try {
    const response = await fetch(`/api/collections/${encodeURIComponent(slug)}/vars`);
    const data = await response.json();
    return (response.ok && data.variables) || {};
  } catch {
    return {};
  }
}

// --- scope picker: searchable, multi-select combobox (a plain <select>
// doesn't scale past a handful of requests — no filtering, and the browser
// auto-scrolls the list to the checked option on open, hiding the top of a
// long collection). "Quick pick" rows (single request/folder/whole
// collection) select-and-close as before; individual request rows carry a
// checkbox and stay open, so picking 2-3 specific requests out of 90+ is a
// few clicks in one place rather than a separate panel the picker itself
// gives no hint exists. Both write the same runnerState.scope/excludedNames
// the checklist panel below already reads, so they stay in sync either way.
// Builds its own floating box (not autocomplete.js's shared renderDropdown)
// since "stays open on click" is a different interaction than every other
// caller of that helper.

let runnerScopeDropdownEl = null;
// The query the currently-open dropdown was last rendered with — needed to
// refresh it in place after a checkbox toggle without reading the search
// input's live value, which updateRunnerScopeInputLabel() overwrites with a
// summary label ("GET Loan Account" / "3 of 95 requests selected") the
// moment any selection changes, so it's no longer the search text by then.
let runnerScopeDropdownQuery = "";
// See the click listener that reads this, further down — set right before
// a bulk-button mousedown tears down and rebuilds the dropdown box.
let suppressNextRunnerScopeOutsideClick = false;

function refreshRunnerRequestOptions() {
  const previousValue = $("runnerRequestSelect").dataset.value || "";
  const wasMultiSelect = previousValue.startsWith("multi:");
  runnerScopeIndex = [];

  for (const collection of consoleState.collectionsCache || []) {
    const requests = collection.requests || [];
    if (!requests.length) continue;

    addRunnerScopeEntry(`collection:${collection.slug}:`, "(whole collection)", collection.name,
      { type: "collection", slug: collection.slug, name: null });

    // Real Folder records (id/name/parentFolderId — see collection_store.py),
    // not names derived by chopping " / " off request names: Phase 3b stops
    // baking folder paths into request names, so that derivation would find
    // zero folders on any freshly-imported collection.
    for (const folder of collection.folders || []) {
      addRunnerScopeEntry(`folder:${collection.slug}:${folder.name}`, folder.name, collection.name,
        { type: "folder", slug: collection.slug, name: folder.name });
    }

    for (const request of requests) {
      addRunnerScopeEntry(`request:${collection.slug}:${request.name}`, request.name, collection.name,
        { type: "request", slug: collection.slug, name: request.name }, request.method);
    }
  }

  if (wasMultiSelect && runnerState.scope) {
    // A specific-requests pick isn't one of runnerScopeIndex's entries (see
    // updateRunnerScopeInputLabel) — preserve it across a rebuild instead of
    // falling through to "not found -> clear the scope".
    updateRunnerScopeInputLabel();
    renderRunnerScopeChecklist();
    return;
  }
  const restored = runnerScopeIndex.find((e) => e.value === previousValue);
  if (restored) selectRunnerScope(restored);
  else onRunnerRequestChange();
}

function addRunnerScopeEntry(value, label, collectionName, scope, method) {
  runnerScopeIndex.push({ value, label, collectionName, scope, method });
}

function closeRunnerScopeDropdown() {
  if (runnerScopeDropdownEl) runnerScopeDropdownEl.remove();
  runnerScopeDropdownEl = null;
}

function openRunnerScopeDropdown() {
  const input = $("runnerRequestSelect");
  const query = input.value === (input.dataset.label || "") ? "" : input.value;
  renderRunnerScopeDropdownContent(query);
}

// Focus/click entry point (as opposed to re-opening while already focused,
// e.g. after typing): if the box is currently just displaying the selection
// summary ("GET Loan Account" / "3 of 95 requests selected") rather than
// something the user actively typed, clear it so they can start a new search
// immediately instead of having to select-all-delete the old summary text
// first. Safe to clear unconditionally here — the blur handler below already
// restores dataset.label if focus leaves without a new pick being made, so
// clicking in and straight back out is a no-op from the user's perspective.
function focusRunnerScopeInputForSearch() {
  const input = $("runnerRequestSelect");
  if (input.value === (input.dataset.label || "") && input.value !== "") input.value = "";
  openRunnerScopeDropdown();
}

function renderRunnerScopeDropdownContent(query) {
  runnerScopeDropdownQuery = query;
  const input = $("runnerRequestSelect");
  const scrollTop = runnerScopeDropdownEl ? runnerScopeDropdownEl.scrollTop : 0;
  closeRunnerScopeDropdown();

  const needle = query.trim().toLowerCase();
  const matchesNeedle = (e) => !needle || e.label.toLowerCase().includes(needle) || e.collectionName.toLowerCase().includes(needle);
  const groupEntries = runnerScopeIndex.filter((e) => e.scope.type !== "request" && matchesNeedle(e)).slice(0, 20);
  const requestEntries = runnerScopeIndex.filter((e) => e.scope.type === "request" && matchesNeedle(e)).slice(0, 60);

  const box = document.createElement("div");
  box.className = "var-autocomplete runner-scope-dropdown";
  const rect = input.getBoundingClientRect();
  box.style.left = `${rect.left + window.scrollX}px`;
  box.style.top = `${rect.bottom + window.scrollY + 2}px`;
  box.style.minWidth = `${Math.max(rect.width, 340)}px`;

  const groupRowsHtml = groupEntries.map((entry) => `
    <div class="var-autocomplete-row runner-scope-group-row" data-value="${escapeAttr(entry.value)}">
      <span class="var-autocomplete-name">${escapeHtml(entry.label)}</span>
      <span class="var-autocomplete-value">${escapeHtml(entry.collectionName)}</span>
    </div>
  `).join("");
  const requestRowsHtml = requestEntries
    .map((entry) => buildRunnerScopeDropdownRequestRowHtml(entry, isRunnerRequestSelected(entry.scope.slug, entry.scope.name)))
    .join("");

  const individualSectionLabel = requestEntries.length ? `
    <div class="runner-scope-dropdown-section-label runner-scope-dropdown-section-label-row">
      <span>Select individual requests — check as many as you need, this stays open</span>
      <span class="runner-scope-dropdown-bulk-actions">
        <button type="button" class="icon-btn" data-bulk="all" title="Check every request matching this search">Select all</button>
        <button type="button" class="icon-btn" data-bulk="none" title="Uncheck every request matching this search">Clear</button>
      </span>
    </div>
  ` : `<div class="runner-scope-dropdown-section-label">Select individual requests — check as many as you need, this stays open</div>`;

  box.innerHTML = `
    ${groupRowsHtml ? `<div class="runner-scope-dropdown-section-label">Quick pick (selects and closes)</div>${groupRowsHtml}` : ""}
    ${individualSectionLabel}
    ${requestRowsHtml || '<div class="meta" style="padding:8px 10px">No matches</div>'}
  `;
  document.body.appendChild(box);
  runnerScopeDropdownEl = box;
  box.scrollTop = scrollTop;

  for (const row of box.querySelectorAll(".runner-scope-group-row")) {
    row.addEventListener("mousedown", (event) => {
      event.preventDefault(); // don't blur the input — selectRunnerScope closes explicitly
      const entry = runnerScopeIndex.find((e) => e.value === row.dataset.value);
      selectRunnerScope(entry);
    });
  }
  for (const checkbox of box.querySelectorAll("input[type=checkbox]")) {
    checkbox.addEventListener("change", () => {
      toggleRunnerScopeRequest(checkbox.dataset.slug, checkbox.dataset.name, checkbox.checked);
    });
  }
  const bulkAllBtn = box.querySelector('[data-bulk="all"]');
  const bulkNoneBtn = box.querySelector('[data-bulk="none"]');
  if (bulkAllBtn) bulkAllBtn.addEventListener("mousedown", (event) => {
    event.preventDefault(); // don't blur the input, same reason as the group rows above
    suppressNextRunnerScopeOutsideClick = true;
    bulkSetRunnerScopeRequests(requestEntries, true);
  });
  if (bulkNoneBtn) bulkNoneBtn.addEventListener("mousedown", (event) => {
    event.preventDefault();
    suppressNextRunnerScopeOutsideClick = true;
    bulkSetRunnerScopeRequests(requestEntries, false);
  });
}

// Applies checked/unchecked to every currently-filtered ("Select all" /
// "Clear") request row in one shot. Restricted to a single collection — the
// already-established scope's if there is one, else the first match's —
// because one runner scope can only ever point at one collection at a time;
// applyRunnerScopeInclusion would otherwise whipsaw scope between
// collections as this loop crossed from one to another in a broad,
// unfiltered search. Mutates state via the shared helper in a tight loop
// (safe — see that helper's own comment) and renders once at the end, not
// once per item.
function bulkSetRunnerScopeRequests(requestEntries, checked) {
  if (!requestEntries.length) return;
  // "Clear" with nothing chosen yet has nothing to clear — falling through
  // would promote scope from "nothing chosen" to "collection A, 0 of N
  // selected", a scope the user never actually picked.
  if (!checked && !runnerState.scope) return;
  const targetSlug = (runnerState.scope && runnerState.scope.type === "collection")
    ? runnerState.scope.slug : requestEntries[0].scope.slug;
  for (const entry of requestEntries) {
    if (entry.scope.slug !== targetSlug) continue;
    applyRunnerScopeInclusion(entry.scope.slug, entry.scope.name, checked);
  }
  renderRunnerScopeSelectionSurfaces();
}

function isRunnerRequestSelected(slug, name) {
  if (!runnerState.scope || runnerState.scope.slug !== slug) return false;
  return requestNamesInScope(runnerState.scope).includes(name) && !runnerState.excludedNames.has(name);
}

// State mutation only, no rendering — shared by the single-checkbox change
// handler and the bulk Select all/Clear buttons, which call this in a loop
// and render once afterward instead of once per item.
//
// Deliberately synchronous, not async — this used to `await fetchVarsFor()`
// mid-function while resetting shared state (runnerState.scope/excludedNames).
// Checking several boxes in quick succession (the entire point of this UI)
// meant a second click's handler could run while the first was still
// suspended on that fetch: the second call would see the just-reset scope,
// mutate the SAME excludedNames Set, and render before the first click's own
// toggle had been applied — a checkbox would flip with no new click the
// moment the first fetch resolved. Keeping this function synchronous makes
// each click's state update complete in one turn, so clicks can never
// interleave; the vars fetch (only needed later, at Run time) now happens in
// the background instead of gating the toggle.
function applyRunnerScopeInclusion(slug, name, checked) {
  const isSameCollectionScope = runnerState.scope && runnerState.scope.type === "collection" && runnerState.scope.slug === slug;
  if (!isSameCollectionScope) {
    // Starting a fresh pick-specific-requests selection — not merging with
    // whatever scope (or none) was set before, matching "I want to run
    // exactly these 2-3" rather than trying to combine with a prior pick.
    runnerState.scope = { type: "collection", slug, name: null };
    runnerState.excludedNames = new Set(requestNamesInScope(runnerState.scope));
    // Fire-and-forget, but guarded: if the scope has since moved to a
    // different collection by the time this resolves (another toggle,
    // fired before this fetch landed), drop the result instead of pairing
    // this collection's vars with a different scope. runRunnerBatch()
    // re-fetches and awaits fresh vars anyway before actually using them, so
    // this is just keeping the in-between state honest, not the last line
    // of defense.
    fetchVarsFor(slug).then((vars) => {
      if (runnerState.scope && runnerState.scope.slug === slug) {
        runnerState.vars = vars;
        runnerState.varsSlug = slug;
      }
    });
  }
  if (checked) runnerState.excludedNames.delete(name);
  else runnerState.excludedNames.add(name);
}

// Renders every surface that shows scope-selection state: the input label,
// the persistent "Requests in scope" checklist, and — if it's currently
// open — the scope-picker dropdown itself. A checkbox's own native click
// only updates ITS OWN checkbox in the DOM; every OTHER row in an
// already-open dropdown was rendered at some earlier point (e.g. while
// "(whole collection)" was selected and every row showed checked) and goes
// stale the instant the underlying scope/exclusions change — nothing else
// ever told those other rows to re-render, which is exactly how a leftover
// "Prepayment" checkbox could still show checked after picking only "GET
// Loan Account".
function renderRunnerScopeSelectionSurfaces() {
  updateRunnerScopeInputLabel();
  renderRunnerScopeChecklist();
  if (runnerScopeDropdownEl) renderRunnerScopeDropdownContent(runnerScopeDropdownQuery);
}

function toggleRunnerScopeRequest(slug, name, checked) {
  applyRunnerScopeInclusion(slug, name, checked);
  renderRunnerScopeSelectionSurfaces();
}

function updateRunnerScopeInputLabel() {
  const input = $("runnerRequestSelect");
  const names = requestNamesInScope(runnerState.scope);
  const included = names.filter((n) => !runnerState.excludedNames.has(n));
  const label = included.length === 1 ? included[0] : `${included.length} of ${names.length} requests selected`;
  input.value = label;
  // Deliberately NOT "collection:<slug>:" — that value belongs to the
  // "(whole collection)" quick-pick entry in runnerScopeIndex. Reusing it
  // would make refreshRunnerRequestOptions()'s restore-by-value logic treat
  // a specific 2-of-94 pick as if it were "whole collection" and silently
  // re-select everything the next time the picker rebuilds (e.g. switching
  // away from and back to the Runner tab).
  input.dataset.value = `multi:${runnerState.scope.slug}:`;
  input.dataset.label = label;
}

async function selectRunnerScope(entry) {
  const input = $("runnerRequestSelect");
  input.value = entry.label;
  input.dataset.value = entry.value;
  input.dataset.label = entry.label;
  closeRunnerScopeDropdown();
  await onRunnerRequestChange();
}

async function onRunnerRequestChange() {
  const input = $("runnerRequestSelect");
  const entry = runnerScopeIndex.find((e) => e.value === input.dataset.value);
  runnerState.scope = entry ? entry.scope : null;
  runnerState.excludedNames = new Set();
  const targetSlug = entry ? entry.scope.slug : "";
  const vars = targetSlug ? await fetchVarsFor(targetSlug) : {};
  // Guard against the scope having moved on again while that fetch was in
  // flight — same reasoning as applyRunnerScopeInclusion's own fetch.
  if ((runnerState.scope ? runnerState.scope.slug : "") === targetSlug) {
    runnerState.vars = vars;
    runnerState.varsSlug = targetSlug;
  }
  if (!entry) {
    // No restorable prior pick (e.g. a collection rebuild couldn't find
    // whatever it used to point at) — clear the box's own display too, or
    // it would keep showing a label for a scope that no longer exists.
    input.value = "";
    input.dataset.value = "";
    input.dataset.label = "";
  }
  renderRunnerScopeChecklist();
}

// --- checklist: uncheck individual requests within a folder/collection scope ---

// Mirrors run_orchestrator.py's _folder_closure_by_name/expand_scope on the
// backend — same folderId + parentFolderId walk, so the "Requests in scope"
// checklist previews exactly what the Runner will actually execute instead
// of a client-side approximation that could drift from it.
function folderDescendantClosure(folders, folderId) {
  const closure = new Set([folderId]);
  const frontier = [folderId];
  while (frontier.length) {
    const current = frontier.pop();
    for (const folder of folders) {
      if (folder.parentFolderId === current && !closure.has(folder.id)) {
        closure.add(folder.id);
        frontier.push(folder.id);
      }
    }
  }
  return closure;
}

function requestsInScope(scope) {
  if (!scope) return [];
  const collection = (consoleState.collectionsCache || []).find((c) => c.slug === scope.slug);
  const requests = (collection && collection.requests) || [];
  if (scope.type === "request") return requests.filter((r) => r.name === scope.name);
  if (scope.type === "folder") {
    const folders = (collection && collection.folders) || [];
    const root = folders.find((f) => f.name === scope.name);
    if (!root) return [];
    const closure = folderDescendantClosure(folders, root.id);
    return requests.filter((r) => closure.has(r.folderId));
  }
  return requests;
}

function requestNamesInScope(scope) {
  return requestsInScope(scope).map((r) => r.name);
}

// Mirrors folders.js's sidebar request rows (same "DEL" shorthand, same `.m
// ${method}` badge class) so every place a request's method shows up —
// sidebar, checklist, and the scope-picker dropdown below — reads consistently.
function methodBadgeHtml(method) {
  const shortMethod = method === "DELETE" ? "DEL" : method;
  return `<span class="m ${escapeAttr(method || "")}">${escapeHtml(shortMethod || "")}</span>`;
}

// `selected` marks the row currently previewed in the Response-card pane
// (see runnerScopePreviewedName below) — without it, any re-render (All/None,
// a checkbox toggle, a filter keystroke) would rebuild every row from scratch
// with no memory of which one the pane belongs to.
function buildRunnerScopeCheckRowHtml(request, checked, selected) {
  return `
    <div class="runner-scope-check-row${selected ? " sel" : ""}" data-name="${escapeAttr(request.name)}" data-name-lower="${escapeAttr(request.name.toLowerCase())}">
      <input type="checkbox" ${checked ? "checked" : ""} data-name="${escapeAttr(request.name)}">
      ${methodBadgeHtml(request.method)}
      <span class="mono">${escapeHtml(request.name)}</span>
    </div>
  `;
}

// Same row shape as the scope-picker dropdown's own markup (see
// renderRunnerScopeDropdownContent) — pulled out as a pure builder, same
// reason buildRunnerScopeCheckRowHtml above is: testable without a DOM.
function buildRunnerScopeDropdownRequestRowHtml(entry, checked) {
  return `
    <div class="runner-scope-check-row runner-scope-dropdown-check-row">
      <input type="checkbox" ${checked ? "checked" : ""} data-slug="${escapeAttr(entry.scope.slug)}" data-name="${escapeAttr(entry.scope.name)}">
      ${methodBadgeHtml(entry.method)}
      <span class="mono">${escapeHtml(entry.label)}</span>
      <span class="meta">${escapeHtml(entry.collectionName)}</span>
    </div>
  `;
}

// The name of the request currently previewed in the Response-card pane, or
// null if nothing from this checklist is being previewed (e.g. the pane is
// showing an executed result row instead — see clearRunnerScopePreview()).
let runnerScopePreviewedName = null;

function renderRunnerScopeChecklist() {
  const panel = $("runnerScopeChecklist");
  const requests = requestsInScope(runnerState.scope);
  const names = requests.map((r) => r.name);
  if (!runnerState.scope || runnerState.scope.type === "request" || names.length < 2) {
    panel.classList.add("hidden");
    return;
  }
  $("runnerScopeChecklistBody").innerHTML = requests
    .map((request) => buildRunnerScopeCheckRowHtml(
      request, !runnerState.excludedNames.has(request.name), request.name === runnerScopePreviewedName,
    ))
    .join("");
  for (const box of $("runnerScopeChecklistBody").querySelectorAll("input[type=checkbox]")) {
    box.addEventListener("change", () => {
      if (box.checked) runnerState.excludedNames.delete(box.dataset.name);
      else runnerState.excludedNames.add(box.dataset.name);
      updateRunnerScopeChecklistMeta(names);
      // Keep the search box's label and the (possibly still open) dropdown
      // in sync too — not just this panel's own meta text — same staleness
      // gap the All/None buttons had.
      updateRunnerScopeInputLabel();
      if (runnerScopeDropdownEl) renderRunnerScopeDropdownContent(runnerScopeDropdownQuery);
      // Checking/unchecking IS how a user picks a request in this list — it
      // must preview too, not just clicking the row's bare text next to it,
      // or ticking the box a user is looking straight at appears to do
      // nothing in the Response-card pane.
      const request = requests.find((r) => r.name === box.dataset.name);
      if (request) previewRunnerScopeRequest(box.closest(".runner-scope-check-row"), request);
    });
  }
  // Selecting a row (its text, or its checkbox — see the checkbox handler
  // above) previews that request's method/URL/headers in the same
  // Response-card pane the executed run rows use — the request hasn't run
  // yet, so showRunnerRequestPreview() (runner-row-detail.js) fills only the
  // Request/Headers tabs instead of the run-result shape showRunnerRowDetail()
  // expects.
  for (const row of $("runnerScopeChecklistBody").children) {
    row.addEventListener("click", (event) => {
      if (event.target.closest("input[type=checkbox]")) return;
      const request = requests.find((r) => r.name === row.dataset.name);
      if (request) previewRunnerScopeRequest(row, request);
    });
  }
  applyRunnerScopeChecklistFilter($("runnerScopeChecklistSearch").value);
  updateRunnerScopeChecklistMeta(names);
  panel.classList.remove("hidden");
}

function previewRunnerScopeRequest(row, request) {
  runnerScopePreviewedName = request.name;
  clearRunnerRowSelection();
  row.classList.add("sel");
  showRunnerRequestPreview(request);
}

// Called from runner-row-detail.js's selectRunnerListRow when the pane
// switches to an executed result instead — otherwise the next checklist
// re-render (All/None, a checkbox toggle) would resurrect a highlight on a
// checklist row the pane no longer has anything to do with.
function clearRunnerScopePreview() {
  runnerScopePreviewedName = null;
}

function updateRunnerScopeChecklistMeta(names) {
  const includedCount = names.filter((n) => !runnerState.excludedNames.has(n)).length;
  $("runnerScopeChecklistMeta").textContent = `${includedCount}/${names.length} request(s) selected`;
}

// With a 90+ request collection, "click None then check the 2-3 you want" is
// only usable if you can find those 2-3 without scrolling past the rest —
// same problem the scope picker itself had, same fix (filter, don't scroll).
function applyRunnerScopeChecklistFilter(query) {
  const needle = query.trim().toLowerCase();
  for (const row of $("runnerScopeChecklistBody").children) {
    row.classList.toggle("hidden", !!needle && !row.dataset.nameLower.includes(needle));
  }
}

function scopeWithExclusions() {
  if (!runnerState.scope) return null;
  return { ...runnerState.scope, excludedNames: [...runnerState.excludedNames] };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    requestsInScope, requestNamesInScope, buildRunnerScopeCheckRowHtml, buildRunnerScopeDropdownRequestRowHtml,
  };
}
