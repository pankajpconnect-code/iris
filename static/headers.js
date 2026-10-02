// Headers tab: same kv-row + bulk-edit interaction pattern as the Body
// Params tab (static/body-params.js) — split out of static/request-tabs.js
// to keep that file under this repo's 500-line cap.

function renderHeaderRows(headers) {
  // Force back to table view first, discarding whatever's in the bulk
  // textarea unconditionally — safe because the OUTGOING tab's own bulk
  // edits were already captured via collectAllHeaders() (which reads live
  // from the textarea while bulk mode is active) before a tab switch calls
  // this. Without this reset, activating a different tab left the previous
  // tab's stale bulk text on screen with a "Done" button that, if clicked,
  // overwrote the new tab's headers with the old tab's text.
  exitHeadersBulkEditUiOnly();
  const list = $("headersList");
  list.innerHTML = "";
  headers.forEach((header) => addHeaderRow(header.key, header.value, header.enabled !== false));
  updateHeaderCountBadge();
}

function isHeadersBulkEditActive() {
  return !$("headersBulkEditor").classList.contains("hidden");
}

function exitHeadersBulkEditUiOnly() {
  $("headersBulkEditor").classList.add("hidden");
  $("headersList").classList.remove("hidden");
  $("headerKvLabels").classList.remove("hidden");
  $("addHeaderBtn").classList.remove("hidden");
  $("bulkEditHeadersBtn").textContent = "Bulk Edit";
}

// Matches collectHeaders()'s own enabled+keyed filter, so the badge and what
// Send/Save actually use never disagree.
function updateHeaderCountBadge() {
  $("tabHeaderCount").textContent = collectHeaders().length || "";
}

function addHeaderRow(key = "", value = "", enabled = true) {
  const row = document.createElement("div");
  row.className = "kv-row" + (enabled ? "" : " row-disabled");
  row.innerHTML = `
    <input type="checkbox" class="hdr-enabled" ${enabled ? "checked" : ""} title="Include this header">
    <input class="hdr-key" type="text" placeholder="Key" value="${escapeAttr(key)}">
    <div class="var-input-wrap">
      <div class="var-input-highlight"></div>
      <input class="hdr-value" type="text" placeholder="Value" value="${escapeAttr(value)}">
    </div>
    <button class="icon-btn" type="button" title="Remove header">&times;</button>
  `;
  const enabledBox = row.querySelector(".hdr-enabled");
  enabledBox.addEventListener("change", () => row.classList.toggle("row-disabled", !enabledBox.checked));
  // Hover/highlight work without ever focusing the row, so they're attached
  // here at creation time rather than via the focusin delegation
  // autocomplete.js uses for the {{var}} autocomplete dropdown.
  if (typeof attachVarHighlight === "function") {
    attachVarHighlight(row.querySelector(".hdr-value"), row.querySelector(".var-input-highlight"));
  }
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    updateHeaderCountBadge();
    markActiveTabDirty();
  });
  $("headersList").appendChild(row);
}

function collectHeaders() {
  return collectAllHeaders().filter((header) => header.enabled).filter((header) => header.key);
}

// Includes disabled rows too — used for the Bulk Edit round-trip, where a
// disabled header still needs to survive the toggle (as a commented-out
// line). Reads live from the bulk textarea whenever it's the visible
// surface — otherwise Send/Save/tab-switch would silently act on the stale
// row DOM sitting hidden underneath it instead of what's actually on screen.
function collectAllHeaders() {
  if (isHeadersBulkEditActive()) return bulkTextToHeaders($("headersBulkEditor").value);
  return [...document.querySelectorAll("#headersList .kv-row")].map((row) => ({
    key: row.querySelector(".hdr-key").value.trim(),
    value: row.querySelector(".hdr-value").value.trim(),
    enabled: row.querySelector(".hdr-enabled").checked,
  }));
}

// --- headers bulk edit ---

// Bulk Edit convention: one "Key: Value" per line, a leading "// " comments
// a header out (disabled) without discarding it.
function headersToBulkText(headers) {
  return headers
    .filter((header) => header.key)
    .map((header) => `${header.enabled ? "" : "// "}${header.key}: ${header.value}`)
    .join("\n");
}

function bulkTextToHeaders(text) {
  return text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const disabled = line.startsWith("//");
    const content = (disabled ? line.slice(2) : line).trim();
    const sep = content.indexOf(":");
    const key = (sep === -1 ? content : content.slice(0, sep)).trim();
    const value = (sep === -1 ? "" : content.slice(sep + 1)).trim();
    return { key, value, enabled: !disabled };
  }).filter((header) => header.key);
}

function toggleHeadersBulkEdit() {
  if (isHeadersBulkEditActive()) {
    // renderHeaderRows() itself calls exitHeadersBulkEditUiOnly() — no need
    // to duplicate the hide/show toggling here.
    renderHeaderRows(bulkTextToHeaders($("headersBulkEditor").value));
    markActiveTabDirty();
  } else {
    $("headersBulkEditor").value = headersToBulkText(collectAllHeaders());
    $("headersList").classList.add("hidden");
    $("headerKvLabels").classList.add("hidden");
    $("addHeaderBtn").classList.add("hidden");
    $("headersBulkEditor").classList.remove("hidden");
    $("bulkEditHeadersBtn").textContent = "Done";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("addHeaderBtn").addEventListener("click", () => { addHeaderRow(); markActiveTabDirty(); });
  $("bulkEditHeadersBtn").addEventListener("click", toggleHeadersBulkEdit);
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    renderHeaderRows, collectHeaders, collectAllHeaders,
    headersToBulkText, bulkTextToHeaders,
  };
}
