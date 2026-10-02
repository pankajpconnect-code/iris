// Body-mode KV editor for x-www-form-urlencoded bodies — same kv-row +
// bulk-edit interaction pattern as the Headers tab (static/headers.js),
// split into its own file to keep request-tabs.js under this repo's 500-line
// limit (it was already at 460/500 before this feature).

function renderBodyParamRows(params) {
  exitBodyParamsBulkEditUiOnly();
  const list = $("bodyParamsList");
  list.innerHTML = "";
  (params || []).forEach((param) => addBodyParamRow(param.key, param.value, param.enabled !== false));
}

function isBodyParamsBulkEditActive() {
  return !$("bodyParamsBulkEditor").classList.contains("hidden");
}

function exitBodyParamsBulkEditUiOnly() {
  $("bodyParamsBulkEditor").classList.add("hidden");
  $("bodyParamsList").classList.remove("hidden");
  $("bodyParamsKvLabels").classList.remove("hidden");
  $("addBodyParamBtn").classList.remove("hidden");
  $("bulkEditBodyParamsBtn").textContent = "Bulk Edit";
}

function addBodyParamRow(key = "", value = "", enabled = true) {
  const row = document.createElement("div");
  row.className = "kv-row" + (enabled ? "" : " row-disabled");
  row.innerHTML = `
    <input type="checkbox" class="bp-enabled" ${enabled ? "checked" : ""} title="Include this param">
    <input class="bp-key" type="text" placeholder="Key" value="${escapeAttr(key)}">
    <input class="bp-value" type="text" placeholder="Value" value="${escapeAttr(value)}">
    <button class="icon-btn" type="button" title="Remove param">&times;</button>
  `;
  const enabledBox = row.querySelector(".bp-enabled");
  enabledBox.addEventListener("change", () => row.classList.toggle("row-disabled", !enabledBox.checked));
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    markActiveTabDirty();
  });
  $("bodyParamsList").appendChild(row);
}

function collectBodyParams() {
  return collectAllBodyParams().filter((param) => param.enabled).filter((param) => param.key);
}

// Includes disabled rows too — same reason collectAllHeaders() does: Save
// must not silently drop a disabled param, and the backend (not the
// collector) is the one place that strips disabled entries before an
// actual outgoing send.
function collectAllBodyParams() {
  if (isBodyParamsBulkEditActive()) return bulkTextToBodyParams($("bodyParamsBulkEditor").value);
  return [...document.querySelectorAll("#bodyParamsList .kv-row")].map((row) => ({
    key: row.querySelector(".bp-key").value.trim(),
    value: row.querySelector(".bp-value").value.trim(),
    enabled: row.querySelector(".bp-enabled").checked,
  }));
}

// Same "Key: Value" per line, "// " disables convention as the Headers tab's
// Bulk Edit (headersToBulkText/bulkTextToHeaders, headers.js) — reused
// deliberately rather than a `key=value` form-encoded-looking convention, so
// a user who already learned one Bulk Edit format doesn't learn a second,
// differently-delimited one for the other tab that has the same feature.
function bodyParamsToBulkText(params) {
  return params
    .filter((param) => param.key)
    .map((param) => `${param.enabled ? "" : "// "}${param.key}: ${param.value}`)
    .join("\n");
}

function bulkTextToBodyParams(text) {
  return text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const disabled = line.startsWith("//");
    const content = (disabled ? line.slice(2) : line).trim();
    const sep = content.indexOf(":");
    const key = (sep === -1 ? content : content.slice(0, sep)).trim();
    const value = (sep === -1 ? "" : content.slice(sep + 1)).trim();
    return { key, value, enabled: !disabled };
  }).filter((param) => param.key);
}

function toggleBodyParamsBulkEdit() {
  if (isBodyParamsBulkEditActive()) {
    renderBodyParamRows(bulkTextToBodyParams($("bodyParamsBulkEditor").value));
    markActiveTabDirty();
  } else {
    $("bodyParamsBulkEditor").value = bodyParamsToBulkText(collectAllBodyParams());
    $("bodyParamsList").classList.add("hidden");
    $("bodyParamsKvLabels").classList.add("hidden");
    $("addBodyParamBtn").classList.add("hidden");
    $("bodyParamsBulkEditor").classList.remove("hidden");
    $("bulkEditBodyParamsBtn").textContent = "Done";
  }
}

// --- body mode ---

function syncBodyModeVisibility() {
  const mode = $("bodyModeSelect").value;
  $("bodyRawSection").classList.toggle("hidden", mode !== "raw");
  $("bodyUrlencodedSection").classList.toggle("hidden", mode !== "urlencoded");
}

document.addEventListener("DOMContentLoaded", () => {
  $("addBodyParamBtn").addEventListener("click", () => { addBodyParamRow(); markActiveTabDirty(); });
  $("bulkEditBodyParamsBtn").addEventListener("click", toggleBodyParamsBulkEdit);
  $("bodyModeSelect").addEventListener("change", () => { syncBodyModeVisibility(); markActiveTabDirty(); });
});

if (typeof module !== "undefined" && module.exports) {
  module.exports = { renderBodyParamRows, collectBodyParams, collectAllBodyParams, bodyParamsToBulkText, bulkTextToBodyParams, syncBodyModeVisibility };
}
