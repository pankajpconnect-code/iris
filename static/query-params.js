// Params tab: a pure VIEW over the URL field's query string — there is no
// separate `params` field anywhere in the saved/sent request (design doc
// docs/superpowers/specs/2026-09-14-query-params-tab-design.md §2.1). A
// disabled row survives save/reload by staying in the query string with its
// key prefixed `~` — an RFC 3986 *unreserved* character, so it's never
// percent-encoded away — mirroring the Headers tab's own `// `-prefix
// convention for "disabled but not discarded" (addHeaderRow/headersToBulkText,
// headers.js), just applied inline since a query string has no
// per-line structure to comment out.
//
// Only "&" and "=" inside a raw key/value are ever escaped (to %26/%3D)
// when writing into the URL, and un-escaped the same way when reading back
// out — nothing else is touched. This keeps {{var}} tokens and any
// already-percent-encoded text in the URL completely unaffected; see the
// design doc §3 for why a general encode/decode step was rejected.

// "~" is escaped too, everywhere it appears (not just a leading position) —
// it's the disabled-row marker (below), so a real key/value containing a
// literal "~" must never reach the URL unescaped, or it would be
// misread as disabled the next time the URL is parsed back into rows.
function escapeParamDelims(text) {
  return String(text ?? "").replace(/&/g, "%26").replace(/=/g, "%3D").replace(/~/g, "%7E");
}

function unescapeParamDelims(text) {
  return String(text ?? "").replace(/%26/gi, "&").replace(/%3D/gi, "=").replace(/%7E/gi, "~");
}

function splitUrlAtQuery(url) {
  const raw = url || "";
  const i = raw.indexOf("?");
  return i === -1 ? { base: raw, query: "" } : { base: raw.slice(0, i), query: raw.slice(i + 1) };
}

// Mirrors bulkTextToHeaders' shape (headers.js): one entry per
// "&"-separated segment, a leading "~" on the key disables it without
// discarding it.
function parseQueryString(query) {
  return String(query || "").split("&").filter(Boolean).map((segment) => {
    const eq = segment.indexOf("=");
    const rawKey = eq === -1 ? segment : segment.slice(0, eq);
    const rawValue = eq === -1 ? "" : segment.slice(eq + 1);
    const disabled = rawKey.startsWith("~");
    const key = unescapeParamDelims(disabled ? rawKey.slice(1) : rawKey);
    const value = unescapeParamDelims(rawValue);
    return { key, value, enabled: !disabled };
  });
}

function paramsFromUrl(url) {
  return parseQueryString(splitUrlAtQuery(url).query);
}

// Mirrors headersToBulkText/bulkTextToHeaders' filter(key) convention: a row
// with no key yet cannot be represented in the URL and does not survive.
function serializeQueryString(params) {
  return params
    .filter((p) => p.key)
    .map((p) => `${p.enabled ? "" : "~"}${escapeParamDelims(p.key)}=${escapeParamDelims(p.value)}`)
    .join("&");
}

function urlWithParams(url, params) {
  const { base } = splitUrlAtQuery(url);
  const query = serializeQueryString(params);
  return query ? `${base}?${query}` : base;
}

// --- params bulk edit ---
// Same convention as headersToBulkText/bulkTextToHeaders (headers.js):
// one "key=value" per line, a leading "// " comments a param out (disabled)
// without discarding it. A DIFFERENT surface from the `~`-in-URL marker
// above — this one is a multi-line textarea and can use Headers' own
// per-line convention directly.
function paramsToBulkText(params) {
  return params
    .filter((p) => p.key)
    .map((p) => `${p.enabled ? "" : "// "}${p.key}=${p.value}`)
    .join("\n");
}

function bulkTextToParams(text) {
  return text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const disabled = line.startsWith("//");
    const content = (disabled ? line.slice(2) : line).trim();
    const eq = content.indexOf("=");
    const key = (eq === -1 ? content : content.slice(0, eq)).trim();
    const value = (eq === -1 ? "" : content.slice(eq + 1)).trim();
    return { key, value, enabled: !disabled };
  }).filter((p) => p.key);
}

// --- params UI ---

function renderParamRows(params) {
  exitParamsBulkEditUiOnly();
  const list = $("paramsList");
  list.innerHTML = "";
  params.forEach((p) => addParamRow(p.key, p.value, p.enabled !== false));
  updateParamCountBadge();
}

function isParamsBulkEditActive() {
  return !$("paramsBulkEditor").classList.contains("hidden");
}

function exitParamsBulkEditUiOnly() {
  $("paramsBulkEditor").classList.add("hidden");
  $("paramsList").classList.remove("hidden");
  $("paramKvLabels").classList.remove("hidden");
  $("addParamBtn").classList.remove("hidden");
  $("bulkEditParamsBtn").textContent = "Bulk Edit";
}

function updateParamCountBadge() {
  $("tabParamCount").textContent = collectAllParams().filter((p) => p.key && p.enabled).length || "";
}

function addParamRow(key = "", value = "", enabled = true) {
  const row = document.createElement("div");
  row.className = "kv-row" + (enabled ? "" : " row-disabled");
  row.innerHTML = `
    <input type="checkbox" class="prm-enabled" ${enabled ? "checked" : ""} title="Include this param">
    <input class="prm-key" type="text" placeholder="Key" value="${escapeAttr(key)}">
    <input class="prm-value" type="text" placeholder="Value" value="${escapeAttr(value)}">
    <button class="icon-btn" type="button" title="Remove param">&times;</button>
  `;
  const enabledBox = row.querySelector(".prm-enabled");
  enabledBox.addEventListener("change", () => {
    row.classList.toggle("row-disabled", !enabledBox.checked);
    syncUrlFromParams();
  });
  row.querySelector(".prm-key").addEventListener("input", syncUrlFromParams);
  row.querySelector(".prm-value").addEventListener("input", syncUrlFromParams);
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    syncUrlFromParams();
  });
  $("paramsList").appendChild(row);
}

// Includes disabled rows too, same reasoning as collectAllHeaders (request-
// tabs.js) — reads live from the bulk textarea whenever it's the visible
// surface, otherwise a param edit made just before a tab switch would act on
// stale DOM sitting hidden underneath it.
function collectAllParams() {
  if (isParamsBulkEditActive()) return bulkTextToParams($("paramsBulkEditor").value);
  return [...document.querySelectorAll("#paramsList .kv-row")].map((row) => ({
    key: row.querySelector(".prm-key").value.trim(),
    value: row.querySelector(".prm-value").value.trim(),
    enabled: row.querySelector(".prm-enabled").checked,
  }));
}

function toggleParamsBulkEdit() {
  if (isParamsBulkEditActive()) {
    renderParamRows(bulkTextToParams($("paramsBulkEditor").value));
    syncUrlFromParams();
  } else {
    $("paramsBulkEditor").value = paramsToBulkText(collectAllParams());
    $("paramsList").classList.add("hidden");
    $("paramKvLabels").classList.add("hidden");
    $("addParamBtn").classList.add("hidden");
    $("paramsBulkEditor").classList.remove("hidden");
    $("bulkEditParamsBtn").textContent = "Done";
  }
}

// --- URL <-> Params sync ---
// See design doc §3 for the full rationale. Summary: Params -> URL is
// immediate on every row edit (never re-renders rows, so the row/input
// being edited keeps focus/cursor); URL -> Params re-parses only on the
// url field's native "change" event (blur/Enter, not every keystroke).
// Setting an <input>'s .value via JS never fires "input"/"change" itself,
// so syncUrlFromParams writing $("url").value cannot loop back into
// renderParamsTabFromUrl below.

function syncUrlFromParams() {
  $("url").value = urlWithParams($("url").value, collectAllParams());
  if (typeof renderUrlHighlight === "function") renderUrlHighlight();
  updateParamCountBadge();
  if (typeof markActiveTabDirty === "function") markActiveTabDirty();
}

function renderParamsTabFromUrl() {
  renderParamRows(paramsFromUrl($("url").value));
}

// $("url").value alone is stale while Params Bulk Edit is open and not yet
// "Done" — the same gap collectAllHeaders() already closes for Headers by
// reading live from its own bulk textarea whenever it's the visible
// surface. The URL field has no separate draft array to read through
// instead, so this is the URL-specific equivalent: wherever "the current
// true URL" is needed for save/send/tab-capture, call this instead of
// reading $("url").value directly, or an in-progress (not yet "Done"d)
// param bulk edit is silently lost the moment the tab is switched, saved,
// or sent — exactly the failure mode this feature must not repeat.
function currentUrlWithPendingParamEdits() {
  return urlWithParams($("url").value, collectAllParams());
}

document.addEventListener("DOMContentLoaded", () => {
  $("addParamBtn").addEventListener("click", () => {
    addParamRow();
    if (typeof markActiveTabDirty === "function") markActiveTabDirty();
  });
  $("bulkEditParamsBtn").addEventListener("click", toggleParamsBulkEdit);
  $("url").addEventListener("change", renderParamsTabFromUrl);
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    escapeParamDelims, unescapeParamDelims, splitUrlAtQuery, parseQueryString, paramsFromUrl,
    serializeQueryString, urlWithParams, paramsToBulkText, bulkTextToParams,
  };
}
